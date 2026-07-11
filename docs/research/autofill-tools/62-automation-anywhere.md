# Automation Anywhere —— 自动填表实现调研

- 项目地址/官网: https://www.automationanywhere.com/ ，文档中心 https://docs.automationanywhere.com/
- 类型: 闭源（RPA 企业级工具，可配置用于网页表单填写，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Automation Anywhere 当前主打产品是 **Automation 360**（简称 A360），架构分三大部分：

- **Control Room**：集中式编排/治理平台，负责部署、调度、凭证管理、审计日志、权限（RBAC）等，是所有 Bot 的"控制平面"。云版本（Automation 360 Cloud）中 Control Room 作为 SaaS 服务随订阅提供，无需单独安装服务器。
- **Bot Creator**：Web 化的开发客户端（Workbench），用于录制/编写自动化流程（"Bot"）。A360 相比早期 v11 版本把整个开发端重写为 Web UI。
- **Bot Runner / Bot Agent**：实际执行 Bot 的运行时代理，基于 Java 的执行引擎，安装在目标机器（本地设备、VM 或云端 Runner）上，与 Control Room 通信获取任务并回报结果。

文档强调 A360 具备"云原生"特性：微服务架构、容器化基础设施、CI/CD 部署框架，可通过复制所需微服务实现水平扩展；并提供高可用/灾备（HA/DR）能力（参见 docs.automationanywhere.com 的 "Bot Agent-Control Room resiliency" 页面）。

网页表单自动化具体通过以下命令/包实现：

1. **Recorder 包（Universal Recorder）**：A360 把早期版本中 Screen/Standard Recorder、Object Recorder、Web Recorder 三种录制器整合为统一的 "Universal Recorder"，可录制对桌面、任务栏、应用或浏览器窗口内 UI 对象的点击（click）、读取（read/抓取数据）、写入（write/表单填值）操作。录制时点击一个网页元素，Recorder 会抓取该元素的属性（如 HTML DOM 属性），用于运行时重新定位该元素。
2. **Object Cloning 命令**：更底层的元素捕获方式，可指定目标技术（HTML、Java、Flex、Silverlight 等），抓取对象的 X/Y 坐标、对象属性，并可选附带图像信息，用于对象化（基于 DOM/控件树）识别 UI 元素，比纯坐标/图像方式更稳健。
3. **图像识别兜底（Image Recognition / Visualize 技术）**：当目标控件无法通过对象属性识别时（如非标准控件、Flash/Silverlight 遗留控件、远程桌面/虚拟化环境），退化为基于屏幕截图比对的图像识别方式定位元素。
4. **AISense Recorder（计算机视觉）**：面向复杂 UI 或远程/虚拟化应用场景的机器学习screen recorder，通过对应用界面截图做计算机视觉目标检测，自动从图像中识别出所有 UI 控件对象，官方称其模型基于"数千张图像与数百万控件示例"训练，具备对分辨率、缩放比例、UI 变动的一定鲁棒性。

因此 Automation Anywhere 的网页表单填写是"录制 + 对象化元素识别（DOM/控件属性）为主，图像识别/计算机视觉为兜底"的组合模式，与 UiPath、Power Automate 等主流 RPA 工具的技术路线基本一致。

典型的"从 Excel/CSV 批量填写网页表单"场景（文档中 "Example of entering data into a webform from a file" 一节标题可见）通常组合：Recorder/Object Cloning 捕获表单字段 → CSV/Excel 包读取数据源 → Loop 循环遍历每行 → 变量映射写入对应表单字段。

## 技术栈（推测）

- Control Room：Java 微服务架构，容器化部署（Kubernetes 类基础设施），支持云端 SaaS 与本地/私有云部署。
- Bot Agent/Runner 执行引擎：Java 编写。
- Bot Creator（Workbench）：Web 前端（浏览器内使用，无需本地安装即可开始搭建 Bot）。
- 元素识别：DOM/HTML 属性抓取（网页）、Windows UI Automation / Microsoft Active Accessibility（桌面/Java 应用）、图像匹配算法、以及 AISense 的计算机视觉/机器学习模型。
- IQ Bot / Document Automation：独立的智能文档处理（IDP）模块，基于机器学习做非结构化/半结构化文档（含简历）字段抽取，随人工校验持续学习优化抽取准确率。
- 生成式 AI 层（Automator AI / Automation Co-Pilot）：可对接 Microsoft Azure OpenAI、Google Vertex AI、Amazon Bedrock、Nvidia NeMo 等外部大模型服务，用于自然语言生成自动化流程骨架。

## 支持平台/网站

- 官方文档列出 Universal Recorder 支持的应用/浏览器包括 Google Chrome、Internet Explorer、Java 应用、基于 Microsoft Active Accessibility 与 Microsoft UI Automation 的桌面应用，要求屏幕缩放为 100% 或 125%。
- 作为通用 RPA 平台，理论上可对任意基于浏览器渲染的网站进行操作（不区分招聘网站或普通网站），没有为特定招聘平台（如 LinkedIn、Boss直聘等）提供专用连接器；如需适配某招聘网站，需要用户自行录制/编写对应流程。
- 官方也提供大量预制的"Bot Store"连接器（多为企业 SaaS 系统，如 Salesforce、SAP、ServiceNow 等），未见公开的求职网站专用连接器。

## 自动化程度（全自动 / 半自动，人工介入点）

- 一旦 Bot 编写/录制完成并部署到 Control Room，日常运行是"全自动"的：由 Control Room 按计划或触发条件调度 Bot Runner 执行，无需人工逐次操作。
- 但整个方案属于"半自动"性质，因为：
  - 首次搭建（录制、定位元素、编写流程逻辑、异常处理分支）需要人工完成，且当目标网页结构变化时，识别对象失效，需要人工重新录制/调整选择器。
  - IQ Bot/Document Automation 在文档抽取的"学习阶段"需要人工标注与校验（human-in-the-loop），抽取模型通过每次人工校正持续改进。
  - 企业场景下通常配置"异常队列"，遇到无法处理的页面/字段/验证码时，Bot 会将任务转入人工处理队列，等待人工介入后继续。

## 反爬虫/验证码/风控应对

官方文档中未见任何针对 CAPTCHA 或反爬虫机制的原生解决方案 —— Automation Anywhere 定位是企业内部流程自动化工具（面向企业自有系统、合作方系统的正常业务流程），不是为绕过网站反爬/反机器人机制设计的抓取或"刷"工具。公开资料与行业讨论（包括对同类工具 UiPath 的分析）普遍指出：

- 现代 CAPTCHA（如 reCAPTCHA v3）依赖鼠标移动轨迹、按键节奏、浏览器指纹、IP 信誉等大量行为信号打分，RPA 机器人由于操作模式机械化（毫秒级精确点击、无自然鼠标轨迹、自动化框架指纹）很容易被判定为非人类。
- 企业 RPA 项目遇到验证码通常采用：接入第三方打码/验证码识别服务（如 2Captcha、Anti-Captcha 等，需要额外集成，非 Automation Anywhere 自带能力）；或采用 human-in-the-loop 方案，Bot 遇到验证码时暂停并将任务转交人工处理后再继续。
- 未检索到 Automation Anywhere 官方提供或背书的验证码绕过功能；相反，其安全与合规定位（审计日志、权限管控）说明产品设计假设是在被自动化的系统"授权/许可"下运行，而非用于对抗反自动化机制的场景。

## 应用于求职投递场景的可行性简评

理论上可行，但性价比与工程量都不匹配"求职投递"这种轻量级个人自动化需求：

- 优点：对象化识别 + 图像识别兜底的组合方案技术上足以应对结构相对稳定的招聘网站表单填写；配合 Document Automation/IQ Bot 可实现"简历字段抽取 → 映射填入网页表单"的链路；Automator AI/Co-Pilot 的自然语言建流程能力理论上能降低开发门槛。
- 但企业级授权/部署模式（Control Room 订阅制、按 Bot Runner/Creator 收费）、面向企业 IT 治理设计的架构（审批流、RBAC、审计）都是为大型组织内部流程设计，个人求职者部署成本（时间、金钱、学习曲线）远高于收益。
- 招聘网站的反爬/反机器人策略（验证码、行为分析、登录风控）恰恰是 Automation Anywhere 未内置解决的短板，个人使用时更容易触发平台风控被封号。

## 局限性

- 闭源商业软件，核心识别算法、AISense 模型细节、Control Room 内部实现均不公开，只能通过官方文档/博客反推行为，无法验证具体实现细节。
- 面向企业 IT 部门而非个人开发者，获取、部署、许可成本高，不适合个人求职自动化的"轻量"场景。
- 对页面结构变化、动态渲染、反自动化机制的鲁棒性依赖官方未公开的具体算法，公开资料无法给出量化的成功率或稳定性数据。
- 未发现官方对"求职网站""简历投递"场景的专门支持或案例，本文中的适配可行性分析属推测，未经实测验证。

## 参考来源
- https://www.automationanywhere.com/company/blog/thought-leadership/why-your-business-should-move-automation-360-cloud
- https://www.automationanywhere.com/company/blog/thought-leadership/build-future-value-true-cloud-native-platform
- http://docs.automationanywhere.com/r/cloud-automation-anywhere-enterprise-overview/bot-agent-control-room-resiliency
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/control-room/getting-started/cloud-getting-started.html
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/aae-client/bot-creator/using-the-workbench/cloud-using-the-recorder.html
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/aae-client/bot-creator/using-the-workbench/universal-recorder-supported-applications-and-browsers.html
- https://docs.automationanywhere.com/bundle/enterprise-v11.3/page/enterprise/topics/aae-client/bot-creator/commands/object-cloning-command.html
- https://docs.automationanywhere.com/bundle/enterprise-v11.3/page/enterprise/topics/aae-client/bot-creator/commands/using-select-technology.html
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/aae-client/bot-creator/using-the-workbench/cloud-aisense-overview.html
- https://www.automationanywhere.com/company/blog/product-insights/build-and-automate-bots-faster-on-a-virtual-machine-with-aisense
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/release-notes/v28-release-document-processing.html
- https://docs.automationanywhere.com/bundle/enterprise-v2019/page/enterprise-cloud/topics/iq-bot/cloud-iqb-process-overview.html
- https://intuerainc.com/iq-bot-vs-docai/
- https://www.automationanywhere.com/company/press-room/automation-anywhere-unveils-expanded-generative-ai-powered-automation-platform
- https://www.automationanywhere.com/products/automator-ai
- https://www.techtarget.com/searchenterpriseai/news/366552517/Automation-Anywhere-intros-new-generative-AI-tools
- http://docs.automationanywhere.com/r/cloud-build/cloud-work-area/a2019-build-bots-examples-list/enter-data-into-webform-from-file
- https://forum.uipath.com/t/rpa-recaptcha-solutions-uipath/237767
- https://blog.addmeintop10.com/rpa-workflows-captcha-handling
