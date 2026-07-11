# EarnBetter (Application Autofill) —— 自动填表实现调研

- 项目地址/官网: https://earnbetter.com/ ；Chrome 插件: https://chromewebstore.google.com/detail/earnbetter-ai-autofill-fo/dipmddknpfmlbdladkhofaimddikfdmc
- 类型: 闭源（SaaS + Chrome 插件，主业为求职搜索平台，附带自动填表功能）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

EarnBetter 的主产品是一个 AI 求职平台（官网 earnbetter.com/job-seekers），核心功能包括：AI 简历改写/重排版、职位匹配（号称覆盖 500 万+职位）、求职进度追踪（job tracker）、面试准备资料生成等。"Application Autofill"（自动填表）是这个平台衍生出来的一个 **Chrome 浏览器插件** 功能，定位是减少用户在 ATS 网站上重复手动填表的负担，而不是一个独立产品。

根据官方帮助文档（Help Center）描述的使用流程：
1. 用户在受支持的 ATS 网站上打开职位并点击 "Apply"；
2. 打开 EarnBetter 插件图标，从账号中保存的多份简历里选择一份要使用的简历（可选择在填表前先用 AI 针对该职位定制简历/求职信）；
3. 点击 "Autofill"，插件基于用户在 EarnBetter 账户中已存储的简历/档案信息（"based on what we have on file"）去填充页面表单字段；
4. 插件在页面底部给出"本次已填充哪些字段"的摘要，用户需要人工检查并补全缺失字段；
5. 用户点击 "Save & Continue" 翻页，对多页申请表重复以上步骤。

由此可以推测其技术实现大致是：**浏览器插件通过 content script 检测/解析当前页面 DOM 中的表单字段（input/select/textarea 等），把字段名/label 与用户在 EarnBetter 云端账户里结构化存储的简历数据（姓名、联系方式、教育、工作经历等）做匹配，然后用脚本方式向对应字段写入内容**。因为官方明确列出了具体支持的 ATS 系统（而不是宣称"支持任意网站"），推测其字段匹配逻辑很可能针对每个 ATS 平台的页面结构做了适配（每个 ATS 的表单 DOM 结构、字段命名规则不同），即存在"平台特定的选择器/适配层"，而非纯通用的、跨站点自适应的表单理解方案。公开资料中没有任何关于其内部算法、选择器策略或数据结构的技术细节，以上均为根据产品行为反推的合理猜测。

## 技术栈（推测）

- 官网/SaaS 后端：无公开技术细节，推测为常规 Web 应用（前端 + 后端 API + 数据库存储用户简历/职位数据）。
- Chrome 插件：Manifest V3 体系下的浏览器扩展，包含 content script（注入到 ATS 页面里读取/填充表单）和与 EarnBetter 云端账户同步简历数据的后台/popup 逻辑。
- AI 部分：官网明确宣传"AI 简历重写"、"AI 定制简历/求职信"、"AI 职位匹配"等功能使用 AI/LLM 技术生成文本内容；但帮助文档中关于 Autofill 本身的说明**没有提及 AI 用于表单字段识别/匹配**，只说"根据已保存的档案信息填充"。因此，"简历内容生成"这一侧明确是 AI/LLM 驱动，而"表单字段填充"这一侧是否使用 AI/LLM 做字段级语义匹配，公开资料未明确说明，无法确认。
- 以上技术栈判断均为推测，非源码或官方技术白皮书验证。

## 支持平台/网站

官方帮助文档及 LinkedIn 官方发帖明确列出目前支持的 ATS 为：
- Workday
- Taleo
- iCIMS
- Greenhouse
- Lever

官方表示这一列表在"快速扩展中"（rapidly expanding），并通过用户反馈收集新增 ATS 需求。值得注意的是，帮助文档特别提示：在 Workday 上应选择"apply manually"而不是 Workday 自带的"autofill with resume"选项，理由是 EarnBetter 插件的填充准确度优于 Workday 原生自动填充——这也从侧面印证了插件是针对具体 ATS 页面结构做了适配，而不是通用方案。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动，非全自动提交**。根据官方流程说明：
- 插件只负责"填充"字段，不会自动点击提交/下一步；
- 每次填充后会展示"已完成哪些字段"的摘要，明确要求用户"review the autofilled responses for accuracy"（人工检查填充结果的准确性）；
- 对于插件档案中没有的信息，需要用户手动录入；
- 翻页/推进到下一步（"Save & Continue"）由用户手动点击，不存在自动连续翻页直至最终提交的行为；
- 生成的简历/求职信在填表前也可选择性地由用户触发 AI 定制，属于用户主导的操作而非后台自动运行。

综上，人工介入点包括：选择简历、（可选）确认 AI 定制内容、检查/补全字段、逐页点击继续、最终提交。没有公开资料显示 EarnBetter 具备"一键从职位列表到完成提交"的全自动批量投递能力。

## 反爬虫/验证码/风控应对

在官网、帮助中心、Chrome 商店页面、第三方评测文章及 Trustpilot 用户评论中，均**未检索到任何关于 CAPTCHA 处理、反爬虫规避、IP/风控应对的公开说明**。可能的原因：
- 该插件面向的是用户在自己浏览器里以真实登录身份手动触发的操作（用户本人在自己的会话里点击"Autofill"），本质上是"辅助人工操作"而非无人值守的自动化脚本/爬虫，因此大概率不需要处理 CAPTCHA 或反机器人机制——因为整个过程仍由真人在浏览器前操作、真人点击提交。
- 没有找到任何技术文章、Reddit/HN 讨论或安全评测提到过 EarnBetter 遇到或处理验证码的情况。

此项为信息缺失，而非"确认不存在"，如需确认需要实际安装插件测试或获得官方技术说明。

## 局限性

- 仅支持官方列出的 5 个 ATS（Workday、Taleo、iCIMS、Greenhouse、Lever），不是通用型全网站autofill工具；据第三方评测文章提到"autofill 在不同网站/表单结构下效果不稳定"（"Autofill support can vary by site and form structure"）。
- 官方及第三方评测都强调 AI 生成内容（简历、求职信）"仍需人工审核编辑"，存在生成内容偏"通用化"、缺乏具体量化成果描述的问题，可能影响简历在人工筛选阶段的表现（第三方评测提到响应率约 1–3%）。
- 部分第三方评测文章（如 jobright.ai 的对比文章）声称"截至撰写时该 autofill 插件在 Chrome Web Store 并不可用"，但这与我们直接检索到的 Chrome Web Store 真实插件页面矛盾，怀疑是该竞品评测文章信息过时或存在偏差，不能作为可靠依据。
- 未找到任何独立安全评测或技术拆解文章验证其插件权限范围、数据传输方式、简历数据存储安全性等，用户隐私/数据处理细节缺乏第三方验证。
- 未找到关于批量投递吞吐量、失败率、防封号策略等运营层面的公开数据。

## 参考来源
- https://earnbetter.com/
- https://earnbetter.com/job-seekers/
- https://earnbetter.com/application-autofill/
- https://chromewebstore.google.com/detail/earnbetter-ai-autofill-fo/dipmddknpfmlbdladkhofaimddikfdmc
- https://intercom.help/earnbetter-83fd641ab32a/en/articles/10063750-how-to-autofill-job-applications-with-extension
- https://intercom.help/earnbetter-83fd641ab32a/en/articles/10063614-how-to-download-install-our-extension
- https://www.linkedin.com/posts/earnbetter_extension-ats-automate-activity-7270149212833484801-dx74
- https://jobright.ai/blog/earnbetter-review-2026-features-pricing-pros-cons-and-alternatives/
- https://resumeoptimizerpro.com/blog/autofill-job-applications-chrome-extension
- https://www.trustpilot.com/review/earnbetter.com
