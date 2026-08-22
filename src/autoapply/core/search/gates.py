"""Gate A (hard drop) + Gate B (cheap score) + shortlist cap (docs/search-spec.md §6).

Pure functions: no sqlite, no LLM, no typer. Pytest hits this first.
"""

from __future__ import annotations

import re
from typing import Sequence

from autoapply.core.contracts import SearchCandidate, SearchJob
from autoapply.core.search.prefs import SearchPrefs

TITLE_FIT_MIN_FOR_TOP = 0.3
YOE_MISSING_FIT = 0.60
YOE_PREFERRED_HIGH_FIT = 0.60
YOE_SLIGHTLY_OVER_FIT = 0.25
YOE_BELOW_MIN_FIT = 0.85
SIGNAL_RICH = 1.0
SIGNAL_THIN = 0.3
MIN_DESC_CHARS = 80

W_TITLE = 0.50
W_YOE = 0.30
W_SIGNAL = 0.20

_RANGE_YOE = re.compile(
    r"(\d+)\s*[-–]\s*(\d+)\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_PLUS_YOE = re.compile(r"(\d+)\s*\+\s*(?:years?|yrs?)\b", re.IGNORECASE)
_SIMPLE_YOE = re.compile(r"(\d+)\s*(?:years?|yrs?)\b", re.IGNORECASE)
_PREFERRED = re.compile(r"preferred|nice to have|plus", re.IGNORECASE)


def extract_yoe(title: str, description: str | None) -> tuple[int | None, bool]:
    """Return (years, is_preferred). First match in title, then description."""
    for blob in (title or "", description or ""):
        years, preferred = _extract_from_text(blob)
        if years is not None:
            return years, preferred
    return None, False


def _extract_from_text(text: str) -> tuple[int | None, bool]:
    for pattern in (_RANGE_YOE, _PLUS_YOE, _SIMPLE_YOE):
        match = pattern.search(text)
        if match is None:
            continue
        years = int(match.group(1))
        window = text[max(0, match.start() - 40) : match.end() + 40]
        preferred = _PREFERRED.search(window) is not None
        return years, preferred
    return None, False


def attach_yoe(job: SearchJob) -> SearchJob:
    years, preferred = extract_yoe(job.title, job.description)
    return job.model_copy(update={"extracted_yoe": years, "yoe_is_preferred": preferred})


def title_fit(title: str, keywords: Sequence[str]) -> float:
    if not (title or "").strip():
        return 0.0
    usable = [kw.strip().lower() for kw in keywords if kw and str(kw).strip()]
    if not usable:
        return 0.5
    title_l = title.lower()
    hits = 0
    for kw in usable:
        if kw in title_l or all(token in title_l for token in kw.split()):
            hits += 1
    return hits / len(usable)


def yoe_fit(
    extracted_yoe: int | None,
    *,
    is_preferred: bool,
    yoe_prefer_min: int,
    yoe_prefer_max: int,
) -> float:
    if extracted_yoe is None:
        return YOE_MISSING_FIT
    if yoe_prefer_min <= extracted_yoe <= yoe_prefer_max:
        return 1.0
    if extracted_yoe > yoe_prefer_max:
        if is_preferred:
            return YOE_PREFERRED_HIGH_FIT
        return YOE_SLIGHTLY_OVER_FIT
    return YOE_BELOW_MIN_FIT


def signal_score(description: str | None) -> float:
    length = len((description or "").strip())
    return SIGNAL_RICH if length >= MIN_DESC_CHARS else SIGNAL_THIN


def score_job(job: SearchJob, prefs: SearchPrefs) -> tuple[float, float]:
    """Return (score, title_fit_value)."""
    tf = title_fit(job.title, prefs.keywords)
    yf = yoe_fit(
        job.extracted_yoe,
        is_preferred=job.yoe_is_preferred,
        yoe_prefer_min=prefs.yoe_prefer_min,
        yoe_prefer_max=prefs.yoe_prefer_max,
    )
    sig = signal_score(job.description)
    return W_TITLE * tf + W_YOE * yf + W_SIGNAL * sig, tf


def evaluate_job(
    job: SearchJob,
    prefs: SearchPrefs,
    *,
    score_threshold: float,
) -> SearchCandidate:
    """Gate A then Gate B. Does not assign prefilter_rank (cap is applied on the batch)."""
    candidate = SearchCandidate.model_validate(job.model_dump())
    if not (job.title or "").strip():
        candidate.drop_reason = "title_empty"
        candidate.score = 0.0
        return candidate

    if (
        job.extracted_yoe is not None
        and not job.yoe_is_preferred
        and job.extracted_yoe > prefs.yoe_prefer_max
    ):
        candidate.drop_reason = "required_yoe"

    score, tf = score_job(job, prefs)
    candidate.score = round(score, 4)
    if candidate.drop_reason:
        return candidate
    if tf < TITLE_FIT_MIN_FOR_TOP:
        candidate.drop_reason = "title_mismatch"
        return candidate
    if score < score_threshold:
        candidate.drop_reason = "below_threshold"
    return candidate


def assign_shortlist(
    candidates: list[SearchCandidate],
    *,
    shortlist_cap: int,
) -> list[SearchCandidate]:
    """Set prefilter_rank 1..cap on eligible jobs (drop_reason is None), score DESC."""
    eligible = [c for c in candidates if c.drop_reason is None]
    eligible.sort(key=lambda c: c.score, reverse=True)
    ranked = {
        (c.platform, c.job_id): c.model_copy(update={"prefilter_rank": i})
        for i, c in enumerate(eligible[: max(0, shortlist_cap)], start=1)
    }
    return [ranked.get((c.platform, c.job_id), c) for c in candidates]


def shortlist_of(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    ranked = [c for c in candidates if c.prefilter_rank is not None]
    ranked.sort(key=lambda c: c.prefilter_rank or 0)
    return ranked
