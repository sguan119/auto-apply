"""autoapply.core.llm —— LLM 决策客户端（spec 决策四「大脑」/ 决策十「可插拔」）。

`client.py` 定义抽象与 DOM 层↔LLM 层的契约（PageContext/PageDecision）；
`transport.py` 负责怎么把 prompt 送给模型（本地 CLI 或 OpenAI 兼容 HTTP）；
`cli_client.py` 把投递的 PageDecision 接到 transport 上。
"""
