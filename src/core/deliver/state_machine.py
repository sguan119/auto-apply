"""core.deliver.state_machine —— 单职位投递状态机（spec 决策六）。

纯逻辑模块：不做 IO、不碰 Playwright、不碰存储，只依赖 `core.contracts`。
只回答「这次转移合法吗」，真正执行状态变更（跑浏览器、落库）留给后续阶段的
`engine.py` / `runner.py`。

状态转移图逐条对应 `docs/deliver-spec.md` 决策六：

    PENDING         → OPENING           # 进入本次 run 队列
    OPENING         → AUTHENTICATING    # 平台需要账号
    OPENING         → FILLING           # 平台不需要账号，直接进表单
    AUTHENTICATING  → FILLING           # 登录/自动注册完成
    AUTHENTICATING  → WAITING_USER      # 自动注册复用 FILLING 循环，撞上拿不准字段（阶段 8 补，见下）
    FILLING         → WAITING_USER      # 本页有拿不准字段，抛问询（决策七）
    FILLING         → READY_TO_SUBMIT   # 逐页填完，无下一页
    WAITING_USER    → FILLING           # 用户已回答，回写 bio 后回到填表
    WAITING_USER    → SUSPENDED         # 问询超时，职位挂起（非终态，可恢复）
    READY_TO_SUBMIT → SUBMITTING        # 手动模式经问询通道确认 / 自动模式直接穿过
    SUBMITTING      → CONFIRMING
    CONFIRMING      → SUCCEEDED         # 识别到提交确认页
    SUSPENDED       → OPENING           # 问题补答后「恢复=重投」，从头开始（决策六）
    <任意非终态>    → FAILED(reason)    # 任意阶段失败

终态：SUCCEEDED、FAILED —— 没有任何合法出边。
SUSPENDED 是**持久化的非终态**：问题与职位入库，答案补上后从 OPENING 重投，
不恢复浏览器现场（决策六「恢复=重投」）。阶段 2 交接的落库规则供阶段 8 对齐：
runner 挂起时调用 `record_delivery(SUSPENDED)` + `save_suspended_questions()`；
requeue 后调用 `clear_suspended_questions()`。

**阶段 8 补的 `AUTHENTICATING → WAITING_USER` 边**（对决策六的细化，非新决策）：
决策六原文「注册表单复用 FILLING 同一套 LLM+DOM 循环」——`auth.py`（阶段 6）
的 `Authenticator._register()` 确实直接调用 `engine.run_form()`，跟 FILLING
阶段填职位表单走的是同一套「decide → 问询 → 挂起」逻辑，会产出同样的
`outcome="suspended"`。但原转移表只给了 `AUTHENTICATING → FILLING`
一条出边，没有为「注册阶段撞上拿不准字段」这个天然会发生的场景留合法边——
这是建模时的遗漏，不是要重新设计状态机。修法：直接照抄 `FILLING → WAITING_USER`
的语义加一条 `AUTHENTICATING → WAITING_USER`；`WAITING_USER → SUSPENDED`
本就存在，注册阶段挂起后一样落 `record_delivery(SUSPENDED)` +
`save_suspended_questions()`，跟 FILLING 阶段挂起的落库规则完全一致（阶段 8
runner 按 `AUTHENTICATING → WAITING_USER → SUSPENDED` 驱动）。
"""

from __future__ import annotations

from core.contracts import DeliveryStatus as S


class IllegalTransition(Exception):
    """状态转移违反决策六转移表时抛出，携带 src/dst 便于排查。"""

    def __init__(self, src: S, dst: S) -> None:
        self.src = src
        self.dst = dst
        super().__init__(f"非法状态转移：{src.value} → {dst.value}")


# 终态：转移表里没有出边；any-state→FAILED 规则也不对它们生效。
# 注意 SUSPENDED **不在**其中——它是持久化的非终态，见模块文档。
_TERMINAL_STATES: frozenset[S] = frozenset({S.SUCCEEDED, S.FAILED})

# 显式声明的「正常路径」出边（不含 any-state→FAILED，那条规则单独叠加）。
_EXPLICIT_TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.OPENING}),
    S.OPENING: frozenset({S.AUTHENTICATING, S.FILLING}),
    # WAITING_USER 出边见下：自动注册复用 FILLING 循环，见模块文档「阶段 8 补的边」。
    S.AUTHENTICATING: frozenset({S.FILLING, S.WAITING_USER}),
    S.FILLING: frozenset({S.WAITING_USER, S.READY_TO_SUBMIT}),
    S.WAITING_USER: frozenset({S.FILLING, S.SUSPENDED}),
    S.READY_TO_SUBMIT: frozenset({S.SUBMITTING}),
    S.SUBMITTING: frozenset({S.CONFIRMING}),
    S.CONFIRMING: frozenset({S.SUCCEEDED}),
    # SUSPENDED 恢复 = 重投，不是恢复现场：唯一出边是重新 OPENING（决策六）。
    S.SUSPENDED: frozenset({S.OPENING}),
    S.SUCCEEDED: frozenset(),
    S.FAILED: frozenset(),
}

# 对外公开的完整转移表：非终态在显式出边之外一律叠加「→FAILED」
# （决策六「任意阶段失败」，SUSPENDED 因非终态也叠加此边）。
TRANSITIONS: dict[S, frozenset[S]] = {
    status: (dests if status in _TERMINAL_STATES else dests | frozenset({S.FAILED}))
    for status, dests in _EXPLICIT_TRANSITIONS.items()
}


def can_transition(src: S, dst: S) -> bool:
    """判断 src → dst 是否是转移表里的合法边。"""
    return dst in TRANSITIONS.get(src, frozenset())


def assert_transition(src: S, dst: S) -> None:
    """不合法则抛 `IllegalTransition`；合法则什么也不做。供调用方在执行动作前校验。"""
    if not can_transition(src, dst):
        raise IllegalTransition(src, dst)


def is_terminal(status: S) -> bool:
    """SUCCEEDED / FAILED 是终态，没有任何合法出边。

    SUSPENDED **不是**终态——它是持久化的挂起态，问题补答后从 OPENING 重投
    （决策六「恢复=重投」），因此不计入这里；调用方判断「run 是否还有活要干」
    时不能把 SUSPENDED 当作跟 SUCCEEDED/FAILED 一样已经结束。
    """
    return status in _TERMINAL_STATES


def is_failure(status: S) -> bool:
    """是否失败终态。目前只有 FAILED；独立出来是为了未来失败态若细分，
    调用点不用跟着改。"""
    return status is S.FAILED


class JobStateMachine:
    """包一层「当前状态」的轻量状态机，`.to(dst)` 校验合法性后原地推进。

    纯内存对象，不持久化——阶段 8 的 runner 负责在真正执行完一步动作
    （打开页面、登录、填表……）后调用 `.to()` 推进状态，并按其落库纪律
    只把终态/SUSPENDED 写入 `deliveries` 表。
    """

    def __init__(self, initial: S = S.PENDING) -> None:
        self.status = initial
        self.failure_reason: str | None = None

    def to(self, dst: S, *, reason: str | None = None) -> "JobStateMachine":
        """推进到 dst；非法转移抛 `IllegalTransition`，成功则更新 `self.status`。

        `reason` 仅在 `dst is FAILED` 时有意义，记录到 `self.failure_reason`
        （对应 `DeliveryRecord.failure_reason`，落库是调用方的职责）。
        """
        assert_transition(self.status, dst)
        self.status = dst
        if dst is S.FAILED:
            self.failure_reason = reason
        return self

    def can_go(self, dst: S) -> bool:
        """`self.status` 能否合法转移到 dst，不实际推进。"""
        return can_transition(self.status, dst)
