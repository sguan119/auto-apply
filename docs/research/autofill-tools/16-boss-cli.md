# boss-cli —— 自动填表实现调研

- 项目地址/官网: https://github.com/jackwener/boss-cli （PyPI 包名 `kabi-boss-cli`）
- 类型: 开源（国内，专门做求职自动投递 / BOSS直聘 CLI 工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（未能直接拉取仓库源码文件逐行确认，全部信息来自 WebFetch 抓取的 README.md、SKILL.md 及仓库目录结构页面；GitHub 搜索结果中同名/近似名的项目较多，如 joohw/boss-cli（Puppeteer/CDP 浏览器自动化）、tianhhe/boss-zhipin-cli（Browser Bridge）等，本文只针对 jackwener/boss-cli 这个"逆向 API"版本）

## 核心实现方式

jackwener/boss-cli 明确定位为"通过逆向工程的 API 与 BOSS直聘 交互"的命令行工具（README 原话：a CLI for BOSS 直聘 — search jobs, view recommendations, manage applications **via reverse-engineered API**）。它不是浏览器自动化脚本，而是直接调用 BOSS 直聘网页版所使用的内部 HTTP 接口（通过复用浏览器登录后的 Cookie 来鉴权），因此运行时不需要打开/操控真实浏览器窗口。

仓库目录结构（从 GitHub 文件树页面获取）大致为：

```
boss_cli/
├── cli.py            # CLI 入口（Click）
├── client.py          # API 客户端，负责请求发送、限流与反检测
├── auth.py            # 认证：多浏览器 Cookie 提取 + 二维码登录
├── constants.py
├── exceptions.py
├── index_cache.py
└── commands/
    ├── auth.py
    ├── search.py       # 搜索/推荐职位
    ├── personal.py      # 个人中心：投递记录、面试邀请等
    ├── social.py        # 打招呼/批量打招呼
    └── recruiter.py     # 招聘方视角：候选人管理、简历查看/下载
```

## 技术栈

- 语言：Python（要求 Python ≥ 3.10）
- CLI 框架：Click
- 终端输出：Rich（富文本格式化，输出走 stderr 以保留 stdout 供管道/脚本消费）
- 安装方式：`uv tool install kabi-boss-cli` 或 `pipx install kabi-boss-cli`，也可源码 `git clone` 构建；可选 YAML 支持需额外依赖
- 输出格式：结构化 JSON/YAML "信封"格式 `{"ok": true, "schema_version": "1", "data": {...}}`，明显是为了方便被脚本或 AI Agent 消费
- 许可证：Apache-2.0

## 支持平台/网站

仅支持 BOSS直聘（求职者端 + 招聘方/HR 端两种身份的操作）。

## 自动化程度（全自动 / 半自动，人工介入点）

- **登录环节需要人工介入**：支持两种方式——(1) 自动从本地已登录的浏览器（Chrome、Firefox、Edge、Brave、Arc、Chromium、Opera、Vivaldi、Safari、LibreWolf 等 10+ 种浏览器）中提取 Cookie；(2) 终端内扫码登录（QR code login）。登录后的凭证保存在 `~/.config/boss-cli/credential.json`，并支持"7 天后自动从浏览器刷新 Cookie"，刷新失败则回退使用旧 Cookie。
- **投递/打招呼环节可批量执行**：`boss greet <securityId>` 针对单个职位打招呼，`boss batch-greet "golang" -n 10` 可批量对搜索结果打招呼，内置打招呼间隔延迟（约 1.5 秒）。README 及配套的 SKILL.md（面向 AI Agent/Claude Code 的工具说明书）都建议先用 `--dry-run` 预览后再真正执行，体现出"半自动、需人工/Agent 决策把关"的定位，而非无脑全自动海投。
- SKILL.md 中明确写出该工具**不支持发送聊天消息**（"No message sending — cannot send chat messages"），也就是说打招呼之后如果对方回复，仍需人工（或另配 Agent）去 BOSS直聘 App/网页里继续沟通，工具本身不覆盖完整对话流程。
- 未发现"简历"在求职者侧的上传/改写/自动生成功能；"简历"相关命令只出现在**招聘方（recruiter）**子命令里，例如 `boss recruiter resume <encryptGeekId>`（终端查看候选人简历）、`boss recruiter resume-download <id> --job <id>`（下载候选人简历为 Markdown）、`boss recruiter request-resume <friendId> --yes`（向候选人求简历）。也就是说，作为求职者使用该工具时，简历本身仍然是你事先在 BOSS直聘 网站/App 上传好的，工具并不负责改写或投递简历文件，只负责调用"打招呼/申请"这类交互接口。

## 反爬虫/验证码/风控应对

README 中列出的反检测/限流措施包括：

- **高斯抖动延迟**（Gaussian jitter）：请求间加入带高斯分布的随机延迟
- **随机长时间停顿**：约 5% 概率触发 2–5 秒的额外停顿
- **指数退避**：遇到平台返回的限流错误码（`code=9`，对应 HTTP 429/5xx 类场景）时，按 10s → 20s → 40s → 60s 逐级退避重试
- **浏览器指纹伪装**：固定使用 "macOS Chrome 145" 的 User-Agent，并配套 `sec-ch-ua`、`DNT`、`Priority` 等请求头，模拟真实浏览器请求特征
- **Cookie 自动刷新机制**：定期从本地浏览器重新提取新鲜 Cookie，降低因 Cookie 过期/失效导致的异常请求

**未发现**任何关于验证码（captcha）或滑块验证处理的说明——README 和 SKILL.md 均未提及如何应对图形验证码/滑块这类交互式风控挑战，推测该工具的定位是"尽量不触发"（通过节流、伪装规避），而不是"触发后自动破解"。若账号触发了滑块/验证码，大概率需要人工回到浏览器/App 手动完成验证。

需要指出的是，该工具作者（jackwener）同时维护了一个逆向微信生态的 wx-cli 项目，其 Issue 中出现过"账号被封一周"的风控反馈，可以作为同类"逆向官方私有 API"工具普遍存在账号风控风险的旁证（该反馈来自 wx-cli 而非 boss-cli 本身，未在 boss-cli 仓库中直接找到类似的封号报告）。

## 局限性

- 依赖对 BOSS直聘 私有 API 的逆向工程，接口一旦变化（签名算法、字段结构、风控策略升级）该工具可能随时失效，需要作者持续跟进维护
- 不处理验证码/滑块等交互式风控挑战，遇到此类拦截时自动化流程会中断，需人工介入
- 不具备发送/回复聊天消息的能力，打招呼后续的沟通仍需人工在官方客户端完成
- 求职者侧没有简历自动投递/改写功能，"打招呼"更接近于主动触达 HR 而非标准意义上的"投递简历+附件"
- 项目 README 中未发现明确的免责声明（disclaimer）或法律风险提示章节
- 使用逆向 API 的方式绕开了官方客户端的正常交互路径，存在触发平台风控、导致账号被限制或封禁的潜在风险（尤其在批量操作场景下）

## 参考来源

- https://github.com/jackwener/boss-cli
- https://raw.githubusercontent.com/jackwener/boss-cli/main/README.md
- https://github.com/jackwener/boss-cli/blob/main/SKILL.md
- https://github.com/jackwener/boss-cli/tree/main
- https://github.com/jackwener/wx-cli/issues/72 （同作者其他逆向项目的封号风险反馈，作为旁证）
