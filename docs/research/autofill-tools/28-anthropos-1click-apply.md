# Anthropos 1-Click Apply —— 自动填表实现调研

- 项目地址/官网: https://anthropos.work/ （产品页：https://anthropos.work/autofill-job-applications-1-click-apply ）
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Anthropos 是一个先建档、后填表的求职自动化工具，与许多同类插件思路一致：

1. 用户先在 Anthropos 网站上创建"职业档案"（career profile），方式是导入 LinkedIn 数据或上传简历（CV/Resume），也可手动补充信息，其中有一个"Introduction"（自我介绍）字段会被用来提升 AI 回答质量。
2. 安装官方 Chrome 插件（Anthropos 1-Click Apply）后，插件会在用户访问受支持的招聘网站/ATS 投递页面时注入一个悬浮小组件（widget）。
3. 点击组件触发"1-click"填表：插件读取用户档案中的结构化数据（姓名、联系方式、教育、工作经历等），通过 DOM 操作把这些值写入页面上对应的表单字段。
4. 对无法直接映射的开放式问答题（如"为什么想加入这家公司"），插件调用 AI（官方明确提到使用 OpenAI 的 GPT）生成候选回答，供用户使用或编辑。
5. 官方页面没有提到"自动提交"能力；表述是"尽可能多地自动填充字段"，未被自动填充的字段仍需用户手动完成，暗示最终提交动作由用户手动点击完成。

以上流程均来自官网/第三方目录站描述，未见任何技术白皮书或代码，具体的字段匹配算法（选择器规则库、模糊匹配、LLM 结构化输出等）无法从公开材料判断，只能确认"用户档案数据 + 页面表单"是核心输入输出。

## 技术栈（推测）

- 前端/插件：Chrome Extension（Manifest 版本未知），推测使用 content script 向 ATS 页面注入 DOM 填充逻辑 + 一个悬浮 UI 组件。
- 后端：Anthropos 自有 SaaS 后台，托管用户档案数据；具体后端语言/框架未公开。
- AI 能力：官方博客与第三方目录站均提到"uses GPT by OpenAI"来回答开放式问题及生成求职信（cover letter），推测是通过 OpenAI API 做文本生成，而非自研模型。
- 以上均为推测，Anthropos 未公开任何架构图、API 文档或技术博客细节。

## 支持平台/网站

- 官方仅笼统宣称"整合 7 个主流 ATS 系统之一"（不同来源分别写"7 of the most popular ATS systems"），并表示"每周/每月都在新增支持"，但公开资料中未列出具体 ATS 名单（如 Workday、Greenhouse、Lever 等），无法逐一确认。
- 官网提供反馈渠道（info@anthropos.work），供用户报告未被支持的投递页面，说明覆盖范围是渐进式扩展、非全量覆盖。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动，且以"辅助人工投递"为主，而非无人值守全自动批量投递：

- 自动部分：结构化字段（姓名、联系方式、教育经历、工作经历等）自动填充；开放式问答题由 AI 生成草稿。
- 人工介入点：
  - AI 生成的开放式回答需要用户审核/编辑（第三方评价中有用户提醒"ALWAYS proof-read your generated texts"）。
  - 无法自动填充的字段需手动补全。
  - 未见"自动提交"功能的任何公开描述，最终点击"提交申请"大概率仍由用户完成。

## 反爬虫/验证码/风控应对

公开资料（官网、博客、第三方目录站、Trustpilot 摘要、chrome-stats/extpose 页面）均未提及任何关于 CAPTCHA 绕过、反爬虫对抗或风控规避的技术说明。由于该工具是"用户主动点击触发的表单填充"而非后台无人值守批量投递，大概率不需要专门处理 CAPTCHA/反爬（用户本人在浏览器里操作、逐个职位手动确认提交），但这只是基于产品形态的推测，并非官方确认。

## 局限性

- 该 Chrome 插件已于 2025 年 9 月 17 日从 Chrome 网上应用店下架（第三方插件监测站 extpose.com 记录为"因轻微政策违规下架"），目前是否仍可通过官网直接分发安装包不确定。
- 观察到 chrome-stats.com 上同一插件 ID（nkppcikijhohdiaenfmbkcoibdmpkiop）的标题已变为"Anthropos: AI Job Simulations for Skill Development"，暗示产品可能已从"自动投递"转型/侧重到"AI 职业技能模拟/学习路径"等其他功能，1-Click Apply 是否仍是其主推功能存疑。
- 历史安装量较小（chrome-stats 记录约 748 次安装，16 条评分均分 4.25/5），最后一次更新版本号 0.26.1（2024-08-23），活跃度和维护状态存疑。
- 未找到任何 Reddit/HN 上的深度技术讨论或逆向工程分析，第三方信息大多是转载官网文案的目录站（toolify.ai、creati.ai、xix.ai、softonic 等），信息重复度高、增量价值有限，且部分页面因反爬无法直接抓取正文。
- 支持的具体 ATS 名单、字段匹配算法、是否有失败重试/异常处理机制等均无公开细节，本文所有"推测"标注内容均不构成对其真实实现的确认。

## 参考来源
- https://anthropos.work/autofill-job-applications-1-click-apply
- https://anthropos.work/blog/1-click-apply-is-now-available-apply-to-any-job-in-minutes/
- https://anthropos.work/blog/autofill-your-job-applications-using-ai/
- https://anthropos.work/blog/how-to-use-chatgpt-to-find-a-job/
- https://extpose.com/ext/nkppcikijhohdiaenfmbkcoibdmpkiop
- https://chrome-stats.com/d/nkppcikijhohdiaenfmbkcoibdmpkiop
- https://anthropos-autofill-your-job-applications.en.softonic.com/chrome/extension
- https://www.toolify.ai/tool/anthropos-autofill-your-job-applications
- https://creati.ai/ai-tools/anthropos-autofill-your-job-applications/
- https://xix.ai/tool/anthropos-chrome-extension.html
- https://www.trustpilot.com/review/anthropos.work
