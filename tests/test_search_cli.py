"""tests.test_search_cli — thin search CLI (no live JobSpy)."""

from __future__ import annotations

from typer.testing import CliRunner

import autoapply.cli.search as search_cli
from autoapply.core.contracts import SearchCandidate, SearchJob, SearchRunSummary
from autoapply.core.search.prefs import EmptySearchKeywords
from autoapply.core.search.runner import SearchRunResult

runner = CliRunner()


def test_help_exits_zero():
    result = runner.invoke(search_cli.app, ["--help"])
    assert result.exit_code == 0
    assert "Search" in result.stdout or "search" in result.stdout.lower()


def test_run_prints_table_and_output_path(tmp_path, monkeypatch):
    job = SearchJob(
        platform="linkedin",
        job_id="1",
        url="https://example.com/jobs/1",
        title="UX Designer",
        company="Acme",
        location="Toronto, ON",
    )
    summary = SearchRunSummary(run_id="abc", fetched=1, after_dedupe=1)
    output_dir = tmp_path / "abc"

    def fake_run_search(**kwargs):
        candidate = SearchCandidate(
            platform="linkedin",
            job_id="1",
            url="https://example.com/jobs/1",
            title="UX Designer",
            company="Acme",
            location="Toronto, ON",
            score=0.8,
            prefilter_rank=1,
        )
        return SearchRunResult(
            summary=summary,
            jobs=[job],
            candidates=[candidate],
            shortlist=[candidate],
            output_dir=output_dir,
        )

    monkeypatch.setattr(search_cli, "run_search", fake_run_search)
    result = runner.invoke(search_cli.app, ["run", "-k", "UX designer"])
    assert result.exit_code == 0
    assert "UX Designer" in result.stdout
    assert "Acme" in result.stdout
    assert "candidates.json" in result.stdout


def test_run_without_keywords_exits_one(monkeypatch):
    def boom(**kwargs):
        raise EmptySearchKeywords("search requires at least one keyword")

    monkeypatch.setattr(search_cli, "run_search", boom)
    result = runner.invoke(search_cli.app, ["run"])
    assert result.exit_code == 1
    assert "keyword" in result.output.lower()


def test_list_reads_current_shortlist(tmp_path, monkeypatch):
    candidate = SearchCandidate(
        platform="linkedin",
        job_id="1",
        url="https://example.com/jobs/1",
        title="UX Designer",
        company="Acme",
        score=0.8,
        prefilter_rank=1,
    )
    monkeypatch.setattr(search_cli.search_store, "current_run_id", lambda: "abc")
    monkeypatch.setattr(
        search_cli.search_store, "load_shortlist", lambda run_id: [candidate]
    )
    result = runner.invoke(search_cli.app, ["list"])
    assert result.exit_code == 0
    assert "UX Designer" in result.stdout


def test_pick_requires_a_selector(monkeypatch):
    monkeypatch.setattr(search_cli.search_store, "current_run_id", lambda: "abc")
    monkeypatch.setattr(search_cli.search_store, "load_shortlist", lambda run_id: [])
    result = runner.invoke(search_cli.app, ["pick"])
    assert result.exit_code == 1
    assert "--id" in result.output or "shortlist" in result.output.lower()


def test_pick_ids_prints_path(tmp_path, monkeypatch):
    from autoapply.core.contracts import JobRef
    from autoapply.core.search.pick import PickResult

    candidate = SearchCandidate(
        platform="linkedin",
        job_id="1",
        url="https://example.com/jobs/1",
        title="UX Designer",
        company="Acme",
        score=0.8,
        prefilter_rank=1,
    )
    path = tmp_path / "selected.json"

    def fake_pick(job_keys, **kwargs):
        assert job_keys == ["linkedin:1"]
        return PickResult(
            job_refs=[
                JobRef(
                    platform="linkedin",
                    job_id="1",
                    url="https://example.com/jobs/1",
                    title="UX Designer",
                    company="Acme",
                    score=0.8,
                )
            ],
            path=path,
            run_id="abc",
        )

    monkeypatch.setattr(search_cli.search_store, "current_run_id", lambda: "abc")
    monkeypatch.setattr(
        search_cli.search_store, "load_shortlist", lambda run_id: [candidate]
    )
    monkeypatch.setattr(search_cli, "pick_jobs", fake_pick)
    result = runner.invoke(search_cli.app, ["pick", "--id", "linkedin:1"])
    assert result.exit_code == 0
    assert "UX Designer" in result.stdout
    assert "picked=1" in result.stdout
    assert "selected.json" in result.stdout


def test_from_resume_plan_only_does_not_fetch(tmp_path, monkeypatch):
    resume = tmp_path / "resume.md"
    resume.write_text("UX designer and game designer\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    called = {"search": False}

    def boom_search(**kwargs):
        called["search"] = True
        raise AssertionError("run_search should not run without --run")

    monkeypatch.setattr(search_cli, "run_search", boom_search)
    result = runner.invoke(
        search_cli.app,
        [
            "from-resume",
            str(resume),
            "-q",
            "product designer",
            "-q",
            "game designer",
            "--plan-out",
            str(plan_path),
        ],
    )
    assert result.exit_code == 0
    assert called["search"] is False
    assert "product designer" in result.stdout
    assert "game designer" in result.stdout
    assert "product designer" in plan_path.read_text(encoding="utf-8")


def test_from_resume_run_passes_queries_and_excerpt(tmp_path, monkeypatch):
    resume = tmp_path / "resume.md"
    resume.write_text("UX / Product Designer and Game Designer at U of T.\n", encoding="utf-8")
    captured: dict = {}

    def fake_run_search(**kwargs):
        captured.update(kwargs)
        job = SearchJob(
            platform="linkedin",
            job_id="1",
            url="https://example.com/jobs/1",
            title="UX Designer",
            company="Acme",
        )
        candidate = SearchCandidate(
            platform="linkedin",
            job_id="1",
            url="https://example.com/jobs/1",
            title="UX Designer",
            company="Acme",
            score=0.8,
            prefilter_rank=1,
        )
        return SearchRunResult(
            summary=SearchRunSummary(run_id="r1", fetched=1, after_dedupe=1, shortlisted=1),
            jobs=[job],
            candidates=[candidate],
            shortlist=[candidate],
            output_dir=tmp_path / "r1",
        )

    monkeypatch.setattr(search_cli, "run_search", fake_run_search)
    result = runner.invoke(
        search_cli.app,
        [
            "from-resume",
            str(resume),
            "--run",
            "--no-llm",
            "-q",
            "product designer",
            "-q",
            "game designer",
            "--plan-out",
            str(tmp_path / "plan.json"),
        ],
    )
    assert result.exit_code == 0
    assert captured["keywords"] == ["product designer", "game designer"]
    assert captured["resume_excerpt"]
    assert "UX Designer" in result.stdout
