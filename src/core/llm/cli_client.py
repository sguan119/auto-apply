"""core.llm.cli_client —— LLMClient 的首个实现：无头 CLI 子进程（spec 决策四/十）。

用户已确认的范围决策：第一个 `LLMClient` 实现走 headless CLI 子进程，思路
参考 ApplyPilot 用 Claude Code CLI 作投递「大脑」
（`docs/research/autofill-tools/01-applypilot.md`）——但这里不绑定任何具体
供应商：`CliLLMClient` 只知道「把 prompt 喂进子进程 stdin，从 stdout 读 JSON」，
默认命令 `claude -p` 只是 `config.example.toml` 里的默认值，换成任何能这么
工作的命令都能接。

**stdout 必须是原始 PageDecision JSON**：`_extract_json()` 从 CLI 输出里抠出
那一个 `{"decisions": ..., "next_action": ...}` 对象——顶层必须直接带
PageDecision 字段。**不接受 agent 信封**：`claude -p --output-format json` 输出
`{"type":"result","result":"...(决策 JSON 被转义进字符串)..."}`，决策对象藏在
`result` 字符串里、顶层没有 `decisions`/`next_action`，`_extract_json` 会拒收
（宁可显式 llm_decision_error 也不静默把信封「校验」成空决策）——这是刻意
不在解析器里给某个供应商开特例，而是靠默认命令 `claude -p`（直接输出模型
文本）从源头保证 stdout 是原始决策 JSON。详见 config.example.toml/README。

**JSON 解析健壮性**：CLI 输出经常夹带 markdown 代码块或解释性文字（真实 LLM
CLI 的常见行为），`_extract_json()` 负责从中抠出 JSON 对象文本。

**Windows 上的命令切分**：见 `_split_command()` 文档字符串。

**密钥传递**：`api_key`/`base_url` 一律走子进程 `env`，不拼进命令行参数
（命令行参数在同机其它进程眼里通常可见，如 `tasklist`/`ps`；env 更不容易
被无意记进日志或历史记录）。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from typing import Any

from pydantic import ValidationError

from core.config import LLMSettings
from core.llm.client import LLMClient, LLMDecisionError, PageContext, PageDecision

_SYSTEM_PROMPT = """你是求职投递工具的表单填写决策引擎。
你会收到一页表单的精简 DOM（编号元素列表 PageContext.elements）、职位信息（job）、
用户简历摘要（bio_excerpt）。对每一个编号元素做出决策：

1. 能从 bio_excerpt 里直接对应上的字段：action="fill"（文本框）或 "select"
   （下拉/单选），value 填具体值，value_source="bio"。
2. 开放式问答字段（如「为什么想加入我们」「你的优势是什么」）：结合 job 和
   bio_excerpt 现场生成回答，不要因为没有现成答案就跳过或问用户，
   action="fill"，value_source="llm_generated"。
3. bio_excerpt 里找不到、且不是开放式问答的字段（如「是否需要工作签证」这类
   需要用户本人确认的事实性问题），或者你对某个决策信心不足：
   needs_user=true，question 写清楚要问用户什么人话问题，action="skip"，
   value/value_source 留空。不要瞎猜硬填。
4. 附件上传字段：action="upload"，value 留空（引擎自己知道简历/求职信路径）。
5. 无需处理的按钮/元素：action="click" 或 "skip"。

严格按下面给出的 PageDecision JSON Schema 输出，覆盖 elements 里的每一个
element_id，不要遗漏、不要编造不存在的 element_id。"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# PageDecision 的顶层字段名，用来在多个候选 JSON 对象里挑出「真正的决策对象」
# （见 _extract_json）。从 model_fields 派生，schema 改名会自动同步。
_PAGE_DECISION_KEYS = frozenset(PageDecision.model_fields)


def _build_prompt(page_context: PageContext) -> str:
    """system 规则 + PageDecision schema + 序列化 PageContext，拼成完整 prompt。"""
    schema_hint = json.dumps(PageDecision.model_json_schema(), ensure_ascii=False)
    context_json = page_context.model_dump_json(indent=2)
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"## PageDecision JSON Schema\n{schema_hint}\n\n"
        f"## 当前页面（PageContext）\n{context_json}\n\n"
        "只输出一个 JSON 对象（可选用 ```json 代码块包裹），不要输出其它内容。"
    )


def _balanced_object(text: str, start: int) -> str | None:
    """从 `text[start]`（必为 `{`）起配对花括号，返回完整对象子串；不闭合则 None。

    字符串内部（含转义 `\\"` / `\\\\`）的花括号不参与配对，避免被 value 里混入
    的 `{`/`}` 带偏；数组里的 `[`/`]` 不含裸 `}`，只数 `{`/`}` 即可正确定界。
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _iter_object_candidates(text: str):
    """按优先级产出 `text` 里「看起来平衡」的候选 JSON 对象子串（可能重复）。

    先给代码围栏（```json ... ```）里的对象——CLI 最明确的意图；再退回全文
    扫描，从每个 `{` 尝试配对。是否为合法 JSON 由调用方 `json.loads` 裁决。
    """
    for m in _JSON_FENCE_RE.finditer(text):
        body = m.group(1)
        brace = body.find("{")
        if brace != -1:
            region = _balanced_object(body, brace)
            if region is not None:
                yield region
    i = text.find("{")
    while i != -1:
        region = _balanced_object(text, i)
        if region is not None:
            yield region
        i = text.find("{", i + 1)


def _extract_json(text: str) -> str:
    """从 CLI 输出里抠出「那个」PageDecision JSON 对象文本。

    CLI 输出常夹带 markdown 代码块、解释性文字，甚至 prompt 里 schema 的示例
    花括号。策略：收集所有平衡的候选对象（代码围栏优先，再全文扫描），只留能
    `json.loads` 成 dict 的；其中**优先**返回顶层键命中 PageDecision 字段
    （`decisions` / `next_action`）的那个——这样即便正文里先出现无关的
    `{...}`（如「参考格式 {}」）或裁剪示例，也不会被带偏。

    找不到任何可解析对象、或没有一个含 PageDecision 字段时抛 `ValueError`，
    由调用方包成 `LLMDecisionError`——宁可显式失败进 run log，也不静默把一个
    无关对象「校验」成空决策。已知限制：顶层直接是 JSON 数组不受支持
    （PageDecision 恒为对象），会走这条失败路径。
    """
    parsed: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for region in _iter_object_candidates(text):
        if region in seen:
            continue
        seen.add(region)
        try:
            obj = json.loads(region)
        except json.JSONDecodeError:
            continue
        parsed.append((region, obj))

    if not parsed:
        raise ValueError("输出中没有找到可解析的 JSON 对象")

    for region, obj in parsed:
        if isinstance(obj, dict) and _PAGE_DECISION_KEYS.intersection(obj):
            return region
    raise ValueError(
        "输出中没有含 PageDecision 字段（decisions/next_action）的 JSON 对象"
    )


def _split_command(command: str) -> list[str]:
    """把 config 里的命令字符串切成 `subprocess.run` 的 argv 列表。

    Windows 上可执行文件/脚本路径常含反斜杠（如 `C:\\Users\\...\\claude.cmd`），
    `shlex.split` 的 POSIX 模式会把反斜杠当转义符处理，切坏路径；这里按平台
    选 `posix` 参数——Windows 用非 POSIX 规则（反斜杠保留原样，双引号仍能加
    空格参数），其它平台用标准 POSIX 规则处理引号与转义。
    """
    return shlex.split(command, posix=(os.name != "nt"))


class CliLLMClient(LLMClient):
    """`LLMClient` 的首个实现：把决策请求转成 prompt，走无头 CLI 子进程。

    对 CLI 本身不做任何假设——只知道「喂 stdin，读 stdout 的 JSON」；换成
    Gemini CLI、本地模型包装脚本等任意同构命令都能接，符合决策十「可插拔」。
    """

    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings

    def decide(self, page_context: PageContext) -> PageDecision:
        prompt = _build_prompt(page_context)
        argv = self._build_argv()
        env = self._build_env()

        try:
            result = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._settings.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMDecisionError(
                f"LLM CLI 超时（{self._settings.timeout}s）：{self._settings.command!r}"
            ) from exc
        except OSError as exc:
            raise LLMDecisionError(
                f"LLM CLI 启动失败：{self._settings.command!r}：{exc}"
            ) from exc

        if result.returncode != 0:
            raise LLMDecisionError(
                f"LLM CLI 非零退出码 {result.returncode}：{self._settings.command!r}\n"
                f"stderr: {result.stderr.strip()}\nstdout: {result.stdout.strip()}"
            )

        stdout = result.stdout.strip()
        if not stdout:
            raise LLMDecisionError(
                f"LLM CLI 输出为空：{self._settings.command!r}\nstderr: {result.stderr.strip()}"
            )

        try:
            json_text = _extract_json(stdout)
            parsed: Any = json.loads(json_text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise LLMDecisionError(
                f"LLM CLI 输出无法解析为 JSON：{exc}\n原始输出: {stdout}"
            ) from exc

        try:
            return PageDecision.model_validate(parsed)
        except ValidationError as exc:
            raise LLMDecisionError(
                f"LLM CLI 输出的 JSON 不符合 PageDecision schema：{exc}\n原始输出: {stdout}"
            ) from exc

    def _build_argv(self) -> list[str]:
        # 用字面替换而非 str.format：命令里若含其它花括号（如某些 JSON 形态的
        # 参数）不会被误当成占位符而抛 KeyError。
        command = self._settings.command.replace("{model}", self._settings.model)
        return _split_command(command)

    def _build_env(self) -> dict[str, str]:
        """密钥/模型信息通过子进程 env 传，不拼进命令行（见模块文档字符串）。"""
        env = dict(os.environ)
        env["LLM_MODEL"] = self._settings.model
        if self._settings.api_key:
            env["LLM_API_KEY"] = self._settings.api_key
        if self._settings.base_url:
            env["LLM_BASE_URL"] = self._settings.base_url
        return env
