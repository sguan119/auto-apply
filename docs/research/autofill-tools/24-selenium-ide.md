# Selenium IDE —— 自动填表实现调研

- 项目地址/官网: https://github.com/SeleniumHQ/selenium-ide ；文档 https://www.selenium.dev/selenium-ide/
- 类型: 开源（通用浏览器/Agent自动化框架，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（README、官方文档站通过 WebFetch 抓取核实，未在本地实际安装/运行源码或跑通录制回放流程，部分细节如具体选择器算法实现未读源码验证）

## 核心实现方式

Selenium IDE 是一个 JavaScript/TypeScript monorepo 项目，核心是一个基于 **Electron + React** 的桌面应用（早期版本是 Firefox/Chrome 浏览器扩展，后重写为独立 Electron 应用）。其工作流程是经典的"录制-回放"（record & playback）模式：

1. **录制**：用户在 IDE 中设置起始 URL 并点击录制按钮后，IDE 会打开一个浏览器窗口；用户在页面上进行的交互操作会被实时记录进 IDE 界面，形成一系列"命令"（command），录制结束后可保存为 **`.side` 项目文件**（JSON 格式，包含测试套件、测试用例、每一步的命令/目标元素定位符/参数等）。
2. **回放**：`.side` 文件由 `side-runtime` 包（回放引擎）解释执行，依次对目标页面重放录制时记录的每一步操作；也可以用命令行工具 `side-runner`（基于 NodeJS + TypeScript）在无 GUI 环境、CI/CD 流水线中批量执行 `.side` 文件，支持跨浏览器/操作系统并行运行。

Monorepo 内主要子包（来自 README）：
- `selenium-ide`：主 Electron 应用（webpack + React 前端，IPC 通信）
- `side-runner`：命令行任务执行器
- `side-runtime`：回放执行核心
- `side-api`：插件用的类型定义
- `side-model`：标准命令与参数类型的元数据
- `side-code-export` 及 `code-export-*`：将 `.side` 文件转译为多语言 Selenium WebDriver 代码的转译器

## 技术栈

- NodeJS / TypeScript / Electron / React（桌面应用与前端）
- 底层依赖 Selenium WebDriver 生态（导出代码即标准 Selenium WebDriver 脚本）
- 无任何 AI/LLM 相关依赖或功能：官方文档与 README 中均未提及模型推理、视觉理解或语言模型集成，是一套**纯确定性**的录制回放工具（选择器 + 命令序列的直接重放）。

## 支持平台/网站

通用型工具，不针对特定招聘网站或平台设计，理论上可用于任意基于浏览器渲染的网页表单（包括求职网站的职位申请表单）。不提供针对特定站点（如 LinkedIn、BOSS直聘等）的专用适配层。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动，"录制一次、多次回放"模式：

- **人工介入点**：必须先由人手动执行一遍完整流程（打开页面、点击、输入文字、下拉选择等），IDE 才能生成 `.side` 脚本；录制阶段是完全依赖人的操作演示。
- **回放阶段**：一旦脚本录制完成，回放可以是无人值守的（IDE 内回放或通过 `side-runner` 命令行/CI 批量执行），但当页面结构、字段、跳转流程发生变化时，脚本容易失效，需要人工重新录制或手动编辑 `.side` 文件/导出代码进行修复。
- 不具备理解页面语义、动态适应新表单结构的能力，属于"演示一次，机械复现"，没有类似 LLM Agent 那样的自主决策/纠错能力。

官方文档强调的"Resilient Tests"（弹性测试）特性：**"Selenium IDE records multiple locators for each element it interacts with. If one locator fails during playback, the others will be tried until one is successful."**（Selenium IDE 会为每个交互元素记录多个定位符；回放时若某个定位符失败，会依次尝试其余定位符，直到成功为止）。这是其鲁棒性的核心机制——录制时对同一元素生成多种选择器策略（如 id、CSS、XPath、name、link text 等，具体优先级算法未在本次抓取的文档中看到详细说明），回放时按顺序容错尝试，而非语义级理解页面变化。README 中也提到未来改进方向包括"Selectors accuracy - 对选择器进行准确性排序优化"，说明该机制仍在持续迭代中，并非完美。

支持导出为多语言 Selenium WebDriver 测试代码：C#、Java、JavaScript、Python、Ruby，方便测试人员将录制的浏录像转成正式的自动化测试代码进行二次开发和维护。

## 反爬虫/验证码/风控应对

无。官方 README 与文档中完全没有提及 CAPTCHA 处理、指纹伪装、行为随机化等反检测/反爬虫能力。Selenium IDE 定位是 **QA/测试工具**，其自动化流量特征（WebDriver 协议驱动的浏览器）本身容易被网站的反自动化检测识别（例如 `navigator.webdriver` 标志位），项目设计目标是测试自身产品/网站，而非绕过第三方网站的反爬虫/反机器人机制。

## 应用于求职投递场景的可行性简评

- 优点：零代码即可录制"打开职位页 → 点击申请 → 填写表单字段 → 提交"的完整流程，对于**同一网站、表单结构长期不变**的重复投递场景（如反复给同一批固定几个网站投递不同职位）有一定实用性；可导出为 Selenium WebDriver 代码后集成进现有 Python/JS 自动化管道，与本项目"投递（deliver）"模块的自动化诉求方向一致。
- 缺点/风险：
  1. **脆弱性**：不同职位/公司的申请表单字段、页面结构差异很大，"录制一次复用所有职位"的假设在求职场景下很难成立，几乎每个新网站/新表单都要重新录制。
  2. **无智能内容生成能力**：只是机械回放固定文本/固定顺序的点击输入，无法根据不同职位 JD 动态调整投递内容（如是否需要针对性回答问答题），需要额外结合本项目的"改简历"模块或人工填充变量。
  3. **无反检测能力**：直接用 Selenium WebDriver 驱动浏览器容易被主流招聘网站的风控识别并拦截/封号，实际生产环境使用风险较高。
  4. **无 CAPTCHA 处理**：遇到验证码会直接卡住，需要人工介入或额外接入打码服务。

综合来看，Selenium IDE 更适合作为**原型验证/一次性小规模场景**的候选方案（例如内部测试同一个自定义 ATS 后台的重复性操作），不建议作为大规模、跨平台自动投递的核心方案，可作为"导出代码 + 二次开发"的起点，但仍需自行补充选择器容错升级、反检测、动态内容注入等能力。

## 局限性

- 纯确定性录制回放，无语义理解/自愈能力，页面结构变化后极易失效。
- 无 AI/LLM 集成，无法理解职位描述、无法智能匹配/生成回答内容。
- 无反爬虫/反机器人对抗能力，无验证码处理，暴露于目标网站风控之下。
- 面向 QA/测试场景设计，缺乏针对求职投递的专用适配层（如简历上传、多平台账号管理等）。
- 本次调研受限于公开文档抓取，未实际安装运行验证录制/回放/导出代码的具体效果，部分细节（如选择器优先级算法、`side-runner` 参数详情）未能完全确认，抓取部分文档页面（如 command-reference、side-runner 专页）返回 404，可能是文档路径已变更。

## 参考来源
- https://github.com/SeleniumHQ/selenium-ide
- https://github.com/SeleniumHQ/selenium-ide/blob/trunk/README.md
- https://www.selenium.dev/selenium-ide/
- https://www.selenium.dev/selenium-ide/docs/en/introduction/getting-started
