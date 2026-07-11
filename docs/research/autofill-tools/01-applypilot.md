# ApplyPilot —— 自动填表实现调研

- 项目地址/官网: https://github.com/Pickle-Pixel/ApplyPilot
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已直接读取 README 及 `src/applypilot/apply/` 下的 `chrome.py`、`launcher.py`、`prompt.py` 源码内容，非仅凭描述推测）

> 命名歧义说明：GitHub 上至少有两个同名/近似名项目——`Pickle-Pixel/ApplyPilot`（本篇调研对象，AGPL-3.0，Python，聚焦"发现职位→打分→改简历→自动投递"全流程自动化）和 `eliornl/applypilot`（自托管的求职辅助工具，侧重简历改写/面试准备，非自动投递为主）。另有 applypilot.app、useapplypilot.com 等商业网站与本开源项目无关联，官方 README 明确声明"不隶属关系"。本调研仅针对 `Pickle-Pixel/ApplyPilot`。

## 核心实现方式

ApplyPilot 并未使用传统的"selenium/playwright 脚本 + 硬编码选择器"模式，而是**用 Claude Code（Anthropic 的 Agentic CLI）作为投递执行的"大脑"**：`src/applypilot/apply/launcher.py` 通过 subprocess 以如下方式拉起 Claude Code 会话：
`claude --model <model> -p --mcp-config <path> --permission-mode bypassPermissions --output-format stream-json`，并挂载 Playwright MCP Server（用于浏览器操作）与一个只读 Gmail MCP Server（用于处理邮箱验证等场景）。职位描述、经过针对性改写的简历文本（tailored resume）会被拼接进 prompt，通过 stdin 传给 Claude Code；随后 Claude Code 在会话中自主感知页面结构、决定填哪个字段、点击提交，整个"填表逻辑"是由 LLM 在运行时推理完成的，而不是预先写死的表单字段映射代码。

## 技术栈

- 语言：Python 3.11+（`pyproject.toml`，PyPI 打包）
- 浏览器自动化：Chrome DevTools Protocol（CDP）。`chrome.py` 负责为每个并发 worker 启动独立的 Chrome 实例（`BASE_CDP_PORT + worker_id`，从 9222 起），管理 profile 克隆、进程树清理等；Claude Code 通过 **Playwright MCP Server**（README 中说明"运行时自动为每个 worker 配置，无需手动设置"）连接到这些 CDP 端口来实际执行浏览器操作，而不是项目自己直接调用 Playwright/Puppeteer API。
- 依赖：`python-jobspy`（职位抓取）、`pydantic`（数据校验）、`tls-client`/`requests`（HTTP）、`markdownify`、`regex`；LLM 侧支持 Gemini（免费额度）、OpenAI、以及本地模型（Ollama/llama.cpp），投递阶段需要 Claude Code CLI。
- 需要 Node.js 18+（供 `npx` 运行 Playwright MCP Server）。

## 支持平台/网站

- 职位来源（Discover 阶段）：Indeed、LinkedIn、Glassdoor、ZipRecruiter、Google Jobs 共 5 个主流招聘平台。
- 企业招聘门户：48 个 Workday 雇主门户 + 30 个企业官网直投页面（direct career sites）。
- 投递环节本身不依赖针对具体 ATS（Workday/Greenhouse/Lever 等）写死的选择器规则，而是由 Claude Code 在页面上实时识别表单结构后填写，理论上具备跨 ATS 的通用性，但实际成功率依赖 LLM 对页面的理解能力。

## 自动化程度（全自动 / 半自动，人工介入点）

整体是**全自动**流程：6 阶段流水线（Discover → Enrich → Score → Tailor → Cover Letter → Auto-Apply）全部无人工干预运行，Auto-Apply 阶段由 Claude Code 自主完成"打开表单→填字段→上传简历/求职信→回答筛选题→提交"，成功后输出 `RESULT:APPLIED` 标记。
提交前有一个"自查"环节：prompt 中要求 Claude Code 在点提交前"take a snapshot and review EVERY field on the page. Verify all data matches the APPLICANT PROFILE and TAILORED RESUME"，但这是 **agent 自身的自我核查，不是人工确认**。
项目提供 `--dry-run` 选项，可让流程走完但不点击最终提交按钮，供用户人工抽查表单填写效果，但默认模式下不需要人工介入即可真正提交申请。

## 反爬虫/验证码/风控应对

- 验证码：集成 CapSolver（付费第三方打码服务）API。prompt 中明确规则：任何验证码出现（hCaptcha/reCAPTCHA/Turnstile/FunCaptcha）时必须先"CAPTCHA DETECT"识别类型和 sitekey，再"CAPTCHA SOLVE"（createTask → poll → inject）调用 CapSolver；检测顺序上优先判断 hCaptcha 而非 reCAPTCHA。未配置 CapSolver key 时，验证码相关申请会"优雅失败"（标记为 `RESULT:CAPTCHA`），不会阻塞整体流程。
- 反检测（针对 Chrome 而非针对具体网站的风控算法）：`chrome.py` 中做了大量"降低自动化痕迹"的处理——每个 worker 独立 Chrome profile（可克隆用户已登录的真实 Chrome profile 以复用 cookie/会话）、禁用密码保存/自动填充/通知/崩溃恢复弹窗、拦截摄像头麦克风权限请求、抑制"是否恢复页面"提示等，目的是让并发跑的多个 Chrome 实例看起来更接近真实用户环境、减少被网站识别为自动化脚本的信号。
- 未见到专门针对具体招聘网站限流策略（如请求频率控制、IP 轮换/代理池）的代码说明；README/源码中没有提到显式的速率限制或代理管理机制。

## 局限性

- 依赖 LLM 实时理解页面结构来完成填表，而非稳定的选择器映射，可能导致同一网站不同版本表单下成功率不稳定，且强依赖 Claude Code/Anthropic API 可用性与费用。
- CAPTCHA 处理依赖第三方付费打码服务 CapSolver，未配置时对应网站会直接放弃该次投递。
- 目前只调研了 README 与 `apply/` 目录下 4 个核心文件（chrome.py、launcher.py、prompt.py，另有 dashboard.py 未细读），未逐行审查 discovery/enrichment/scoring/wizard 等其他模块的实现细节。
- "全自动无人工确认提交"意味着一旦 profile.json 信息有误，可能会批量投出包含错误信息的申请，风险需用户自行把控（`--dry-run` 为唯一的人工把关手段）。

## 参考来源
- https://github.com/Pickle-Pixel/ApplyPilot
- https://github.com/Pickle-Pixel/ApplyPilot/blob/main/README.md
- https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/apply/chrome.py
- https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/apply/launcher.py
- https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/apply/prompt.py
- https://dev.to/picklepixel/i-built-an-ai-agent-to-apply-to-1000-jobs-while-i-kept-building-things-3j64
