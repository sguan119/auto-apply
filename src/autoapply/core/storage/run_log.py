"""autoapply.core.storage.run_log —— 按 run 切分的 JSONL 过程日志（spec 决策九 / PRD 八审计）。

逐行追加纯文本 JSON，记录步骤/LLM 决策/验证码求解/报错，供调试与审计；
不进 SQLite——过程日志量大且只顺序读，JSONL 追加写最简单也最抗损坏。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LOGS_DIR = _REPO_ROOT / "logs"


class RunLogger:
    """一个 run 对应一个 `logs/run-<run_id>.jsonl` 文件，`log()` 逐行追加一个事件。"""

    def __init__(self, run_id: str, logs_dir: str | Path | None = None) -> None:
        self.run_id = run_id
        self.logs_dir = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.logs_dir / f"run-{run_id}.jsonl"

    def log(self, event_type: str, **fields: object) -> None:
        """追加一行事件记录：`{"timestamp", "run_id", "event_type", **fields}`。

        `default=str` 兜底非 JSON 原生类型（如误传入 Path/datetime 字段），
        保证过程日志绝不会因为一次序列化失败而中断整个 run。
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            **fields,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str))
            f.write("\n")
