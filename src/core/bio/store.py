"""core.bio.store —— BioStore 抽象 + YamlBioStore 最小实现。

用户已确认的 bio 依赖策略：core 只定义两个接口方法（按字段路径读 / 回写），
不锁定完整 bio schema——deliver 模块解耦，schema 演进不影响 deliver 代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BIO_PATH = _REPO_ROOT / "data" / "bio.yaml"

# 回写时若带了原始问题文本，存进这个保留键下（与实际 bio 数据分区），
# 不污染用户手编的正文字段——不算「锁 schema」，只是内部审计备注。
_FIELD_NOTES_KEY = "_field_notes"


class BioStore(ABC):
    """bio 依赖的最小接口：deliver 只认这两个方法，不关心底层怎么存。"""

    @abstractmethod
    def read_path(self, field_path: str) -> Any | None:
        """按点号分隔的字段路径读值，如 `preferences.visa_sponsorship_needed`；
        路径不存在返回 None。"""

    @abstractmethod
    def write_path(
        self, field_path: str, value: Any, question: str | None = None
    ) -> None:
        """按字段路径写值，中间层级不存在则创建；`question` 可选携带表单原始问题
        文本留档（对应 PRD 四 / `BioWriteback.question`）。"""


class YamlBioStore(BioStore):
    """基于单个 YAML 文件的 BioStore 实现（spec 决策九：bio 用人类可读可编辑的
    `data/bio.yaml` 单文件，用户手工维护的单一事实源）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_BIO_PATH

    def read_path(self, field_path: str) -> Any | None:
        data = self._load()
        node: Any = data
        for part in field_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def write_path(
        self, field_path: str, value: Any, question: str | None = None
    ) -> None:
        parts = field_path.split(".")
        # `_field_notes` 是内部审计备注的保留顶层键，不允许用户/LLM 的字段路径写入，
        # 否则备注与正文互相踩踏会损坏数据树。显式拒绝而非静默覆盖。
        if parts[0] == _FIELD_NOTES_KEY:
            raise ValueError(
                f"字段路径不能以保留键 {_FIELD_NOTES_KEY!r} 开头：{field_path!r}"
            )
        data = self._load()
        node = data
        for part in parts[:-1]:
            existing = node.get(part)
            if not isinstance(existing, dict):
                existing = {}
                node[part] = existing
            node = existing
        node[parts[-1]] = value

        if question is not None:
            notes = data.setdefault(_FIELD_NOTES_KEY, {})
            notes[field_path] = question

        self._save(data)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
