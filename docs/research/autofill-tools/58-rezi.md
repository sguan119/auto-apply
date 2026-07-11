# Rezi —— 自动填表实现调研

- 项目地址/官网: https://www.rezi.ai/ （原 rezi.io，现已统一为 rezi.ai）；Chrome 扩展: https://chromewebstore.google.com/detail/rezi-ai-autofill-job-appl/jkcdmgcaamddgioenedkdhbegbaokcek
- 类型: 闭源。核心产品是 AI 简历生成器 + ATS 简历打分工具（"Rezi Score"），**同时确实附带一个 Chrome 浏览器扩展，具备自动填表能力**（而非纯粹的简历编辑器），但填表后仍需用户手动点击"提交"，并非全自动投递。
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Rezi 的主产品是网页端简历/求职信生成器，核心卖点是 "Rezi Score"：

- 官方文档（rezi.ai/rezi-docs/the-rezi-score-explained）称，系统会从 **Content（内容与量化成果）、Format（排版格式）、Optimization（关键词与职位描述匹配）、Best Practices（文件命名、日期格式、字数等）、Application Ready（整体完整度）** 五个维度对简历打分（1-100 分），并提示官方文档还提到会扫描 "23+ 项 ATS 检查点"（文件类型、字号、关键词密度、章节标题等）。
- 关键词优化部分：用户粘贴目标职位描述（JD）后，系统会提取 JD 中的技能、工具、资格认证等关键词，与简历内容做比对，标出缺失/应补充的关键词，并按优先级分类。官方文案强调这是"不仅匹配关键词，还能理解语义"，暗示背后并非单纯字符串匹配，而是结合了某种语言模型的语义理解，但**具体算法、权重、模型架构未公开**。
- 官方页面 rezi.ai/ai-llm-info 中"技术栈"一节明确写着占位文字（"NLP-powered resume generation... using [insert AI framework / model]"），即官方目前**并未公开具体使用的 AI/LLM 模型或框架名称**，只是笼统宣称使用了 NLP/AI 技术，并有一个对话式的 "RzAI" 简历顾问 Agent。
- 官方特别声明"真实的 ATS 系统并不会给简历打官方分数"，即 Rezi Score 是自研的启发式/引导性打分，用来模拟、逼近真实 ATS 可能关注的维度，而非对接任何真实招聘平台的 ATS 系统 API。

以上均为根据官网及帮助文档文字推测，未见到任何算法伪代码、模型名称或论文披露。

## 技术栈（推测）

- 网页端主产品：SaaS 平台（React 等前端 + 后端服务，具体未知）。
- AI 能力：官方笼统描述为"NLP-powered"，未指明底层大模型（可能是自研模型、也可能调用第三方 LLM API，如 OpenAI/Anthropic 等，但官方页面未列出，仅留占位符）。
- 浏览器自动填表：以 **Chrome 扩展**形式实现（Manifest V3 时代的扩展，需登录 Rezi 账号），扩展页面自我描述为 "AI Autofill job applications, job tracker, resume import"。
- 扩展会读取用户在 Rezi 网页端保存的简历/档案数据，并声明处理"个人身份信息（PII）"与"身份验证信息"，未见公开的具体 DOM 操作/表单填充技术细节（如是否使用内容脚本 content script 注入、坐标点击还是表单字段语义匹配）。

## 支持平台/网站

- 官方宣传：可在 **Workday、Greenhouse、Lever 及"数千个其他"** 主流 ATS/招聘网站上一键自动填表。
- 未见到官方提供的完整支持网站清单或名单式文档，"数千个"为营销性表述，具体覆盖率、匹配规则未知。
- 扩展同时支持从 LinkedIn 个人资料导入信息，反哺生成/完善简历。

## 自动化程度（全自动 / 半自动，人工介入点）

- 属于**半自动**：扩展会自动识别求职申请表单并用已保存的档案/简历数据填充各字段，但根据官方扩展描述"Your information fills itself in. You just hit submit."——最终提交动作仍由用户手动点击完成，不存在无人值守的全自动批量投递。
- 第三方评测（如 fastapply.co 的对比软文）进一步指出，Rezi 定位为"简历构建工具"，认为用户需要自己找职位、手动上传简历，暗示其自动化程度低于专门的"auto-apply"类工具（如 FastApply、Simplify Copilot 等）。但该说法与 Rezi 官方 Chrome 扩展"一键自动填表"的宣传存在一定出入，可能是竞品软文刻意弱化竞争对手能力，也可能是该扩展的自动填表能力有限（例如仅适用于部分标准表单字段，遇到复杂/自定义字段仍需人工补全）。**此处存在信息矛盾，以官方 Chrome 商店描述为准，但实际自动化覆盖率无法在不安装使用的情况下验证。**
- 结论：Rezi 的自动填表功能定位介于"纯手动投递"和"全自动批量投递"之间，人工介入点至少包括最终提交、以及可能的字段核对/补全。

## 反爬虫/验证码/风控应对

- 未检索到任何官方或第三方资料提及 Rezi 扩展有专门的反爬虫、CAPTCHA 破解或规避风控机制的设计。
- 由于该功能定性为"辅助填表 + 人工提交"，且并非无人值守的批量自动化工具，产品形态上可能本身就不太需要应对验证码/反机器人检测（因为关键操作由真人在浏览器中触发），但这纯属推测，官方未做任何相关技术说明。

## 局限性

- Rezi 官方及第三方资料均未公开自动填表功能的具体实现细节（如是否用规则匹配表单字段名、是否使用 AI 辅助识别非标准字段、扩展权限清单等），Chrome 网上应用店页面本身也未列出详细权限项。
- "Rezi Score"的具体打分算法、关键词匹配/语义理解的技术路径（规则引擎 vs. 向量匹配 vs. LLM 调用）均未公开，官方仅以营销性语言描述。
- 官方"AI/LLM info"页面中的技术栈说明存在明显占位符文本，表明官方并未认真披露底层模型信息，可信度和透明度较低。
- 扩展目前 Chrome 网上应用店收录的安装量约 1,000（评分 4.7/5，14 条评价），体量较小，公开的独立技术评测/逆向分析文章很少，多数信息来自官方营销文案与转载性质的博客对比文章，需谨慎对待其准确性。
- 第三方评测对"是否具备真正自动投递能力"存在分歧（官方称支持一键自动填表；部分竞品博客称其本质仍是手动投递工具），未能找到独立、可信的技术验证来源澄清。

## 参考来源
- https://www.rezi.ai/
- https://www.rezi.ai/rezi-docs/the-rezi-score-explained
- https://www.rezi.ai/ai-llm-info
- https://www.rezi.ai/tools/resume-checker
- https://chromewebstore.google.com/detail/rezi-ai-autofill-job-appl/jkcdmgcaamddgioenedkdhbegbaokcek
- https://www.rezi.ai/rezi-docs/importing-your-linkedin-profile
- https://blog.fastapply.co/fastapply-vs-rezi-review-and-comparison-2026
- https://enhancv.com/blog/rezi-review/
