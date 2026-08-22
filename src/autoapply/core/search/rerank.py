"""LLM rerank of the Gate B shortlist (docs/search-spec.md §6.6).

Separate prompt + schema from deliver form-fill decisions. Transport may reuse [llm].
On parse/timeout/rate-limit the caller falls back to Gate B order and leaves
llm_keep null — never wipe the run.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Protocol, Sequence

from pydantic import BaseModel, Field, ValidationError

from autoapply.core.bio.store import BioStore
from autoapply.core.config import LLMSettings
from autoapply.core.contracts import SearchCandidate
from autoapply.core.llm.cli_client import _iter_object_candidates
from autoapply.core.llm.transport import LLMTransportError, complete_prompt
from autoapply.core.search.prefs import SearchPrefs

log = logging.getLogger(__name__)

MAX_JD_CHARS = 3500
MAX_RESUME_EXCERPT_CHARS = 800
_RANKED_KEYS = frozenset({"ranked"})

_SYSTEM_PROMPT = """You rank a shortlist of job postings for one job seeker.

Decide keep vs drop for each job, then rank the ones you keep.

Rules:
- Only use the jobs in the input. Do not invent job_key values.
- job_key is "{platform}:{job_id}" and must match the input exactly.
- keep=true means this role is a plausible match for the seeker's keywords, YoE, and skills.
- keep=false means it is the wrong seniority, wrong function, or a junk/unrelated posting.
- rank is 1 for the best keep; omit rank (null) when keep=false.
- reason is one short sentence the human reviewer can scan.
- Cover every input job_key exactly once.

Reply with one JSON object only (a ```json fence is allowed). No other text.
"""


class SearchRerankError(Exception):
    """CLI/parse failure. Runner must fall back to Gate B order, not abort the run."""


class RerankItem(BaseModel):
    job_key: str
    keep: bool
    rank: int | None = None
    reason: str = ""


class RankedPayload(BaseModel):
    ranked: list[RerankItem] = Field(default_factory=list)


class SearchRerankClient(Protocol):
    def rerank(
        self,
        jobs: Sequence[SearchCandidate],
        *,
        prefs: SearchPrefs,
        bio_excerpt: dict[str, Any],
    ) -> list[RerankItem]:
        """Return keep/rank annotations. Raise SearchRerankError (or any Exception) to trigger fallback."""


def job_key_of(candidate: SearchCandidate) -> str:
    return f"{candidate.platform}:{candidate.job_id}"


def compact_bio_excerpt(
    bio: BioStore,
    prefs: SearchPrefs,
    resume_excerpt: str | None = None,
) -> dict[str, Any]:
    """Role + YoE prefs + skills/summary if present. Keep this small; it is sent every rerank call."""
    excerpt: dict[str, Any] = {
        "keywords": list(prefs.keywords),
        "locations": list(prefs.locations),
        "remote": prefs.remote,
        "yoe_prefer_min": prefs.yoe_prefer_min,
        "yoe_prefer_max": prefs.yoe_prefer_max,
        "skills": bio.read_path("skills") or bio.read_path("preferences.skills"),
        "summary": bio.read_path("summary") or bio.read_path("profile.summary"),
    }
    resume = (resume_excerpt or "").strip()
    if resume:
        excerpt["resume"] = resume[:MAX_RESUME_EXCERPT_CHARS]
    return excerpt


def shortlist_payload(jobs: Sequence[SearchCandidate], *, max_jd_chars: int = MAX_JD_CHARS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        description = job.description or ""
        if len(description) > max_jd_chars:
            description = description[:max_jd_chars]
        rows.append(
            {
                "job_key": job_key_of(job),
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "score": job.score,
                "description": description,
            }
        )
    return rows


def parse_rerank_json(text: str) -> list[RerankItem]:
    """Pull the {"ranked": [...]} object out of CLI stdout (fences / extra prose allowed)."""
    parsed: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for region in _iter_object_candidates(text):
        if region in seen:
            continue
        seen.add(region)
        try:
            obj = json.loads(region)
        except json.JSONDecodeError:
            continue
        parsed.append((region, obj))

    if not parsed:
        raise SearchRerankError("LLM rerank output had no parseable JSON object")

    for _region, obj in parsed:
        if isinstance(obj, dict) and _RANKED_KEYS.intersection(obj):
            try:
                return RankedPayload.model_validate(obj).ranked
            except ValidationError as exc:
                raise SearchRerankError(f"LLM rerank JSON failed schema: {exc}") from exc
    raise SearchRerankError("LLM rerank output had no object with a top-level 'ranked' key")


def apply_rerank(
    candidates: Sequence[SearchCandidate],
    items: Sequence[RerankItem],
) -> list[SearchCandidate]:
    """Copy LLM keep/rank/reason onto shortlist rows only. Unknown job_keys are ignored."""
    by_key: dict[str, RerankItem] = {}
    for item in items:
        by_key.setdefault(item.job_key, item)

    out: list[SearchCandidate] = []
    for candidate in candidates:
        if candidate.prefilter_rank is None:
            out.append(candidate)
            continue
        item = by_key.get(job_key_of(candidate))
        if item is None:
            out.append(candidate)
            continue
        reason = item.reason.strip() or None
        out.append(
            candidate.model_copy(
                update={
                    "llm_keep": item.keep,
                    "llm_rank": item.rank,
                    "llm_reason": reason,
                }
            )
        )
    return out


def review_order(shortlist: Sequence[SearchCandidate]) -> list[SearchCandidate]:
    """Keep-first when any llm_keep is set; otherwise Gate B prefilter_rank."""
    rows = list(shortlist)
    if not any(c.llm_keep is not None for c in rows):
        rows.sort(key=lambda c: c.prefilter_rank or 0)
        return rows

    def _key(c: SearchCandidate) -> tuple[int, int, int]:
        gate = c.prefilter_rank or 0
        llm_rank = c.llm_rank if c.llm_rank is not None else 10_000
        if c.llm_keep is True:
            return (0, llm_rank, gate)
        if c.llm_keep is False:
            return (1, llm_rank, gate)
        return (2, gate, 0)

    rows.sort(key=_key)
    return rows


def llm_kept_count(shortlist: Sequence[SearchCandidate]) -> int | None:
    """None = rerank did not land (fallback). 0 = model kept nothing."""
    annotated = [c for c in shortlist if c.llm_keep is not None]
    if not annotated:
        return None
    return sum(1 for c in annotated if c.llm_keep)


class CliSearchRerankClient:
    """Search ranking via [llm].transport (CLI or HTTP). Schema is {ranked: [...]}, not form-fill."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        timeout: int | None = None,
        model: str | None = None,
        transport: str | None = None,
        run_fn: Callable[[str], str] | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if model:
            updates["model"] = model
        if timeout is not None:
            updates["timeout"] = timeout
        if transport:
            updates["transport"] = transport
        self._settings = settings.model_copy(update=updates) if updates else settings
        self._run_fn = run_fn

    def rerank(
        self,
        jobs: Sequence[SearchCandidate],
        *,
        prefs: SearchPrefs,
        bio_excerpt: dict[str, Any],
    ) -> list[RerankItem]:
        if not jobs:
            return []
        prompt = _build_prompt(jobs, prefs=prefs, bio_excerpt=bio_excerpt)
        stdout = self._complete(prompt)
        return parse_rerank_json(stdout)

    def _complete(self, prompt: str) -> str:
        if self._run_fn is not None:
            try:
                return self._run_fn(prompt)
            except SearchRerankError:
                raise
            except Exception as exc:
                raise SearchRerankError(f"LLM rerank run_fn failed: {exc}") from exc
        try:
            return complete_prompt(prompt, self._settings)
        except LLMTransportError as exc:
            raise SearchRerankError(str(exc)) from exc


def _build_prompt(
    jobs: Sequence[SearchCandidate],
    *,
    prefs: SearchPrefs,
    bio_excerpt: dict[str, Any],
) -> str:
    schema_hint = json.dumps(RankedPayload.model_json_schema(), ensure_ascii=False)
    payload = {
        "seeker": bio_excerpt,
        "prefs": {
            "keywords": list(prefs.keywords),
            "locations": list(prefs.locations),
            "yoe_prefer_min": prefs.yoe_prefer_min,
            "yoe_prefer_max": prefs.yoe_prefer_max,
        },
        "jobs": shortlist_payload(jobs),
    }
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"## Output JSON Schema\n{schema_hint}\n\n"
        f"## Input\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        'Reply with {"ranked":[{"job_key":"...","keep":true,"rank":1,"reason":"..."}, ...]} only.'
    )
