"""tests.test_search_gates — Gate A/B + shortlist cap, no network."""

from __future__ import annotations

from autoapply.core.contracts import SearchJob
from autoapply.core.search.gates import (
    TITLE_FIT_MIN_FOR_TOP,
    assign_shortlist,
    attach_yoe,
    evaluate_job,
    extract_yoe,
    title_fit,
)
from autoapply.core.search.prefs import SearchPrefs

PREFS = SearchPrefs(
    keywords=["product designer", "UX designer"],
    yoe_prefer_min=0,
    yoe_prefer_max=3,
)
LONG_DESC = (
    "We are hiring a designer to work on product experiences across web "
    "and mobile platforms with researchers and engineers."
)


def _job(**overrides) -> SearchJob:
    data = dict(
        platform="linkedin",
        job_id="1",
        url="https://example.com/jobs/1",
        title="Product Designer",
        company="Acme",
        description=LONG_DESC,
    )
    data.update(overrides)
    return SearchJob(**data)


def test_extract_required_yoe_from_description():
    years, preferred = extract_yoe("Engineer", "Requires 8 years of experience.")
    assert years == 8
    assert preferred is False


def test_extract_preferred_yoe_is_flagged():
    years, preferred = extract_yoe("", "5+ years preferred")
    assert years == 5
    assert preferred is True


def test_blank_title_fit_is_zero():
    assert title_fit("   ", ["product designer"]) == 0.0


def test_gate_a_drops_required_yoe_over_max():
    job = attach_yoe(_job(description="Minimum 8 years of experience. " + LONG_DESC))
    candidate = evaluate_job(job, PREFS, score_threshold=0.35)
    assert candidate.drop_reason == "required_yoe"


def test_missing_yoe_is_not_dropped():
    job = attach_yoe(_job())
    candidate = evaluate_job(job, PREFS, score_threshold=0.35)
    assert candidate.drop_reason is None
    assert job.extracted_yoe is None
    assert candidate.score > 0


def test_preferred_high_yoe_is_not_hard_dropped():
    job = attach_yoe(_job(description="8 years preferred. " + LONG_DESC))
    candidate = evaluate_job(job, PREFS, score_threshold=0.35)
    assert candidate.drop_reason != "required_yoe"


def test_title_mismatch_excluded_from_shortlist():
    job = attach_yoe(_job(title="Ice Cream Delivery", job_id="junk"))
    candidate = evaluate_job(job, PREFS, score_threshold=0.0)
    assert candidate.drop_reason == "title_mismatch"
    assert title_fit(job.title, PREFS.keywords) < TITLE_FIT_MIN_FOR_TOP


def test_below_threshold_not_shortlisted():
    job = attach_yoe(_job(title="Product Designer", description="short"))
    candidate = evaluate_job(job, PREFS, score_threshold=0.9)
    assert candidate.drop_reason == "below_threshold"


def test_cap_keeps_rank_null_on_overflow():
    jobs = [
        evaluate_job(
            attach_yoe(_job(job_id=str(i), url=f"https://example.com/jobs/{i}")),
            PREFS,
            score_threshold=0.0,
        )
        for i in range(5)
    ]
    ranked = assign_shortlist(jobs, shortlist_cap=2)
    ranked_ids = {c.job_id for c in ranked if c.prefilter_rank is not None}
    assert len(ranked_ids) == 2
    overflow = [c for c in ranked if c.prefilter_rank is None]
    assert len(overflow) == 3
    assert all(c.drop_reason is None for c in overflow)
