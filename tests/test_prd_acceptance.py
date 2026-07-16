"""tests.test_prd_acceptance —— 按 PRD 章节组织的「预期行为」验收测试集。

与 `test_*.py`（按实现模块拆分的单元/集成测试）互补：本文件**按
`docs/deliver-prd.md` 的条款**组织，每个测试类对应一节 PRD，每个用例名就是
一条「预期行为」，docstring 引用具体 PRD 出处。目的是让 PRD 与代码之间有一条
可追溯的验收线——读这个文件就能核对「PRD 承诺的行为是否真的成立」，而不必先
理解内部模块怎么切分。

**打法**：不打真实网络/真实 LLM。用真实 headless chromium 灌 `set_content()`
当 Workday 表单，`select_adapter()` 靠 URL host 命中真实 `WorkdayAdapter`（不
mock），只把「LLM 决策」和「页面导航」脚本化——这样验收的是 adapter→engine→
submit→runner 的真实全链路行为。DB/日志走临时目录，不碰真实 `data/`/`logs/`。

测试替身（`ScriptedBrowserSession`/`PerJobLLMClient`/`InMemoryBioStore`）与
`test_runner.py` 同源，此处自带一份以保持文件自包含。
"""

from __future__ import annotations

import json
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
    Question,
)
from core.deliver import submit as submit_module
from core.deliver.adapters.base import select_adapter
from core.deliver.adapters.workday import WorkdayAdapter
from core.deliver.auth import generate_password
from core.deliver.runner import run_delivery
from core.llm.client import ElementDecision, LLMClient, PageContext, PageDecision
from core.questions.channel import TIMEOUT, AutoAnswerChannel, QuestionChannel
from core.storage import db, repository


# ======================================================================
# 测试替身
# ======================================================================


class PerJobLLMClient(LLMClient):
    """按 `PageContext.job.job_id` FIFO 回放脚本的假 LLM 客户端。"""

    def __init__(self, scripts: dict[str, list[PageDecision]] | None = None) -> None:
        self._scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.contexts: list[PageContext] = []

    def decide(self, page_context: PageContext) -> PageDecision:
        self.contexts.append(page_context)
        job_id = page_context.job.job_id if page_context.job else None
        script = self._scripts.get(job_id)
        if not script:
            raise AssertionError(f"PerJobLLMClient 脚本已耗尽或未配置：job_id={job_id!r}")
        return script.pop(0)

    def job_contexts(self, job_id: str) -> list[PageContext]:
        return [c for c in self.contexts if c.job and c.job.job_id == job_id]


class InMemoryBioStore(BioStore):
    """点分路径的内存 bio，供断言「答案是否回写」。"""

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
    模拟真实浏览器在同一 tab 里依次导航到不同职位链接。"""

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


class RecordingChannel(QuestionChannel):
    """记录每一次 `ask()` 的问题，并用固定文本回答（供断言「问没问 / 问了什么」）。"""

    def __init__(self, answer_text: str) -> None:
        self._answer_text = answer_text
        self.asked: list[Question] = []

    def ask(self, questions: list[Question], timeout: float):
        if not questions:
            return []
        self.asked.extend(questions)
        return [Answer(question=q, answer=self._answer_text) for q in questions]

    @property
    def asked_pages(self) -> list[str | None]:
        return [q.page for q in self.asked]


# ======================================================================
# 决策构造辅助
# ======================================================================


def decision(*decisions: ElementDecision, next_action=None) -> PageDecision:
    return PageDecision(decisions=list(decisions), next_action=next_action)


def fill(element_id: int, value: str, source=FieldValueSource.BIO) -> ElementDecision:
    return ElementDecision(element_id=element_id, action="fill", value=value, value_source=source)


def needs_user(element_id: int, question: str) -> ElementDecision:
    return ElementDecision(element_id=element_id, action="skip", needs_user=True, question=question)


# ======================================================================
# 表单 HTML fixture
# ======================================================================

# 点击提交按钮后把 body 换成致谢页（= 提交确认页，PRD 八成功判定）。提交按钮
# 文本用 "Submit Application"：不含独立单词 "apply" 的子串误伤（"application"
# 里没有 "apply"），OPENING 阶段的 apply 扫描不会误点它。
_THANKS_ONCLICK = (
    "document.body.innerHTML ="
    " '<h1>Thank you for applying!</h1>"
    "<p>Your application has been submitted.</p>'"
)

_ON_FORM_HTML = f"""
<input name="full_name" type="text">
<button type="button" onclick="{_THANKS_ONCLICK}">Submit Application</button>
"""

_ON_FORM_WITH_VISA_HTML = f"""
<input name="full_name" type="text">
<input name="visa" type="text">
<button type="button" onclick="{_THANKS_ONCLICK}">Submit Application</button>
"""

# 带 hCaptcha 挂件的表单：`detect_captcha` 认 `.h-captcha[data-sitekey]` 静态
# 标记；测试 Settings 未配置 CAPSOLVER_API_KEY → 求解直接失败（PRD 五优雅降级）。
_ON_FORM_WITH_CAPTCHA_HTML = f"""
<input name="full_name" type="text">
<div class="h-captcha" data-sitekey="test-sitekey-123"></div>
<button type="button" onclick="{_THANKS_ONCLICK}">Submit Application</button>
"""

# 提交按钮点了也不出现确认页（无 onclick）——用于「看不到确认页 → FAILED」。
_ON_FORM_NO_CONFIRM_HTML = """
<input name="full_name" type="text">
<button type="button">Submit Application</button>
"""


def make_job(job_id: str, *, score: float = 0.9, company: str = "Acme", tenant: str = "acme") -> JobRef:
    return JobRef(
        platform="workday",
        job_id=job_id,
        url=f"https://{tenant}.wd1.myworkdayjobs.com/en-US/Careers/job/{job_id}",
        title="Software Engineer",
        company=company,
        score=score,
    )


def make_task(job: JobRef, tmp_dir: Path) -> DeliveryTask:
    return DeliveryTask(job=job, resume_pdf=tmp_dir / "resume.pdf", cover_letter_pdf=None)


def make_settings(mode: str = "auto", question_timeout: int = 2) -> Settings:
    return Settings(
        deliver=DeliverSettings(mode=mode, question_timeout=question_timeout),
        browser=BrowserSettings(headless=True),
    )


# ======================================================================
# fixtures
# ======================================================================


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
    # 兜底：任何只认 DEFAULT_DB_PATH 的组件也被隔离到临时库，绝不碰真实 data/app.db。
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "app.db")
    yield


@pytest.fixture()
def db_path(tmp_path) -> Path:
    return tmp_path / "app.db"


@pytest.fixture()
def logs_dir(tmp_path) -> Path:
    return tmp_path / "logs"


def run(tasks, *, settings, channel, llm, browser_session, bio=None, run_id, db_path, logs_dir, **kw):
    """薄封装 run_delivery，统一注入测试替身，减少每个用例的样板。"""
    return run_delivery(
        tasks,
        settings=settings,
        question_channel=channel,
        llm_client=llm,
        browser=browser_session,
        bio_store=bio or InMemoryBioStore(),
        run_id=run_id,
        repository_db_path=db_path,
        logs_dir=logs_dir,
        **kw,
    )


# ======================================================================
# PRD 一：无人值守、遇阻才问（核心原则） / PRD 三：LLM+DOM 逐页填表
# ======================================================================


class TestPRD1_UnattendedHappyPath:
    def test_auto_fills_and_submits_without_any_prompt(self, page, db_path, logs_dir):
        """PRD 一「默认全自动跑，不打断用户」+ PRD 三：一个不含拿不准字段的表单，
        auto 模式应当全自动填完并提交到 SUCCEEDED，全程不触发任何问询。"""
        job = make_job("job-happy")
        channel = RecordingChannel("y")  # 若被问会记录；预期一次都不问
        llm = PerJobLLMClient({"job-happy": [decision(fill(1, "Alice"), next_action="done")]})
        browser_session = ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML})

        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=channel,
            llm=llm,
            browser_session=browser_session,
            run_id="prd1",
            db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 1
        assert summary.succeeded == 1
        assert channel.asked == []  # 无人值守：一次都没打断
        assert repository.get_delivery("workday", "job-happy", db_path=db_path).status is (
            DeliveryStatus.SUCCEEDED
        )


# ======================================================================
# PRD 二：投递范围（Workday 优先，平台路由）
# ======================================================================


class TestPRD2_PlatformScope:
    def test_workday_url_routes_to_workday_adapter(self):
        """PRD 二「第一个落地平台：优先 Workday」：myworkdayjobs.com 链接应命中
        WorkdayAdapter。"""
        adapter = select_adapter(
            "https://acme.wd1.myworkdayjobs.com/en-US/Careers/job/R123"
        )
        assert isinstance(adapter, WorkdayAdapter)

    def test_non_workday_url_has_no_adapter_and_fails_cleanly(self, page, db_path, logs_dir):
        """PRD 二「仅北美 Workday 起步」：不在范围内的平台链接没有适配器，应当
        干净地失败（FAILED/no_adapter），不崩、不调用 LLM。"""
        job = JobRef(
            platform="greenhouse",
            job_id="gh-1",
            url="https://boards.greenhouse.io/acme/jobs/1",
            title="Data Scientist",
            company="Umbrella",
            score=0.5,
        )
        llm = PerJobLLMClient()  # 不应被调用
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {}),
            run_id="prd2",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.failed_by_reason == {"no_adapter": 1}
        assert llm.contexts == []
        assert repository.get_delivery("greenhouse", "gh-1", db_path=db_path).failure_reason == (
            "no_adapter"
        )


# ======================================================================
# PRD 四：字段处理规则
# ======================================================================


class TestPRD4_FieldHandling:
    def test_open_ended_question_is_generated_not_blocked(self, page, db_path, logs_dir):
        """PRD 四「开放式问答字段不算不确定字段，不阻塞」：LLM 现场生成答案
        （value_source=llm_generated），不触发问询，直接投完。"""
        job = make_job("job-open")
        channel = RecordingChannel("y")
        llm = PerJobLLMClient(
            {
                "job-open": [
                    decision(
                        fill(1, "I admire your mission.", source=FieldValueSource.LLM_GENERATED),
                        next_action="done",
                    )
                ]
            }
        )
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd4-open",
            db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.succeeded == 1
        assert channel.asked == []  # 开放式问答绝不阻塞
        record = repository.get_delivery("workday", "job-open", db_path=db_path)
        sources = {f.value_source for f in record.filled_fields}
        assert FieldValueSource.LLM_GENERATED in sources

    def test_uncertain_field_asks_then_writes_bio_then_completes_same_job(
        self, page, db_path, logs_dir
    ):
        """PRD 四「不确定字段」全流程：bio 缺失字段 → 停下来问 → 用户回答 →
        答案回写 bio → **用回写后的信息继续完成当前这个职位**（同一次 run 内投完，
        不是挂起到下次）。"""
        job = make_job("job-uncertain")
        bio = InMemoryBioStore()

        def answer_fn(questions: list[Question]) -> list[Answer]:
            return [Answer(question=q, answer="No") for q in questions]

        channel = AutoAnswerChannel(answer_fn=answer_fn)  # 有人在场应答
        # 第一次决策：visa 字段拿不准（needs_user）。回写 bio 后 engine 强制重决策，
        # 第二次决策填入 visa 并结束。
        llm = PerJobLLMClient(
            {
                "job-uncertain": [
                    decision(fill(1, "Alice"), needs_user(2, "Do you need visa sponsorship?")),
                    decision(fill(1, "Alice"), fill(2, "No"), next_action="done"),
                ]
            }
        )
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_WITH_VISA_HTML}),
            bio=bio,
            run_id="prd4-uncertain",
            db_path=db_path,
            logs_dir=logs_dir,
        )

        # 当前 run 内直接投完（succeeded），没有转挂起。
        assert summary.succeeded == 1
        assert summary.suspended == []
        assert repository.get_delivery("workday", "job-uncertain", db_path=db_path).status is (
            DeliveryStatus.SUCCEEDED
        )
        # 答案确实回写进了 bio（form_answers 命名空间下能读回 "No"）。
        assert bio.read_path("form_answers.visa") == "No"

    def test_low_confidence_field_asks_even_when_bio_has_value(self, page, db_path, logs_dir):
        """PRD 四「填了但信心低」作为**独立**触发（≠ bio 缺失）：即使 bio 里已经
        有该字段的值，LLM 仍可因信心低把它标成拿不准 → 照样问询。证明问询触发
        与「bio 是否缺失」解耦。"""
        job = make_job("job-lowconf")
        bio = InMemoryBioStore()
        bio.write_path("form_answers.visa", "Yes")  # bio 明明有值
        llm = PerJobLLMClient(
            {
                "job-lowconf": [
                    decision(fill(1, "Alice"), needs_user(2, "Need visa? (low confidence)"))
                ]
            }
        )
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),  # 无应答 → 观察是否触发了问询（挂起即证明问了）
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_WITH_VISA_HTML}),
            bio=bio,
            run_id="prd4-lowconf",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        # bio 有值也照样问了（否则不会挂起）——低信心触发独立于 bio 缺失。
        assert summary.suspended == [job]
        assert len(summary.unanswered_questions) == 1

    def test_unanswered_uncertain_field_suspends_job(self, page, db_path, logs_dir):
        """PRD 四 + PRD 七：拿不准字段在无人应答（超时）时，该职位挂起等补答，
        不会瞎填、也不会静默失败。"""
        job = make_job("job-noanswer")
        llm = PerJobLLMClient(
            {"job-noanswer": [decision(fill(1, "Alice"), needs_user(2, "Need visa?"))]}
        )
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),  # 无 answer_fn → TIMEOUT
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_WITH_VISA_HTML}),
            run_id="prd4-noanswer",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.suspended == [job]
        assert len(summary.unanswered_questions) == 1
        assert repository.get_delivery("workday", "job-noanswer", db_path=db_path).status is (
            DeliveryStatus.SUSPENDED
        )


# ======================================================================
# PRD 五：验证码/反爬应对
# ======================================================================


class TestPRD5_Captcha:
    def test_unsolvable_captcha_fails_and_continues_to_next_job_without_retry(
        self, page, db_path, logs_dir
    ):
        """PRD 五「实在过不去 → 标记该职位失败，跳过，继续投下一个，不阻塞、
        不重试」：未配置打码服务时验证码求解失败 → FAILED(captcha_unsolved)，
        下一个职位照常投成功，且失败职位只被打开一次（不重试）。"""
        captcha_job = make_job("job-captcha", score=0.9)
        ok_job = make_job("job-ok", score=0.5, company="Globex", tenant="globex")
        html_by_url = {
            str(captcha_job.url): _ON_FORM_WITH_CAPTCHA_HTML,
            str(ok_job.url): _ON_FORM_HTML,
        }
        browser_session = ScriptedBrowserSession(page, html_by_url)
        llm = PerJobLLMClient(
            {
                "job-captcha": [decision(fill(1, "Alice"), next_action="done")],
                "job-ok": [decision(fill(1, "Bob"), next_action="done")],
            }
        )
        summary = run(
            [make_task(captcha_job, db_path.parent), make_task(ok_job, db_path.parent)],
            settings=make_settings("auto"),  # 自动模式，capsolver 无 key
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=browser_session,
            run_id="prd5",
            db_path=db_path,
            logs_dir=logs_dir,
        )

        assert summary.total == 2
        assert summary.succeeded == 1  # 下一个职位不受影响
        assert summary.failed_by_reason == {"captcha_unsolved": 1}
        assert repository.get_delivery("workday", "job-captcha", db_path=db_path).failure_reason == (
            "captcha_unsolved"
        )
        assert repository.get_delivery("workday", "job-ok", db_path=db_path).status is (
            DeliveryStatus.SUCCEEDED
        )
        # 不重试：失败职位的 URL 只被打开一次。
        assert browser_session.goto_calls.count(str(captcha_job.url)) == 1


# ======================================================================
# PRD 六：账号与凭据管理
# ======================================================================


class TestPRD6_Accounts:
    def test_password_generation_random_mode_is_strong(self):
        """PRD 六「密码随机生成」：random 模式生成足够长、含多字符类的密码。"""
        pw = generate_password(make_settings())
        assert len(pw) >= 12
        assert any(c.islower() for c in pw)
        assert any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw)

    def test_password_generation_template_mode_honors_user_template(self):
        """PRD 六「密码用户预设模板」：template 模式按模板生成，{rand} 被替换。"""
        settings = make_settings()
        settings.deliver.password_generation_mode = "template"
        settings.deliver.password_template = "Job{rand}!2026"
        pw = generate_password(settings)
        assert pw.startswith("Job") and pw.endswith("!2026")
        assert pw != "Job{rand}!2026"  # 占位符确实被替换

    def test_credentials_grouped_per_employer_portal(self, db_path):
        """PRD 六「每个平台/雇主门户生成并记录一份账号」：同一雇主的所有职位
        映射到同一 portal 凭据 key，不同雇主分开——WorkdayAdapter.portal_id
        以租户子域为 key。"""
        adapter = WorkdayAdapter()
        job_a1 = make_job("R1", tenant="acme")
        job_a2 = make_job("R2", tenant="acme")
        job_b = make_job("R3", tenant="globex")
        assert adapter.portal_id(job_a1) == adapter.portal_id(job_a2) == "acme"
        assert adapter.portal_id(job_b) == "globex"

    def test_credentials_stored_plaintext_and_reusable(self, db_path):
        """PRD 六「本地明文存储 + 下次复用」：凭据按 (platform, portal) 落库，
        明文可读回复用（不加密，见 PRD 六存储约束）。"""
        repository.upsert_credential(
            "workday", "acme", username="me@example.com", password="Secret123!", db_path=db_path
        )
        cred = repository.get_credential("workday", "acme", db_path=db_path)
        assert cred is not None
        assert cred.password == "Secret123!"  # 明文存储、原样读回，可直接复用登录
        assert cred.username == "me@example.com"


# ======================================================================
# PRD 七：运行模式（自动 / 手动，全局开关）
# ======================================================================


class TestPRD7_RunModes:
    def test_default_mode_is_manual(self):
        """PRD 七「默认手动投递」：不指定时投递模式应为 manual（安全默认，
        避免未经确认就自动提交）。"""
        assert DeliverSettings().mode == "manual"

    def test_manual_mode_asks_confirmation_before_submitting(self, page, db_path, logs_dir):
        """PRD 七「手动投递：只填表，等用户确认后再提交」：手动模式在提交前必须
        经问询通道确认（page=submit_confirm）；确认后走到 SUCCEEDED。"""
        job = make_job("job-manual")
        channel = RecordingChannel("y")  # 用户确认提交
        llm = PerJobLLMClient({"job-manual": [decision(fill(1, "Alice"), next_action="done")]})
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("manual"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd7-manual",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.succeeded == 1
        assert "submit_confirm" in channel.asked_pages  # 提交前确实问了确认

    def test_auto_mode_submits_without_confirmation_prompt(self, page, db_path, logs_dir):
        """PRD 七「自动投递：表单填完直接提交」：auto 模式不问确认，直接提交。"""
        job = make_job("job-auto")
        channel = RecordingChannel("y")
        llm = PerJobLLMClient({"job-auto": [decision(fill(1, "Alice"), next_action="done")]})
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd7-auto",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.succeeded == 1
        assert "submit_confirm" not in channel.asked_pages  # 自动模式不问确认

    def test_manual_decline_does_not_submit(self, page, db_path, logs_dir):
        """PRD 七「等用户确认」的反面：用户拒绝确认 → 不提交（记 FAILED，
        reason 区分「拒绝」而非真失败）。"""
        job = make_job("job-decline")
        channel = RecordingChannel("n")  # 用户拒绝
        llm = PerJobLLMClient({"job-decline": [decision(fill(1, "Alice"), next_action="done")]})
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("manual"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd7-decline",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.succeeded == 0
        assert summary.failed_by_reason == {"user_declined_submit": 1}

    def test_mode_applies_to_all_jobs_in_the_run(self, page, db_path, logs_dir):
        """PRD 七「选定后当次运行的所有职位都按该模式处理」：一次 run 的模式是
        全局的——手动模式下两个职位都要经确认（这里都拒绝，两个都 declined）。"""
        job1 = make_job("job-m1", score=0.9, tenant="acme")
        job2 = make_job("job-m2", score=0.8, tenant="globex", company="Globex")
        channel = RecordingChannel("n")
        llm = PerJobLLMClient(
            {
                "job-m1": [decision(fill(1, "Alice"), next_action="done")],
                "job-m2": [decision(fill(1, "Bob"), next_action="done")],
            }
        )
        html = {str(job1.url): _ON_FORM_HTML, str(job2.url): _ON_FORM_HTML}
        summary = run(
            [make_task(job1, db_path.parent), make_task(job2, db_path.parent)],
            settings=make_settings("manual"),
            channel=channel,
            llm=llm,
            browser_session=ScriptedBrowserSession(page, html),
            run_id="prd7-all",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.total == 2
        assert summary.failed_by_reason == {"user_declined_submit": 2}
        assert channel.asked_pages.count("submit_confirm") == 2  # 每个职位各问一次确认


# ======================================================================
# PRD 八：记录与日志
# ======================================================================


class TestPRD8_RecordsAndLogs:
    def test_success_is_defined_by_confirmation_page(self, page, db_path, logs_dir):
        """PRD 八「成功判定：以进入提交确认页为准」：点提交后出现确认页 → SUCCEEDED。"""
        job = make_job("job-conf")
        llm = PerJobLLMClient({"job-conf": [decision(fill(1, "Alice"), next_action="done")]})
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd8-conf",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.succeeded == 1

    def test_no_confirmation_page_is_failure(self, page, db_path, logs_dir, monkeypatch):
        """PRD 八「否则记为失败」：点了提交但一直看不到确认页 → FAILED
        (confirmation_page_not_detected)。缩短确认轮询预算让负例快速收敛。"""
        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_TIMEOUT", 0.5)
        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_INTERVAL", 0.1)
        job = make_job("job-noconf")
        llm = PerJobLLMClient({"job-noconf": [decision(fill(1, "Alice"), next_action="done")]})
        summary = run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_NO_CONFIRM_HTML}),
            run_id="prd8-noconf",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.succeeded == 0
        assert summary.failed_by_reason == {"confirmation_page_not_detected": 1}

    def test_record_captures_which_fields_were_filled(self, page, db_path, logs_dir):
        """PRD 八「记录每个表单填了哪些内容」：投递记录里保留 filled_fields
        （问题原文 + 填入值 + 值来源）。"""
        job = make_job("job-rec")
        llm = PerJobLLMClient({"job-rec": [decision(fill(1, "Alice Smith"), next_action="done")]})
        run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd8-rec",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        record = repository.get_delivery("workday", "job-rec", db_path=db_path)
        assert [f.value for f in record.filled_fields] == ["Alice Smith"]

    def test_failures_grouped_by_reason(self, page, db_path, logs_dir, monkeypatch):
        """PRD 八「失败（含验证码导致的失败）」汇总：一次 run 里同时产生多种失败
        原因时，RunSummary.failed_by_reason 按 reason 分别计数、不混淆。"""
        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_TIMEOUT", 0.5)
        monkeypatch.setattr(submit_module, "_CONFIRMATION_POLL_INTERVAL", 0.1)

        gh = JobRef(  # 不支持的平台 → no_adapter（不导航、不调 LLM）
            platform="greenhouse",
            job_id="gh-x",
            url="https://boards.greenhouse.io/acme/jobs/9",
            title="X",
            company="Umbrella",
            score=0.9,
        )
        cap = make_job("job-cap", score=0.8, tenant="globex")  # 验证码求解失败
        noc = make_job("job-noc", score=0.7, tenant="initech")  # 无确认页

        html = {
            str(cap.url): _ON_FORM_WITH_CAPTCHA_HTML,
            str(noc.url): _ON_FORM_NO_CONFIRM_HTML,
        }
        llm = PerJobLLMClient(
            {
                "job-cap": [decision(fill(1, "A"), next_action="done")],
                "job-noc": [decision(fill(1, "B"), next_action="done")],
            }
        )
        summary = run(
            [make_task(gh, db_path.parent), make_task(cap, db_path.parent), make_task(noc, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, html),
            run_id="prd8-group",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.total == 3
        assert summary.succeeded == 0
        assert summary.failed_by_reason == {
            "no_adapter": 1,
            "captcha_unsolved": 1,
            "confirmation_page_not_detected": 1,
        }

    def test_process_log_records_key_steps(self, page, db_path, logs_dir):
        """PRD 八「过程日志：记录运行过程中的关键步骤」：逐 run 的 JSONL 日志
        文件确实生成，且含 run/职位/状态转移这类关键事件。"""
        job = make_job("job-log")
        llm = PerJobLLMClient({"job-log": [decision(fill(1, "Alice"), next_action="done")]})
        run(
            [make_task(job, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, {str(job.url): _ON_FORM_HTML}),
            run_id="prd8-log",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        log_path = logs_dir / "run-prd8-log.jsonl"
        assert log_path.exists()
        events = [json.loads(line)["event_type"] for line in log_path.read_text("utf-8").splitlines()]
        assert "run_started" in events
        assert "job_started" in events
        assert "state_transition" in events


# ======================================================================
# PRD 九：并发（当前 MVP：单 worker，按分数降序，全投不设上限）
# ======================================================================


class TestPRD9_Concurrency:
    def test_processes_jobs_in_score_descending_order(self, page, db_path, logs_dir):
        """PRD 九「按分数从高到低顺序逐个投」：不管输入顺序如何，实际打开职位的
        顺序应按 score 降序。"""
        low = make_job("job-low", score=0.30, tenant="low")
        high = make_job("job-high", score=0.95, tenant="high")
        mid = make_job("job-mid", score=0.60, tenant="mid")
        html = {
            str(low.url): _ON_FORM_HTML,
            str(high.url): _ON_FORM_HTML,
            str(mid.url): _ON_FORM_HTML,
        }
        browser_session = ScriptedBrowserSession(page, html)
        llm = PerJobLLMClient(
            {
                "job-low": [decision(fill(1, "L"), next_action="done")],
                "job-high": [decision(fill(1, "H"), next_action="done")],
                "job-mid": [decision(fill(1, "M"), next_action="done")],
            }
        )
        # 输入顺序刻意打乱（low, high, mid）。
        summary = run(
            [make_task(low, db_path.parent), make_task(high, db_path.parent), make_task(mid, db_path.parent)],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=browser_session,
            run_id="prd9-order",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.total == 3
        assert summary.succeeded == 3  # 全投，不设上限
        assert browser_session.goto_calls == [str(high.url), str(mid.url), str(low.url)]

    def test_invests_all_jobs_no_cap(self, page, db_path, logs_dir):
        """PRD 九「把列表里所有过阈值职位都投一遍，不设单次投递件数上限」：给
        5 个职位应处理 5 个。"""
        jobs = [make_job(f"job-{i}", score=0.5 + i / 100, tenant=f"t{i}") for i in range(5)]
        html = {str(j.url): _ON_FORM_HTML for j in jobs}
        llm = PerJobLLMClient(
            {j.job_id: [decision(fill(1, "X"), next_action="done")] for j in jobs}
        )
        summary = run(
            [make_task(j, db_path.parent) for j in jobs],
            settings=make_settings("auto"),
            channel=AutoAnswerChannel(),
            llm=llm,
            browser_session=ScriptedBrowserSession(page, html),
            run_id="prd9-all",
            db_path=db_path,
            logs_dir=logs_dir,
        )
        assert summary.total == 5
        assert summary.succeeded == 5
