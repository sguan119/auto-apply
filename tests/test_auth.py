"""tests.test_auth —— core.deliver.auth.Authenticator 测试。

登录路径需要真实 DOM/Playwright 行为（`_fill_login_fields`/`_click_submit`
靠 `dom.collect_page()` + `apply_action()`），走真实 headless chromium（同
test_engine.py 套路）。注册路径用一个脚本化的假 `FillEngine`（只需要
`.run_form()`/`.bio_store`/`.question_channel` 三个协作点，不必是真实
`FillEngine` 实例）。凭据落库用临时 SQLite（`monkeypatch` 覆盖
`core.storage.db.DEFAULT_DB_PATH`，不碰真实 `data/app.db`，也不需要给
`repository.*` 调用一路多传 `db_path`——Authenticator 本身就不接受这个参数,
覆盖默认路径是唯一能隔离测试的手段）。
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from autoapply.core.config import DeliverSettings, Settings
from autoapply.core.contracts import Answer, FieldValueSource, FilledField, JobRef, Question
from autoapply.core.deliver.auth import Authenticator, generate_password
from autoapply.core.deliver.engine import RunFormResult
from autoapply.core.storage import db, repository


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------


class InMemoryBioStore:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def read_path(self, field_path: str) -> Any | None:
        node: Any = self.data
        for part in field_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def write_path(self, field_path: str, value: Any, question: str | None = None) -> None:
        parts = field_path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


class FakeEngine:
    """脚本化的假 `FillEngine`：`run_form()` 按调用顺序回放预先编排好的
    `RunFormResult`。Authenticator 只依赖 `.bio_store`/`.question_channel`/
    `.run_form()` 三个协作点，不需要一个真实 `FillEngine`。"""

    def __init__(self, results: list[RunFormResult]) -> None:
        self._results = list(results)
        self.bio_store = InMemoryBioStore()
        self.question_channel = object()  # 哨兵：Authenticator 只存取/还原它
        self.run_form_calls: list[tuple[JobRef, str | None]] = []

    def run_form(self, job: JobRef, *, page_hint: str | None = None, max_pages=None):
        self.run_form_calls.append((job, page_hint))
        if not self._results:
            raise AssertionError("FakeEngine 脚本已耗尽，但又被调用了一次")
        return self._results.pop(0)


class FakeBrowserSession:
    """镜像 `BrowserSession` 用到的接口子集（`.page`/`.goto()`）。"""

    def __init__(self, page) -> None:
        self._page = page
        self.goto_calls: list[str] = []

    @property
    def page(self):
        return self._page

    def goto(self, url: str, **kwargs):
        self.goto_calls.append(url)
        return self._page


class FakeEmailVerifier:
    def __init__(self, *, code: str | None = None, link: str | None = None) -> None:
        self.code = code
        self.link = link
        self.fetch_code_calls: list[dict] = []
        self.fetch_link_calls: list[dict] = []

    def fetch_code(self, **kwargs):
        self.fetch_code_calls.append(kwargs)
        return self.code

    def fetch_link(self, **kwargs):
        self.fetch_link_calls.append(kwargs)
        return self.link


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


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    # repository.* 的默认 db_path 兜底到 core.storage.db.DEFAULT_DB_PATH；
    # Authenticator 调用 repository 时不传 db_path，覆盖这个模块级常量是
    # 隔离测试与真实 data/app.db 的唯一手段。
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "app.db")
    yield


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
    return Settings(deliver=DeliverSettings(**deliver_overrides))


# ----------------------------------------------------------------------
# (a) 有凭据 → 登录路径
# ----------------------------------------------------------------------


class TestLoginPath:
    def test_existing_credential_fills_and_submits_login_form(self, page, job):
        repository.upsert_credential(
            "workday", "acme-portal", username="alice@example.com", password="Secret123!"
        )
        page.set_content(
            """
            <input type="email" name="email">
            <input type="password" name="password">
            <button type="button" onclick="this.dataset.clicked='1'">Log In</button>
            """
        )
        engine = FakeEngine([])
        browser = FakeBrowserSession(page)
        auth = Authenticator(browser, engine, make_settings())

        result = auth.authenticate(job, "acme-portal")

        assert result.outcome == "authenticated"
        assert page.locator('[name="email"]').input_value() == "alice@example.com"
        assert page.locator('[name="password"]').input_value() == "Secret123!"
        assert page.locator("button").get_attribute("data-clicked") == "1"
        # 登录不该复用整页 LLM 循环
        assert engine.run_form_calls == []
        # 审计记录里密码不落明文
        password_field = next(f for f in result.filled_fields if f.value != "alice@example.com")
        assert password_field.value == "********"


# ----------------------------------------------------------------------
# (b) 无凭据 → 注册路径，复用 engine.run_form()
# ----------------------------------------------------------------------


class TestRegisterPath:
    def test_no_credential_registers_and_stores_credential(self, page, job):
        page.set_content("<div>signup landing</div>")
        result = RunFormResult(
            outcome="completed",
            filled_fields=[
                FilledField(question="Email", value="alice@acme-portal.com", value_source=FieldValueSource.BIO)
            ],
            pages_completed=1,
        )
        engine = FakeEngine([result])
        browser = FakeBrowserSession(page)
        auth = Authenticator(browser, engine, make_settings())

        assert repository.get_credential("workday", "acme-portal") is None

        auth_result = auth.authenticate(job, "acme-portal")

        assert auth_result.outcome == "authenticated"
        assert engine.run_form_calls == [(job, "注册")]

        credential = repository.get_credential("workday", "acme-portal")
        assert credential is not None
        assert credential.email == "alice@acme-portal.com"
        assert credential.password  # 生成过密码

        # 密码在调用 run_form() 前已经预写进 bio_store 的约定路径，供
        # engine 的 LLM+DOM 循环直接当已知值填上，不触发 needs_user。
        assert engine.bio_store.read_path("form_answers.password") == credential.password

    def test_generated_password_is_masked_in_filled_fields(self, page, job):
        """engine 复用 FILLING 循环填注册表单时会把密码字段（BIO 来源）记进
        filled_fields——auth 必须在返回前把等于生成密码的填值遮罩，避免明文
        密码随 runner 落进 DeliveryRecord/run log。用 template 模式拿到确定的
        密码，模拟 engine 回填这个明文值。"""
        page.set_content("<div>signup landing</div>")
        fixed_password = "FixedPassw0rd!"
        result = RunFormResult(
            outcome="completed",
            filled_fields=[
                FilledField(question="Email", value="bob@acme-portal.com", value_source=FieldValueSource.BIO),
                FilledField(question="Password", value=fixed_password, value_source=FieldValueSource.BIO),
            ],
            pages_completed=1,
        )
        engine = FakeEngine([result])
        browser = FakeBrowserSession(page)
        settings = make_settings(
            password_generation_mode="template", password_template=fixed_password
        )
        auth = Authenticator(browser, engine, settings)

        auth_result = auth.authenticate(job, "acme-portal")

        assert auth_result.outcome == "authenticated"
        # filled_fields 里绝不出现明文密码
        values = [f.value for f in auth_result.filled_fields]
        assert fixed_password not in values
        password_field = next(f for f in auth_result.filled_fields if f.question == "Password")
        assert password_field.value == "********"
        # 但凭据表里仍按 PRD 六存明文
        credential = repository.get_credential("workday", "acme-portal")
        assert credential.password == fixed_password

    def test_verification_question_falls_through_when_no_email_code(self, page, job):
        """邮件迟迟不到（fetch_code 返回 None）时，验证码问题必须原样转发给真正
        的问询通道，绝不能给引擎喂一个空/None 的答案。"""
        from autoapply.core.questions.channel import QuestionChannel

        page.set_content("<div>signup landing</div>")
        received: dict[str, Any] = {}

        class RecordingChannel(QuestionChannel):
            def ask(self, questions, timeout):
                received["questions"] = questions
                return [Answer(question=q, answer="typed-by-user") for q in questions]

        class ProbingEngine(FakeEngine):
            def run_form(self, job, *, page_hint=None, max_pages=None):
                question = Question(job=job, field_path=None, question="Enter verification code")
                answers = self.question_channel.ask([question], 5.0)
                received["answers"] = answers
                return super().run_form(job, page_hint=page_hint, max_pages=max_pages)

        engine = ProbingEngine([RunFormResult(outcome="completed", filled_fields=[], pages_completed=1)])
        engine.question_channel = RecordingChannel()
        browser = FakeBrowserSession(page)
        email_verifier = FakeEmailVerifier(code=None)  # 邮件永远没到
        auth = Authenticator(browser, engine, make_settings(), email_verifier=email_verifier)

        auth.authenticate(job, "acme-portal")

        # 问题被转发给了真人通道（不是被静默丢弃或答成空）
        assert len(received["questions"]) == 1
        assert received["answers"][0].answer == "typed-by-user"
        assert email_verifier.fetch_code_calls  # 确实先尝试过邮箱

    def test_registration_uses_email_verifier_for_verification_code_questions(self, page, job):
        """引擎在 FILLING 过程中把一个「验证码」问题抛给 question_channel——
        _EmailVerifyingChannel 应该拦下来，用 EmailVerifier 自动作答，不转发
        给真正的（本测试里会直接超时的）底层通道。"""
        from autoapply.core.questions.channel import TIMEOUT, QuestionChannel

        class TimeoutChannel(QuestionChannel):
            def ask(self, questions, timeout):
                return TIMEOUT  # 任何真的转发过来的问题都会在这里超时

        page.set_content("<div>signup landing</div>")

        captured: dict[str, Any] = {}

        class ProbingEngine(FakeEngine):
            def run_form(self, job, *, page_hint=None, max_pages=None):
                # 模拟 engine 内部在 FILLING 过程中被 needs_user 命中后调用
                # question_channel.ask()——这一步真实 engine 会自己做，这里
                # 直接调用 Authenticator 换上的那个 channel 验证行为。
                question = Question(job=job, field_path=None, question="Enter verification code")
                answers = self.question_channel.ask([question], 5.0)
                captured["answers"] = answers
                return super().run_form(job, page_hint=page_hint, max_pages=max_pages)

        result = RunFormResult(outcome="completed", filled_fields=[], pages_completed=1)
        engine = ProbingEngine([result])
        engine.question_channel = TimeoutChannel()
        browser = FakeBrowserSession(page)
        email_verifier = FakeEmailVerifier(code="775533")
        auth = Authenticator(browser, engine, make_settings(), email_verifier=email_verifier)

        auth_result = auth.authenticate(job, "acme-portal")

        assert auth_result.outcome == "authenticated"
        answers = captured["answers"]
        assert answers != TIMEOUT
        assert answers[0].answer == "775533"
        assert email_verifier.fetch_code_calls  # 确认真的调用了邮箱取回
        # run_form() 返回后 channel 必须换回原来的 TimeoutChannel，不泄漏包装
        assert isinstance(engine.question_channel, TimeoutChannel)


# ----------------------------------------------------------------------
# (c) 验证码求解失败 → AuthResult failed("captcha_unsolved")
# ----------------------------------------------------------------------


class TestCaptchaFailure:
    def test_unsolved_captcha_short_circuits_before_engine_call(self, page, job):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        engine = FakeEngine([RunFormResult(outcome="completed")])
        browser = FakeBrowserSession(page)
        # 默认 Settings() 没配 CAPSOLVER_API_KEY → 验证码求解优雅失败
        auth = Authenticator(browser, engine, Settings())

        result = auth.authenticate(job, "acme-portal")

        assert result.outcome == "failed"
        assert result.reason == "captcha_unsolved"
        assert engine.run_form_calls == []  # 验证码卡在前面，根本没进到注册表单


# ----------------------------------------------------------------------
# (d) 注册中途挂起 → AuthResult suspended，pending_questions 透传
# ----------------------------------------------------------------------


class TestRegistrationSuspended:
    def test_suspended_run_form_propagates_pending_questions(self, page, job):
        page.set_content("<div>signup landing</div>")
        question = Question(job=job, field_path="form_answers.visa", question="Need visa sponsorship?")
        result = RunFormResult(
            outcome="suspended",
            filled_fields=[FilledField(question="Name", value="Alice", value_source=FieldValueSource.BIO)],
            pending_questions=[question],
        )
        engine = FakeEngine([result])
        browser = FakeBrowserSession(page)
        auth = Authenticator(browser, engine, make_settings())

        auth_result = auth.authenticate(job, "acme-portal")

        assert auth_result.outcome == "suspended"
        assert auth_result.pending_questions == [question]
        assert len(auth_result.filled_fields) == 1
        # 挂起时不落凭据（还没注册成功）
        assert repository.get_credential("workday", "acme-portal") is None

    def test_failed_run_form_propagates_failure_reason(self, page, job):
        page.set_content("<div>signup landing</div>")
        result = RunFormResult(outcome="failed", failure_reason="llm_decision_error: boom")
        engine = FakeEngine([result])
        browser = FakeBrowserSession(page)
        auth = Authenticator(browser, engine, make_settings())

        auth_result = auth.authenticate(job, "acme-portal")

        assert auth_result.outcome == "failed"
        assert auth_result.reason == "llm_decision_error: boom"


# ----------------------------------------------------------------------
# (e) generate_password：random / template 两种模式
# ----------------------------------------------------------------------


class TestGeneratePassword:
    def test_random_mode_meets_length_and_char_class_policy(self):
        settings = make_settings(password_generation_mode="random")
        password = generate_password(settings)

        assert len(password) == 16
        assert any(c.islower() for c in password)
        assert any(c.isupper() for c in password)
        assert any(c.isdigit() for c in password)
        assert any(c in "!@#$%^&*" for c in password)

    def test_random_mode_generates_distinct_passwords(self):
        settings = make_settings(password_generation_mode="random")
        passwords = {generate_password(settings) for _ in range(20)}
        assert len(passwords) == 20  # 实际碰撞概率可忽略不计

    def test_template_mode_fills_rand_placeholder(self):
        settings = make_settings(
            password_generation_mode="template", password_template="Deliver{rand}!2026"
        )
        password = generate_password(settings)

        assert password.startswith("Deliver")
        assert password.endswith("!2026")
        assert password != "Deliver{rand}!2026"

    def test_template_mode_without_placeholder_returns_literal(self):
        settings = make_settings(
            password_generation_mode="template", password_template="FixedPassw0rd!"
        )
        assert generate_password(settings) == "FixedPassw0rd!"

    def test_unknown_mode_falls_back_to_random(self):
        settings = make_settings(password_generation_mode="not-a-real-mode")
        password = generate_password(settings)
        assert len(password) == 16
