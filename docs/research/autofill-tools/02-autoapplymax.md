# AutoApplyMax —— 自动填表实现调研

- 项目地址/官网: https://github.com/Azoo92i/AutoApplyMax （官网 autoapplymax.com，Chrome 商店同名扩展）
- 类型: 开源（海外，专门做求职自动投递），AGPL-3.0 协议
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 WebFetch 读取 README、manifest.json、content-simple.js 及仓库文件列表，核心结论基于实际文件内容而非宣传文案）

## 核心实现方式

AutoApplyMax 是一个 Manifest V3 的 Chrome 扩展，不依赖 Selenium/Playwright 等外部浏览器自动化框架，而是通过扩展自身的 **content script（`content-simple.js`）+ background service worker（`background.js`）** 在页面内直接操作 DOM 来完成"自动投递"。核心逻辑是：

1. 用 `querySelectorAll` 抓取表单里的 `input[type=text/email/tel/number]` 等元素；
2. 从 `aria-label`、`name`、关联 `<label>`、父容器文本等多个来源提取字段标签；
3. 用**正则表达式**匹配标签文本（支持多语言，如英/法/西），命中后把预置的配置值（如工作年限、邮箱、电话、城市）填入对应输入框；
4. 用 `while (step < 10)` 循环处理分步表单，每步找"下一步/提交"按钮并点击，直到完成或超过步数上限。

简历上传部分会把 base64 编码的简历数据转成 File 对象，尝试上传到 `input[type=file]`，并优先复用站点已保存的简历（通过 radio 按钮/data 属性选择）而非每次重新上传。

## 技术栈

- 纯 JavaScript（约 78.5%）+ HTML/CSS，无 Selenium/Playwright/Puppeteer 等外部驱动，也没有 undetected-chromedriver 之类的反检测浏览器方案。
- Manifest V3 扩展架构：`background.js`（service worker）、`content-simple.js`（内容脚本，实际执行填表逻辑）、`popup.html/js/css`（弹窗 UI）。
- 数据存储在 `chrome.storage`（本地），官方声明简历数据"never stored on external servers"，AI 相关功能（简历生成、Cover Letter、ATS 打分）走 autoapplymax.com 后端 API，非扩展本地逻辑。

## 支持平台/网站

README 宣传支持 LinkedIn（Easy Apply）、Indeed（SmartApply）、Glassdoor、WTTJ、Monster 以及"任意网站的通用自动填表"，但**实际抓取到的 `manifest.json` 中 `host_permissions` 只包含 `https://www.linkedin.com/*`**，且仓库文件列表中没有发现针对 Indeed/Glassdoor/WTTJ/Monster 的独立 content script（如 `content-indeed.js` 等）。也就是说：

- GitHub 上公开的"开源核心"版本，从当前可验证的 manifest 权限和文件结构看，实际生效范围主要是 **LinkedIn Easy Apply**；
- README 中提到的多平台支持，可能依赖 Chrome 商店发布版本（未完全开源）或"通用自动填表"这一更泛化、未按站点定制的兜底逻辑，公开仓库里未见到对应的站点专用适配代码。
- 这是宣传资料与可验证源码之间的明显差异点，调研时予以标注，不代表结论确凿覆盖全部平台。

## 自动化程度（全自动 / 半自动，人工介入点）

- 定位为"全自动"批量投递工具（README 宣称可从每天 5-10 份提升到 50+ 份申请）。
- 源码中有明确的人工介入门槛：`isRunning` 与 `userExplicitlyClickedStart` 两个标志位必须同时为真，脚本才会执行任何点击/填表操作 —— 即用户必须手动点击"开始"才会触发自动化，防止扩展在后台静默运行。
- 一旦启动，多步表单内的填写、翻页、提交是自动连续执行的（循环最多 10 步），并未见到"提交前逐字段人工确认"的强制暂停设计；投递结果通过独立的 dashboard（需注册 autoapplymax.com 账号）追踪。

## 反爬虫/验证码/风控应对

- 未发现任何 CAPTCHA 检测或处理代码（源码分析结论：脚本完全不处理验证码场景）。
- 反检测手段主要是"类人行为"：在点击、填写之间插入固定或近似随机的等待（如 `wait(500)`、`wait(1000)`、`wait(1500)`），并非真正的随机化/指纹伪装，也没有使用 undetected-chromedriver 一类的浏览器指纹对抗方案。
- 有"卡住检测"（`isStuck()`，基于最后活动时间超过 120 秒判定）与自动刷新恢复机制，以及基于固定次数（如 `maxAttempts = 15`）的重试，但不是指数退避策略，也不针对平台风控（如触发选择题验证码/账号冻结）做专门处理。

## 局限性

- 多平台支持的宣传与公开仓库实际权限/代码覆盖范围不一致，Indeed/Glassdoor/WTTJ/Monster 等平台的适配细节在开源仓库中不可见，无法验证其真实自动化程度。
- 字段匹配完全基于硬编码正则表达式，非 LLM 语义匹配，对非常规问题（如自定义 Screening Questions、开放式问答题）适配能力有限。
- 无 CAPTCHA/风控应对能力，遇到验证码或平台反自动化拦截时会直接卡住或失败，依赖"卡住检测+刷新"这种较粗糙的兜底手段。
- 核心 AI 功能（简历生成、Cover Letter、ATS 打分）依赖官方付费/注册后端，开源仓库仅是"核心引擎"，与完整产品体验存在功能落差。

## 参考来源
- https://github.com/Azoo92i/AutoApplyMax
- https://raw.githubusercontent.com/Azoo92i/AutoApplyMax/main/manifest.json
- https://raw.githubusercontent.com/Azoo92i/AutoApplyMax/main/content-simple.js
