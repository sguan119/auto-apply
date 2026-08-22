"""autoapply.core.export_schemas —— 把 core.contracts 里的 pydantic 模型导出成 JSON Schema。

供文档与贡献者参考（spec 决策五：「契约本身可由 pydantic 自动导出 JSON Schema」）。
输出到仓库根 `docs/contracts/<ModelName>.json`，**这些生成文件本身要提交进仓库**，
不在 .gitignore 排除范围内。

用法：`python -m core.export_schemas`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from autoapply.core import contracts

# 只导出面向模块边界的数据契约模型，DeliveryStatus/FieldValueSource 这类枚举
# 已内嵌在引用它们的模型 schema 里，不必单独导出。
_EXPORTED_MODELS = [
    contracts.JobRef,
    contracts.SearchJob,
    contracts.SearchCandidate,
    contracts.SearchRunSummary,
    contracts.FilledField,
    contracts.DeliveryTask,
    contracts.DeliveryRecord,
    contracts.BioWriteback,
    contracts.Question,
    contracts.Answer,
    contracts.RunSummary,
]

# 本文件位于 src/autoapply/core/export_schemas.py，向上三级即仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = _REPO_ROOT / "docs" / "contracts"


def export_schemas(output_dir: Path | None = None) -> list[Path]:
    """把 `_EXPORTED_MODELS` 的 JSON Schema 逐个写入 `output_dir`，返回写入的文件路径列表。"""
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for model in _EXPORTED_MODELS:
        schema = model.model_json_schema()
        out_path = target_dir / f"{model.__name__}.json"
        out_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(out_path)
    return written


if __name__ == "__main__":
    # Windows 默认控制台编码（cp1252/gbk）打印不了仓库路径里的中文，
    # 用 errors="replace" 兜底，避免脚本本身跑成功却在打印时崩溃。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    paths = export_schemas()
    for p in paths:
        print(f"wrote {p}")
