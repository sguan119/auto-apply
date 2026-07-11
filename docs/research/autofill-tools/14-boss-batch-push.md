# boss_batch_push —— 自动填表实现调研

- 项目地址/官网: https://github.com/yangfeng20/boss_batch_push （同步镜像 Gitee: https://gitee.com/yangfeng20/boss_batch_push；发布渠道 Greasy Fork: https://greasyfork.org/zh-CN/scripts/468125）
- 类型: 开源（国内，专门做求职自动投递，Boss直聘平台）
- 调研日期: 2026-07-06
- 置信度: 源码验证（README.md 全文、核心源码 `src/oop-self-req-main.js` 全文共 1928 行均已直接抓取并逐段核对，结论均来自实际代码/文档原文，未依赖第三方转述）

## 核心实现方式

项目是一个 **Tampermonkey（油猴）用户脚本**，脚本头声明 `@match https://www.zhipin.com/*`，以 `document-start` 时机注入页面。它不是独立的浏览器自动化程序（不驱动 Selenium/Playwright 打开浏览器），而是运行在用户已经手动登录、已经打开的 Boss直聘网页内部，直接复用页面自身的登录态（Cookie）和 JS 运行环境。

关键实现是**"页面脚本 + 直接调用站内接口"的混合方式**，而非单纯 DOM 点击模拟：

- **投递简历（打招呼）**：直接用 `axios` 向 Boss 的内部接口 `https://www.zhipin.com/wapi/zpgeek/friend/add.json` 发 POST 请求，请求头带上从 Cookie 中读到的 `bst` 值作为 `zp_token`（见 `sendPublishReq()`，`src/oop-self-req-main.js` 约 1468-1535 行），并不是模拟点击"打招呼"按钮。
- **发送自定义招呼语**：用 `protobufjs` 在脚本内按 Boss 的 IM 协议（`cn.techwolf.boss.chat`）手工构造 `TechwolfChatProtocol` 二进制消息（见 `Message` 类，约 1779-1850 行），再通过 `unsafeWindow.ChatWebsocket.send(this)` 挂到页面已建立好的真实 WebSocket 连接上发出，即"借用"页面自身的长连接而不是自己开一条连接。
- README 中作者"闲话"部分记录了这一实现的演化过程：最初尝试直接拿到 Boss 的 API/WebSocket 自己发消息，担心被加密或拦截，遂改为开一个 `iframe` 模拟用户点击；但直接 `.click()` 会被拦截，后来发现是输入框未触发 focus 事件，于是改成直接修改页面 Vue 组件的 `enableSubmit` 值来绕过；最后仍因 `WebSocket` 消息里 `to.uid` 为空发送不到对方而失败，才改为手动把 `bossInfo$.friendId` 赋给 `uid`。这段说明其技术路线经历了"DOM 模拟点击 → 操作 Vue 组件状态 → 直接构造并发送协议消息"的迭代。
- 职位列表/详情数据同样通过 `axios.get` 调用站内 JSON 接口（如 `wapi/zpgeek/job/card.json`、`wapi/zpchat/geek/getBossData`）获取，而不是解析 DOM 文本。

## 技术栈

- 运行环境：Tampermonkey/Greasemonkey/Violentmonkey 等用户脚本管理器（浏览器扩展），纯前端 JavaScript，无后端服务、无数据库。
- 依赖库（脚本头 `@require`）：`axios`（HTTP 请求）、`protobufjs`（编解码 Boss IM 的 protobuf 消息）、`js2wordcloud`（生成职位关键词词云）、`maple-lib`（日志封装）。
- GM_* API：`GM_setValue/GM_getValue`（配置持久化）、`GM_xmlhttpRequest`（跨域请求，如分词 API）、`GM_cookie`（Cookie 读写，用于"切换 Ck/大小号切换"）、`GM_notification`（停止时桌面通知）、`GM_addStyle`（页面美化）。
- 许可证：Apache-2.0。

## 支持平台/网站

仅支持 Boss直聘（zhipin.com）单一平台，`@match` 精确限定该域名，不做多平台通用适配。README 明确提示"Boss直聘新推出了职位页面，本项目未对新的页面进行适配"，建议迁移到作者的新项目 **AI工作猎手**（https://github.com/yangfeng20/ai-job）。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动：

- **登录**：完全依赖人工——脚本只是页面内的用户脚本，用户必须先在浏览器里用常规方式（扫码/账号密码）登录 Boss直聘网站，脚本仅在页面美化时删除了"去登录"按钮元素（`DOMApi.delElement(".go-login-btn")`），未见任何自动登录、自动扫码或验证码代码。
- **批量投递本身自动执行**：用户手动设置筛选条件（公司名包含/排除、职位名包含/排除、薪资区间、公司规模区间、工作内容排除关键词等）并点击"批量投递"按钮后，脚本按设定条件遍历列表页职位卡片并循环调用投递接口，期间无需人工逐条点击。
- **账号切换**：通过 `GM_registerMenuCommand` 提供"切换 Ck / 清除当前 Ck"菜单命令，用 `GM_cookie` 增删 Cookie 实现"大小号切换"，但每个账号仍需人工预先登录一次以采集 Cookie。
- **自定义招呼语功能目前已失效**：源码第 605 行附近有明确提示："BOSS直聘更新了，发送自定义招呼语功能不可用。作者在另一个脚本中更新修复了该功能……请移步到" AI工作猎手项目。也就是说仓库当前版本的核心卖点之一（自定义招呼语）在实际运行中已经被 Boss 的更新破坏，需要人工确认效果或改用姊妹项目。
- 招呼语文本是用户在配置面板里手写的一段固定文本（`getSelfGreet()`），不是根据简历内容自动生成或做字段映射，只是原样通过协议发送。

## 反爬虫/验证码/风控应对

- 全文搜索未发现任何滑块验证码、图形验证码识别/打码平台对接、指纹伪装（如 `navigator.webdriver`、`toString` hook、CDP 检测规避）相关代码。因为脚本运行在用户真实登录的浏览器会话里、复用真实 Cookie 与真实 WebSocket 连接，天然规避了"检测自动化浏览器/无头浏览器"这类风控手段，但也意味着一旦 Boss 弹出滑块验证码或人机校验，脚本没有能力自动处理，只能靠用户人工完成。
- 主要的"风控应对"体现在**限流与规则规避**而非绕过验证码：
  - 内置**每日投递上限检测**（`ScriptConfig.PUSH_LIMIT`，README 原文"以免浪费每天的100次机会"），检测到接口返回"今日沟通人数已达上限"会抛出 `PublishLimitExp` 并自动停止批量投递（`sendPublishReq` 中判断 `result.message.includes("今日沟通人数已达上限")`）。
  - **投递锁**（`PUSH_LOCK`，通过 `setInterval` 轮询）确保同一时刻只有一个职位在投递，避免并发请求过快触发风控；README 更新记录中提到过"延迟投递，避免频繁【500ms-->800ms】"，即人为加入投递间隔。
  - **不活跃 Boss 过滤**：读取职位详情里的 `activeTimeDesc` 字段，通过 `Tools.bossIsActive()` 判断招聘者是否近期活跃，过滤掉不活跃的招聘者发布的职位，避免把每日有限的沟通次数浪费在不会回复的账号上（并非反风控本身，但客观上减少了无效请求）。
  - 请求头里带的 `zp_token`（来自 Cookie `bst`）由 Boss 页面自身签发和维护，脚本只是读取转发，不做任何自行伪造或逆向加密算法的工作；README 更新日志里多次提到 Boss 更新接口字段（如 `haveContacted` 改名为 `friendStatus`、token 字段变化）导致脚本报错"请求不合法"，需要作者跟进修复，说明该项目对 Boss 接口变更颇为脆弱，需要持续维护适配。
- 未见任何应对账号封禁/风控升级（如异常登录检测、行为轨迹分析）的专门代码，遇到此类风控只能依赖人工判断和降低使用频率。

## 局限性

- 仅支持 Boss直聘旧版职位页面，README 明确声明未适配新版页面，功能可能已部分失效，作者建议迁移到新项目 AI工作猎手。
- 自定义招呼语功能在当前版本中已被作者标注为"不可用"（Boss 更新导致），是文档中明确写出的已知缺陷。
- 没有验证码/滑块自动处理能力，遇到人机验证只能人工介入；依赖真实登录会话，账号仍可能因高频操作被 Boss 风控限制或封禁，项目本身不提供规避方案。
- 对 Boss 接口字段变化非常敏感，历史更新记录显示多次因为 Boss 后端接口调整（字段改名、token 校验变化）导致脚本失效，需要作者持续跟进维护，用户自行使用时也可能遇到脚本"过期"不可用的情况。
- 未见任何测试代码或 CI；一切逻辑集中在单个 83KB 的 `oop-self-req-main.js` 文件中，工程化程度较低，属于典型的个人维护的油猴脚本项目。
- 招呼语为用户手写固定文本，不具备根据目标职位/简历内容做个性化文本生成的能力（这部分能力被拆分到了作者的付费/更新版姊妹项目 AI工作猎手中，本仓库不含 AI/LLM 相关代码）。

## 参考来源
- https://github.com/yangfeng20/boss_batch_push
- https://raw.githubusercontent.com/yangfeng20/boss_batch_push/master/README.md
- https://raw.githubusercontent.com/yangfeng20/boss_batch_push/master/src/oop-self-req-main.js
- https://greasyfork.org/zh-CN/scripts/468125-boss-batch-push-boss%E7%9B%B4%E8%81%98%E6%89%B9%E9%87%8F%E6%8A%95%E7%AE%80%E5%8E%86
- https://github.com/yangfeng20/ai-job
