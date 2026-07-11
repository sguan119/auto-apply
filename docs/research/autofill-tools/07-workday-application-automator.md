# Workday-Application-Automator —— 自动填表实现调研

- 项目地址/官网: https://github.com/ubangura/Workday-Application-Automator （作者已声明弃用，后续项目为 SnapFill 浏览器插件 https://snapfill.pages.dev）
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 GitHub 直接读取 README、`apply.js`、`utils.js`、`information.js`、`package.json` 的实际内容/摘要，而非仅凭项目描述推测）

## 核心实现方式

这是一个 **Node.js 脚本**，本质上是一个本地运行的浏览器自动化程序，而不是浏览器扩展、书签脚本（bookmarklet）或用户脚本（userscript）。使用方式为：

1. `git clone` 仓库到本地
2. `npm install puppeteer`
3. 在 `information.js` 中手工填入个人信息（姓名、地址、教育经历、工作经历数组、简历文件路径、人口统计信息等）
4. 在 `apply.js` 中指定目标 Workday 职位 URL
5. 执行 `node apply.js`

仓库文件很少（`apply.js`、`utils.js`、`information.js`、`package.json` 等），没有 UI 界面、没有服务端、没有打包成扩展。

值得注意：作者在 README 顶部注明该仓库**已被归档、不再维护**，并表示正在用 Chrome 扩展的形式重写（SnapFill，"no Node.js, no terminal, no manual config"），说明作者自己也认为 Node 脚本这种形态存在使用门槛过高的问题。

## 技术栈

- 语言：JavaScript（ES Module，`"type": "module"`）
- 唯一依赖：`puppeteer`（`package.json` 中锁定 `^24.43.1`）
- 浏览器自动化 API：使用 Puppeteer 较新版本内置的 **Locator API**（`page.locator(selector)`），而非 Selenium 或 Playwright（尽管命名风格上 `locator` 容易让人联想到 Playwright，实际是 Puppeteer 自带的同名机制）
- 运行模式：`headless: false`，即以有头浏览器方式启动，运行过程中用户可以在浏览器窗口里实时看到自动化操作

## 支持平台/网站

仅针对 **Workday** 招聘系统（`myworkdayjobs.com` 等 Workday 托管的申请门户），不支持其他 ATS（如 Greenhouse、Lever、iCIMS 等）。README 明确说明目标是"减少在多个使用 Workday 的公司之间重复填写相同基础信息"的痛苦。

## 自动化程度（全自动 / 半自动，人工介入点）

- **配置阶段（人工）**：用户必须手动编辑 `information.js`（个人信息，含工作经历数组 `workexperiences`、教育信息、人口统计学问题的答案等）以及在 `apply.js` 中填入目标职位 URL。这是一次性/低频的人工介入，不是每次投递都要做。
- **运行阶段（脚本自动执行，但可视化监督）**：脚本以非无头模式启动浏览器，依次完成：
  1. 账号登录（若不存在则尝试注册）
  2. 点击进入申请流程
  3. 依次填写多个分页表单：基础联系方式 → 工作经历 → 教育经历 → 自愿披露（人口统计学）→ 自我认定（残疾状况）
  4. 上传简历文件（`uploadFile()`）
  5. 提交表单
- 据抓取到的代码分析摘要，脚本设计上是"整段自动跑完、无需用户在运行过程中输入"，即偏向**全自动**（作者选择 `headless: false` 更多是为了方便用户观察/必要时人工介入纠错，而非强制要求人工确认每一步）。
- README 本身没有强调"提交前需要人工二次确认"这一设计，也没有内置人工审核环节；是否要在提交前手动打断，取决于用户是否在浏览器窗口手动干预。

## Workday 表单复杂度的处理方式

Workday 表单的两个典型难点及该项目的应对方式：

- **多分页表单**：`apply.js` 按照 Workday 申请流程的固定分页顺序（联系方式 → 工作经历 → 教育 → 自愿披露 → 自我认定）依次调用对应的填写逻辑，属于**按页面结构硬编码流程**，而非通用/自适应的表单解析。
- **工作经历重复区块（work history repeater）**：通过形如 `workExperience-${addedWorks}` 的选择器动态生成，脚本会按 `information.js` 中 `workexperiences` 数组的长度循环，在需要时点击"添加一段工作经历"来动态创建新条目，从而支持多条工作经历。
- **动态/可搜索下拉框**：不是通过硬编码的 `<option>` value/id 去选择，而是用 `page.keyboard.type()` 输入文本后按 `Enter` 确认，这样可以适配 Workday 那种基于搜索过滤的下拉组件，无需预先知道每个下拉选项的内部 ID。
- **元素存在性容错**：`utils.js` 中的 `selectorExists()`（等待 1 秒判断元素是否存在）与 `withOptSelector()`（可配置超时、区分"超时未找到"与"其他异常"两种情况）用于处理可选字段/页面结构轻微差异的情况，避免因某个字段缺失而整个流程崩溃。

## 反爬虫/验证码/风控应对

代码与文档中**没有任何 CAPTCHA 识别、验证码绕过、代理池、限速控制或反爬虫对抗**相关的逻辑。项目采用的方式是"有头浏览器、模拟真实点击/键盘输入"，本质上依赖模拟人类操作行为来降低被检测概率，但没有专门设计应对滑块验证码、reCAPTCHA、行为分析等风控手段。若目标 Workday 门户触发验证码，脚本大概率会卡住，需要人工介入处理。

## 局限性

- 项目已被作者标注为**归档/不再维护**，仅覆盖"基础字段"，README 原文："requires manual setup and only covers basic fields"。
- 仅支持 Workday 一家 ATS，且是针对特定页面结构/选择器硬编码的流程，Workday 前端一旦改版，选择器容易失效。
- 需要本地 Node.js 环境和命令行操作，对非技术用户不友好（这也是作者决定另起炉灶做 Chrome 扩展 SnapFill 的原因）。
- 完全不涉及 AI/LLM：整个项目未使用任何大模型或语义匹配能力，字段映射靠用户在 `information.js` 里手工预先结构化好的数据，脚本只是按固定顺序把这些数据"打"到已知的表单位置上。
- 没有验证码/风控应对能力，遇到强风控页面会失败。
- 没有内置"提交前二次确认"的强制人工审核环节，误投风险需要用户自行通过 `headless: false` 的可视化窗口去监督。

## 参考来源
- https://github.com/ubangura/Workday-Application-Automator
- https://github.com/ubangura/Workday-Application-Automator/blob/master/README.md
- https://github.com/ubangura/Workday-Application-Automator/blob/master/apply.js
- https://github.com/ubangura/Workday-Application-Automator/blob/master/utils.js
- https://github.com/ubangura/Workday-Application-Automator/blob/master/information.js
- https://github.com/ubangura/Workday-Application-Automator/blob/master/package.json
- https://snapfill.pages.dev （作者提到的继任项目，Chrome 扩展形态）
