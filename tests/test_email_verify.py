"""tests.test_email_verify —— core.deliver.email_verify.EmailVerifier 测试。

用一个假 IMAP 对象（记录方法调用、按脚本返回消息）替代真实 `imaplib.IMAP4`——
不连真实邮箱。核心断言：
- `select()` 总是带 `readonly=True`（EXAMINE，只读承诺的关键一行）；
- `fetch()` 总是用 `(BODY.PEEK[])`，从不用会隐式打 `\\Seen` 的 `(RFC822)`；
- 全程不调用任何会改状态的方法（`store`/`expunge`/`copy` 等一律不存在于假
  对象上——真调用了会因为 `AttributeError` 直接让测试失败，天然的断言）。
"""

from __future__ import annotations

import time
from email.message import EmailMessage

import pytest

from core.config import ImapSettings, Settings
from core.deliver.email_verify import EmailVerifier


def make_email_bytes(*, subject: str, sender: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "candidate@example.com"
    msg.set_content(body)
    return bytes(msg)


class FakeImap:
    """假 IMAP4：`messages` 是脚本化的 (subject, sender, body) 列表；
    `search_results` 控制每次 `search()` 返回哪些 id（用于模拟「邮件还没到，
    轮询几次后才出现」）。故意不实现 `store`/`expunge`——真被调用会
    `AttributeError`，等价于断言「read-only 期间没有写操作」。
    """

    def __init__(self, messages: list[tuple[str, str, str]]) -> None:
        self._messages = {
            str(i + 1).encode(): make_email_bytes(subject=s, sender=f_, body=b)
            for i, (s, f_, b) in enumerate(messages)
        }
        self.select_calls: list[tuple[str, bool]] = []
        self.search_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        # 每次 search() 调用弹出一个「本轮可见 id 列表」；耗尽后固定用最后一个。
        self._search_script: list[list[bytes]] = [list(self._messages.keys())]

    def select(self, mailbox, readonly=False):
        self.select_calls.append((mailbox, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.search_calls.append(criteria)
        if len(self._search_script) > 1:
            ids = self._search_script.pop(0)
        else:
            ids = self._search_script[0]
        return "OK", [b" ".join(ids)]

    def fetch(self, msg_id, parts):
        self.fetch_calls.append((msg_id, parts))
        raw = self._messages.get(msg_id)
        if raw is None:
            return "NO", [None]
        return "OK", [(msg_id, raw)]

    def close(self):
        pass

    def logout(self):
        pass

    def set_delayed_arrival(self, delayed_ids: list[bytes], immediate_ids: list[bytes]) -> None:
        """模拟「第一次轮询看不到邮件，之后才出现」：先返回 immediate_ids，
        后续调用返回 immediate_ids + delayed_ids。"""
        self._search_script = [immediate_ids, immediate_ids + delayed_ids]


def make_settings(**imap_overrides) -> Settings:
    return Settings(imap=ImapSettings(**imap_overrides))


# ----------------------------------------------------------------------
# 只读承诺
# ----------------------------------------------------------------------


class TestReadOnlyGuarantee:
    def test_select_uses_readonly_true(self):
        fake = FakeImap([("code", "noreply@ats.com", "your code is 4821")])
        verifier = EmailVerifier(make_settings(mailbox="INBOX"), imap_factory=lambda s: fake)

        verifier.fetch_code(timeout=0.05, poll_interval=0.01)

        assert fake.select_calls == [("INBOX", True)]

    def test_fetch_uses_body_peek_not_rfc822(self):
        fake = FakeImap([("code", "noreply@ats.com", "your code is 4821")])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        verifier.fetch_code(timeout=0.05, poll_interval=0.01)

        assert fake.fetch_calls
        for _, parts in fake.fetch_calls:
            assert parts == "(BODY.PEEK[])"

    def test_no_write_methods_exist_on_fake(self):
        # store/expunge/copy 压根没在 FakeImap 上定义——真实代码若不慎调用会
        # AttributeError；这里直接断言它们不存在，把"只读"钉死成结构性事实。
        fake = FakeImap([])
        for forbidden in ("store", "expunge", "copy", "uid"):
            assert not hasattr(fake, forbidden)


# ----------------------------------------------------------------------
# fetch_code
# ----------------------------------------------------------------------


class TestFetchCode:
    def test_extracts_numeric_code_from_body(self):
        fake = FakeImap([("Your verification code", "noreply@ats.com", "Your code is 482913. Expires in 10 min.")])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        code = verifier.fetch_code(timeout=0.1, poll_interval=0.01)

        assert code == "482913"

    def test_returns_none_on_timeout_when_no_mail(self):
        fake = FakeImap([])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        started = time.monotonic()
        code = verifier.fetch_code(timeout=0.1, poll_interval=0.02)
        elapsed = time.monotonic() - started

        assert code is None
        assert elapsed < 1.0  # 确认真的按 timeout 退出，没有卡死

    def test_polls_until_delayed_mail_arrives(self):
        fake = FakeImap([("code", "noreply@ats.com", "verification code: 991122")])
        all_ids = list(fake._messages.keys())
        fake.set_delayed_arrival(delayed_ids=all_ids, immediate_ids=[])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        code = verifier.fetch_code(timeout=1.0, poll_interval=0.02)

        assert code == "991122"
        assert len(fake.search_calls) >= 2  # 第一次没查到，至少轮询了第二次

    def test_sender_and_subject_filters_forwarded_to_search(self):
        fake = FakeImap([("Verify", "noreply@workday.com", "code 1234")])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        verifier.fetch_code(
            sender_filter="noreply@workday.com",
            subject_filter="Verify",
            timeout=0.05,
            poll_interval=0.01,
        )

        criteria = fake.search_calls[0]
        assert "FROM" in criteria
        assert '"noreply@workday.com"' in criteria
        assert "SUBJECT" in criteria
        assert '"Verify"' in criteria


# ----------------------------------------------------------------------
# fetch_link
# ----------------------------------------------------------------------


class TestFetchLink:
    def test_extracts_verification_link_from_body(self):
        body = "Please verify your account: https://portal.example.com/verify?token=abc123 Thanks."
        fake = FakeImap([("Verify your account", "noreply@ats.com", body)])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        link = verifier.fetch_link(timeout=0.1, poll_interval=0.01)

        assert link == "https://portal.example.com/verify?token=abc123"

    def test_returns_none_on_timeout(self):
        fake = FakeImap([("hello", "someone@example.com", "no link here")])
        verifier = EmailVerifier(make_settings(), imap_factory=lambda s: fake)

        link = verifier.fetch_link(timeout=0.05, poll_interval=0.01)

        assert link is None
