"""Search-owned SQLite helpers. Query search_* tables only — never `deliveries`.

Dedup against already-applied jobs goes through `repository.get_delivered_job_keys()`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autoapply.core.contracts import SearchCandidate, SearchRunSummary
from autoapply.core.storage import db


def clear_current_flag(db_path: str | Path | None = None) -> None:
    """Commit immediately so a later scoring failure cannot resurrect the previous shortlist."""
    with db.connect(db_path) as conn:
        conn.execute("UPDATE search_runs SET is_current = 0 WHERE is_current = 1")


def seen_keys(
    *,
    lookback_hours: int,
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> set[tuple[str, str]]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=lookback_hours)
    cutoff_iso = cutoff.isoformat()
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT platform, job_id FROM search_seen WHERE last_seen_at >= ?",
            (cutoff_iso,),
        ).fetchall()
    return {(row["platform"], row["job_id"]) for row in rows}


def record_run(
    *,
    run_id: str,
    keywords: list[str],
    summary: SearchRunSummary,
    candidates: list[SearchCandidate],
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> None:
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO search_runs
                (run_id, started_at, finished_at, is_current, keywords_json, summary_json)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                finished_at = excluded.finished_at,
                is_current = 1,
                keywords_json = excluded.keywords_json,
                summary_json = excluded.summary_json
            """,
            (
                run_id,
                stamp,
                stamp,
                json.dumps(keywords, ensure_ascii=False),
                summary.model_dump_json(),
            ),
        )
        conn.execute("DELETE FROM search_candidates WHERE run_id = ?", (run_id,))
        for candidate in candidates:
            conn.execute(
                """
                INSERT INTO search_candidates
                    (run_id, platform, job_id, job_json, score, drop_reason, prefilter_rank)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candidate.platform,
                    candidate.job_id,
                    candidate.model_dump_json(),
                    candidate.score,
                    candidate.drop_reason,
                    candidate.prefilter_rank,
                ),
            )
            conn.execute(
                """
                INSERT INTO search_seen (platform, job_id, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform, job_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (candidate.platform, candidate.job_id, stamp),
            )


def current_run_id(db_path: str | Path | None = None) -> str | None:
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT run_id FROM search_runs WHERE is_current = 1 ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return row["run_id"] if row else None


def load_candidates(
    run_id: str,
    db_path: str | Path | None = None,
) -> list[SearchCandidate]:
    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT job_json FROM search_candidates
            WHERE run_id = ?
            ORDER BY CASE WHEN prefilter_rank IS NULL THEN 1 ELSE 0 END, prefilter_rank ASC
            """,
            (run_id,),
        ).fetchall()
    return [SearchCandidate.model_validate_json(row["job_json"]) for row in rows]


def load_shortlist(
    run_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[SearchCandidate]:
    resolved = run_id or current_run_id(db_path)
    if resolved is None:
        return []
    return [c for c in load_candidates(resolved, db_path=db_path) if c.prefilter_rank is not None]


def mark_selected(
    *,
    run_id: str,
    keys: set[tuple[str, str]],
    db_path: str | Path | None = None,
) -> list[SearchCandidate]:
    """Replace the selected set on this run. Does not touch search_seen timestamps."""
    candidates = load_candidates(run_id, db_path=db_path)
    updated: list[SearchCandidate] = []
    with db.connect(db_path) as conn:
        for candidate in candidates:
            selected = (candidate.platform, candidate.job_id) in keys
            new = candidate.model_copy(update={"selected": selected})
            updated.append(new)
            conn.execute(
                """
                UPDATE search_candidates
                SET job_json = ?
                WHERE run_id = ? AND platform = ? AND job_id = ?
                """,
                (new.model_dump_json(), run_id, new.platform, new.job_id),
            )
        row = conn.execute(
            "SELECT summary_json FROM search_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None:
            summary = SearchRunSummary.model_validate_json(row["summary_json"])
            summary = summary.model_copy(update={"selected": len(keys)})
            conn.execute(
                "UPDATE search_runs SET summary_json = ? WHERE run_id = ?",
                (summary.model_dump_json(), run_id),
            )
    return updated
