# Edge 内置表单自动填充 —— 自动填表实现调研

- 项目地址/官网: https://www.microsoft.com/en-us/edge/features/autofill （用户侧说明）；https://support.microsoft.com/en-us/microsoft-edge/automatically-fill-info-in-microsoft-edge-81da697c-9910-d9b8-d50a-1712d96f3db8 （官方支持文档）；企业策略: https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/
- 类型: 浏览器原生功能（基线参考，基于 Chromium）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测。Edge 未开源其增量代码（Chromium 内核部分开源，但 Edge 专有层——Wallet/Copilot/账号同步等——闭源），本调研主要依据 Microsoft 官方支持文档、企业策略文档（learn.microsoft.com）、Edge 官方博客（blogs.windows.com/msedgedev）与第三方媒体报道；未能读到任何 Edge 专有层源码。

## 核心实现方式

**继承自 Chromium 的基础架构（不重复展开，详见同目录 `63-chrome-native-autofill.md`）**

Edge 基于 Chromium 构建，其表单字段识别/填充的核心引擎（`components/autofill/` 分层组件、`AutofillAgent`/`AutofillManager`/`FormStructure` 等类、autocomplete 属性 > 众包预测 > 本地正则启发式的三层字段类型判定逻辑、`AutofillProfile`/`CreditCard` 固定字段数据模型、SQLite 本地持久化）大概率直接继承自 Chromium 上游，Microsoft 官方文档中也未声称重写了这套底层引擎。因此本文件不再重复推导这部分实现，只聚焦 Edge 在此基础上新增/差异化的部分。

**Edge 专有层新增能力**

1. **账户与数据管理 UI**：Edge 将 Autofill 相关设置整合在"个人资料"（Profiles）体系下——`edge://settings/profiles` 对应"个人信息"（地址等）、"支付信息"（Wallet/银行卡）、"密码"三大分区，用户需通过对应开关（如"在注册表单上自动填写我的信息"）显式启用（Microsoft Support 文档）。
2. **Microsoft 账号同步**：数据默认本地存储，登录 Microsoft 账号并开启同步后，地址/支付/密码信息可跨设备（含 Windows、其他平台的 Edge，以及登录同一账号的移动端）同步；密码管理器同时支持在 Chrome 上以扩展形式使用（Microsoft Autofill Password Manager 扩展），可跨浏览器同步密码，这是 Edge 相对纯 Chromium 的差异化能力之一（tech.co 报道）。
3. **安全加固**：支付信息本地加密存储，Edge 不存储 CVV；可配置在自动填充已保存密码/支付信息前，要求 Windows Hello（PIN/生物识别/设备凭据）二次验证（Microsoft Support 文档、社区文章）。
4. **Wallet 功能变迁**：早期的 Edge Wallet（含会员卡号等 membership 数据）已被整合/退役，迁移到新的 Profiles 体系后，原 membership 类数据不再可访问——官方文档明确提示这一数据迁移的局限（support.microsoft.com）。
5. **企业侧机器学习增强的自动填充建议（Edge 专有，非 Chromium 通用开关）**：企业策略文档中存在一个 `EdgeAutofillMlEnabled` 策略，官方描述为"启用后，Edge 可使用基于历史自动填充数据的云端机器学习模型，为表单填充提供更智能、更符合上下文的建议"；禁用后自动填充"退化为不含机器学习增强的基础表单数据填充"。该策略依赖 `AutofillAddressEnabled`（后者关闭时前者自动关闭），说明这是叠加在地址自动填充之上的一层云端 ML 能力，Microsoft Learn 上单独成文管理，与 Chrome 的 `AutofillPredictionSettings`（生成式 AI 理解表单）在策略命名和归类上并不完全一致，可能是 Edge 团队在 Chromium 基础上做的独立封装或差异化实现（learn.microsoft.com/.../edgeautofillmlenabled）。
6. **Copilot 相关的"智能体式"浏览能力（与传统 Autofill 是两套不同技术栈）**：Edge 陆续推出 "Copilot Mode"（2025-07 发布博客）→ "Copilot Actions"/"Journeys"（2025 年内测）→ 更名为 "Browse with Copilot"（2026 年向 Microsoft 365 Premium 订阅用户推广，目前仅限美国）。其官方支持页（support.microsoft.com/.../copilot-actions-in-edge）明确列出的可执行任务包括：**表单填写与数据录入、购物下单、预订、以及"提交求职申请"（job application submission）**——这是官方文档中直接点名的使用场景，与本项目要研究的"全自动投递"高度相关。运作方式：用户在地址栏/新标签页输入"Browse with Copilot"指令后，Copilot 以类人方式操作页面——点选、输入、滚动、跨标签导航；对陌生网站会弹出"始终允许/仅本次允许/取消"授权提示，全局还有 Light/Balanced/Strict 三档权限策略；对"下单购买、预订、发邮件、删除日程"等有实际后果的操作，即使网站已被信任，仍会停下来征求用户确认。官方同时明确：Copilot **无法访问** Edge 的 autofill 数据、已保存密码或 Wallet 信息（作为隔离设计），且官方直接承认该功能"仍处于实验阶段，可能误解指令、出错，或被网页中隐藏的恶意指令（prompt injection）影响"，建议用户密切监督。企业版对应功能为 "Edge for Business" 的受控智能体浏览（2026-05 宣布，有限预览），通过 Microsoft Purview 由 IT 设定可访问网站白名单，仅面向持有 Microsoft 365 Copilot 许可的企业客户，且不面向欧洲经济区（EEA）开放。需要说明的是，Copilot Mode/Actions 相关功能命名在 2025-2026 年间变动频繁（有报道称 "Copilot Mode" 品牌被整合/替换），说明该功能仍在快速迭代、尚未定型。

## 技术栈

- 浏览器内核：Chromium/Blink（C++），Autofill 基础引擎继承自 `components/autofill/`
- Edge 专有 UI/账号层：闭源，无法确认具体实现，仅能从功能行为反推
- 云端机器学习模型：`EdgeAutofillMlEnabled` 对应的表单填充建议模型为云端调用（非纯本地），基于历史自动填充数据
- Copilot Actions/Browse with Copilot：基于大模型的智能体式浏览器操作能力，运行在浏览器本地捕获页面截图/DOM 并与云端模型交互（截图会上传用于操作推理，官方声明"从不用于训练"，非对话删除时最长保留 30 天）；具体依赖的模型未在公开文档中指名（推测与 Microsoft Copilot/OpenAI 模型体系相关，但未找到直接证据，此处不作断言）

## 支持平台/网站

- 基础 Autofill（地址/支付/密码）：不针对特定网站，是通用浏览器能力，覆盖 Windows/macOS/移动端 Edge
- Copilot Actions / Browse with Copilot：面向 Microsoft 365 Premium 个人订阅用户，目前仅限美国，逐步扩展中；企业版 "Edge for Business" 智能体浏览仅限持有 Microsoft 365 Copilot 许可、IT 已设定白名单的企业客户，且明确排除欧洲经济区（EEA）；对高风险网站（成人内容、赌博等）内置黑名单限制访问

## 自动化程度（全自动 / 半自动，人工介入点）

- **基础 Autofill**：与 Chrome 一致，半自动、人工始终驱动浏览器——用户需主动点击字段/候选项触发填充，填充结果为可编辑文本，需人工核对提交。
- **Copilot Actions / Browse with Copilot**：自动化程度显著更高，是本调研中少见的、官方明确具备"较强自主性"的浏览器原生功能——在用户已授权的可信网站上，Copilot 可以连续执行点击、输入、跨页导航等多步操作而无需逐步确认；但对"购买、预订、发邮件、删除日程"等有实际后果的动作，仍会暂停征求用户批准。官方文档未明确说明"提交求职申请"这一具体动作是否被归入需要人工确认的"有后果操作"之列，本调研未能找到该细节的直接证据，需谨慎对待——不排除其在实际使用中对求职申请提交同样会暂停确认。整体上，这套机制处于"半自动"与"更自主的智能体"之间的过渡形态，而非完全无人值守。

## 反爬虫/验证码/风控应对

- **基础 Autofill**：不适用，填表全程在人工操作的真实浏览器会话中完成，不涉及自动化脚本式访问，不会触发网站反爬/验证码机制。
- **Copilot Actions / Browse with Copilot**：同样运行在用户真实登录的浏览器会话内（非无头浏览器、非批量请求），本质上仍是"人类账号 + 浏览器原生集成的智能体在操作"，而非独立于浏览器之外的自动化脚本，所以不属于传统意义上需要"绕过反爬虫/验证码"的场景。但相较传统 Autofill，它确实向"更自主的智能体式操作"迈出了一步（多步操作、部分网站无需逐步确认），Microsoft 采用的应对方式是产品侧治理而非反检测：网站白名单/黑名单机制、分级权限（Light/Balanced/Strict）、对高风险/成人内容网站的访问限制、企业版由 IT 通过 Microsoft Purview 统一管控可访问站点。官方也坦承该功能可能被网页中的隐藏恶意指令（prompt injection）影响，这是智能体式浏览器自动化特有的新风险类别，与传统反爬虫风控不是同一维度的问题。

## 应用于求职投递场景的可行性简评

基础 Autofill 的可行性评估与 Chrome 原生 Autofill 基本一致（详见 `63-chrome-native-autofill.md`）：只能覆盖固定的联系人/支付字段，无法处理开放式问答、简历定制内容生成，直接可用性低，更适合作为字段映射范式的参考基线。

真正值得关注的是 Copilot Actions / Browse with Copilot：Microsoft 官方支持文档直接点名"提交求职申请"作为其能力示例，说明浏览器厂商本身正在验证与本项目高度重合的目标场景。但从"可被本项目复用"的角度看，其可行性很低：（1）完全闭源、无公开 API 或 SDK，无法作为组件集成进本项目的"投递"模块；（2）目前仅面向 Microsoft 365 Premium 个人订阅用户（美国）或持特定企业许可的组织，普适性差；（3）官方明确将其定性为"实验性"功能，存在误解指令、出错、被提示词注入攻击影响等风险，尚不具备生产级稳定性；（4）其"多步自主操作 + 关键动作需人工确认"的交互设计思路，以及"网站白名单/分级权限"的治理框架，倒是可以作为本项目设计"投递"模块自动化程度与人工介入点（比如"提交前必须人工确认"这类关键节点）时的参考范式。

## 局限性

- Edge 专有层（账号同步、Wallet、Copilot 相关能力）完全闭源，公开文档披露的实现细节有限，本调研只能从官方支持页/企业策略页的行为描述反推，未能验证任何具体代码实现
- `EdgeAutofillMlEnabled` 对应的云端 ML 模型细节（模型结构、调用方式）官方文档未披露，只知道"基于历史自动填充数据的云端模型"这一描述
- Copilot Actions/Browse with Copilot 命名与形态在 2025-2026 年间多次变动（Copilot Mode → Copilot Actions/Journeys → Browse with Copilot），说明该功能尚未定型，本文档描述的细节存在后续变化的可能性
- 该功能目前地域/账号门槛较高（美国 + M365 Premium 订阅，或企业许可 + IT 白名单），普通用户/开发者难以直接验证或复用
- 未找到官方文档明确说明 Copilot Actions 是否会在"提交求职申请"这一具体步骤上强制要求人工确认，这一细节存疑，不应假设其等同于全自动无人值守投递

## 参考来源
- https://support.microsoft.com/en-us/microsoft-edge/automatically-fill-info-in-microsoft-edge-81da697c-9910-d9b8-d50a-1712d96f3db8
- https://www.microsoft.com/en-us/edge/features/autofill
- https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/autofilladdressenabled
- https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/edgeautofillmlenabled
- https://support.microsoft.com/en-us/topic/copilot-actions-in-edge-5ed5e17e-42df-40a3-984a-20420eba86e2
- https://blogs.windows.com/msedgedev/2025/07/28/introducing-copilot-mode-in-edge-a-new-way-to-browse-the-web/
- https://blogs.windows.com/msedgedev/2025/10/23/meet-copilot-mode-in-edge-your-ai-browser/
- https://blogs.windows.com/msedgedev/2026/05/13/new-updates-to-edge-across-desktop-and-mobile/
- https://windowsforum.com/threads/edge-for-business-agentic-browsing-copilot-can-act-under-it-rules.419324/
- https://tech.co/news/microsoft-autofill-password-manager
- https://www.neowin.net/news/microsoft-is-killing-copilot-mode-in-edge-but-ai-features-arent-going-away/
