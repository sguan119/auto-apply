"""autoapply.core.storage.db —— SQLite 连接管理 + 建表（spec 决策九）。

单库 `data/app.db`，承载投递记录/凭据/挂起问题/run 记录/Easy Apply 计数。
`data/` 目录被 `.gitignore` 排除（决策九硬约束），本模块负责懒创建它。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# 仓库根目录约定：本文件位于 src/autoapply/core/storage/db.py，向上四级即仓库根
# （与 core/config.py 的 _REPO_ROOT 约定一致）。
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT NOT NULL,
    failure_reason TEXT,
    filled_fields TEXT NOT NULL DEFAULT '[]',
    job_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    UNIQUE (platform, job_id)
);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    portal TEXT NOT NULL,
    username TEXT,
    password TEXT,
    email TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (platform, portal)
);

CREATE TABLE IF NOT EXISTS suspended_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_id TEXT NOT NULL,
    job_json TEXT NOT NULL,
    field_path TEXT,
    question TEXT NOT NULL,
    page TEXT,
    answer TEXT,
    answered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suspended_questions_job
    ON suspended_questions (platform, job_id);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    total INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS easy_apply_count (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_easy_apply_count_created_at
    ON easy_apply_count (created_at);
"""


def _resolve_path(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """打开一个到 `db_path`（缺省 `data/app.db`）的连接，懒建目录 + 建表。

    调用方负责 commit/close（一般用下面的 `connect()` 上下文管理器代替直接调用）。
    """
    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL 为 future 多 worker 并发写预留（spec 决策九）；单 worker MVP 下也无害。
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """连接上下文管理器：成功自动 commit，异常自动 rollback，退出自动 close。"""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
