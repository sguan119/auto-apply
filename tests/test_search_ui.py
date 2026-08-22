"""tests.test_search_ui — local search test page API (no live JobSpy)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from autoapply.core.contracts import JobRef, SearchCandidate, SearchJob, SearchRunSummary
from autoapply.core.search.pick import PickResult
from autoapply.core.search.runner import SearchRunResult
from autoapply.web import search_app


def _fake_pick(tmp_path, job_keys):
    refs = [
        JobRef(
            platform="linkedin",
            job_id="1",
            url="https://example.com/jobs/1",
            title="UX Designer",
            company="Acme",
            score=0.8,
        )
    ]
    path = tmp_path / "selected.json"
    return PickResult(job_refs=refs, path=path, run_id="ui-1")


@pytest.fixture
def search_calls():
    return {}


@pytest.fixture
def client(tmp_path, monkeypatch, search_calls):
    shortlisted = SearchCandidate(
        platform="linkedin",
        job_id="1",
        url="https://example.com/jobs/1",
        title="UX Designer",
        company="Acme",
        location="Toronto, ON",
        score=0.8,
        prefilter_rank=1,
    )
    dropped = SearchCandidate(
        platform="indeed",
        job_id="2",
        url="https://example.com/jobs/2",
        title="Ice Cream Delivery",
        company="Cold Co",
        score=0.1,
        drop_reason="title_mismatch",
    )
    summary = SearchRunSummary(run_id="ui-1", fetched=2, after_dedupe=2, shortlisted=1)

    def fake_run_search(**kwargs):
        search_calls.update(kwargs)
        return SearchRunResult(
            summary=summary,
            jobs=[
                SearchJob(
                    platform="linkedin",
                    job_id="1",
                    url="https://example.com/jobs/1",
                    title="UX Designer",
                    company="Acme",
                )
            ],
            candidates=[shortlisted, dropped],
            shortlist=[shortlisted],
            output_dir=tmp_path / "ui-1",
        )

    monkeypatch.setattr(search_app, "run_search", fake_run_search)
    monkeypatch.setattr(
        search_app,
        "pick_jobs",
        lambda job_keys, **kwargs: _fake_pick(tmp_path, job_keys),
    )
    return TestClient(search_app.app)


def test_index_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AutoApply Search" in response.text


def test_api_search_returns_shortlist(client, search_calls):
    response = client.post(
        "/api/search",
        json={"keywords": ["UX designer"], "locations": ["Toronto, ON"], "quick": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["shortlisted"] == 1
    assert data["shortlist"][0]["title"] == "UX Designer"
    assert data["dropped"][0]["drop_reason"] == "title_mismatch"
    assert search_calls.get("resume_excerpt") is None


def test_index_includes_pick_controls(client):
    response = client.get("/")
    assert "Save picks" in response.text
    assert "LLM rerank shortlist" in response.text
    assert "Custom API" in response.text
    assert "Include already-seen jobs" in response.text
    assert "From résumé" in response.text
    assert "Propose queries" in response.text


def test_api_search_custom_api_sets_http_transport(client, search_calls):
    response = client.post(
        "/api/search",
        json={
            "keywords": ["UX designer"],
            "locations": ["Toronto, ON"],
            "quick": True,
            "llm_rerank": True,
            "llm_transport": "http",
        },
    )
    assert response.status_code == 200
    settings = search_calls["settings"]
    assert settings.search.llm_rerank is True
    assert settings.search.llm_transport == "http"


def test_api_search_include_seen_disables_lookback(client, search_calls):
    response = client.post(
        "/api/search",
        json={
            "keywords": ["UX designer"],
            "quick": True,
            "include_seen": True,
        },
    )
    assert response.status_code == 200
    assert search_calls["settings"].search.seen_lookback_hours == 0


def test_api_search_claude_cli_sets_cli_transport(client, search_calls):
    response = client.post(
        "/api/search",
        json={
            "keywords": ["UX designer"],
            "quick": True,
            "llm_rerank": True,
            "llm_transport": "cli",
        },
    )
    assert response.status_code == 200
    assert search_calls["settings"].search.llm_transport == "cli"


def test_api_pick_returns_jobrefs(client, tmp_path):
    response = client.post(
        "/api/pick",
        json={"job_keys": ["linkedin:1"], "run_id": "ui-1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "ui-1"
    assert data["selected"][0]["job_id"] == "1"
    assert "description" not in data["selected"][0]
    assert str(tmp_path / "selected.json") in data["path"]


def test_api_resume_plan_returns_queries(client, tmp_path, monkeypatch):
    from autoapply.core.search.resume_query import ResumeQueryPlan

    plan_calls = {}

    def fake_plan(resume_text, **kwargs):
        plan_calls["resume_text"] = resume_text
        plan_calls.update(kwargs)
        return ResumeQueryPlan(
            queries=["product designer", "game designer"],
            clusters=["product/ux", "game/level"],
            resume_summary="UX + game design.",
            notes="two tracks",
        )

    monkeypatch.setattr(search_app, "plan_queries", fake_plan)
    monkeypatch.setattr(search_app, "write_plan", lambda plan, path=None: tmp_path / "plan.json")
    response = client.post(
        "/api/resume-plan",
        json={"resume_text": "UX designer and game designer", "llm_transport": "http"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["queries"] == ["product designer", "game designer"]
    assert data["notes"] == "two tracks"
    assert plan_calls["resume_text"] == "UX designer and game designer"


def test_api_search_passes_resume_excerpt(client, search_calls):
    response = client.post(
        "/api/search",
        json={
            "keywords": ["product designer", "game designer"],
            "quick": True,
            "resume_excerpt": "UX + game design, MI student.",
        },
    )
    assert response.status_code == 200
    assert search_calls["keywords"] == ["product designer", "game designer"]
    assert search_calls["resume_excerpt"] == "UX + game design, MI student."
