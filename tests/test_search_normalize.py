"""tests.test_search_normalize — JobSpy row → SearchJob (no network)."""

from __future__ import annotations

from autoapply.core.search.normalize import (
    canonicalize_url,
    job_id_for,
    normalize_jobspy_row,
)


def test_prefers_direct_apply_url_and_strips_tracking():
    job = normalize_jobspy_row(
        {
            "site": "linkedin",
            "id": "abc",
            "title": "Product Designer",
            "company": "Acme",
            "job_url": "https://www.linkedin.com/jobs/view/abc?utm_source=jobspy",
            "job_url_direct": "https://acme.wd1.myworkdayjobs.com/job/abc?utm_campaign=li",
            "location": "Toronto, ON",
            "description": "Design things.",
        }
    )
    assert job is not None
    assert job.platform == "linkedin"
    assert job.job_id == "abc"
    assert str(job.url) == "https://acme.wd1.myworkdayjobs.com/job/abc"
    assert job.title == "Product Designer"
    assert job.company == "Acme"


def test_falls_back_to_listing_url():
    job = normalize_jobspy_row(
        {
            "site": "indeed",
            "id": "x1",
            "title": "UX Designer",
            "company_name": "Globex",
            "job_url": "https://www.indeed.com/viewjob?jk=x1",
        }
    )
    assert job is not None
    assert job.company == "Globex"
    assert "indeed.com" in str(job.url)


def test_missing_url_returns_none():
    assert (
        normalize_jobspy_row({"site": "indeed", "title": "X", "company": "Y"}) is None
    )


def test_job_id_hashes_canonical_url_when_board_id_missing():
    url = "https://example.com/jobs/42"
    first = job_id_for(None, canonicalize_url(url))
    second = job_id_for("  ", canonicalize_url(url))
    assert first == second
    assert len(first) == 16


def test_canonicalize_drops_utm_and_lowercases_host():
    assert (
        canonicalize_url("HTTPS://Example.COM/jobs/1?utm_source=x&foo=1")
        == "https://example.com/jobs/1?foo=1"
    )
