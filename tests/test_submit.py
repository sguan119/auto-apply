"""tests.test_submit —— core.deliver.submit.confirm_and_submit / is_confirmation_page 测试。

不打真实 Workday/网络：走真实 headless chromium（同 test_engine.py 套路），用
`page.set_content()` 灌表单/确认页 fixture；`QuestionChannel` 用脚本化假实现
（不经终端 `input()`）。
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from core.config import Settings
from core.contracts import Answer, JobRef, Question
from core.deliver.adapters.base import PlatformAdapter
from core.deliver.submit import SubmitResult, confirm_and_submit, is_confirmation_page
from core.questions.channel import TIMEOUT, QuestionChannel


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------


class ScriptedConfirmChannel(QuestionChannel):
    """脚本化问询通道：`ask()` 只用于本模块的「是否确认提交」单条 yes/no 问题，
    按预设的 `answer_text`（`"y"`/`"n"`）或直接超时来回放。"""

    def __init__(self, answer_text: str | None = None, *, timeout: bool = False) -> None:
        self._answer_text = answer_text
        self._timeout = timeout
        self.ask_calls: list[list[Question]] = []

    def ask(self, questions: list[Question], timeout: float):
        self.ask_calls.append(questions)
        if self._timeout:
            return TIMEOUT
        return [Answer(question=q, answer=self._answer_text) for q in questions]


class FixedHintAdapter(PlatformAdapter):
    """只覆盖 `confirmation_hint()` 的最小假适配器，其余抽象方法给桩实现
    （本模块的测试不会调用到它们）。"""

    def __init__(self, hint: bool | None) -> None:
        self._hint = hint

    def matches(self, url: str) -> bool:
        return True

    def portal_id(self, job: JobRef) -> str:
        return "fixed"

    def needs_auth(self, page) -> bool:
        return False

    def open_application(self, browser, job, settings, run_logger=None):
        raise NotImplementedError

    def confirmation_hint(self, page) -> bool | None:
        return self._hint


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture()
def job() -> JobRef:
    return JobRef(
        platform="workday",
        job_id="job-1",
        url="https://acme.wd1.myworkdayjobs.com/jobs/1",
        title="Software Engineer",
        company="Acme",
        score=0.9,
    )


def make_settings(**deliver_overrides) -> Settings:
    from core.config import DeliverSettings

    return Settings(deliver=DeliverSettings(**deliver_overrides))


_CONFIRMATION_HTML = "<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>"
_SUBMIT_FORM_HTML = """
<form>
    <button onclick="document.body.innerHTML = '{confirmation}'">Submit Application</button>
</form>
""".format(confirmation=_CONFIRMATION_HTML)


# ----------------------------------------------------------------------
# 手动模式：confirm=True / False / TIMEOUT
# ----------------------------------------------------------------------


class TestManualModeConfirmation:
    def test_confirm_true_proceeds_to_submit_and_succeeds(self, page, job):
        page.set_content(_SUBMIT_FORM_HTML)
        channel = ScriptedConfirmChannel(answer_text="y")

        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=make_settings()
        )

        assert result == SubmitResult(outcome="succeeded")
        assert len(channel.ask_calls) == 1

    def test_confirm_false_declines_without_submitting(self, page, job):
        page.set_content(_SUBMIT_FORM_HTML)
        channel = ScriptedConfirmChannel(answer_text="n")

        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=make_settings()
        )

        assert result.outcome == "declined"
        assert result.reason == "user_declined_submit"
        # 没有真的点提交——页面内容应保持原样（按钮还在，确认页文案不存在）
        assert "Thank you for applying" not in (page.inner_text("body") or "")

    def test_confirm_timeout_suspends_without_submitting(self, page, job):
        page.set_content(_SUBMIT_FORM_HTML)
        channel = ScriptedConfirmChannel(timeout=True)

        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=make_settings()
        )

        assert result.outcome == "suspended"
        assert result.reason == "submit_confirmation_timeout"
        assert "Thank you for applying" not in (page.inner_text("body") or "")


# ----------------------------------------------------------------------
# 自动模式：不问询，直接提交
# ----------------------------------------------------------------------


class TestAutoMode:
    def test_auto_mode_submits_without_asking(self, page, job):
        page.set_content(_SUBMIT_FORM_HTML)

        class ExplodingChannel(QuestionChannel):
            def ask(self, questions, timeout):
                raise AssertionError("auto 模式不应该调用 question_channel.ask()")

        result = confirm_and_submit(
            page, job, mode="auto", question_channel=ExplodingChannel(), settings=make_settings()
        )

        assert result == SubmitResult(outcome="succeeded")


# ----------------------------------------------------------------------
# is_confirmation_page()：通用文本启发式 + adapter.confirmation_hint() 优先级
# ----------------------------------------------------------------------


class TestIsConfirmationPage:
    def test_true_on_confirmation_text(self, page):
        page.set_content(_CONFIRMATION_HTML)
        assert is_confirmation_page(page) is True

    def test_false_on_still_on_form(self, page):
        page.set_content("<form><input name='email'><button>Submit</button></form>")
        assert is_confirmation_page(page) is False

    def test_adapter_hint_true_overrides_generic_text(self, page):
        page.set_content("<div>ambiguous content with no generic markers</div>")
        assert is_confirmation_page(page, adapter=FixedHintAdapter(True)) is True

    def test_adapter_hint_false_overrides_generic_text(self, page):
        page.set_content(_CONFIRMATION_HTML)  # 通用文本本会判 True
        assert is_confirmation_page(page, adapter=FixedHintAdapter(False)) is False

    def test_adapter_no_opinion_falls_back_to_generic_text(self, page):
        page.set_content(_CONFIRMATION_HTML)
        assert is_confirmation_page(page, adapter=FixedHintAdapter(None)) is True

    def test_generic_still_on_form_marker_beats_coincidental_positive(self, page):
        # 回归：无 adapter 时的通用启发式，正向关键词与「还在表单上」措辞同页
        # 共存必须判 False——绝不因巧合子串把仍在表单/出错的页面误报成 SUCCEEDED
        # （PRD 八下会永不重投、静默丢失投递）。
        page.set_content(
            "<h1>Your application has been submitted</h1>"
            "<div class='error'>There was a problem. Please complete all required fields.</div>"
            "<button>Submit Application</button>"
        )
        assert is_confirmation_page(page) is False

    def test_generic_review_page_is_not_confirmation(self, page):
        # 复核页（含 Submit 按钮、无正向关键词）→ 通用启发式判 False。
        page.set_content(
            "<h1>Review your application</h1><button>Submit Application</button>"
        )
        assert is_confirmation_page(page) is False


# ----------------------------------------------------------------------
# 提交后未识别到确认页 → failed
# ----------------------------------------------------------------------


class TestConfirmationNotDetected:
    def test_submit_click_that_stays_on_form_fails(self, page, job, monkeypatch):
        # 提交按钮点击后页面没有变化（没有确认页信号）——应判 failed，
        # 不应无限等待（缩短轮询预算，测试不用真的等 30 秒）。
        import core.deliver.submit as submit_module

        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_TIMEOUT", 1.0)
        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_INTERVAL", 0.1)

        page.set_content("<form><button>Submit Application</button></form>")
        channel = ScriptedConfirmChannel(answer_text="y")

        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=make_settings()
        )

        assert result.outcome == "failed"
        assert result.reason == "confirmation_page_not_detected"

    def test_submit_button_not_found_fails(self, page, job):
        page.set_content("<div>no submit button anywhere</div>")
        channel = ScriptedConfirmChannel(answer_text="y")

        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=make_settings()
        )

        assert result.outcome == "failed"
        assert result.reason == "submit_button_not_found"


# ----------------------------------------------------------------------
# 验证码求解失败 → failed("captcha_unsolved")
# ----------------------------------------------------------------------


class TestCaptchaCheckpoint:
    def test_unsolved_captcha_short_circuits_before_submit_click(self, page, job):
        page.set_content(
            '<div class="h-captcha" data-sitekey="sk"></div>'
            '<button>Submit Application</button>'
        )
        channel = ScriptedConfirmChannel(answer_text="y")
        # 默认 Settings() 没配 CAPSOLVER_API_KEY → 验证码求解优雅失败
        result = confirm_and_submit(
            page, job, mode="manual", question_channel=channel, settings=Settings()
        )

        assert result.outcome == "failed"
        assert result.reason == "captcha_unsolved"


# ----------------------------------------------------------------------
# PlatformAdapter.login_succeeded() 默认实现（base ABC 契约，供阶段 8 统一调用）
# ----------------------------------------------------------------------


class TestBaseLoginSucceededDefault:
    def test_base_default_returns_true(self):
        # 不覆盖 login_succeeded 的适配器（FixedHintAdapter）继承 ABC 默认——
        # 默认信任 authenticate 的乐观结果，返回 True；阶段 8 可对任意
        # PlatformAdapter 统一调用，无需 hasattr/类型转换。
        adapter = FixedHintAdapter(None)
        assert adapter.login_succeeded(object(), pre_auth_url="https://x") is True
