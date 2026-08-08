"""autoapply.core.bio —— bio 依赖的最小接口（用户确认的范围决策：只锁两个接口，不锁 schema）。

deliver 只依赖「按字段路径读 / 回写」两个操作，不依赖 bio 内部结构；完整 bio
schema 属 bio 模块自己的事，另立文档（spec「待续」/ 计划阶段 2 说明）。
"""
