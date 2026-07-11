# 全自动投递脚本

一个全自动求职投递工具（开源）。整体流程：**搜索职位 → 改写简历 → 自动投递**。

三大模块高度独立，通过明确的数据契约交互：**搜索（search）**、**改简历（resume）**、**投递（deliver）**。当前仓库聚焦 **deliver** 模块的 CLI 版本落地，详见 [`docs/deliver-spec.md`](docs/deliver-spec.md)。

## 环境要求

- Python 3.11+（配置解析用 stdlib `tomllib`，需 3.11 起）。

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## 配置

非密钥行为参数放 `config.toml`，密钥放 `.env`（两者均被 `.gitignore` 排除，绝不入仓库）。仓库只提供模板：

```bash
cp config.example.toml config.toml   # 按需修改投递模式、超时、LLM 命令等
cp .env.example .env                  # 填入 LLM / CapSolver / IMAP 等真实密钥
```

未创建 `config.toml` 时，加载逻辑会自动回退到 `config.example.toml`，便于首次跑通。

### LLM 命令要求（重要）

`[llm].command` 配的 CLI 子进程，**stdout 必须是原始 PageDecision JSON 对象**
——即那一个 `{"decisions": [...], "next_action": ...}`（可选用 ` ```json ` 代码块
包裹，前后夹带解释性文字也没关系，解析器会抠出对象）。

关键坑：**不要**用 `claude -p --output-format json`。那个 `--output-format json`
输出的是 Claude Code 的结果信封
`{"type":"result","result":"…(决策 JSON 被转义成字符串塞进 result)…"}`，
真正的决策 JSON 藏在 `result` 字符串里、顶层没有 `decisions`/`next_action`，
解析器会拒收 → 每一页都 `llm_decision_error`，整条链路跑不通。默认值因此用不带
`--output-format` 的 `claude -p`（直接把模型文本回复打到 stdout，系统提示已要求
模型只回一个 PageDecision JSON 对象）。

换任何别的 CLI（Gemini CLI、本地模型包装脚本等）同理：只要它把**原始决策 JSON**
写到 stdout 即可；若某个工具默认要套一层信封，就自己写个薄包装脚本把内层决策
JSON 透出来，再把 `command` 指向那个脚本。

## 运行

```bash
deliver --help                          # 查看命令组
deliver version                         # 打印版本

deliver run --tasks tasks.example.json --manual   # 跑一次投递（默认 manual，见 config.toml）
deliver run --tasks tasks.example.json --auto --headful  # 自动模式 + 有头浏览器（调试用）
deliver answer                          # 交互式补答挂起问题（回写 bio，供下次 run 优先重投）
deliver retry workday R12345            # 手动重投单个 FAILED 职位（决策八：失败默认不自动重试）
deliver status                          # 打印投递记录 + 挂起问题清单
```

### tasks.json 格式

`deliver run --tasks` 吃一个 `DeliveryTask[]` 的 JSON 文件（`docs/deliver-spec.md`
决策五的契约；正常应由搜索 + 改简历模块产出，这里手工写一份用于本地验证），
形如 `tasks.example.json`：

```json
[
  {
    "job": {
      "platform": "workday",
      "job_id": "R12345",
      "url": "https://acme.wd1.myworkdayjobs.com/.../Software-Engineer_R12345",
      "title": "Software Engineer",
      "company": "Acme Corp",
      "score": 0.92
    },
    "resume_pdf": "data/artifacts/workday/R12345/resume.pdf",
    "cover_letter_pdf": "data/artifacts/workday/R12345/cover_letter.pdf"
  }
]
```

`cover_letter_pdf` 可省略/传 `null`。`score` 决定投递顺序（降序）；挂起职位
补答完问题后会优先于新任务重投，不需要放进这个文件（`deliver run` 每次都会
自动检查）。

## 测试

```bash
pytest
```

## 目录结构

```
src/core/    纯 Python 核心包（零界面假设）：契约 / 配置 / 存储 / 投递引擎
src/cli/     薄命令行入口层
docs/        PRD 与技术规格（deliver-spec.md 已拍定地基级技术决策）
data/        运行期数据（bio.yaml / app.db / 简历产物），已 gitignore
logs/        逐 run 的 JSONL 过程日志，已 gitignore
```

## 约定

- **核心逻辑与界面分离**：CLI 与未来 Web 后端共用 `core`，界面只是薄入口。
- **模块解耦**：跨模块只走数据契约，不产生隐式耦合。
- **敏感数据绝不入仓库**：密钥、cookie、个人简历、投递记录一律 gitignore。
