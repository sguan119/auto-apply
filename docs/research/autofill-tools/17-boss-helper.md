# boss-helper (Ocyss) —— 自动填表实现调研

- 项目地址/官网: https://github.com/Ocyss/boss-helper （亦有商店介绍页 https://chrome-stats.com/d/boss-helper ；Greasy Fork 上存在同名/同作者的用户脚本版本 https://greasyfork.org/en/scripts/491340）
- 类型: 开源（国内，专门做求职自动投递，专攻 BOSS直聘）
- 调研日期: 2026-07-06
- 置信度: **源码验证**（已直接抓取并阅读 README 及 `src/` 下约 10 个核心源码文件，包括投递流程、任务筛选链、AI 调用、请求封装、Vue 内部钩子工具等）

## 核心实现方式

boss-helper 是一个**浏览器扩展（content script）**，注入到 BOSS直聘网页中运行，通过"任务链"（`TaskRegistry` / `defineTaskWorkflow`，见 `src/entrypoints/boss/delivery.ts`）依次执行一系列筛选与操作 handler，最终完成"投递 + 打招呼"。

关键点：它**不是纯粹的 DOM 点击模拟器，也不是纯粹的 API 直连脚本，而是两种技术混合**，且从代码痕迹看正在从"直连官方内部 API"向"劫持页面自身 Vue 实例"迁移：

1. **直连 BOSS 内部 API（`src/entrypoints/boss/requests.ts`）**：封装了三个真实网络请求
   - `requestDetail` → `GET https://www.zhipin.com/wapi/zpgeek/job/detail.json`（职位详情）
   - `sendPublishReq` → `POST https://www.zhipin.com/wapi/zpgeek/friend/add.json`（投递/加好友，即"打招呼"动作），请求头带 `Zp_token`，Cookie 中的 `bst` 作为 token
   - `requestBossData` → `POST https://www.zhipin.com/wapi/zpchat/geek/getBossData`（获取 HR 信息）

2. **劫持页面自身 Vue 实例（`src/composables/useVue.ts` + `src/utils/elmGetter.ts`）**：`useHookVueData` / `useHookVueFn` 通过 `document.querySelector(selectors).__vue__` 拿到页面 Vue2 组件实例，直接读取其响应式数据（如 `jobDetail`）、劫持 setter，或直接调用其内部方法（如 `clickJobCardAction`）。在 `src/entrypoints/boss/delivery.ts` 中，"岗位详情获取"这一步**已经把 `requestDetail()` 的直连调用注释掉**，改为调用 `ctx.helper._clickJobCardAction(job.rawData.jobitem)`（本质是触发页面自己的点击处理函数）然后轮询等待页面内部状态 `_jobDetail` 更新。

3. **注意**：在抓取到的 `main` 分支代码中，"岗位投递"这一步的真实网络调用 `sendPublishReq(...)` 同样被**整段注释掉**，替换为只打印日志并直接返回 `{status:'success'}` 的占位实现；`BossHelperCtx.sendMessage()` 也只是 `logger.info('发送消息', ...)` 的桩函数。也就是说，**当前抓到的这份源码里，真正把"投递请求"和"打招呼消息"发送出去的最后一步是被注释/stub 掉的**，`requests.ts` 里功能完整的 API 封装函数目前处于未被引用或半废弃状态。这可能是项目正在从"直连内部 API"重构为"驱动页面自身逻辑"过程中的中间态（发布的插件商店版本是否启用了真实调用，无法仅凭 GitHub 主分支代码确认）。

## 技术栈

- **框架**：WXT（浏览器扩展开发框架）+ Vue3 + Nuxt UI v4 + TailwindCSS v4
- **AI SDK**：`@ai-sdk/openai`（Vercel AI SDK 的 OpenAI 兼容 provider），走 `createOpenAI({ baseURL, apiKey })`，因此可对接任意 OpenAI 协议兼容的服务（README/代码中列出的可选 `base_url` 预设：OpenAI 官方、OpenRouter、DeepSeek、Moonshot Kimi、火山方舟/豆包等）
- 另有一套基于 WebSocket/MQTT/Protobuf 的模块（`src/composables/useWebSocket/{mqtt,protobuf,chatCore,chatBridge}.ts`，含 `src/assets/chat.proto`），推测用于监听/解析 BOSS 网页端聊天的实时消息（未逐行确认其是否已用于生产路径）。
- 分发形式：Chrome Web Store / Edge 附加组件 / Firefox Add-ons / GitHub Release 手动安装包，国内还提供"Crx搜搜"作为商店受限时的替代下载渠道。

## 支持平台/网站

仅 BOSS直聘（zhipin.com）网页版，未见适配其他招聘平台的代码或说明。

## 自动化程度（全自动 / 半自动，人工介入点）

- 整体定位为**半自动批量投递**：用户先在插件的筛选配置面板（`src/components/Tabs/Filter.vue` 等）中设置岗位名/公司名/薪资范围/公司规模/工作地址/HR职位/活跃度/猎头过滤/相同公司或HR去重等条件，插件在职位列表页上按任务链自动执行"过滤 → 获取详情 → （AI）二次筛选 → 投递 → 打招呼"。
- **打招呼语生成**分两种模式（均在 `handles.ts` 中定义为可选 handler，任选其一或都关闭）：
  - `customGreeting`：用户手写模板 + `renderTemplate`（`{{jobData.xxx}}` 占位符渲染，类似 mustache 的模板引擎），可插入职位字段变量。
  - `aiGreeting`：把职位信息（岗位名/薪资/学历要求/技能/标签/职位描述等，来自 `jobData`）套进用户配置的 system/user prompt 模板，调用大模型生成开场白。**默认 prompt 模板里明确留了"求职者信息"占位区块要求用户自己手工填写**（如 `defaultFormData.aiGreeting.prompt` 中 system 提示词写着"1. .... 2. .... 3. ...."），即**没有自动解析简历文件、没有简历字段到表单的结构化映射**，个人信息完全靠用户在 AI 提示词里自行描述，映射的只是"职位方信息 → 模板变量"，不是"简历 → 表单"。
  - 另有 `aiReply`（AI 自动回复 HR 消息）作为规划中/半实现功能。
- 人工介入点：账号登录、Cookie/`bst` token 由浏览器会话提供（无需用户单独配置密钥）；AI 功能需要用户自备并填写模型的 `base_url`/`api_key`；投递的筛选条件、延迟参数、投递上限均由用户手动配置；启动/暂停由用户在插件面板中触发，并非无人值守的后台常驻服务。

## 反爬虫/验证码/风控应对

- **无验证码/滑块识别或绕过逻辑**：全仓库检索未发现任何与"验证码""滑块""captcha"相关的处理代码。
- **主要靠限速和数量上限"软"避险**（`src/types/formData.ts` 中 `defaultFormData.delay` 与 `deliveryLimit`）：
  - `deliveryStarts`（默认 3\~10 秒）：点击"投递"后先等待再开始
  - `deliveryInterval`（默认 2\~5 秒）：每次投递之间的间隔，说明文字直接写"太快易风控"
  - `deliveryPageNext`（默认 60 秒）：翻页之间的等待，同样标注"太快易风控"
  - `deliveryLimit`（默认 100\~120 次）：达到上限自动暂停，说明中提到"当前boss上限为150"
  - `sameCompanyFilter` / `sameHrFilter`：避免对同一公司/同一HR重复投递触发风控
  - `activityFilter`：过滤掉长期不活跃HR发布的职位，避免浪费"每天100次机会"额度
- **对 BOSS 平台自身限额弹窗的处理**（`requests.ts` 的 `sendPublishReq`）：识别返回内容中的"您今天已与120位BOSS沟通"提示并自动调用确认接口（`chatremind.json`）后重试；识别"您今天已与150位BOSS沟通"抛出 `LimitError`（到达平台硬上限，终止）；识别"操作过于频繁"抛出 `RateLimitError`。这是**对平台已知业务规则/限额弹窗的应对，而非对反爬虫/验证码的技术性绕过**。
- **README 中的免责声明**明确写明"使用该脚本有一定风险(如黑号、封号、权重降低等)，本项目不承担任何责任"，可视为作者对无法保证规避风控的坦白说明。

## 局限性

- 从抓取到的主分支代码看，真正把"投递"请求和"打招呼消息"发出去的最后一步在 `delivery.ts`/`BossHelperCtx.sendMessage` 中是被注释/stub 的（只打日志），说明该功能可能仍在从"直连内部API"向"驱动页面自身Vue逻辑"重构过渡中，**无法仅凭本次抓取确认商店发行版是否已经启用真实发送**。
- 高度依赖 BOSS直聘页面的私有内部接口（`wapi/zpgeek/...`）和页面 Vue 组件的内部字段名/方法名（`__vue__`、`clickJobCardAction`、`jobDetail` 等），一旦 BOSS 前端改版或更换框架版本，相关 hook 会直接失效。
- 无验证码/滑块自动处理能力，遇到人机验证只能人工介入。
- 没有简历文件解析或结构化简历字段到招呼语/表单的自动映射，AI 打招呼所需的"求职者信息"需用户手工写入 prompt。
- README 与代码内多处（如 `formInfoData` 里 `useCache` 的说明"缓存功能并不积极维护，可能会有bug"、`messageSending` 延迟标注"暂未实现"）显示部分功能仍不完整或维护有限。
- 仅支持 BOSS直聘一个平台，不具备跨平台通用性。

## 参考来源
- https://github.com/Ocyss/boss-helper
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/README.md
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/entrypoints/boss/delivery.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/entrypoints/boss/requests.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/entrypoints/boss/index.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/composables/useApplying/handles.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/composables/useApplying/utils.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/composables/useVue.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/composables/useModel/openai.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/composables/conf/info.ts
- https://raw.githubusercontent.com/Ocyss/boss-helper/main/src/types/formData.ts
- https://chrome-stats.com/d/boss-helper
- https://greasyfork.org/en/scripts/491340-boss%E7%9B%B4%E8%81%98%E5%8A%A9%E6%89%8B
