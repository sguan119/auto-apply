# Jobfillr —— 自动填表实现调研

- 项目地址/官网: https://www.jobfillr.com/ ；Chrome 应用商店页面: https://chromewebstore.google.com/detail/jobfillr-autofill-your-jo/pjclfaplmlmplmdjnhpilgpnflnmdbdg
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Jobfillr 实际上是一个**非常轻量**的 Chrome 浏览器插件，而非严格意义上的"SaaS"产品——未发现独立的后台服务或账号体系。根据官网及 Chrome 商店描述：

- 用户首次使用时手动填写一份"个人信息表"（邮箱、姓名、电话、所在地、工作经历等），信息**完全保存在浏览器本地**（`chrome.storage` 或类似本地存储机制），官方明确声明"不会发送到任何服务器"。
- 页面中通过所谓"state of the art techniques"（官网原话，未展开细节）自动识别当前页面是否为求职申请表单。合理推测其实现方式是**基于规则/启发式的 DOM 表单字段识别**（如匹配 `<label>`、`name`/`id`/`placeholder` 关键词如 email、phone、first name 等），而非机器学习模型——因为没有任何服务端调用的迹象，本地规则匹配是唯一可行的技术路径。
- 用户在目标网页上点击插件图标后，插件遍历页面表单字段，将本地存储的对应字段值填入匹配到的输入框，即完成"一键填充"。

以上均为**基于公开页面描述的推测**，未能获取插件源码或逆向其打包的 JS 进行验证。

## 技术栈（推测）

- Chrome 扩展（Manifest V3 可能性较大，2024 年及以后新上架的插件多数已迁移），核心权限为"读取和更改你访问网站上的所有数据"+ `storage`。
- 插件体积极小（Chrome 商店显示约 54.57 KiB），说明代码量非常有限，不含复杂的机器学习模型或大型依赖库，纯前端 JS 实现表单检测与填充逻辑的可能性很高。
- 未发现后端 API、云函数或数据库的痕迹；未发现 OAuth/账号登录体系。

## 支持平台/网站

官网与商店页面均**未列出具体支持的 ATS 平台或招聘网站清单**（如 Workday、Greenhouse、Lever 等均未被提及）。产品定位是"通用求职表单填充器"，即针对网页上任意包含常见字段（邮箱、姓名、电话、地址等）的表单生效，而非针对特定 ATS 做深度适配。这与许多专门产品（如声称支持 Workday/Greenhouse/iCIMS 等）形成对比——Jobfillr 更像是一个通用型自动填表小工具。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动**。根据官网博客（thetalhatahir.com 的介绍文章）描述的使用流程：安装插件 → 填写一次个人信息 → 打开求职申请页面 → 点击插件图标触发填充 → **用户手动检查并提交（submit）**。

未发现任何"自动提交"功能的描述；插件的作用范围仅限于**填充表单字段**，最终提交动作由用户手动完成。这与"全自动投递"工具（可自动点击提交、跨多个职位批量投递）有明显区别。

## 反爬虫/验证码/风控应对

公开资料中**未提及任何针对 CAPTCHA、机器人检测或平台风控的处理机制**。由于该插件本质上只是模拟用户手动填写表单字段（而非自动提交或自动化浏览器操作如 Puppeteer/Selenium），也没有批量投递行为，因此大概率不会触发大多数网站的反爬虫/风控系统——但这只是基于其功能范围做出的推测，官方文档中没有正面说明。

## 局限性

- 该工具规模较小（Chrome 商店显示约 1,000 名用户，5.0 分但仅 13 条评价），未见 Reddit、Hacker News 等技术社区的独立讨论或第三方深度评测，公开可考证的信息非常有限。
- 官网和商店描述均较为营销化、简短，缺乏技术白皮书或架构说明，很多细节（如具体的字段识别算法、是否支持简历解析、是否处理下拉框/复选框等复杂控件）无法从公开资料中确认。
- 命名上容易与其他同名/近名产品混淆，例如 `jobfill.ai`（更强调"AI"和"最先进的自动填充"）、`JobFill - Autofill Smartly` 等，这些是不同的产品，本文仅针对 `jobfillr.com` / Chrome 商店 ID `pjclfaplmlmplmdjnhpilgpnflnmdbdg` 对应的 "Jobfillr" 展开调研，注意不要与近似名称产品混淆。
- 未发现该产品明确使用 AI/LLM 技术的证据；其"智能识别表单"的说法更可能是基于规则的字段匹配，而非大模型驱动的语义理解，但由于缺乏源码或技术细节披露，无法完全排除内部使用了某种轻量级匹配算法。

## 参考来源
- https://www.jobfillr.com/
- https://chromewebstore.google.com/detail/jobfillr-autofill-your-jo/pjclfaplmlmplmdjnhpilgpnflnmdbdg
- https://www.thetalhatahir.com/blog/jobfillr-autofill-job-applications
