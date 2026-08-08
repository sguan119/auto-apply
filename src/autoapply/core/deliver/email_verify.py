"""autoapply.core.deliver.email_verify —— IMAP 只读取回注册验证码/验证链接（决策六 / PRD 六）。

**只读是硬约束**：本模块任何路径都不会修改邮箱状态（不打 `\\Seen`、不删除、
不挪动邮件）——`select(mailbox, readonly=True)` 走的是 IMAP `EXAMINE` 命令而
非 `SELECT`，服务端本身就拒绝在这个模式下执行任何状态变更命令；取信内容用
`FETCH ... (BODY.PEEK[])` 而不是 `(RFC822)`，双重保险（`BODY.PEEK[]` 明确
不触发已读标记，即使某些实现在 EXAMINE 模式下的行为不够严格也不会误标）。

**假设**（provider-agnostic，不锁定 Gmail/Outlook 等具体实现）：
- 邮箱已开通 IMAP 访问，`host`/`port`/`mailbox` 走 `config.toml` 的 `[imap]`
  段（spec 决策十非密钥行为参数）。
- 登录走应用专用密码（多数强制 2FA 的邮箱——Gmail 等——要求普通密码无法
  IMAP 登录，需要用户在邮箱设置里单独生成一个），`username`/`password` 走
  环境变量 `IMAP_USERNAME`/`IMAP_PASSWORD`（决策十密钥不进 config.toml）。
- 不支持 OAuth2 token 流（留作 future：`imap_factory` 注入点已经能接一个
  OAuth 版本的 `imaplib.IMAP4` 子类，不需要改这个模块本身）。

**轮询而非一次性查询**：验证邮件发送有延迟（ATS 后端排队、邮件网关中转），
`fetch_code`/`fetch_link` 在 `timeout` 秒内反复 `SEARCH`，命中就立即返回；
超时返回 `None`，由调用方（`auth.py`）决定怎么降级——不在这里抛异常阻塞。
"""

from __future__ import annotations

import email
import imaplib
import re
import time
from datetime import datetime
from email.message import Message
from typing import Callable

from autoapply.core.config import Settings

ImapFactory = Callable[[Settings], "imaplib.IMAP4"]

# 常见验证码形态：4~8 位连续数字，前后是词边界（避免从邮件里的电话号码/
# 日期片段误抓）。这是一个宽松的默认值，调用方可传 `pattern` 覆盖。
_DEFAULT_CODE_PATTERN = re.compile(r"\b(\d{4,8})\b")

# 宽松匹配一条含 "verif"（verify/verification）关键词的 http(s) 链接。
_DEFAULT_LINK_PATTERN = re.compile(r"https?://\S*verif\S*", re.IGNORECASE)


class EmailVerifier:
    """只读 IMAP 连接，轮询取回验证码 (`fetch_code`) 或验证链接 (`fetch_link`)。

    `imap_factory(settings) -> imaplib.IMAP4` 可注入，测试传一个假 IMAP 对象
    （实现 `.select`/`.search`/`.fetch`/`.close`/`.logout`），不连真实邮箱。
    """

    def __init__(self, settings: Settings, *, imap_factory: ImapFactory | None = None) -> None:
        self.settings = settings
        self._imap_factory = imap_factory or _default_imap_factory

    def fetch_code(
        self,
        *,
        since: datetime | None = None,
        sender_filter: str | None = None,
        subject_filter: str | None = None,
        pattern: re.Pattern | None = None,
        timeout: float | None = None,
        poll_interval: float | None = None,
    ) -> str | None:
        """轮询取回一个验证码；超时未见符合条件的邮件返回 `None`。"""
        used_pattern = pattern or _DEFAULT_CODE_PATTERN
        match = self._poll(
            since=since,
            sender_filter=sender_filter,
            subject_filter=subject_filter,
            timeout=timeout,
            poll_interval=poll_interval,
            extract=lambda body: used_pattern.search(body),
        )
        return match.group(1) if match else None

    def fetch_link(
        self,
        *,
        since: datetime | None = None,
        sender_filter: str | None = None,
        subject_filter: str | None = None,
        pattern: re.Pattern | None = None,
        timeout: float | None = None,
        poll_interval: float | None = None,
    ) -> str | None:
        """轮询取回一条验证链接；超时未见符合条件的邮件返回 `None`。"""
        used_pattern = pattern or _DEFAULT_LINK_PATTERN
        match = self._poll(
            since=since,
            sender_filter=sender_filter,
            subject_filter=subject_filter,
            timeout=timeout,
            poll_interval=poll_interval,
            extract=lambda body: used_pattern.search(body),
        )
        return match.group(0) if match else None

    # ------------------------------------------------------------------

    def _connect(self):
        conn = self._imap_factory(self.settings)
        # readonly=True → IMAP EXAMINE，服务端层面拒绝任何状态变更命令，
        # 这是「绝不修改邮箱」承诺的关键一行。
        conn.select(self.settings.imap.mailbox, readonly=True)
        return conn

    def _poll(
        self,
        *,
        since: datetime | None,
        sender_filter: str | None,
        subject_filter: str | None,
        timeout: float | None,
        poll_interval: float | None,
        extract: Callable[[str], re.Match | None],
    ) -> re.Match | None:
        resolved_timeout = timeout if timeout is not None else self.settings.imap.poll_timeout
        resolved_interval = (
            poll_interval if poll_interval is not None else self.settings.imap.poll_interval
        )
        conn = self._connect()
        try:
            deadline = time.monotonic() + resolved_timeout
            while True:
                messages = _search_messages(conn, sender_filter, subject_filter, since)
                # 最新邮件优先：验证邮件多为最近一封，且能更快命中「最新一次
                # 请求」对应的验证码/链接，避免误用同一线程里更早的旧邮件。
                for msg in reversed(messages):
                    found = extract(_extract_body(msg))
                    if found:
                        return found
                if time.monotonic() >= deadline:
                    return None
                time.sleep(resolved_interval)
        finally:
            _safe_logout(conn)


def _default_imap_factory(settings: Settings) -> "imaplib.IMAP4":
    conn = imaplib.IMAP4_SSL(settings.imap.host, settings.imap.port)
    conn.login(settings.imap.username or "", settings.imap.password or "")
    return conn


def _search_messages(
    conn, sender_filter: str | None, subject_filter: str | None, since: datetime | None
) -> list[Message]:
    criteria: list[str] = []
    if sender_filter:
        criteria += ["FROM", f'"{sender_filter}"']
    if subject_filter:
        criteria += ["SUBJECT", f'"{subject_filter}"']
    if since:
        criteria += ["SINCE", since.strftime("%d-%b-%Y")]
    if not criteria:
        criteria = ["ALL"]

    status, data = conn.search(None, *criteria)
    if status != "OK" or not data or not data[0]:
        return []

    messages: list[Message] = []
    for msg_id in data[0].split():
        # BODY.PEEK[]：取整封原始内容但不触发 \Seen（对照 (RFC822) 会隐式已读）。
        status, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        messages.append(email.message_from_bytes(raw))
    return messages


def _extract_body(msg: Message) -> str:
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            if part.get_content_type() not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        return "\n".join(parts)

    payload = msg.get_payload(decode=True)
    if payload is None:
        return msg.get_payload() or ""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")


def _safe_logout(conn) -> None:
    # close()/logout() 失败不该掩盖真正的结果，也不该让调用方多处理一种异常
    # ——收尾操作尽力而为即可。
    try:
        conn.close()
    except Exception:
        pass
    try:
        conn.logout()
    except Exception:
        pass
