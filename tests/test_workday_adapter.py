"""tests.test_workday_adapter —— core.deliver.adapters.workday.WorkdayAdapter 测试。

不打真实 Workday/网络：`matches`/`portal_id` 只操作 URL 字符串，不需要浏览器；
`needs_auth`/`login_succeeded`/`confirmation_hint`/`open_application` 需要真实
DOM 行为（querySelector/文本提取/点击），走真实 headless chromium（同
test_engine.py/test_auth.py 套路），用 `page.set_content()` 灌 Workday 风格 fixture。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from core.config import Settings
from core.contracts import JobRef
from core.deliver.adapters.base import select_adapter
from core.deliver.adapters.workday import WorkdayAdapter


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------


class FakeBrowserSession:
    """镜像 `BrowserSession` 用到的接口子集（`.page`/`.goto()`）。goto() 不做真实
    导航——测试用 `page.set_content()` 预先灌好内容，goto() 只需要返回同一个 page
    （同 test_auth.py 的 FakeBrowserSession）。"""

    def __init__(self, page) -> None:
        self._page = page
        self.goto_calls: list[str] = []

    @property
    def page(self):
        return self._page

    def goto(self, url: str, **kwargs):
        self.goto_calls.append(url)
        return self._page


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
def adapter() -> WorkdayAdapter:
    return WorkdayAdapter()


def make_job(url: str) -> JobRef:
    return JobRef(
        platform="workday",
        job_id="job-1",
        url=url,
        title="Software Engineer",
        company="Acme",
        score=0.9,
    )


# ----------------------------------------------------------------------
# matches()
# ----------------------------------------------------------------------


class TestMatches:
    @pytest.mark.parametrize(
        "url",
        [
            "https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/Remote/Software-Engineer_R12345",
            "https://acme.wd5.myworkdayjobs.com/Acme_Careers/job/abc",
            "https://foo-corp.wd3.myworkdayjobs.com/External/job/abc",
            "https://acme.myworkdaysite.com/careers/job/abc",
        ],
    )
    def test_matches_workday_hosts(self, adapter, url):
        assert adapter.matches(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://boards.greenhouse.io/acme/jobs/12345",
            "https://jobs.lever.co/acme/abc",
            "https://www.linkedin.com/jobs/view/12345",
            "https://careers.acme.com/job/12345",
        ],
    )
    def test_does_not_match_non_workday_hosts(self, adapter, url):
        assert adapter.matches(url) is False


# ----------------------------------------------------------------------
# portal_id()
# ----------------------------------------------------------------------


class TestPortalId:
    @pytest.mark.parametrize(
        ("url", "expected_tenant"),
        [
            ("https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/1", "acme"),
            ("https://foo-corp.wd5.myworkdayjobs.com/External/job/1", "foo-corp"),
            ("https://acme.myworkdaysite.com/careers/job/1", "acme"),
        ],
    )
    def test_extracts_tenant_from_host(self, adapter, url, expected_tenant):
        job = make_job(url)
        assert adapter.portal_id(job) == expected_tenant

    def test_same_tenant_different_jobs_share_portal_id(self, adapter):
        job_a = make_job("https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/1")
        job_b = make_job("https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/2")
        assert adapter.portal_id(job_a) == adapter.portal_id(job_b)


# ----------------------------------------------------------------------
# select_adapter()
# ----------------------------------------------------------------------


class TestSelectAdapter:
    def test_returns_workday_adapter_for_workday_url(self):
        found = select_adapter("https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/1")
        assert isinstance(found, WorkdayAdapter)

    def test_returns_none_for_unsupported_platform(self):
        assert select_adapter("https://boards.greenhouse.io/acme/jobs/12345") is None


# ----------------------------------------------------------------------
# needs_auth()
# ----------------------------------------------------------------------


class TestNeedsAuth:
    def test_sign_in_gate_detected(self, page, adapter):
        page.set_content(
            """
            <h1>Sign In</h1>
            <p>New user? Create Account</p>
            <input type="email" name="email">
            <input type="password" name="password">
            """
        )
        assert adapter.needs_auth(page) is True

    def test_application_form_is_not_a_gate(self, page, adapter):
        page.set_content(
            """
            <form>
                <input type="text" name="firstName" placeholder="First Name">
                <input type="text" name="lastName" placeholder="Last Name">
                <input type="tel" name="phone" placeholder="Phone">
            </form>
            """
        )
        assert adapter.needs_auth(page) is False

    def test_structural_hint_selector_is_sufficient(self, page, adapter):
        # 没有密码字段/门禁文本，但有 Workday 的门禁页结构提示——应直接判定门禁页。
        page.set_content('<div data-automation-id="signInLink">Sign In</div>')
        assert adapter.needs_auth(page) is True


# ----------------------------------------------------------------------
# login_succeeded()：登录/注册后校验（Phase 6 carry-forward b）
# ----------------------------------------------------------------------


class TestLoginSucceeded:
    def test_error_banner_means_failure(self, page, adapter):
        page.goto("about:blank")
        page.set_content("<div class='error'>Invalid username or password.</div>")
        assert adapter.login_succeeded(page, pre_auth_url="about:blank") is False

    def test_no_error_and_url_changed_means_success(self, page, adapter):
        page.goto("about:blank")
        page.set_content("<div>Welcome back, Alice.</div>")
        assert adapter.login_succeeded(page, pre_auth_url="https://acme.wd1.myworkdayjobs.com/signin") is True

    def test_no_error_but_url_unchanged_means_failure(self, page, adapter):
        page.goto("about:blank")
        page.set_content("<div>Sign In</div>")
        # pre_auth_url 与当前 page.url 相同 → 视为没有发生跳转，判失败。
        assert adapter.login_succeeded(page, pre_auth_url=page.url) is False

    def test_no_pre_auth_url_skips_url_check(self, page, adapter):
        page.set_content("<div>All good.</div>")
        assert adapter.login_succeeded(page, pre_auth_url=None) is True


# ----------------------------------------------------------------------
# confirmation_hint()
# ----------------------------------------------------------------------


class TestConfirmationHint:
    def test_structural_hint_true(self, page, adapter):
        page.set_content('<div data-automation-id="applicationConfirmationPage"></div>')
        assert adapter.confirmation_hint(page) is True

    def test_text_marker_true(self, page, adapter):
        page.set_content("<h1>Thank you for applying!</h1>")
        assert adapter.confirmation_hint(page) is True

    def test_still_on_form_marker_false(self, page, adapter):
        page.set_content("<div class='error'>Please complete all required fields.</div>")
        assert adapter.confirmation_hint(page) is False

    def test_no_signal_returns_none(self, page, adapter):
        page.set_content("<div>Some unrelated page content.</div>")
        assert adapter.confirmation_hint(page) is None

    def test_negative_marker_beats_coincidental_positive_text(self, page, adapter):
        # 回归：正向文本关键词与「还在表单上」措辞同页共存时，必须表态 False
        # （偏向可重投的 FAILED，绝不误判成永不重投的 SUCCEEDED）。旧实现里正向
        # 关键词先判定，会误判成确认页；反向信号现在优先。
        page.set_content(
            "<h1>Thank you for applying!</h1>"
            "<div class='error'>There was a problem. Please complete all required fields.</div>"
            "<button>Submit Application</button>"
        )
        assert adapter.confirmation_hint(page) is False

    def test_review_step_with_submit_button_not_confirmation(self, page, adapter):
        # 提交前的「复核」步（仍带 Submit 按钮）绝不能被当成确认页。
        page.set_content(
            "<h1>Review your application</h1>"
            "<p>Please review the information below before submitting.</p>"
            "<button>Submit Application</button>"
        )
        assert adapter.confirmation_hint(page) is False

    def test_plain_review_page_without_markers_returns_none(self, page, adapter):
        # 没有任何 Workday 专属信号的复核页 → 不表态，交回 submit.py 通用启发式
        # （通用启发式同样不会因缺正向关键词而误报成功）。
        page.set_content(
            "<h1>Review</h1><p>Check your answers.</p><button>Submit Application</button>"
        )
        assert adapter.confirmation_hint(page) is None


# ----------------------------------------------------------------------
# open_application()
# ----------------------------------------------------------------------


class TestOpenApplication:
    def test_clicks_through_apply_flow_to_form(self, page, adapter):
        # 模拟职位详情页 → 点 Apply → 二选一页（优先 Apply Manually，跳过
        # Autofill with Resume）→ 表单第一页。
        page.set_content(
            """
            <button onclick="document.body.innerHTML =
                '<button>Apply Manually</button><button>Autofill with Resume</button>'
            ">Apply</button>
            """
        )
        browser = FakeBrowserSession(page)
        settings = Settings()

        result = adapter.open_application(browser, make_job("https://acme.wd1.myworkdayjobs.com/job/1"), settings)

        # 二选一页点了 "Apply Manually" 后，页面没有再变化（fixture 到此为止），
        # needs_auth 判否，视为已到表单——outcome 应为 on_form。
        assert result.outcome == "on_form"
        assert browser.goto_calls == ["https://acme.wd1.myworkdayjobs.com/job/1"]

    def test_reaches_auth_gate(self, page, adapter):
        page.set_content(
            """
            <button onclick="document.body.innerHTML =
                '<h1>Sign In</h1><p>Create Account</p><input type=password>'
            ">Apply</button>
            """
        )
        browser = FakeBrowserSession(page)
        settings = Settings()

        result = adapter.open_application(browser, make_job("https://acme.wd1.myworkdayjobs.com/job/1"), settings)

        assert result.outcome == "needs_auth"

    def test_captcha_failure_short_circuits(self, page, adapter):
        page.set_content('<div class="h-captcha" data-sitekey="sk"></div>')
        browser = FakeBrowserSession(page)
        # 默认 Settings() 没配 CAPSOLVER_API_KEY → 验证码求解优雅失败
        settings = Settings()

        result = adapter.open_application(browser, make_job("https://acme.wd1.myworkdayjobs.com/job/1"), settings)

        assert result.outcome == "failed"
        assert result.reason == "captcha_unsolved"
