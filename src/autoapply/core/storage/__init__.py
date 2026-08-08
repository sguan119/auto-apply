"""autoapply.core.storage —— SQLite 存储层（spec 决策九）。

`db.py` 管理连接与建表；`repository.py` 是唯一对外查询/写入接口——跨模块
（如 search 模块的去重回喂）只走这里，不直读 SQL（决策八 / CLAUDE.md 模块解耦）。
`run_log.py` 是独立的 JSONL 过程日志，不进 SQLite。
"""
