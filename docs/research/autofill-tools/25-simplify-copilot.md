# Simplify Copilot —— 自动填表实现调研

- 项目地址/官网: https://simplify.jobs/copilot ；Chrome 商店: https://chromewebstore.google.com/detail/simplify-copilot-autofill/pbanhockgagggenencehbnadejlgchfc
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

官方宣传为"一键 Autofill"：用户先在 Simplify 网站上建立个人档案（联系方式、教育、工作经历、技能、简历文件、作品集链接等），安装 Chrome/Firefox 插件后，在受支持的招聘页面上插件会弹出悬浮窗，点击"Autofill"按钮即可自动填充表单。官方文案称"Copilot detects the form automatically and starts matching fields using your Simplify profile"，即插件在页面内检测表单字段并与用户档案数据做匹配后填入。这与同类工具（Jobright、JobCopilot 等）的通用做法一致：**Chrome 扩展 content script 注入目标页面 DOM，识别 `<input>`/`<select>`/`<textarea>` 等字段（通过 name/id/label/placeholder 等文本线索），与用户档案字段做匹配后写入值**——但 Simplify 官方公开材料中并未披露具体的字段匹配算法、选择器规则或是否使用了独立的 DOM 规则库，这部分是基于该品类工具近乎普遍的实现路径做的推测，未见源码或技术白皮书证实。

## 技术栈（推测）

- 前端：Chrome/Firefox 浏览器扩展（Manifest V3 大概率），通过 content script 在目标网页 DOM 中运行；后台/popup 脚本负责与 Simplify 云端账户同步档案数据。
- 后端：Simplify.jobs 云端 SaaS，托管用户档案、简历文件、投递记录（dashboard）。
- 官方描述插件为"AI-powered"，并明确提供 **AI 简历/求职信生成**、**基于职位描述的开放式问题（如"Why do you want this role?"）AI 回答生成**、**简历关键词与职位描述比对（缺失关键词提示）**等 LLM 相关功能。但对于"标准字段自动填充"这部分，官方措辞更偏向"档案数据匹配"而非明确宣称使用 LLM 做 DOM 字段理解；是否对标准字段填充也使用 LLM 辅助匹配，公开资料未明确说明。
- 未找到关于具体所用模型（如是否调用 OpenAI/Anthropic API）的公开技术细节。

## 支持平台/网站

官方及第三方评测口径较为一致：宣称支持 **100+ 招聘平台/ATS**，明确点名的包括 Workday、Greenhouse、Lever、iCIMS、Taleo、Ashby、Avature、SmartRecruiters 等主流 ATS，以及"数千个招聘网站和公司官网职位页"。未见到详尽的完整白名单或适配层技术说明。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动**——官方帮助文档明确说明该工具 **不会自动提交申请**："you always review everything before submitting it yourself"。即插件只负责自动填充表单内容，最终的"提交/Submit"按钮点击由用户手动完成，这也是该类目工具的普遍设计（避免误投、避免触发平台反自动化机制）。

## 反爬虫/验证码/风控应对

公开资料中未找到 Simplify Copilot 关于 CAPTCHA、人机验证或反爬虫/反机器人应对机制的任何官方说明或第三方技术分析。由于其"半自动、需人工点击提交"的设计，遇到验证码等环节大概率是交由用户手动处理，而非插件自动绕过；但这一点缺乏公开证据支持，只能存疑标注为未知。

## 局限性

- 闭源产品，官方及第三方评测/博客均停留在功能层面的介绍，未见任何技术白皮书、逆向分析或源码泄露披露具体 DOM 检测算法、字段匹配规则或 Manifest 权限清单细节。
- Chrome Web Store 页面本身未能在本次调研中直接抓取到完整的权限声明文本（如是否为"读取和更改您在所有网站上的数据"），只能确认官方文案承认"需要访问页面权限以实现 autofill 功能"。
- 是否对复杂/动态渲染表单（如 React/Shadow DOM 组件化的 Workday 表单）有特殊适配逻辑，缺乏公开信息，只能视为该品类工具的共性推测。
- 本文所有实现层面的判断均为基于官网、帮助中心、Chrome 商店描述及第三方评测文章的合理推测，不构成对其真实代码实现的验证。

## 参考来源
- https://simplify.jobs/copilot
- https://chromewebstore.google.com/detail/simplify-copilot-autofill/pbanhockgagggenencehbnadejlgchfc
- https://help.simplify.jobs/articles/1749022-installing-and-setting-up-copilot
- https://help.simplify.jobs/articles/9660493-using-copilot-with-simplify
- https://www.chromeanalyzer.com/content/blog/simplify-copilot-autofill-job-applications-behind-the-code-how-the-chrome-extension-really-works/
- https://jobcopilot.com/simplify-jobs-review/
- https://jobright.ai/blog/simplify-copilot-review-2026-features-pricing-and-top-alternatives/
