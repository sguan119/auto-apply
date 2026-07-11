# JobFill / Autofill Smartly (jobfill.ai) —— 自动填表实现调研

- 项目地址/官网: https://jobfill.ai/ ；Chrome 商店: https://chromewebstore.google.com/detail/autofill-smartly-jobfill/kbgfilncepjeoodogmebahnloidgaibg ；Firefox 版: https://addons.mozilla.org/en-US/firefox/addon/autofill-smartly-jobfill/
- 类型: 闭源（SaaS + Chrome/Firefox 插件，专门的求职自动投递/自动填表工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

官方定位为"最强大的 Chrome 自动填表插件"，不仅限于求职场景，也覆盖注册、预订等通用表单。核心机制是 **Chrome 扩展 content script 注入目标页面**，检测页面中的 `<input>`/`<select>`/`<textarea>` 等表单元素并自动填入用户档案数据。第三方评测明确提到该插件能处理 **Shadow DOM（包括多层嵌套的 Shadow DOM 结构）**以及 `<slot>` 元素中的字段标签，这说明其字段检测逻辑并非简单的 `document.querySelector`，而是对 Shadow DOM 场景做了专门穿透处理——这类适配对 Workday 等大量使用 Web Components/Shadow DOM 的 ATS 系统尤为关键。

插件提供"Auto-Capture"功能：可手动或自动从用户已经填写过的表单中**学习/捕获**新的字段-数值对应关系，形成自定义填充规则，用于覆盖默认档案信息或适配非标准字段命名，这一自定义规则库和"从用户输入学习"的机制是其区别于纯静态字段映射工具的特点。

官方还宣传"auto-trigger 模式"：进入目标表单页面后无需点击插件图标，页面加载完成即自动触发全页填充。这属于填表触发时机上的自动化，但与是否自动提交申请（点击最终 Submit）是两回事（见"自动化程度"一节）。

以上关于 Shadow DOM 穿透、字段检测算法细节、Auto-Capture 学习逻辑的具体实现方式，均未见官方技术白皮书或源码披露，仅为基于第三方评测/官方博客文案的合理推测。

## 技术栈（推测）

- 前端：Chrome/Firefox 浏览器扩展，通过 content script 在目标网页 DOM（含 Shadow DOM）中检测并填充表单；popup/后台脚本负责与 jobfill.ai 云端账户同步数据。
- Chrome 商店权限声明包含 `host_permissions: *://*/*`（用于跨站点检测和填充表单）、`unlimitedStorage`（本地存储捕获的数据）、`cookie`（访问 jobfill.ai 的 cookie 用于登录鉴权/加密）。
- 后端：jobfill.ai 云端 SaaS，用户通过 Google 账号登录，托管用户档案、简历文件、职位收藏与投递记录。
- 官方及第三方资料明确提及 **AI 相关功能**：读取用户上传的 PDF 简历并用 AI 提取工作经历、教育背景、技能等结构化信息用于填表（而非仅依赖用户手填的档案表单）；此外还有"根据职位描述定制/裁剪简历（Resume Tailoring）""职位描述智能摘要（JD Summarization）""职位申请跟踪（Job Tracker）"等 AI 驱动功能。是否对"开放式问答字段"（如"Why do you want this job?"）做 LLM 生成式回答，公开资料中未见明确证实。
- 未找到任何关于具体调用哪家 LLM（OpenAI/Anthropic/自建模型等）的公开技术细节。

（注：Chrome 商店中还存在另一个名称非常相似但主体不同的扩展 "JobFill AI: Auto Apply to Jobs & Fill Applications"（ID: feldflnnmndgnpdpkfhpdjbphfimhaff），其描述明确宣称"解析 PDF 简历 + 生成式回答开放式问题 + 一键填充"。该扩展与 jobfill.ai 官网主推的 "Autofill Smartly - JobFill" 是否为同一开发者/同一产品的不同分发渠道，未能从公开资料中确认，本文以 jobfill.ai 官网及其对应的 "Autofill Smartly - JobFill" 商店页面为主要调研对象，特此注明避免混淆。）

## 支持平台/网站

官方插件权限为 `*://*/*`，即理论上适配任意网站的表单，并非局限于固定 ATS 白名单。官方博客明确提到近期更新"新增支持 SmartRecruiters 平台"，并在讨论复杂表单时点名 Workday、Taleo 属于"表单结构复杂"的代表性 ATS（暗示其对这类平台做过专门适配/测试，但未明确列出完整支持列表）。未找到官方给出的完整 ATS 白名单或"支持 XX+ 平台"的量化宣传语。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动，填表自动化程度较高，但未见"自动提交申请"的功能宣传。** 公开材料（官网、Chrome 商店描述、官方博客）均只描述"自动填充表单字段"这一动作，包括"auto-trigger 模式：页面加载后无需点击即自动填满整页表单"，但没有任何一处提及该工具会代替用户点击最终的"Submit/提交申请"按钮。据此推断：人工介入点应在于最后确认并手动点击提交，工具负责的是"填",不负责"交"——但由于未找到官方对此的明确声明（不像 Simplify Copilot 那样在帮助文档中白纸黑字写明"你需要自己点击提交"），这一点只能标注为**推测，未经官方文本直接证实**。

## 反爬虫/验证码/风控应对

未找到 JobFill/Autofill Smartly 关于 CAPTCHA、人机验证或反爬虫/反机器人应对机制的任何官方说明或第三方技术分析。由于该工具设计上似乎只做"填表"而不做"提交"，遇到验证码环节大概率交由用户自行处理；但公开资料对此没有任何直接描述，只能存疑标注为未知。

## 局限性

- 闭源产品，官网为前端渲染的 SPA，本次调研中多次尝试直接抓取官网首页/定价页/文档页正文时，页面内容大部分未能被有效提取（渲染内容依赖 JS 执行），因此定价方案（是否分免费版/付费版、付费版解锁哪些自动化深度）**未能确认**，本文不做臆测。
- 官方博客、Chrome 商店描述、第三方评测站点提供的信息均停留在功能宣传层面，没有任何技术白皮书、逆向分析文章或源码泄露披露具体的字段检测算法、DOM 选择器规则、Shadow DOM 穿透实现或 Auto-Capture 学习机制的技术细节。
- 是否自动提交申请、是否有 CAPTCHA/风控应对机制，均未见官方或第三方给出明确说法，本文仅作合理推测并已在正文中标注置信度。
- 第三方评测中提到该插件存在"针对特定网站的检测/触发问题、偶发 bug 导致基础填表失败"等负面反馈，说明其字段检测并非对所有网站/所有表单结构都稳定可靠。
- 存在同名/相似名称的另一款 Chrome 扩展（"JobFill AI: Auto Apply to Jobs & Fill Applications"），本文已在"技术栈"一节中注明区分，但无法完全排除两者在数据/技术上的关联性。

## 参考来源
- https://jobfill.ai/
- https://jobfill.ai/docs
- https://jobfill.ai/docs/blog/tags/chrome-extension/
- https://jobfill.ai/docs/blog/tags/best-job-autofill-extension-2026/
- https://jobfill.ai/docs/blog/tags/job-application-autofill-tool/
- https://chromewebstore.google.com/detail/autofill-smartly-jobfill/kbgfilncepjeoodogmebahnloidgaibg
- https://chromewebstore.google.com/detail/jobfill-ai-auto-apply-to/feldflnnmndgnpdpkfhpdjbphfimhaff
- https://chrome-stats.com/d/kbgfilncepjeoodogmebahnloidgaibg
- https://addons.mozilla.org/en-US/firefox/addon/autofill-smartly-jobfill/
- https://crozdesk.com/software/jobfill
