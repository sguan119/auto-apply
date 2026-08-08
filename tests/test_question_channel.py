"""tests.test_question_channel —— QuestionChannel 抽象与实现的测试（spec 决策七）。

覆盖：
- TIMEOUT sentinel 与「空答案列表」/`None` 语义不同；
- 桩实现 `AutoAnswerChannel` 返回的 Answer 与传入的 Question 一一对应；
- 终端实现 `TerminalQuestionChannel` 的超时路径——用 monkeypatch 让 `input()`
  阻塞超过 timeout，断言快速返回 TIMEOUT，不真的等 stdin、不拖慢 CI；
- 终端实现的正常应答路径与「确认提交」yes/no 判定。
"""

from __future__ import annotations

import threading
import time

import pytest

from autoapply.core.contracts import Answer, JobRef, Question
from autoapply.core.questions.channel import TIMEOUT, AutoAnswerChannel, QuestionChannel, Timeout
from autoapply.cli.terminal_channel import TerminalQuestionChannel


def make_job() -> JobRef:
    return JobRef(
        platform="workday",
        job_id="job-1",
        url="https://example.com/jobs/1",
        title="Software Engineer",
        company="Acme Corp",
        score=0.9,
    )


def make_questions(job: JobRef, n: int = 2) -> list[Question]:
    return [
        Question(job=job, field_path=f"preferences.field_{i}", question=f"问题 {i}?", page="page-1")
        for i in range(n)
    ]


class TestTimeoutSentinel:
    def test_timeout_is_not_none(self):
        assert TIMEOUT is not None

    def test_timeout_is_not_empty_list(self):
        # 空答案列表（问询成功但恰好没有问题）与「超时未答」必须能区分。
        assert TIMEOUT != []
        assert not isinstance(TIMEOUT, list)

    def test_timeout_is_singleton_instance_of_timeout_type(self):
        assert isinstance(TIMEOUT, Timeout)


class TestQuestionChannelAbstract:
    def test_abc_cannot_be_instantiated_directly(self):
        # QuestionChannel 是抽象基类，未实现 ask()——直接实例化必须失败，
        # 保证调用方只能拿到具体通道实现（决策二的接缝约束）。
        with pytest.raises(TypeError):
            QuestionChannel()


class TestAutoAnswerChannel:
    def test_empty_questions_returns_empty_list_without_blocking(self):
        channel = AutoAnswerChannel()
        result = channel.ask([], timeout=0.01)
        assert result == []

    def test_default_no_answer_fn_returns_timeout(self):
        channel = AutoAnswerChannel()
        job = make_job()
        result = channel.ask(make_questions(job), timeout=0.01)
        assert result is TIMEOUT

    def test_scripted_answers_correlate_to_questions(self):
        job = make_job()
        questions = make_questions(job, n=3)

        def answer_fn(qs: list[Question]) -> list[Answer]:
            return [Answer(question=q, answer=f"answer-for-{q.field_path}") for q in qs]

        channel = AutoAnswerChannel(answer_fn=answer_fn)
        result = channel.ask(questions, timeout=1.0)

        assert isinstance(result, list)
        assert len(result) == len(questions)
        for question, answer in zip(questions, result):
            assert answer.question.field_path == question.field_path
            assert answer.answer == f"answer-for-{question.field_path}"


class TestTerminalQuestionChannel:
    def test_timeout_path_does_not_block_past_timeout(self, monkeypatch):
        """`input()` 模拟用户迟迟不敲回车（sleep 远超 timeout）；
        `ask()` 必须在 timeout 附近返回 TIMEOUT，而不是等 input 完成。
        """

        def slow_input(prompt: str = "") -> str:
            time.sleep(5)
            return "太晚了"

        monkeypatch.setattr("builtins.input", slow_input)

        channel = TerminalQuestionChannel()
        job = make_job()
        questions = make_questions(job, n=1)

        started = time.monotonic()
        result = channel.ask(questions, timeout=0.2)
        elapsed = time.monotonic() - started

        assert result is TIMEOUT
        assert elapsed < 2.0  # 远小于 slow_input 的 5 秒，证明没有真等 stdin

    def test_normal_path_returns_answers_in_order(self, monkeypatch, capsys):
        job = make_job()
        questions = make_questions(job, n=2)
        canned = iter(["first answer", "second answer"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(canned))

        channel = TerminalQuestionChannel()
        result = channel.ask(questions, timeout=5.0)

        assert result != TIMEOUT
        assert [a.answer for a in result] == ["first answer", "second answer"]
        assert [a.question.field_path for a in result] == [
            q.field_path for q in questions
        ]

    def test_confirm_yes_variants_return_true(self, monkeypatch):
        job = make_job()
        for reply in ["y", "yes", "Y", "是"]:
            monkeypatch.setattr("builtins.input", lambda prompt="", reply=reply: reply)
            channel = TerminalQuestionChannel()
            assert channel.confirm(job, "是否确认提交？", timeout=5.0) is True

    def test_confirm_no_or_other_returns_false(self, monkeypatch):
        job = make_job()
        for reply in ["n", "no", "", "maybe"]:
            monkeypatch.setattr("builtins.input", lambda prompt="", reply=reply: reply)
            channel = TerminalQuestionChannel()
            assert channel.confirm(job, "是否确认提交？", timeout=5.0) is False

    def test_confirm_timeout_returns_timeout_sentinel(self, monkeypatch):
        def slow_input(prompt: str = "") -> str:
            time.sleep(5)
            return "y"

        monkeypatch.setattr("builtins.input", slow_input)
        channel = TerminalQuestionChannel()
        job = make_job()
        result = channel.confirm(job, "是否确认提交？", timeout=0.2)
        assert result is TIMEOUT

    def test_empty_questions_returns_empty_list(self):
        channel = TerminalQuestionChannel()
        assert channel.ask([], timeout=0.01) == []

    def test_consecutive_asks_use_fresh_queue_no_stale_answer(self, monkeypatch):
        """第一次 ask 超时后，后台线程仍卡在 input() 上（daemon，随进程回收）；
        第二次 ask 必须拿到自己的答案，不被上一次遗留线程/队列污染——证明每次
        ask 都用独立的 queue+thread（决策七实现的 Windows 超时写法的正确性）。
        """
        job = make_job()
        release = threading.Event()

        def blocking_input(prompt: str = "") -> str:
            release.wait(5)  # 迟迟不返回，逼出第一次超时
            return "stale-answer"

        monkeypatch.setattr("builtins.input", blocking_input)
        channel = TerminalQuestionChannel()
        first = channel.ask(make_questions(job, n=1), timeout=0.2)
        assert first is TIMEOUT

        canned = iter(["fresh-answer"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(canned))
        second = channel.ask(make_questions(job, n=1), timeout=5.0)

        assert isinstance(second, list)
        assert [a.answer for a in second] == ["fresh-answer"]  # 不是 "stale-answer"
        release.set()  # 放行遗留线程收尾，避免拖到 daemon 超时
