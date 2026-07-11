"""core.deliver.adapters.workday —— Workday 门户适配（阶段 7，spec 决策六终态之前的落地平台）。

Workday-Application-Automator 调研的固定分页流程（联系方式→工作经历→教育→
自愿披露→自我认定）、work-history repeater、可搜索下拉、可选字段容错，全部
已经是 `engine.py`/`browser.py`（阶段 5）通用能力的一部分——本模块**不重复
实现那些**，只补三段 `engine.run_form()` 天生做不到的平台特异步骤：

1. **OPENING（`open_application`）**：从职位 URL 走到表单第一页或登录门禁页。
   Workday 的固定链路是「职位详情页 → 点 Apply → （可能）二选一 Apply
   Manually / Autofill with Resume → 门禁页或表单」。这里刻意**不接
   `FillEngine`**：状态机（阶段 3，不可改）里 `OPENING` 没有到 `WAITING_USER`
   的合法边——如果用 `engine.fill_current_page()` 走这一步，一旦 LLM 判定
   某个按钮 `needs_user`（比如撞上一个奇怪的弹窗），`fill_current_page` 会
   返回 `"suspended"`，但 runner 这时候没有合法状态机边能落这个结果。所以
   这里走跟 `auth._click_submit()`/`_fill_login_fields()`（阶段 6，同样发生
   在 FILLING 之前）一样的「关键词启发式 + Playwright 直接操作」路子，不
   触发问询。这是本适配器唯一放弃「LLM 决策」的地方，理由是状态机约束而
   非偷懒——文档到此为止，报告里会再强调一遍。
2. **`needs_auth`**：识别 Workday 的登录/创建账号门禁页（vs. 已经落在申请
   表单）。
3. **`confirmation_hint`**：给 `submit.is_confirmation_page()` 补一个 Workday
   专属的强信号（`data-automation-id` 结构提示），比纯文本启发式更可靠。

**已知的硬编码假设**（跟随任务要求，逐条标注脆弱点）：
- `_APPLY_BUTTON_HINT_SELECTORS`/`_CONFIRMATION_HINT_SELECTORS` 里的
  `data-automation-id` 值是 Workday 前端社区调研中常见的约定属性名（Workday
  大量使用 `data-automation-id` 做自动化测试钩子），但**不是 Workday 官方
  承诺的稳定 API**——门户改版/不同 Workday 版本可能换名或去掉。所以每处都
  「先试结构提示，没找到就退回关键词文本启发式」两道保险，不单点依赖它。
- 关键词列表（`_APPLY_KEYWORDS`/`_AUTH_GATE_TEXT_MARKERS`/
  `_CONFIRMATION_TEXT_MARKERS` 等）是英文为主（Workday 门户默认多为英文），
  只搭配了少量中文关键词兜底；非英语门户可能需要按需扩充。
"""

from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from core.config import Settings
from core.contracts import JobRef
from core.deliver.adapters.base import OpenResult, PlatformAdapter, register_adapter
from core.deliver.captcha import handle_captcha_if_present
from core.storage.run_log import RunLogger

# matches()：Workday 招聘门户的两类常见 host——绝大多数走 `<tenant>.<wdN>.
# myworkdayjobs.com`（wd1/wd3/wd5 等分片），少数雇主套自定义域名走
# `myworkdaysite.com`。只判断 host 里含不含这两个标记词，不锁死 wdN 编号
# （新分片号随时可能出现）。
_WORKDAY_HOST_MARKERS = ("myworkdayjobs.com", "myworkdaysite.com")

# open_application()：Apply 流程按钮的两道保险——结构提示优先，找不到才走
# 关键词文本匹配。"apply manually" 排在 "apply" 前面：Workday 常见的二选一
# 页（Apply Manually / Autofill with Resume）里，我们要的是前者（走标准表单
# 流程，不依赖简历解析的不确定性），必须先于泛化的 "apply" 命中，否则可能
# 先点中泛化关键词匹配到的别的按钮。
_APPLY_BUTTON_HINT_SELECTORS = (
    '[data-automation-id="applyButton"]',
    '[data-automation-id="apply"]',
)
_APPLY_KEYWORDS = ("apply manually", "apply now", "apply")
_APPLY_EXCLUDE_KEYWORDS = ("autofill",)  # 明确避开「用简历自动填充」选项
_MAX_APPLY_CLICKS = 4  # 安全阀：职位详情页→(可能的)二选一页→门禁/表单页，正常 1~2 次点击够用

# Cookie 同意横幅：最佳努力关闭，找不到/点失败都不算错误（很多门户根本没有）。
_COOKIE_ACCEPT_KEYWORDS = ("accept all", "accept", "agree", "同意")

# needs_auth()：Workday 登录/创建账号门禁页的结构 + 文本双重信号。
_AUTH_GATE_HINT_SELECTORS = (
    '[data-automation-id="signInLink"]',
    '[data-automation-id="createAccountLink"]',
    '[data-automation-id="signInFormEmailInput"]',
)
_AUTH_GATE_TEXT_MARKERS = ("sign in", "create account", "登录", "创建账号", "注册")

# login_succeeded()：登录/注册提交后的失败信号（错误提示条常见措辞）。宁可
# 漏判「其实失败了但没识别出来」（后续 FILLING 大概率会因为看不到表单字段
# 而自然失败），也不误判「其实成功了」为失败——所以关键词尽量取明确的错误
# 措辞，不用泛化词。
_LOGIN_ERROR_KEYWORDS = (
    "invalid",
    "incorrect",
    "failed to sign in",
    "we could not",
    "we were unable",
    "账号或密码错误",
    "登录失败",
    "错误",
    "无效",
)

# confirmation_hint()：Workday 提交确认页的结构 + 文本双重信号。
_CONFIRMATION_HINT_SELECTORS = (
    '[data-automation-id="applicationConfirmationPage"]',
    '[data-automation-id="submitConfirmation"]',
)
_CONFIRMATION_TEXT_MARKERS = (
    "you have successfully submitted",
    "your application has been submitted",
    "thank you for applying",
)
# 明确「还在表单上/提交被拒绝」的反向信号，命中就明确表态 False（而不是
# 交给 submit.py 的通用启发式，那边看不到 Workday 专属的校验错误措辞）。
# 宁可多收几条「还在表单上」的措辞：误判 False（可重投）远比误判 True
# （职位永不重投、静默丢失投递）安全。含 Workday 提交前最后一步的
# "review your application" 标题——万一 Submit 点击没生效、页面仍停在复核步，
# 这条能把它拦成 False 而不是被别处残留文案误判成确认页。
_STILL_ON_FORM_TEXT_MARKERS = (
    "required fields",
    "please complete",
    "please correct",
    "there was a problem",
    "review your application",
    "必填",
    "请完成",
)


@register_adapter
class WorkdayAdapter(PlatformAdapter):
    """Workday 招聘门户适配（PRD 二：每雇主门户独立账号体系）。"""

    # ------------------------------------------------------------------
    # matches / portal_id
    # ------------------------------------------------------------------

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(marker in host for marker in _WORKDAY_HOST_MARKERS)

    def portal_id(self, job: JobRef) -> str:
        """host 的第一段子域即租户/雇主标识（如 `acme.wd1.myworkdayjobs.com` → `acme`）。

        同一雇主在 Workday 上所有职位共享这同一个 host 前缀，映射到同一条
        `credentials` 表记录，满足 PRD 二「每雇主门户独立账号」——不是「每
        职位」，也不是「整个 Workday 平台共用一个账号」。
        """
        host = (urlparse(str(job.url)).hostname or "").lower()
        if not host:
            return job.platform
        return host.split(".")[0]

    # ------------------------------------------------------------------
    # needs_auth
    # ------------------------------------------------------------------

    def needs_auth(self, page: Page) -> bool:
        for selector in _AUTH_GATE_HINT_SELECTORS:
            if page.locator(selector).count() > 0:
                return True

        has_password_field = page.locator('input[type="password"]').count() > 0
        text = _safe_inner_text(page)
        has_gate_text = any(marker in text for marker in _AUTH_GATE_TEXT_MARKERS)
        return has_password_field and has_gate_text

    # ------------------------------------------------------------------
    # open_application：OPENING 全流程
    # ------------------------------------------------------------------

    def open_application(
        self,
        browser,
        job: JobRef,
        settings: Settings,
        run_logger: RunLogger | None = None,
    ) -> OpenResult:
        page = browser.goto(str(job.url))

        outcome = handle_captcha_if_present(page, settings, run_logger)
        if outcome == "failed":
            return OpenResult(outcome="failed", reason="captcha_unsolved")

        _dismiss_cookie_banner(page)

        for _ in range(_MAX_APPLY_CLICKS):
            if self.needs_auth(page):
                return OpenResult(outcome="needs_auth")
            if not _click_apply_like_button(page):
                break

        outcome = handle_captcha_if_present(page, settings, run_logger)
        if outcome == "failed":
            return OpenResult(outcome="failed", reason="captcha_unsolved")

        if self.needs_auth(page):
            return OpenResult(outcome="needs_auth")
        return OpenResult(outcome="on_form")

    # ------------------------------------------------------------------
    # login_succeeded：阶段 6 交接的「登录/注册后校验」（覆盖 base ABC 的默认实现）
    # ------------------------------------------------------------------

    def login_succeeded(self, page: Page, *, pre_auth_url: str | None = None) -> bool:
        """覆盖 `PlatformAdapter.login_succeeded()`（默认信任 authenticate 的乐观结果）。

        `Authenticator.authenticate()`（阶段 6）返回 `"authenticated"` 是乐观的——
        它只保证「提交了登录/注册表单」，没有验证提交后是不是真的进入了登录态。
        这里补三重校验：

        1. 页面上有没有明确的错误提示措辞（`_LOGIN_ERROR_KEYWORDS`）——有则
           直接判失败，无论 URL 变没变。
        2. 没有错误提示，但页面 URL 跟提交前一样（没有发生任何跳转）——多数
           登录/注册失败会原地停留（校验不通过、按钮被禁用等），这是次要
           信号。`pre_auth_url` 缺省（调用方没有提供）则跳过这项检查。
        3. 都没命中→ 判定成功。
        """
        if _has_error_banner(page):
            return False
        if pre_auth_url is not None and page.url == pre_auth_url:
            return False
        return True

    # ------------------------------------------------------------------
    # confirmation_hint：供 submit.is_confirmation_page() 调用
    # ------------------------------------------------------------------

    def confirmation_hint(self, page: Page) -> bool | None:
        # 结构信号（Workday 专属 data-automation-id）最强，命中即确认页。
        for selector in _CONFIRMATION_HINT_SELECTORS:
            if page.locator(selector).count() > 0:
                return True

        text = _safe_inner_text(page)
        # 反向信号先于「正向文本信号」判定：PRD 八下误判 SUCCEEDED 会导致职位
        # 永不重投（决策八），代价远高于误判 FAILED（可重投）。所以一旦页面还
        # 带「必填未完成/提交出错」这类明确的「还在表单上」措辞，即便同时命中了
        # 某个正向文本关键词（如页脚残留的 "thank you for applying"），也一律
        # 表态 False——正向纯文本关键词比结构信号弱，不足以压过明确的失败措辞。
        if any(marker in text for marker in _STILL_ON_FORM_TEXT_MARKERS):
            return False
        if any(marker in text for marker in _CONFIRMATION_TEXT_MARKERS):
            return True
        return None


# ---------------------------------------------------------------------------
# 内部辅助：关键词启发式（不经 LLM，理由见模块文档）
# ---------------------------------------------------------------------------


def _safe_inner_text(page: Page) -> str:
    try:
        return (page.inner_text("body") or "").lower()
    except PlaywrightError:
        return ""


def _dismiss_cookie_banner(page: Page) -> None:
    """最佳努力关闭 cookie 同意横幅：找不到/点击失败都不算错误，直接放弃。"""
    candidates = page.locator("button")
    count = candidates.count()
    for i in range(count):
        element = candidates.nth(i)
        try:
            label = (element.inner_text() or "").strip().lower()
        except PlaywrightError:
            continue
        if any(keyword in label for keyword in _COOKIE_ACCEPT_KEYWORDS):
            try:
                element.click(timeout=2000)
            except PlaywrightError:
                pass
            return


def _click_apply_like_button(page: Page) -> bool:
    """点一次「Apply / Apply Manually / Apply Now」类按钮；点到返回 `True`。

    不经过 `dom.collect_page()`（它的候选选择器不含 `<a>`，Workday 的 Apply
    入口有时是链接而非按钮）——直接用 Playwright locator 扫描
    `button`/`a`/`input[type=submit|button]`，本函数不需要 `element_id`
    编号体系（那是给 LLM 决策用的，这里是纯启发式点击，不涉及 LLM）。
    """
    for selector in _APPLY_BUTTON_HINT_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            try:
                locator.first.click()
                page.wait_for_load_state("load")
                return True
            except PlaywrightError:
                pass

    candidates = page.locator("button, a, input[type='submit'], input[type='button']")
    count = candidates.count()
    for keyword in _APPLY_KEYWORDS:
        for i in range(count):
            element = candidates.nth(i)
            try:
                label = (
                    element.inner_text() or element.get_attribute("value") or ""
                ).strip().lower()
            except PlaywrightError:
                continue
            if not label or keyword not in label:
                continue
            if any(bad in label for bad in _APPLY_EXCLUDE_KEYWORDS):
                continue
            try:
                element.click()
                page.wait_for_load_state("load")
            except PlaywrightError:
                continue
            return True
    return False


def _has_error_banner(page: Page) -> bool:
    text = _safe_inner_text(page)
    return any(keyword in text for keyword in _LOGIN_ERROR_KEYWORDS)
