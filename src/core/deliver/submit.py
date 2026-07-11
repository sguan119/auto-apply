"""core.deliver.submit —— READY_TO_SUBMIT → SUBMITTING → CONFIRMING（决策六终态 / PRD 八）。

`confirm_and_submit()` 是这三个状态的唯一入口，跟 `engine.py`/`auth.py` 一样
不导入 `state_machine`/`repository`，只返回结构化的 `SubmitResult`——runner
（阶段 8）负责把它翻译成状态机转移、落 `DeliveryRecord`。

**⚠️ 状态机边界的一个重要坑，写给阶段 8**：`state_machine.py`（阶段 3，不可
改）里 `READY_TO_SUBMIT` 的唯一合法出边是 `SUBMITTING`（以及任意非终态都有
的 `→FAILED`），**没有 `READY_TO_SUBMIT → SUSPENDED` 这条边**。但手动模式下
「确认提交」走的正是 `QuestionChannel`（决策七），天然可能超时——超时按语义
应该挂起该职位（跟 `WAITING_USER` 超时一样，问题补答后从 `OPENING` 重投），
状态机却没给这条路留边。

解决办法**不是**改状态机（超出本阶段范围，且 `WAITING_USER → SUSPENDED`
这条边本来就够用）：**调用方必须在还处于 `FILLING` 状态时调用
`confirm_and_submit()`，先拿到确认结果，再决定要不要真的把状态机推进到
`READY_TO_SUBMIT`**：

```
result = confirm_and_submit(page, job, mode=..., question_channel=..., ...)
match result.outcome:
    case "suspended":
        # 当成 FILLING 的 WAITING_USER 超时处理，不要先 state.to(READY_TO_SUBMIT)
        state.to(WAITING_USER); state.to(SUSPENDED)
        # 把 confirm_and_submit 内部构造的确认问题落挂起问题表，
        # 让 RunSummary/CLI 的「待补答清单」里能看到它
    case "declined":
        # 用户明确拒绝提交——不是「出错」，但 8 态模型里没有第三个终态，
        # 只能落 FAILED，用 reason 区分「拒绝」与「真失败」，
        # RunSummary.failed_by_reason 靠这个 reason 字符串分组，不会跟
        # 别的失败原因混在一起
        state.to(READY_TO_SUBMIT); state.to(FAILED, reason="user_declined_submit")
    case "failed":
        # 确认已经通过（或 auto 模式直接穿过），但 SUBMITTING/CONFIRMING
        # 阶段本身失败——这时候合法地推进过 READY_TO_SUBMIT/SUBMITTING 再落 FAILED
        state.to(READY_TO_SUBMIT); state.to(SUBMITTING); state.to(FAILED, reason=result.reason)
    case "succeeded":
        state.to(READY_TO_SUBMIT); state.to(SUBMITTING); state.to(CONFIRMING); state.to(SUCCEEDED)
```

**手动模式确认为什么不调用 `TerminalQuestionChannel.confirm()`**：那是 CLI
包（`src/cli/`）的实现细节，`core` 不能反向依赖 `cli`（CLAUDE.md「核心逻辑与
界面分离」）。这里直接对 `QuestionChannel` 抽象构造一条 yes/no 语义的
`Question` 再 `ask()`，逻辑上与 `TerminalQuestionChannel.confirm()` 完全一致
（复刻，不是调用）——任何 `QuestionChannel` 实现都能驱动，不要求额外暴露
`confirm()` 方法。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from core.config import Settings
from core.contracts import JobRef, Question
from core.deliver.adapters.base import PlatformAdapter
from core.deliver.captcha import handle_captcha_if_present
from core.questions.channel import TIMEOUT, QuestionChannel, Timeout
from core.storage.run_log import RunLogger

SubmitOutcome = Literal["succeeded", "failed", "suspended", "declined"]

# READY_TO_SUBMIT 手动确认：走 QuestionChannel.ask() 的 yes/no 语义（复刻
# TerminalQuestionChannel.confirm()，理由见模块文档）。
_CONFIRM_QUESTION_PAGE = "submit_confirm"
_AFFIRMATIVE_PREFIXES = ("y", "是")

# SUBMITTING：最终提交按钮的关键词匹配（优先级从高到低）。"submit application"
# 比泛化的 "submit" 更明确，Workday 等门户常见措辞；中文兜底。排除词避免
# 误点「保存草稿」「取消」「上一步」这类同样含泛化关键词的按钮。
_SUBMIT_KEYWORDS = ("submit application", "submit", "提交申请", "提交")
_SUBMIT_EXCLUDE_KEYWORDS = ("save", "draft", "cancel", "back", "上一步", "保存")

# CONFIRMING：提交确认页的通用文本启发式（`adapter.confirmation_hint()` 优先，
# 问不出结果才退回这里——见 `is_confirmation_page()`）。
_CONFIRMATION_TEXT_MARKERS = (
    "application submitted",
    "you have successfully submitted",
    "thank you for applying",
    "thank you for your application",
    "your application has been submitted",
    "已提交",
    "申请已提交",
)
# 通用「还在表单上/提交出错」反向信号：`is_confirmation_page()` 退回通用文本
# 启发式时，先查这些措辞——命中就判「不是确认页」。PRD 八下误判 SUCCEEDED 会
# 让职位永不重投（决策八，静默丢失投递），代价远高于误判 FAILED（可重投），
# 所以宁可让反向信号压过同页可能残留的某个正向关键词。adapter.confirmation_hint()
# 已表态时不会走到这里；这条只在无 adapter / adapter 不表态（如未来非 Workday
# 平台）时兜底，让通用路径自身也不会因巧合子串误报成功。
_STILL_ON_FORM_TEXT_MARKERS = (
    "required fields",
    "please complete",
    "please correct",
    "there was a problem",
    "review your application",
    "必填",
    "请完成",
)

# 提交按钮点下去到确认页渲染完成之间通常有一次网络/导航往返；用短轮询代替
# 一次性判断，避免刚点完提交、页面还没来得及跳转就被误判成 FAILED。这个
# 预算独立于 `question_timeout`（那是给真人用的等待窗口，量级完全不同）。
_CONFIRMATION_POLL_INTERVAL = 1.0
_CONFIRMATION_POLL_TIMEOUT = 30.0


@dataclass
class SubmitResult:
    """`confirm_and_submit()` 的返回。`outcome` 语义：

    - `"succeeded"`：确认（或 auto 直穿）→ 提交 → 确认页命中。
    - `"declined"`：手动模式下用户明确拒绝提交（未点击提交按钮）。
    - `"suspended"`：手动模式确认超时（未获得回答）。
    - `"failed"`：验证码求解失败 / 找不到提交按钮 / 提交后未识别到确认页，
      `reason` 给出具体原因字符串。
    """

    outcome: SubmitOutcome
    reason: str | None = None


def confirm_and_submit(
    page: Page,
    job: JobRef,
    *,
    mode: str,
    question_channel: QuestionChannel,
    adapter: PlatformAdapter | None = None,
    settings: Settings,
    run_logger: RunLogger | None = None,
) -> SubmitResult:
    """READY_TO_SUBMIT（手动确认）→ SUBMITTING（点提交）→ CONFIRMING（识别确认页）。

    `mode`：`"manual"`（默认）先经 `question_channel` 确认，`False`/`TIMEOUT`
    分别映射 `"declined"`/`"suspended"`，不会点击提交按钮；`"auto"` 直接穿过
    （决策六）。`adapter` 可选——传入时 `is_confirmation_page()` 优先问它的
    `confirmation_hint()`。
    """
    if mode == "manual":
        prompt = f"即将提交「{job.company} - {job.title}」的申请，确认提交吗？(y/n)"
        confirmed = _ask_submit_confirmation(
            question_channel, job, prompt, settings.deliver.question_timeout
        )
        if confirmed is TIMEOUT:
            if run_logger:
                run_logger.log("submit_confirmation_timeout")
            return SubmitResult(outcome="suspended", reason="submit_confirmation_timeout")
        if not confirmed:
            if run_logger:
                run_logger.log("submit_confirmation_declined")
            return SubmitResult(outcome="declined", reason="user_declined_submit")
    # auto 模式：不问询，直接穿过（决策六「自动模式直接穿过」）。

    captcha_outcome = handle_captcha_if_present(page, settings, run_logger)
    if captcha_outcome == "failed":
        return SubmitResult(outcome="failed", reason="captcha_unsolved")

    if not _click_submit_button(page):
        if run_logger:
            run_logger.log("submit_button_not_found")
        return SubmitResult(outcome="failed", reason="submit_button_not_found")
    if run_logger:
        run_logger.log("submit_clicked")

    if not _wait_for_confirmation(page, adapter):
        if run_logger:
            run_logger.log("confirmation_page_not_detected")
        return SubmitResult(outcome="failed", reason="confirmation_page_not_detected")

    if run_logger:
        run_logger.log("submit_confirmed")
    return SubmitResult(outcome="succeeded")


def is_confirmation_page(page: Page, adapter: PlatformAdapter | None = None) -> bool:
    """CONFIRMING 的核心判定：`adapter.confirmation_hint()` 优先，`None`（不表态）
    才退回通用文本启发式（PRD 八：看到确认页即 SUCCEEDED，否则 FAILED）。
    """
    if adapter is not None:
        hint = adapter.confirmation_hint(page)
        if hint is not None:
            return hint
    try:
        text = (page.inner_text("body") or "").lower()
    except PlaywrightError:
        return False
    # 反向信号先判：还带「必填未完成/提交出错/仍在复核」措辞的页面一律判否，
    # 即便同页残留了某个正向关键词（偏向可重投的 FAILED，不偏静默丢失的 SUCCEEDED）。
    if any(marker in text for marker in _STILL_ON_FORM_TEXT_MARKERS):
        return False
    return any(marker in text for marker in _CONFIRMATION_TEXT_MARKERS)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _ask_submit_confirmation(
    question_channel: QuestionChannel, job: JobRef, prompt: str, timeout: float
) -> bool | Timeout:
    question = Question(job=job, field_path=None, question=prompt, page=_CONFIRM_QUESTION_PAGE)
    result = question_channel.ask([question], timeout)
    if result is TIMEOUT:
        return TIMEOUT
    answer_text = result[0].answer.strip().lower()
    return answer_text.startswith(_AFFIRMATIVE_PREFIXES)


def _click_submit_button(page: Page) -> bool:
    candidates = page.locator("button, input[type='submit'], input[type='button']")
    count = candidates.count()
    for keyword in _SUBMIT_KEYWORDS:
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
            if any(bad in label for bad in _SUBMIT_EXCLUDE_KEYWORDS):
                continue
            try:
                element.click()
            except PlaywrightError:
                continue
            return True
    return False


def _wait_for_confirmation(page: Page, adapter: PlatformAdapter | None) -> bool:
    deadline = time.monotonic() + _CONFIRMATION_POLL_TIMEOUT
    while True:
        if is_confirmation_page(page, adapter):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_CONFIRMATION_POLL_INTERVAL)
