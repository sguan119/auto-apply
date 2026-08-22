"""Search fetch adapters. JobSpy is the MVP source (docs/search-spec.md)."""

from autoapply.core.search.fetch.base import SearchAdapter
from autoapply.core.search.fetch.jobspy import JobSpyAdapter

__all__ = ["SearchAdapter", "JobSpyAdapter"]
