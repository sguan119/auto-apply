# Bitwarden —— 自动填表实现调研

- 项目地址/官网: https://bitwarden.com/ ；客户端源码 https://github.com/bitwarden/clients ；架构文档 https://contributing.bitwarden.com/architecture/deep-dives/autofill/
- 类型: 客户端开源/服务端闭源（密码管理器，表单自动填充为副产品功能，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 源码验证（部分）+ 官方架构文档。通过 WebFetch 实际读取了 `bitwarden/clients` 仓库中 `autofill-constants.ts`、`autofill.service.ts`、`collect-autofill-content.service.ts`、`autofill-init.ts` 等文件的公开代码内容，并交叉核对了 Bitwarden 官方 Contributing 文档（contributing.bitwarden.com，由 Bitwarden 工程团队维护，专门描述 autofill 架构的技术细节）。未逐行克隆仓库做静态分析，部分细节（如具体正则/常量的完整清单）为工具摘要而非逐字抄录，故不标记为"完全源码验证"。

## 核心实现方式

Bitwarden 的自动填充是**基于规则的启发式字段匹配**，完全不涉及 AI/LLM，架构分三层：

1. **内容脚本（Content Scripts）**：注入到网页中，负责实际读写 DOM。关键文件：
   - `apps/browser/src/autofill/content/autofill-init.ts`（核心入口）
   - `apps/browser/src/autofill/content/bootstrap-autofill.ts`（初始化）
   - `apps/browser/src/autofill/services/collect-autofill-content.service.ts`（收集页面上的 input/textarea/select 等表单元素信息）
   - `apps/browser/src/autofill/services/autofill-overlay-content.service.ts`（处理内联填充菜单 UI 与表单字段的绑定）
2. **后台服务（Background/Service Worker）**：`apps/browser/src/autofill/services/autofill.service.ts` 中的 `AutofillService` 负责根据收集到的页面字段信息 + 用户 vault 中的条目，生成一份 "fill script"（一系列"填哪个字段、填什么值"的指令），再发回内容脚本执行。
3. **字段匹配规则**：`apps/browser/src/autofill/services/autofill-constants.ts` 中硬编码了大量按 cipher 类型（Login / Card / Identity）分类的关键词常量表，用于比对表单元素的 `htmlName`、`htmlID`、`placeholder`、`label`、`aria-label`、`autocomplete` 等属性，包含多语言变体（如德语 "vorname"/"nachname"、法语 "numero-carte"）：
   - 登录类：`UsernameFieldNames`、`EmailFieldNames`、密码字段通过检测 `htmlID`/`htmlName`/`placeholder` 是否包含 "password" 判定，随后在 DOM 中向前查找最近的文本/邮箱/电话输入框作为用户名候选
   - 银行卡类：`CardHolderFieldNames`、`CardNumberFieldNames`、`ExpiryMonthFieldNames`、`ExpiryYearFieldNames`、`CVVFieldNames`、`CardBrandFieldNames`，还会比对 `data-stripe`、`data-recurly` 等第三方支付 SDK 特有属性
   - 身份（Identity）类：`FirstnameFieldNames`、`LastnameFieldNames`、`AddressFieldNames`、`PhoneFieldNames`、`CityFieldNames`、`StateFieldNames`、`CountryFieldNames`、`PostalCodeFieldNames` 等约 12 个固定属性槽位
4. 匹配成功后按预定义映射规则批量填值，不做语义理解、不做自然语言推理。

## 技术栈

- TypeScript（Manifest V3 浏览器扩展，Chrome/Firefox/Edge/Safari 等）
- 内联填充菜单（Autofill inline menu）UI 使用**沙箱化 iframe**渲染，通过 `postMessage` 与扩展背景页通信，避免直接暴露扩展 API，并施加严格 CSP 防止其他扩展读取上下文
- 扩展消息 API（`BrowserApi.tabSendMessage` / `BrowserMessagingService`）用于 background、content script、popup UI 三者之间通信
- 桌面端（Electron/.NET/Rust 混合，视版本而定）、移动端（Kotlin/Swift）作为独立 vault 客户端，与浏览器扩展共享同一账号数据，但表单自动填充的核心逻辑主要在浏览器扩展中实现；移动端在系统级 Autofill Framework（Android Autofill Service / iOS AutoFill Credential Provider）上对接，机制由操作系统提供、Bitwarden 仅作为数据源

## 支持平台/网站

- 无网站白名单，理论上适配任意网页，靠通用启发式规则识别表单
- 官方承认存在"已知有填充问题的网站"，2026.6.1 版本新增 "Fill Assist" 功能——针对 Bitwarden 官方整理的一批已知疑难网站列表，启用后采用更激进的匹配策略以提升准确率（说明常规启发式在部分现代前端框架页面上会失败，需要人工维护例外名单来补救）
- 支持通过 URI 匹配规则（Base domain / Host / Starts with / Regex 等）决定某个网站上该提示哪些 vault 条目

## 自动化程度（全自动 / 半自动，人工介入点）

- 默认**半自动**：需要用户主动触发（点击扩展图标、右键菜单、内联菜单选择条目、或快捷键 Ctrl/Cmd+Shift+L）；"页面加载时自动填充"选项存在但默认关闭
- 填充目标仅限已保存的 Login / Card / Identity 三类条目中的固定字段槽位，用户仍需人工创建/维护这些条目内容
- 不支持任何多步骤自动化流程（如自动点击"下一步"、跨页面提交表单），文档与代码中均未发现相关逻辑
- 2025-2026 年 Bitwarden 推出了 **MCP（Model Context Protocol）服务器**，允许外部 AI Agent 通过 API 访问 vault 中的凭据（生成/检索/管理），但这是"AI 调用 Bitwarden 数据"的集成能力，而非"Bitwarden 自动填表功能本身使用 AI"——两者需要区分：表单填充的字段匹配逻辑仍是纯规则式，MCP 只是新增的数据访问通道，供第三方 Agent 编排使用

## 反爬虫/验证码/风控应对

未发现任何相关机制。Bitwarden 定位是密码管理器而非自动化投递/爬虫工具，没有处理 CAPTCHA、模拟人类行为、代理池等能力的需求，架构文档和代码中都无此类内容。

## 应用于求职投递场景的可行性简介

- 可行性有限：Bitwarden 的 Identity 条目字段是**固定预设的通用信息槽位**（姓名、地址、电话、证件号等），没有"教育经历/工作经历/技能列表"这类结构化字段，也不支持简历文件的自动上传（其 Attachments 附件功能是登录条目下的通用文件存储，与表单的 file input 自动填充无关联，需要用户手动上传附件到具体网站）
- 对于求职网站中常见的"基本信息"字段（姓名、邮箱、电话、地址）可以复用其身份填充能力，减少重复输入
- 完全不具备多页表单跳转、自动提交、验证码处理等投递自动化所需的能力，需要与专门的投递自动化工具组合使用，Bitwarden 只能承担"基础信息代填"这一小部分工作
- 自定义字段（Custom Fields）机制允许用户手工为特定网站的特殊字段建立"别名映射"，但仍需用户逐个网站手动配置，扩展性差，不适合批量投递场景

## 局限性

- 字段识别基于静态关键词/属性表，无法应对语义变化较大或高度定制化的现代前端表单（这也是官方专门推出 "Fill Assist" 例外名单的原因）
- Identity 条目字段是固定 schema，不可扩展出求职专用字段（如"期望薪资""可到岗时间"等），无法承载完整简历信息
- 不支持简历/附件文件的自动上传绑定
- 无跨页面/多步骤表单状态记忆能力
- 无 AI/语义理解能力，表单填充完全依赖预置关键词表和 DOM 结构启发式，遇到不常见的字段命名或高度封装的组件（如自定义 Web Component 输入框）容易失效

## 参考来源
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/services/autofill.service.ts
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/services/autofill-constants.ts
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/services/collect-autofill-content.service.ts
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/content/autofill-init.ts
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/content/bootstrap-autofill.ts
- https://github.com/bitwarden/clients/blob/main/apps/browser/src/autofill/services/autofill-overlay-content.service.ts
- https://contributing.bitwarden.com/architecture/deep-dives/autofill/
- https://contributing.bitwarden.com/architecture/deep-dives/autofill/generating-fill-scripts/
- https://contributing.bitwarden.com/architecture/deep-dives/autofill/autofill-menu/
- https://bitwarden.com/help/auto-fill-browser/
- https://bitwarden.com/help/uri-match-detection/
- https://bitwarden.com/help/auto-fill-custom-fields/
- https://bitwarden.com/help/custom-fields/
- https://bitwarden.com/help/auto-fill-android/
- https://community.bitwarden.com/t/2026-6-1-release-notes/98121
- https://www.businesswire.com/news/home/20250710815039/en/Bitwarden-Brings-Agentic-AI-to-Secure-Credential-Management
