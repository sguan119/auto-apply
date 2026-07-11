# OwlApply —— 自动填表实现调研

- 项目地址/官网: https://owlapply.com/ （Chrome 插件商店页：https://chromewebstore.google.com/detail/owlapply-ai-autofill-job/pbglgmekagjpmeiifbhkdbabcinndalm）
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

根据官网说明与 Chrome 商店描述，OwlApply 的工作流程大致为：

1. 用户先在插件/账号中一次性录入个人资料（联系方式、教育背景、工作经历、技能、自定义问答对），并可上传/生成多份简历版本。
2. 用户浏览到目标职位的投递页面（ATS 表单）后，点击插件的 "Autofill" 按钮。
3. 插件通过内容脚本 (content script) 读取当前页面的表单字段，识别字段类型（文本框、下拉框、多选、文件上传等），并将其与本地/云端保存的资料做匹配，逐字段填充。
4. 对于开放式的"筛选问题" (screening questions)，插件调用 AI（LLM）读取问题文本并结合简历数据生成一段针对性回答，填入对应文本框。
5. 表单填充完成后，**由用户自行检查、修改并手动点击投递按钮提交**——官方文档明确表示"你需要在提交前review，插件只负责填充，你来核实并提交"。

以上均为根据官网/商店文案与第三方评测推测的实现方式，未见任何技术架构图或源码级说明。

## 技术栈（推测）

- Chrome 扩展（Manifest V3 大概率，商店listing 未直接标注版本号细节），核心是浏览器插件 + content script 做 DOM 读取/填充。
- 后端为 SaaS 账号体系，个人资料"加密存储在 OwlApply 账号中，可跨设备同步"（官网博客原文），意味着存在云端数据库，插件与云端 API 通讯获取/同步用户资料。
- AI 部分（简历打分、职位匹配度、筛选问题回答生成、AI 简历/求职信生成）大概率通过调用第三方或自研 LLM API 实现，官网未披露具体模型（如是否基于 GPT/其他基座模型）。
- 插件本身体积较小（商店信息约 737 KiB），说明复杂计算（AI 生成、匹配打分）应在云端完成，插件端主要负责 DOM 操作与数据传输。

## 支持平台/网站

官网与商店列出的支持平台包括：Workday、Lever、Greenhouse、iCIMS、Taleo、LinkedIn、Indeed、Glassdoor，以及"其他任意标准 ATS/HTML 表单"（官方宣称覆盖"数千个平台"）。这属于官方宣传口径，实际覆盖率/兼容质量未经第三方系统性验证；有评测提到"复杂门户网站有时表现不稳定，额外功能并非在每个招聘门户都能正常工作"。

## 自动化程度（全自动 / 半自动，人工介入点）

- 官方文档明确定位为**半自动**：插件负责"读取字段 + AI 生成筛选问题答案 + 自动填充表单"，但**不会自动提交**。用户需要在填充完成后手动检查每个字段、编辑内容，再自行点击"提交"按钮完成投递。
- 未发现任何"睡觉时自动批量投递"式的全自动无人值守宣传语，营销上更强调"把 15 分钟的重复填表工作压缩到 2 分钟内"（即提效工具，而非无人值守 agent）。
- 与此同时，第三方评测（resumejudge.com）批评其"更看重投递数量而非质量"，暗示该工具鼓励用户快速批量点击投递，但产品机制本身仍保留人工点击提交这一步。

## 反爬虫/验证码/风控应对

公开资料（官网、Chrome 商店、第三方评测）中**未发现任何关于反爬虫、CAPTCHA 破解或平台风控应对机制的说明**。由于其自动化止步于"填表"而非"自动提交/批量遍历投递"，产品形态上对 CAPTCHA/风控的依赖需求本就低于全自动 agent 类工具；没有证据表明其内置了验证码绕过能力。

## 局限性

- 闭源 SaaS，核心匹配/生成逻辑、云端架构、数据处理细节完全不透明，以上均为对外文案与第三方评测的转述与合理推测。
- 官方"90% 时间节省""数千平台支持"等属于营销宣传语，未经独立测评机构的系统性验证。
- 第三方评测反馈：AI 生成内容"较为模板化，容易导致千篇一律"；复杂 ATS 门户中表单识别/填充可能失败或不完整。
- 未查到任何技术博客、逆向工程分析或安全研究对其插件内部实现（如 DOM 选择器策略、字段匹配算法细节）做深入剖析，因此本报告中"技术栈"一节的判断仅停留在合理推测层面。

## 参考来源
- https://owlapply.com/en
- https://owlapply.com/en/ai-tools/job-application-autofill
- https://owlapply.com/en/blog/how-to-use-owlapply-extension-for-your-job-applications
- https://owlapply.com/en/blog/owlapply-extension
- https://chromewebstore.google.com/detail/owlapply-ai-autofill-job/pbglgmekagjpmeiifbhkdbabcinndalm
- https://resumejudge.com/blog/owlapply-review/
- https://medium.com/@eddyenos1/owlapply-review-can-ai-solve-your-job-search-problems-0a905f09fbfb
