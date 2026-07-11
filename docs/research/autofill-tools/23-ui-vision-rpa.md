# UI.Vision RPA —— 自动填表实现调研

- 项目地址/官网: https://ui.vision/rpa （官方站点） ｜ 源码: https://github.com/A9T9/RPA
- 类型: 开源（通用浏览器/Agent自动化框架，非专为求职），个人及商业使用免费
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测。原因：主要依据官网 `ui.vision/rpa` 文档站、GitHub README（A9T9/RPA）以及社区论坛内容整理，未直接克隆源码逐行阅读实现细节，部分内部机制（如选择器降级策略的具体代码路径）是根据文档描述推断的。

## 核心实现方式

UI.Vision（原名 Kantu）是一个浏览器扩展（Chrome / Edge / Firefox），核心是"录制 - 回放"式的 Selenium IDE 兼容自动化工具，同时叠加了计算机视觉（Computer Vision/OCR）能力：

1. **录制层**：用户在浏览器中手动执行一遍操作（点击、输入、跳转等），扩展的 Web Macro Recorder 记录下每一步，生成宏（macro）。
2. **定位层**：默认优先使用 **CSS 选择器 / XPath** 定位页面元素（与 Selenium IDE 的 `.side` 格式一致），这是常规 DOM 自动化路径。
3. **视觉兜底层**：当元素无法通过 DOM 选择器可靠定位时（例如 Canvas 渲染的内容、iframe/跨域内嵌页面、桌面原生控件、图形验证码图片等），可切换到基于图像识别的 **Visual Automation**（`VisualSearch`/`VisualClick`/`VisualVerify` 等命令），即用一张截取的小图片作为"目标图案"，在屏幕/页面截图中做图像匹配后再执行点击/输入。官网称其为"the first and only Chrome/Firefox extension that has 👁👁 eyes"，强调这是与纯 DOM 方案的差异化能力。
4. **XModules（原生扩展模块）**：为突破浏览器扩展的沙箱限制，UI.Vision 提供可选安装的本地原生组件（RealUser XModule、Desktop Automation XModule、File Access XModule 等），用于模拟更底层的鼠标/键盘事件（不经过 `dispatchEvent` 而是操作系统级别的事件），以及读写本地文件系统中的宏、CSV、图片素材，并可将自动化范围从浏览器扩展到桌面应用。
5. **新增的 AI Agent 层（V9.3.8+）**：近期版本引入了 `aiComputerUse` 命令，接入 Anthropic Claude 的 Computer Use API——这与"录制回放"是不同的执行模式：不再依赖预录制脚本，而是把当前截图和自然语言任务描述发给 Claude，由模型自主决策下一步该点击/输入什么，循环执行直至任务完成或达到最大循环次数（文档示例中提到默认上限 20 次循环，避免无限调用产生高额 API 费用）。

## 技术栈

- 前端/扩展主体：JavaScript + TypeScript（GitHub 仓库语言占比约 JS 48% / TS 47%），构建工具为 Webpack + Babel + PostCSS，Node v20.11.1 / NPM v10.2.4。
- 原生 XModules：跨平台原生程序（Windows/Mac/Linux 各自实现，文档提到用到 PowerShell、VBScript、AppleScript 等平台脚本能力）。
- 宏存储：标准 **JSON** 格式（与 Selenium IDE 的 `.side` 文件结构兼容，可互相导入导出），宏、测试套件默认保存在浏览器的 HTML5 LocalStorage 中，安装 File Access XModule 后也可直接读写本地 `/macros`、`/testsuites`、`/images` 目录下的文件。
- 命令体系沿用 Selenium IDE 的 Selenese 命令族（`click`、`type`、`store`、`storeText`、`storeAttribute`、`storeEval` 等），并扩展了流程控制（if/else、while 循环）和 40+ 内置变量（控制回放速度、超时、CSV 读写、错误处理如 `!ErrorIgnore` 等）。

## 支持平台/网站

- 浏览器：Chrome、Edge、Firefox（扩展商店直接安装）。
- 操作系统：Windows、macOS、Linux（原生 XModules 支持三大平台）。
- 由于核心是"通用 DOM 选择器 + 视觉匹配"的组合，理论上可用于任意网站，不针对特定招聘平台做适配；能否稳定工作取决于目标页面结构是否频繁变化、是否有强反自动化机制。

## 自动化程度（全自动 / 半自动，人工介入点）

- 传统 Selenium IDE 模式：**半自动 —— "录制一次，回放多次"（record-once-replay-many）**。人工介入点在于：
  1. 首次必须由人手动演示一遍完整操作流程供录制；
  2. 遇到页面结构变化、选择器失效、验证码等异常时，宏会执行失败，需要人工检查并修改宏（例如切换到视觉匹配、手动暂停等待人工处理验证码）。
- 新的 `aiComputerUse`（Claude Computer Use）模式：更接近"自主 Agent"，不需要逐步录制脚本，只需给出自然语言任务描述，由模型截图+推理自主操作；但仍需要人工设置任务提示词、配置 Anthropic API Key/额度，并对循环次数、成本进行人工把控，遇到边界情况仍可能卡住需要人工介入。
- 两种模式都不是无人值守的"黑箱全自动"：录制模式的鲁棒性依赖人工预先编排的固定脚本，AI Agent 模式虽然更灵活，但会产生真实 API 调用成本，也未见文档声明可无监督长期运行。

## 反爬虫/验证码/风控应对

- 官方文档中**未见**任何专门针对"绕过检测/反爬虫"设计的机制；UI.Vision 定位是合法的 RPA/测试工具，而非专门对抗网站风控的爬虫框架。
- 关于验证码：社区论坛（forum.ui.vision）中有用户讨论"如何检测 reCAPTCHA 出现并暂停宏等待人工手动解决"，说明官方原生能力里**没有自动识别/跳过验证码**的功能，通常需要人工在宏运行到验证码步骤时手动介入解决。
- 第三方生态中存在把 UI.Vision 与商业验证码解答服务（如 CapSolver）结合使用的教程/插件，通过外部 API 自动解析 reCAPTCHA、Cloudflare Turnstile 等，但这是社区/第三方方案，并非 UI.Vision 官方内置能力。
- 总体结论：UI.Vision 本身不做"反侦测"设计（例如伪造浏览器指纹、模拟人类行为节奏避免被识别为 bot 等并非其核心卖点），遇到网站主动拦截自动化流量或验证码时，默认策略是失败/需人工干预，而非自动绕过。

## 应用于求职投递场景的可行性简评

- 优势：
  - "录制一次、回放多次"的模式非常契合"在同一招聘平台反复填写相似表单"的场景（如：登录、填写个人信息、上传简历、点击投递按钮），可以针对某个招聘网站录制一条标准投递宏，之后批量对不同职位重复执行（结合 CSV 数据驱动，可为不同职位/公司填入不同变量）。
  - CSS/XPath 选择器覆盖大多数标准 HTML 表单；遇到用 Canvas 渲染或复杂 JS 组件（如某些自定义下拉框、拖拽上传控件）导致选择器失效时，可以用视觉匹配兜底，减少"选择器找不到元素"导致的中断。
  - 开源、本地运行、无需服务器部署，符合项目"CLI优先、简单可控"的路线图。
- 局限（结合求职投递场景）：
  - 招聘网站页面结构经常变化（不同职位详情页布局差异、A/B 测试等），固定选择器的宏容易失效，维护成本高，且没有自愈能力。
  - 遇到登录验证码、滑块验证、人机验证时需要人工干预，无法做到无人值守的批量投递。
  - 新的 AI Agent（Claude Computer Use）模式理论上更灵活，能适应页面变化，但按截图+推理循环调用计费，单次任务成本明显更高（文档提到一次 Computer Use 任务约 $0.30 vs 简单 AI 命令约 $0.01），大规模批量投递场景下成本会显著上升。
  - 作为通用浏览器扩展工具，缺乏对招聘网站结构的专门适配（不像专门爬虫/投递工具那样内置各平台的解析规则），需要使用者自行为每个目标网站编写/维护宏。

## 局限性

- 面向通用网页自动化/RPA/测试，不是专为求职投递设计，需自行为目标招聘网站编写宏并维护其稳定性。
- 传统录制回放模式对页面结构变化脆弱，容错和"自愈"能力有限；视觉匹配虽然是兜底手段，但对目标图片的分辨率、UI 主题变化也敏感。
- 官方文档未声明具备躲避反爬虫/验证码检测的能力，遇到强风控网站（含验证码墙）仍需人工介入。
- AI Agent（Claude Computer Use）模式虽引入了LLM自主决策，但按调用计费、有循环次数上限，且是较新功能，成熟度、稳定性有待验证，也不等同于面向求职场景优化的智能体。
- 本次调研基于官网文档、GitHub README 及社区论坛内容，未实际安装运行验证具体行为，细节以官方最新文档为准。

## 参考来源
- https://github.com/A9T9/RPA
- https://github.com/A9T9/RPA/blob/master/README.md
- https://ui.vision/rpa
- https://ui.vision/rpa/docs/
- https://ui.vision/rpa/x
- https://ui.vision/ai/computeruse
- https://ui.vision/rpa/docs/selenium-ide/
- https://forum.ui.vision/t/detect-recaptcha-i-am-not-a-robot/4657
- https://forum.ui.vision/t/wait-for-image-captcha-to-be-solved/4114
- https://www.capsolver.com/blog/All/uivision-capsolver
