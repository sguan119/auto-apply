"""tests.test_cli_client —— core.llm.cli_client.CliLLMClient 测试。

不调用任何真实 LLM：用一个「假 CLI」脚本（`sys.executable` 跑的临时 .py 文件）
模拟 headless CLI 子进程的各种行为（正常 JSON / 代码块+文字包裹 / 非零退出 /
垃圾输出 / 超时），覆盖 `decide()` 的解析与健壮性路径。

假 CLI 还会把「收到的 stdin」和「看到的环境变量」原样写进一个由
`FAKE_CLI_ECHO_PATH` 指定的侧车文件，供测试断言 prompt 拼装内容与密钥
传递方式（不进 argv，走 env）。
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from autoapply.core.config import LLMSettings
from autoapply.core.contracts import FieldValueSource, JobRef
from autoapply.core.llm.cli_client import CliLLMClient, _extract_json
from autoapply.core.llm.client import LLMDecisionError, PageContext, PageDecision, PageElement

_REAL = '{"decisions": [{"element_id": 1, "action": "skip"}], "next_action": "done"}'

_FAKE_CLI_SOURCE = textwrap.dedent(
    """
    import json
    import os
    import sys
    import time

    mode = sys.argv[1]
    stdin_data = sys.stdin.read()

    echo_path = os.environ.get("FAKE_CLI_ECHO_PATH")
    if echo_path:
        with open(echo_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "stdin": stdin_data,
                    "env": {
                        "LLM_MODEL": os.environ.get("LLM_MODEL"),
                        "LLM_API_KEY": os.environ.get("LLM_API_KEY"),
                        "LLM_BASE_URL": os.environ.get("LLM_BASE_URL"),
                    },
                },
                f,
            )

    HAPPY_DECISION = {
        "decisions": [
            {
                "element_id": 1,
                "action": "fill",
                "value": "Alice",
                "value_source": "bio",
                "confidence": 0.95,
                "reason": "matched bio.personal.name",
            },
            {
                "element_id": 2,
                "action": "skip",
                "needs_user": True,
                "question": "Do you require visa sponsorship?",
            },
        ],
        "next_action": "submit_page",
    }

    if mode == "happy":
        print(json.dumps(HAPPY_DECISION))
    elif mode == "fenced":
        print("Sure, here is my decision:")
        print("```json")
        print(json.dumps(HAPPY_DECISION))
        print("```")
        print("Let me know if you need anything else.")
    elif mode == "prose_brace":
        # 正文里先冒出一个无关的花括号（引用 schema 片段），随后才是真答案；
        # _extract_json 必须跳过前者、锁定含 decisions 的真对象。
        print("Per the schema {element_id: int}, my decision is:")
        print(json.dumps(HAPPY_DECISION))
    elif mode == "example_fence":
        # 先给一个空对象示例围栏，再给真答案——不能被示例带偏。
        print("For example: ```json\\n{}\\n```")
        print("Actual decision:")
        print(json.dumps(HAPPY_DECISION))
    elif mode == "nonzero":
        print("boom", file=sys.stderr)
        sys.exit(1)
    elif mode == "garbage":
        print("not json at all, sorry about that")
    elif mode == "timeout":
        time.sleep(30)
    else:
        raise SystemExit(f"unknown mode: {mode}")
    """
)


@pytest.fixture()
def fake_cli(tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI_SOURCE, encoding="utf-8")
    return script


def _settings(command: str, **overrides) -> LLMSettings:
    overrides.setdefault("model", "test-model")
    overrides.setdefault("timeout", 10)
    return LLMSettings(command=command, **overrides)


def _page_context() -> PageContext:
    return PageContext(
        elements=[
            PageElement(element_id=1, tag="input", label="Full name", type="text"),
            PageElement(
                element_id=2,
                tag="select",
                label="Visa sponsorship?",
                options=["Yes", "No"],
            ),
        ],
        job=JobRef(
            platform="workday",
            job_id="123",
            url="https://example.com/jobs/123",
            title="Software Engineer",
            company="Acme",
            score=0.9,
        ),
        bio_excerpt={"personal": {"name": "Alice"}},
        page_hint="联系方式",
    )


class TestHappyPath:
    def test_valid_json_parses_into_page_decision(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} happy"))
        decision = client.decide(_page_context())

        assert isinstance(decision, PageDecision)
        assert decision.next_action == "submit_page"
        assert len(decision.decisions) == 2

    def test_normal_fill_decision_has_value_and_source(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} happy"))
        decision = client.decide(_page_context())

        fill = next(d for d in decision.decisions if d.element_id == 1)
        assert fill.action == "fill"
        assert fill.value == "Alice"
        assert fill.value_source == FieldValueSource.BIO
        assert fill.needs_user is False

    def test_needs_user_field_parsed_with_question(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} happy"))
        decision = client.decide(_page_context())

        uncertain = decision.uncertain
        assert len(uncertain) == 1
        assert uncertain[0].element_id == 2
        assert uncertain[0].question == "Do you require visa sponsorship?"
        assert uncertain[0].value is None


class TestJsonExtractionRobustness:
    def test_json_wrapped_in_markdown_fence_and_prose_still_parses(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} fenced"))
        decision = client.decide(_page_context())

        assert len(decision.decisions) == 2
        assert decision.actionable[0].value == "Alice"

    def test_prose_brace_before_real_object_is_skipped(self, fake_cli):
        # 真答案 = HAPPY_DECISION（2 条决策）；正文里在它之前的无关花括号
        # 不能把解析带偏成空/错对象。
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} prose_brace"))
        decision = client.decide(_page_context())

        assert decision.next_action == "submit_page"
        assert len(decision.decisions) == 2

    def test_example_fence_does_not_shadow_real_answer(self, fake_cli):
        # 空对象示例围栏 {} 在真答案之前，不能被它遮蔽成空决策。
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} example_fence"))
        decision = client.decide(_page_context())

        assert decision.next_action == "submit_page"
        assert len(decision.decisions) == 2


class TestExtractJsonUnit:
    """直接针对 `_extract_json` 的对抗性输入（不启子进程）。"""

    def test_nested_braces_in_fence(self):
        text = '```json\n{"decisions": [], "next_action": {"a": 1}}\n```'
        assert json.loads(_extract_json(text))["next_action"] == {"a": 1}

    def test_brace_inside_string_value(self):
        text = '{"decisions": [], "next_action": "has } and { brace"}'
        assert json.loads(_extract_json(text))["next_action"] == "has } and { brace"

    def test_escaped_quote_and_brace_in_string(self):
        text = '{"decisions": [], "next_action": "she said \\"} hi\\""}'
        assert json.loads(_extract_json(text))["next_action"] == 'she said "} hi"'

    def test_prose_brace_before_real_object(self):
        text = "Based on schema {placeholder}, here: " + _REAL
        assert json.loads(_extract_json(text))["next_action"] == "done"

    def test_example_object_before_real_object(self):
        text = "Example: ```json\n{}\n```\nActual:\n" + _REAL
        assert json.loads(_extract_json(text))["next_action"] == "done"

    def test_top_level_array_raises(self):
        with pytest.raises(ValueError):
            _extract_json('[{"element_id": 1}]')

    def test_object_without_page_decision_keys_raises(self):
        with pytest.raises(ValueError):
            _extract_json('here is {"element_id": 1}')

    def test_unterminated_object_raises(self):
        with pytest.raises(ValueError):
            _extract_json('here {"decisions": [1')

    def test_no_json_at_all_raises(self):
        with pytest.raises(ValueError):
            _extract_json("sorry, no json here")

    def test_claude_code_result_envelope_is_rejected(self):
        """`claude -p --output-format json` 的结果信封必须被拒收：决策 JSON 被
        转义进 `result` 字符串里、顶层没有 decisions/next_action，不能被当成
        决策对象。这是 config.example.toml 默认改用不带 --output-format 的
        `claude -p`（直接输出模型文本）的原因——把这条 out-of-box 坑钉成断言，
        而不是仅靠文档。（见 README「LLM 命令要求」）"""
        inner = '{"decisions": [], "next_action": "done"}'
        envelope = json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "result": inner}
        )
        with pytest.raises(ValueError):
            _extract_json(envelope)

    def test_raw_model_text_output_parses(self):
        """不带 --output-format 的 `claude -p` 直接输出模型文本——即原始
        PageDecision JSON（可带 ```json 代码围栏 + 前后散文），必须能解析。"""
        text = '好的，这是决策：\n```json\n{"decisions": [], "next_action": "done"}\n```'
        assert json.loads(_extract_json(text))["next_action"] == "done"


class TestFailureModes:
    def test_nonzero_exit_raises_llm_decision_error(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} nonzero"))

        with pytest.raises(LLMDecisionError) as exc_info:
            client.decide(_page_context())
        assert "非零退出码" in str(exc_info.value)

    def test_garbage_output_raises_llm_decision_error(self, fake_cli):
        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} garbage"))

        with pytest.raises(LLMDecisionError):
            client.decide(_page_context())

    def test_timeout_raises_llm_decision_error(self, fake_cli):
        client = CliLLMClient(
            _settings(f"{sys.executable} {fake_cli} timeout", timeout=1)
        )

        with pytest.raises(LLMDecisionError) as exc_info:
            client.decide(_page_context())
        assert "超时" in str(exc_info.value)

    def test_api_key_never_leaks_into_error_message(self, fake_cli):
        # 密钥走 env 传入；即便子进程失败，错误信息（含 command/stdout/stderr）
        # 也不能带出密钥字符串。
        secret = "super-secret-key-abc123"
        client = CliLLMClient(
            _settings(f"{sys.executable} {fake_cli} nonzero", api_key=secret)
        )

        with pytest.raises(LLMDecisionError) as exc_info:
            client.decide(_page_context())
        assert secret not in str(exc_info.value)


class TestPromptAssembly:
    def test_numbered_elements_and_bio_reach_subprocess_stdin(
        self, fake_cli, tmp_path, monkeypatch
    ):
        echo_path = tmp_path / "echoed.json"
        monkeypatch.setenv("FAKE_CLI_ECHO_PATH", str(echo_path))

        client = CliLLMClient(_settings(f"{sys.executable} {fake_cli} happy"))
        client.decide(_page_context())

        echoed = json.loads(echo_path.read_text(encoding="utf-8"))
        stdin_received = echoed["stdin"]
        assert '"element_id": 1' in stdin_received
        assert "Full name" in stdin_received
        assert '"element_id": 2' in stdin_received
        assert "Alice" in stdin_received  # bio_excerpt 内容确实进了 prompt
        assert "Software Engineer" in stdin_received  # job 上下文也进了 prompt

    def test_model_and_api_key_passed_via_env_not_argv(self, fake_cli, tmp_path, monkeypatch):
        echo_path = tmp_path / "echoed.json"
        monkeypatch.setenv("FAKE_CLI_ECHO_PATH", str(echo_path))

        settings = _settings(
            f"{sys.executable} {fake_cli} happy",
            model="test-model-x",
            api_key="secret-key-123",
            base_url="https://example.com/v1",
        )
        client = CliLLMClient(settings)
        client.decide(_page_context())

        echoed = json.loads(echo_path.read_text(encoding="utf-8"))
        assert echoed["env"]["LLM_MODEL"] == "test-model-x"
        assert echoed["env"]["LLM_API_KEY"] == "secret-key-123"
        assert echoed["env"]["LLM_BASE_URL"] == "https://example.com/v1"
        # 密钥没有被拼进命令行参数（argv 只有脚本路径和 mode，不含密钥字符串）
        assert "secret-key-123" not in settings.command

    def test_model_placeholder_in_command_is_substituted(self, fake_cli, tmp_path, monkeypatch):
        echo_path = tmp_path / "echoed.json"
        monkeypatch.setenv("FAKE_CLI_ECHO_PATH", str(echo_path))

        # {model} 占位符应被 settings.model 替换后再切分成 argv 执行；
        # "happy" 是固定追加的模式参数，验证替换没有破坏后续参数切分。
        settings = _settings(
            f"{sys.executable} {fake_cli} {{model}}",
            model="happy",
        )
        client = CliLLMClient(settings)
        decision = client.decide(_page_context())

        assert len(decision.decisions) == 2
