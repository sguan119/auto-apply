"""autoapply.core.questions.channel —— 遇阻问询通道抽象（spec 决策七）。

FILLING 循环遇到「拿不准」的字段（bio 缺失 / LLM 低信心，PRD 四）时，把同一页
所有不确定字段一次性打包成 `Question` 列表，通过 `ask()` 抛给用户，等待批量
回答或超时。

- **按页批量**：调用方（阶段 5 engine）保证一次 `ask()` 传入的是同一页内的
  全部不确定字段——多步表单必须提交当前页才能看到下一页，按页天然就是批量
  上限，跨页批量在物理上做不到（决策七）。`channel.py` 本身不做任何合并，
  只负责把传入的一批问题原样抛出、原样收答案。
- **超时挂起**：`timeout` 秒（对应 `config.toml` 的 `question_timeout`，默认
  1800）内没有获得完整应答，返回 `TIMEOUT`——一个专门的 sentinel 对象，不用
  `None`：`None` 没法区分「用户明确给了空回答」与「压根没触发超时判断」这两
  种语义，sentinel 消除歧义。调用方（阶段 8 runner）收到 `TIMEOUT` 后把该职位
  置 `SUSPENDED` 并落库挂起问题，继续投下一个职位（决策六/七）。
- **手动模式提交确认复用同一通道**（决策七，不另起机制）：`READY_TO_SUBMIT`
  阶段的「确认提交」构造一个 yes/no 语义的单条 `Question`
  （`field_path=None`，`question` 形如「是否确认提交？」）走同一个 `ask()`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from autoapply.core.contracts import Answer, Question


class Timeout:
    """`ask()` 超时未获完整应答时返回的 sentinel 类型（区别于 `None`）。

    不需要实例状态，模块级单例 `TIMEOUT` 即可；调用方用 `result is TIMEOUT`
    判断，语义上比裸 `None` 明确。
    """

    def __repr__(self) -> str:  # pragma: no cover - 纯调试辅助
        return "TIMEOUT"


TIMEOUT = Timeout()


class QuestionChannel(ABC):
    """遇阻问询的抽象接口（spec 决策七）。

    CLI 用终端交互实现（见 `cli.terminal_channel.TerminalQuestionChannel`）；
    未来 Web 用 FastAPI WebSocket/SSE 推给前端实现——底层 core（engine/runner）
    只认这个抽象，换问询通道不影响任何调用逻辑（决策二已预留接缝）。
    """

    @abstractmethod
    def ask(self, questions: list[Question], timeout: float) -> list[Answer] | Timeout:
        """抛出一页的全部问题，等待用户在 `timeout` 秒内批量回答。

        返回 `list[Answer]`（与 `questions` 一一对应、顺序一致）或 `TIMEOUT`
        （超时未获完整应答）。`questions` 为空列表时应直接返回 `[]`，不阻塞。
        """
        raise NotImplementedError


class AutoAnswerChannel(QuestionChannel):
    """测试 / 无人值守自动模式用的桩实现：不等待、不阻塞终端。

    默认策略是「什么都答不上来」，`ask()` 直接返回 `TIMEOUT`——贴合自动模式
    本就无人在场应答问询的现实（PRD 七：自动模式遇到拿不准字段同样只能挂起）。
    传入 `answer_fn`（`questions -> list[Answer]`）可自定义应答策略，供单测
    构造「已回答」场景，或未来给自动模式接一个基于 bio 默认值的兜底策略。
    """

    def __init__(
        self, answer_fn: Callable[[list[Question]], list[Answer]] | None = None
    ) -> None:
        self._answer_fn = answer_fn

    def ask(self, questions: list[Question], timeout: float) -> list[Answer] | Timeout:
        if not questions:
            return []
        if self._answer_fn is None:
            return TIMEOUT
        return self._answer_fn(questions)
