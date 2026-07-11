# Teal (Autofill Job Applications) —— 自动填表实现调研

- 项目地址/官网: https://www.tealhq.com/ ；自动填表功能页: https://www.tealhq.com/tools/autofill-job-applications ；Chrome 插件: https://chromewebstore.google.com/detail/teal-job-search-companion/opafjjlpbiaicbbgifbejoochmmeikep
- 类型: 闭源（SaaS + Chrome 插件，主业为求职工具箱，附带自动填表功能）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Teal 的主产品是"求职工具箱"：简历生成器（Resume Builder）、职位追踪器（Job Tracker，看板式管理投递状态）、联系人/公司管理，以及一个 Chrome 插件用于从各大招聘网站一键收藏/抓取职位信息（标题、薪资、JD 关键词等）到 Job Tracker 中。

"Autofill Job Applications" 是 2023 年以 Beta 形式推出的附加功能，官方宣传的工作流程是：用户在 Teal 平台内创建/选择一份简历，将其与 Job Tracker 中的某个职位配对，插件检测到当前页面为受支持的申请表单页时，会在 Chrome 插件图标上出现一个黄色数字提示，随后由插件自动把简历中的工作经历、教育背景、技能等信息填入表单字段，对于开放式问答题（long-form questions）则借助 GPT 生成回答草稿，用户在提交前可以查看和修改。这一套流程与市面上同类自动填表插件（如 Simplify、Teal 竞品）的公开描述基本一致，即"简历结构化数据 + DOM 表单字段映射 + LLM 生成长文本答案"。

需要特别说明的是：官方营销页面（tealhq.com 及历史 LinkedIn 推广帖）截至 2026 年仍然在线，声称该功能可"自动填充并提交申请"；但多篇 2026 年的独立第三方测评（如 resumly.ai 的 Teal 评测）明确指出，实际测试中 Teal **并不存在真正的自动投递/自动填表能力**（"Teal has zero application automation — there is no auto-apply, and there is no autofill product either — you manually click apply and fill out every job form yourself"）。这两类信息相互矛盾，本调研如实并列呈现，不做取舍判断——即无法确认该 Autofill 功能当前是否仍对普通用户开放、是否仅小范围灰度、或宣传与实际体验存在差距。

## 技术栈（推测）

- Chrome 插件（Manifest V3 大概率），content script 注入目标招聘网站页面，读取/操作 DOM 表单元素。
- 后端 SaaS（Teal 账户体系）存储用户简历结构化数据（工作经历、教育、技能等字段）。
- AI 部分官方明确提到使用 "GPT"（GPT-powered），用于根据 JD 与简历内容生成开放式问答（如"为什么想加入我们"类问题）的草稿文本；未提及具体模型版本或是否为自研模型封装。
- 未公开任何字段匹配算法细节（如是否用规则匹配 label/name 属性，还是用 AI 辅助识别表单字段语义）。

## 支持平台/网站

- 插件本身声称支持 40+ 招聘网站/职位聚合平台，官方列有专门页面持续更新支持列表，包括 LinkedIn、Indeed、Glassdoor、BuiltIn 等主流职位聚合站（主要用于"收藏/抓取职位"这一核心用途）。
- 关于 Autofill 专门支持哪些 ATS（如 Greenhouse、Lever、Workday、iCIMS 等）没有找到官方详尽清单；第三方评测普遍将 Teal 与 Simplify 对比，后者被认为在 Greenhouse/Lever/Workday 等 ATS 上有更成熟的自动填表能力，暗示 Teal 在 ATS 深度适配上不如同类竞品（此为第三方评测观点，非 Teal 官方承认）。

## 自动化程度（全自动 / 半自动，人工介入点）

- 官方宣传：选择简历 + 配对职位 → 插件自动填充结构化字段 → AI 生成长文本答案 → 用户提交前可"review and modify" → 最终由用户手动点击提交（官方文案强调"你始终可以在提交前查看和修改答案"，暗示不是无人值守全自动提交）。
- 第三方评测：认为 Teal 实际上没有自动投递能力，用户仍需手动点击 Apply 并逐项填写表单，Teal 更多扮演"职位收藏与简历管理"的角色，而非真正的自动填表工具。
- 综合来看，即便按官方最乐观的描述，该功能设计上也是半自动（辅助填充 + 人工审核 + 人工点击提交），并非无人值守的全自动批量投递；而独立评测则质疑其自动化程度是否名副其实。

## 反爬虫/验证码/风控应对

- 未检索到任何公开资料提及 Teal 对 CAPTCHA、机器人检测或 ATS 风控机制的处理方式。
- 由于该功能（按官方设计）依赖用户手动触发、逐份申请填写并人工点击提交，理论上不构成大规模自动化爬虫/批量投递行为，因而可能未面临与全自动批量投递工具类似的强风控压力；但这仅是基于产品定位的推测，无直接证据。

## 局限性

- Teal 为完全闭源 SaaS + 浏览器插件，没有任何公开源码、API 文档或技术博客披露实现细节，本调研所有实现层面的描述均为"根据官网营销文案 + 第三方评测反推"，可信度有限。
- 官方宣传与近期（2026）独立评测之间存在明显矛盾：前者声称可自动填充并快速提交申请，后者认为该功能形同虚设或已名存实亡。无法在不接触实际产品/内部代码的情况下判定孰对孰错，也无法确认功能当前的可用范围（是否仅限 Teal+ 付费版、是否仅支持特定网站等）。
- 未找到该功能针对具体 ATS（Greenhouse/Lever/Workday 等）的技术适配细节、错误处理、失败重试策略等信息。
- AI 部分仅知晓使用 "GPT"，具体模型、Prompt 设计、是否有 RAG/简历向量匹配等均未公开。

## 参考来源
- https://www.tealhq.com/tools/autofill-job-applications
- https://www.tealhq.com/tool/job-search-chrome-extension
- https://chromewebstore.google.com/detail/teal-job-search-companion/opafjjlpbiaicbbgifbejoochmmeikep
- https://www.linkedin.com/posts/tealhq_teal-autofill-apply-for-a-job-in-under-60-activity-7051564968353169409-jGdx
- https://www.linkedin.com/posts/tealhq_sneak-peek-autofill-your-online-application-activity-7048038618833059841-itMu
- https://www.resumly.ai/answers/teal-review
- https://resumeoptimizerpro.com/blog/teal-chrome-extension-alternative
- https://scale.jobs/blog/teal-vs-simplify-job-tracker-comparison
- https://www.tealhq.com/post/an-always-up-to-date-list-of-job-boards-teal-supports
