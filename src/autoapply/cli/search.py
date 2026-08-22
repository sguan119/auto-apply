"""autoapply.cli.search — thin typer entry for the search module (docs/search-spec.md §3.3)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import load_settings
from autoapply.core.contracts import SearchCandidate
from autoapply.core.search.pick import PickError, pick_jobs, resolve_pick_keys
from autoapply.core.search.prefs import EmptySearchKeywords
from autoapply.core.search.rerank import review_order
from autoapply.core.search.resume_query import (
    CliResumeQueryClient,
    ResumeQueryError,
    ResumeQueryPlan,
    load_resume_text,
    plan_queries,
    write_plan,
)
from autoapply.core.search.runner import SearchRunResult, run_search
from autoapply.core.search import store as search_store

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

app = typer.Typer(help="Search job boards, filter a shortlist for review. Does not apply.")
console = Console()


@app.callback()
def main() -> None:
    """search command group."""


@app.command("run")
def run_cmd(
    keyword: list[str] = typer.Option(
        [],
        "--keyword",
        "-k",
        help="Search keyword. Repeatable. Overrides bio preferences.target_role_keywords when set.",
    ),
    location: list[str] = typer.Option(
        [],
        "--location",
        "-l",
        help="Location. Repeatable. Overrides bio preferences.locations when set.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Parent directory for this run's snapshot (default: data/search/runs/<run_id>/).",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip LLM rerank for this run (Gate B order only).",
    ),
) -> None:
    """Fetch, dedupe, score, optional LLM rerank, and print the shortlist. Does not auto-apply."""
    settings = load_settings()
    if no_llm:
        settings.search.llm_rerank = False
    try:
        result = run_search(
            settings=settings,
            bio_store=YamlBioStore(),
            keywords=keyword or None,
            locations=location or None,
            output_root=out,
        )
    except EmptySearchKeywords as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    _print_run(result)
    if result.summary.failed_reason:
        raise typer.Exit(code=1)


@app.command("from-resume")
def from_resume_cmd(
    resume: Path = typer.Argument(
        ...,
        help="Plain-text resume (.txt/.md). Use - to read stdin. PDF is refused.",
    ),
    query: list[str] = typer.Option(
        [],
        "--query",
        "-q",
        help="Skip the planner; use these board queries. Repeatable.",
    ),
    location: list[str] = typer.Option(
        [],
        "--location",
        "-l",
        help="Location. Repeatable. Overrides bio preferences.locations when set.",
    ),
    run: bool = typer.Option(
        False,
        "--run",
        help="After planning, fetch with the proposed queries. Does not apply.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip shortlist LLM rerank (only used with --run).",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Parent directory for this run's snapshot (default: data/search/runs/<run_id>/).",
    ),
    plan_out: Path | None = typer.Option(
        None,
        "--plan-out",
        help="Write the query plan JSON here (default: data/search/resume_plan.json).",
    ),
) -> None:
    """Propose board queries from a résumé. Fetch only with --run. Does not write bio."""
    settings = load_settings()
    try:
        if str(resume) == "-":
            text = sys.stdin.read()
        else:
            text = load_resume_text(resume)
        client = None
        if not query:
            client = CliResumeQueryClient(
                settings.llm,
                timeout=settings.llm.timeout,
                model=settings.search.llm_model,
                transport=settings.search.llm_transport,
            )
        plan = plan_queries(
            text,
            client=client,
            settings=settings.llm,
            queries=query or None,
        )
        plan_path = write_plan(plan, plan_out)
    except ResumeQueryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    _print_plan(plan, path=plan_path)
    if not run:
        return

    if no_llm:
        settings.search.llm_rerank = False
    try:
        result = run_search(
            settings=settings,
            bio_store=YamlBioStore(),
            keywords=plan.queries,
            locations=location or None,
            output_root=out,
            resume_excerpt=plan.resume_summary,
        )
    except EmptySearchKeywords as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    _print_run(result)
    if result.summary.failed_reason:
        raise typer.Exit(code=1)


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8765, "--port", help="Local port. Bound to 127.0.0.1 only."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the page in your browser."),
) -> None:
    """Start a local test page for search. Does not apply to jobs."""
    try:
        import uvicorn
        from autoapply.web.search_app import app as web_app
    except ImportError as exc:
        typer.echo(
            'Install the web extra first:  pip install -e ".[web]"',
            err=True,
        )
        raise typer.Exit(code=1) from exc

    import webbrowser

    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"Search test UI → {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(web_app, host="127.0.0.1", port=port, log_level="info")


@app.command("list")
def list_cmd() -> None:
    """Reprint the current shortlist from the last search run."""
    run_id = search_store.current_run_id()
    shortlist = review_order(search_store.load_shortlist(run_id))
    if not shortlist:
        typer.echo("No current shortlist. Run `search run` first.")
        return
    _print_shortlist(shortlist, title=f"Shortlist run_id={run_id}")


@app.command("pick")
def pick_cmd(
    job_id: list[str] = typer.Option(
        [],
        "--id",
        help="Job to pick, as platform:job_id. Repeatable.",
    ),
    ids: str | None = typer.Option(
        None,
        "--ids",
        help="Comma-separated platform:job_id list.",
    ),
    kept: bool = typer.Option(
        False,
        "--kept",
        help="Pick every job the LLM marked keep=true.",
    ),
    entire_shortlist: bool = typer.Option(
        False,
        "--shortlist",
        help="Pick the entire current shortlist.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write JobRef[] JSON here (default: data/search/selected.json).",
    ),
) -> None:
    """Write selected jobs to selected.json as JobRef[]. Does not apply."""
    extra = [part.strip() for part in (ids or "").split(",") if part.strip()]
    try:
        run_id = search_store.current_run_id()
        shortlist = search_store.load_shortlist(run_id)
        keys = resolve_pick_keys(
            shortlist,
            ids=[*job_id, *extra],
            kept=kept,
            entire_shortlist=entire_shortlist,
        )
        result = pick_jobs(keys, run_id=run_id, output_path=out)
    except PickError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    console.print(
        f"picked={len(result.job_refs)}  run_id={result.run_id}  wrote {result.path}"
    )
    for ref in result.job_refs:
        console.print(f"  {ref.platform}:{ref.job_id}  {ref.title}  {ref.company}")


def _print_plan(plan: ResumeQueryPlan, *, path: Path | None) -> None:
    console.print("Proposed board queries (edit with --query, then --run to fetch):")
    for i, term in enumerate(plan.queries, start=1):
        console.print(f"  {i}. {term}")
    if plan.clusters:
        console.print("clusters: " + " | ".join(plan.clusters))
    if plan.yoe_guess is not None:
        console.print(
            f"yoe_guess: {plan.yoe_guess.min}–{plan.yoe_guess.max}  "
            "(advisory; bio YoE prefs still used)"
        )
    if plan.notes:
        console.print(f"notes: {plan.notes}")
    if path is not None:
        console.print(f"Wrote {path}")


def _print_run(result: SearchRunResult) -> None:
    summary = result.summary
    console.print(
        f"run_id={summary.run_id}  fetched={summary.fetched}  "
        f"after_dedupe={summary.after_dedupe}  gate_a_dropped={summary.dropped_gate_a}  "
        f"shortlisted={summary.shortlisted}  llm_kept={summary.llm_kept}"
    )
    if result.shortlist:
        _print_shortlist(result.shortlist, title="Shortlist")
    elif summary.failed_reason:
        typer.echo(f"No jobs fetched ({summary.failed_reason}).", err=True)
    else:
        typer.echo("No jobs made the shortlist.")
    console.print(f"Wrote {result.output_dir / 'candidates.json'}")


def _print_shortlist(shortlist: list[SearchCandidate], *, title: str) -> None:
    table = Table(title=title)
    table.add_column("rank")
    table.add_column("keep")
    table.add_column("score")
    table.add_column("title")
    table.add_column("company")
    table.add_column("location")
    table.add_column("platform")
    table.add_column("reason")
    for job in shortlist:
        keep = "yes" if job.llm_keep is True else "no" if job.llm_keep is False else ""
        rank = job.llm_rank if job.llm_rank is not None else job.prefilter_rank
        table.add_row(
            str(rank or ""),
            keep,
            f"{job.score:.2f}",
            job.title,
            job.company,
            job.location or "",
            job.platform,
            job.llm_reason or "",
        )
    console.print(table)


if __name__ == "__main__":
    app()
