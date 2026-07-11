# find-job (noBaldAaa) —— 自动填表实现调研

- 项目地址/官网: https://github.com/noBaldAaa/find-job
- 类型: 开源（国内，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 WebFetch 直接读取 README.md、main.js、utils.js、domOperationMock.js、简历基本信息.txt 的原始内容进行确认；未能在本地克隆运行代码，个别实现细节以工具摘要转述为准）

## 核心实现方式

find-job 是一个**只针对 BOSS 直聘（zhipin.com）单一平台**的"AI 打招呼"自动化工具，本质上不是"自动填表投递简历"，而是"自动浏览职位列表 + 用 GPT 生成打招呼语 + 自动点击沟通并发送消息"。

工作流程（README 及 main.js 内容确认）：
1. 用 Selenium 启动 Chrome（`--detach` 参数，窗口最大化），打开 zhipin.com。
2. 点击登录按钮 → 点击"微信登录"选项（XPath 定位），随后**由用户手动扫码**完成登录（等待微信 logo 出现，超时 60000ms），登录本身不是全自动的。
3. 遍历职位列表，通过 `getJobDescriptionByIndex()` 点击某个职位并抓取职位描述（固定 XPath 提取 `<p>` 文本）。
4. 将职位描述与本地简历文本（读取自 `简历基本信息.txt`）拼接成 prompt，调用 GPT（`gpt-3.5-turbo`）生成一段约 80 字、可直接复制发送的"专业得体"打招呼语。
5. 定位聊天输入框（`//*[@id='chat-input']`），`clear()` 后 `sendKeys()` 填入 GPT 生成的文本，再 `sendKeys(Key.RETURN)` 发送。
6. 返回职位列表，循环处理下一个职位。

也就是说，"投递"在这里被简化为：给招聘方发一条 AI 生成的打招呼消息，而不是上传/填写结构化的简历表单（如姓名、学历、工作经历等字段）。

## 技术栈

- 语言/运行时：Node.js（JavaScript），用 `yarn` 管理依赖。
- 浏览器自动化：`selenium-webdriver`（非 Playwright/Puppeteer）。
- AI/LLM：OpenAI 接口协议，但通过国内代理服务 `https://api.chatanywhere.com.cn`（免费 API key，来源于 GitCode 上的 "GPT-API-free" 项目）调用，模型为 `gpt-3.5-turbo`。
- 无配置文件 schema：简历信息只是一份**纯文本文件** `简历基本信息.txt`（README 中提供的示例是一份技能条目列表，如"精通 React/Vue2/3 框架开发……"），没有结构化字段（JSON/YAML）与表单字段的映射关系；程序把整份文本原样喂给 GPT 做上下文，而不是逐字段填表。

## 支持平台/网站

- 仅支持 **BOSS 直聘（zhipin.com）**一个平台。README 与源码中均未发现对前程无忧、猎聘、拉勾、智联招聘等其他平台的适配代码或说明。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动，且人工介入点较多：
- **登录环节需要人工扫码**（微信扫码登录），脚本只是点击到登录弹窗、切换到"微信登录"选项，之后由 `driver` 等待页面出现微信 logo 元素，实际扫码授权动作由用户完成。
- **API Key 需要用户手动获取并手动全局替换**占位符 `【你的 apiKey】`（README 明确写明操作步骤）。
- 简历信息需要用户手工编辑 `简历基本信息.txt`。
- 一旦登录完成、Key 填好，"浏览职位 → 生成打招呼语 → 发送消息 → 翻页"这部分循环是自动执行的（一键运行：`yarn install && yarn start`）。

综合看，这是"人工登录 + 全自动打招呼群发"的半自动工具，而非严格意义上的全自动投递（不涉及自动上传简历附件或自动填写结构化申请表单）。

## 反爬虫/验证码/风控应对

源码中**未发现任何针对验证码、滑块验证的处理逻辑**：
- `domOperationMock.js` 里全部是基于固定 XPath 的 `findElement` + `until.elementLocated()` 等待（10s/60s 超时）+ 简单 `try/catch` 打印错误，没有滑块拖拽、图形验证码识别、行为轨迹模拟等反检测代码。
- 唯一近似"防风控"的设计是让**登录环节交给真人**（扫码），从而规避自动化登录容易触发的验证码/风控问题；除此之外没有 UA 伪装、指纹伪装、随机延迟等专门的反爬虫手段。
- 项目定位是"轻量小工具"，README 中也未提及应对封号/风控的策略。

## 局限性

- 只支持 BOSS 直聘一个平台，扩展性有限，选择器为写死的绝对 XPath，页面改版即失效（`utils.js`/`domOperationMock.js` 中的分析已指出这一脆弱性）。
- 简历数据是非结构化纯文本，不存在"字段 → 表单"的映射机制，无法做到精细化的简历字段自动填写，只能靠 GPT 拼接文本生成一段打招呼话术。
- `utils.js` 中 `getResumeInfo()` 存在异步处理缺陷（`fs.readFile` 回调未正确返回数据，`return` 语句先于回调执行），存在实际可用性问题。
- 无验证码/滑块/风控对抗能力，登录依赖人工扫码，无法做到真正"全自动"跑通整个投递流程。
- 免费 GPT 代理（chatanywhere）属于第三方服务，稳定性和可持续性依赖外部服务方，非官方 OpenAI 通道。
- 由于个人信息、简历文本存放在本地明文文件中，且早期版本要求用户把 API Key 硬编码进源码里，需要用户自行注意不要把这些敏感信息提交到仓库或分享出去。

## 参考来源
- https://github.com/noBaldAaa/find-job
- https://github.com/noBaldAaa/find-job/blob/main/README.md
- https://raw.githubusercontent.com/noBaldAaa/find-job/main/main.js
- https://raw.githubusercontent.com/noBaldAaa/find-job/main/utils.js
- https://raw.githubusercontent.com/noBaldAaa/find-job/main/domOperationMock.js
- https://raw.githubusercontent.com/noBaldAaa/find-job/main/简历基本信息.txt
