"""tests.test_captcha —— core.deliver.captcha 测试。

`detect_captcha`/`inject_solution` 用真实 chromium（`page.set_content()` 灌入
挂件 DOM fixture，同 test_engine.py 的套路）——只用静态 DOM 标记，不加载任何
远程脚本，杜绝真实网络请求。`solve_captcha`/`handle_captcha_if_present` 用一个
假 CapSolver HTTP 客户端（脚本化 createTask→getTaskResult 序列），同样不打
真实网络。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from autoapply.core.config import CapsolverSettings, Settings
from autoapply.core.deliver.captcha import (
    CaptchaChallenge,
    CaptchaSolveError,
    CaptchaUnconfigured,
    detect_captcha,
    handle_captcha_if_present,
    inject_solution,
    solve_captcha,
)


# ----------------------------------------------------------------------
# 测试替身：假 CapSolver HTTP 客户端
# ----------------------------------------------------------------------


class FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return self._data


class FakeCapSolverClient:
    """脚本化 createTask → getTaskResult 序列：前 `ready_after - 1` 次
    `getTaskResult` 回 `processing`，第 `ready_after` 次回 `ready` 带 token。
    `fail_create`/`fail_forever` 用于模拟 createTask 报错 / 永远求解不成功。
    """

    def __init__(
        self,
        *,
        ready_after: int = 1,
        solution_token: str = "TOKEN123",
        fail_create: bool = False,
        fail_forever: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._get_result_calls = 0
        self._ready_after = ready_after
        self._solution_token = solution_token
        self._fail_create = fail_create
        self._fail_forever = fail_forever

    def post(self, url: str, json: dict | None = None, **kwargs) -> FakeResponse:
        self.calls.append((url, json or {}))
        if url.endswith("/createTask"):
            if self._fail_create:
                return FakeResponse({"errorId": 1, "errorDescription": "boom"})
            return FakeResponse({"errorId": 0, "taskId": "task-1"})
        if url.endswith("/getTaskResult"):
            self._get_result_calls += 1
            if self._fail_forever or self._get_result_calls < self._ready_after:
                return FakeResponse({"errorId": 0, "status": "processing"})
            return FakeResponse(
                {
                    "errorId": 0,
                    "status": "ready",
                    "solution": {"gRecaptchaResponse": self._solution_token},
                }
            )
        raise AssertionError(f"unexpected CapSolver url: {url}")

    def close(self) -> None:
        pass


def settings_with_key(**overrides) -> Settings:
    return Settings(capsolver=CapsolverSettings(api_key="test-capsolver-key", **overrides))


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


# ----------------------------------------------------------------------
# detect_captcha
# ----------------------------------------------------------------------


class TestDetectCaptcha:
    def test_no_captcha_returns_none(self, page):
        page.set_content('<input name="full_name" type="text">')
        assert detect_captcha(page) is None

    def test_detects_hcaptcha(self, page):
        page.set_content('<div class="h-captcha" data-sitekey="hc-key-1"></div>')
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "hcaptcha"
        assert challenge.sitekey == "hc-key-1"

    def test_detects_recaptcha_v2(self, page):
        page.set_content('<div class="g-recaptcha" data-sitekey="rc-key-1"></div>')
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "recaptcha_v2"
        assert challenge.sitekey == "rc-key-1"

    def test_detects_recaptcha_v3_from_inline_script(self, page):
        page.set_content(
            "<script>grecaptcha.execute('rc-v3-key', {action: 'submit'});</script>"
        )
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "recaptcha_v3"
        assert challenge.sitekey == "rc-v3-key"

    def test_detects_turnstile(self, page):
        page.set_content('<div class="cf-turnstile" data-sitekey="ts-key-1"></div>')
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "turnstile"
        assert challenge.sitekey == "ts-key-1"

    def test_detects_funcaptcha(self, page):
        page.set_content('<div id="FunCaptcha" data-pkey="fc-key-1"></div>')
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "funcaptcha"
        assert challenge.sitekey == "fc-key-1"

    def test_hcaptcha_checked_before_recaptcha(self, page):
        page.set_content(
            '<div class="g-recaptcha" data-sitekey="rc-key"></div>'
            '<div class="h-captcha" data-sitekey="hc-key"></div>'
        )
        challenge = detect_captcha(page)
        assert challenge is not None
        assert challenge.type == "hcaptcha"
        assert challenge.sitekey == "hc-key"


# ----------------------------------------------------------------------
# solve_captcha
# ----------------------------------------------------------------------


class TestSolveCaptcha:
    def test_no_api_key_raises_unconfigured(self):
        challenge = CaptchaChallenge(type="hcaptcha", sitekey="sk", url="https://example.com")
        with pytest.raises(CaptchaUnconfigured):
            solve_captcha(challenge, Settings(), http_client=FakeCapSolverClient())

    def test_polls_until_ready_and_returns_token(self):
        challenge = CaptchaChallenge(type="hcaptcha", sitekey="sk", url="https://example.com")
        client = FakeCapSolverClient(ready_after=3, solution_token="TOKEN-XYZ")

        token = solve_captcha(
            challenge,
            settings_with_key(),
            http_client=client,
            poll_interval=0.01,
            poll_timeout=1.0,
        )

        assert token == "TOKEN-XYZ"
        assert client.calls[0][0].endswith("/createTask")
        get_result_calls = [c for c in client.calls if c[0].endswith("/getTaskResult")]
        assert len(get_result_calls) == 3
        # createTask 请求体带上了正确映射的任务类型与 sitekey
        assert client.calls[0][1]["task"]["type"] == "HCaptchaTaskProxyLess"
        assert client.calls[0][1]["task"]["websiteKey"] == "sk"

    def test_funcaptcha_uses_website_public_key_field(self):
        # CapSolver FunCaptchaTaskProxyLess 的 sitekey 字段名是 websitePublicKey，
        # 不是 websiteKey——用错会被 CapSolver 直接拒单。
        challenge = CaptchaChallenge(type="funcaptcha", sitekey="fc-sk", url="https://example.com")
        client = FakeCapSolverClient(ready_after=1)

        solve_captcha(challenge, settings_with_key(), http_client=client, poll_interval=0.01)

        task = client.calls[0][1]["task"]
        assert task["type"] == "FunCaptchaTaskProxyLess"
        assert task["websitePublicKey"] == "fc-sk"
        assert "websiteKey" not in task

    def test_create_task_error_raises_solve_error(self):
        challenge = CaptchaChallenge(type="recaptcha_v2", sitekey="sk", url="https://example.com")
        client = FakeCapSolverClient(fail_create=True)
        with pytest.raises(CaptchaSolveError):
            solve_captcha(challenge, settings_with_key(), http_client=client, poll_interval=0.01)

    def test_poll_timeout_raises_solve_error(self):
        challenge = CaptchaChallenge(type="turnstile", sitekey="sk", url="https://example.com")
        client = FakeCapSolverClient(fail_forever=True)
        with pytest.raises(CaptchaSolveError):
            solve_captcha(
                challenge,
                settings_with_key(),
                http_client=client,
                poll_interval=0.01,
                poll_timeout=0.03,
            )


# ----------------------------------------------------------------------
# inject_solution
# ----------------------------------------------------------------------


class TestInjectSolution:
    def test_injects_hcaptcha_response_field(self, page):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        challenge = CaptchaChallenge(type="hcaptcha", sitekey="sk", url=page.url)
        inject_solution(page, challenge, "TOKEN-A")
        assert page.locator('textarea[name="h-captcha-response"]').input_value() == "TOKEN-A"

    def test_injects_recaptcha_response_field(self, page):
        page.set_content('<div class="g-recaptcha" data-sitekey="sk"></div>')
        challenge = CaptchaChallenge(type="recaptcha_v2", sitekey="sk", url=page.url)
        inject_solution(page, challenge, "TOKEN-B")
        assert page.locator('textarea[name="g-recaptcha-response"]').input_value() == "TOKEN-B"

    def test_injects_turnstile_response_field(self, page):
        page.set_content('<div class="cf-turnstile" data-sitekey="sk"></div>')
        challenge = CaptchaChallenge(type="turnstile", sitekey="sk", url=page.url)
        inject_solution(page, challenge, "TOKEN-C")
        assert page.locator('textarea[name="cf-turnstile-response"]').input_value() == "TOKEN-C"

    def test_fires_data_callback(self, page):
        page.set_content(
            """
            <div class="h-captcha" data-sitekey="sk" data-callback="onSolved"></div>
            <script>window.onSolved = (token) => { window.__lastToken = token; };</script>
            """
        )
        challenge = CaptchaChallenge(type="hcaptcha", sitekey="sk", url=page.url)
        inject_solution(page, challenge, "TOKEN-D")
        assert page.evaluate("window.__lastToken") == "TOKEN-D"


# ----------------------------------------------------------------------
# handle_captcha_if_present：outcome 映射
# ----------------------------------------------------------------------


class TestHandleCaptchaIfPresent:
    def test_no_captcha_returns_none_outcome(self, page):
        page.set_content('<input name="x" type="text">')
        outcome = handle_captcha_if_present(page, Settings())
        assert outcome == "none"

    def test_solved_and_injected_returns_solved(self, page):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        client = FakeCapSolverClient(ready_after=1, solution_token="TOKEN-SOLVED")
        outcome = handle_captcha_if_present(
            page, settings_with_key(poll_interval=0.01), http_client=client
        )
        assert outcome == "solved"
        assert (
            page.locator('textarea[name="h-captcha-response"]').input_value() == "TOKEN-SOLVED"
        )

    def test_unconfigured_maps_to_failed_without_raising(self, page):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        # 没有配置 api_key：内部会抛 CaptchaUnconfigured，但外部调用方不应看到异常。
        outcome = handle_captcha_if_present(page, Settings())
        assert outcome == "failed"

    def test_solve_failure_maps_to_failed_without_raising(self, page):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        client = FakeCapSolverClient(fail_create=True)
        outcome = handle_captcha_if_present(
            page, settings_with_key(poll_interval=0.01), http_client=client
        )
        assert outcome == "failed"

    def test_logs_each_substep(self, page, tmp_path):
        from autoapply.core.storage.run_log import RunLogger

        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        client = FakeCapSolverClient(ready_after=1)
        logger = RunLogger("test-run", logs_dir=tmp_path)

        handle_captcha_if_present(
            page, settings_with_key(poll_interval=0.01), logger, http_client=client
        )

        content = logger.path.read_text(encoding="utf-8")
        assert "captcha_detected" in content
        assert "captcha_solved" in content
