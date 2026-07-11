"""core.contracts —— 全系统数据契约（spec 决策五）。

模块间只认这里定义的 pydantic 模型，不依赖对方内部实现（CLAUDE.md「模块解耦」）。
字段与 `docs/deliver-spec.md` 第五节的 Python 类草图一一对应；
**增删字段必须回改 spec 第五节**（spec 明文约束）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl


class DeliveryStatus(str, Enum):
    """单职位投递状态机的状态集合（spec 决策六）。

    PENDING → OPENING → AUTHENTICATING → FILLING ⇄ WAITING_USER →
    READY_TO_SUBMIT（仅手动模式停留）→ SUBMITTING → CONFIRMING → SUCCEEDED；
    任意阶段失败 → FAILED；WAITING_USER 超时 → SUSPENDED（非终态，可恢复重投）。
    """

    PENDING = "pending"
    OPENING = "opening"
    AUTHENTICATING = "authenticating"
    FILLING = "filling"
    WAITING_USER = "waiting_user"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTING = "submitting"
    CONFIRMING = "confirming"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUSPENDED = "suspended"


class FieldValueSource(str, Enum):
    """表单字段填入值的来源（spec 决策五 FilledField 注释）。"""

    BIO = "bio"  # 从 bio.yaml 按字段路径读出
    LLM_GENERATED = "llm_generated"  # LLM 直接生成（如开放式问答）
    USER_ANSWER = "user_answer"  # 用户经 QuestionChannel 回答


class JobRef(BaseModel):
    """搜索模块输出中 deliver 依赖的子集（spec 决策五）。唯一键 = (platform, job_id)。"""

    platform: str  # 来源平台，如 "linkedin" / "indeed"
    job_id: str  # 平台内职位 ID；无 ID 平台用规范化 URL 代替
    url: HttpUrl  # 投递入口（官网/ATS 优先，见 PRD 二）
    title: str
    company: str
    score: float  # 搜索模块评分，决定投递顺序

    @property
    def key(self) -> tuple[str, str]:
        """去重/查询用唯一键 (platform, job_id)（spec 决策八）。"""
        return (self.platform, self.job_id)


class FilledField(BaseModel):
    """FILLING 阶段填入的单个表单字段记录（spec 决策五 DeliveryRecord 注释）。"""

    question: str  # 表单问题原文
    value: str  # 填入值
    value_source: FieldValueSource  # 值来源：bio / llm_generated / user_answer


class DeliveryTask(BaseModel):
    """deliver 的输入：一个待投职位 + 为它定制的材料（spec 决策五）。"""

    job: JobRef
    resume_pdf: Path  # 改简历模块产物，路径约定见 spec「九、存储」
    cover_letter_pdf: Path | None = None


class DeliveryRecord(BaseModel):
    """deliver 的输出：一次投递的结果记录（PRD 八 / spec 决策五）。"""

    job: JobRef
    status: DeliveryStatus  # 终态：SUCCEEDED / FAILED / SUSPENDED（见「六」）
    filled_fields: list[FilledField] = Field(default_factory=list)
    failure_reason: str | None = None  # 如 "captcha_unsolved" / "login_failed"
    run_id: str
    started_at: datetime
    finished_at: datetime


class BioWriteback(BaseModel):
    """用户回答回写 bio 的载体（PRD 四 / spec 决策五）。"""

    field_path: str  # bio 内的字段路径，如 "preferences.visa_sponsorship_needed"
    question: str  # 表单原始问题，留档
    answer: str


class Question(BaseModel):
    """遇阻问询的问题载体（spec 决策七）。按页批量抛出，携带职位上下文以便汇总。"""

    job: JobRef  # 归属职位，供 RunSummary / CLI 展示上下文
    field_path: str | None = None  # 对应 bio 字段路径；非 bio 字段（如开放式问答）为 None
    question: str  # 表单原始问题文本
    page: str | None = None  # 所在页面/步骤标识，便于用户定位


class Answer(BaseModel):
    """用户对 Question 的回答（spec 决策七）。QuestionChannel.ask() 的返回单元。"""

    question: Question  # 对应的原始问题，回写 bio 时需要 field_path
    answer: str


class RunSummary(BaseModel):
    """一次 run 结束后的汇总（spec 决策八）：总数/成功/失败按原因分组/挂起+未答问题清单。"""

    run_id: str
    total: int
    succeeded: int
    failed_by_reason: dict[str, int] = Field(default_factory=dict)
    suspended: list[JobRef] = Field(default_factory=list)  # 本次 run 挂起的职位
    unanswered_questions: list[Question] = Field(default_factory=list)  # 集中列出待补答问题
