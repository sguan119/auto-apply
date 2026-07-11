# AIApply —— 自动填表实现调研

- 项目地址/官网: https://aiapply.co/ （AutoApply 功能页: https://aiapply.co/auto-apply）
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

AIApply 官网及第三方测评文章描述的工作流程大致是:

1. 用户上传简历或连接 LinkedIn 账号导入个人信息，设置目标职位偏好/筛选条件（职位关键词、地点、薪资等）。
2. 系统在后台"持续扫描职位列表"（continuously scans job listings），并对每个职位计算一个"匹配分数"（match score），官方称基于"技能与职业目标的智能匹配"（smart matching based on skills and career goals），并声称匹配质量会随时间迭代改善。
3. 对匹配到的职位，系统自动生成定制化简历与求职信（声称会做 ATS 关键词优化，且"不含 AI 水印"、力求"专业自然、不显生硬"）。
4. 系统"自动填写并提交"申请，官方宣称能处理"不仅仅是一键申请"的场景，即可以"自动完成多步骤的申请表单"（complete multi-step applications automatically across supported platforms）。
5. 计费上是按"信用点"（credit）消耗的增值服务：AutoApply 功能不包含在基础订阅（约 $29/月）内，需额外购买 credit 包（如 10 个 $10、100 个 $60），每提交一次申请消耗 1 credit，credit 用尽则自动化停止。

**重要推测**: 多篇第三方评测（Adzuna、jobcopilot、autoapplier 博客等）均提到 AutoApply 的职位扫描/生成/提交流程是在"后台持续运行"，且官网未提及需要安装/依赖浏览器插件来完成 AutoApply 的表单提交这一步。同时该产品的 Chrome 插件（Chrome Web Store 上架名为 "AiApply"）在公开资料中的描述聚焦于"Interview Buddy"——即真实面试/模拟面试时实时监听问题并给出建议回答的插件，与投递自动化似乎是两个独立子系统。也就是说，AutoApply 很可能是**服务器端（云端）自动化**（类似云端 headless 浏览器/后台任务去访问职位站点并提交表单），而不是像 Simplify/LazyApply 那类工具那样完全依赖用户本地 Chrome 插件在浏览器里执行 DOM 填表操作。但官网并未公开披露具体的后端实现细节（是否用 Puppeteer/Playwright、是否直接对接各平台 API 等），这一点没有找到可验证的技术说明，只能视为基于产品行为描述的合理推测。

## 技术栈（推测）

- 未见任何公开的技术栈披露（编程语言、云服务商、自动化框架均未提及）。
- 猜测点（均无直接证据）:
  - AI 文案生成（简历/求职信/求职信优化）很可能调用第三方 LLM API（如 OpenAI/Anthropic 等），官网只泛称"AI"，未指明具体模型。
  - 职位聚合可能来自第三方职位数据 API 或自建爬虫（官网提及"continuously scans job listings"，具体数据源未知）。
  - AutoApply 的实际表单提交若为服务器端自动化，技术上大概率依赖 headless 浏览器（如 Playwright/Puppeteer）或平台专属适配脚本，但没有任何公开文章证实这一点。
  - Chrome 插件（Interview Buddy）技术上大概率是监听会议音频/字幕 + 调用 LLM 实时生成回答，具体实现未知。

## 支持平台/网站

- 第三方评测（如 remotejobassistant、jobcopilot）提到 AutoApply 覆盖 "LinkedIn Easy Apply、Indeed、以及部分公司官网招聘页（career pages）"。
- 也有评测（jobcopilot）给出相反描述，称 "AIApply 通过自己的职位聚合板块投递，而非直接对接各公司官网系统"，并举例 "Greenhouse 可用、Workday 会出错、自定义问题（custom questions）约 38% 的尝试失败"。
- 两种描述并不完全一致，说明公开资料对具体支持的 ATS/平台列表**没有统一、权威的官方清单**，官网本身只笼统提及"通过可信域名提交"（through trusted domains），未列出具体支持平台。
- 结论：支持范围**无法从公开资料中确认到精确、可靠的清单**，只能确认大概率覆盖主流职位板（LinkedIn/Indeed 等）及部分 ATS（如 Greenhouse），对 Workday 等复杂多步骤系统的兼容性据用户反馈存在明显问题。

## 自动化程度（全自动 / 半自动，人工介入点）

- 官方定位为"全自动"：用户设置偏好后，AI 自动找职位、自动生成材料、自动提交，全程在后台运行（"submits them on its own while you focus on interview prep"）。
- 但官网/客服也提到存在可选的人工介入点："you can review and approve applications before they go out if you prefer more control"——即用户可以选择开启"提交前人工审核"模式，但这并非默认/强制流程，默认路径是自动提交。
- 因此该工具属于**默认全自动、可选半自动（人工复核开关）**的模式，实际是否人人都能找到并正确开启该复核选项，第三方评测未做验证。

## 反爬虫/验证码/风控应对

- 未找到任何官方或第三方资料提及 AIApply 如何应对目标网站的验证码（CAPTCHA）、机器人检测或平台风控措施。
- 没有证据表明其使用了打码平台、人工介入验证码，或有专门的反检测技术说明。
- 第三方评测中提到的"技术问题"主要集中在**匹配准确度**（投递到语言不符/地点不符/经验等级不符的职位）以及**特定 ATS 兼容性差**（如 Workday 报错、自定义问题填写失败率约 38%），而非明确的"被平台封号/验证码拦截"类报道。
- 结论：这方面公开资料几乎是空白，无法给出可靠推测，只能如实说明信息缺失。

## 局限性

- 定价/功能透明度问题：多篇评测和 Reddit/Trustpilot 用户反馈称，AutoApply 功能不包含在基础订阅内，需额外购买 credit，导致用户"被误导"（felt misled），实际全月投递 100 份的成本可达 $68～$89，远高于宣传的 $29/月起价。
- 投递准确度问题：用户反馈出现"投递到不会讲的语言的职位""投递地点/职位级别不符"等匹配失效案例。
- 平台兼容性问题：据第三方测试（60 个真实职位样本），Greenhouse 可用，Workday 出错，自定义问题环节约 38% 失败。
- 客服/退款问题：部分用户反映功能未生效（如购买的"自动定制简历"增值项在账户中不显示）时，客服处理不佳且拒绝退款。
- 生成内容质量：AI 生成的简历/求职信在竞争激烈的高级职位上可能显得"公式化"（formulaic）。
- 技术实现细节高度不透明：官网仅有营销性描述，无 API 文档、无技术博客、无源码，具体的表单填写引擎、匹配算法、反检测机制均无法验证。

## 参考来源
- https://aiapply.co/
- https://aiapply.co/auto-apply
- https://chromewebstore.google.com/detail/aiapply/bmmijjhlpoimjbfbhnnkkkbmiibeemnf
- https://www.remotejobassistant.com/blog/aiapply-review
- https://jobcopilot.com/aiapply-review/
- https://scoutify.com/blog/aiapply-review/
- https://www.adzuna.com/blog/aiapply-review-what-works-what-doesnt-a-better-alternative/
- https://www.autoapplier.com/blog/aiapply
- https://careermax.ai/alternatives/aiapply
- https://checkthat.ai/brands/aiapply
- https://resumejudge.com/blog/aiapply-review/
- https://www.resumly.ai/answers/aiapply-review
