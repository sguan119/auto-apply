"""cli.terminal_channel —— QuestionChannel 的终端交互实现（spec 决策七）。

按页批量在终端打印一整页的不确定字段，逐条读用户输入；整批在 `timeout`
秒内未答完则返回 `TIMEOUT`，调用方（runner）据此把职位挂起。

Windows 兼容性说明：标准库 `select` 只能对 socket 生效，对 stdin 在 Windows 上
不可用，因此不能用 `select`/`selectors` 做超时读取。这里改用「后台线程跑阻塞
的 `input()`，主线程 `Thread.join(timeout)` 限时等待」的写法——`join` 超时后
主线程可以正常返回 `TIMEOUT`，后台线程仍卡在 `input()` 上（daemon=True，
不阻止进程退出；用户若之后才把行敲完，输入会进 `queue`，但已经没人再读，
线程随进程结束回收）。
"""

from __future__ import annotations

import queue
import threading

from core.contracts import Answer, JobRef, Question
from core.questions.channel import TIMEOUT, QuestionChannel, Timeout


class TerminalQuestionChannel(QuestionChannel):
    """终端问答实现：打印整页问题，逐条 `input()` 读答案，超时返回 `TIMEOUT`。"""

    def ask(self, questions: list[Question], timeout: float) -> list[Answer] | Timeout:
        if not questions:
            return []

        print(f"\n=== 需要你确认 {len(questions)} 个问题（{timeout:.0f} 秒内未答将挂起该职位）===")

        result_queue: "queue.Queue[list[Answer]]" = queue.Queue(maxsize=1)

        def _collect() -> None:
            answers: list[Answer] = []
            for i, q in enumerate(questions, start=1):
                page_hint = f"[{q.page}] " if q.page else ""
                print(f"{i}. {page_hint}{q.question}")
                text = input("> ")
                answers.append(Answer(question=q, answer=text))
            result_queue.put(answers)

        worker = threading.Thread(target=_collect, daemon=True)
        worker.start()
        worker.join(timeout)

        if worker.is_alive():
            print("\n[超时] 未在限定时间内答完，该职位将被挂起。")
            return TIMEOUT
        return result_queue.get()

    def confirm(self, job: JobRef, prompt: str, timeout: float) -> bool | Timeout:
        """手动模式 READY_TO_SUBMIT 的「确认提交」——复用 `ask()`（决策七）。

        构造一条 yes/no 语义的 `Question`（`field_path=None`），把回答文本
        判定为布尔值：以 y/yes/是 开头（大小写不敏感）视为确认，其余一律
        视为拒绝（宁可保守不提交，也不误投）。
        """
        question = Question(job=job, field_path=None, question=prompt, page="submit_confirm")
        result = self.ask([question], timeout)
        if isinstance(result, Timeout):
            return result
        answer_text = result[0].answer.strip().lower()
        return answer_text.startswith(("y", "是"))
