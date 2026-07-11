# Kickresume —— 自动填表实现调研

- 项目地址/官网: https://www.kickresume.com/
- 类型: 闭源（简历生成器/求职平台，附带"求职信一键生成"浏览器插件——不存在真正的自动填表/自动投递功能）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Kickresume 的核心产品是 **AI 简历生成器 + 求职信生成器 + 简历模板库**，本质上是一个在线简历/求职信编辑与求职品牌展示平台（8M+ 用户宣传口径），并非以"自动投递/自动填表"为主打功能的工具。

其唯一与"求职流程自动化"沾边的组件是 Chrome 插件 **"AI Cover Letter Generator by Kickresume"**（Chrome 网上应用店可搜到，评分约 4.4/5）。据插件商店描述与官网页面，工作流程是：
1. 用户安装插件并登录 Kickresume 账号；
2. 浏览到某个招聘信息页面（"最流行的在线招聘平台"，未逐一列出具体网站名称）；
3. 点击插件按钮，插件读取当前页面的职位信息（职位名/职位描述）；
4. 后台调用 GPT-4 / GPT-4.1 生成一封针对该职位定制的求职信；
5. 用户在 Kickresume 界面中查看、编辑该求职信，并**手动**下载/复制/提交到目标招聘网站。

插件商店宣传语中出现过"1-click autofill millions of job applications"这类措辞，但经交叉核实（Chrome Web Store 详情页内容 + 第三方评测），该"autofill"实际指的是"一键生成求职信内容"，而**不是**把职位信息自动填入招聘网站的申请表单，也不涉及自动提交。多篇第三方评测（如 Resumly 的 Kickresume 替代品对比文章，标注"verified on the live site in June 2026"）明确指出：

> "Kickresume has no auto-apply, no form autofill and no application tracker" —— 该文将 Kickresume 描述为一个止步于"Apply 按钮之前"的工具。

因此可以判断：Kickresume **不具备**真正的职位申请表单自动填写/自动投递能力，其"自动化"仅限于 AI 文案生成（简历内容、求职信内容）。

## 技术栈（推测）

- 前端：Web 应用 + iOS/Android 移动端 App（官网未公开具体技术栈）。
- AI 能力：接入 OpenAI GPT-4 / GPT-4.1（官网 ai-cover-letter-writer 页面明确写"GPT-4.1 powered cover letter writer"，并称模型"trained and fine-tuned on thousands of real cover letters and job postings"，推测为在 GPT-4.1 基础上做了提示词/微调层，而非自研底座模型）。
- 浏览器插件："AI Cover Letter Generator by Kickresume"，Manifest 版本、具体注入脚本细节未公开（闭源，Chrome Web Store 不展示源码）。
- 简历/求职信渲染：模板引擎生成 PDF/DOCX（官网提及"9 款专业模板""ATS-friendly 格式化"）。

以上均为根据官网文案与商店描述的合理推测，未经源码或抓包验证。

## 支持平台/网站

- 官方仅笼统宣称插件"works with the most popular online job platforms"、"any job post across a wide range of industries"，**未在公开资料中列出具体支持的招聘网站名单**（如是否明确支持 LinkedIn、Indeed 等），需要用户自行在目标页面尝试插件按钮是否激活。
- 核心产品（简历/求职信生成）本身不针对特定招聘平台，是通用文档生成工具，导出后可用于任意平台投递。
- 额外提及一个 "Pyjama Jobs" 职位看板功能，用于被动匹配远程职位，但这属于职位聚合/推荐，不是自动投递。

## 自动化程度（全自动 / 半自动，人工介入点）

**纯手动 / 半自动的文案生成，不含任何投递自动化：**

- 全自动化程度：无。不存在自动登录招聘网站、自动填表、自动点击"提交/Apply"等行为。
- 半自动部分仅体现在"求职信内容生成"这一步：AI 根据职位信息自动生成初稿。
- 人工介入点（贯穿全流程）：
  - 用户需手动浏览到职位页面并手动触发插件；
  - 生成的求职信/简历内容需要用户手动检查、编辑、必要时手动重新生成；
  - 最终投递（打开招聘网站申请表单、填写字段、上传文件、点击提交）全部由用户手动完成。

## 反爬虫/验证码/风控应对

公开资料中**没有任何证据**表明 Kickresume 的插件涉及自动化网页填表、模拟点击提交等行为，因此也未见任何关于反爬虫、CAPTCHA 绕过或风控应对的技术描述——这类问题对该工具而言并不适用，因为它根本不执行自动化表单提交操作。

## 局限性

- 闭源产品，官网/商店/评测资料中不含实现细节（无 API 文档、无插件源码、无技术博客深入讲解内部机制）。
- 插件商店宣传语（如"autofill millions of job applications"）存在一定营销夸大成分，容易被误读为"自动投递"工具，实际上经多方交叉验证仅为"AI 生成求职信内容"。
- 未找到官方或第三方明确列出插件支持的具体招聘网站清单。
- 本报告结论主要依据官网营销页、Chrome Web Store 列表页与第三方评测/替代品对比文章，均为二手信息，不排除功能随版本更新而变化。

## 参考来源
- https://www.kickresume.com/en/
- https://www.kickresume.com/en/ai-cover-letter-writer/
- https://www.kickresume.com/en/cover-letter-generator-from-resume/
- https://chromewebstore.google.com/detail/ai-cover-letter-generator/khgnimehiiohfhdjbailflcfgjjlgamo
- https://www.resumly.ai/alternatives/kickresume-alternatives
- https://himalayas.app/advice/careerflow-alternatives
