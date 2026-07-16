# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

**全自动投递脚本** —— 一个全自动求职投递工具（开源）。整体流程：**搜索职位 → 改写简历 → 自动投递**。三大模块 **search / resume / deliver** 高度独立，只通过数据契约交互。

**当前仓库聚焦 deliver（投递）模块的 CLI 版本**（Workday-only MVP）；search 与 resume 尚未落地。所有地基级技术决策（含被排除的替代方案与理由）写在 [`docs/deliver-spec.md`](docs/deliver-spec.md) —— **改动架构前先读它**，避免绕回已经讨论过的选型。

## 常用命令

```bash
# 安装（Python 3.11+，配置解析依赖 stdlib tomllib）
python -m venv .venv
.venv\Scripts\activate            # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -e ".[dev]"           # 装 core/cli 两个包 + pytest；tests 用 `from core...` 导入，必须先装

# 测试
pytest                            # 全量
pytest tests/test_engine.py       # 单文件
pytest tests/test_runner.py::TestResumeCrossJob            # 单个类
pytest tests/test_engine.py::TestSelectorCache -k cache    # 单个用例

# 运行 deliver CLI（entry point 见 pyproject [project.scripts]）
deliver run --tasks tasks.example.json --manual   # 跑一次投递（默认 manual）
deliver run --tasks tasks.example.json --auto --headful   # 自动模式 + 有头浏览器（调试）
deliver answer                    # 交互补答挂起问题（回写 bio，供下次 run 优先重投）
deliver retry workday R12345      # 手动重投单个 FAILED 职位（失败默认不自动重试）
deliver status                    # 打印投递记录 + 挂起问题清单
```

无 lint/format 工具链配置；代码风格跟随现有文件（`from __future__ import annotations`、类型注解、大量中文 docstring 记录"为什么这么做"）。

## 配置与密钥

- 非密钥行为参数 → `config.toml`；密钥 → `.env`（两者均 gitignore，**绝不入仓库**）。仓库只给模板：`cp config.example.toml config.toml`、`cp .env.example .env`。
- 未创建 `config.toml` 时加载逻辑回退到 `config.example.toml`，首次可直接跑通。
- **`[llm].command` 的 CLI 子进程，stdout 必须是原始 `PageDecision` JSON 对象**（`{"decisions":[...], "next_action":...}`，可用 ```json 代码块包裹）。**不要**用 `claude -p --output-format json`——那会套一层 Claude Code 结果信封，决策 JSON 被转义进 `result` 字符串，解析器拒收 → 每页 `llm_decision_error`。默认用不带 `--output-format` 的 `claude -p`。换别的 CLI 同理：只要 stdout 是裸决策 JSON 即可，否则写个薄包装脚本透出内层。

## 架构大图

分三层，接缝对应 spec 决策二"核心逻辑与界面分离"：

```
入口层   cli/ (typer, 薄)              未来 Web 后端 (FastAPI, 薄)
              └──────────────┬──────────────┘
核心层        src/core/  （纯 Python 包，零界面假设）
```

**`cli/main.py` 每个命令只做「解析参数 → 调 core 函数 → 格式化打印」**，真正的编排/存储/浏览器逻辑全在 core。加功能时逻辑进 core，不要堆进 CLI。

### 投递引擎的心脏：DOM → LLM → Playwright 逐页循环（spec 决策四）

这是自研执行架构，不用视觉截图、不用 Agent-MCP。数据流：

1. **`deliver/dom.py`** `collect_page(page)` —— 把当前页 DOM 精简 + 给每个可交互元素编号，产出 `PageSnapshot`（含 `selector_map`：编号 → Playwright 选择器）。
2. **`llm/client.py` / `cli_client.py`** —— `LLMClient.decide(PageContext)` 让 LLM 对整页决策「填哪个编号、填什么、值来源（BIO/LLM_GENERATED/USER_ANSWER）」，返回 `PageDecision`（`actionable` + `uncertain`/needs_user + `next_action`）。
3. **`deliver/browser.py`** `apply_action()` —— 用 Playwright 执行决策（可搜索下拉自动分流「键入+Enter」）。
4. **`deliver/engine.py`** `FillEngine.run_form()` —— 驱动上面三步逐页循环，直到 `completed`/`suspended`/`failed`。**engine 只认注入的抽象接口**（`LLMClient`/`BioStore`/`QuestionChannel`/`RunLogger`），不导入 state_machine/repository，只返回结构化 `RunFormResult`。

**选择器缓存（`deliver/selector_cache.py`）** 是省 token 补丁：键 = 页面**结构指纹**（不含 value）。关键安全边界见 `engine._is_cross_job_cacheable()`——含 `LLM_GENERATED` 填值或 `upload` 动作的页面**绝不跨职位缓存**（否则会把 A 职位的求职信/简历重放到 B 职位，真实错投 bug，回归测试 `test_runner.py::TestResumeCrossJob`）。

### 状态机 + 编排（spec 决策六/七/八）

- **`deliver/state_machine.py`** —— 单职位 8 状态：`PENDING → OPENING → AUTHENTICATING → FILLING ⇄ WAITING_USER → READY_TO_SUBMIT → SUBMITTING → CONFIRMING → SUCCEEDED`；任意阶段失败 → `FAILED(reason)`；`WAITING_USER` 超时 → `SUSPENDED`（非终态，可恢复）。
- **`deliver/runner.py`** `run_delivery()` —— **唯一编排入口**，串起全部构件按精确顺序驱动每个职位的状态机，产出 `RunSummary`。模块顶部 docstring 有 outcome→DeliveryStatus 的逐字映射，改编排前先读。
- **恢复 = 从头重投，不恢复浏览器现场**。挂起可能跨天，保留 Playwright context 不现实；重投前表单未提交、操作幂等，且答案已回写 bio，理论上不会再卡同一字段。
- **持久化纪律**：`repository.record_delivery()` 只在终态或 SUSPENDED 时调一次，绝不在中途状态调用。

### 关键抽象（可替换的接缝）

- **平台适配层 `deliver/adapters/`** —— 只有「从职位 URL 走到表单第一页 / 判断是否要登录」这段（状态机 OPENING）因平台而异，无法通用推断，故单独切一层。`base.py` 的 `PlatformAdapter` ABC 刻意保持小；新增平台 = 写子类 + `@register_adapter` + 在 `adapters/__init__.py` 加一行 import，`select_adapter()` 不用改。**FILLING 本身仍是通用的**，不经过适配层。
- **问询通道 `questions/channel.py`** —— `QuestionChannel.ask(questions, timeout)` 抽象。CLI 实现 = 终端交互（`cli/terminal_channel.py`）；自动模式 = `AutoAnswerChannel`（答不上来直接挂起）；未来 Web = WebSocket/SSE。按页批量问询，超时挂起该职位继续下一个。
- **LLM 客户端 `llm/`** —— `LLMClient` 抽象，首个实现 `CliLLMClient` 走 headless CLI 子进程（见上「配置与密钥」）。

### 数据契约与存储（spec 决策五/九）

- **契约在 `core/contracts.py`**（pydantic 模型）：`JobRef`（唯一键 `(platform, job_id)`）、`DeliveryTask`（deliver 输入：job + resume_pdf/cover_letter_pdf 路径）、`DeliveryRecord`（输出）、`RunSummary`、`Question`/`Answer`/`BioWriteback`/`FilledField`。**增删字段必须同步改 spec 决策五**。PDF 等大文件只传路径不进对象体。`core/export_schemas.py` 把契约导出到 `docs/contracts/*.json` 供文档参考。
- **存储按数据形态分工**：`data/app.db`（SQLite，`storage/repository.py`：投递记录/凭据/挂起问题/run 记录，需按键查询去重）+ `data/bio.yaml`（`bio/store.py`，用户手工维护的单一事实源，须人类可读）+ `logs/run-<run_id>.jsonl`（`storage/run_log.py`，逐 run 追加的过程审计日志）+ `data/artifacts/<platform>/<job_id>/`（简历产物）。
- **模块解耦硬约束**：跨模块只走 core 接口（如搜索模块用 `get_delivered_job_keys()` 查已投列表去重），不直读对方存储。
- `data/`、`logs/`、`.env`、`config.toml`、简历/cover-letter **一律 gitignore**（敏感数据绝不入仓库）。

## 路线图

CLI（当前）→ Website（core 之上加 FastAPI + 前端）→ Docker 发布。search / resume 两模块待落地。spec「待续」列出的后续议题：非-Workday 平台适配抽象、bio schema、DOM 精简/选择器缓存细节、多 worker 暂停协调。
