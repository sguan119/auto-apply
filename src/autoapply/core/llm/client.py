"""autoapply.core.llm.client —— LLMClient 抽象 + 决策 schema（spec 决策四大脑 / 决策十可插拔）。

这里同时定义了**两条契约**：

1. **DOM 层 → LLM 层**：`PageContext` / `PageElement`。阶段 5 的 `dom.py` 还没
   落地，这里先给出一个最小可用形状（编号元素 + 语义信息 + bio 摘录 + 职位
   上下文），让阶段 4 能独立开发测试；阶段 5 产出的精简 DOM 必须能装进这个
   形状，字段可以随需要增补，但 `element_id` 编号语义（LLM 只认数字，不碰
   真实选择器）不能变——选择器映射是 `selector_cache.py` 的职责，不在这层。
2. **LLM 层 → engine 层**：`ElementDecision` / `PageDecision`，`LLMClient.decide()`
   的唯一返回类型，阶段 5 的 `engine.py` 消费。

`needs_user` 表示法见 `ElementDecision` 文档字符串。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from autoapply.core.contracts import FieldValueSource, JobRef


class PageElement(BaseModel):
    """DOM 精简+编号后的单个可交互元素（阶段 5 `dom.py` 产出）。

    `element_id` 是页面内稳定的编号标识，LLM 决策只引用这个数字；
    编号↔真实选择器的映射由 `selector_cache.py` 维护，不在这个契约里。
    """

    element_id: int
    tag: str  # "input" / "select" / "textarea" / "button" ...
    label: str | None = None  # 关联 <label> 或推断出的语义标签文本
    placeholder: str | None = None
    name: str | None = None  # DOM name/id，辅助 LLM 判断字段语义
    type: str | None = None  # input type，如 "text" / "email" / "checkbox"
    options: list[str] | None = None  # select/radio 的可选项文本；无则 None


class PageContext(BaseModel):
    """`LLMClient.decide()` 的输入：一页表单的精简 DOM + 决策所需上下文。

    阶段 5 的 `dom.py` 尚未实现，这里先定义**最小可用**契约供阶段 4 对接测试；
    字段随阶段 5 落地可能微调，但下面三块的用途不变：`elements` 是本页要决策
    的全部编号元素，`bio_excerpt` 是按需裁剪过的 bio 摘录（不传全量 bio，省
    token），`job` 帮助 LLM 理解「这是投的哪个职位」（对开放式问答生成尤其
    有用）。
    """

    elements: list[PageElement]
    job: JobRef | None = None
    bio_excerpt: dict[str, Any] | str | None = None
    page_hint: str | None = None  # 页面/步骤提示，如 "联系方式" / "工作经历"（Workday 分页语义）


class ElementDecision(BaseModel):
    """LLM 对单个编号元素的决策（`PageDecision.decisions` 的元素）。

    **needs-user 表示法**（PRD 四「字段处理规则」——开放式问答字段 LLM 现场
    生成不阻塞；其余字段 bio 缺失/信心不够才问用户）：选定「挂在
    `ElementDecision` 本身」这一种表示，不另立 `uncertain_fields` 列表——
    `needs_user=True` 时该元素本页不填（`action` 一般是 `"skip"`，`value`/
    `value_source` 留空），`question` 必须给出人话问题。engine（阶段 5）扫描
    `PageDecision.uncertain` 把这些元素收集成 `Question` 抛给
    `QuestionChannel`；回答回写 bio 后，下一轮 FILLING 重新 `decide()` 会把
    它正常填上（不需要专门的「已回答」状态，bio 里有值了 LLM 自然会用）。
    """

    element_id: int  # 对应 PageContext.elements 里的编号
    action: Literal["fill", "select", "click", "upload", "skip"]
    value: str | None = None  # 要填入的文本 / 要选中的选项文本；click/skip 通常为 None
    value_source: FieldValueSource | None = None  # 有 value 时应给来源；skip/needs_user 留空
    confidence: float = 1.0  # 0..1，决策把握程度
    reason: str | None = None  # 简短决策理由，供 run log 审计（PRD 八）
    needs_user: bool = False  # True＝这个字段拿不准，需要问用户（见上）
    question: str | None = None  # needs_user=True 时必填：给用户看的人话问题

    @model_validator(mode="after")
    def _needs_user_requires_question(self) -> "ElementDecision":
        if self.needs_user and not self.question:
            raise ValueError("needs_user=True 时必须提供 question")
        return self


class PageDecision(BaseModel):
    """`LLMClient.decide()` 的唯一返回类型：整页所有编号元素的决策。"""

    decisions: list[ElementDecision] = Field(default_factory=list)
    # submit_page：本页填完可提交进入下一页；done：已是最后一页/流程结束；
    # need_user：本页存在 needs_user 决策，需先问询再继续。这是给 engine 的
    # 路由提示（engine 也能自己扫描 decisions 推断，显式给出减少 engine 侧逻辑）。
    next_action: Literal["submit_page", "done", "need_user"] | None = None

    @property
    def actionable(self) -> list[ElementDecision]:
        """过滤出可直接执行的决策（`needs_user=False`）。"""
        return [d for d in self.decisions if not d.needs_user]

    @property
    def uncertain(self) -> list[ElementDecision]:
        """过滤出需要问用户的决策（`needs_user=True`），供 engine 组装 `Question`。"""
        return [d for d in self.decisions if d.needs_user]


class LLMDecisionError(Exception):
    """`LLMClient.decide()` 失败时抛出：子进程超时/非零退出/空输出/JSON 解析
    或 schema 校验失败等。携带尽量多上下文（原始输出等），供 runner 落
    `FAILED(reason)`、run log 审计（PRD 八）用。"""


class LLMClient(ABC):
    """LLM 决策客户端抽象（spec 决策四大脑 / 决策十可插拔）。

    engine（阶段 5）只认 `decide(page_context) -> PageDecision` 这一个方法。
    首个实现是无头 CLI 子进程（见 `cli_client.CliLLMClient`）；HTTP/SDK 实现
    （决策十提到的 model+base_url+key 直连）可以后续按同一抽象接入，不影响
    engine 侧代码——这正是「可插拔」的落地方式。
    """

    @abstractmethod
    def decide(self, page_context: PageContext) -> PageDecision:
        """对整页编号元素做一次决策，返回 `PageDecision`。"""
        raise NotImplementedError
