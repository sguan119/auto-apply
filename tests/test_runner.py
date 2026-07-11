"""tests.test_runner —— core.deliver.runner.run_delivery 的端到端编排测试。

不打真实网络/真实 LLM：用真实 headless chromium（同 test_engine.py/
test_auth.py/test_workday_adapter.py 套路）灌 `page.set_content()` fixture 当
Workday 表单；`select_adapter()` 靠 URL host 命中真实 `WorkdayAdapter`（不
mock 掉它——这样才是货真价实的「adapter → engine → submit」全链路集成测试，
只有 LLM 决策和浏览器导航是脚本化的）。DB/日志走临时目录，不碰真实
`data/`/`logs/`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from core.bio.store import BioStore
from core.config import BrowserSettings, DeliverSettings, Settings
from core.contracts import (
    Answer,
    DeliveryStatus,
    DeliveryTask,
    FieldValueSource,
    JobRef,
)
from core.deliver.runner import run_delivery
from core.llm.client import ElementDecision, LLMClient, PageContext, PageDecision
from core.questions.channel import TIMEOUT, AutoAnswerChannel
from core.storage import db, repository


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------


class PerJobLLMClient(LLMClient):
    """按 `PageContext.job.job_id` 派发脚本/异常的假 LLM 客户端。

    `scripts` 是 `job_id -> PageDecision 列表`（FIFO 回放）；`raises` 是
    `job_id -> Exception`，命中即抛（用于模拟「某个职位处理中途崩溃」，
    不是 `LLMDecisionError` 那种 engine 自己能优雅捕获的失败，而是真正未预期
    的异常，专门验证 runner 自己的 try/except 兜底）。
    """

    def __init__(
        self,
        scripts: dict[str, list[PageDecision]] | None = None,
        raises: dict[str, Exception] | None = None,
    ) -> None:
        self._scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self._raises = raises or {}
        self.contexts: list[PageContext] = []

    def decide(self, page_context: PageContext) -> PageDecision:
        self.contexts.append(page_context)
        job_id = page_context.job.job_id if page_context.job else None
        if job_id in self._raises:
            raise self._raises[job_id]
        script = self._scripts.get(job_id)
        if not script:
            raise AssertionError(f"PerJobLLMClient 脚本已耗尽或未配置：job_id={job_id!r}")
        return script.pop(0)


class InMemoryBioStore(BioStore):
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


class ScriptedBrowserSession:
    """一个真实 `Page` 服务多个职位：`goto(url)` 按 url 查表灌入对应 HTML，
    模拟真实浏览器在同一个 tab 里依次导航到不同职位链接（同
    `BrowserSession.goto()` 语义），不需要真的发网络请求。单 worker 一个 run
    内确实是同一个浏览器 context 顺序处理多个职位，这个假实现比「每个职位
    一个新页面」更贴近生产行为。
    """

    def __init__(self, page, html_by_url: dict[str, str]) -> None:
        self._page = page
        self._html_by_url = html_by_url
        self.goto_calls: list[str] = []

    @property
    def page(self):
        return self._page

    def goto(self, url: str, **kwargs):
        self.goto_calls.append(url)
        html = self._html_by_url.get(url)
        if html is not None:
            self._page.set_content(html)
        return self._page


# ----------------------------------------------------------------------
# 决策构造辅助（同 test_engine.py 套路）
# ----------------------------------------------------------------------


def decision(*decisions: ElementDecision, next_action=None) -> PageDecision:
    return PageDecision(decisions=list(decisions), next_action=next_action)


def fill(element_id: int, value: str, source=FieldValueSource.BIO) -> ElementDecision:
    return ElementDecision(element_id=element_id, action="fill", value=value, value_source=source)


def needs_user(element_id: int, question: str) -> ElementDecision:
    return ElementDecision(element_id=element_id, action="skip", needs_user=True, question=question)


def upload(element_id: int, path, source=FieldValueSource.BIO) -> ElementDecision:
    """一个附件上传决策。`source` 默认 BIO——刻意复现真实最坏情况：LLM 从
    `bio_store`（runner 预写的简历路径）读回值后大概率标成 BIO 而非
    LLM_GENERATED（见 runner 模块文档「简历错投 bug 及其修复」）。"""
    return ElementDecision(
        element_id=element_id, action="upload", value=str(path), value_source=source
    )


# 一个不需要登录、没有验证码、没有「apply」类按钮的极简 Workday 风格表单：
# open_application() 会直接判定 on_form（不撞见任何门禁/验证码信号）。
# 提交按钮文本刻意含 "Application" 而非独立单词 "Apply"（"application" 不含
# "apply" 子串），确保 OPENING 阶段的 apply-按钮启发式扫描不会误点它。
_ON_FORM_HTML = """
<input name="full_name" type="text">
<button type="button" onclick="document.body.innerHTML =
    '<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>'">
  Submit Application
</button>
"""

_ON_FORM_WITH_VISA_HTML = """
<input name="full_name" type="text">
<input name="visa" type="text">
<button type="button" onclick="document.body.innerHTML =
    '<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>'">
  Submit Application
</button>
"""


def make_job(job_id: str, *, score: float = 0.9, company: str = "Acme") -> JobRef:
    return JobRef(
        platform="workday",
        job_id=job_id,
        url=f"https://acme.wd1.myworkdayjobs.com/en-US/Acme/job/{job_id}",
        title="Software Engineer",
        company=company,
        score=score,
    )


def make_task(job: JobRef, tmp_path: Path) -> DeliveryTask:
    return DeliveryTask(job=job, resume_pdf=tmp_path / "resume.pdf", cover_letter_pdf=None)


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
    # 一些阶段 6 组件（如 Authenticator 的凭据读写）不接受 db_path 参数，
    # 只认 core.storage.db.DEFAULT_DB_PATH——覆盖它是隔离测试与真实
    # data/app.db 的唯一手段（同 test_auth.py 套路）；本文件的场景本身不
    # 需要登录，但仍然兜底，防止任何路径不小心碰到真实库。
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "app.db")
    yield


@pytest.fixture()
def db_path(tmp_path) -> Path:
    return tmp_path / "app.db"


@pytest.fixture()
def logs_dir(tmp_path) -> Path:
    return tmp_path / "logs"


def make_settings(mode: str = "auto") -> Settings:
    return Settings(
        deliver=DeliverSettings(mode=mode, question_timeout=2),
        browser=BrowserSettings(headless=True),
    )


# ----------------------------------------------------------------------
# (a) PENDING → … → SUCCEEDED
# ----------------------------------------------------------------------


class TestSucceedPath:
    def test_full_run_reaches_succeeded_and_persists(self, page, db_path, logs_dir):
        job = make_job("job-ok")
        task = make_task(job, db_path.parent)
        browser = ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML})
        llm = PerJobLLMClient({"job-ok": [decision(fill(1, "Alice"), next_action="done")]})

        summary = run_delivery(
            [task],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-a",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 1
        assert summary.succeeded == 1
        assert summary.failed_by_reason == {}
        assert summary.suspended == []

        record = repository.get_delivery("workday", "job-ok", db_path=db_path)
        assert record is not None
        assert record.status is DeliveryStatus.SUCCEEDED
        assert record.run_id == "run-a"

        # RunSummary 落库（阶段 8 新增的 runs 表读写）
        stored_summary = repository.get_run_summary("run-a", db_path=db_path)
        assert stored_summary == summary

        # JSONL 过程日志确实写了（决策九审计）
        log_path = logs_dir / "run-run-a.jsonl"
        assert log_path.exists()
        assert log_path.read_text(encoding="utf-8").strip() != ""


# ----------------------------------------------------------------------
# (b) WAITING_USER → SUSPENDED → 补答后第二次 run 重投 → SUCCEEDED
# ----------------------------------------------------------------------


class TestSuspendAndResurrect:
    def test_suspend_then_answer_then_resurrect_succeeds(self, browser, db_path, logs_dir):
        job = make_job("job-susp")
        page1 = browser.new_page()
        task = make_task(job, db_path.parent)
        fake_browser_1 = ScriptedBrowserSession(page1, {str(job.url): _ON_FORM_WITH_VISA_HTML})
        llm_1 = PerJobLLMClient(
            {
                "job-susp": [
                    decision(fill(1, "Alice"), needs_user(2, "Do you need visa sponsorship?"))
                ]
            }
        )

        summary_1 = run_delivery(
            [task],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),  # 无 answer_fn → TIMEOUT，触发挂起
            llm_client=llm_1,
            browser=fake_browser_1,
            bio_store=InMemoryBioStore(),
            run_id="run-b1",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )
        page1.close()

        assert summary_1.total == 1
        assert summary_1.succeeded == 0
        assert summary_1.suspended == [job]
        assert len(summary_1.unanswered_questions) == 1

        record = repository.get_delivery("workday", "job-susp", db_path=db_path)
        assert record.status is DeliveryStatus.SUSPENDED

        pending = repository.pending_unanswered_questions(db_path=db_path)
        assert len(pending) == 1
        # 补答前：该职位已经在「可重投」候选里等着最后一批答案
        assert repository.resuspendable_jobs(db_path=db_path) == []
        repository.record_answer(pending[0].id, "No", db_path=db_path)
        assert [j.key for j in repository.resuspendable_jobs(db_path=db_path)] == [
            ("workday", "job-susp")
        ]

        # 第二次 run：不传入任何新 task，纯靠挂起恢复队列把它捞回来重投。
        page2 = browser.new_page()
        fake_browser_2 = ScriptedBrowserSession(page2, {str(job.url): _ON_FORM_WITH_VISA_HTML})
        llm_2 = PerJobLLMClient(
            {"job-susp": [decision(fill(1, "Alice"), fill(2, "No"), next_action="done")]}
        )

        summary_2 = run_delivery(
            [],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm_2,
            browser=fake_browser_2,
            bio_store=InMemoryBioStore(),
            run_id="run-b2",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )
        page2.close()

        assert summary_2.total == 1
        assert summary_2.succeeded == 1
        assert summary_2.suspended == []

        record_2 = repository.get_delivery("workday", "job-susp", db_path=db_path)
        assert record_2.status is DeliveryStatus.SUCCEEDED
        assert record_2.run_id == "run-b2"

        # 恢复态处理完（终态）后必须清掉旧的挂起问题记录（见 runner 模块文档）。
        assert repository.resuspendable_jobs(db_path=db_path) == []
        assert repository.pending_unanswered_questions(db_path=db_path) == []

    def test_resuspend_loop_never_orphans_or_double_resurrects(
        self, browser, db_path, logs_dir
    ):
        """连续挂起场景（决策八「重投又挂起」）：suspend → 答 → 恢复重投 → 又
        suspend → 再答 → 再恢复 → SUCCEEDED。验证 `resuspendable_jobs()` 的
        `HAVING MIN(answered)=1` 能正确处理两批问题：第二批未答完前该职位不会
        被再次判为「可重投」（不会无限循环 / 提前重投），最终终态才清空全部
        挂起行（不留孤儿）。"""
        job = make_job("job-loop")
        task = make_task(job, db_path.parent)

        def run_once(run_id: str, page, script):
            fake = ScriptedBrowserSession(page, {str(job.url): _ON_FORM_WITH_VISA_HTML})
            llm = PerJobLLMClient({"job-loop": [script]})
            return run_delivery(
                [],  # 纯靠挂起恢复队列捞回（首轮除外，见下）
                settings=make_settings("auto"),
                question_channel=AutoAnswerChannel(),  # 无 answer_fn → TIMEOUT → 挂起
                llm_client=llm,
                browser=fake,
                bio_store=InMemoryBioStore(),
                run_id=run_id,
                repository_db_path=db_path,
                logs_dir=logs_dir,
            )

        # --- run 1：首投，撞第一批拿不准字段 → SUSPENDED ---
        page1 = browser.new_page()
        fake1 = ScriptedBrowserSession(page1, {str(job.url): _ON_FORM_WITH_VISA_HTML})
        llm1 = PerJobLLMClient(
            {"job-loop": [decision(fill(1, "Alice"), needs_user(2, "Need visa? (batch 1)"))]}
        )
        summary1 = run_delivery(
            [task],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm1,
            browser=fake1,
            bio_store=InMemoryBioStore(),
            run_id="run-loop-1",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )
        page1.close()
        assert summary1.suspended == [job]
        assert repository.resuspendable_jobs(db_path=db_path) == []  # 第一批还没答

        # 答第一批 → 变成可重投
        pending1 = repository.pending_unanswered_questions(db_path=db_path)
        assert len(pending1) == 1
        repository.record_answer(pending1[0].id, "No", db_path=db_path)
        assert [j.key for j in repository.resuspendable_jobs(db_path=db_path)] == [
            ("workday", "job-loop")
        ]

        # --- run 2：恢复重投，撞第二批拿不准字段 → 又一次 SUSPENDED ---
        page2 = browser.new_page()
        summary2 = run_once(
            "run-loop-2",
            page2,
            decision(fill(1, "Alice"), needs_user(2, "Need visa? (batch 2)")),
        )
        page2.close()
        assert summary2.total == 1
        assert summary2.suspended == [job]
        record2 = repository.get_delivery("workday", "job-loop", db_path=db_path)
        assert record2.status is DeliveryStatus.SUSPENDED

        # 关键不变式：第二批未答完前，MIN(answered)=0 → 不被判为「可重投」，
        # 不会在 run 3 提前重投或无限循环。
        assert repository.resuspendable_jobs(db_path=db_path) == []
        pending2 = repository.pending_unanswered_questions(db_path=db_path)
        assert len(pending2) == 1  # 只剩第二批那一条（第一批已 answered=1）
        assert pending2[0].question.question == "Need visa? (batch 2)"

        # 答第二批 → 再次可重投
        repository.record_answer(pending2[0].id, "No", db_path=db_path)
        assert [j.key for j in repository.resuspendable_jobs(db_path=db_path)] == [
            ("workday", "job-loop")
        ]

        # --- run 3：再次恢复重投，这次填完 → SUCCEEDED，清空全部挂起行 ---
        page3 = browser.new_page()
        summary3 = run_once(
            "run-loop-3",
            page3,
            decision(fill(1, "Alice"), fill(2, "No"), next_action="done"),
        )
        page3.close()
        assert summary3.total == 1
        assert summary3.succeeded == 1
        record3 = repository.get_delivery("workday", "job-loop", db_path=db_path)
        assert record3.status is DeliveryStatus.SUCCEEDED

        # 终态后不留任何孤儿挂起行（两批都清掉）。
        assert repository.resuspendable_jobs(db_path=db_path) == []
        assert repository.pending_unanswered_questions(db_path=db_path) == []


# ----------------------------------------------------------------------
# 去重：已 SUCCEEDED 的 key 不会被再次排队
# ----------------------------------------------------------------------


class TestDedup:
    def test_succeeded_key_in_incoming_tasks_is_skipped(self, page, db_path, logs_dir):
        from datetime import datetime, timezone

        from core.contracts import DeliveryRecord

        job = make_job("job-done")
        repository.record_delivery(
            DeliveryRecord(
                job=job,
                status=DeliveryStatus.SUCCEEDED,
                run_id="run-earlier",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            ),
            db_path=db_path,
        )

        task = make_task(job, db_path.parent)
        browser = ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML})
        llm = PerJobLLMClient()  # 不应该被调用

        summary = run_delivery(
            [task],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-dedup",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 0
        assert llm.contexts == []
        assert browser.goto_calls == []


# ----------------------------------------------------------------------
# 一个职位崩溃不拖死整个 run，继续处理下一个
# ----------------------------------------------------------------------


class TestCrashContinues:
    def test_one_job_crash_does_not_stop_the_run(self, page, db_path, logs_dir):
        crash_job = make_job("job-crash", score=0.95)
        ok_job = make_job("job-ok", score=0.5, company="Globex")

        html_by_url = {
            str(crash_job.url): _ON_FORM_HTML,
            str(ok_job.url): _ON_FORM_HTML,
        }
        browser = ScriptedBrowserSession(page, html_by_url)
        llm = PerJobLLMClient(
            scripts={"job-ok": [decision(fill(1, "Alice"), next_action="done")]},
            raises={"job-crash": RuntimeError("boom - simulated unexpected crash")},
        )

        tasks = [make_task(crash_job, db_path.parent), make_task(ok_job, db_path.parent)]

        summary = run_delivery(
            tasks,
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-crash",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 2
        assert summary.succeeded == 1  # job-ok 仍然跑完
        failed_reasons = summary.failed_by_reason
        assert len(failed_reasons) == 1
        (reason,) = failed_reasons.keys()
        assert "boom - simulated unexpected crash" in reason

        crash_record = repository.get_delivery("workday", "job-crash", db_path=db_path)
        assert crash_record.status is DeliveryStatus.FAILED
        ok_record = repository.get_delivery("workday", "job-ok", db_path=db_path)
        assert ok_record.status is DeliveryStatus.SUCCEEDED

        # score 降序：job-crash（0.95）应该先被处理，job-ok（0.5）后处理，
        # 两者的 goto 顺序能反映出来。
        assert browser.goto_calls == [str(crash_job.url), str(ok_job.url)]


# ----------------------------------------------------------------------
# 手动模式下用户拒绝提交 → FAILED("user_declined_submit")
# ----------------------------------------------------------------------


class TestManualDeclined:
    def test_manual_mode_decline_maps_to_failed(self, page, db_path, logs_dir):
        job = make_job("job-decline")
        task = make_task(job, db_path.parent)
        browser = ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML})
        llm = PerJobLLMClient({"job-decline": [decision(fill(1, "Alice"), next_action="done")]})

        class DecliningChannel(AutoAnswerChannel):
            def ask(self, questions, timeout):
                return [Answer(question=q, answer="n") for q in questions]

        summary = run_delivery(
            [task],
            settings=make_settings("manual"),
            question_channel=DecliningChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-decline",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 1
        assert summary.succeeded == 0
        assert summary.failed_by_reason == {"user_declined_submit": 1}

        record = repository.get_delivery("workday", "job-decline", db_path=db_path)
        assert record.status is DeliveryStatus.FAILED
        assert record.failure_reason == "user_declined_submit"


# ----------------------------------------------------------------------
# 简历错投回归：同模板两个职位，第二个必须上传自己的简历，不是第一个的
# ----------------------------------------------------------------------


# 带一个文件上传输入的极简 Workday 风格表单（两个职位共用同一模板 → 同一
# 结构指纹，触发 selector_cache 跨职位命中的条件）。上传框 name="resume"，
# engine._field_path_for 会 slug 成 form_answers.resume，正好命中
# runner._seed_materials_into_bio 预写的简历路径。
_ON_FORM_UPLOAD_HTML = """
<input name="resume" type="file">
<button type="button" onclick="document.body.innerHTML =
    '<h1>Thank you for applying!</h1><p>Your application has been submitted.</p>'">
  Submit Application
</button>
"""


class TestResumeCrossJob:
    """两个结构相同的职位、不同简历路径：第二个职位必须上传它**自己的**简历。

    没有修复时（`_is_cross_job_cacheable` 只排除 LLM_GENERATED），职位 A 的
    upload 决策（value=简历A、value_source=BIO）会被存进本 run 共享的
    SelectorCache；职位 B 同结构指纹命中缓存，直接重放职位 A 的决策，把
    **简历A 上传到职位 B**（错投）。修复后含 upload 的页面一律不跨职位缓存，
    职位 B 重新推理、上传简历B。
    """

    def test_second_job_uploads_its_own_resume_not_the_first(
        self, page, db_path, logs_dir, monkeypatch
    ):
        from core.deliver import browser as browser_primitives

        resume_a = db_path.parent / "resume_a.pdf"
        resume_b = db_path.parent / "resume_b.pdf"
        resume_a.write_bytes(b"%PDF-1.4 resume A")
        resume_b.write_bytes(b"%PDF-1.4 resume B")

        job_a = make_job("job-a", score=0.9)
        job_b = make_job("job-b", score=0.8)
        task_a = DeliveryTask(job=job_a, resume_pdf=resume_a, cover_letter_pdf=None)
        task_b = DeliveryTask(job=job_b, resume_pdf=resume_b, cover_letter_pdf=None)

        browser = ScriptedBrowserSession(
            page,
            {str(job_a.url): _ON_FORM_UPLOAD_HTML, str(job_b.url): _ON_FORM_UPLOAD_HTML},
        )
        llm = PerJobLLMClient(
            {
                "job-a": [decision(upload(1, resume_a), next_action="done")],
                "job-b": [decision(upload(1, resume_b), next_action="done")],
            }
        )

        # 监视真正落到 DOM 的 upload 路径（engine 通过 browser_primitives.apply_action
        # 调用；这里包一层记录 value 再委托真实实现）。
        uploaded: list[str] = []
        real_apply = browser_primitives.apply_action

        def spy_apply(pg, selector, action, value=None):
            if action == "upload":
                uploaded.append(value)
            return real_apply(pg, selector, action, value)

        monkeypatch.setattr(browser_primitives, "apply_action", spy_apply)

        summary = run_delivery(
            [task_a, task_b],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-cross",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 2
        assert summary.succeeded == 2

        # 核心断言：两个职位各自上传自己的简历，第二个绝不是第一个的路径。
        assert uploaded == [str(resume_a), str(resume_b)]
        assert uploaded[1] != uploaded[0]

        # 职位 B 确实各自重新推理了（缓存未替它决策）——脚本被消费掉即证明。
        job_b_contexts = [c for c in llm.contexts if c.job and c.job.job_id == "job-b"]
        assert job_b_contexts, "职位 B 的 decide() 应被调用（含上传页不得跨职位缓存）"


# ----------------------------------------------------------------------
# 没有匹配的适配器 → FAILED("no_adapter")
# ----------------------------------------------------------------------


class TestNoAdapter:
    def test_unknown_platform_url_fails_with_no_adapter(self, page, db_path, logs_dir):
        job = JobRef(
            platform="greenhouse",
            job_id="job-unknown",
            url="https://example.com/careers/job-unknown",
            title="Data Scientist",
            company="Umbrella",
            score=0.5,
        )
        task = make_task(job, db_path.parent)
        browser = ScriptedBrowserSession(page, {})
        llm = PerJobLLMClient()  # 不应该被调用

        summary = run_delivery(
            [task],
            settings=make_settings("auto"),
            question_channel=AutoAnswerChannel(),
            llm_client=llm,
            browser=browser,
            bio_store=InMemoryBioStore(),
            run_id="run-no-adapter",
            repository_db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 1
        assert summary.succeeded == 0
        assert summary.failed_by_reason == {"no_adapter": 1}
        assert llm.contexts == []

        record = repository.get_delivery("greenhouse", "job-unknown", db_path=db_path)
        assert record.status is DeliveryStatus.FAILED
        assert record.failure_reason == "no_adapter"
