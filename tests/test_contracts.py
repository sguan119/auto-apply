"""tests.test_contracts —— core.contracts 契约的构造/校验/序列化往返测试（spec 决策五）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.contracts import (
    Answer,
    BioWriteback,
    DeliveryRecord,
    DeliveryStatus,
    DeliveryTask,
    FieldValueSource,
    FilledField,
    JobRef,
    Question,
    RunSummary,
)


def make_job_ref(**overrides) -> JobRef:
    defaults = dict(
        platform="linkedin",
        job_id="job-123",
        url="https://example.com/jobs/123",
        title="Software Engineer",
        company="Acme Corp",
        score=0.87,
    )
    defaults.update(overrides)
    return JobRef(**defaults)


class TestJobRef:
    def test_construct_valid(self):
        job = make_job_ref()
        assert job.platform == "linkedin"
        assert job.job_id == "job-123"
        assert str(job.url).startswith("https://example.com/jobs/123")
        assert job.score == pytest.approx(0.87)

    def test_key_is_platform_and_job_id(self):
        job = make_job_ref()
        assert job.key == ("linkedin", "job-123")

    def test_rejects_bad_url(self):
        with pytest.raises(ValidationError):
            make_job_ref(url="not-a-url")

    def test_rejects_missing_required_field(self):
        with pytest.raises(ValidationError):
            JobRef(platform="linkedin", job_id="job-123")

    def test_dump_json_round_trip(self):
        job = make_job_ref()
        restored = JobRef.model_validate_json(job.model_dump_json())
        assert restored == job


class TestFilledField:
    def test_construct_valid(self):
        field = FilledField(
            question="Do you require visa sponsorship?",
            value="No",
            value_source=FieldValueSource.BIO,
        )
        assert field.value_source == FieldValueSource.BIO

    def test_rejects_bad_value_source(self):
        with pytest.raises(ValidationError):
            FilledField(question="q", value="v", value_source="not_a_source")

    def test_dump_json_round_trip(self):
        field = FilledField(question="q", value="v", value_source="llm_generated")
        restored = FilledField.model_validate_json(field.model_dump_json())
        assert restored == field


class TestDeliveryTask:
    def test_construct_valid(self):
        task = DeliveryTask(
            job=make_job_ref(),
            resume_pdf=Path("data/artifacts/linkedin/job-123/resume.pdf"),
            cover_letter_pdf=None,
        )
        assert task.cover_letter_pdf is None
        assert isinstance(task.resume_pdf, Path)

    def test_rejects_missing_job(self):
        with pytest.raises(ValidationError):
            DeliveryTask(resume_pdf=Path("resume.pdf"))

    def test_dump_json_round_trip(self):
        task = DeliveryTask(
            job=make_job_ref(),
            resume_pdf=Path("resume.pdf"),
            cover_letter_pdf=Path("cover.pdf"),
        )
        restored = DeliveryTask.model_validate_json(task.model_dump_json())
        assert restored == task


class TestDeliveryRecord:
    def test_construct_valid(self):
        record = DeliveryRecord(
            job=make_job_ref(),
            status=DeliveryStatus.SUCCEEDED,
            filled_fields=[
                FilledField(question="q", value="v", value_source=FieldValueSource.BIO)
            ],
            failure_reason=None,
            run_id="run-1",
            started_at=datetime(2026, 7, 10, 9, 0, 0),
            finished_at=datetime(2026, 7, 10, 9, 5, 0),
        )
        assert record.status is DeliveryStatus.SUCCEEDED
        assert len(record.filled_fields) == 1

    def test_rejects_bad_status(self):
        with pytest.raises(ValidationError):
            DeliveryRecord(
                job=make_job_ref(),
                status="not_a_status",
                run_id="run-1",
                started_at=datetime.now(),
                finished_at=datetime.now(),
            )

    def test_dump_json_round_trip(self):
        record = DeliveryRecord(
            job=make_job_ref(),
            status=DeliveryStatus.FAILED,
            failure_reason="captcha_unsolved",
            run_id="run-1",
            started_at=datetime(2026, 7, 10, 9, 0, 0),
            finished_at=datetime(2026, 7, 10, 9, 5, 0),
        )
        restored = DeliveryRecord.model_validate_json(record.model_dump_json())
        assert restored == record


class TestBioWriteback:
    def test_construct_valid(self):
        wb = BioWriteback(
            field_path="preferences.visa_sponsorship_needed",
            question="Do you require visa sponsorship?",
            answer="No",
        )
        assert wb.field_path == "preferences.visa_sponsorship_needed"

    def test_rejects_missing_field(self):
        with pytest.raises(ValidationError):
            BioWriteback(field_path="x")

    def test_dump_json_round_trip(self):
        wb = BioWriteback(field_path="x.y", question="q", answer="a")
        restored = BioWriteback.model_validate_json(wb.model_dump_json())
        assert restored == wb


class TestQuestionAndAnswer:
    def test_construct_question_valid(self):
        q = Question(
            job=make_job_ref(),
            field_path="preferences.visa_sponsorship_needed",
            question="Do you require visa sponsorship?",
            page="Voluntary Disclosures",
        )
        assert q.page == "Voluntary Disclosures"

    def test_question_field_path_optional(self):
        q = Question(job=make_job_ref(), question="Tell us why you want this job")
        assert q.field_path is None

    def test_answer_carries_question_back(self):
        q = Question(job=make_job_ref(), question="Do you require visa sponsorship?")
        answer = Answer(question=q, answer="No")
        assert answer.question == q
        assert answer.answer == "No"

    def test_dump_json_round_trip(self):
        q = Question(job=make_job_ref(), question="q", field_path="a.b")
        answer = Answer(question=q, answer="yes")
        restored = Answer.model_validate_json(answer.model_dump_json())
        assert restored == answer


class TestRunSummary:
    def test_construct_valid(self):
        job = make_job_ref()
        summary = RunSummary(
            run_id="run-1",
            total=10,
            succeeded=6,
            failed_by_reason={"captcha_unsolved": 2, "login_failed": 1},
            suspended=[job],
            unanswered_questions=[Question(job=job, question="q")],
        )
        assert summary.total == 10
        assert summary.failed_by_reason["captcha_unsolved"] == 2
        assert summary.suspended == [job]

    def test_defaults_are_empty(self):
        summary = RunSummary(run_id="run-1", total=0, succeeded=0)
        assert summary.failed_by_reason == {}
        assert summary.suspended == []
        assert summary.unanswered_questions == []

    def test_dump_json_round_trip(self):
        job = make_job_ref()
        summary = RunSummary(
            run_id="run-1",
            total=3,
            succeeded=1,
            failed_by_reason={"login_failed": 1},
            suspended=[job],
            unanswered_questions=[Question(job=job, question="q")],
        )
        restored = RunSummary.model_validate_json(summary.model_dump_json())
        assert restored == summary


class TestDeliveryStatus:
    def test_has_exactly_the_spec_states(self):
        expected = {
            "PENDING",
            "OPENING",
            "AUTHENTICATING",
            "FILLING",
            "WAITING_USER",
            "READY_TO_SUBMIT",
            "SUBMITTING",
            "CONFIRMING",
            "SUCCEEDED",
            "FAILED",
            "SUSPENDED",
        }
        actual = {member.name for member in DeliveryStatus}
        assert actual == expected

    def test_values_are_stable_snake_case(self):
        # 阶段 2 会把 `status.value` 直接存进 SQLite TEXT 列；这些字符串一旦落库
        # 就成了持久化契约，改动会让旧数据无法回读。锁死值映射，防止静默重命名。
        assert {m.name: m.value for m in DeliveryStatus} == {
            "PENDING": "pending",
            "OPENING": "opening",
            "AUTHENTICATING": "authenticating",
            "FILLING": "filling",
            "WAITING_USER": "waiting_user",
            "READY_TO_SUBMIT": "ready_to_submit",
            "SUBMITTING": "submitting",
            "CONFIRMING": "confirming",
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
            "SUSPENDED": "suspended",
        }


class TestFieldValueSource:
    def test_values_are_stable(self):
        # 同上：value_source 会随 FilledField 落库，值字符串是持久化契约。
        assert {m.name: m.value for m in FieldValueSource} == {
            "BIO": "bio",
            "LLM_GENERATED": "llm_generated",
            "USER_ANSWER": "user_answer",
        }
