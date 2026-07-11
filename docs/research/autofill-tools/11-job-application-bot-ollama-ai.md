# job-application-bot-by-ollama-ai —— 自动填表实现调研

- 项目地址/官网: https://github.com/lookr-fyi/job-application-bot-by-ollama-ai （产品对外名称 "JobHuntr.fyi"）
- 类型: 开源（海外，专门做求职自动投递）—— 但见下文"局限性"，实际并非传统意义上的开源代码仓库
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 GitHub API 拉取仓库完整文件列表，确认仓库内不含任何程序源码文件，只有 Markdown 文档与图片/GIF/PDF 素材；技术细节主要来自 README/FAQ 等文档的公开表述，无法核实其真实实现）

## 核心实现方式

该仓库**不包含任何可执行的源代码**（无 `.py`/`.js`/`.ts` 等文件，无 `package.json`/`requirements.txt` 等依赖清单）。仓库根目录只有 `README.md`、`FAQ.md`、`MAC_SETUP.md`、`WIN_SETUP.md`、`PLATFORM_LETTER.md`、`PRICING.md`、`USER_LETTER.md` 等说明文档，以及一个 `src/` 目录，里面全部是截图、演示 GIF、Logo 图片和一份示例求职信 PDF（`sample_cover_letter.pdf`），没有任何源代码或流程图源文件（`flow_chart.png` 只是一张示意图片，无法看到其背后逻辑）。

因此该 GitHub 仓库本质上是一个**产品分发/引流落地页**，真正的应用是一个可下载安装的 macOS/Windows 桌面客户端（闭源二进制），仓库只是用来做营销文案、安装教程、FAQ 展示，并非"开源项目"。

根据 README 与 FAQ 等文档描述（未经源码验证，仅为厂商自述）：
- 产品会在后台 24/7 自动浏览职位、筛选与自身简历匹配的岗位（所谓"semantic filters"语义筛选）。
- 针对每个目标职位自动生成 ATS 优化的定制简历，并按需生成个性化求职信。
- 对需要回答筛选问题（screening questions）的申请，会基于用户简历/FAQ 内容生成"有依据"的回答（README 原文："Every answered question is backed by content from your resume or FAQs"）。
- 还宣称会在投递后向招聘经理/同事/猎头发送个性化联系消息（"referrals from hiring managers"）。
- 文档中提到有一个初期"人工审核期"：大约需要人工确认前 10 次投递结果，之后可切换为完全自动放飞（"Usually need review around 10, then you can let it free run"）。

## 技术栈

- 客户端形态：README 与仓库描述指出这是一个**原生 macOS 桌面应用**（早期版本描述为"native macOS desktop app"），后续版本（WIN_SETUP.md 存在）也推出了 Windows 版本，属于闭源桌面软件而非开源脚本/库。
- 浏览器自动化：README（v2.5.0 更新日志）提到"rebuilt AI browser stack that rides directly inside your Chrome profile"（即在用户自己的 Chrome 浏览器 profile 内运行的"AI 浏览器技术栈"），但**没有指明具体使用的自动化库**（如 Playwright/Puppeteer/Selenium 等一律未提及），无法验证。
- LLM 使用：项目最初的定位（也是仓库名 "by-ollama-ai" 的由来）是"全部 AI 推理通过本地 Ollama 运行，无需 OpenAI API Key"，强调隐私和免费本地推理。但根据 README 更新记录，**v3.0.0 版本起改为云端 AI 模型**，官方描述从"不需要 OpenAI Key"变为默认使用云端模型，本地 Ollama 是否仍可选配置在现有文档中未见明确说明。也就是说，仓库名称所标榜的"本地 Ollama 驱动"在当前版本中可能已经不是事实上的默认实现。
- 未见任何关于简历解析（PDF/Word parsing）、表单字段映射算法、数据存储方式的技术说明或代码。

## 支持平台/网站

README 列出支持：Indeed、ZipRecruiter、Glassdoor、Dice，以及通过"AI 驱动的网站搜索"访问企业官网职位页；v3.2.3 版本更新记录中提到新增了"通用职位网站投递能力（universal job board application capability across any website）"以及 LinkedIn 个人资料审查功能。早期该产品曾以"LinkedIn 自动投递"为主打卖点（搜索结果中的历史描述为"apply for jobs on LinkedIn — automatically, 24/7"），但当前 README 列出的主平台不含 LinkedIn 本身（LinkedIn 仅用于"profile auditing"个人资料审查）。这些均为厂商自述，未见实现细节或代码验证。

## 自动化程度（全自动 / 半自动，人工介入点）

厂商定位为"100% hands-free"（100%无需人工），但文档同时说明存在一个渐进式的人工介入阶段：新用户需要人工审核大约前 10 次投递（确认生成的简历/回答/求职信是否合适），验证无误后才建议切换到完全自动、无人值守的"free run"模式，可随时暂停或将特定公司加入黑名单。因此更准确的描述是**"半自动起步 + 可升级为全自动"**，而非从一开始就无监督全自动。

## 反爬虫/验证码/风控应对

FAQ 中提到一句笼统表述："All actions are designed to mimic human behavior, with built-in randomness... all requests are sent from your own IP address, making it extremely difficult for LinkedIn to detect any automation."（即模拟人类操作节奏、加入随机性，且所有请求都从用户自己的 IP 发出，而非集中式服务器 IP，以降低被检测风险）。README v2.5.0 更新记录中还提到"更好的隐蔽性和更少的机器人检测触发（better stealth and less frequent bot detection）"。除此之外，**没有任何关于 CAPTCHA 处理策略的说明**（既未提及打码平台，也未提及人工介入解验证码的流程），也没有速率限制、失败重试等具体机制的技术描述。

## 局限性

- **本调研最关键的发现是：该 GitHub 仓库不含任何实际源代码**，只有文档和素材文件，因此"如何实现自动填表"这一问题在源码层面完全无法回答——所有技术细节均来自厂商自己撰写的营销/说明文档，无法交叉验证真实性，也无法排除夸大宣传的可能。
- 产品实际上是**闭源收费桌面应用**（PRICING.md 中提到 v3.2.0 起有 $9.99 起的 Starter Plan 付费方案），与"全自动投递脚本"项目要求的"开源、可审查、可自行部署"的定位不完全一致，若要在自己的开源项目中借鉴或依赖，需要注意其闭源和收费性质。
- 仓库名称中的"by-ollama-ai"暗示核心卖点是"本地 Ollama 隐私推理"，但根据版本更新记录，v3.0.0 起似乎已转向云端模型，可能意味着当前默认版本不再是纯本地 LLM 方案，与项目名称产生不一致，需要用户自行在客户端设置中确认。
- 无法确认其 LLM 提示词工程、简历字段映射、表单元素识别（如何应对不同 ATS 千差万别的 DOM 结构）等具体实现方式，因为这些逻辑封装在闭源客户端内部，README/FAQ 均未披露。
- 无法验证其"人工审核约10次后可全自动"的说法在真实使用中的效果与可靠性；也没有第三方安全审计或代码审查佐证其"从用户自己IP发起请求以规避检测"的说法。

## 参考来源
- https://github.com/lookr-fyi/job-application-bot-by-ollama-ai
- https://github.com/lookr-fyi/job-application-bot-by-ollama-ai/blob/main/README.md
- https://raw.githubusercontent.com/lookr-fyi/job-application-bot-by-ollama-ai/main/README.md
- https://raw.githubusercontent.com/lookr-fyi/job-application-bot-by-ollama-ai/main/FAQ.md
- https://api.github.com/repos/lookr-fyi/job-application-bot-by-ollama-ai/contents/ （仓库文件列表，验证无源代码）
- https://api.github.com/repos/lookr-fyi/job-application-bot-by-ollama-ai/contents/src （src 目录仅含图片/GIF/PDF素材）
- https://github.com/lookr-fyi/job-application-bot-by-ollama-ai/releases
- https://news.ycombinator.com/item?id=43518064 （Show HN 讨论帖）
