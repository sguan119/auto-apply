# job_app_filler —— 自动填表实现调研

- 项目地址/官网: https://github.com/berellevy/job_app_filler
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 GitHub API 拉取完整文件树，并直接读取 README、manifest.json、package.json、CHANGELOG.md 及多个核心源码文件的原始内容，如 `baseFormInput.tsx`、`inject.ts`、`fieldFillerQueue.ts`、`stringMatch.ts` 等）

> 说明：搜索 "job_app_filler" 时命中多个同类小项目（如 `bdcorps/easy-job-application-filler-extension`、`lovincyrus/job-autofiller`、`Anioko/JobBot` 等），但 `berellevy/job_app_filler` 是与目标名称完全一致、且有持续提交记录（471 次提交，最近推送于 2025-02）的仓库，故选定该项目作为调研对象。仓库规模较小（26 stars，16 forks），属于个人维护的小型工具，非大型/知名项目。

## 核心实现方式

job_app_filler 是一个 **Chrome 浏览器扩展**（Manifest V3），不是独立脚本或 RPA 工具。其架构分三层：

1. **content script**（`src/contentScript/contentScript.ts`）：运行在隔离环境中，负责与扩展的本地存储（`DataStore`）通信，管理用户保存的历史答案。
2. **injected script**（`src/inject/inject.ts`）：被注入到页面的主世界（main world），直接操作 DOM/React 受控表单元素（content script 因隔离无法直接触发 React 状态更新，所以需要注入脚本绕过这一限制）。
3. 两者之间通过自定义 DOM 事件实现「客户端-服务端」式请求/响应通信（`src/shared/utils/crossContextCommunication/{client,server}.ts`）。

字段发现与填充逻辑集中在 `BaseFormInput` 抽象基类（`src/inject/app/services/formFields/baseFormInput.tsx`）：
- 每个具体网站/字段类型的子类定义一个静态 `XPATH` 属性；
- `static async autoDiscover(node)` 用 XPath 在 DOM 中查找匹配元素，通过一个 `job-app-filler` 属性判重，避免重复注册；
- 每个被发现的输入框会实例化为一个 `BaseFormInput` 子类对象，并挂载一个小型 React 应用（`attachReactApp()`），在该字段旁渲染出「填充 / 保存 / 更多信息」等按钮（`FieldWidget/FillButton.tsx`、`SaveButton.tsx`、`MoreInfoButton.tsx`）。
- `inject.ts` 中用 `MutationObserver` 持续监听 DOM 变化，在页面动态渲染新字段（如 Workday/Greenhouse 的分步表单、重复区块）时重新触发发现逻辑（`RegisterInputs(document)`）。

未在 `fieldFillerQueue.ts`（一个通用异步任务队列，`AsyncQueue` 单例）中发现「一键填充全部字段并提交」的批量自动化逻辑；该队列只是保证多个填充/保存任务顺序执行的基础设施，实际触发仍来自逐字段的用户交互（点击各字段旁的 Fill 按钮）。

## 技术栈

- **前端**：TypeScript + React 18 + Material UI (`@mui/material`, `@mui/icons-material`) + Emotion（样式）
- **构建**：Webpack 5（`webpack.common/dev/prod.js`）+ ts-loader，产物为标准 Chrome 扩展 `dist` 目录，需手动通过 `chrome://extensions` 「加载已解压的扩展程序」安装
- **辅助库**：lodash、uuid、elasticlunr/lunr（用于历史答案的检索/匹配）
- 未使用 Puppeteer/Playwright/Selenium 等浏览器自动化框架 —— 完全依赖浏览器扩展 API（content script + 注入脚本），不是无头浏览器方案
- `package.json` 中没有任何生产环境依赖（`dependencies` 为空），所有库都在 `devDependencies` 中，通过 Webpack 打包进最终扩展产物

## 支持平台/网站

以 `src/static/manifest.json` 的 `content_scripts.matches` 为准（这是实际生效的匹配范围）：

- `https://*.myworkdayjobs.com/*`
- `https://*.myworkdaysite.com/*`
- `https://*.greenhouse.io/*`

源码目录中也印证了针对性实现：`formFields/workday/`（含 Dropdown、日期、文件上传、密码、单选/多选等多种字段类型）、`formFields/greenhouse/` 与 `formFields/greenhouseReact/`（Greenhouse 传统版与 React 版分别适配，因为两者 DOM 结构不同）。

需要指出一处 **README 与实际代码不一致**：README 文案提到支持 "workday, icims, etc."，但 manifest.json 的 host 匹配范围里**并没有 iCIMS 域名**，源码目录中也没有 iCIMS 专属的 formFields 实现。可以判断 iCIMS 支持要么是早期计划中尚未落地，要么是文档过时未更新。CHANGELOG 中同样只能看到 Greenhouse（v2.1.0 起新增）和 Workday 的详细字段支持记录，iCIMS 未见具体版本记录。

## 自动化程度（全自动 / 半自动，人工介入点）

整体是 **半自动 / 人工介入型工具**，而非"一键投递"：

- 页面加载后，扩展会在每个可识别的表单字段旁挂一个小型悬浮 UI（Fill / Save / More Info 按钮），需要用户**逐字段点击 Fill** 才会把已保存的历史答案填入该字段；没有发现"一键填充整页表单"或"自动点击提交按钮"的逻辑。
- 用户需要先手动在某个字段里填写答案并点击 "Save" 将其存入本地存储（`localStorage`/扩展 storage），后续在其他职位申请中遇到相同/相似问题时，可以点击 Fill 复用之前保存的答案。
- `MoreInfoPopup` 系列组件（`AnswerDisplay`、`AnswerSection` 等）说明用户可以在填充前查看/编辑候选答案，即存在人工审核/编辑的中间步骤。
- 没有发现自动提交申请表单的代码路径；表单提交这一步仍由用户手动完成。

因此可以将其定位为"辅助填表"工具：自动化的是"记忆并复用过去在类似字段上填过的答案"，而不是"全自动跑完整个投递流程"。

## 反爬虫/验证码/风控应对

在 README、CHANGELOG 及抽查的核心源码文件中均未发现任何针对验证码（CAPTCHA）、反爬虫检测或速率限制的处理逻辑。这符合其"浏览器扩展 + 用户手动点击触发填充"的定位——因为所有操作都由真实用户在真实浏览器会话中手动触发（点击按钮），不存在无头浏览器/脚本化批量提交，所以天然不太会触发常见的反机器人风控（但项目本身没有专门为此设计任何应对机制，只是架构上被动规避了这个问题）。

## 局限性

- 仅支持三类站点匹配规则（Workday 两个域名 + Greenhouse），覆盖的 ATS 种类有限；不支持简历解析、职位搜索或跨平台批量投递。
- 不含任何 AI/LLM 能力：字段值来自用户手动保存的历史答案，仅做简单字符串匹配（`stringMatch.ts` 中是精确匹配、前缀/后缀匹配、包含关系、关键词计数等朴素规则，未见任何模型调用或语义相似度计算）。
- 需要手动通过 Webpack 构建并以"开发者模式加载已解压扩展"的方式安装，未上架 Chrome Web Store（仓库中未见相关说明），普通用户使用门槛较高。
- 仓库活跃度较低（自 2025-02 起未见新提交动态，star/fork 数量均为个位数到二十几），维护规模是个人项目级别，功能仍以"逐字段辅助填充"为主，尚未发展到"全自动投递"阶段。
- README 宣称支持的部分平台（iCIMS）与实际 manifest 权限、源码实现不符，存在文档滞后的问题。

## 参考来源
- https://github.com/berellevy/job_app_filler
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/README.md
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/CHANGELOG.md
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/package.json
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/src/static/manifest.json
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/src/inject/inject.ts
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/src/inject/app/services/formFields/baseFormInput.tsx
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/src/shared/utils/fieldFillerQueue.ts
- https://raw.githubusercontent.com/berellevy/job_app_filler/main/src/shared/utils/stringMatch.ts
- https://api.github.com/repos/berellevy/job_app_filler（仓库元数据：stars/forks/语言/许可证/推送时间）
