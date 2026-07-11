# Jobs_helper（海投助手）—— 自动填表实现调研

- 项目地址/官网: 原始仓库 https://github.com/YangShengzhou03/Jobs_helper 已在 GitHub 上失效（404，可能已删除或改名）。当前可访问的镜像/分支为 https://github.com/mikey-ccccccccc/Jobs_helper （`Boss` 分支）。项目的规范分发源是 Gitee：https://gitee.com/yangshengzhou/boss_helper （脚本内 `@require` 均从此处加载），项目也更名为「BOSS海投助手」。文档站 https://yangshengzhou.gitbook.io/Jobs_helper （未验证，未抓取）。
- 类型: 开源（国内，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（通过 GitHub API 拉取了 `Boss` 分支下的 `main.js`、`core.js`、`config.js`、`state.js`、`utils.js` 及 README，并逐一阅读确认实现细节）。注意：原作者账号下的仓库已不可直接访问，以下结论基于社区镜像仓库中的代码，版本号为 `1.2.3`。

## 核心实现方式

这不是 Selenium/Playwright/Puppeteer 式的外部浏览器自动化，也不是逆向 API 调用，而是一个运行在用户真实登录会话中的 **Tampermonkey/ScriptCat 用户脚本（userscript）**。脚本通过 `@match https://www.zhipin.com/web/*` 注入到 BOSS直聘网页，直接操作真实 DOM：

- 监听页面加载（`window.addEventListener('load', init)`），注入一个悬浮控制面板（`UI.init()`）。
- 在职位列表页（`/jobs`）：自动滚动加载全部职位卡片（`autoScrollJobList`，通过连续对比 3 次滚动后卡片数量是否不再变化来判断"加载完成"），然后按关键词/地区过滤后的职位列表逐个 `card.click()` 打开详情，再点击"立即沟通"按钮（`a.op-btn-chat`），并自动关闭"留在此页"弹窗（`handleGreetingModal`）。
- 在聊天页（`/chat`）：用 `MutationObserver` 监听聊天列表变化，找到最新一条会话（`clickLatestChat`），点击头像进入对话，依次点击平台自带的"常用语"（`.btn-dict` → 常用语列表）逐条发送作为自我介绍，再点击"发简历"按钮 (`.toolbar-btn` 文本为"发简历") 和确认按钮 (`span.btn-sure-v2`) 完成投递。
- 交互全部基于 XPath/CSS 选择器解析页面元素 + 派发合成鼠标事件（`mouseover→mousemove→mousedown→mouseup→click`，每步间隔约 30ms）模拟点击，而不是直接 `element.click()`。
- 网络请求（仅用于 AI 回复接口）通过 `GM_xmlhttpRequest` 发出，绕过页面 CORS 限制。
- 已处理的 HR/岗位通过 `localStorage`（`processedHRs` 等）持久化，避免重复投递/重复打招呼。

## 技术栈

- 纯前端 JavaScript，无框架、无构建流程，模块通过 `@require` 以多个独立 `.js` 文件方式加载（`config.js`、`state.js`、`utils.js`、`ui.js`、`core.js`），最终以 Tampermonkey/ScriptCat 用户脚本形式分发（`main.js` 头部有标准 `// ==UserScript==` 元数据块）。
- 依赖 `crypto-js`（通过 CDN `@require`）；未见其他第三方自动化库。
- 无后端、无数据库；所有状态存储在浏览器 `localStorage`。

## 支持平台/网站

- **仅支持 BOSS直聘**（`zhipin.com`），且只覆盖两个页面：职位列表页 `/web/geek/jobs` 和聊天页 `/web/geek/chat`。
- README「未来规划」中提到计划支持"拉勾网、猎聘网等"，但当前源码中没有任何相关实现，纯属愿望清单。
- 未见前程无忧、智联招聘的适配代码或提及。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动、依托用户已有平台账号数据的自动化，人工介入点包括：

1. **登录**：完全依赖用户在浏览器中手动登录 BOSS直聘账号，脚本不做任何登录/验证码/滑块处理。
2. **简历内容**：脚本本身**不做任何简历字段填充或简历生成**——它点击的"发简历"按钮直接调用平台自身功能，发送的是用户**已经在 BOSS直聘个人资料里绑定好的简历**；同样，"打招呼语"发送的是用户**预先在平台配置好的"常用语"**列表，脚本只是按顺序点击发送，没有做任何字段映射（无姓名/学历/工作经历等结构化数据填表逻辑）。
3. **启动/停止/参数配置**：用户需手动点击悬浮面板上的"开始投递""暂停""停止"按钮；筛选关键词、地区、投递间隔、AI 角色 prompt、API Key 等均需手动在面板或脚本源码中配置。
4. 一旦启动，职位列表遍历、进入聊天、发常用语、发简历、AI 自动回复 HR 消息这一整条链路是全自动循环执行的（`while (state.isRunning) { ... }`），不需要逐条人工确认。

## 反爬虫/验证码/风控应对

源码中**没有找到任何验证码识别、滑块验证处理或专门的反检测代码**。观察到的"防风控"手段仅限于：

- **模拟真实鼠标事件序列**代替直接 `.click()`（`simulateClick` 依次派发 mouseover/mousemove/mousedown/mouseup/click，每步间隔 30ms），使点击行为在 DOM 层面更接近人工操作。
- **可配置的操作节流**：`CONFIG.BASIC_INTERVAL`（默认 800ms，用于滚动/轮询）与 `CONFIG.OPERATION_INTERVAL`（默认 1500ms，用于点击"立即沟通"后的等待）用于避免过快连续操作。
- **AI 回复限流**：普通用户每日最多 5 次自动回复（`state.aiReplyCount >= 5`），超出后停止，主要目的可能是控制作者自建 AI 接口成本，也间接降低了账号异常活跃度。
- 因为脚本运行在用户真实浏览器的真实登录会话里（而非无头浏览器或另开的自动化浏览器实例），天然规避了"新设备/新指纹登录"类风控，但如果 BOSS直聘对该账号触发验证码/滑块，脚本没有相应处理逻辑，需要用户手动介入解决。

## 局限性

- 原始 GitHub 仓库已不可访问（404），项目的可持续性/维护状态存疑；本调研基于第三方镜像仓库代码。
- 仅支持单一平台（BOSS直聘）、且仅两个页面，覆盖面远小于 README 宣传的"多平台"愿景。
- 没有独立的简历数据模型或字段映射机制——严格依赖用户预先在 BOSS直聘网页端维护好"简历"与"常用语"，脚本本身不具备"改写简历"或"生成个性化打招呼语"的能力（AI 部分仅用于回复 HR 消息，不用于生成投递内容）。
- AI 回复功能调用作者自己的第三方大模型 API（讯飞星火 `spark-api-open.xf-yun.com`），鉴权 Token 以字符码数组混淆后硬编码在 `core.js` 的 `requestAi()` 函数中，为作者自持的共享 Key，存在被滥用/失效/限流风险，且用户消息会被发送到该第三方服务。
- 无验证码/滑块处理能力，遇到平台风控需人工介入。
- AGPL-3.0 协议且 README 自称"有限开源"，与"完全开源"的宣传存在一定矛盾。

## 参考来源
- https://github.com/YangShengzhou03/Jobs_helper （原始仓库地址，当前返回 404）
- https://github.com/mikey-ccccccccc/Jobs_helper （镜像仓库，`Boss` 分支，README 与源码均取自此处）
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/README.md
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/main.js
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/core.js
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/config.js
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/state.js
- https://github.com/mikey-ccccccccc/Jobs_helper/blob/Boss/utils.js
- https://gitee.com/yangshengzhou/boss_helper （规范分发源，README 中 `@require` 指向此仓库，抓取时返回 403）
