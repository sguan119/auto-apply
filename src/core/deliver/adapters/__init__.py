"""core.deliver.adapters —— 平台适配层（spec「待续」：适配层最小接口，通用 LLM+DOM 引擎为主）。

`base.py` 定义最小 `PlatformAdapter` 接口 + 一个「谁 import 谁注册」的轻量注册表
（`register_adapter` 装饰器 + `select_adapter(url)` 查找）。import 本包会顺带
import 已实现的平台模块（目前只有 `workday`），触发它们的 `@register_adapter`
自注册——调用方只需要 `from core.deliver.adapters.base import select_adapter`，
不需要知道/显式 import 具体是哪个平台模块（新增平台只需要在这里加一行 import）。
"""

from __future__ import annotations

from core.deliver.adapters import workday as _workday  # noqa: F401  触发 WorkdayAdapter 自注册
