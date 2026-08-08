"""autoapply.core.deliver.selector_cache —— Stagehand 式选择器缓存（决策四降 token 补丁）。

缓存键是页面的**结构指纹**：按 `element_id` 排序后取每个元素的
`tag`/`name`/`label`/`type`/`options` 签名做哈希——**不含 `value`**，保证
同一 ATS 模板换个职位/换个候选人再来一次仍命中同一指纹（Workday 同一表单
模板大量复用，指纹层面结构完全一致）。指纹不匹配（页面改版、不同表单、
不同分页）即视为未命中，重新推理——指纹本身就是失效判据，不需要 TTL 或
显式失效 API。

**缓存的是什么，不是什么**：真正省 token 的地方是跳过 `llm_client.decide()`
重新推理（缓存 `PageDecision`），而不是「选择器映射」本身——`selector_map`
的值（`[data-deliver-id="N"]`）依赖 `dom.collect_page()` 在**当前这个 Page
实例**上现场写回 DOM 属性，天然没法跨 Page 复用，每次都得重新走一遍（但
这一步是本地 JS 求值，不吃 token，重算成本可忽略）。只要两次采集的页面结构
一致，编号分配顺序也一致，缓存的 `PageDecision`（按 `element_id` 引用）可以
直接套到新页面刚生成的 `selector_map` 上。

**跨职位安全边界（重要）**：因为缓存值里含具体 `value`、键又只看结构，命中
会把这份决策连 value 原样套到另一个（很可能属于**另一个职位**的）同结构页面
上。只有当填值与「投哪个职位」无关时才安全——`BIO`/`USER_ANSWER` 是候选人级
稳定值可缓存，`LLM_GENERATED`（求职信、开放式问答等逐职位定制文案）会串味，
**不能**缓存。这道闸由 `engine._is_cross_job_cacheable()` 在 `put` 前把关，本
模块只做无脑存取，不重复判断。

MVP 用进程内 dict；持久化到 `data/`（跨进程/跨 run 复用）是明确的扩展点，
接口（`get`/`put`）保持不变，届时把 `_store` 换成落盘实现即可。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from autoapply.core.llm.client import PageDecision, PageElement


def compute_fingerprint(elements: list[PageElement]) -> str:
    """结构指纹：`tag`/`name`/`label`/`type`/`options` 签名的 sha256，不含 value。"""
    signature = [
        {
            "tag": element.tag,
            "name": element.name,
            "label": element.label,
            "type": element.type,
            "options": element.options,
        }
        for element in sorted(elements, key=lambda e: e.element_id)
    ]
    blob = json.dumps(signature, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    """一次命中缓存的内容：目前只存 `PageDecision`（跳过 LLM 重新推理用）。"""

    decision: PageDecision


class SelectorCache:
    """进程内 `fingerprint -> CacheEntry` 缓存（MVP；持久化是扩展点，见模块文档）。"""

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}

    def get(self, fingerprint: str) -> CacheEntry | None:
        return self._store.get(fingerprint)

    def put(self, fingerprint: str, entry: CacheEntry) -> None:
        self._store[fingerprint] = entry
