"""core.storage.repository —— 存储层对外唯一接口（spec 决策八 / 决策九）。

跨模块（尤其是 search 模块的去重回喂）只经这里的函数，不直读 `db.py` 的 SQL——
守住 CLAUDE.md「模块解耦」与 spec 决策八「走接口不直读对方存储」的约束。

持久化规则（阶段 1 review 定的坑）：pydantic 模型一律用 `model_dump_json()` /
`model_dump(mode="json")` 序列化进 SQLite TEXT 列，绝不用裸 `model_dump()`
（`HttpUrl`/`Path` 不是 JSON 原生类型，裸 dump 会在 `json.dumps` 时炸)。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from core.contracts import DeliveryRecord, DeliveryStatus, JobRef, Question, RunSummary
from core.storage import db


class Credential(BaseModel):
    """账号凭据（PRD 六：明文存储；按 platform + portal 区分，同平台不同雇主门户
    各自独立账号——见 PRD 二 Workday 每个雇主门户独立账号）。"""

    platform: str
    portal: str  # 门户/雇主标识；无子门户概念的平台可用平台名本身占位
    username: str | None = None
    password: str | None = None
    email: str | None = None
    created_at: datetime


class PendingQuestion(BaseModel):
    """挂起问题的一条持久化记录（附自增 id，供 `record_answer` 定位）。"""

    id: int
    job: JobRef
    question: Question
    answer: str | None = None
    answered: bool = False


# ---------------------------------------------------------------------------
# 投递记录（决策八去重 + 决策九落库）
# ---------------------------------------------------------------------------


def get_delivered_job_keys(db_path: str | Path | None = None) -> set[tuple[str, str]]:
    """回喂搜索模块去重用的「已投过」职位键集合（决策八「已投过的自动跳过」）。

    语义选择：返回 `deliveries` 表里**当前记录到的所有**键，不局限于 SUCCEEDED。
    理由——
    - SUCCEEDED 永不再投，自然要跳过；
    - FAILED 默认不跨 run 自动重试（决策八），如果搜索模块继续把它喂回来，
      下个 run 又会把它排进 PENDING 重新走一遍，等价于绕开了「不自动重试」；
      FAILED 的重投只走 CLI `deliver retry` 的显式手动路径，不该由搜索模块的
      去重结果间接触发。
    - SUSPENDED 有专门的自动恢复路径（见 `resuspendable_jobs()`），由 runner
      在 run 开头主动拉取、优先于新职位重投，不需要（也不应该）让搜索模块把
      它当「新职位」再交一次——那样会产生重复的 DeliveryTask。
    结论：`(platform, job_id)` 只要出现在 `deliveries` 表里，就代表「deliver
    已经处理过」，一律回喂给搜索模块跳过。
    """
    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT platform, job_id FROM deliveries").fetchall()
    return {(row["platform"], row["job_id"]) for row in rows}


def record_delivery(record: DeliveryRecord, db_path: str | Path | None = None) -> None:
    """按 (platform, job_id) UPSERT 一条投递记录——同一职位键只保留最新状态。"""
    platform, job_id = record.job.key
    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO deliveries
                (platform, job_id, status, run_id, failure_reason,
                 filled_fields, job_json, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (platform, job_id) DO UPDATE SET
                status = excluded.status,
                run_id = excluded.run_id,
                failure_reason = excluded.failure_reason,
                filled_fields = excluded.filled_fields,
                job_json = excluded.job_json,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at
            """,
            (
                platform,
                job_id,
                record.status.value,
                record.run_id,
                record.failure_reason,
                json.dumps(
                    [f.model_dump(mode="json") for f in record.filled_fields],
                    ensure_ascii=False,
                ),
                record.job.model_dump_json(),
                record.started_at.isoformat(),
                record.finished_at.isoformat(),
            ),
        )


def get_delivery(
    platform: str, job_id: str, db_path: str | Path | None = None
) -> DeliveryRecord | None:
    """按职位键查最新一条投递记录，不存在返回 None。"""
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM deliveries WHERE platform = ? AND job_id = ?",
            (platform, job_id),
        ).fetchone()
    if row is None:
        return None
    return _row_to_delivery_record(row)


def _row_to_delivery_record(row) -> DeliveryRecord:
    job = JobRef.model_validate_json(row["job_json"])
    filled_fields_raw = json.loads(row["filled_fields"])
    return DeliveryRecord(
        job=job,
        status=DeliveryStatus(row["status"]),
        filled_fields=filled_fields_raw,
        failure_reason=row["failure_reason"],
        run_id=row["run_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]),
    )


# ---------------------------------------------------------------------------
# 凭据（PRD 六：明文存储，按 platform + portal 区分门户/雇主账号）
# ---------------------------------------------------------------------------


def upsert_credential(
    platform: str,
    portal: str,
    *,
    username: str | None = None,
    password: str | None = None,
    email: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO credentials (platform, portal, username, password, email, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (platform, portal) DO UPDATE SET
                username = excluded.username,
                password = excluded.password,
                email = excluded.email
            """,
            (
                platform,
                portal,
                username,
                password,
                email,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_credential(
    platform: str, portal: str, db_path: str | Path | None = None
) -> Credential | None:
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM credentials WHERE platform = ? AND portal = ?",
            (platform, portal),
        ).fetchone()
    if row is None:
        return None
    return Credential(
        platform=row["platform"],
        portal=row["portal"],
        username=row["username"],
        password=row["password"],
        email=row["email"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# 挂起问题（决策六 SUSPENDED / 决策七问询 / 决策八优先重投）
# ---------------------------------------------------------------------------


def save_suspended_questions(
    job: JobRef, questions: list[Question], db_path: str | Path | None = None
) -> None:
    """一个职位 WAITING_USER 超时挂起时，把该页未答问题整批入库。"""
    platform, job_id = job.key
    job_json = job.model_dump_json()
    now = datetime.now(timezone.utc).isoformat()
    with db.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO suspended_questions
                (platform, job_id, job_json, field_path, question, page, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (platform, job_id, job_json, q.field_path, q.question, q.page, now)
                for q in questions
            ],
        )


def pending_unanswered_questions(
    db_path: str | Path | None = None,
) -> list[PendingQuestion]:
    """所有尚未回答的挂起问题（run 汇总用于集中展示，决策七「无人值守闭环」）。"""
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM suspended_questions WHERE answered = 0"
        ).fetchall()
    return [_row_to_pending_question(row) for row in rows]


def record_answer(
    question_id: int, answer: str, db_path: str | Path | None = None
) -> None:
    """用户对某条挂起问题给出回答（回写 bio 是调用方——问询通道/CLI——的职责，
    这里只负责把答案持久化到该问题记录上）。"""
    with db.connect(db_path) as conn:
        conn.execute(
            "UPDATE suspended_questions SET answer = ?, answered = 1 WHERE id = ?",
            (answer, question_id),
        )


def resuspendable_jobs(db_path: str | Path | None = None) -> list[JobRef]:
    """问题已全部补答、可以优先重投的挂起职位（决策八：下次 run 开头优先于新职位）。

    判定：一个 (platform, job_id) 下所有 suspended_questions 行都 answered=1。
    """
    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT platform, job_id, job_json
            FROM suspended_questions
            GROUP BY platform, job_id
            HAVING MIN(answered) = 1
            """
        ).fetchall()
    return [JobRef.model_validate_json(row["job_json"]) for row in rows]


def clear_suspended_questions(
    platform: str, job_id: str, db_path: str | Path | None = None
) -> None:
    """职位重投后清掉它的挂起问题记录（runner 在消化 `resuspendable_jobs()` 后调用，
    避免同一批问题被反复判定为「已可重投」）。"""
    with db.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM suspended_questions WHERE platform = ? AND job_id = ?",
            (platform, job_id),
        )


def _row_to_pending_question(row) -> PendingQuestion:
    job = JobRef.model_validate_json(row["job_json"])
    question = Question(
        job=job,
        field_path=row["field_path"],
        question=row["question"],
        page=row["page"],
    )
    return PendingQuestion(
        id=row["id"],
        job=job,
        question=question,
        answer=row["answer"],
        answered=bool(row["answered"]),
    )


# ---------------------------------------------------------------------------
# run 记录（决策八 run 汇总 / 阶段 8 runner 落库）
# ---------------------------------------------------------------------------


def record_run_start(run_id: str, db_path: str | Path | None = None) -> None:
    """一次 run 开始时插入一条 `status="running"` 的占位记录。

    `total`/`succeeded` 此时还不知道，留表定义的默认值 0；`finished_at`/
    `summary_json` 留 NULL，run 结束时由 `record_run_summary()` 补上。
    """
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, ?)",
            (run_id, datetime.now(timezone.utc).isoformat(), "running"),
        )


def record_run_summary(
    run_id: str, summary: RunSummary, db_path: str | Path | None = None
) -> None:
    """run 结束时把 `RunSummary` 落进对应的 `runs` 行，`status` 转 `"completed"`。

    `run_id` 必须是先前 `record_run_start()` 插入过的那一行——本函数只 UPDATE，
    不 INSERT（一次 run 的生命周期是「先 start 后 summary」，不支持跳过 start
    直接落 summary）。
    """
    with db.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE runs SET
                finished_at = ?,
                status = ?,
                total = ?,
                succeeded = ?,
                summary_json = ?
            WHERE run_id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                "completed",
                summary.total,
                summary.succeeded,
                summary.model_dump_json(),
                run_id,
            ),
        )


def get_run_summary(run_id: str, db_path: str | Path | None = None) -> RunSummary | None:
    """按 `run_id` 取回落库的 `RunSummary`；run 还没结束（`summary_json` 为 NULL）
    或 `run_id` 不存在都返回 `None`。"""
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT summary_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None or row["summary_json"] is None:
        return None
    return RunSummary.model_validate_json(row["summary_json"])


# ---------------------------------------------------------------------------
# Easy Apply 滚动 24h 计数（决策八；LinkedIn 专属，Workday MVP 暂不接线）
# ---------------------------------------------------------------------------


def increment_easy_apply(db_path: str | Path | None = None) -> None:
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO easy_apply_count (created_at) VALUES (?)",
            (datetime.now(timezone.utc).isoformat(),),
        )


def easy_apply_count_last_24h(db_path: str | Path | None = None) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM easy_apply_count WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
    return row["n"]
