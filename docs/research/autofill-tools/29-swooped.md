# Swooped —— 自动填表实现调研

- 项目地址/官网: https://swooped.co/ （自动填表专题页: https://swooped.co/job-application-autofill-extension ；帮助中心: https://help.swooped.co/ ；Chrome 商店: https://chromewebstore.google.com/detail/swooped-job-search-tracke/nafkdopjabijmpmfnogbnccgipnocljm）
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Swooped 是一个"简历/求职信生成 + 职位追踪 + 自动填表"一体化的 SaaS 产品，核心是一个 Chrome 插件 + 云端账户系统。根据官网、帮助中心与 Chrome 商店页面的公开描述（均为厂商自述，非源码验证）：

- 用户先在 Swooped 网站/插件中建立"个人资料（profile）"，包含简历内容、联系方式等结构化信息。
- 在受支持的招聘网站上，插件会**自动检测并弹出**（"fully integrated" 网站会自动唤起插件窗口），将页面上的申请表单字段与用户 profile 中的数据做**字段映射（form field mapping）**，生成"Live autofill preview"供用户在提交前查看。
- 对于开放式问答题（如"为什么想加入我们"），官网提到会提供"Drafted"（AI 起草）的申请回答，结合职位描述（JD）与用户资料生成针对该职位定制的简历、求职信及问答草稿。
- 对于插件未深度集成的网站（"partially supported"），用户需要**手动**将职位描述复制粘贴进插件，并手动点击生成文档，属于半自动模式。
- 官方材料没有披露具体的字段匹配算法、DOM 解析方式或后端架构细节，仅停留在产品功能描述层面。

## 技术栈（推测）

- 前端：Chrome 扩展（Manifest V3 大概率，未证实），网页端为 SaaS Web App。
- 后端：云端账户系统 + AI 生成服务（用于简历评分、简历/求职信生成、问答起草），推测调用某个大语言模型 API，但官方未指明具体使用哪家模型（OpenAI/Anthropic/自研等均未公开）。
- 数据存储：用户 profile、职位追踪记录存储在其云端（Job Tracker 功能），涉及个人信息（PII）与网页内容（Chrome 商店隐私说明中列出的数据收集类别）。
- 以上均为根据公开页面功能推断，无法从源码验证具体技术选型。

## 支持平台/网站

- **深度集成（"fully integrated"，插件会自动弹出）**：LinkedIn、Indeed、Monster、Greenhouse、Lever、Workable。
- **官网自动填表页宣传**支持范围更广，提到 "LinkedIn, Indeed, Workday, Greenhouse, Lever, Workable and 50+ other boards"，但未列出完整的 50+ 名单。
- **部分支持（"partially supported"）**：其他招聘网站/自建 ATS 页面，需要用户手动触发插件（点击插件图标）或手动复制粘贴职位描述后再生成文档，不具备自动表单映射能力。

## 自动化程度（全自动 / 半自动，人工介入点）

整体判断为**半自动、以人工复核为终点**的设计：

- 插件负责"发现职位→抓取/映射表单字段→预填充→AI 生成定制文档（简历/求职信/问答）"这一段的自动化。
- 官网和帮助文档明确强调"lets you review before submission" "Review packet before submit"，即**不会自动点击最终提交按钮**，需要用户人工确认后自行提交。
- 对未深度集成的网站，连预填充这一步都需要用户手动介入（手动创建 tracked job、手动生成文档），自动化程度进一步降低。
- 结论：Swooped 定位是"辅助/加速投递"工具，而非无人值守的全自动海投机器人；这与很多求职自动化工具强调"人在回路（human-in-the-loop）"以规避账号风险的做法一致。

## 反爬虫/验证码/风控应对

公开材料（官网、帮助中心、Chrome 商店页面）**未提及任何关于反爬虫、CAPTCHA 处理、IP/代理轮换或平台风控规避的内容**。由于该产品坚持"人工点击提交"而非全自动批量投递，其对目标网站的自动化行为强度本身较低（主要是读取/填充表单，而非模拟批量注册或高频提交），可能因此较少触发平台的反自动化机制，但这只是基于产品设计的推测，官方未做任何相关说明。

## 局限性

- 官方公开资料主要是市场宣传性质的产品页面和帮助中心 FAQ，缺乏技术白皮书或架构说明，因此关于表单字段识别算法、AI 模型选择、后端实现等技术细节均无法证实。
- 第三方评测（如 autogpt.net、declom.com 等）指出 AI 生成的简历/求职信内容有时会"编造"过于具体的经验描述，需要用户人工核对修改，说明其字段/内容生成并非完全可靠，用户仍需承担审核责任。
- 未找到该插件的技术拆解文章、逆向工程分析或安全研究报告；本次调研未能获取其 Manifest 权限清单的完整内容或网络请求层面的实现细节。
- Chrome 商店页面提及会收集"个人身份信息"和"网站内容"，但具体数据流转、是否发往第三方 AI 服务等未详细披露。

## 参考来源
- https://swooped.co/job-application-autofill-extension
- https://swooped.co/
- https://help.swooped.co/en/articles/9247065-how-to-use-the-chrome-extension
- https://help.swooped.co/en/articles/9261545-can-i-use-swooped-to-customize-resumes-and-cover-letters-for-jobs-on-other-job-boards
- https://chromewebstore.google.com/detail/swooped-job-search-tracke/nafkdopjabijmpmfnogbnccgipnocljm?hl=en
- https://chrome-stats.com/d/nafkdopjabijmpmfnogbnccgipnocljm
- https://www.trustpilot.com/review/swooped.co
- https://autogpt.net/ai-tool/swooped-ai/
- https://declom.com/swooped
- https://skywork.ai/skypage/en/Swooped-Careers-An-AI-Powered-Job-Search-Deep-Dive-(2025-Review)/1976138982057766912
