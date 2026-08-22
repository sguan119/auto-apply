"""Resume → board-query planner (docs/search-resume-query.md).

Experimental search entry. Does not write bio, does not rank jobs, does not fetch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from pydantic import BaseModel, Field, ValidationError

from autoapply.core.config import LLMSettings
from autoapply.core.llm.cli_client import _iter_object_candidates
from autoapply.core.llm.transport import LLMTransportError, complete_prompt

log = logging.getLogger(__name__)

MAX_RESUME_CHARS = 12_000
MAX_SUMMARY_CHARS = 800
MAX_QUERIES = 5
MAX_QUERY_CHARS = 40
DEFAULT_PLAN_PATH = Path(__file__).resolve().parents[4] / "data" / "search" / "resume_plan.json"

_PLAN_KEYS = frozenset({"queries"})
_SKILL_QUERY_BLOCKLIST = frozenset(
    {
        "figma",
        "sketch",
        "python",
        "unreal",
        "unity",
        "photoshop",
        "illustrator",
        "jira",
        "notion",
        "excel",
        "sql",
        "javascript",
        "typescript",
        "react",
        "blender",
    }
)

_SYSTEM_PROMPT = """You turn a résumé into a small set of job-board search queries.

Output terms a scraper can type into LinkedIn or Indeed — not LinkedIn-style job titles.

Rules:
- Emit 3 to 5 queries when the résumé supports it. Fewer is allowed if only one role cluster exists.
- Each query is short and loose: 2–4 words, lowercase.
- Do not include seniority (Senior, Staff, Lead, Junior), company names, or locations.
- Cover distinct role clusters. Do not emit three near-synonyms as the whole set
  (e.g. product designer + UX designer + UI designer) when another track is on the résumé.
- Do not use tool or skill names as queries (Figma, Python, Unreal, Unity, …).
- clusters names the tracks you covered.
- yoe_guess is {min, max} years of relevant experience, or null if unclear. Advisory only.
- resume_summary is at most three sentences: function, domain, YoE, notable skills.
- notes is one short sentence for the human reviewer.

Reply with one JSON object only (a ```json fence is allowed). No other text.
"""


class ResumeQueryError(Exception):
    """Extract/plan failure. Caller must not fetch."""


class YoeGuess(BaseModel):
    min: int | None = None
    max: int | None = None


class ResumeQueryPlan(BaseModel):
    queries: list[str]
    clusters: list[str] = Field(default_factory=list)
    yoe_guess: YoeGuess | None = None
    resume_summary: str = ""
    notes: str = ""


class ResumeQueryClient(Protocol):
    def plan(self, resume_text: str) -> ResumeQueryPlan:
        """Return a query plan. Raise ResumeQueryError (or any Exception) to abort fetch."""


def load_resume_text(source: str | Path, *, max_chars: int = MAX_RESUME_CHARS) -> str:
    """Read plain text from a path or a raw string. PDF is refused."""
    if isinstance(source, Path) or _looks_like_path(source):
        path = Path(source)
        if path.suffix.lower() == ".pdf":
            raise ResumeQueryError(
                "PDF is out of this experiment; paste text or use a .txt/.md file"
            )
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ResumeQueryError(f"could not read resume file: {exc}") from exc
        return normalize_resume_text(raw, max_chars=max_chars)
    return normalize_resume_text(str(source), max_chars=max_chars)


def _looks_like_path(source: str | Path) -> bool:
    if isinstance(source, Path):
        return True
    text = str(source)
    if "\n" in text or len(text) > 240:
        return False
    path = Path(text)
    return path.suffix.lower() in {".txt", ".md", ".markdown", ".text", ".pdf"} or path.exists()


def normalize_resume_text(text: str, *, max_chars: int = MAX_RESUME_CHARS) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        raise ResumeQueryError("resume text is empty")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


def normalize_queries(raw: Sequence[str], *, max_queries: int = MAX_QUERIES) -> list[str]:
    """Lowercase, collapse whitespace, drop skills/dups/overlong, cap length."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        text = " ".join(str(item).split()).strip().lower()
        if not text or len(text) > MAX_QUERY_CHARS:
            continue
        if text in _SKILL_QUERY_BLOCKLIST:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_queries:
            break
    return out


def parse_plan_json(text: str) -> ResumeQueryPlan:
    """Pull the {queries:[...]} object out of model stdout (fences / extra prose allowed)."""
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
        raise ResumeQueryError("resume-query output had no parseable JSON object")

    for _region, obj in parsed:
        if isinstance(obj, dict) and _PLAN_KEYS.intersection(obj):
            try:
                plan = ResumeQueryPlan.model_validate(obj)
            except ValidationError as exc:
                raise ResumeQueryError(f"resume-query JSON failed schema: {exc}") from exc
            return plan
    raise ResumeQueryError("resume-query output had no object with a top-level 'queries' key")


def write_plan(plan: ResumeQueryPlan, path: Path | None = None) -> Path:
    dest = path or DEFAULT_PLAN_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return dest


def plan_queries(
    resume_text: str,
    *,
    client: ResumeQueryClient | None = None,
    settings: LLMSettings | None = None,
    queries: Sequence[str] | None = None,
) -> ResumeQueryPlan:
    """Build a ResumeQueryPlan. Explicit queries skip the LLM. Never writes bio."""
    text = normalize_resume_text(resume_text)
    if queries:
        normalized = normalize_queries(queries)
        if not normalized:
            raise ResumeQueryError("no usable board queries after normalizing --query values")
        plan = ResumeQueryPlan(
            queries=normalized,
            resume_summary=_truncate(text, MAX_SUMMARY_CHARS),
            notes="queries supplied by the user; planner skipped",
        )
        return plan

    planner = client or CliResumeQueryClient(settings or LLMSettings())
    plan = planner.plan(text)
    normalized = normalize_queries(plan.queries)
    if not normalized:
        raise ResumeQueryError("planner returned no usable board queries")
    summary = (plan.resume_summary or "").strip() or _truncate(text, MAX_SUMMARY_CHARS)
    return plan.model_copy(update={"queries": normalized, "resume_summary": summary[:MAX_SUMMARY_CHARS]})


def _truncate(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


class CliResumeQueryClient:
    """Query planner via [llm].transport. Schema is {queries:[...]}, not ranked or form-fill."""

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

    def plan(self, resume_text: str) -> ResumeQueryPlan:
        prompt = _build_prompt(resume_text)
        stdout = self._complete(prompt)
        return parse_plan_json(stdout)

    def _complete(self, prompt: str) -> str:
        if self._run_fn is not None:
            try:
                return self._run_fn(prompt)
            except ResumeQueryError:
                raise
            except Exception as exc:
                raise ResumeQueryError(f"resume-query run_fn failed: {exc}") from exc
        try:
            return complete_prompt(prompt, self._settings)
        except LLMTransportError as exc:
            raise ResumeQueryError(str(exc)) from exc


def _build_prompt(resume_text: str) -> str:
    schema_hint = json.dumps(ResumeQueryPlan.model_json_schema(), ensure_ascii=False)
    payload = {"resume": resume_text}
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"## Output JSON Schema\n{schema_hint}\n\n"
        f"## Input\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        'Reply with {"queries":["..."],"clusters":["..."],"yoe_guess":{"min":0,"max":3},'
        '"resume_summary":"...","notes":"..."} only.'
    )
