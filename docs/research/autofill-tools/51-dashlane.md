# Dashlane —— 自动填表实现调研

- 项目地址/官网: https://www.dashlane.com/
- 类型: 闭源（密码管理器，表单自动填充为副产品功能，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Dashlane 早期采用的是**规则式（rule-based）语义引擎**——由工程师手写规则识别表单字段，官方博客承认这种方式"只能在访问量最高的少数网站上保持可靠"，对长尾网站命中率差。

此后 Dashlane 将 autofill 引擎迁移为**机器学习驱动**（官方称为 "autofill engine powered by machine learning"），核心变化：

- 不再靠人工规则，而是用大量"人工标注过的网站样本"训练模型，让引擎自主学会识别字段类型，号称字段识别更快（约 15 毫秒识别一个页面）、准确率据称提升约 7.6%。
- 近期（2025-2026）Dashlane 进一步引入 **GenAI + 自建标注体系**：
  - 提出了一套内部标准 **SAWF（Semantically Annotated Web Forms）**，用于统一定义表单类型（登录、注册、支付、收货、账单、搜索等）与字段类型（用户名、密码、邮箱、地址子字段等），并表达多步表单（如"先填邮箱再填密码"）之间的层级关系。
  - 通过内部工具 "Vortex for Dashlaners"，让 Dashlane 员工自愿提交浏览中遇到的、引擎尚未识别的表单样本（已脱敏），汇总进内部数据集（Vortex 数据库）。
  - 用 GenAI（大模型）**离线**对这些收集到的表单样本做字段打标 / 分类（依据 SAWF 标准），因为打标发生在"收集到的表单数据集"上而非用户个人数据上，官方强调因此可以放心使用更强的云端大模型而不涉及隐私问题。
  - 打标后的数据集用于训练一个"高度优化、体积小"的生产模型，最终部署进浏览器扩展和移动端 App，在本地毫秒级完成推理，不与服务器通信、不上传用户数据。

字段检测/抓取的技术手段（推测）：引擎扫描页面 DOM，既识别标准 `<form>`，也识别"伪表单"（没有 form 标签但功能上组成一组输入框的字段集合）；抓取两类信号——技术属性（HTML 标签、input type、name 属性等）和人类可读内容（label、placeholder、周围文本），供本地小模型判断字段语义。

选中一个字段（如"名"）后，引擎会联动填充相关字段（姓、生日等）；地址、信用卡等场景下，若同类信息有多条（如多个地址、多张卡），会弹出候选列表供用户选择要填哪一条。2026 年 3 月的更新称 autofill 变得"更精准克制"，从"点一下填满整个表单"改为"只填与所选条目直接相关的字段"。

以上关于 SAWF、Vortex、GenAI 标注流程、模型本地推理等细节，均来自 Dashlane 官方博客（"How AI Powers Dashlane's Autofill Without Compromising Privacy"）的公开描述，**未经源码或内部实现验证**，实际字段匹配逻辑、模型结构、规则与 ML 的融合比例等仍是黑箱。

## 技术栈（推测）

- 浏览器扩展（Chrome/Firefox/Edge/Safari，以及基于 Chromium 的 Opera/Brave）内置本地推理模型，用于页面字段分类与自动填充，属于闭源商业实现。
- 移动端 App（iOS/Android）内置类似的 autofill 能力，并提供"App 内自动填充"（iOS 系统级 AutoFill 扩展、Android Autofill Framework 集成）以及自带的安全浏览器。
- 训练侧（云端，非产品运行时）：内部标注工具 Vortex + GenAI 打标 + 机器学习训练管线，产出的模型下发到客户端。
- 官方强调生产环境的字段识别是"设备本地推理"，不联网、不上传用户表单数据，训练数据来自员工自愿贡献且脱敏的公开网站表单样本，而非真实用户数据。
- 2025 年 10 月起，桌面端已不再提供独立桌面应用，电脑上的访问统一收敛到浏览器扩展（不再有单独的 Dashlane 桌面 App 承载 autofill）。

## 支持平台/网站

- 面向通用互联网表单（登录、注册、支付、收货地址等），非求职网站专用。
- 覆盖 Chrome、Firefox、Edge、Safari 等主流浏览器扩展，以及 iOS/Android 移动端（含系统级 AutoFill 集成、Dashlane 自带浏览器、部分第三方 iOS App 内自动填充）。
- 官方文档未提及对求职网站/ATS（如 Workday、Greenhouse、Lever）做过任何专门适配或优化。

## 自动化程度（全自动 / 半自动，人工介入点）

- 半自动为主：用户需要主动点击某个输入框，触发 Dashlane 弹出建议（图标/下拉），再点选具体要填的身份、地址或卡片条目，才会联动填充相关字段。
- 当保存了多条同类信息（多个地址、多个身份）时，需要人工从候选列表中选择用哪一条，不会自动判断"应该用哪个"。
- 未见任何"整份申请表单全自动提交"或"批量投递"的能力描述；autofill 仅解决"填字段"这一步，提交、翻页、上传附件等仍需用户手动操作。
- 2026 年 3 月更新后，行为更收敛（只填选中条目直接相关的字段，而非试图填满整页），进一步说明其定位是"辅助填写"而非"全自动流程"。

## 反爬虫/验证码/风控应对

- 公开资料中未发现任何关于验证码识别、反爬虫绕过或风控规避机制的描述。作为浏览器扩展/移动端 autofill 工具，Dashlane 的交互方式是模拟用户在页面上的真实点击和输入（而非无头浏览器脚本化提交），天然不涉及需要绕过反爬的场景；官方也从未将"绕过验证码"作为宣传点。
- 此项为推测：未搜索到相关公开材料，不排除完全不涉及此类问题。

## 应用于求职投递场景的可行性简评

- Dashlane 可以帮助用户在填写求职网站的"个人信息""联系方式""地址"等标准字段时省去手动输入，这一点与其他密码管理器（1Password、Bitwarden 等）的通用 autofill 能力类似。
- 但公开资料中**没有看到简历（Resume/CV）解析、上传或结构化数据映射到申请表单的功能**；官方产品页只提到姓名、地址、邮箱、电话、支付卡等"Secure Digital Wallet"字段类型，不涉及工作经历、教育背景等简历专属字段。
- 不支持多页/多步骤 ATS 申请流程的整体自动化（如自动翻页、自动上传附件、自动点击"下一步"），这些仍需人工操作；Dashlane 的价值仅限于"减少重复输入基础个人信息"这一环节。
- 综合来看，Dashlane 不适合作为求职自动投递系统的核心引擎，最多可以作为"个人信息自动填充"的参考实现（尤其是其 SAWF 字段分类思路和本地小模型 + 云端大模型打标结合的训练流程，对设计求职表单字段识别系统有一定参考价值）。

## 局限性

- 闭源商业产品，核心算法、模型结构、训练数据规模等均未公开，本文所述技术细节全部来自官方博客/帮助中心的高层次描述，可信度有限，且可能随产品迭代而变化。
- 无简历解析/上传功能，无法处理求职场景中常见的"上传 PDF 简历自动解析生成申请表"需求。
- 无多页表单流程自动化、无自动提交、无验证码处理相关的公开信息。
- 2025 年 10 月起取消独立桌面应用，架构变化可能会影响未来的功能形态，本文所述信息存在时效性风险。

## 参考来源
- https://www.dashlane.com/personal-password-manager/autofill
- https://www.dashlane.com/blog/ai-autofill-privacy
- https://www.dashlane.com/blog/autofill-machine-learning
- https://support.dashlane.com/hc/en-us/articles/202699151-Autofill-your-data-using-Dashlane
- https://support.dashlane.com/hc/en-us/articles/360014230539-Autofill-FAQ
- https://support.dashlane.com/hc/en-us/articles/36305045093138-10-AI-at-Dashlane
- https://www.dashlane.com/blog/mar-2026-whats-new
- https://support.dashlane.com/hc/en-us/articles/26994895773842-Desktop-access-restricted-to-Dashlane-browser-extension-only
- https://support.dashlane.com/hc/en-us/articles/202625002-Supported-devices-and-browsers
