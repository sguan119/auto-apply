# get_jobs (loks666) —— 自动填表实现调研

- 项目地址/官网: https://github.com/loks666/get_jobs （国内镜像 Gitee 版）
- 类型: 开源（国内，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（README、`application.yaml`、`anti-detection.js` 已抓取原文；`Boss.java`/`PlaywrightManager` 等核心类未逐行通读，相关结论来自第三方源码解读页 zread.ai 与项目 Discussion，标记为二手确认）

## 核心实现方式

项目为 Java（Gradle + JDK21）编写的 Spring Boot 应用，内置 SQLite 数据库（`getjobs.db`）与网页管理界面（端口 8888），用于配置和查看投递记录。核心投递逻辑通过浏览器自动化驱动各平台网页完成"搜索职位 → 逐条打招呼/投递 → 发送简历"的流程，而非调用平台私有 API。每个平台对应一个独立 Java 类（`Boss.java`、`Liepin.java`、`Job51.java`、`ZhiLian.java`），各自实现搜索、过滤、投递的适配逻辑。

## 技术栈

- 后端：Java 21 + Spring Boot + Gradle；数据存储用 SQLite + MyBatis-Plus。
- 浏览器自动化：历史上使用 Selenium（README 中仍提到"自动判断系统环境、自动下载 chromedriver"），但据第三方源码解读（zread.ai 对 `PlaywrightManager` 的分析）及社交媒体报道，项目已迁移到 **Playwright**：由一个 `PlaywrightManager` 单例统一管理一个 Chromium 实例、一个共享 `BrowserContext`（复用 cookie/localStorage/注入脚本），为 Boss/猎聘/51job/智联四个平台各分配一个 Page（标签页），浏览器以有头模式启动并固定 `--remote-debugging-port=7866`。此点未能在本次调研中直接读取到 `Boss.java` 源码逐行确认，故标注为二手信息。
- 前端：TypeScript/JS 页面（GitHub 语言占比显示 Java 64%、TS 33.5%）。

## 支持平台/网站

README 原文对四个平台分别给出评价，差异明显：
- **Boss直聘**：功能最完整，支持 AI 生成打招呼语、AI 判断岗位匹配度、自动发送图片简历；"打招呼上限已修改为每日150次"。
- **猎聘**：默认打招呼无上限，但"主动发消息有上限，成功率不高"。
- **前程无忧（51job）**：投递有上限，且限制搜索到的岗位数量，"没什么活人"。
- **智联招聘**：投递上限约100，README 原话"烂掉了，不要用"。

各平台适配层是独立的，选择器、限流策略、登录方式均按平台单独实现。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动为主：
- 登录环节需人工介入——多数平台"只可微信扫码"登录（猎聘、智联），Boss直聘支持超长 Cookie 登录，README 称"大部分平台每周仅需扫码一次"，即仍需周期性人工扫码续期。
- 登录之后的搜索、筛选、打招呼、投递、发送简历为自动执行。
- 配置（求职关键词、简历图片 `resume.jpg`、`sendImgResume` 开关、黑名单公司等）通过网页管理界面或 resources 目录人工预设，运行前需人工设置一次。
- README 明确"本项目不支持服务器部署"，且要求"必须关闭墙外代理"（因主要面向国内平台，代理会导致页面加载缓慢/失败），意味着需在本地图形环境下人工值守运行。

## 反爬虫/验证码/风控应对

这是该项目着墨最多、技术含量最高的部分：
- 项目在 `src/main/resources/anti-detection.js` 中注入一段浏览器端 stealth 脚本，会 hook `Function.prototype.toString`（用 WeakMap 缓存原生签名，防止被检测出函数被包装过）以及重写 `console.log/debug/info/warn/error/dir/table` 等方法（清空传入对象），以对抗基于 DevTools/CDP 检测自动化的手段。
- 项目 Discussion #250（"关于Boss防检测的讨论"）详细讨论了 Boss直聘使用的 `disable-devtool` 类库如何通过以下方式识别自动化：`console.table()` 执行大对象时的耗时差异、检测 `--remote-debugging-port` 等 CDP 特征、扫描 `navigator.webdriver` 等 27+ 项浏览器属性。社区提出的对策包括：覆盖 console 相关函数为空函数、伪装 `toString` 结果、使用 `launchPersistentContext`/真实 Chrome 用户数据保持登录态而非无头实例、乃至更深层的输入法(IME)上屏与真实键鼠时序模拟，因为讨论指出 Boss 企业侧已引入基于 WebAssembly 神经网络分析键鼠轨迹与刷新率的行为检测（属于社区讨论内容，非官方确认实现）。
- 未见项目内置滑块验证码/图形验证码的自动识别或打码平台对接；应对验证码/风控的主要方式仍是"降低并发/限速 + 保持真实登录态 + 周期性人工扫码"，而非破解验证码本身。

## 局限性

- 部分平台（智联、51job）已被作者在 README 中标注为效果差甚至"烂掉了"，说明反检测/限流是持续对抗、非一劳永逸。
- 不支持服务器/无头部署，必须本地有头浏览器运行，且不能挂代理，限制了云端托管能力。
- 需要定期人工扫码维持登录，无法做到完全免人工的长期自动化。
- Selenium→Playwright 的具体迁移细节及 `Boss.java` 完整选择器逻辑本次未逐行验证，仅基于第三方解读确认，存在信息滞后或不准确的风险。

## 参考来源
- https://github.com/loks666/get_jobs
- https://raw.githubusercontent.com/loks666/get_jobs/master/README.md
- https://raw.githubusercontent.com/loks666/get_jobs/master/src/main/resources/application.yaml
- https://raw.githubusercontent.com/loks666/get_jobs/master/src/main/resources/anti-detection.js
- https://github.com/loks666/get_jobs/discussions/250
- https://zread.ai/loks666/get_jobs/10-playwrightmanager-unified-browser-lifecycle-and-session-management
- https://x.com/GitHub_Daily/status/1963867193398935898
