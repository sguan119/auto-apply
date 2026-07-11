"""core.llm —— LLM 决策客户端（spec 决策四「大脑」/ 决策十「可插拔」）。

`client.py` 定义抽象与 DOM 层↔LLM 层的契约（PageContext/PageDecision）；
`cli_client.py` 是首个实现，走无头 CLI 子进程（用户已确认的范围决策）。
"""
