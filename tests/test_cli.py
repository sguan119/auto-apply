"""tests.test_cli —— cli.main 的 typer 命令测试。

CLI 是薄入口（CLAUDE.md），这里只验证「参数解析 → 正确调用 core 层 → 退出码/
输出符合预期」，不重复测 `run_delivery`/`repository` 自身的逻辑（那是
test_runner.py/test_repository.py 的职责）。`deliver run`/`deliver retry` 用
`monkeypatch` 换掉 `cli.main.run_delivery`，不启动真实浏览器/LLM 子进程。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

import cli.main as main_module
from core.bio.store import YamlBioStore
from core.contracts import DeliveryRecord, DeliveryStatus, JobRef, Question, RunSummary
from core.questions.channel import AutoAnswerChannel
from core.storage import db, repository
from cli.terminal_channel import TerminalQuestionChannel

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    # cli/main.py 里的 repository.*/YamlBioStore() 调用都不传路径参数，只认
    # 各自模块的默认路径常量——覆盖它们是隔离测试与真实 data/ 的唯一手段
    # （同 test_auth.py 套路）。
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(main_module, "YamlBioStore", YamlBioStore)
    import core.bio.store as bio_store_module

    monkeypatch.setattr(bio_store_module, "DEFAULT_BIO_PATH", tmp_path / "bio.yaml")
    yield


def make_job(job_id: str = "job-1", **overrides) -> JobRef:
    defaults = dict(
        platform="workday",
        job_id=job_id,
        url="https://acme.wd1.myworkdayjobs.com/jobs/1",
        title="Software Engineer",
        company="Acme",
        score=0.9,
    )
    defaults.update(overrides)
    return JobRef(**defaults)


def write_tasks_file(tmp_path, jobs: list[JobRef]):
    path = tmp_path / "tasks.json"
    payload = [
        {
            "job": json.loads(job.model_dump_json()),
            "resume_pdf": str(tmp_path / "resume.pdf"),
            "cover_letter_pdf": None,
        }
        for job in jobs
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# version / --help
# ----------------------------------------------------------------------


class TestBasicCommands:
    def test_version_exits_zero(self):
        result = runner.invoke(main_module.app, ["version"])
        assert result.exit_code == 0
        assert "deliver" in result.stdout

    def test_top_level_help_exits_zero(self):
        result = runner.invoke(main_module.app, ["--help"])
        assert result.exit_code == 0

    @pytest.mark.parametrize("command", ["run", "answer", "retry", "status"])
    def test_subcommand_help_exits_zero(self, command):
        result = runner.invoke(main_module.app, [command, "--help"])
        assert result.exit_code == 0


# ----------------------------------------------------------------------
# status（空库 / 有记录）
# ----------------------------------------------------------------------


class TestStatus:
    def test_status_on_empty_db_exits_zero(self):
        result = runner.invoke(main_module.app, ["status"])
        assert result.exit_code == 0
        assert "还没有任何投递记录" in result.stdout

    def test_status_lists_recorded_deliveries(self):
        job = make_job()
        repository.record_delivery(
            DeliveryRecord(
                job=job,
                status=DeliveryStatus.FAILED,
                failure_reason="captcha_unsolved",
                run_id="run-1",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )

        result = runner.invoke(main_module.app, ["status"])
        assert result.exit_code == 0
        assert "captcha_unsolved" in result.stdout
        assert "Acme" in result.stdout

    def test_status_lists_pending_questions(self):
        job = make_job(job_id="job-pending")
        repository.save_suspended_questions(
            job, [Question(job=job, question="Need visa sponsorship?")]
        )

        result = runner.invoke(main_module.app, ["status"])
        assert result.exit_code == 0
        assert "Need visa sponsorship?" in result.stdout


# ----------------------------------------------------------------------
# answer
# ----------------------------------------------------------------------


class TestAnswer:
    def test_answer_with_no_pending_questions_exits_zero(self):
        result = runner.invoke(main_module.app, ["answer"])
        assert result.exit_code == 0
        assert "没有待补答" in result.stdout

    def test_answer_records_answer_and_writes_back_bio(self):
        job = make_job(job_id="job-pending")
        question = Question(
            job=job, field_path="preferences.visa", question="Need visa sponsorship?"
        )
        repository.save_suspended_questions(job, [question])

        result = runner.invoke(main_module.app, ["answer"], input="No\n")
        assert result.exit_code == 0

        pending = repository.pending_unanswered_questions()
        assert pending == []

        bio_store = YamlBioStore()
        assert bio_store.read_path("preferences.visa") == "No"


# ----------------------------------------------------------------------
# run（monkeypatch run_delivery，不碰真实浏览器/LLM）
# ----------------------------------------------------------------------


class TestRun:
    def test_run_passes_auto_mode_and_loaded_tasks(self, tmp_path, monkeypatch):
        captured = {}

        def fake_run_delivery(tasks, *, settings, question_channel, llm_client, **kwargs):
            captured["tasks"] = tasks
            captured["mode"] = settings.deliver.mode
            captured["question_channel"] = question_channel
            return RunSummary(run_id="run-x", total=len(tasks), succeeded=len(tasks))

        monkeypatch.setattr(main_module, "run_delivery", fake_run_delivery)

        tasks_path = write_tasks_file(tmp_path, [make_job("job-a"), make_job("job-b")])

        result = runner.invoke(
            main_module.app, ["run", "--tasks", str(tasks_path), "--auto"]
        )

        assert result.exit_code == 0
        assert captured["mode"] == "auto"
        assert len(captured["tasks"]) == 2
        assert isinstance(captured["question_channel"], AutoAnswerChannel)
        assert "run-x" in result.stdout

    def test_run_manual_mode_uses_terminal_channel(self, tmp_path, monkeypatch):
        captured = {}

        def fake_run_delivery(tasks, *, settings, question_channel, llm_client, **kwargs):
            captured["question_channel"] = question_channel
            captured["mode"] = settings.deliver.mode
            return RunSummary(run_id="run-y", total=0, succeeded=0)

        monkeypatch.setattr(main_module, "run_delivery", fake_run_delivery)
        tasks_path = write_tasks_file(tmp_path, [])

        result = runner.invoke(
            main_module.app, ["run", "--tasks", str(tasks_path), "--manual"]
        )

        assert result.exit_code == 0
        assert captured["mode"] == "manual"
        assert isinstance(captured["question_channel"], TerminalQuestionChannel)

    def test_run_rejects_auto_and_manual_together(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            main_module,
            "run_delivery",
            lambda *a, **k: pytest.fail("run_delivery 不应该被调用"),
        )
        tasks_path = write_tasks_file(tmp_path, [])

        result = runner.invoke(
            main_module.app, ["run", "--tasks", str(tasks_path), "--auto", "--manual"]
        )
        assert result.exit_code != 0

    def test_run_missing_tasks_file_still_runs_with_empty_queue(self, tmp_path, monkeypatch):
        captured = {}

        def fake_run_delivery(tasks, *, settings, question_channel, llm_client, **kwargs):
            captured["tasks"] = tasks
            return RunSummary(run_id="run-empty", total=0, succeeded=0)

        monkeypatch.setattr(main_module, "run_delivery", fake_run_delivery)

        result = runner.invoke(
            main_module.app,
            ["run", "--tasks", str(tmp_path / "does-not-exist.json"), "--auto"],
        )

        assert result.exit_code == 0
        assert captured["tasks"] == []


# ----------------------------------------------------------------------
# retry
# ----------------------------------------------------------------------


class TestRetry:
    def test_retry_missing_record_errors(self):
        result = runner.invoke(main_module.app, ["retry", "workday", "no-such-job"])
        assert result.exit_code != 0

    def test_retry_refuses_succeeded_job(self):
        job = make_job(job_id="job-done")
        repository.record_delivery(
            DeliveryRecord(
                job=job,
                status=DeliveryStatus.SUCCEEDED,
                run_id="run-1",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )

        result = runner.invoke(main_module.app, ["retry", "workday", "job-done"])
        assert result.exit_code != 0
        assert "SUCCEEDED" in result.output or "永不再投" in result.output

    def test_retry_calls_run_delivery_with_force_keys(self, monkeypatch):
        job = make_job(job_id="job-failed")
        repository.record_delivery(
            DeliveryRecord(
                job=job,
                status=DeliveryStatus.FAILED,
                failure_reason="login_failed",
                run_id="run-1",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )

        captured = {}

        def fake_run_delivery(tasks, *, settings, question_channel, llm_client, **kwargs):
            captured["tasks"] = tasks
            captured["force_keys"] = kwargs.get("force_keys")
            return RunSummary(run_id="run-retry", total=1, succeeded=1)

        monkeypatch.setattr(main_module, "run_delivery", fake_run_delivery)

        result = runner.invoke(main_module.app, ["retry", "workday", "job-failed", "--auto"])

        assert result.exit_code == 0
        assert captured["force_keys"] == {("workday", "job-failed")}
        assert len(captured["tasks"]) == 1
        assert captured["tasks"][0].job.key == ("workday", "job-failed")
