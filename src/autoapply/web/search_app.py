"""Local FastAPI app for trying search in a browser. Binds to localhost only."""

from __future__ import annotations

from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import load_settings
from autoapply.core.search.pick import PickError, pick_jobs
from autoapply.core.search.prefs import EmptySearchKeywords
from autoapply.core.search.resume_query import (
    CliResumeQueryClient,
    ResumeQueryError,
    plan_queries,
    write_plan,
)
from autoapply.core.search.runner import run_search

_HTML = Path(__file__).with_name("search.html")

app = FastAPI(title="AutoApply Search (local test)", docs_url=None, redoc_url=None)


class SearchRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    quick: bool = True
    llm_rerank: bool = False
    llm_transport: Literal["cli", "http"] | None = None
    include_seen: bool = False
    resume_excerpt: str | None = None


class ResumePlanRequest(BaseModel):
    resume_text: str = ""
    queries: list[str] = Field(default_factory=list)
    llm_transport: Literal["cli", "http"] | None = None


class PickRequest(BaseModel):
    job_keys: list[str] = Field(default_factory=list)
    run_id: str | None = None


def _split_terms(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        for part in str(raw).replace(";", ",").split(","):
            text = part.strip()
            if text:
                out.append(text)
    return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_HTML, media_type="text/html")


@app.post("/api/search")
def api_search(body: SearchRequest) -> dict:
    settings = load_settings()
    if body.quick:
        settings.search.results_wanted = 12
    settings.search.llm_rerank = body.llm_rerank
    if body.llm_rerank and body.llm_transport:
        settings.search.llm_transport = body.llm_transport
    if body.include_seen:
        settings.search.seen_lookback_hours = 0
    keywords = _split_terms(body.keywords) or None
    locations = _split_terms(body.locations) or None
    try:
        result = run_search(
            settings=settings,
            bio_store=YamlBioStore(),
            keywords=keywords,
            locations=locations,
            resume_excerpt=body.resume_excerpt,
        )
    except EmptySearchKeywords as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dropped = [c for c in result.candidates if c.prefilter_rank is None]
    return {
        "summary": result.summary.model_dump(mode="json"),
        "shortlist": [c.model_dump(mode="json") for c in result.shortlist],
        "dropped": [c.model_dump(mode="json") for c in dropped[:80]],
        "dropped_total": len(dropped),
        "output_dir": str(result.output_dir),
        "llm_error": result.llm_error,
    }


@app.post("/api/resume-plan")
def api_resume_plan(body: ResumePlanRequest) -> dict:
    settings = load_settings()
    if body.llm_transport:
        settings.search.llm_transport = body.llm_transport
    queries = _split_terms(body.queries) or None
    client = None
    if not queries:
        client = CliResumeQueryClient(
            settings.llm,
            timeout=settings.llm.timeout,
            model=settings.search.llm_model,
            transport=settings.search.llm_transport,
        )
    try:
        plan = plan_queries(
            body.resume_text,
            client=client,
            settings=settings.llm,
            queries=queries,
        )
        write_plan(plan)
    except ResumeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plan.model_dump(mode="json")


@app.post("/api/pick")
def api_pick(body: PickRequest) -> dict:
    try:
        result = pick_jobs(body.job_keys, run_id=body.run_id)
    except PickError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "run_id": result.run_id,
        "path": str(result.path),
        "selected": [ref.model_dump(mode="json") for ref in result.job_refs],
    }
