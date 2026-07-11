# Chrome 内置表单自动填充 —— 自动填表实现调研

- 项目地址/官网: https://chromium.googlesource.com/chromium/src/+/master/components/autofill/ （源码，Chromium 是开源项目）；用户侧说明: https://www.google.com/chrome/ai-innovations/ ，https://blog.google/products/chrome/enhanced-autofill/
- 类型: 浏览器原生功能（基线参考，Chromium 开源）
- 调研日期: 2026-07-06
- 置信度: 混合 —— 经典 Autofill 架构（本节"核心实现方式"前半部分）来自 Chromium 官方源码仓库的组件说明文档与源码文件名/特性开关直接验证，标记为"源码验证"；2025 年新增的 "Enhanced Autofill" / "AutofillAI" 生成式 AI 能力，源码层只确认了特性开关（feature flag）与文件名的存在（说明功能真实存在于代码库中），未逐行阅读其模型调用/推理实现，具体行为描述主要引自 Google 官方博客与 Chrome Enterprise 政策文档，故这部分标记为"基于公开资料推测"。

## 核心实现方式

**经典 Autofill（地址/支付/密码，多年来的主体架构，源码验证）**

Chromium 的 autofill 是一个"分层组件"（layered component），代码位于 `components/autofill/`，分为 `core/`（浏览器与渲染进程共用逻辑，含 `browser/`、`common/`）、`content/`（非 iOS 平台的驱动层，含 `browser/renderer/common`）、`ios/`（iOS 专用驱动）、`android/`（Android Java 层）。关键类：渲染进程侧 `AutofillAgent`（每个 RenderFrame 一个实例，观察表单变化）；浏览器进程侧 `ContentAutofillDriver`（每个 RenderFrameHost 一个实例，负责渲染进程与浏览器进程通信）与 `AutofillManager` / `BrowserAutofillManager`（表单级别的核心编排逻辑）；表单数据在渲染进程侧表示为 `FormData`/`FormFieldData`，进入浏览器进程后被扩充为带有字段类型预测的 `FormStructure`/`AutofillField`。对于含有 iframe 的"跨帧表单"（frame-transcending form），由 `AutofillDriverRouter` 负责打平处理。

字段类型判定采用分层优先级机制（源码位置 `components/autofill/core/browser/form_parsing/` 等）：
1. **HTML `autocomplete` 属性**：优先级最高，直接覆盖本地启发式与众包结果（值为 `off` 时除外）；
2. **众包（Crowdsourcing）**：由 `AutofillCrowdsourcingManager` 从服务端下载基于海量匿名用户表单结构统计得到的字段类型预测，优先级高于本地启发式；
3. **本地启发式（Local Heuristics）**：基于正则表达式匹配字段的 name/id/label 等属性的硬编码规则，按语言/地区分别维护规则集，作为兜底方案；触发条件通常要求表单至少 3 个字段且分类出至少 3 种不同类型（邮箱、优惠码、IBAN、CVV 等字段有豁免）；
4. **归一化（Rationalization）**：对前几步输出做后处理，修正不合理的字段组合（如 street-address 后紧跟 address-line1）。

数据存储方面，地址类信息由 `AutofillProfile` 表示（姓名、地址、电话等，按 `EmailInfo` 等字段分组存储支持的类型），支付方式由 `CreditCard` 表示；两者都持久化在本地 SQLite 的 `AutofillTable` 中，`PersonalDataManager`（每个 BrowserContext 一个实例）在内存中维护其副本供填充时读取。这是一个固定字段集合（姓名、住址、电话、邮箱、公司、银行卡号/有效期/持卡人等）的结构化数据模型，不是自由格式的简历/问答数据。

**近年 ML 分类器与生成式 AI（2024-2025，混合验证）**

除了上述正则启发式，Chromium 特性开关文件 `components/autofill/core/common/autofill_features.h`（GitHub: chromium/chromium 镜像可查）中可见多个与预测模型相关的 flag，如 `kAutofillModelPredictions`、`kAutofillModelPredictionsAreActive`、`kFieldClassificationModelCaching` 等，对应一个基于机器学习（推测为轻量级设备端分类模型，Chromium 的设备端 ML 基础设施使用 TensorFlow Lite/LiteRT 运行时）的字段分类改进方向，用于在启发式/众包不足时进一步提升分类准确率；这与地址栏等其他 Chromium 子系统采用的"轻量 on-device ML 分类模型"技术路线一致（用于分类/打分，而非生成文本）。

2025 年，Google 推出了范围更大的 "Enhanced Autofill" / "AutofillAI" 能力（源码中可见 `chrome/browser/autofill/autofill_ai_model_cache_factory.h`、`kAutofillAiServerModel`、`kAutofillAiServerModelSendPageContent`、`kAutofillAiServerModelSendPageUrl` 等 flag，说明存在一个会把页面内容/URL 发送到服务端模型进行推理的机制），对应 2025 年 11 月起全球上线的 "Enhanced Autofill" 功能：除传统的姓名/地址/支付卡外，新增护照号码、驾照号码、车牌/VIN 车辆信息、Google Wallet 里的会员卡号与航班行程信息等的自动填充。Chrome Enterprise 官方政策文档 `AutofillPredictionSettings` 明确写明该策略"控制是否允许 Google Chrome 使用生成式 AI（Generative AI）更好地理解表单、帮助用户填充更多字段"，并被归类在 Chrome 的"生成式 AI 功能与政策"分类下，策略取值包括：0=允许使用且允许 Google 用相关数据改进模型、1=允许使用但不允许用用户内容改进模型（企业/教育账号默认值）、2=完全禁止。这是目前能确认的、Chrome 原生 Autofill 家族中真正使用生成式 AI 的部分，用途是"更好地理解表单结构、扩大可自动填充的字段范围"，而非用于生成开放式问答内容。

## 技术栈

- 浏览器内核 C++（Chromium/Blink），Autofill 组件位于 `components/autofill/`，按 content/ios/android 分驱动层适配
- 本地持久化：SQLite（`AutofillTable`），内存缓存由 `PersonalDataManager` 维护
- 众包预测：客户端-服务端协议，`AutofillCrowdsourcingManager` 负责下载/上传
- 设备端分类模型：推测基于 TensorFlow Lite / LiteRT（Chromium Optimization Guide 基础设施），模型文件按需下发到本地 `optimization_guide_model_store`
- 生成式 AI 部分（AutofillAI/Enhanced Autofill）：服务端模型调用（发送页面内容/URL），2025 年起与 Google 账号、Google Wallet 云端数据打通

## 支持平台/网站

不针对特定招聘网站或平台，是通用的浏览器内置能力，理论上对任意包含 `<form>`/输入框的网页生效；效果依赖网页是否使用标准 HTML 表单元素与语义化标记（`autocomplete` 属性、恰当的 `input type`/`name`/`label`）。支持桌面版 Chrome（Windows/macOS/Linux/ChromeOS）与移动版（Android/iOS），Enhanced Autofill 的护照/驾照/车辆信息在 2025 年 11 月起先在桌面端上线，随后扩展到移动端并与 Google Wallet 深度整合。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动、且始终由人工驱动浏览器操作本身：用户需要主动点击某个字段（或点击建议下拉框中的候选项）才会触发填充，填充结果仍展示为可编辑文本供用户核对后再手动提交表单；Enhanced Autofill 中涉及护照/驾照等敏感证件信息时，官方明确"填充前会要求用户确认"（"Chrome will ask you to confirm"）。它不具备自主导航、连续多步操作或自动提交表单的能力——这与 Chrome 近期推出的、构建在 Gemini 之上的独立 "Auto Browse" 智能体功能（可多步执行任务、代表用户操作，但在下单/提交支付等关键步骤仍会停下来征求用户确认）是两个不同的产品/技术栈，不应混为一谈：Auto Browse 是 agentic LLM 驱动的浏览器自动化，Autofill 是本报告讨论的传统表单填充功能。

## 反爬虫/验证码/风控应对

不适用。Autofill 只是在人工操作的浏览器会话中协助填充输入框内容，不涉及任何自动化脚本式访问、无头浏览、批量请求等行为，因此不会触发、也无需应对网站的反爬虫/验证码/风控机制——填表过程与人类正常使用浏览器完全一致。

## 应用于求职投递场景的可行性简评

作为"基线参考"意义较大，但直接可用性很低：Autofill 只能填充其预定义的固定字段集合（姓名、地址、电话、邮箱、支付卡，以及新增的证件/会员卡/行程信息），无法理解招聘网站中大量的开放式问题（如"为什么想加入我们"、工作经历详述、算法题/主观问答）、无法上传/生成简历、也不能跨字段做语义改写或按职位定制内容。它比较适合帮用户快速填完投递流程中"标准化的联系人/基本信息"部分（如姓名、邮箱、电话、住址），但对于本项目"投递"模块所需的"职位定制内容生成 + 结构化字段回填 + 全流程自动化"的目标，Chrome 原生 Autofill 提供的价值有限，更适合作为"浏览器原生填表能力"的参照基线，而不是可复用的核心组件。其字段分类的三层优先级（autocomplete 属性 > 众包 > 本地正则启发式）思路，以及"固定 profile 数据模型 + 表单结构解析"的架构，倒是可以作为本项目设计"简历字段 → 表单字段映射"逻辑时的参考范式。

## 局限性

- 仅覆盖预定义的通讯录/支付/证件类字段，字段集合由 Chromium 团队硬编码维护，不可由第三方扩展新的语义字段类型
- 无法处理开放式问答、简历上传、职位相关的定制化内容生成，与求职投递场景的核心诉求（简历改写+多样化申请表单）存在本质差距
- 生成式 AI（AutofillAI/Enhanced Autofill）用途局限于"更准确地识别与填充已有字段"，并非生成新内容，且该功能会把页面内容/URL 发送到 Google 服务端（`kAutofillAiServerModelSendPageContent` 等 flag 印证），存在企业可关闭的隐私开关，说明其并非纯本地闭环
- 本次调研对"设备端 ML 分类模型"的具体模型结构/训练方式，以及 "AutofillAI 服务端模型"的具体推理逻辑，均未能读到完整源码实现，只能通过特性开关名称、公开博客与企业政策文档间接确认其存在与大致用途
- 完全依赖人工在真实浏览器中逐步操作，没有任何形式的批量化、无人值守能力

## 参考来源
- https://chromium.googlesource.com/chromium/src/+/master/components/autofill/
- https://github.com/chromium/chromium/blob/master/components/autofill/core/common/autofill_features.h
- https://github.com/chromium/chromium/blob/main/chrome/browser/autofill/autofill_ai_model_cache_factory.h
- https://www.chromium.org/developers/design-documents/form-autofill/
- https://developer.chrome.com/docs/identity/autofill
- https://blog.google/products/chrome/enhanced-autofill/
- https://blog.google/products/chrome/autofill-improvements/
- https://chromeenterprise.google/policies/autofill-prediction-settings/
- https://support.google.com/chrome/a/answer/14443058?hl=en （Chrome—Generative AI features and policies，AutofillPredictionSettings 归类于此）
- https://techcrunch.com/2025/11/03/chrome-can-now-autofill-your-passport-drivers-license-and-vehicle-registration-info/
