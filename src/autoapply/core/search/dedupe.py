"""In-run and cross-run job-key dedupe (docs/search-spec.md §6.2)."""

from __future__ import annotations

from autoapply.core.contracts import SearchJob


def richer(left: SearchJob, right: SearchJob) -> SearchJob:
    """Keep the posting with the longer description when keys collide."""
    left_len = len((left.description or "").strip())
    right_len = len((right.description or "").strip())
    return right if right_len > left_len else left


def dedupe_in_run(jobs: list[SearchJob]) -> list[SearchJob]:
    """Collapse duplicate (platform, job_id) in this fetch; preserve first-seen order."""
    by_key: dict[tuple[str, str], SearchJob] = {}
    order: list[tuple[str, str]] = []
    for job in jobs:
        key = job.key
        if key not in by_key:
            by_key[key] = job
            order.append(key)
        else:
            by_key[key] = richer(by_key[key], job)
    return [by_key[key] for key in order]
