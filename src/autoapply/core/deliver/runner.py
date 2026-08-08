"""autoapply.core.deliver.runner —— run 编排：单 worker 顺序驱动全部职位的状态机（决策六/七/八，PRD 九）。

`run_delivery()` 是本模块唯一的公开入口，串起阶段 0-7 交付的全部构件，按
Phase 7 review 定的精确顺序驱动每个职位的状态机（见下），产出 `RunSummary`。
CLI（`cli/main.py`）只是薄薄一层包这个函数——真正的编排逻辑全在这里
（CLAUDE.md「核心逻辑与界面分离」）。

**编排顺序 + outcome → DeliveryStatus 映射**（逐字对照 Phase 7 review 结论，
`_process_job()` 就是这段伪代码的直译）：

```
adapter = select_adapter(job.url); None → FAILED("no_adapter")
PENDING→OPENING; adapter.open_application(browser, job, settings, run_logger):
  failed     → OPENING→FAILED(reason)
  needs_auth → OPENING→AUTHENTICATING; pre_url = browser.page.url
               Authenticator.authenticate(job, adapter.portal_id(job)):
                 failed        → AUTHENTICATING→FAILED(reason)   # reason 可能是 "captcha_unsolved"
                 suspended     → AUTHENTICATING→WAITING_USER→SUSPENDED（阶段 8 补的边，见 state_machine.py）
                 authenticated → if not adapter.login_succeeded(browser.page, pre_auth_url=pre_url):
                                     AUTHENTICATING→FAILED("login_failed")
                                 else: AUTHENTICATING→FILLING
  on_form    → OPENING→FILLING
FILLING: engine.run_form(job):
  failed    → FILLING→FAILED(reason)
  suspended → FILLING→WAITING_USER→SUSPENDED (+save_suspended_questions)
  completed → 停在 FILLING，再 confirm_and_submit(page, job, mode=settings.deliver.mode,
                 question_channel, adapter=adapter, settings, run_logger):
    suspended → FILLING→WAITING_USER→SUSPENDED (+把确认问题存进挂起问题表) ⇒ SUSPENDED
    declined  → FILLING→READY_TO_SUBMIT→FAILED("user_declined_submit")    ⇒ FAILED
    failed    → FILLING→READY_TO_SUBMIT→SUBMITTING→FAILED(reason)         ⇒ FAILED
    succeeded → FILLING→READY_TO_SUBMIT→SUBMITTING→CONFIRMING→SUCCEEDED   ⇒ SUCCEEDED
```

**持久化纪律**（阶段 2 交接）：`repository.record_delivery()` **只在终态
（SUCCEEDED/FAILED）或 SUSPENDED 时调用一次**，绝不在中途状态调用；挂起时
额外调 `save_suspended_questions()`；从挂起恢复重投的职位处理完（走到终态，
不是又一次挂起）后额外调 `clear_suspended_questions()`——重新挂起的场景故意
不清（见下面「挂起恢复」一节，靠 `resuspendable_jobs()` 的
`HAVING MIN(answered)=1` 自然处理）。每一步状态转移与关键动作都记进
`RunLogger`（决策九过程审计），不进 `deliveries` 表。

**挂起恢复（决策八）**：run 开头用 `repository.resuspendable_jobs()` 拉取全部
问题已补答的挂起职位，按 `job.score` 降序排列，**排在新职位队列最前面**；
`get_delivered_job_keys()` 过滤掉的新任务里天然已经包含这些挂起职位的键
（`record_delivery(SUSPENDED)` 已经写过一次），所以它们不会在 `new_tasks`
里被当成新职位重复出现。恢复态职位处理完：
- 走到 SUCCEEDED/FAILED（终态）→ `clear_suspended_questions()` 清掉旧的
  已答问题记录，避免残留脏数据。
- 又一次 SUSPENDED（同一批或新一批拿不准字段）→ **不清**：旧的已答问题行
  还留着（反正 `answered=1`，不影响判定），`save_suspended_questions()` 插入
  的新一批问题 `answered=0`；`resuspendable_jobs()` 的 `GROUP BY ... HAVING
  MIN(answered)=1` 会在新一批也被答完前，自然地不再把这个职位算作「可重投」
  ——不需要显式清理就能正确处理「重投又挂起」的连续挂起场景。

**恢复态的材料从哪来**：`DeliveryTask`（含 `resume_pdf`/`cover_letter_pdf`）
是搜索+改简历模块喂给 deliver 的输入，deliver 自己的存储（`deliveries`/
`suspended_questions` 表）只落了 `JobRef`，没有留材料路径——`resuspendable_jobs()`
只能给回 `JobRef`。搜索模块按决策八不会再把挂起职位当新职位喂回来（否则
「恢复=重投」会和「搜索模块去重」互相打架），所以 runner 必须自己重建材料
路径。这里退回 spec 决策五「PDF 路径约定」——`data/artifacts/<platform>/
<job_id>/resume.pdf`（及 `cover_letter.pdf`）——**仅用于恢复态**：正常新任务
路径依然由调用方在 `DeliveryTask` 里显式传路径（约定不是契约的隐式依赖，
见决策五），只有在 deliver 自己手上确实没有别的材料来源时，才退回这个约定
目录当兜底（`_resurrection_task()`）。

**材料怎么到达 upload 动作**（阶段 8 交办的插座）：`engine.py`/
`core.llm.cli_client` 不能改，`cli_client._SYSTEM_PROMPT` 第 4 条让 LLM 对
upload 字段留空 value（假设「引擎自己知道路径」），但 `engine._apply_actionable()`
并没有为 upload 做特殊注入——这是留给阶段 8 的插座，不是本阶段的疏漏。选定
的接法：`_seed_materials_into_bio()` 在每个职位开跑前，把这个职位的
`resume_pdf`/`cover_letter_pdf` 路径写进 `bio_store` 的 `form_answers.<slug>`
命名空间（跟 `auth.py` 预写密码同一个套路），命中常见的简历/求职信上传字段
名后，`engine._bio_excerpt()` 会在下次 `decide()` 时把这条路径读进
`bio_excerpt`，LLM 按系统提示规则一（bio 命中直接用值）有机会把它当
`action="upload"` 的 `value` 用上；命中不了就让该字段照常触发 `needs_user`，
不是致命失败。

**简历错投 bug 及其修复（阶段 8 集成期）**：`resume_pdf` 是改简历模块**按职位
定制**的产物（CLAUDE.md 模块简介），逐职位可能不同——语义上跟
`FieldValueSource.LLM_GENERATED`（逐职位定制、不能跨职位缓存）是一类东西。
但它是从 `bio_store` 读出来的，LLM 大概率会把它标成 `FieldValueSource.BIO`
（系统提示规则一的字面意思）。如果 `engine._is_cross_job_cacheable()` 只排除
`LLM_GENERATED`，那么两个职位命中同一个 `SelectorCache`（本 run 内跨职位共享，
见下）、同一个结构指纹、且都有上传字段时，第二个职位就会被缓存重放成第一个
职位的简历路径——**把 A 的简历上传到 B 职位**（真实错投）。修法（阶段 8 允许
的跨阶段修正）：让 `_is_cross_job_cacheable()` 额外排除任何 `action="upload"`
的决策——上传目标是逐职位定制材料，含上传的页面一律不跨职位缓存，每个职位
各自重新推理、各自读回自己 `_seed_materials_into_bio()` 写下的路径。这样既
保住了「同一候选人跨职位共享缓存」的省 token 设计（`test_engine.py::
TestSelectorCache` 依赖它），又根除了错投。回归测试见
`test_runner.py::TestResumeCrossJob`。

**SelectorCache 的生命周期**：本 run 全程一个实例（构造在 `run_delivery()`
层面），跨职位共享——「候选人」指跑这次 run 的这个人（一份 `bio_store`），
不是「职位」；见 `selector_cache.py` 模块文档「跨职位安全边界」与上一段。
不同 `run_delivery()`调用（不同候选人/不同次运行）各自拿新实例，互不污染。

**Easy Apply 计数**：决策八的 LinkedIn Easy Apply 专属日限，本阶段 Workday-only
MVP 不触发，本模块不调用 `repository.increment_easy_apply()`（阶段 2 已建好
存储骨架，留给未来 LinkedIn 适配接线）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from autoapply.core.bio.store import BioStore, YamlBioStore
from autoapply.core.config import Settings
from autoapply.core.contracts import (
    DeliveryRecord,
    DeliveryStatus,
    DeliveryTask,
    FilledField,
    JobRef,
    Question,
    RunSummary,
)
from autoapply.core.deliver.adapters.base import select_adapter
from autoapply.core.deliver.auth import Authenticator
from autoapply.core.deliver.browser import BrowserSession
from autoapply.core.deliver.email_verify import EmailVerifier
from autoapply.core.deliver.engine import FillEngine
from autoapply.core.deliver.selector_cache import SelectorCache
from autoapply.core.deliver.state_machine import IllegalTransition, JobStateMachine
from autoapply.core.deliver.submit import confirm_and_submit
from autoapply.core.llm.cli_client import CliLLMClient
from autoapply.core.llm.client import LLMClient
from autoapply.core.questions.channel import QuestionChannel
from autoapply.core.storage import repository
from autoapply.core.storage.run_log import RunLogger

S = DeliveryStatus

# spec 决策五「PDF 路径约定」——恢复态职位重建材料路径时的唯一来源（见模块文档）。
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ARTIFACTS_ROOT = _REPO_ROOT / "data" / "artifacts"

# 材料预写进 bio_store 的候选字段 slug（form_answers 命名空间，跟
# auth._PASSWORD_FIELD_SLUGS 同一套「多试几个常见命名，命中不了就多问一次」
# 的启发式，见模块文档「材料怎么到达 upload 动作」）。
_RESUME_FIELD_SLUGS = (
    "resume",
    "resume_cv",
    "resume_upload",
    "resume_attachment",
    "attach_resume",
    "upload_resume",
    "cv",
)
_COVER_LETTER_FIELD_SLUGS = (
    "cover_letter",
    "cover_letter_upload",
    "coverletter",
    "upload_cover_letter",
    "attach_cover_letter",
)


def run_delivery(
    tasks: list[DeliveryTask],
    *,
    settings: Settings,
    question_channel: QuestionChannel,
    llm_client: LLMClient | None = None,
    browser=None,
    bio_store: BioStore | None = None,
    run_id: str | None = None,
    repository_db_path: str | Path | None = None,
    logs_dir: str | Path | None = None,
    force_keys: set[tuple[str, str]] | None = None,
) -> RunSummary:
    """单 worker 顺序驱动一次 run（PRD 九：全部过阈值职位都投，不设上限）。

    `browser`：不传则按 `settings.browser.headless` 起一个真实
    `BrowserSession`（`with` 块内全程复用同一个浏览器 context）；传入时按现成
    的 `.page`/`.goto()` 鸭子类型对象直接用（测试注入假浏览器，调用方负责其
    生命周期，本函数不会尝试 `__enter__`/`__exit__` 它）。

    `llm_client`/`bio_store` 缺省分别退回 `CliLLMClient(settings.llm)` 与
    `YamlBioStore()`（生产默认路径）；测试传脚本化替身。

    `run_id` 缺省生成一个 uuid4 十六进制串；`repository_db_path`/`logs_dir`
    透传给存储层/`RunLogger`，测试用临时路径隔离，不碰真实 `data/`/`logs/`。

    `force_keys`：显式绕开 `get_delivered_job_keys()` 去重的职位键集合——
    专供 `deliver retry`（决策八「留 CLI 命令按 job key 手动重投单个职位」）：
    普通 run 靠去重防止已处理过的职位被重复排队，但手动重投恰恰是要故意
    再投一次已经在 `deliveries` 表里的（FAILED）职位，两者不冲突——`retry`
    命令把要重投的那一个 key 放进 `force_keys`，其余职位的去重规则不受影响。
    """
    run_id = run_id or uuid.uuid4().hex
    run_logger = RunLogger(run_id, logs_dir=logs_dir)
    repository.record_run_start(run_id, db_path=repository_db_path)

    resolved_llm_client = llm_client or CliLLMClient(settings.llm)
    resolved_bio_store = bio_store or YamlBioStore()
    # 本 run 全程一个实例，跨职位共享（见模块文档「SelectorCache 的生命周期」）。
    selector_cache = SelectorCache()
    email_verifier = _build_email_verifier(settings)

    queue, resurrected_keys = _build_queue(tasks, repository_db_path, force_keys or set())
    run_logger.log(
        "run_started",
        run_id=run_id,
        total_queued=len(queue),
        resurrected=len(resurrected_keys),
    )

    common_kwargs = dict(
        settings=settings,
        question_channel=question_channel,
        llm_client=resolved_llm_client,
        bio_store=resolved_bio_store,
        selector_cache=selector_cache,
        email_verifier=email_verifier,
        run_logger=run_logger,
        run_id=run_id,
        db_path=repository_db_path,
    )

    if browser is not None:
        summary = _drive_queue(queue, resurrected_keys, browser=browser, **common_kwargs)
    else:
        with BrowserSession(
            user_data_dir=settings.browser.user_data_dir, headless=settings.browser.headless
        ) as session:
            summary = _drive_queue(queue, resurrected_keys, browser=session, **common_kwargs)

    repository.record_run_summary(run_id, summary, db_path=repository_db_path)
    run_logger.log(
        "run_finished",
        run_id=run_id,
        total=summary.total,
        succeeded=summary.succeeded,
        failed=sum(summary.failed_by_reason.values()),
        suspended=len(summary.suspended),
    )
    return summary


# ---------------------------------------------------------------------------
# 队列构建：挂起恢复优先 + 新任务分数降序 + 去重（决策八）
# ---------------------------------------------------------------------------


def _build_queue(
    tasks: list[DeliveryTask],
    db_path: str | Path | None,
    force_keys: set[tuple[str, str]],
) -> tuple[list[DeliveryTask], set[tuple[str, str]]]:
    resurrected_jobs = sorted(
        repository.resuspendable_jobs(db_path=db_path), key=lambda j: j.score, reverse=True
    )
    resurrected_tasks = [_resurrection_task(job) for job in resurrected_jobs]
    resurrected_keys = {t.job.key for t in resurrected_tasks}

    # get_delivered_job_keys() 回喂的是「deliver 已处理过」的全部键（含
    # SUSPENDED），挂起恢复职位的键天然已经在里面——按 job.key 过滤一遍
    # incoming tasks 就自动把它们从「新任务」里排除掉，不会跟恢复队列重复。
    # force_keys（deliver retry 专用，见 run_delivery 文档）显式绕开这条过滤。
    delivered_keys = repository.get_delivered_job_keys(db_path=db_path)
    new_tasks = sorted(
        (t for t in tasks if t.job.key not in delivered_keys or t.job.key in force_keys),
        key=lambda t: t.job.score,
        reverse=True,
    )
    return resurrected_tasks + new_tasks, resurrected_keys


def _resurrection_task(job: JobRef) -> DeliveryTask:
    """恢复态职位重建 `DeliveryTask`：退回 spec 决策五的 PDF 路径约定当兜底
    （唯一可用来源，见模块文档「恢复态的材料从哪来」）。"""
    platform, job_id = job.key
    artifacts_dir = _ARTIFACTS_ROOT / platform / job_id
    resume_pdf = artifacts_dir / "resume.pdf"
    cover_letter_pdf = artifacts_dir / "cover_letter.pdf"
    return DeliveryTask(
        job=job,
        resume_pdf=resume_pdf,
        cover_letter_pdf=cover_letter_pdf if cover_letter_pdf.exists() else None,
    )


def _build_email_verifier(settings: Settings) -> EmailVerifier | None:
    """只有真的配置了 IMAP 凭据才构造——未配置时 `Authenticator` 拿到 `None`，
    验证码问题原样转发真人问询通道（阶段 6 既有降级路径），不会尝试连一个
    没配置好的邮箱而炸掉整个 run。"""
    if settings.imap.username and settings.imap.password:
        return EmailVerifier(settings)
    return None


# ---------------------------------------------------------------------------
# 驱动整条队列
# ---------------------------------------------------------------------------


def _drive_queue(
    queue: list[DeliveryTask],
    resurrected_keys: set[tuple[str, str]],
    *,
    browser,
    settings: Settings,
    question_channel: QuestionChannel,
    llm_client: LLMClient,
    bio_store: BioStore,
    selector_cache: SelectorCache,
    email_verifier: EmailVerifier | None,
    run_logger: RunLogger,
    run_id: str,
    db_path: str | Path | None,
) -> RunSummary:
    total = 0
    succeeded = 0
    failed_by_reason: dict[str, int] = {}
    suspended: list[JobRef] = []
    unanswered_questions: list[Question] = []

    for task in queue:
        total += 1
        is_resurrected = task.job.key in resurrected_keys
        try:
            status, reason, questions = _process_job(
                task,
                browser=browser,
                settings=settings,
                question_channel=question_channel,
                llm_client=llm_client,
                bio_store=bio_store,
                selector_cache=selector_cache,
                email_verifier=email_verifier,
                run_logger=run_logger,
                run_id=run_id,
                db_path=db_path,
                is_resurrected=is_resurrected,
            )
        except Exception as exc:  # noqa: BLE001 — 无人值守闭环的最后一道防线：
            # _process_job 内部已经把常规失败都兜进了它自己的 try/except，这里
            # 只会在极端情况下触发（例如 finalize 落库本身失败），依然不能
            # 让一个职位的崩溃拖死整条队列（决策七/八）。
            run_logger.log(
                "job_crashed_outside_process_job",
                platform=task.job.platform,
                job_id=task.job.job_id,
                error=str(exc),
            )
            status, reason, questions = S.FAILED, f"unexpected_error: {exc}", []

        if status is S.SUCCEEDED:
            succeeded += 1
        elif status is S.FAILED:
            key = reason or "unknown"
            failed_by_reason[key] = failed_by_reason.get(key, 0) + 1
        elif status is S.SUSPENDED:
            suspended.append(task.job)
            unanswered_questions.extend(questions)

    return RunSummary(
        run_id=run_id,
        total=total,
        succeeded=succeeded,
        failed_by_reason=failed_by_reason,
        suspended=suspended,
        unanswered_questions=unanswered_questions,
    )


# ---------------------------------------------------------------------------
# 单个职位：驱动状态机（编排顺序见模块文档）
# ---------------------------------------------------------------------------


def _process_job(
    task: DeliveryTask,
    *,
    browser,
    settings: Settings,
    question_channel: QuestionChannel,
    llm_client: LLMClient,
    bio_store: BioStore,
    selector_cache: SelectorCache,
    email_verifier: EmailVerifier | None,
    run_logger: RunLogger,
    run_id: str,
    db_path: str | Path | None,
    is_resurrected: bool,
) -> tuple[DeliveryStatus, str | None, list[Question]]:
    job = task.job
    platform, job_id = job.key
    started_at = datetime.now(timezone.utc)
    sm = JobStateMachine()  # 每个职位一个新状态机，从 PENDING 开始
    accumulated_filled: list[FilledField] = []

    run_logger.log(
        "job_started",
        platform=platform,
        job_id=job_id,
        title=job.title,
        company=job.company,
        resurrected=is_resurrected,
    )

    def advance(dst: DeliveryStatus, *, reason: str | None = None) -> None:
        src = sm.status
        sm.to(dst, reason=reason)
        run_logger.log(
            "state_transition",
            platform=platform,
            job_id=job_id,
            src=src.value,
            dst=dst.value,
            reason=reason,
        )

    def finalize(
        status: DeliveryStatus, reason: str | None, questions: list[Question] | None = None
    ) -> tuple[DeliveryStatus, str | None, list[Question]]:
        finished_at = datetime.now(timezone.utc)
        record = DeliveryRecord(
            job=job,
            status=status,
            filled_fields=accumulated_filled,
            failure_reason=reason,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
        )
        repository.record_delivery(record, db_path=db_path)
        if status is S.SUSPENDED:
            repository.save_suspended_questions(job, questions or [], db_path=db_path)
        elif is_resurrected:
            # 只有走到终态才清（不是又一次挂起）——见模块文档「挂起恢复」。
            repository.clear_suspended_questions(platform, job_id, db_path=db_path)
        run_logger.log(
            "job_finished", platform=platform, job_id=job_id, status=status.value, reason=reason
        )
        return status, reason, list(questions or [])

    try:
        advance(S.OPENING)

        adapter = select_adapter(str(job.url))
        if adapter is None:
            advance(S.FAILED, reason="no_adapter")
            return finalize(S.FAILED, "no_adapter")

        open_result = adapter.open_application(browser, job, settings, run_logger)
        if open_result.outcome == "failed":
            advance(S.FAILED, reason=open_result.reason)
            return finalize(S.FAILED, open_result.reason)

        engine = FillEngine(
            browser.page,
            llm_client,
            bio_store,
            question_channel,
            run_logger,
            settings,
            selector_cache,
        )
        _seed_materials_into_bio(bio_store, task)

        if open_result.outcome == "needs_auth":
            advance(S.AUTHENTICATING)
            pre_auth_url = browser.page.url
            authenticator = Authenticator(browser, engine, settings, run_logger, email_verifier)
            auth_result = authenticator.authenticate(job, adapter.portal_id(job))
            accumulated_filled.extend(auth_result.filled_fields)

            if auth_result.outcome == "failed":
                advance(S.FAILED, reason=auth_result.reason)
                return finalize(S.FAILED, auth_result.reason)
            if auth_result.outcome == "suspended":
                advance(S.WAITING_USER)
                advance(S.SUSPENDED)
                return finalize(S.SUSPENDED, None, auth_result.pending_questions)

            # authenticated 是乐观结果，进 FILLING 前必须复核（阶段 7 交接）。
            if not adapter.login_succeeded(browser.page, pre_auth_url=pre_auth_url):
                advance(S.FAILED, reason="login_failed")
                return finalize(S.FAILED, "login_failed")
            advance(S.FILLING)
        else:  # "on_form"
            advance(S.FILLING)

        fill_result = engine.run_form(job)
        accumulated_filled.extend(fill_result.filled_fields)

        if fill_result.outcome == "failed":
            advance(S.FAILED, reason=fill_result.failure_reason)
            return finalize(S.FAILED, fill_result.failure_reason)
        if fill_result.outcome == "suspended":
            advance(S.WAITING_USER)
            advance(S.SUSPENDED)
            return finalize(S.SUSPENDED, None, fill_result.pending_questions)

        # completed：停在 FILLING，先拿确认结果再决定要不要推进状态机
        # （submit.py 模块文档的明确要求，避免 READY_TO_SUBMIT 没有 →SUSPENDED
        # 边这个状态机坑）。
        submit_result = confirm_and_submit(
            browser.page,
            job,
            mode=settings.deliver.mode,
            question_channel=question_channel,
            adapter=adapter,
            settings=settings,
            run_logger=run_logger,
        )

        if submit_result.outcome == "suspended":
            advance(S.WAITING_USER)
            advance(S.SUSPENDED)
            confirm_question = Question(
                job=job,
                field_path=None,
                question=(
                    f"即将提交「{job.company} - {job.title}」的申请，确认提交吗？(y/n)"
                ),
                page="submit_confirm",
            )
            return finalize(S.SUSPENDED, None, [confirm_question])
        if submit_result.outcome == "declined":
            advance(S.READY_TO_SUBMIT)
            advance(S.FAILED, reason="user_declined_submit")
            return finalize(S.FAILED, "user_declined_submit")
        if submit_result.outcome == "failed":
            advance(S.READY_TO_SUBMIT)
            advance(S.SUBMITTING)
            advance(S.FAILED, reason=submit_result.reason)
            return finalize(S.FAILED, submit_result.reason)

        # succeeded
        advance(S.READY_TO_SUBMIT)
        advance(S.SUBMITTING)
        advance(S.CONFIRMING)
        advance(S.SUCCEEDED)
        return finalize(S.SUCCEEDED, None)

    except Exception as exc:  # noqa: BLE001 — 一个职位崩溃不能拖死整个 run（决策七/八）
        reason = f"unexpected_error: {exc}"
        run_logger.log("job_crashed", platform=platform, job_id=job_id, error=str(exc))
        try:
            advance(S.FAILED, reason=reason)
        except IllegalTransition:
            pass  # 已经在终态/转移非法时不因二次转移失败丢结果，仍按下面 finalize 落 FAILED
        try:
            return finalize(S.FAILED, reason)
        except Exception as finalize_exc:  # noqa: BLE001 — 连落库都失败也不能拖死整条队列
            run_logger.log(
                "job_finalize_failed",
                platform=platform,
                job_id=job_id,
                error=str(finalize_exc),
            )
            return S.FAILED, reason, []


def _seed_materials_into_bio(bio_store: BioStore, task: DeliveryTask) -> None:
    """把这个职位的材料路径预写进 `bio_store`，供 upload 字段决策使用（见模块
    文档「材料怎么到达 upload 动作」及其「已知的残余风险」）。每个职位开跑前
    都会重新调用一次，用当前职位的路径覆盖上一个职位写下的值——保证非缓存
    命中路径下的决策总能读到当前职位自己的材料。
    """
    resume_path = str(task.resume_pdf)
    for slug in _RESUME_FIELD_SLUGS:
        bio_store.write_path(f"form_answers.{slug}", resume_path)
    if task.cover_letter_pdf is not None:
        cover_path = str(task.cover_letter_pdf)
        for slug in _COVER_LETTER_FIELD_SLUGS:
            bio_store.write_path(f"form_answers.{slug}", cover_path)
