# JobWizard —— 自动填表实现调研

- 项目地址/官网: https://jobwizard.ai/ ；Chrome 应用商店: https://chromewebstore.google.com/detail/jobwizard-ai-autofill-for/kbhgdbfkbgkokgkkdhnnlmkhnokjmfib
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递/自动填表工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

> 说明: "JobWizard" 为较通用的名称，可能与其他同名产品混淆。本文档确认调研对象为 jobwizard.ai（Chrome Web Store 上的 "JobWizard: AI Autofill for Workday, Greenhouse & 500+ Job Sites"，10,000+ 用户，评分约 4.5–4.6），下述内容均围绕该产品。

## 核心实现方式（推测）

- JobWizard 是一个 Chrome 浏览器扩展，用户在职位申请页面浏览时插件会自动激活（content script 常驻探测页面）。
- 官网称其可对"文本输入框、下拉菜单、复选框、自定义问答"等多种字段类型进行自动填充，推测实现方式与同类工具类似：通过 content script 扫描当前页面 DOM（表单元素、label 文本、周边上下文），将字段与用户预先保存的简历/履历数据做匹配后填入。
- 用户数据来源包括简历文件、LinkedIn 资料、以及用户在插件仪表盘中手动补充/确认过的历史问答，插件会"记住"用户此前对同类问题的回答，用于后续申请复用。
- 官网/博客均未公开任何架构图、API 说明或技术白皮书，以上均为根据产品行为与常见同类插件实现方式的推测，未经代码验证。

## 技术栈（推测）

- Chrome 扩展（Manifest V3 推测，未证实），content script + 后台/仪表盘 Web 应用（jobwizard.ai）。
- 明确使用 AI/LLM：官网与第三方测评（JobCopilot 评测）提到底层调用了类 ChatGPT 的大模型，用于生成求职信、回答开放性问题、"AI 职业顾问对话"等功能；具体模型提供商未公开。
- 用户数据（简历、职位描述）会上传/发送至其后端服务用于生成内容与匹配分数，隐私说明中承诺"不用于模型训练、不与模型提供商共享"，但这属于商业承诺而非技术验证。
- 存在 Gmail 集成（用于跟踪投递后的回复邮件），通过转发规则实现，非 OAuth 全量读取（用户可随时移除转发规则解除关联）。

## 支持平台/网站

- 官方宣传支持 Workday、Greenhouse、Lever、iCIMS、Ashby、SmartRecruiters、Taleo、Workable、BambooHR、Eightfold、Jobvite、ADP、Oracle 等主流 ATS，号称覆盖 "500+"（部分资料称 "1000+"）招聘平台。
- 同时支持在 LinkedIn、Glassdoor、Wellfound（原 AngelList）、RemoteOK 及各公司自建招聘官网（如 Apple、Google、Meta、Microsoft、Stripe、Spotify、Netflix 等）上使用。
- 具体每个平台的填表覆盖率、字段识别准确率等未见第三方公开测评数据。

## 自动化程度（全自动 / 半自动，人工介入点）

- 明确为半自动：官网多处强调"不做自动投递/批量投递"（no auto-apply / mass-apply），流程是"插件自动填表 → 用户审核 → 用户手动点击提交"。
- 官方博客甚至专门发文强调"无自动提交风险"（"Without Auto-Submit Risk"）作为卖点，与部分竞品的"一键批量海投"策略形成对比，用于降低账号被平台风控/封禁的风险。
- 人工介入点：确认/修正自动填入的字段内容、审阅 AI 生成的求职信与问答文本、最终提交动作全部由用户在招聘方官网上手动完成。

## 反爬虫/验证码/风控应对

- 公开资料（官网、Chrome 商店页、博客文章）均未提及任何 CAPTCHA 处理或反机器人检测规避机制。
- 由于产品定位是"辅助填表、人工提交"而非全自动批量投递，其对目标网站的请求模式更接近正常用户操作（浏览器内真实点击/输入），因此产品设计上可能刻意避免了触发验证码/风控的高频自动化行为，但这纯属推测，未见官方说明。

## 局限性

- 官方及第三方评测明确指出：JobWizard 不会主动"找工作"，仅在用户已打开职位详情/申请页面后才能工作，职位搜索仍需用户自行在 LinkedIn、招聘网站或公司官网完成。
- 未公开填表准确率、多页表单跳转成功率等量化数据；对复杂/非标准表单（如自定义组件、非标准下拉框）的兼容性未知。
- 免费版每日使用次数有限（10 次/天），完整功能（无限次数）需付费订阅（Plus 19.99 美元/月、Pro 39.99 美元/月）。
- 所有实现细节（DOM 识别算法、字段匹配逻辑、所用具体大模型、数据加密与存储方式等）均未公开，本调研中的"技术栈"部分为合理推测，非源码或官方技术文档验证。

## 参考来源
- https://jobwizard.ai/
- https://chromewebstore.google.com/detail/jobwizard-ai-autofill-for/kbhgdbfkbgkokgkkdhnnlmkhnokjmfib
- https://jobwizard.ai/blog/autofill-job-applications-chrome-extension
- https://jobwizard.ai/blog/best-chrome-extension-autofill-workday-job-applications
- https://jobwizard.ai/blog/how-to-autofill-ashby-job-applications-with-a-chrome-extension
- https://jobwizard.ai/blog/how-to-autofill-lever-job-applications-with-jobwizard
- https://jobwizard.ai/blog/how-to-autofill-greenhouse-job-applications-with-jobwizard
- https://jobwizard.ai/blog/job-autofill-extension-how-to-autofill-job-applications
- https://jobwizard.ai/blog/autofill-resume-speed-up-applications-without-auto-submit
- https://jobwizard.ai/blog/how-to-automate-job-application-forms-with-ai-autofill-tools-in-2026
- https://jobcopilot.com/jobwizard-ai-review/
