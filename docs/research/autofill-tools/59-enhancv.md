# Enhancv —— 自动填表实现调研

- 项目地址/官网: https://enhancv.com/
- 类型: 闭源（简历生成器/求职平台，附带"Chrome 扩展"——但经调研确认，该扩展是**职位追踪器（job application tracker）**，并非自动投递/自动填表工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Enhancv 的核心产品是一个**在线简历/求职信生成器**，主打视觉设计精美的简历模板，并叠加了一系列 AI 辅助功能：

- **AI 简历撰写/改写**：AI Writer / Bullet Point Generator 可将经历部分的弱表述改写为更有影响力、结果导向的语句（推测使用 LLM 生成文本，官网未公开具体模型，仅笼统提及 "advanced AI"，部分营销页面标注 "ChatGPT-Powered"）。
- **Resume Score / 简历检测**：对简历进行 27 项检查（覆盖 ATS 兼容性、内容质量、关键词匹配、HR 红线/歧视性表述、资历匹配度等 7 大类），生成评分和改进建议（推测为规则引擎+LLM 结合，非纯规则）。
- **Tailor Resume to Job Description（按职位描述定制简历）**：用户在编辑器中粘贴目标职位描述（JD），AI 将简历与 JD 做比对，生成"匹配分数"（relevance score），并给出针对经历、技能、summary 部分的具体修改建议（推测基于 LLM 的语义匹配与关键词抽取）。
- **Cover Letter Builder**：配套的求职信生成器，提供模板和大量示例。
- **AI Job Application Tracker（Chrome 扩展）**：这是本次调研重点关注的"附带自动填表功能"，但实际功能是：
  - 在 LinkedIn、Indeed、Glassdoor、Greenhouse、Workday 等主流招聘网站/ATS 页面上，**自动检测当前页面是否为职位详情页**，并弹出提示，让用户一键"保存"该职位。
  - 扩展会抓取该职位的结构化信息：职位名称、公司、职位描述全文、URL、工作类型、地点、薪资（如有）。
  - 这些信息被保存进 Enhancv 账号内的一个可视化求职看板（dashboard），用户可在其中添加备注、更新投递状态、查看每周进度汇总，并为每条记录关联对应的定制简历版本。
  - 部分第三方评测中使用了"auto-fill job details"这一措辞，但结合官方 FAQ 与产品页描述核实后，其含义是"自动把抓取到的职位信息填入 Enhancv 自己的追踪表格/看板"，**而不是自动填写目标招聘网站上的申请表单**。官网及帮助文档中**没有找到**"自动投递""一键批量申请""auto-apply""auto-submit"等相关功能描述。

综上，Enhancv **没有真正意义上的自动投递/自动填表（autofill）功能**；用户仍需手动前往各招聘网站完成投递，Enhancv 扩展仅承担"职位信息收集 + 求职进度追踪"的辅助角色。

## 技术栈（推测）

- 前端：官网及编辑器推测为现代 Web 前端框架（未公开具体技术栈）。
- Chrome 扩展：标准 Manifest V3 浏览器扩展（推测），通过内容脚本（content script）识别招聘网站 DOM 结构，抓取职位字段后通过 Enhancv 后端 API 同步到用户账号。
- AI 能力：官网营销页面出现过"ChatGPT-Powered AI Resume Writer"字样，推测底层调用了 OpenAI GPT 系列或同类大语言模型 API 用于文本改写、评分建议生成；具体模型版本、是否自研微调模型，官方均未披露。
- 后端/数据存储：闭源，无公开信息。

## 支持平台/网站

- 扩展明确列出支持的招聘网站/ATS：LinkedIn、Indeed、Glassdoor、Greenhouse、Workday，以及"其他多个主流招聘平台"（官方未列全）。
- 目前仅提供 Chrome 桌面版扩展，未见 Firefox/Edge 版本或移动端支持的公开信息。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动，且自动化程度仅限于"职位信息采集与追踪"环节，不涉及投递本身：**

- 职位信息抓取：扩展检测到职位页面后需要用户**手动点击"保存"**确认，不会静默/后台批量抓取。
- 简历定制：AI 根据 JD 生成建议后，是否采纳、如何修改仍由用户在编辑器中手动操作确认。
- 投递环节：**完全依赖用户手动前往目标网站（LinkedIn、Indeed 等）自行填写并提交申请**，Enhancv 不参与、不代为提交。
- 进度追踪：投递状态（已投/面试中/已拒等）由用户在看板中手动更新。

即：从"搜索职位→改简历→投递"这一全链条看，Enhancv 覆盖的是"改简历"和"职位/进度追踪"，完全不覆盖"自动投递"环节，且每一步都需人工确认或操作。

## 反爬虫/验证码/风控应对

未发现任何相关公开信息。由于该扩展不执行自动提交表单、不做批量/后台自动化操作（仅在用户主动点击"保存"时读取当前页面 DOM 抓取职位字段），大概率不会触发目标网站的反爬虫/验证码机制，官方资料中也未提及需要处理 CAPTCHA 或反自动化对抗的场景。

## 局限性

- **没有自动投递功能**：本次调研的核心结论——Enhancv 不是一个自动填表/自动投递工具，它是简历生成器 + 求职信生成器 + 简历评分/定制工具，外加一个"职位收藏与追踪"性质的 Chrome 扩展。若用户期望"一键批量投递"，Enhancv 无法满足，需要搭配 OwlApply、JobFill.ai、Huntr 等专门的 autofill/auto-apply 工具使用（第三方评测中多次提到此类组合用法）。
- 官网关于 AI 具体模型、评分算法细节均未公开，"27 项检查"等描述缺乏透明的评判标准说明。
- Chrome 扩展目前仅支持桌面 Chrome，跨浏览器/移动端支持不明。
- 所有信息均来自官网营销页面、FAQ 及第三方评测文章，Enhancv 为完全闭源产品，无法通过源码核实上述实现细节的准确性。

## 参考来源
- https://enhancv.com/
- https://enhancv.com/ai-resume-builder/
- https://enhancv.com/features/ai-job-application-tracker-chrome-extension/
- https://enhancv.com/features/tailor-resume-to-job-description/
- https://enhancv.com/features/resume-feedback/
- https://enhancv.com/resources/resume-checker/
- https://tooliverse.ai/tools/enhancv
- https://resumejudge.com/blog/enhancv-review/
- https://resumeoptimizerpro.com/blog/autofill-job-applications-chrome-extension
- https://owlapply.com/en/blog/best-ai-resume-builders-2025
