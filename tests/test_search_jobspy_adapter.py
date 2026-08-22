"""tests.test_search_jobspy_adapter — maps scrape_jobs output; no live boards."""

from __future__ import annotations

from autoapply.core.search.fetch.jobspy import JobSpyAdapter


def test_adapter_normalizes_rows_and_continues_after_one_site_error():
    def fake_scrape(**kwargs):
        site = kwargs["site_name"][0]
        if site == "glassdoor":
            raise RuntimeError("blocked")
        return [
            {
                "site": site,
                "id": f"{site}-1",
                "title": "Product Designer",
                "company": "Acme",
                "job_url": "https://example.com/jobs/1",
                "description": "Hello",
            }
        ]

    adapter = JobSpyAdapter(scrape_jobs=fake_scrape)
    jobs = adapter.search(
        keywords="product designer",
        location="Toronto, ON",
        is_remote=True,
        results_wanted=10,
        hours_old=72,
        country_indeed="USA",
        sites=["linkedin", "glassdoor", "indeed"],
    )
    platforms = {job.platform for job in jobs}
    assert platforms == {"linkedin", "indeed"}
    assert all(job.title == "Product Designer" for job in jobs)


def test_linkedin_requests_full_description():
    seen: list[dict] = []

    def fake_scrape(**kwargs):
        seen.append(kwargs)
        return []

    JobSpyAdapter(scrape_jobs=fake_scrape).search(
        keywords="ux",
        location=None,
        is_remote=False,
        results_wanted=5,
        hours_old=24,
        country_indeed="USA",
        sites=["linkedin"],
    )
    assert seen[0]["linkedin_fetch_description"] is True
    assert seen[0]["country_indeed"] == "usa"
