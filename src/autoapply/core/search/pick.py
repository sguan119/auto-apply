"""Human pick → data/search/selected.json as JobRef[] (docs/search-spec.md §6.7).

Does not start deliver. Selection is stored on the current search run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from autoapply.core.contracts import JobRef, SearchCandidate
from autoapply.core.search.rerank import job_key_of, review_order
from autoapply.core.search import store as search_store

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SELECTED_PATH = _REPO_ROOT / "data" / "search" / "selected.json"


class PickError(ValueError):
    """User-facing pick failure (unknown keys, empty selection, no current run)."""


@dataclass
class PickResult:
    job_refs: list[JobRef]
    path: Path
    run_id: str


def parse_job_key(key: str) -> tuple[str, str]:
    text = key.strip()
    platform, sep, job_id = text.partition(":")
    if not sep or not platform or not job_id:
        raise PickError(f"job key must be platform:job_id, got {key!r}")
    return platform, job_id


def candidate_to_job_ref(candidate: SearchCandidate) -> JobRef:
    return JobRef(
        platform=candidate.platform,
        job_id=candidate.job_id,
        url=candidate.url,
        title=candidate.title,
        company=candidate.company,
        score=candidate.score,
    )


def resolve_pick_keys(
    shortlist: Sequence[SearchCandidate],
    *,
    ids: Sequence[str] | None = None,
    kept: bool = False,
    entire_shortlist: bool = False,
) -> list[str]:
    """Turn CLI flags into job_key strings. Explicit --id wins over --kept / --shortlist."""
    explicit = [k.strip() for k in (ids or []) if k and k.strip()]
    if explicit:
        return explicit
    ordered = review_order(shortlist)
    if kept:
        keys = [job_key_of(c) for c in ordered if c.llm_keep is True]
        if not keys:
            raise PickError("no LLM-kept jobs on the current shortlist (try --id or --shortlist)")
        return keys
    if entire_shortlist:
        keys = [job_key_of(c) for c in ordered]
        if not keys:
            raise PickError("current shortlist is empty")
        return keys
    raise PickError("pass --id / --ids, --kept, or --shortlist")


def pick_jobs(
    job_keys: Sequence[str],
    *,
    run_id: str | None = None,
    db_path: str | Path | None = None,
    output_path: Path | None = None,
) -> PickResult:
    """Mark selected jobs on the run and write JobRef[] JSON. Replaces the previous pick set."""
    resolved_run = run_id or search_store.current_run_id(db_path)
    if resolved_run is None:
        raise PickError("no current search run; run `search run` first")

    shortlist = search_store.load_shortlist(resolved_run, db_path=db_path)
    by_key = {job_key_of(c): c for c in shortlist}
    wanted: list[str] = []
    seen: set[str] = set()
    missing: list[str] = []
    for raw in job_keys:
        parse_job_key(raw)  # validate shape
        key = raw.strip()
        if key in seen:
            continue
        seen.add(key)
        if key not in by_key:
            missing.append(key)
            continue
        wanted.append(key)
    if missing:
        raise PickError("not on the current shortlist: " + ", ".join(missing))
    if not wanted:
        raise PickError("pick requires at least one job")

    tuples = {parse_job_key(key) for key in wanted}
    search_store.mark_selected(run_id=resolved_run, keys=tuples, db_path=db_path)
    refs = [candidate_to_job_ref(by_key[key]) for key in wanted]
    path = output_path or DEFAULT_SELECTED_PATH
    _write_job_refs(path, refs)
    return PickResult(job_refs=refs, path=path, run_id=resolved_run)


def _write_job_refs(path: Path, refs: Sequence[JobRef]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [ref.model_dump(mode="json") for ref in refs]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
