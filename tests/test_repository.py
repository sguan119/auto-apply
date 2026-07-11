"""tests.test_repository —— core.storage.repository 的去重/UPSERT/凭据/挂起问题/
Easy Apply 计数往返测试（spec 决策八 / 决策九）。每个用例用 tmp_path 下的临时库，
互不干扰、不碰真实 `data/app.db`。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.contracts import (
    DeliveryRecord,
    DeliveryStatus,
    FieldValueSource,
    FilledField,
    JobRef,
    Question,
    RunSummary,
)
from core.storage import repository


def make_job_ref(**overrides) -> JobRef:
    defaults = dict(
        platform="workday",
        job_id="job-1",
        url="https://example.com/jobs/1",
        title="Software Engineer",
        company="Acme Corp",
        score=0.9,
    )
    defaults.update(overrides)
    return JobRef(**defaults)


def make_record(job: JobRef, status: DeliveryStatus, **overrides) -> DeliveryRecord:
    defaults = dict(
        job=job,
        status=status,
        filled_fields=[
            FilledField(question="q", value="v", value_source=FieldValueSource.BIO)
        ],
        failure_reason=None,
        run_id="run-1",
        started_at=datetime(2026, 7, 10, 9, 0, 0),
        finished_at=datetime(2026, 7, 10, 9, 5, 0),
    )
    defaults.update(overrides)
    return DeliveryRecord(**defaults)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "app.db"


class TestDeliveryRecords:
    def test_record_and_get_round_trip(self, db_path):
        job = make_job_ref()
        record = make_record(job, DeliveryStatus.SUCCEEDED)
        repository.record_delivery(record, db_path=db_path)

        fetched = repository.get_delivery("workday", "job-1", db_path=db_path)
        assert fetched == record

    def test_httpurl_and_path_survive_round_trip(self, db_path):
        # Phase 1 review 标出的坑：HttpUrl/Path 不是 JSON 原生类型，必须用
        # model_dump_json()/mode="json" 落库，这里断言真的能读回来。
        job = make_job_ref(url="https://workday.example.com/jobs/42")
        record = make_record(job, DeliveryStatus.FAILED, failure_reason="captcha_unsolved")
        repository.record_delivery(record, db_path=db_path)

        fetched = repository.get_delivery("workday", "job-1", db_path=db_path)
        assert str(fetched.job.url) == str(job.url)
        assert fetched.failure_reason == "captcha_unsolved"

    def test_get_missing_returns_none(self, db_path):
        assert repository.get_delivery("workday", "no-such-job", db_path=db_path) is None

    def test_upsert_same_key_updates_not_duplicates(self, db_path):
        job = make_job_ref()
        repository.record_delivery(make_record(job, DeliveryStatus.FAILED), db_path=db_path)
        repository.record_delivery(
            make_record(job, DeliveryStatus.SUCCEEDED, run_id="run-2"), db_path=db_path
        )

        fetched = repository.get_delivery("workday", "job-1", db_path=db_path)
        assert fetched.status is DeliveryStatus.SUCCEEDED
        assert fetched.run_id == "run-2"
        assert repository.get_delivered_job_keys(db_path=db_path) == {("workday", "job-1")}

    def test_get_delivered_job_keys_includes_all_recorded_statuses(self, db_path):
        # 决策：get_delivered_job_keys 回喂的是「deliver 已处理过」的全部键，
        # 不局限于 SUCCEEDED——FAILED/SUSPENDED 也要让搜索模块跳过（见函数 docstring）。
        succeeded_job = make_job_ref(job_id="job-succeeded")
        failed_job = make_job_ref(job_id="job-failed")
        repository.record_delivery(
            make_record(succeeded_job, DeliveryStatus.SUCCEEDED), db_path=db_path
        )
        repository.record_delivery(
            make_record(failed_job, DeliveryStatus.FAILED, failure_reason="login_failed"),
            db_path=db_path,
        )

        keys = repository.get_delivered_job_keys(db_path=db_path)
        assert keys == {("workday", "job-succeeded"), ("workday", "job-failed")}


class TestCredentials:
    def test_upsert_and_get_round_trip(self, db_path):
        repository.upsert_credential(
            "workday",
            "acme.wd1.myworkdayjobs.com",
            username="me@example.com",
            password="s3cret",
            email="me@example.com",
            db_path=db_path,
        )
        cred = repository.get_credential(
            "workday", "acme.wd1.myworkdayjobs.com", db_path=db_path
        )
        assert cred is not None
        assert cred.username == "me@example.com"
        assert cred.password == "s3cret"

    def test_missing_returns_none(self, db_path):
        assert repository.get_credential("workday", "nope", db_path=db_path) is None

    def test_same_platform_different_portal_isolated(self, db_path):
        # PRD 二：同一平台（workday）下每个雇主门户独立账号。
        repository.upsert_credential(
            "workday", "acme.wd1.myworkdayjobs.com", username="a@x.com", db_path=db_path
        )
        repository.upsert_credential(
            "workday", "globex.wd5.myworkdayjobs.com", username="b@x.com", db_path=db_path
        )

        acme = repository.get_credential("workday", "acme.wd1.myworkdayjobs.com", db_path=db_path)
        globex = repository.get_credential(
            "workday", "globex.wd5.myworkdayjobs.com", db_path=db_path
        )
        assert acme.username == "a@x.com"
        assert globex.username == "b@x.com"

    def test_upsert_same_key_updates(self, db_path):
        repository.upsert_credential("workday", "acme", username="old", db_path=db_path)
        repository.upsert_credential("workday", "acme", username="new", db_path=db_path)

        cred = repository.get_credential("workday", "acme", db_path=db_path)
        assert cred.username == "new"


class TestSuspendedQuestions:
    def test_save_then_pending_then_answer_then_resuspendable(self, db_path):
        job = make_job_ref(job_id="job-suspended")
        questions = [
            Question(job=job, field_path="preferences.visa", question="Need visa?", page="p1"),
            Question(job=job, field_path=None, question="Why this role?", page="p1"),
        ]
        repository.save_suspended_questions(job, questions, db_path=db_path)

        pending = repository.pending_unanswered_questions(db_path=db_path)
        assert len(pending) == 2
        assert {p.question.question for p in pending} == {"Need visa?", "Why this role?"}

        # 尚未全部回答 -> 还不能重投
        assert repository.resuspendable_jobs(db_path=db_path) == []

        for p in pending:
            repository.record_answer(p.id, f"answer to {p.question.question}", db_path=db_path)

        # 全部回答完 -> 不再出现在待答清单里
        assert repository.pending_unanswered_questions(db_path=db_path) == []

        # 且该职位变成可重投
        resuspendable = repository.resuspendable_jobs(db_path=db_path)
        assert [j.key for j in resuspendable] == [("workday", "job-suspended")]

    def test_partial_answer_not_resuspendable(self, db_path):
        job = make_job_ref(job_id="job-partial")
        questions = [
            Question(job=job, question="Q1"),
            Question(job=job, question="Q2"),
        ]
        repository.save_suspended_questions(job, questions, db_path=db_path)
        pending = repository.pending_unanswered_questions(db_path=db_path)
        repository.record_answer(pending[0].id, "A1", db_path=db_path)

        assert repository.resuspendable_jobs(db_path=db_path) == []
        assert len(repository.pending_unanswered_questions(db_path=db_path)) == 1

    def test_clear_suspended_questions(self, db_path):
        job = make_job_ref(job_id="job-clear")
        repository.save_suspended_questions(
            job, [Question(job=job, question="Q1")], db_path=db_path
        )
        pending = repository.pending_unanswered_questions(db_path=db_path)
        repository.record_answer(pending[0].id, "A1", db_path=db_path)
        assert repository.resuspendable_jobs(db_path=db_path) != []

        repository.clear_suspended_questions("workday", "job-clear", db_path=db_path)
        assert repository.resuspendable_jobs(db_path=db_path) == []


class TestTransactionIntegrity:
    def test_exception_mid_write_rolls_back_no_partial(self, db_path):
        # connect() 上下文管理器：异常必须回滚，写入的行不得残留。
        from core.storage import db as db_module

        with pytest.raises(RuntimeError):
            with db_module.connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO easy_apply_count (created_at) VALUES (?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                raise RuntimeError("boom mid-transaction")

        assert repository.easy_apply_count_last_24h(db_path=db_path) == 0

    def test_save_suspended_questions_is_atomic(self, db_path):
        # executemany 批量插入必须整批原子：中途异常不得留下半批问题。
        from core.storage import db as db_module

        job = make_job_ref(job_id="job-atomic")
        job_json = job.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()
        with pytest.raises(RuntimeError):
            with db_module.connect(db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO suspended_questions
                        (platform, job_id, job_json, field_path, question, page, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("workday", "job-atomic", job_json, None, "Q1", "p1", now),
                        ("workday", "job-atomic", job_json, None, "Q2", "p1", now),
                    ],
                )
                raise RuntimeError("boom after executemany, before commit")

        assert repository.pending_unanswered_questions(db_path=db_path) == []


class TestRunRecords:
    def test_start_then_summary_round_trip(self, db_path):
        repository.record_run_start("run-1", db_path=db_path)
        # 结束前查询：还没有 summary_json，get_run_summary 返回 None。
        assert repository.get_run_summary("run-1", db_path=db_path) is None

        job = make_job_ref(job_id="job-suspended")
        summary = RunSummary(
            run_id="run-1",
            total=3,
            succeeded=1,
            failed_by_reason={"captcha_unsolved": 1},
            suspended=[job],
            unanswered_questions=[Question(job=job, question="Need visa?")],
        )
        repository.record_run_summary("run-1", summary, db_path=db_path)

        fetched = repository.get_run_summary("run-1", db_path=db_path)
        assert fetched == summary

    def test_missing_run_id_returns_none(self, db_path):
        assert repository.get_run_summary("no-such-run", db_path=db_path) is None


class TestEasyApplyCount:
    def test_increment_and_count_last_24h(self, db_path):
        assert repository.easy_apply_count_last_24h(db_path=db_path) == 0
        repository.increment_easy_apply(db_path=db_path)
        repository.increment_easy_apply(db_path=db_path)
        assert repository.easy_apply_count_last_24h(db_path=db_path) == 2

    def test_old_entries_excluded_from_window(self, db_path):
        from core.storage import db as db_module

        repository.increment_easy_apply(db_path=db_path)
        # 手动把一条记录的时间戳改到 25 小时前，模拟窗口外的旧记录。
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn = db_module.get_connection(db_path)
        try:
            conn.execute("UPDATE easy_apply_count SET created_at = ?", (old_ts,))
            conn.commit()
        finally:
            conn.close()

        assert repository.easy_apply_count_last_24h(db_path=db_path) == 0
