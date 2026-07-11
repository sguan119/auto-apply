"""core.deliver.engine —— FILLING 循环：DOM → LLM → Playwright，逐页（决策四）。

这是整套自研执行架构的心脏：`FillEngine.run_form()` 从当前页开始，逐页跑
`collect_page → (缓存命中?)decide → 执行 actionable → 处理 uncertain(问询→
回写→重决策) → 判断是否翻页/结束`，直到整个表单流程完结、挂起或失败。

**与 runner（阶段 8）的边界**：engine 不导入 `state_machine`/`repository`，
只返回结构化结果（`RunFormResult`）——runner 负责把 `outcome` 翻译成状态机
转移、把 `pending_questions` 落库为挂起问题、把 `filled_fields`/
`bio_writebacks` 写进 `DeliveryRecord`/审计日志。engine 只认注入进来的
`LLMClient`/`BioStore`/`QuestionChannel`/`RunLogger`，不知道它们的实现。

**次页推进的实现方式**：LLM 对整页决策时，「翻到下一页」的按钮本身就是
`PageContext.elements` 里的一个编号元素，LLM 对它的决策是普通的
`action="click"`——翻页动作在「执行 actionable 决策」这一步就已经发生了；
`PageDecision.next_action` 只是一个路由提示（见 `core.llm.client` 文档），
用来告诉 engine「这次翻页/结束的意图是什么」，不需要 engine 自己再猜。所以
`run_form()` 看到 `next_action == "submit_page"` 时**不会**再去找一个「下一步」
按钮点——点击已经在同一轮里做完了，`run_form()` 只需要重新 `collect_page()`
读新页面。`next_action` 为 `None`（例如这一轮只是点了「添加一段工作经历」
这种 repeater 按钮，DOM 结构变了但还是同一个逻辑页）则留在 `fill_current_page()`
内部继续循环，不当作一页的结束交给 `run_form()`。

**uncertain → 问询 → 回写 → 重决策**：一页存在 `needs_user` 决策时，
`fill_current_page()` 把它们打包成一批 `Question` 扔给 `QuestionChannel.ask()`
（决策七按页批量）。超时（`is TIMEOUT`）直接把这一页标 `suspended` 返回，
附带这批 `Question`（供 runner 落挂起问题表 / 汇总 `RunSummary`）。拿到
`Answer` 后先 `bio_store.write_path()` 回写，再强制绕过 selector_cache 重新
调用一次 `llm_client.decide()`（DOM 结构没变，指纹不变，但 bio 数据变了，
不能用旧缓存）——engine 会把这次重新拿到的、不再含 `needs_user` 的决策存回
缓存，这样同一结构指纹下次出现时（哪怕是全新的 `Page` 实例）能直接命中，
连问询都不用再问一次。

**Workday 通用容错**（不硬编码 Workday，供阶段 7 的 Workday 适配复用）：
- 可搜索下拉：由 `browser.apply_action()` 按目标是否原生 `<select>` 分流，
  非原生走「键入+Enter」（不在这里重复判断）。
- 可选/缺失字段：`element_id` 在本轮快照里找不到选择器，或应用动作时
  Playwright 抛错，都只记录一条日志然后跳过，不让整页崩掉。
- work-history repeater：LLM 点击「添加一段」按钮后 `next_action` 通常是
  `None`——`fill_current_page()` 的内层循环会重新 `collect_page()` 看到新
  出现的字段块，按普通字段继续走。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from core.bio.store import BioStore
from core.config import Settings, load_settings
from core.contracts import Answer, BioWriteback, FieldValueSource, FilledField, JobRef, Question
from core.deliver import browser as browser_primitives
from core.deliver.dom import PageSnapshot, collect_page
from core.deliver.selector_cache import CacheEntry, SelectorCache, compute_fingerprint
from core.llm.client import ElementDecision, LLMClient, LLMDecisionError, PageContext, PageElement
from core.questions.channel import TIMEOUT, QuestionChannel
from core.storage.run_log import RunLogger

# bio 里承接「问询回答」的保留命名空间（不是锁 schema——bio 结构本就未定，
# 这只是 engine 自己一致遵守的写入约定，未来 bio schema 落地时可以整体
# 迁移/重新映射这个命名空间下的键，不影响 engine 逻辑）。
_ANSWER_FIELD_PATH_PREFIX = "form_answers"

# 单页内部「decide → 应用 → (问询→重决策)」循环的安全阀，避免任何未预见的
# 死循环（例如脚本化/坏掉的 LLM 客户端反复触发同一个 repeater 点击）拖死
# 一整个 run。真实表单不太可能超过这个轮数。
_MAX_ROUNDS_PER_PAGE = 20

# run_form() 逐页推进的安全阀，理由同上。
_DEFAULT_MAX_PAGES = 30

PageOutcome = Literal["submit_page", "done", "suspended", "failed"]
RunOutcome = Literal["completed", "suspended", "failed"]


@dataclass
class PageResult:
    """`fill_current_page()` 的返回：这一页跑完/挂起/失败时的结果。"""

    outcome: PageOutcome
    filled: list[FilledField] = field(default_factory=list)
    bio_writebacks: list[BioWriteback] = field(default_factory=list)
    pending_questions: list[Question] = field(default_factory=list)  # outcome=="suspended" 时非空
    failure_reason: str | None = None  # outcome=="failed" 时给出


@dataclass
class RunFormResult:
    """`run_form()` 的返回：engine 对阶段 8 runner 的唯一交付物。

    `outcome`：
    - `"completed"`：表单流程正常走完（对应状态机 FILLING → READY_TO_SUBMIT）。
    - `"suspended"`：某页问询超时，`pending_questions` 携带这批未答问题
      （对应状态机 WAITING_USER → SUSPENDED，runner 负责落挂起问题表）。
    - `"failed"`：LLM 决策不可恢复错误 / 翻页轮数耗尽，`failure_reason` 给出
      原因字符串（对应状态机 → FAILED(reason)，runner 负责落 `DeliveryRecord`）。
    """

    outcome: RunOutcome
    filled_fields: list[FilledField] = field(default_factory=list)
    bio_writebacks: list[BioWriteback] = field(default_factory=list)
    pending_questions: list[Question] = field(default_factory=list)
    failure_reason: str | None = None
    pages_completed: int = 0


class FillEngine:
    """FILLING 循环的驱动者。所有协作对象都是注入进来的抽象接口。

    `run_form()` 对「投职位表单」还是「注册/登录表单」一视同仁（阶段 6 auth
    直接复用同一个类/方法）——只要给一个 `Page` 站在表单第一页上，engine 不
    关心这是哪种表单。
    """

    def __init__(
        self,
        page: Page,
        llm_client: LLMClient,
        bio_store: BioStore,
        question_channel: QuestionChannel,
        run_logger: RunLogger | None = None,
        settings: Settings | None = None,
        selector_cache: SelectorCache | None = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        self.page = page
        self.llm_client = llm_client
        self.bio_store = bio_store
        self.question_channel = question_channel
        self.run_logger = run_logger
        self.settings = settings or load_settings()
        self.selector_cache = selector_cache or SelectorCache()
        self.max_pages = max_pages

    # ------------------------------------------------------------------
    # 整个表单流程（多页）
    # ------------------------------------------------------------------

    def run_form(
        self,
        job: JobRef,
        *,
        page_hint: str | None = None,
        max_pages: int | None = None,
    ) -> RunFormResult:
        """从当前 `self.page` 所在的第一页开始，逐页驱动直到结束/挂起/失败。

        `job` 是必填的——即便阶段 6 的自动注册表单在语义上「不是投一个职位」，
        状态机层面注册也只发生在 AUTHENTICATING（某个具体职位的投递尝试内），
        所以调用方手上总有一个 `JobRef` 可传（`Question.job` 契约本身也是必填，
        没有 job 就没法构造问询）。
        """
        limit = max_pages if max_pages is not None else self.max_pages
        all_filled: list[FilledField] = []
        all_writebacks: list[BioWriteback] = []
        pages_completed = 0

        for _ in range(limit):
            result = self.fill_current_page(job=job, page_hint=page_hint)
            all_filled.extend(result.filled)
            all_writebacks.extend(result.bio_writebacks)

            if result.outcome == "suspended":
                return RunFormResult(
                    outcome="suspended",
                    filled_fields=all_filled,
                    bio_writebacks=all_writebacks,
                    pending_questions=result.pending_questions,
                    pages_completed=pages_completed,
                )
            if result.outcome == "failed":
                return RunFormResult(
                    outcome="failed",
                    filled_fields=all_filled,
                    bio_writebacks=all_writebacks,
                    failure_reason=result.failure_reason,
                    pages_completed=pages_completed,
                )

            pages_completed += 1
            if result.outcome == "done":
                return RunFormResult(
                    outcome="completed",
                    filled_fields=all_filled,
                    bio_writebacks=all_writebacks,
                    pages_completed=pages_completed,
                )
            # outcome == "submit_page"：翻页点击已在 fill_current_page 内执行，
            # 这里只需要重新收集下一页。

        return RunFormResult(
            outcome="failed",
            filled_fields=all_filled,
            bio_writebacks=all_writebacks,
            failure_reason="max_pages_exceeded",
            pages_completed=pages_completed,
        )

    # ------------------------------------------------------------------
    # 单页：decide → 应用 → (问询 → 回写 → 重决策)
    # ------------------------------------------------------------------

    def fill_current_page(
        self, *, job: JobRef, page_hint: str | None = None
    ) -> PageResult:
        """在当前 `self.page` 上跑完一页的循环，直到可翻页/结束，或挂起/失败。"""
        filled: list[FilledField] = []
        writebacks: list[BioWriteback] = []
        force_fresh = False  # 刚回写完 bio 时置 True，强制绕过缓存重新推理一次

        for _ in range(_MAX_ROUNDS_PER_PAGE):
            snapshot = collect_page(self.page)
            fingerprint = compute_fingerprint(snapshot.elements)
            cached = None if force_fresh else self.selector_cache.get(fingerprint)
            force_fresh = False

            if cached is not None:
                decision = cached.decision
                if self.run_logger:
                    self.run_logger.log("selector_cache_hit", fingerprint=fingerprint)
            else:
                context = self._build_context(snapshot.elements, job, page_hint)
                try:
                    decision = self.llm_client.decide(context)
                except LLMDecisionError as exc:
                    if self.run_logger:
                        self.run_logger.log("llm_decision_error", error=str(exc))
                    return PageResult(
                        outcome="failed",
                        filled=filled,
                        bio_writebacks=writebacks,
                        failure_reason=f"llm_decision_error: {exc}",
                    )
                if self.run_logger:
                    self.run_logger.log(
                        "llm_decision",
                        fingerprint=fingerprint,
                        next_action=decision.next_action,
                        decision_count=len(decision.decisions),
                    )

            self._apply_actionable(decision.actionable, snapshot, filled)

            uncertain = decision.uncertain
            if uncertain:
                questions = [self._to_question(d, snapshot, job, page_hint) for d in uncertain]
                answers = self.question_channel.ask(
                    questions, self.settings.deliver.question_timeout
                )
                if answers is TIMEOUT:
                    if self.run_logger:
                        self.run_logger.log("waiting_user_timeout", questions=len(questions))
                    return PageResult(
                        outcome="suspended",
                        filled=filled,
                        bio_writebacks=writebacks,
                        pending_questions=questions,
                    )
                for answer in answers:
                    self._writeback(answer, writebacks)
                force_fresh = True
                continue

            # 本轮没有 needs_user 决策：这个（子）状态已经稳定。但只有当整页
            # 填值都与「投的是哪个职位」无关时，才可以跨职位缓存（缓存键只含
            # 结构指纹、不含 value，命中会把决策连 value 原样套到另一个同结构
            # 页面上——可能是另一个职位）。含 LLM_GENERATED 填值的页面不缓存，
            # 详见 `_is_cross_job_cacheable()`。
            if _is_cross_job_cacheable(decision):
                self.selector_cache.put(fingerprint, CacheEntry(decision=decision))

            if decision.next_action in ("submit_page", "done"):
                return PageResult(
                    outcome=decision.next_action, filled=filled, bio_writebacks=writebacks
                )
            # next_action 是 None（如刚点了 repeater「添加一段」）：DOM 可能
            # 已经变了，继续本页循环重新采集。

        return PageResult(
            outcome="failed",
            filled=filled,
            bio_writebacks=writebacks,
            failure_reason="max_rounds_exceeded",
        )

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _build_context(
        self, elements: list[PageElement], job: JobRef, page_hint: str | None
    ) -> PageContext:
        return PageContext(
            elements=elements,
            job=job,
            bio_excerpt=self._bio_excerpt(elements),
            page_hint=page_hint,
        )

    def _bio_excerpt(self, elements: list[PageElement]) -> dict | None:
        """按本页元素派生候选 bio 路径，尽力探测式摘录。

        `BioStore` 只暴露 `read_path`/`write_path`，没有「读全部」的方法，
        bio schema 本身也未定（spec「待续」），engine 拿不到一份现成的、
        该给 LLM 看哪些字段的清单——只能反过来，用每个页面元素通过
        `_field_path_for()` 派生出的候选路径去试探 `bio_store`，命中的塞进
        摘录字典。这恰好覆盖了本模块最关心的场景：某个 `needs_user` 字段被
        回答并 `write_path()` 回写后，同一 fingerprint 下次出现（本页重新
        决策，或另一页/另一个职位的同结构页面）时，同名字段能在这里被读回
        来，交给 LLM 直接使用而不必再问一次。手工维护在 bio.yaml 其它命名
        空间下的字段（不叫 `form_answers.*`）不会被这条启发式路径覆盖——
        那部分依赖真正的 bio schema 落地后再补齐（不在本阶段范围内）。
        """
        excerpt: dict[str, object] = {}
        for element in elements:
            field_path = _field_path_for(element.element_id, element)
            value = self.bio_store.read_path(field_path)
            if value is not None:
                excerpt[field_path] = value
        return excerpt or None

    def _apply_actionable(
        self,
        decisions: list[ElementDecision],
        snapshot: PageSnapshot,
        filled: list[FilledField],
    ) -> None:
        for decision in decisions:
            selector = snapshot.selector_map.get(decision.element_id)
            if selector is None:
                # 可选/缺失字段容错：LLM 决策引用的编号本轮采集里没有，跳过
                # 不崩（Workday 调研经验：字段存在性容错）。
                if self.run_logger:
                    self.run_logger.log(
                        "element_not_found", element_id=decision.element_id
                    )
                continue
            try:
                browser_primitives.apply_action(
                    self.page, selector, decision.action, decision.value
                )
            except PlaywrightError as exc:
                if self.run_logger:
                    self.run_logger.log(
                        "apply_action_failed",
                        element_id=decision.element_id,
                        action=decision.action,
                        error=str(exc),
                    )
                continue

            if decision.value is not None and decision.value_source is not None:
                element = snapshot.element_by_id(decision.element_id)
                question_text = (element.label if element and element.label else None) or (
                    f"element_{decision.element_id}"
                )
                filled.append(
                    FilledField(
                        question=question_text,
                        value=decision.value,
                        value_source=decision.value_source,
                    )
                )

    def _to_question(
        self,
        decision: ElementDecision,
        snapshot: PageSnapshot,
        job: JobRef,
        page_hint: str | None,
    ) -> Question:
        element = snapshot.element_by_id(decision.element_id)
        field_path = _field_path_for(decision.element_id, element)
        return Question(
            job=job,
            field_path=field_path,
            question=decision.question or "",
            page=page_hint,
        )

    def _writeback(self, answer: Answer, writebacks: list[BioWriteback]) -> None:
        question = answer.question
        if question.field_path:
            self.bio_store.write_path(question.field_path, answer.answer, question.question)
            writebacks.append(
                BioWriteback(
                    field_path=question.field_path,
                    question=question.question,
                    answer=answer.answer,
                )
            )
        if self.run_logger:
            self.run_logger.log(
                "bio_writeback",
                field_path=question.field_path,
                question=question.question,
            )


def _is_cross_job_cacheable(decision: PageDecision) -> bool:
    """判断一个 `PageDecision` 能否跨职位缓存（决策四选择器缓存的安全边界）。

    selector_cache 的键是页面**结构指纹**（`tag`/`name`/`label`/`type`/
    `options`，不含 `value`）。命中时会把缓存里那份决策——连同它的具体
    `value`——原样套到同结构的另一个页面上。这个「另一个页面」很可能属于
    **另一个职位**（决策四的本意就是同一 ATS 模板批量投多个职位时省 token）。
    因此只有当这份决策里所有填值都与「投的是哪个职位」无关时，原样复用才安全：

    - `BIO`：来自候选人 bio，同一候选人跨职位不变 → 安全。
    - `USER_ANSWER`：已回写进 bio（`form_answers` 命名空间），同样是候选人级
      稳定值，正是 `_bio_excerpt` 回读复用的设计意图 → 安全。
    - `LLM_GENERATED`：LLM 针对**具体职位**现场生成（求职信、「为什么想加入
      贵司」等开放式问答）→ 随职位而变。若缓存，A 职位生成的文案会被原样
      泄漏给结构相同的 B 职位（跨职位串味），必须排除。

    **`upload` 动作也必须排除**（阶段 8 集成期发现的真实错投 bug）：附件上传的
    `value` 是文件路径，而简历/求职信是改简历模块**按职位定制**的产物
    （`runner._seed_materials_into_bio` 逐职位把当前职位的 `resume_pdf` 路径
    预写进 `bio_store`）。LLM 从 bio 读回这个路径后大概率把它标成
    `BIO`（而非 `LLM_GENERATED`）——但它跟 `LLM_GENERATED` 一样是**逐职位不同**
    的值。若只按 `value_source` 判定，含上传的这一页会被当成可跨职位缓存：A
    职位缓存下来的决策连同 A 的简历路径，会被原样重放到结构相同的 B 职位，
    导致**把 A 的简历上传到 B 职位**（错投）。因此只要本页存在任一
    `action="upload"` 决策，无论其 `value_source` 是什么，整页都不跨职位缓存。

    所以：本页只要存在任一 `LLM_GENERATED` 填值或任一 `upload` 动作，就整页
    不缓存，让每个职位各自重新推理。代价是这类页面失去 token 节省——但这类
    字段本就应当逐职位定制，重新推理既是安全也是「正确」的选择（token 权衡见
    spec 决策四）。

    注意范围：这里只隔离「跨职位」串味。缓存值中的 `BIO`/`USER_ANSWER` 仍是
    「这个候选人」的值——若把同一个 `SelectorCache` 跨**不同候选人**复用，连
    bio 值也会串。当前批量场景是「一个候选人投多个职位」（共享 cache 合理），
    换候选人应换 cache 实例；候选人级 key 隔离留待持久化缓存落地时补（见
    `selector_cache.py` 扩展点）。
    """
    return not any(
        d.value_source == FieldValueSource.LLM_GENERATED or d.action == "upload"
        for d in decision.actionable
    )


def _field_path_for(element_id: int, element: PageElement | None) -> str:
    """给一个 needs_user 字段派生 bio 回写路径。

    `ElementDecision` 契约没有携带「这个字段对应哪个 bio 路径」的字段（bio
    schema 本就未定，LLM 没有可依赖的路径命名空间），所以这里用一个 engine
    自己的、稳定可复现的约定：优先用 DOM `name`/`id`，其次用标签文本
    slugify，都没有则退化成 `element_<id>`——都挂在 `form_answers.` 命名空间
    下，不与用户手编的 bio 正文字段混在一起。这样同一语义字段（同 name/
    label）跨职位/跨页面重复出现时，一旦回答过一次，未来会写着相同路径，
    真正的 bio schema 落地后可以整体从这个命名空间迁移过去。
    """
    if element is not None and element.name:
        slug = _slugify(element.name)
    elif element is not None and element.label:
        slug = _slugify(element.label)
    else:
        slug = f"element_{element_id}"
    return f"{_ANSWER_FIELD_PATH_PREFIX}.{slug}"


def _slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "field"
