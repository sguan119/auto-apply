# NeuraClick / NeuraCV —— 自动填表实现调研

- 项目地址/官网: https://neuracv.com/ 、扩展页 https://neuracv.com/extension 、Chrome 商店 https://chromewebstore.google.com/detail/neura-click/djpbkodeookpmpaconfchmngjojjjloc
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递/自动填表工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

NeuraCV 是一个 AI 简历构建/优化 SaaS 平台，NeuraClick 是其配套的 Chrome 插件。根据官网及商店描述：

- 用户先在 NeuraCV 平台上传/解析简历（PDF 上传后被结构化解析存储），并登录 NeuraClick 插件账号。
- 浏览职位页面时，插件会"扫描"当前页面的职位描述（JD），与用户简历内容做比对，生成一个实时的简历-JD 匹配分数（match score）。
- 提供 "Magic Rewrite" 功能：分析 JD 后，AI 自动改写/调整简历要点（bullet points）以匹配所需技能和关键词，生成针对该职位定制的简历版本。
- 在职位申请表单页面点击插件图标后，插件检测表单字段并自动填充（autofill），号称对 Workday 等复杂多步骤表单的字段做了专门优化，官网宣称字段映射准确率达 "99%"（厂商自述数字，未经第三方验证）。
- 官网及博客明确将其定位为 "表单填充助手（form-filling assistant），而非爬虫/机器人（not a scraper bot）"，并做类比 "像是求职申请领域的密码管理器（password manager）"——即只做字段填充建议，不会代替用户抓取/自动提交。

以上均为基于官网文案的技术实现推测，无法确认底层是内容脚本（content script）直接操作 DOM，还是配合远程 AI 服务做字段语义匹配；大概率是 Chrome 插件 content script 扫描表单 DOM + 调用云端 LLM API 做字段值/简历内容生成的组合模式。

## 技术栈（推测）

- Chrome 扩展（Manifest V3 大概率，未验证），通过 content script 注入目标页面读取/填充表单 DOM。
- 后端 SaaS（neuracv.com）负责简历解析、存储、AI 生成（Magic Rewrite、JD 匹配打分），插件与后端之间应通过账号登录态通信。
- Chrome Web Store 页面显示该扩展体积仅 352 KiB、版本号 0.0.1（截至 2026-01-05 更新），用户数极少（约 35 名用户，1 条评分，5.0 分）——说明这是一个规模很小、仍处早期阶段的产品，公开技术细节非常有限。
- 开发者信息：NEURAFORGE.AI，注册地英国 Bournemouth，Chrome 商店中标注为 "非交易者"（non-trader，适用欧盟消费者权益免责声明）。

## 支持平台/网站

官网宣传支持的招聘网站/ATS 系统（厂商自述，未逐一验证）：

- 通用招聘网站：LinkedIn、Indeed
- 企业级 ATS：Workday（重点优化对象，有专门落地页）、Oracle Cloud Careers、Taleo（含所有 Taleo 驱动的招聘门户）、iCIMS、Greenhouse、Lever
- 官网还声称能覆盖"数千个其他网站"（thousands of other sites），但未提供具体清单。
- 需注意：NeuraCV 平台自身的"免费 ATS 简历评分器"支持的系统列表（Workday、Greenhouse、Taleo、iCIMS、Lever、SmartRecruiters、SuccessFactors、Oracle Cloud Careers、BambooHR、Jobvite、Ashby）比 NeuraClick 插件实际宣传支持自动填表的平台列表更长，两者不完全等同——简历打分功能覆盖面 ≠ 自动填表实际支持面。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动，且官方明确强调"人工在环（human-in-the-loop）"：

- 官网原文（博客/FAQ 检索结果）明确指出："NeuraClick does not send applications on its own — it suggests text in fields while you stay on the page, and you read the form, edit anything that looks off, and press submit yourself."（NeuraClick 不会自主提交申请——它只在你停留于该页面时为字段填充建议文本，你需要检查表单、修改不合适的内容，并自行点击提交。）
- 因此该工具的定位是"填充辅助 + 人工审核 + 手动点击提交"，与 LazyApply 等宣称"全自动批量投递"的工具形成对比（官方博客中甚至将自身作为 LazyApply 的"更安全"替代方案来营销）。
- 账号注册环节（创建 ATS 账号）据称也可被自动填充，加速流程，但同样非强制自动提交。

## 反爬虫/验证码/风控应对

- 未检索到任何官方文档、FAQ、博客或用户评论中提及具体的反爬虫、CAPTCHA 绕过或风控应对机制。
- 结合其"非自动提交、需人工点击"的产品定位推测：由于最终提交动作由真人用户手动完成，该工具可能刻意避开需要处理 CAPTCHA/自动提交的高风险环节（这类环节通常是触发平台反爬虫机制的关键点），从而在设计上降低被封号/触发风控的概率。但这仅为基于产品定位的合理推测，并无直接证据。
- 未找到第三方技术分析、逆向工程文章或安全研究涉及该插件。

## 局限性

- 该产品規模很小（Chrome 商店仅约 35 名用户、版本号 0.0.1、无第三方评测或技术拆解文章），公开可获得的信息高度依赖厂商自身网站文案，缺乏独立验证来源（如 Reddit/HN 深度讨论、逆向工程博客、安全研究等均未检索到）。
- 官网关于"99% 准确率"等具体数字均为厂商自述，无第三方数据佐证。
- 部分官网页面（如 /faq、/extension、/extension/autofill/workday）因反爬保护返回 403，未能直接抓取原始页面文本，本报告中的相关内容来自搜索引擎摘要缓存，可能存在遗漏或轻微失真。
- 未能确认插件所需的 Chrome 权限清单、Manifest 版本、是否有 Firefox/Edge 版本等具体工程细节。
- 由于是新兴/小众产品，其功能和产品策略可能变化较快，本报告内容仅反映调研时间点（2026-07-06）的公开信息快照。

## 参考来源
- https://neuracv.com/extension
- https://neuracv.com/extension/job-application-autofill
- https://neuracv.com/extension/autofill/workday
- https://neuracv.com/extension/autofill/linkedin
- https://neuracv.com/extension/autofill/indeed
- https://neuracv.com/extension/autofill/taleo
- https://neuracv.com/extension/autofill/icims
- https://neuracv.com/faq
- https://neuracv.com/resources/resume-checker
- https://neuracv.com/resources/blog/5-top-free-lazyapply-alternatives-in-2026-boost-your-productivity
- https://neuracv.com/blog/best-free-lazyapply-alternatives
- https://chromewebstore.google.com/detail/neura-click/djpbkodeookpmpaconfchmngjojjjloc
- https://www.trustpilot.com/review/neuracv.com
