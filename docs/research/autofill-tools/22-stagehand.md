# Stagehand (Browserbase) —— 自动填表实现调研

- 项目地址/官网: https://github.com/browserbase/stagehand ；文档: https://docs.stagehand.dev ；官网: https://stagehand.dev ；Python 版: https://github.com/browserbase/stagehand-python
- 类型: 开源（通用浏览器/Agent自动化框架，非专为求职，MIT License）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（未克隆仓库读取源码，而是通过 GitHub API 读取了 README.md 全文，并通过 WebFetch 抓取了 docs.stagehand.dev 上 `v3/basics/act`、`v3/basics/observe`、`v3/basics/agent`、`v3/first-steps/introduction`、`v3/first-steps/installation`、`v3/integrations/playwright`、`v3/configuration/models` 等官方文档页面的渲染内容做归纳；未实际安装运行或阅读 TypeScript 源码，部分细节——尤其是 act()/observe() 内部是否使用无障碍树、如何将 LLM 输出转成 selector 的具体算法——文档未明确说明，故标注为"推测"而非"源码验证"）

## 核心实现方式

Stagehand 的定位是"用自然语言 + 代码混合控制浏览器"的框架，核心提供四个原语：

1. **`act(instruction)`** —— 用自然语言描述单个动作（如 `"click the add to cart button"`），由 Stagehand 解析后执行点击/填写/滚动/导航等操作。文档 (`v3/basics/act`) 明确写道："The first time an action runs, it's cached. Subsequent runs reuse the cached action without LLM calls."（动作首次执行会被缓存，后续运行复用缓存动作，不再调用 LLM），并建议先用 `observe()` 探测候选动作再执行，以提高可靠性。
2. **`observe(instruction)`** —— "discover actionable elements on a page and returns structured actions you can execute or validate before acting"（发现页面上可操作的元素，返回可在执行前校验的结构化动作列表）。返回值是 `Action[]`，每个 Action 包含 `description`（人类可读描述，如 "Learn more button"）、`method`（如 `click`/`fill`）、`arguments`（参数）、`selector`（XPath 或 CSS 选择器，支持 shadow DOM 路径，如 `xpath=/html[1]/body[1]/shadow-demo[1]//div[1]/button[1]`）。文档明确"自动处理 iframe 穿透和 shadow DOM 元素，无需额外配置"，暗示其底层对 DOM/无障碍树做了较深的解析，但具体是否直接依赖浏览器无障碍树（accessibility tree）API，官方文档页面未给出明确说明。
3. **`extract(instruction, schema)`** —— 结合 Zod schema 从页面提取结构化数据，例如从 GitHub PR 页面提取 `author`/`title` 字段。
4. **`agent()`** —— 面向"多步骤、端到端自主执行"的更高层封装，见下文"自动化程度"一节。

**"先 observe 后 act，然后缓存复用"是其区别于纯 Agent 框架的核心设计**：README 原文强调"Go from AI-driven to repeatable workflows: Stagehand lets you preview AI actions before running them, and also helps you easily cache repeatable actions to save time and tokens"，以及"Write once, run forever: Stagehand's auto-caching combined with self-healing remembers previous actions, runs without LLM inference, and knows when to involve AI whenever the website changes and your automation breaks."——即：动作被解析为确定性的 selector + method + arguments 之后可持久化缓存，重放时不再消耗 LLM token，只有当页面结构变化导致缓存动作失效时才重新触发 LLM 推理（"self-healing"）。使用 Browserbase 时，`observe()` 的结果还可以走服务端缓存（`serverCache` 参数），重复调用直接命中缓存、不消耗 token。

对于表单填写场景，文档还提到一个安全机制：`observe()` 支持传入 `variables`，返回的 Action 中会用 `%variableName%` 占位符替换敏感值（如密码），从而可以在真正执行前先审查/校验动作，而不必把敏感数据实际暴露在 LLM 调用或日志中——这对求职表单中填写身份证号、手机号等敏感字段有直接参考价值。

## 技术栈

- 语言：TypeScript（README 显示仓库 83.4% 为 TypeScript），另有独立维护的 Python 实现 `stagehand-python`。
- **浏览器控制层**：值得注意的是，Stagehand（尤其是当前 v3）**并非简单"构建在 Playwright 之上"**。README 中的最新示例代码写道"Stagehand's CDP engine provides an optimized, low level interface to the browser built for automation"，即其底层是自研的、直接基于 Chrome DevTools Protocol (CDP) 的引擎，而非以 Playwright 为核心依赖。文档 `v3/integrations/playwright` 页面说明两者关系是"可选集成"而非"依赖关系"："Stagehand v3 can work seamlessly with Playwright, allowing you to use Playwright's `Page` objects directly with Stagehand's AI-powered methods"，其集成方式是"Connect Playwright to Stagehand's browser instance using Chrome DevTools Protocol (CDP)"——也就是说 Playwright 可以作为客户端连接到 Stagehand 已经在管理的浏览器实例上，两者通过 CDP 协作，而不是 Stagehand 内部依赖 Playwright 的 API 来做元素定位和点击。**这与早期版本"基于 Playwright 封装"的描述已经不同，说明架构在 v3 有过重大调整**，本调研未能确认具体是从哪个版本开始迁移。
- **LLM 接入**：通过 Vercel AI SDK 统一接入多家模型提供商。文档 `v3/configuration/models` 列出"一等公民"（First-Class）支持：Google (Gemini)、Google Vertex（实验性）、Anthropic (Claude)、OpenAI (GPT)、Azure OpenAI、Cerebras、DeepSeek、Groq、Mistral、Ollama（本地开源模型）、Perplexity、TogetherAI、xAI (Grok)；并声明"Amazon Bedrock, Cohere, all first class models, and any model from the Vercel AI SDK is supported"以及可通过 Vercel AI SDK 接入自定义端点。若使用 Browserbase 的 **Model Gateway**，可用一个 API Key 统一调用多家模型（示例：`openai/gpt-5`、`anthropic/claude-sonnet-4-6`、`google/gemini-3-flash-preview`）。
- **Agent / Computer Use 模型**：`agent()` 额外支持 Computer Use Agent (CUA) 模式，可调用 Anthropic Claude（多个变体）、Google Gemini、Microsoft Fara-7b、OpenAI computer-use-preview 系列等专门的"计算机操作"模型，这类模型基于截图坐标点击而非语义 DOM 操作。
- 依赖/生态：`create-browser-app` 脚手架用于快速创建项目；支持通过 `pnpm add "github:browserbase/stagehand#<branch>&path:/packages/core"` 从指定分支安装；提供 Next.js/Vercel 官方集成指南。
- 许可证：MIT License（Copyright 2025 Browserbase, Inc.）。

## 支持平台/网站

不针对特定招聘网站/ATS 做适配，是通用网页自动化框架，理论上可在任意基于 Chromium 的网页上运行（文档提及"works with all Chromium-based browsers"）。官方 README 示例演示的是访问 GitHub 页面、点击仓库、提取 PR 信息等通用场景，没有出现任何求职/招聘相关的官方示例或模板；Browserbase 官网的 Templates 页面（`browserbase.com/templates`）提供"真实世界自动化案例"，但本次调研未确认其中是否包含求职投递类模板。

## 自动化程度（全自动 / 半自动，人工介入点）

- **三层可选自动化程度**，由开发者按需选择："Choose when to write code vs. natural language: use AI when you want to navigate unfamiliar pages, and use code when you know exactly what you want to do"——即定位介于"纯手写 Playwright/Selenium 代码"（完全确定性、需要开发者维护每个 selector）和"纯 Agent 自主决策"（灵活但不可预测）之间。
- **`act()`/`observe()`/`extract()`** 是"半自动"用法：每一步具体做什么仍由开发者在代码里编排（例如按顺序调用 act 完成"填姓名→填邮箱→点提交"），只是每一步"怎么定位元素、怎么执行"交给 LLM 决定，且支持先 `observe()` 预览动作、再决定是否真正执行，方便人工在自动化流程中插入审核点。
- **`agent()`** 是更高自动化程度的模式，支持三种子模式：
  - **Computer Use Agent (CUA)** 模式："fully autonomous browser workflows"，基于截图坐标点击的专用模型，自主完成多步任务；
  - **DOM Mode**："works with any LLM"，用语义化 DOM 动作而非坐标，仅 TypeScript 支持；
  - **Hybrid Mode**：同时提供坐标工具和 DOM 工具给模型自行选择，需要 Claude/GPT-5.4/Gemini 3 系列等模型。
- **人工介入点**：文档未提供显式的"暂停等待人工确认"API（不同于 Browser Use 的 `pause()/resume()`），但提供了工程化的控制手段：`AbortController` 可随时中止任务；`maxSteps` 参数（默认 20）限制 agent 自主执行的步数上限；支持把复杂任务拆成多次 `execute()` 调用、在调用之间保留上下文，从而让开发者在两次调用之间插入人工审核逻辑。整体上，Stagehand 更强调"开发者编排 + AI 执行单步"的半自动模式，而非"一句话丢给 agent 全自动跑完"，`observe()`→缓存校验→`act()`的设计本身就是鼓励"先看后做"的人工把关思路。

## 反爬虫/验证码/风控应对

Stagehand 开源库本身不包含反爬虫或验证码破解逻辑，这部分能力被明确划给了 Browserbase 云服务：
- 文档 (`v3/first-steps/introduction`) 指出"生产环境部署到 Browserbase 可增加 session replay、Agent Identity、action caching、captcha handling 和零基础设施的 Functions 部署"。
- 根据 Browserbase 文档站（`docs.browserbase.com/features/stealth-mode`）内容：Browserbase 通过与验证码服务商合作**自动求解 CAPTCHA**（默认对所有 session 开启，通常耗时 5-30 秒，可通过 `browserbase-solving-started`/`browserbase-solving-finished` 控制台事件监测进度，也可通过 `solveCaptchas: false` 关闭；对非标准验证码支持指定自定义 CSS 选择器定位图片/输入框）。
- 反检测思路并非单纯"伪装躲避"，而是"合法化"策略："Verified 会话"使用 Browserbase 自研维护的 Chromium 浏览器，具有能被反爬虫合作方识别的"真实浏览器指纹"，从而减少验证码触发、提高成功率；同时支持通过 Cloudflare Web Bot Auth、AgentKit 在 World Chain 上的人类验证等"身份分级认证"机制让网站显式放行自动化访问；此外还支持接入住宅/数据中心代理。文档也强调应遵守目标网站的服务条款和 robots.txt。
- 综上，**验证码求解、代理池、"可信"浏览器指纹均是 Browserbase 付费云服务的能力**，若完全自托管开源版 Stagehand（本地 Chrome/CDP，不接 Browserbase），则不具备这些反爬虫对抗能力，需自行接入第三方方案。

## 应用于求职投递场景的可行性简评

**优点**：
- `act()`/`observe()`/`extract()` 的组合天然贴合"表单填写"场景：`observe()` 可以先扫描出申请表单里所有可交互字段（输入框、下拉、单选、上传按钮），`act()` 逐个字段填充，`extract()` 可用于提取投递结果状态或职位详情页信息反哺"搜索/改简历"模块。
- 首次运行后的"动作缓存 + self-healing"机制对批量投递同一 ATS 模板的多个职位（如同一 Workday/Greenhouse 租户的不同岗位页面）有天然优势：结构相同的申请页只需第一次消耗 LLM token 生成动作，之后可近似"零 LLM 成本"重放，直到页面结构变化才重新触发推理，这比每次都全量调用 LLM 的纯 Agent 方案更省成本、更稳定。
- `observe()` 支持的 `variables`/占位符机制，可以在把敏感个人信息（身份证、手机号等）交给 LLM 之前先做脱敏校验，契合"开源项目不应泄露个人敏感数据"的项目约束。
- 支持自选 LLM（含本地 Ollama），不强制绑定某一家模型供应商，便于按成本/合规需求切换，也便于该项目保持"核心逻辑与界面分离""模块解耦"的设计原则——Stagehand 可以只作为"投递"模块内部的一个可替换执行引擎。

**局限**：
- 求职网站/ATS（LinkedIn、Workday、Greenhouse 等）普遍有较强的反爬虫与行为检测机制，而这部分能力在开源自托管路径下基本缺失，若不接入 Browserbase 付费云服务（验证码求解、可信指纹、代理），直接在真实招聘网站上做批量自动投递容易被拦截或触发风控。
- 框架定位是通用浏览器自动化，没有任何求职场景专属的字段语义理解（如"EEO 问询""是否需要签证担保"等招聘表单常见字段类型），需要在其之上自建业务适配层。
- v3 架构从"基于 Playwright"转向"自研 CDP 引擎 + 可选 Playwright 集成"，官方文档和第三方教程可能存在新旧版本描述不一致的情况，本调研未能确认这一架构切换发生的具体版本节点。
- 本次调研仅通过 WebFetch 抓取官方文档渲染内容做归纳，未克隆仓库阅读 TypeScript 源码，因此"act()/observe() 内部具体如何定位元素（是否使用浏览器无障碍树 API、是否结合截图）"这一关键技术细节未能得到源码级确认，官方文档页面本身对此也未做详细说明。

## 局限性

- 未实际安装运行 Stagehand 或在真实招聘网站上做投递测试，所有结论均来自 README 与官方文档页面的文本描述。
- 未能获取 act()/observe() 判定"可交互元素"和生成 selector 的底层算法细节（例如是否使用 CDP 的 Accessibility 域），只能从文档措辞（如"自动处理 iframe 和 shadow DOM"）间接推断其对 DOM 结构有较深处理。
- Browserbase 相关的验证码/反爬虫细节来自 Browserbase 文档站而非 Stagehand 自身文档，两者虽同属一家公司但功能边界（哪些能力开源库自带、哪些必须依赖 Browserbase 云服务）在官方资料中不总是界限分明，存在被过度推断的风险。
- 求职投递相关的具体可行性评估为调研者基于通用框架能力做出的推测，并非官方给出的用例或案例验证。

## 参考来源
- https://github.com/browserbase/stagehand
- https://raw.githubusercontent.com/browserbase/stagehand/main/README.md
- https://docs.stagehand.dev/v3/basics/act
- https://docs.stagehand.dev/v3/basics/observe
- https://docs.stagehand.dev/v3/basics/agent
- https://docs.stagehand.dev/v3/first-steps/introduction
- https://docs.stagehand.dev/v3/first-steps/installation
- https://docs.stagehand.dev/v3/integrations/playwright
- https://docs.stagehand.dev/v3/configuration/models
- https://docs.browserbase.com/features/stealth-mode
- https://docs.stagehand.dev/llms.txt
