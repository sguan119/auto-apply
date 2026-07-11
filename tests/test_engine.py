"""tests.test_engine —— core.deliver.engine.FillEngine 测试。

不调用真实 LLM、不碰真实 Workday：用 `page.set_content()` 灌入静态多步表单
fixture（headless chromium 真实驱动 DOM/Playwright 行为），配一个「脚本化」
`LLMClient`（预先编排好按调用顺序返回的 `PageDecision`）与
`core.questions.channel.AutoAnswerChannel`（已有的测试桩问询通道）。
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import sync_playwright

from core.bio.store import BioStore
from core.contracts import Answer, FieldValueSource, JobRef
from core.deliver.engine import FillEngine
from core.deliver.selector_cache import SelectorCache
from core.llm.client import (
    ElementDecision,
    LLMClient,
    LLMDecisionError,
    PageContext,
    PageDecision,
)
from core.questions.channel import TIMEOUT, AutoAnswerChannel


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------


class ScriptedLLMClient(LLMClient):
    """按调用顺序回放预先编排好的 `PageDecision` 列表；记录每次收到的
    `PageContext`，供断言 prompt/bio_excerpt 是否按预期变化，以及调用次数
    （selector_cache 命中与否的判据）。"""

    def __init__(self, script: list[PageDecision]) -> None:
        self._script = list(script)
        self.contexts: list[PageContext] = []

    def decide(self, page_context: PageContext) -> PageDecision:
        self.contexts.append(page_context)
        if not self._script:
            raise AssertionError("ScriptedLLMClient 脚本已耗尽，但又被调用了一次")
        return self._script.pop(0)

    @property
    def call_count(self) -> int:
        return len(self.contexts)


class FailingLLMClient(LLMClient):
    def decide(self, page_context: PageContext) -> PageDecision:
        raise LLMDecisionError("模拟不可恢复的 LLM 决策失败")


class InMemoryBioStore(BioStore):
    """纯内存 BioStore 测试替身，不落盘。"""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.write_calls: list[tuple[str, Any, str | None]] = []

    def read_path(self, field_path: str) -> Any | None:
        node: Any = self.data
        for part in field_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def write_path(self, field_path: str, value: Any, question: str | None = None) -> None:
        self.write_calls.append((field_path, value, question))
        parts = field_path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture()
def job() -> JobRef:
    return JobRef(
        platform="workday",
        job_id="job-1",
        url="https://example.com/jobs/1",
        title="Software Engineer",
        company="Acme",
        score=0.9,
    )


def make_engine(page, llm_client, *, bio_store=None, question_channel=None, **kwargs) -> FillEngine:
    return FillEngine(
        page=page,
        llm_client=llm_client,
        bio_store=bio_store or InMemoryBioStore(),
        question_channel=question_channel or AutoAnswerChannel(),
        selector_cache=kwargs.pop("selector_cache", None) or SelectorCache(),
        **kwargs,
    )


def decision(*decisions: ElementDecision, next_action=None) -> PageDecision:
    return PageDecision(decisions=list(decisions), next_action=next_action)


def fill(element_id: int, value: str, source=FieldValueSource.BIO) -> ElementDecision:
    return ElementDecision(
        element_id=element_id, action="fill", value=value, value_source=source
    )


def select(element_id: int, value: str, source=FieldValueSource.BIO) -> ElementDecision:
    return ElementDecision(
        element_id=element_id, action="select", value=value, value_source=source
    )


def click(element_id: int) -> ElementDecision:
    return ElementDecision(element_id=element_id, action="click")


def needs_user(element_id: int, question: str) -> ElementDecision:
    return ElementDecision(
        element_id=element_id, action="skip", needs_user=True, question=question
    )


# ----------------------------------------------------------------------
# 单页端到端
# ----------------------------------------------------------------------


class TestSinglePageFill:
    def test_scripted_decision_fills_dom_and_returns_completed(self, page, job):
        page.set_content(
            """
            <input name="full_name" type="text">
            <button type="button">Submit</button>
            """
        )
        llm = ScriptedLLMClient(
            [decision(fill(1, "Alice"), click(2), next_action="done")]
        )
        engine = make_engine(page, llm)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert page.locator('[name="full_name"]').input_value() == "Alice"
        assert len(result.filled_fields) == 1
        assert result.filled_fields[0].value == "Alice"
        assert result.filled_fields[0].value_source == FieldValueSource.BIO
        assert result.pages_completed == 1


class TestMultiPageFill:
    def test_two_pages_both_get_filled_in_order(self, page, job):
        page.set_content(
            """
            <div id="page1">
              <input name="full_name" type="text">
              <button type="button"
                onclick="document.getElementById('page1').style.display='none';
                         document.getElementById('page2').style.display='block';">Continue</button>
            </div>
            <div id="page2" style="display:none">
              <input name="email" type="email">
              <button type="button">Finish</button>
            </div>
            """
        )
        llm = ScriptedLLMClient(
            [
                decision(fill(1, "Alice"), click(2), next_action="submit_page"),
                decision(fill(1, "alice@example.com"), click(2), next_action="done"),
            ]
        )
        engine = make_engine(page, llm)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert result.pages_completed == 2
        assert page.locator('[name="email"]').input_value() == "alice@example.com"
        values = {f.value for f in result.filled_fields}
        assert values == {"Alice", "alice@example.com"}


# ----------------------------------------------------------------------
# uncertain → 问询 → 回写 → 重决策
# ----------------------------------------------------------------------


class TestUncertainFieldFlow:
    def test_answered_question_writes_back_bio_and_fills_on_redecide(self, page, job):
        page.set_content(
            """
            <input name="full_name" type="text">
            <input name="visa_sponsorship" type="text">
            <button type="button">Submit</button>
            """
        )
        llm = ScriptedLLMClient(
            [
                decision(
                    fill(1, "Alice"),
                    needs_user(2, "Do you require visa sponsorship?"),
                ),
                decision(
                    fill(2, "No", source=FieldValueSource.USER_ANSWER),
                    click(3),
                    next_action="done",
                ),
            ]
        )
        bio_store = InMemoryBioStore()

        def answer_fn(questions):
            assert len(questions) == 1
            assert questions[0].question == "Do you require visa sponsorship?"
            return [Answer(question=questions[0], answer="No")]

        channel = AutoAnswerChannel(answer_fn)
        engine = make_engine(page, llm, bio_store=bio_store, question_channel=channel)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert page.locator('[name="visa_sponsorship"]').input_value() == "No"
        assert len(bio_store.write_calls) == 1
        field_path, value, question = bio_store.write_calls[0]
        assert value == "No"
        assert question == "Do you require visa sponsorship?"
        assert len(result.bio_writebacks) == 1
        assert result.bio_writebacks[0].field_path == field_path
        # 回写后必须强制重新推理（bio 数据变了，不能沿用第一次的 needs_user 决策）
        assert llm.call_count == 2
        # 回写的答案必须在「重新推理」那次 decide 的 bio_excerpt 里被读回来，
        # 交给 LLM 直接使用——这正是 form_answers 命名空间回读复用的设计意图。
        redecide_excerpt = llm.contexts[1].bio_excerpt
        assert redecide_excerpt is not None
        assert field_path in redecide_excerpt
        assert redecide_excerpt[field_path] == "No"
        # 第一次 decide 时 bio 里还没有该答案
        assert (llm.contexts[0].bio_excerpt or {}).get(field_path) is None

    def test_timeout_suspends_without_infinite_loop(self, page, job):
        page.set_content(
            """
            <input name="full_name" type="text">
            <input name="mystery" type="text">
            """
        )
        llm = ScriptedLLMClient(
            [decision(fill(1, "Alice"), needs_user(2, "What is your mystery field?"))]
        )
        channel = AutoAnswerChannel()  # 无 answer_fn → 默认 TIMEOUT
        engine = make_engine(page, llm, question_channel=channel)

        result = engine.run_form(job)

        assert result.outcome == "suspended"
        assert len(result.pending_questions) == 1
        assert result.pending_questions[0].question == "What is your mystery field?"
        # 挂起前已经执行过的 actionable 决策（填 full_name）不应丢失
        assert any(f.value == "Alice" for f in result.filled_fields)
        assert llm.call_count == 1  # 没有陷入重试循环


# ----------------------------------------------------------------------
# selector_cache
# ----------------------------------------------------------------------


class TestSelectorCache:
    def test_second_structurally_identical_page_skips_llm_call(self, browser, job):
        html = '<input name="full_name" type="text"><button type="button">Submit</button>'
        llm = ScriptedLLMClient(
            [decision(fill(1, "Alice"), click(2), next_action="done")]
        )
        shared_cache = SelectorCache()

        page_a = browser.new_page()
        page_a.set_content(html)
        engine_a = make_engine(page_a, llm, selector_cache=shared_cache)
        result_a = engine_a.run_form(job)
        page_a.close()

        assert result_a.outcome == "completed"
        assert llm.call_count == 1

        # 第二个「职位」：全新 Page 实例，同一 ATS 模板结构（同 html）。
        page_b = browser.new_page()
        page_b.set_content(html)
        engine_b = make_engine(page_b, llm, selector_cache=shared_cache)
        result_b = engine_b.run_form(job)

        assert result_b.outcome == "completed"
        assert llm.call_count == 1  # 命中缓存，没有再调一次 LLM
        assert page_b.locator('[name="full_name"]').input_value() == "Alice"
        page_b.close()

    def test_job_specific_llm_generated_value_is_not_cached_across_jobs(self, browser):
        """跨职位串味回归测试（决策四缓存安全边界）。

        两个不同职位共用同一个 SelectorCache、同一 ATS 模板结构（同 html →
        同结构指纹）。表单里有一个 LLM_GENERATED 字段（求职信/「为什么想加入
        贵司」这类逐职位定制文案）。断言 B 职位**不会**拿到 A 职位生成的文案，
        而是各自重新推理出自己的值。
        """
        html = (
            '<input name="full_name" type="text">'
            '<textarea name="cover_letter"></textarea>'
            '<button type="button">Submit</button>'
        )
        job_a = JobRef(
            platform="workday", job_id="job-a", url="https://example.com/jobs/a",
            title="Software Engineer", company="Acme", score=0.9,
        )
        job_b = JobRef(
            platform="workday", job_id="job-b", url="https://example.com/jobs/b",
            title="Software Engineer", company="Globex", score=0.9,
        )
        cover_a = "I am thrilled to join Acme specifically."
        cover_b = "I am thrilled to join Globex specifically."
        llm = ScriptedLLMClient(
            [
                decision(
                    fill(1, "Alice"),
                    fill(2, cover_a, source=FieldValueSource.LLM_GENERATED),
                    click(3),
                    next_action="done",
                ),
                decision(
                    fill(1, "Alice"),
                    fill(2, cover_b, source=FieldValueSource.LLM_GENERATED),
                    click(3),
                    next_action="done",
                ),
            ]
        )
        shared_cache = SelectorCache()

        page_a = browser.new_page()
        page_a.set_content(html)
        engine_a = make_engine(page_a, llm, selector_cache=shared_cache)
        result_a = engine_a.run_form(job_a)
        assert result_a.outcome == "completed"
        assert page_a.locator('[name="cover_letter"]').input_value() == cover_a
        page_a.close()

        # 第二个职位：同结构指纹。若含 LLM_GENERATED 的决策被缓存，B 会拿到
        # cover_a——回归点正是要证明不会。
        page_b = browser.new_page()
        page_b.set_content(html)
        engine_b = make_engine(page_b, llm, selector_cache=shared_cache)
        result_b = engine_b.run_form(job_b)
        assert result_b.outcome == "completed"

        filled_b = page_b.locator('[name="cover_letter"]').input_value()
        assert filled_b == cover_b, "B 职位应拿到自己的求职信，而非 A 的"
        assert filled_b != cover_a, "跨职位串味：B 职位拿到了 A 职位的求职信"
        # 含 LLM_GENERATED 的页面没被缓存 → B 职位必须重新推理一次
        assert llm.call_count == 2
        page_b.close()

    def test_bio_only_page_is_still_cached_across_jobs(self, browser):
        """对照：纯 BIO/click 的页面（无逐职位定制值）仍然跨职位命中缓存，
        确保安全闸没有把 token 节省一并砍掉。"""
        html = '<input name="full_name" type="text"><button type="button">Submit</button>'
        job_a = JobRef(
            platform="workday", job_id="job-a", url="https://example.com/jobs/a",
            title="SWE", company="Acme", score=0.9,
        )
        job_b = JobRef(
            platform="workday", job_id="job-b", url="https://example.com/jobs/b",
            title="SWE", company="Globex", score=0.9,
        )
        llm = ScriptedLLMClient([decision(fill(1, "Alice"), click(2), next_action="done")])
        shared_cache = SelectorCache()

        page_a = browser.new_page()
        page_a.set_content(html)
        make_engine(page_a, llm, selector_cache=shared_cache).run_form(job_a)
        page_a.close()

        page_b = browser.new_page()
        page_b.set_content(html)
        result_b = make_engine(page_b, llm, selector_cache=shared_cache).run_form(job_b)
        page_b.close()

        assert result_b.outcome == "completed"
        assert llm.call_count == 1  # 命中缓存，无逐职位定制值时仍省一次调用


# ----------------------------------------------------------------------
# searchable dropdown（type + Enter）
# ----------------------------------------------------------------------


class TestSearchableDropdown:
    def test_select_action_on_non_native_combobox_types_and_presses_enter(self, page, job):
        page.set_content(
            """
            <input id="city" role="combobox" name="city" type="text" autocomplete="off">
            <button type="button">Submit</button>
            <script>
              document.getElementById('city').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                  document.getElementById('city').setAttribute('data-confirmed',
                    document.getElementById('city').value);
                }
              });
            </script>
            """
        )
        llm = ScriptedLLMClient(
            [decision(select(1, "Seattle"), click(2), next_action="done")]
        )
        engine = make_engine(page, llm)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert page.locator("#city").input_value() == "Seattle"
        assert page.locator("#city").get_attribute("data-confirmed") == "Seattle"


# ----------------------------------------------------------------------
# 可选/缺失字段容错
# ----------------------------------------------------------------------


class TestOptionalFieldTolerance:
    def test_decision_referencing_missing_element_id_does_not_crash(self, page, job):
        page.set_content('<input name="full_name" type="text"><button type="button">Go</button>')
        llm = ScriptedLLMClient(
            [
                decision(
                    fill(1, "Alice"),
                    fill(99, "ghost field"),  # 页面上根本不存在的编号
                    click(2),
                    next_action="done",
                )
            ]
        )
        engine = make_engine(page, llm)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert page.locator('[name="full_name"]').input_value() == "Alice"
        # 幽灵字段不应该出现在 filled_fields 里
        assert all(f.value != "ghost field" for f in result.filled_fields)


# ----------------------------------------------------------------------
# repeater（「添加一段」按钮触发 DOM 变化，同页继续循环）
# ----------------------------------------------------------------------


class TestRepeaterBlock:
    def test_add_block_click_with_no_next_action_recollects_same_page(self, page, job):
        page.set_content(
            """
            <div id="experiences"></div>
            <button id="add-btn" type="button"
              onclick="document.getElementById('experiences').innerHTML +=
                '<input name=company_1 type=text>';">Add experience</button>
            <button id="submit-btn" type="button">Submit</button>
            """
        )
        # 第一轮：只看到「Add experience」「Submit」两个按钮，点 Add；
        # next_action 留空 → engine 在同一页内重新采集。
        # 第二轮：新出现的 company_1 输入框，填完后点 Submit，next_action=done。
        llm = ScriptedLLMClient(
            [
                decision(click(1), next_action=None),
                decision(fill(1, "Acme Inc"), click(3), next_action="done"),
            ]
        )
        engine = make_engine(page, llm)

        result = engine.run_form(job)

        assert result.outcome == "completed"
        assert page.locator('[name="company_1"]').input_value() == "Acme Inc"
        assert llm.call_count == 2


# ----------------------------------------------------------------------
# LLM 失败
# ----------------------------------------------------------------------


class TestLlmFailure:
    def test_llm_decision_error_maps_to_failed_outcome(self, page, job):
        page.set_content('<input name="full_name" type="text">')
        engine = make_engine(page, FailingLLMClient())

        result = engine.run_form(job)

        assert result.outcome == "failed"
        assert "llm_decision_error" in (result.failure_reason or "")
