"""tests.test_state_machine —— core.deliver.state_machine 转移合法性测试
（spec 决策六）。逐条对照转移图断言合法/非法边，以及终态/非终态判定。
"""

from __future__ import annotations

import pytest

from core.contracts import DeliveryStatus as S
from core.deliver.state_machine import (
    TRANSITIONS,
    IllegalTransition,
    JobStateMachine,
    assert_transition,
    can_transition,
    is_failure,
    is_terminal,
)

ALL_STATES = list(S)

# 决策六「正常路径」的合法边，逐条列出用于正向断言。
LEGAL_TRANSITIONS = [
    (S.PENDING, S.OPENING),
    (S.OPENING, S.AUTHENTICATING),
    (S.OPENING, S.FILLING),
    (S.AUTHENTICATING, S.FILLING),
    (S.AUTHENTICATING, S.WAITING_USER),
    (S.FILLING, S.WAITING_USER),
    (S.FILLING, S.READY_TO_SUBMIT),
    (S.WAITING_USER, S.FILLING),
    (S.WAITING_USER, S.SUSPENDED),
    (S.READY_TO_SUBMIT, S.SUBMITTING),
    (S.SUBMITTING, S.CONFIRMING),
    (S.CONFIRMING, S.SUCCEEDED),
    (S.SUSPENDED, S.OPENING),
]

# 明显非法的代表性边（非「任意状态→FAILED」这条规则覆盖的场景）。
ILLEGAL_TRANSITIONS = [
    (S.PENDING, S.SUCCEEDED),
    (S.PENDING, S.FILLING),
    (S.SUCCEEDED, S.PENDING),
    (S.SUCCEEDED, S.OPENING),
    (S.SUCCEEDED, S.FAILED),
    (S.FAILED, S.PENDING),
    (S.FAILED, S.OPENING),
    (S.CONFIRMING, S.FILLING),
    (S.FILLING, S.SUBMITTING),  # 不允许绕过 READY_TO_SUBMIT 的捷径
    (S.SUSPENDED, S.FILLING),  # 恢复=重投，只能回 OPENING，不能直接回填表
    (S.SUSPENDED, S.SUCCEEDED),
]

TERMINAL_STATES = {S.SUCCEEDED, S.FAILED}
NON_TERMINAL_STATES = [s for s in ALL_STATES if s not in TERMINAL_STATES]


class TestLegalTransitions:
    @pytest.mark.parametrize("src,dst", LEGAL_TRANSITIONS)
    def test_can_transition_true(self, src, dst):
        assert can_transition(src, dst) is True

    @pytest.mark.parametrize("src,dst", LEGAL_TRANSITIONS)
    def test_assert_transition_does_not_raise(self, src, dst):
        assert_transition(src, dst)  # 不抛即通过

    @pytest.mark.parametrize("src,dst", LEGAL_TRANSITIONS)
    def test_job_state_machine_to_advances(self, src, dst):
        machine = JobStateMachine(initial=src)
        machine.to(dst)
        assert machine.status is dst


class TestIllegalTransitions:
    @pytest.mark.parametrize("src,dst", ILLEGAL_TRANSITIONS)
    def test_can_transition_false(self, src, dst):
        assert can_transition(src, dst) is False

    @pytest.mark.parametrize("src,dst", ILLEGAL_TRANSITIONS)
    def test_assert_transition_raises(self, src, dst):
        with pytest.raises(IllegalTransition) as exc_info:
            assert_transition(src, dst)
        assert exc_info.value.src is src
        assert exc_info.value.dst is dst

    @pytest.mark.parametrize("src,dst", ILLEGAL_TRANSITIONS)
    def test_job_state_machine_to_raises_and_does_not_move(self, src, dst):
        machine = JobStateMachine(initial=src)
        with pytest.raises(IllegalTransition):
            machine.to(dst)
        assert machine.status is src  # 非法转移不改变当前状态


class TestFailureFromAnyNonTerminalState:
    @pytest.mark.parametrize("src", NON_TERMINAL_STATES)
    def test_any_non_terminal_state_can_fail(self, src):
        assert can_transition(src, S.FAILED) is True

    @pytest.mark.parametrize("src", TERMINAL_STATES)
    def test_terminal_states_cannot_transition_to_failed(self, src):
        assert can_transition(src, S.FAILED) is False

    @pytest.mark.parametrize("src", NON_TERMINAL_STATES)
    def test_job_state_machine_fail_records_reason(self, src):
        machine = JobStateMachine(initial=src)
        machine.to(S.FAILED, reason="captcha_unsolved")
        assert machine.status is S.FAILED
        assert machine.failure_reason == "captcha_unsolved"


class TestTerminalAndFailureClassification:
    def test_succeeded_is_terminal(self):
        assert is_terminal(S.SUCCEEDED) is True

    def test_failed_is_terminal(self):
        assert is_terminal(S.FAILED) is True

    def test_suspended_is_not_terminal(self):
        # 决策六：SUSPENDED 是持久化的非终态，问题补答后从 OPENING 重投。
        assert is_terminal(S.SUSPENDED) is False

    @pytest.mark.parametrize(
        "status", [s for s in ALL_STATES if s not in TERMINAL_STATES]
    )
    def test_non_terminal_states_are_not_terminal(self, status):
        assert is_terminal(status) is False

    def test_is_failure_true_only_for_failed(self):
        assert is_failure(S.FAILED) is True
        for status in ALL_STATES:
            if status is not S.FAILED:
                assert is_failure(status) is False


class TestSpecificBranches:
    """决策六里明确点名的分支节点，单独断言避免被参数化列表漏掉。"""

    def test_opening_branches_to_authenticating_or_filling(self):
        assert can_transition(S.OPENING, S.AUTHENTICATING) is True
        assert can_transition(S.OPENING, S.FILLING) is True

    def test_waiting_user_round_trips_with_filling(self):
        assert can_transition(S.FILLING, S.WAITING_USER) is True
        assert can_transition(S.WAITING_USER, S.FILLING) is True

    def test_authenticating_can_reach_waiting_user(self):
        # 阶段 8 补的边：自动注册复用 FILLING 同一套 LLM+DOM 循环（决策六），
        # 撞上拿不准字段时必须有合法边可以落 WAITING_USER → SUSPENDED，
        # 跟 FILLING 阶段挂起走同一条落库规则（见 state_machine.py 模块文档）。
        assert can_transition(S.AUTHENTICATING, S.WAITING_USER) is True

    def test_waiting_user_timeout_to_suspended(self):
        assert can_transition(S.WAITING_USER, S.SUSPENDED) is True

    def test_suspended_resurrection_to_opening(self):
        assert can_transition(S.SUSPENDED, S.OPENING) is True

    def test_ready_to_submit_passes_through_for_both_modes(self):
        # 手动模式经问询确认、自动模式直接穿过——状态图上是同一条边，
        # 模式差异只体现在 runner 是否在此处调用问询通道（阶段 8）。
        assert can_transition(S.READY_TO_SUBMIT, S.SUBMITTING) is True


def test_transitions_map_only_contains_known_states():
    assert set(TRANSITIONS.keys()) == set(ALL_STATES)
    for dests in TRANSITIONS.values():
        assert dests <= set(ALL_STATES)


def test_can_transition_false_for_pending_success():
    # smoke test 对齐 build 指令里的手工验证命令
    assert can_transition(S.WAITING_USER, S.SUSPENDED) is True
    assert can_transition(S.PENDING, S.SUCCEEDED) is False
