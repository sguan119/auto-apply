"""Search fetch adapter ABC. One implementation per source (JobSpy first)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from autoapply.core.contracts import SearchJob


class SearchAdapter(ABC):
    """Fetch postings for one (keyword, location) query.

    Implementations must not leak pandas/DataFrame past this boundary — return SearchJob.
    A single site or query failure should raise (or return []) so the runner can continue.
    """

    name: str

    @abstractmethod
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
        """Return normalized jobs. May raise; the runner catches per query."""
