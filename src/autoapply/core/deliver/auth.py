"""autoapply.core.deliver.auth —— AUTHENTICATING 编排：登录 / 自动注册（spec 决策六）。

**与 runner（阶段 8）的边界**：跟 `engine.py` 一样，本模块不导入
`state_machine`、不调用 `repository.record_delivery()`——只返回结构化的
`AuthResult`，runner 负责把它翻译成状态机转移。允许使用 `repository` 的地方
只有凭据读写（`get_credential`/`upsert_credential`），这是 AUTHENTICATING
本身的职责，不是「越权碰存储」。

**登录 vs 注册**：
- 有凭据（`repository.get_credential(platform, portal)` 命中）→ **登录**。
  登录表单结构固定（用户名/密码/提交按钮），不需要 LLM 判断内容——直接走
  `dom.collect_page()` + 启发式匹配 + `browser.apply_action()` 的「简单定
  向填」，比整页过一次 LLM 决策更省 token 也更省一次可能出错的环节（spec
  允许这条替代路径，见任务说明）。
- 无凭据 → **注册**，`Authenticator.engine.run_form()` 复用 FILLING 同一套
  LLM+DOM 循环填注册表单（决策六：不单独开发注册逻辑）。生成的密码通过
  `engine.bio_store.write_path()` 预写进 `form_answers.password` 等约定路径
  （复用 `engine._field_path_for()` 的推导习惯——同名/同标签字段回写一次，
  后续同结构页面直接读到），这样 LLM 在决策密码字段时能把它当已知 BIO 值
  直接填，不必对一个「引擎自己已经知道答案」的字段触发 needs_user 问询。

**验证码**：登录/注册的关键节点（进页面时、提交前）调用
`captcha.handle_captcha_if_present()`；返回 `"failed"` 就地短路为
`AuthResult(outcome="failed", reason="captcha_unsolved")`，不重试（PRD 五）。
`engine.run_form()`（阶段 5，不可修改）本身不感知验证码，所以只能在
run_form 前后的边界上查，覆盖不到「多页注册表单中间某一页」出现验证码的
情况——这是本阶段的已知局限，留给阶段 7 Workday 适配按需在关键页前后加查。

**邮箱验证码/链接**：`_EmailVerifyingChannel` 包一层 `QuestionChannel`，把
`engine.run_form()` 内部产生的、形似「验证码」的问询在到达真正问询通道
（终端/未来 Web）之前，先用 `EmailVerifier.fetch_code()` 尝试自动回答——
命中就直接喂回 `Answer`，不惊动用户；没命中的问题原样转发给底层通道。这样
「邮箱验证码经只读邮箱自动取回」（决策六原文）天然嵌进 FILLING 同一套
问询→回写→重决策循环，不需要给 engine 开新接口。表单提交完成后，另外
尝试 `fetch_link()` 补一次「验证链接」（有些 ATS 靠点击邮件里的链接激活
账号，不是表单内的一个字段）——找到就 `browser.goto()` 过去，找不到就
放弃（PRD 六没有强制要求两者都支持，尽力而为）。
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass, field
from typing import Literal

from autoapply.core.config import Settings
from autoapply.core.contracts import Answer, FieldValueSource, FilledField, JobRef, Question
from autoapply.core.deliver import browser as browser_primitives
from autoapply.core.deliver.captcha import handle_captcha_if_present
from autoapply.core.deliver.dom import collect_page
from autoapply.core.deliver.email_verify import EmailVerifier
from autoapply.core.deliver.engine import FillEngine
from autoapply.core.llm.client import PageElement
from autoapply.core.questions.channel import TIMEOUT, QuestionChannel, Timeout
from autoapply.core.storage import repository
from autoapply.core.storage.run_log import RunLogger

AuthOutcome = Literal["authenticated", "failed", "suspended"]

# random 模式密码策略：长度 + 四类字符各至少一个（多数注册表单的常见强度要求）。
_RANDOM_PASSWORD_LENGTH = 16
_SYMBOL_CHARS = "!@#$%^&*"

# template 模式的随机片段长度与占位符。
_TEMPLATE_RAND_TOKEN = "{rand}"
_TEMPLATE_RAND_LENGTH = 6

# 预写进 bio_store 的密码字段路径候选（复用 engine.py 的 `form_answers.<slug>`
# 命名空间约定）——常见注册表单的「密码」「确认密码」字段 name/label slugify
# 后大概率落在这几个里。命中不了的表单会让 LLM 对密码字段照常触发 needs_user，
# 不是致命失败，只是多问一次。
_PASSWORD_FIELD_SLUGS = (
    "password",
    "confirm_password",
    "verify_password",
    "re_enter_password",
    "repeat_password",
    "password_confirmation",
)

# 邮箱验证码相关问题的关键词识别（大小写不敏感），命中就交给 EmailVerifier
# 而不是转发给真人问询通道。宁可漏判（多问用户一次，无害）也不误判（把无关
# 问题错误地丢给邮箱轮询，白白等一个 poll_timeout）。
_VERIFICATION_KEYWORDS = (
    "verification code",
    "confirmation code",
    "verify your email",
    "验证码",
    "确认邮件",
)

# 注册完成后尝试取「验证链接」的等待预算：远小于 question_timeout（那是给
# 真人用的等待窗口），链接验证是 best-effort 补充步骤，不该让整个职位卡在
# 这里太久——超时就放弃，不算失败（多数 ATS 注册后账号已可用，链接验证只是
# 加分项）。
_EMAIL_LINK_WAIT_SECONDS = 20.0

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class AuthResult:
    """`Authenticator.authenticate()` 的返回：镜像 engine 的结果契约，让 runner
    对「填表」和「认证」两类结果一视同仁地处理状态转移。"""

    outcome: AuthOutcome
    reason: str | None = None  # outcome=="failed" 时给出，如 "captcha_unsolved"
    pending_questions: list[Question] = field(default_factory=list)  # outcome=="suspended" 时非空
    filled_fields: list[FilledField] = field(default_factory=list)  # 审计用，登录/注册期间填过的字段


def generate_password(settings: Settings) -> str:
    """按 `settings.deliver.password_generation_mode` 生成一个新密码（PRD 六）。

    - `"random"`（默认）：`secrets` 生成，长度 16，强制包含大写/小写/数字/
      符号各至少一个，满足绝大多数注册表单的密码强度校验。
    - `"template"`：用 `settings.deliver.password_template`，`{rand}` 占位符
      替换成随机字母数字片段；模板不含占位符则原样返回固定字符串（不推荐，
      但尊重用户显式配置）。
    - 其它值：视为未识别，退化为 random 模式（不因为一个拼写错误的配置值
      就让整个注册流程失败）。
    """
    mode = settings.deliver.password_generation_mode
    if mode == "template":
        template = settings.deliver.password_template
        if _TEMPLATE_RAND_TOKEN in template:
            rand_part = "".join(
                secrets.choice(string.ascii_letters + string.digits)
                for _ in range(_TEMPLATE_RAND_LENGTH)
            )
            return template.replace(_TEMPLATE_RAND_TOKEN, rand_part)
        return template

    required = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(_SYMBOL_CHARS),
    ]
    all_chars = string.ascii_letters + string.digits + _SYMBOL_CHARS
    rest = [
        secrets.choice(all_chars) for _ in range(_RANDOM_PASSWORD_LENGTH - len(required))
    ]
    chars = required + rest
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


class Authenticator:
    """AUTHENTICATING 阶段的驱动者。`browser` 只需要暴露 `.page`/`.goto()`
    （`BrowserSession` 的接口子集，测试可传任意鸭子类型对象）；`engine` 是一个
    已经站在目标页面上、构造好的 `FillEngine`（复用它的 `bio_store`/
    `question_channel`/`run_form()`）。
    """

    def __init__(
        self,
        browser,
        engine: FillEngine,
        settings: Settings,
        run_logger: RunLogger | None = None,
        email_verifier: EmailVerifier | None = None,
    ) -> None:
        self.browser = browser
        self.engine = engine
        self.settings = settings
        self.run_logger = run_logger
        self.email_verifier = email_verifier

    def authenticate(self, job: JobRef, portal: str) -> AuthResult:
        credential = repository.get_credential(job.platform, portal)
        if credential is not None:
            return self._login(job, portal, credential)
        return self._register(job, portal)

    # ------------------------------------------------------------------
    # 登录：有凭据，简单定向填（不复用整页 LLM 循环，见模块文档）
    # ------------------------------------------------------------------

    def _login(self, job: JobRef, portal: str, credential: repository.Credential) -> AuthResult:
        page = self.browser.page

        outcome = handle_captcha_if_present(page, self.settings, self.run_logger)
        if outcome == "failed":
            return AuthResult(outcome="failed", reason="captcha_unsolved")

        filled = _fill_login_fields(page, credential)

        outcome = handle_captcha_if_present(page, self.settings, self.run_logger)
        if outcome == "failed":
            return AuthResult(outcome="failed", reason="captcha_unsolved", filled_fields=filled)

        _click_submit(page)
        if self.run_logger:
            self.run_logger.log("auth_login_submitted", platform=job.platform, portal=portal)
        return AuthResult(outcome="authenticated", filled_fields=filled)

    # ------------------------------------------------------------------
    # 注册：无凭据，复用 engine.run_form() 同一套 LLM+DOM 循环
    # ------------------------------------------------------------------

    def _register(self, job: JobRef, portal: str) -> AuthResult:
        password = generate_password(self.settings)
        page = self.browser.page

        outcome = handle_captcha_if_present(page, self.settings, self.run_logger)
        if outcome == "failed":
            return AuthResult(outcome="failed", reason="captcha_unsolved")

        _seed_password_into_bio(self.engine, password)

        original_channel = self.engine.question_channel
        if self.email_verifier is not None:
            self.engine.question_channel = _EmailVerifyingChannel(
                original_channel, self.email_verifier, portal, self.run_logger
            )
        try:
            result = self.engine.run_form(job, page_hint="注册")
        finally:
            self.engine.question_channel = original_channel

        # engine 复用 FILLING 循环填注册表单时，会把从 bio 读到的密码字段照常
        # 记一条 FilledField（value=明文密码）——那份 filled_fields 会被 runner
        # 落进 DeliveryRecord / run log。凭据表已按 PRD 六存了一份明文，没理由让
        # 密码再随审计记录泄漏一份。登录路径本就手动遮罩过，这里给注册路径补齐。
        filled = _mask_password_in_fields(result.filled_fields, password)

        if result.outcome == "suspended":
            return AuthResult(
                outcome="suspended",
                pending_questions=result.pending_questions,
                filled_fields=filled,
            )
        if result.outcome == "failed":
            return AuthResult(
                outcome="failed",
                reason=result.failure_reason,
                filled_fields=filled,
            )

        outcome = handle_captcha_if_present(page, self.settings, self.run_logger)
        if outcome == "failed":
            return AuthResult(
                outcome="failed", reason="captcha_unsolved", filled_fields=filled
            )

        if self.email_verifier is not None:
            link = self.email_verifier.fetch_link(
                sender_filter=portal, timeout=_EMAIL_LINK_WAIT_SECONDS
            )
            if link:
                self.browser.goto(link)
                if self.run_logger:
                    self.run_logger.log("auth_email_link_verified", portal=portal)

        email_value = _extract_email_value(filled)
        repository.upsert_credential(
            job.platform, portal, username=email_value, password=password, email=email_value
        )
        if self.run_logger:
            self.run_logger.log("auth_register_completed", platform=job.platform, portal=portal)
        return AuthResult(outcome="authenticated", filled_fields=filled)


# ---------------------------------------------------------------------------
# 邮箱验证码自动回答：包一层 QuestionChannel
# ---------------------------------------------------------------------------


class _EmailVerifyingChannel(QuestionChannel):
    """拦截「形似邮箱验证码」的问题，用 `EmailVerifier` 自动作答；其余问题原样
    转发给真正的通道。`ask()` 的顺序保证与原始 `questions` 一致（`QuestionChannel`
    契约要求），所以先分流再按原始下标拼回去，而不是简单地把两批结果首尾相接。
    """

    def __init__(
        self,
        inner: QuestionChannel,
        email_verifier: EmailVerifier,
        portal: str,
        run_logger: RunLogger | None = None,
    ) -> None:
        self._inner = inner
        self._email_verifier = email_verifier
        self._portal = portal
        self._run_logger = run_logger

    def ask(self, questions: list[Question], timeout: float) -> list[Answer] | Timeout:
        if not questions:
            return []

        answers_by_index: dict[int, Answer] = {}
        remaining: list[tuple[int, Question]] = []
        for index, question in enumerate(questions):
            if _looks_like_verification_question(question):
                code = self._email_verifier.fetch_code(sender_filter=self._portal)
                if code:
                    if self._run_logger:
                        self._run_logger.log(
                            "email_verification_code_fetched", question=question.question
                        )
                    answers_by_index[index] = Answer(question=question, answer=code)
                    continue
            remaining.append((index, question))

        if remaining:
            inner_answers = self._inner.ask([q for _, q in remaining], timeout)
            if inner_answers is TIMEOUT:
                return TIMEOUT
            for (index, _), answer in zip(remaining, inner_answers):
                answers_by_index[index] = answer

        return [answers_by_index[i] for i in range(len(questions))]


def _looks_like_verification_question(question: Question) -> bool:
    text = (question.question or "").lower()
    return any(keyword in text for keyword in _VERIFICATION_KEYWORDS)


def _seed_password_into_bio(engine: FillEngine, password: str) -> None:
    for slug in _PASSWORD_FIELD_SLUGS:
        engine.bio_store.write_path(f"form_answers.{slug}", password)


def _mask_password_in_fields(
    fields: list[FilledField], password: str
) -> list[FilledField]:
    """把 filled_fields 里等于本次生成密码的填值遮罩成 "********"。

    注册复用 `engine.run_form()`，engine 无从知道某个 BIO 值是密码，会照常把它
    记进 filled_fields；本函数在 auth 边界上按值精确匹配遮罩，避免明文密码随
    审计记录/日志外泄（凭据表另存一份明文是 PRD 六的显式要求，不受影响）。
    """
    if not password:
        return fields
    return [
        FilledField(question=f.question, value="********", value_source=f.value_source)
        if f.value == password
        else f
        for f in fields
    ]


def _extract_email_value(filled_fields: list[FilledField]) -> str | None:
    for filled in filled_fields:
        candidate = filled.value.strip()
        if _EMAIL_PATTERN.match(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# 登录：定向填字段的启发式（不经 LLM）
# ---------------------------------------------------------------------------

_USERNAME_KEYWORDS = ("email", "username", "user name", "login", "账号", "邮箱")
_SUBMIT_KEYWORDS = ("log in", "login", "sign in", "submit", "登录", "提交")


def _fill_login_fields(page, credential: repository.Credential) -> list[FilledField]:
    snapshot = collect_page(page)
    filled: list[FilledField] = []
    username_value = credential.username or credential.email

    for element in snapshot.elements:
        selector = snapshot.selector_map[element.element_id]
        if element.tag == "input" and element.type == "password":
            if not credential.password:
                continue
            browser_primitives.apply_action(page, selector, "fill", credential.password)
            # 密码本体不进审计记录（凭据表里本就明文存了一份，filled_fields
            # 是给人看的运行摘要，没理由再多一份可能被日志系统采集的明文）。
            filled.append(
                FilledField(
                    question=element.label or "password",
                    value="********",
                    value_source=FieldValueSource.BIO,
                )
            )
        elif username_value and _looks_like_username_field(element):
            browser_primitives.apply_action(page, selector, "fill", username_value)
            filled.append(
                FilledField(
                    question=element.label or "username",
                    value=username_value,
                    value_source=FieldValueSource.BIO,
                )
            )
    return filled


def _looks_like_username_field(element: PageElement) -> bool:
    if element.tag != "input":
        return False
    if element.type == "email":
        return True
    haystack = " ".join(
        part for part in (element.name, element.label, element.placeholder) if part
    ).lower()
    return any(keyword in haystack for keyword in _USERNAME_KEYWORDS)


def _click_submit(page) -> None:
    snapshot = collect_page(page)
    buttons = [e for e in snapshot.elements if e.tag == "button"]

    for element in buttons:
        label = (element.label or "").lower()
        if any(keyword in label for keyword in _SUBMIT_KEYWORDS):
            browser_primitives.apply_action(page, snapshot.selector_map[element.element_id], "click")
            return

    # 兜底：找不到语义匹配的按钮，退而求其次点第一个按钮（多数登录表单只有
    # 一个提交按钮，没有语义标签也大概率就是它）。
    if buttons:
        browser_primitives.apply_action(page, snapshot.selector_map[buttons[0].element_id], "click")
