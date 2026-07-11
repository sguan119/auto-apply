# Microsoft Power Automate —— 自动填表实现调研

- 项目地址/官网: https://www.microsoft.com/power-platform/products/power-automate ；文档 https://learn.microsoft.com/power-automate/
- 类型: 闭源（RPA 企业级工具，可配置用于网页表单填写，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Power Automate 分两大类流程，架构上完全不同：

- **Cloud flows（云流）**：纯云端，基于触发器/连接器（connector）编排 SaaS 服务（Outlook、SharePoint、Dataverse 等），不涉及界面操作，不适用于"打开网页填表单"这种场景。
- **Desktop flows（桌面流，原 Power Automate Desktop / WinAutomation）**：安装在本机 Windows 客户端，通过模拟鼠标点击、键盘输入、UI 元素交互来自动化桌面应用与网页，这是实现"网页表单自动填写"的部分。

桌面流的网页自动化子系统称为 **UI flows 的 Web automation（浏览器自动化）**：

1. **录制器（Recorder）**：用户在 Power Automate Desktop 客户端启动 Recorder，在浏览器中手动执行一遍操作（点击、输入、翻页等），录制器同时追踪鼠标/键盘事件与其作用的 UI 元素，自动生成对应的"Launch Browser / Populate text field on web page / Click link on web page"等动作节点，形成可回放的流程（Record → Replay 模式）。
2. **浏览器通信方式**：
   - 传统方式依赖为 Chrome / Edge / Firefox（及遗留的 IE）安装官方 **Power Automate 浏览器扩展**，扩展负责在页面内捕获元素、注入/回放动作；2.27 版本起扩展随桌面客户端安装包一起分发（`...\Power Automate Desktop\BrowserExtensions`）。
   - 2.62 版本起新增 **WebDriver** 作为替代通信方式，可不装浏览器扩展直接通过 WebDriver 协议控制浏览器（类似 Selenium 的方式）。
   - 还提供内置的 **Automation Browser**（基于 IE 内核）作为开箱即用、不需要额外配置的轻量浏览器。
3. **UI 元素与选择器体系**：桌面流不依赖图像识别或绝对坐标，而是维护一个"UI 元素仓库"，每个元素由一个或多个**选择器（selector）**描述：
   - 桌面应用元素：UIA（UI Automation，微软现代无障碍框架）、MSAA（旧版 Active Accessibility，用于遗留 VB6/Win32 应用）、UIA3 Raw（暴露完整原始控件树，适合 Electron 等复杂应用）三种选择器类型。
   - 网页元素：使用 **CSS 选择器**，以 `>` 表示层级包含关系，定位页面 DOM 结构中的目标节点；也支持基于元素文本值的"文本选择器"（text-based selector，使用 Name/Text 属性），据文档称比结构选择器更能抵御页面改版。
   - 一个 UI 元素可配置多个候选选择器，运行时若某个选择器失效会按顺序尝试下一个，提高对页面小幅改版的容错性。
4. **回放执行**：浏览器自动化动作默认通过模拟 JavaScript 事件（而非真实物理鼠标移动）操作元素，因此浏览器最小化或标签页不在前台时也能运行；部分动作（如 Click link on web page）可切换为"物理交互"模式，此时要求浏览器窗口保持焦点。

## 技术栈（推测）

- 桌面客户端：.NET / Windows 桌面应用（Power Automate Desktop 本体）。
- 浏览器侧：官方扩展（Chrome/Edge 基于 Chromium 扩展 API，Firefox 对应 WebExtensions），或 WebDriver 协议（Chromium/Gecko 的 W3C WebDriver 实现）。
- UI 自动化底层：Windows UI Automation（UIA）/ MSAA 无障碍框架，用于识别和操作原生控件；网页内则是 DOM/CSS 选择器 + 模拟 JS 事件。
- AI 相关新能力：
  - **Copilot in Power Automate**：可用自然语言描述需求，由 Copilot 生成/补全流程步骤。
  - **Record with Copilot（AI Recorder，预览版）**：用户共享屏幕并用语音讲解操作过程，系统把屏幕录像、语音旁白、鼠标/键盘元数据上传到云端，由 AI 模型分析后生成包含条件、循环等逻辑的桌面流（普通 Recorder 只能录制"点击-输入"序列,不含条件/循环逻辑）。截至文档更新时该功能仅限美国区环境、工作/学校账号、且仅支持英语讲解。
  - **AI Builder**：底层基于 Azure Form Recognizer 的文档智能服务，提供"文档处理模型"（Document processing model），可从发票、表单等结构化/半结构化文档中抽取字段，供 Power Automate 流程编排使用；与网页表单自动填写是两条不同能力（AI Builder 面向"读文档"，UI flows 面向"填网页/操作界面"），两者可组合，例如先用 AI Builder 从简历 PDF 抽字段，再用桌面流把字段填入网页表单。

## 支持平台/网站

- 支持的浏览器：Microsoft Edge、Google Chrome、Mozilla Firefox、（遗留）Internet Explorer，以及内置的 Automation Browser。
- 理论上可以针对任意网页录制/编写选择器进行操作，不限定网站类型；但选择器与录制内容都是针对特定页面结构定制的，页面改版或使用动态生成的 DOM/class 名会导致选择器失效，需要人工重新录制或维护。
- 需要预先在目标机器安装桌面客户端 + 浏览器扩展（或启用 WebDriver），属本机/托管环境自动化,不是纯云端可直接对任意公网网站开箱运行的爬虫式工具。

## 自动化程度（全自动 / 半自动，人工介入点）

- **录制阶段**：需要人工手动操作一遍目标网站流程（点击、填写、翻页），录制器据此生成动作序列——这是典型的"录制一次、回放多次"（record-once-replay）模式，而非理解语义的智能填表。
- **回放阶段**：可实现无人值守运行（Unattended RPA，需要额外的 Process/Hosted Process 授权与调度），也可配置为需要人在场触发的"有人值守"（Attended RPA）模式。
- 人工介入点通常出现在：
  - 页面结构变化导致选择器失效时的流程维护；
  - 出现验证码/异常弹窗/风控拦截时；
  - Record with Copilot 生成的流程存在"缺失动作或选择器"时需要人工在设计器中补全（官方 FAQ 明确提到这一已知限制）。
- AI Builder 文档抽取环节通常也建议保留人工复核，尤其是非标准模板文档。

## 反爬虫/验证码/风控应对

- Power Automate/桌面流**官方定位是企业内部/已授权系统的流程自动化工具**，官方文档中未提供任何针对验证码识别或反爬虫绕过的原生功能。
- 社区中存在第三方变通方案（非官方能力），包括：
  - 用桌面流截图 + "Extract text with OCR" 动作尝试识别纯文本类验证码；
  - 集成第三方付费验证码识别/打码服务（如 2Captcha、CapSolver）来解 reCAPTCHA 等图形/行为验证码；
  - 借助浏览器扩展（如 Buster）辅助处理 reCAPTCHA。
  这些均是用户自行拼接的第三方方案，不属于 Microsoft 官方支持或推荐的能力，且部分服务本身违反目标网站服务条款，稳定性和合规性存疑。
- 由于其"模拟真实浏览器 + 官方扩展/WebDriver 控制"的方式，行为特征上比无头爬虫更接近真人操作，但仍可能被基于设备指纹、行为模式、IP 信誉的风控系统识别为自动化流量；微软没有为此做任何规避设计。

## 应用于求职投递场景的可行性简评

理论上可以将 Power Automate Desktop 配置为求职投递自动填表工具：录制一次在某招聘网站上填写申请表、上传简历、提交的完整过程，之后对同一网站的其它职位重复回放，或结合 Excel/Dataverse 中的职位列表做批量循环投递,并可用 AI Builder 从简历文档中抽取结构化字段辅助填充。

但实际落地存在明显限制：

- **License 成本**：非免费的开源脚本工具。个人版 Per User 约 15 美元/月起（含有人值守 RPA 能力）；若要无人值守批量投递，需要 Process 计划（约 150 美元/机器人/月，托管版约 215 美元/月），对个人求职者而言性价比很低。
- **维护成本高**：每个招聘网站页面结构不同、且会持续改版，选择器需要针对每个站点单独录制/维护，跨网站复用性差,不像专门的求职自动投递脚本那样内置多平台适配层。
- **非为对抗性公网场景设计**：企业 RPA 工具默认假设自动化对象是内部系统或已获授权、无恶意反爬的系统；求职网站往往有登录风控、频率限制、验证码等对抗手段,而 Power Automate 官方没有配套的反检测/验证码处理能力，需要自行拼接不稳定的第三方方案。
- **部署环境要求**：需要 Windows 客户端环境安装桌面应用与浏览器扩展（或配置 WebDriver），不适合纯 Linux/云端无人值守小成本运行。

综合看,它更适合企业内部、已获授权的批量重复性网页操作场景,直接套用在"面向公众招聘网站的自动投递"这一目标上，成本与对抗性适配都不占优。

## 局限性

- 选择器（无论 UIA/MSAA 还是 CSS）本质上是"结构匹配"，网站前端改版、A/B 测试、动态 class 名都可能导致选择器失效，需人工重新录制。
- Recorder 生成的普通流程不含条件/循环逻辑，复杂分支需要人工在设计器里补充；Record with Copilot 虽能生成条件/循环，但仍是预览功能，官方 FAQ 明确指出可能出现"动作或选择器缺失"，且目前仅限美区、英语、工作账号。
- 无原生验证码/反爬对抗能力，社区变通方案不受官方支持。
- 需要 Windows 桌面环境 + 浏览器扩展（或 WebDriver），部署门槛高于纯脚本工具（如 Selenium/Playwright 脚本）。
- 授权费用面向企业客户设计，按用户/按流程/按机器人计费，对个人求职者而言边际成本偏高。
- 官方文档明确桌面流无法跨系统用户运行——即无法用与启动 Power Automate 不同的系统账号打开或接管浏览器，进一步限制了某些自动化部署场景（如服务账号批量托管运行）。

## 参考来源

- [Automate webpages - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/automation-web)
- [Automate using UI elements - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- [Record desktop flows - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/recording-flow)
- [Install Power Automate browser extensions - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/install-browser-extensions)
- [Create desktop flows using Record with Copilot (preview) - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/create-flow-using-ai-recorder)
- [UI automation actions reference - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- [Browser automation actions reference - Power Automate | Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/webautomation)
- [What is Power Automate? (flow types) - Microsoft Learn](https://learn.microsoft.com/en-us/power-automate/flow-types)
- [Document processing model overview - AI Builder | Microsoft Learn](https://learn.microsoft.com/en-us/ai-builder/form-processing-model-overview)
- [Use the document processing model in Power Automate - AI Builder | Microsoft Learn](https://learn.microsoft.com/en-us/ai-builder/form-processing-model-in-flow)
- [Power Automate licensing FAQ - Power Platform | Microsoft Learn](https://learn.microsoft.com/en-us/power-platform/admin/power-automate-licensing/faqs)
- [Power Automate Pricing | Microsoft Power Platform](https://www.microsoft.com/en-us/power-platform/products/power-automate/pricing)
- [Forums: Bypass Google Recaptcha - Power Platform Community](https://powerusers.microsoft.com/t5/Power-Automate-Desktop/Bypass-Google-Recaptcha/td-p/1137359)
