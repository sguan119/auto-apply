"""tests.test_run_log —— core.storage.run_log.RunLogger 的 JSONL 写入测试。"""

from __future__ import annotations

import json

from core.storage.run_log import RunLogger


class TestRunLogger:
    def test_creates_logs_dir_and_file(self, tmp_path):
        logs_dir = tmp_path / "logs"
        logger = RunLogger("run-1", logs_dir=logs_dir)
        assert logger.path == logs_dir / "run-run-1.jsonl"
        assert logs_dir.exists()

    def test_log_appends_valid_jsonl_lines(self, tmp_path):
        logger = RunLogger("run-1", logs_dir=tmp_path)
        logger.log("step_started", job_id="job-1", platform="workday")
        logger.log("llm_decision", job_id="job-1", action="fill", confidence=0.9)

        lines = logger.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["event_type"] == "step_started"
        assert first["run_id"] == "run-1"
        assert first["job_id"] == "job-1"
        assert "timestamp" in first

        second = json.loads(lines[1])
        assert second["event_type"] == "llm_decision"
        assert second["confidence"] == 0.9

    def test_log_survives_non_json_native_field(self, tmp_path):
        from pathlib import Path

        logger = RunLogger("run-2", logs_dir=tmp_path)
        logger.log("artifact_written", resume_path=Path("data/artifacts/x/resume.pdf"))

        line = logger.path.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        assert "resume.pdf" in record["resume_path"]

    def test_multiple_runs_write_separate_files(self, tmp_path):
        logger_a = RunLogger("run-a", logs_dir=tmp_path)
        logger_b = RunLogger("run-b", logs_dir=tmp_path)
        logger_a.log("x")
        logger_b.log("y")

        assert logger_a.path != logger_b.path
        assert len(logger_a.path.read_text(encoding="utf-8").splitlines()) == 1
        assert len(logger_b.path.read_text(encoding="utf-8").splitlines()) == 1
