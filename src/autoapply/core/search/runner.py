"""autoapply.core.search.runner — fetch → dedupe → Gate A/B → optional LLM rerank → persist.

`run_search()` is the orchestration entry. Does not call deliver.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from autoapply.core.bio.store import BioStore, YamlBioStore
from autoapply.core.config import SearchSettings, Settings, load_settings
from autoapply.core.contracts import SearchCandidate, SearchJob, SearchRunSummary
from autoapply.core.search.dedupe import dedupe_in_run
from autoapply.core.search.fetch import SearchAdapter
from autoapply.core.search.fetch.jobspy import JobSpyAdapter
from autoapply.core.search.gates import assign_shortlist, attach_yoe, evaluate_job, shortlist_of
from autoapply.core.search.prefs import SearchPrefs, load_search_prefs
from autoapply.core.search.rerank import (
    CliSearchRerankClient,
    SearchRerankClient,
    apply_rerank,
    compact_bio_excerpt,
    llm_kept_count,
    review_order,
)
from autoapply.core.search import store as search_store
from autoapply.core.storage import repository

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "data" / "search" / "runs"


@dataclass
class SearchRunResult:
    summary: SearchRunSummary
    jobs: list[SearchJob]
    candidates: list[SearchCandidate] = field(default_factory=list)
    shortlist: list[SearchCandidate] = field(default_factory=list)
    output_dir: Path = Path()
    llm_error: str | None = None


def run_search(
    *,
    settings: Settings | None = None,
    bio_store: BioStore | None = None,
    adapter: SearchAdapter | None = None,
    keywords: Sequence[str] | None = None,
    locations: Sequence[str] | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    db_path: str | Path | None = None,
    delivered_keys: set[tuple[str, str]] | None = None,
    rerank_client: SearchRerankClient | None = None,
    resume_excerpt: str | None = None,
) -> SearchRunResult:
    """Fetch, dedupe, score, shortlist, optional LLM rerank, persist. One query failure does not abort the run."""
    resolved_settings = settings or load_settings()
    search_settings = resolved_settings.search
    bio = bio_store or YamlBioStore()
    prefs = load_search_prefs(bio, search_settings, keywords=keywords, locations=locations)
    fetch_adapter = adapter or JobSpyAdapter()
    run_id = run_id or uuid.uuid4().hex
    output_dir = (output_root or DEFAULT_OUTPUT_ROOT) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    fetched: list[SearchJob] = []
    query_errors = 0
    for keyword, location in _query_pairs(prefs):
        try:
            batch = fetch_adapter.search(
                keywords=keyword,
                location=location,
                is_remote=prefs.remote,
                results_wanted=search_settings.results_wanted,
                hours_old=search_settings.hours_old,
                country_indeed=search_settings.country_indeed,
                sites=list(search_settings.sites),
            )
        except Exception:
            query_errors += 1
            log.exception("search query failed keyword=%r location=%r", keyword, location)
            continue
        fetched.extend(batch)

    search_store.clear_current_flag(db_path)

    unique = dedupe_in_run([attach_yoe(job) for job in fetched])
    delivered = (
        delivered_keys
        if delivered_keys is not None
        else repository.get_delivered_job_keys(db_path=db_path)
    )
    seen = search_store.seen_keys(
        lookback_hours=search_settings.seen_lookback_hours,
        db_path=db_path,
    )

    candidates = [
        _annotate(job, prefs, search_settings, delivered=delivered, seen=seen)
        for job in unique
    ]
    candidates = assign_shortlist(candidates, shortlist_cap=search_settings.shortlist_cap)
    shortlist = shortlist_of(candidates)
    llm_error: str | None = None
    if search_settings.llm_rerank and shortlist:
        candidates, shortlist, llm_error = _rerank_shortlist(
            candidates,
            shortlist,
            prefs=prefs,
            bio=bio,
            settings=resolved_settings,
            client=rerank_client,
            resume_excerpt=resume_excerpt,
        )
    elif search_settings.llm_rerank:
        seen_n = sum(1 for c in candidates if c.drop_reason == "already_seen")
        llm_error = (
            "LLM rerank skipped: shortlist is empty"
            + (f" ({seen_n} jobs already seen this week)" if seen_n else "")
        )

    failed_reason = None
    if not fetched and query_errors:
        failed_reason = "all_queries_failed"

    summary = SearchRunSummary(
        run_id=run_id,
        fetched=len(fetched),
        after_dedupe=len(unique),
        dropped_gate_a=sum(
            1
            for c in candidates
            if c.drop_reason in {"required_yoe", "title_empty"}
        ),
        shortlisted=len(shortlist),
        llm_kept=llm_kept_count(shortlist),
        selected=0,
        failed_reason=failed_reason,
    )
    search_store.record_run(
        run_id=run_id,
        keywords=list(prefs.keywords),
        summary=summary,
        candidates=candidates,
        db_path=db_path,
    )
    _write_snapshot(
        output_dir,
        jobs=unique,
        candidates=candidates,
        summary=summary,
        prefs=prefs,
        settings=search_settings,
        resume_excerpt=resume_excerpt,
    )
    return SearchRunResult(
        summary=summary,
        jobs=unique,
        candidates=candidates,
        shortlist=shortlist,
        output_dir=output_dir,
        llm_error=llm_error,
    )


def _annotate(
    job: SearchJob,
    prefs: SearchPrefs,
    settings: SearchSettings,
    *,
    delivered: set[tuple[str, str]],
    seen: set[tuple[str, str]],
) -> SearchCandidate:
    candidate = evaluate_job(job, prefs, score_threshold=settings.score_threshold)
    if job.key in delivered:
        return candidate.model_copy(update={"drop_reason": "already_delivered"})
    if job.key in seen:
        return candidate.model_copy(update={"drop_reason": "already_seen"})
    return candidate


def _rerank_shortlist(
    candidates: list[SearchCandidate],
    shortlist: list[SearchCandidate],
    *,
    prefs: SearchPrefs,
    bio: BioStore,
    settings: Settings,
    client: SearchRerankClient | None,
    resume_excerpt: str | None = None,
) -> tuple[list[SearchCandidate], list[SearchCandidate], str | None]:
    """LLM on the shortlist only. Any failure → Gate B order, llm_keep left null."""
    search_settings = settings.search
    reranker = client or CliSearchRerankClient(
        settings.llm,
        timeout=search_settings.llm_timeout,
        model=search_settings.llm_model,
        transport=search_settings.llm_transport,
    )
    try:
        items = reranker.rerank(
            shortlist,
            prefs=prefs,
            bio_excerpt=compact_bio_excerpt(bio, prefs, resume_excerpt=resume_excerpt),
        )
        candidates = apply_rerank(candidates, items)
        return candidates, review_order(shortlist_of(candidates)), None
    except Exception as exc:
        log.exception("llm rerank failed; falling back to Gate B shortlist order")
        return candidates, shortlist_of(candidates), str(exc)


def _query_pairs(prefs: SearchPrefs) -> list[tuple[str, str | None]]:
    locations = prefs.locations or [None]
    return [(keyword, location) for keyword in prefs.keywords for location in locations]


def _write_snapshot(
    output_dir: Path,
    *,
    jobs: list[SearchJob],
    candidates: list[SearchCandidate],
    summary: SearchRunSummary,
    prefs: SearchPrefs,
    settings: SearchSettings,
    resume_excerpt: str | None = None,
) -> None:
    (output_dir / "jobs.json").write_text(
        json.dumps([job.model_dump(mode="json") for job in jobs], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "candidates.json").write_text(
        json.dumps(
            [c.model_dump(mode="json") for c in candidates],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    meta = {
        "summary": summary.model_dump(mode="json"),
        "keywords": prefs.keywords,
        "locations": prefs.locations,
        "remote": prefs.remote,
        "sites": settings.sites,
        "source": "resume_query" if resume_excerpt else "keywords",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
