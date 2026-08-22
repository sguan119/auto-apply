"""JobSpy adapter: wraps python-jobspy. pandas stays inside this file."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from autoapply.core.contracts import SearchJob
from autoapply.core.search.fetch.base import SearchAdapter
from autoapply.core.search.normalize import normalize_jobspy_row

log = logging.getLogger(__name__)

ScrapeFn = Callable[..., Any]

_SITE_ALIASES = {
    "ziprecruiter": "zip_recruiter",
    "zip_recruiter": "zip_recruiter",
}


def _normalize_site_name(site: str) -> str:
    key = site.strip().lower()
    return _SITE_ALIASES.get(key, key)


class JobSpyAdapter(SearchAdapter):
    """One JobSpy `scrape_jobs` call per site so one board failing does not abort the rest."""

    name = "jobspy"

    def __init__(self, scrape_jobs: ScrapeFn | None = None) -> None:
        # Injected in tests. Default import is lazy so unit tests need not import JobSpy
        # unless they construct this adapter without a fake.
        self._scrape_jobs = scrape_jobs

    def _scrape(self) -> ScrapeFn:
        if self._scrape_jobs is not None:
            return self._scrape_jobs
        from jobspy import scrape_jobs

        return scrape_jobs

    def search(
        self,
        *,
        keywords: str,
        location: str | None,
        is_remote: bool,
        results_wanted: int,
        hours_old: int,
        country_indeed: str,
        sites: list[str],
    ) -> list[SearchJob]:
        jobs: list[SearchJob] = []
        scrape = self._scrape()
        for site in sites:
            site_name = _normalize_site_name(site)
            kwargs: dict[str, Any] = {
                "site_name": [site_name],
                "search_term": keywords,
                "location": location or "",
                "results_wanted": results_wanted,
                "hours_old": hours_old,
                "country_indeed": country_indeed.lower(),
                "is_remote": is_remote,
                "verbose": 0,
                "description_format": "markdown",
            }
            if site_name == "linkedin":
                kwargs["linkedin_fetch_description"] = True
            try:
                frame = scrape(**kwargs)
            except Exception:
                log.exception(
                    "JobSpy failed for site=%s keyword=%r location=%r",
                    site_name,
                    keywords,
                    location,
                )
                continue
            jobs.extend(_jobs_from_frame(frame, default_platform=site_name))
        return jobs


def _jobs_from_frame(frame: Any, *, default_platform: str) -> list[SearchJob]:
    if frame is None:
        return []
    records: list[dict[str, Any]]
    if hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    elif isinstance(frame, list):
        records = list(frame)
    else:
        return []
    jobs: list[SearchJob] = []
    for record in records:
        cleaned = {key: _jsonable(value) for key, value in dict(record).items()}
        job = normalize_jobspy_row(cleaned, default_platform=default_platform)
        if job is not None:
            jobs.append(job)
    return jobs


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    return value
