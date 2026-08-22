"""tests.test_search_dedupe — in-run key collapse."""

from __future__ import annotations

from autoapply.core.contracts import SearchJob
from autoapply.core.search.dedupe import dedupe_in_run


def _job(job_id: str, description: str | None, platform: str = "linkedin") -> SearchJob:
    return SearchJob(
        platform=platform,
        job_id=job_id,
        url=f"https://example.com/jobs/{job_id}-{platform}",
        title="Product Designer",
        company="Acme",
        description=description,
    )


def test_duplicate_key_keeps_longer_description():
    jobs = [
        _job("1", "short"),
        _job("1", "a much longer description that should win"),
        _job("2", "other"),
    ]
    unique = dedupe_in_run(jobs)
    assert [j.job_id for j in unique] == ["1", "2"]
    assert unique[0].description is not None
    assert "longer" in unique[0].description


def test_same_title_on_two_platforms_is_kept():
    unique = dedupe_in_run(
        [_job("1", "a", "linkedin"), _job("1", "a", "indeed")]
    )
    assert len(unique) == 2
