# ApplyEase —— 自动填表实现调研

- 项目地址/官网: https://github.com/sainikhil1605/ApplyEase
- 类型: 开源（海外，专门做求职自动投递）—— 个人 Chrome 插件项目，非公司产品
- 调研日期: 2026-07-06
- 置信度: 源码验证（已读取 README、manifest.json、contentscript.js 的实际内容，并通过 GitHub API 核实仓库元数据）

## 核心实现方式

ApplyEase 是一个 **Chrome 浏览器插件（Manifest V3）+ 本地/自托管后端** 的组合方案，不是纯 SaaS，也不是 Selenium/Playwright 式的无头浏览器自动化。

- 插件通过 `contentscript.js` 注入到页面（`manifest.json` 中配置为 `matches: ["<all_urls>"]`、`all_frames: true`、`run_at: document_end`），在页面 DOM 中直接查找并操作表单元素。
- 字段识别采用**正则匹配元素的 `name`/`id`/关联 label 文本**的方式，例如姓名字段的判定逻辑：
  `/(first[ _-]*name|given|forename)/i.test((i.name || "") + " " + (i.id || "") + " " + closestLabelText(i))`，邮箱、电话、地址等字段使用类似的正则集合。
- `closestLabelText()` 函数负责通过 `label[for='...']` 或向上遍历 DOM 找到关联的 label 文本，辅助判断字段语义。
- 简历文件上传通过 `DataTransfer` API 模拟文件选择：构造 `DataTransfer` 对象、`dt.items.add(file)`，再赋值给 `input.files` 并派发 `input`/`change` 事件；当浏览器限制程序化操作 `<input type=file>` 时，退化为对已知 dropzone 元素模拟 `dragenter`/`dragover`/`drop` 事件。
- 后端为 FastAPI + PostgreSQL（含 pgvector 存储向量），前端为 React 仪表盘（简历构建器、求职信、职位追踪看板），插件通过 `externally_connectable`（仅限 `http://localhost:3000/*`）与本地前端通信，架构设计上偏本地自托管而非云端 SaaS。

## 技术栈

| 组件 | 技术 |
|------|------|
| 浏览器扩展 | Chrome Extension Manifest V3，纯 JavaScript + Chrome APIs（`scripting`、`activeTab`、`storage` 权限） |
| 后端 | FastAPI、PostgreSQL + pgvector |
| 向量匹配 | SentenceTransformer `all-MiniLM-L6-v2`（384 维向量），用于简历-职位描述匹配打分 |
| 前端 | React（登录、简历构建器、求职信、职位追踪看板） |
| LLM | 本地 LLM，默认 Ollama，或 LM Studio / 兼容 OpenAI 接口的本地服务；未使用云端付费 API |
| 语言占比 | JavaScript ~48.6%，Python ~42.3%，CSS ~5.8%，HTML ~3.3%（GitHub 统计） |

是否使用 AI/LLM：**是**，但定位是"生成申请问题的定制回答"和"简历-JD 语义匹配打分"，而非驱动表单自动化本身——表单字段识别和填充是规则/正则匹配，不经过 LLM。

## 支持平台/网站

README 中声称通用兼容 "LinkedIn/Indeed/Workday/Greenhouse/Lever/etc."，但由于 content script 是通过 `<all_urls>` 通配注入 + 通用正则识别字段，并非针对每个 ATS 单独写选择器适配层。README 也坦承职位自动追踪功能存在局限："如果某个职位没有被捕获，很可能是因为该网站没有可靠地暴露 title/company 信息，可按需求添加站点专属选择器"，说明目前主要依赖通用启发式，专用适配有限。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动，人工在提交环节保留控制权。**

- 用户在插件弹窗中点击 "Auto Fill" 触发一次性批量填表；对于需要文字回答的文本域，插件会在旁边加 "Fill" 按钮，由用户逐个点击触发本地 LLM 生成候选答案。
- README 及代码中均未发现"自动点击提交按钮"的逻辑；职位追踪功能的描述是"用户提交申请后，插件记录该职位状态为 applied"，即插件观察/记录用户的提交动作，而不是替用户代为提交。
- 因此整体流程是：插件自动填充字段 + LLM 辅助生成回答 → 用户人工检查并点击提交 → 插件记录追踪状态。这是明显的人机协作（human-in-the-loop）模式，而非无人值守全自动投递。

## 反爬虫/验证码/风控应对

**README 和已读取的源码（contentscript.js）中均未发现任何 CAPTCHA 检测、绕过或用户提示机制**，也没有请求速率限制、随机延时、User-Agent 伪装等反爬对抗设计。项目定位是"辅助用户手动操作时自动填字段"，运行在用户真实浏览器会话中（而非无头/远程浏览器自动化），因此天然不太触发常见的机器人检测，但对验证码等挑战没有专门应对代码。

## 局限性

- 仓库规模较小（14 stars，创建于 2024-02-28，最后更新 2025-09-09），属于个人/小众开源项目，非广泛验证的成熟产品。
- 无 LICENSE 文件，README 中标注"仅供个人使用，注意敏感信息安全"，开源协议不明确，若要在其他开源项目中参考/复用需注意授权问题。
- 表单字段识别基于通用正则 + label 文本匹配，对结构复杂、字段命名不规范或使用 iframe 隔离较深的 ATS（如部分 Workday 定制表单）可能识别率不稳定；文件上传的 DataTransfer 方案在部分浏览器安全策略下可能失败，需要 dropzone 兜底。
- 未见有测试套件、CI 或站点专属适配层的证据；跨 ATS 的可靠性依赖社区反馈迭代（README 原文邀请用户"按需求添加站点专属选择器"）。
- 依赖本地 LLM（Ollama/LM Studio）和本地 PostgreSQL/pgvector 环境，部署门槛高于纯浏览器插件类竞品。

## 参考来源

- https://github.com/sainikhil1605/ApplyEase
- https://raw.githubusercontent.com/sainikhil1605/ApplyEase/main/README.md
- https://raw.githubusercontent.com/sainikhil1605/ApplyEase/main/manifest.json
- https://raw.githubusercontent.com/sainikhil1605/ApplyEase/main/contentscript.js
- https://api.github.com/repos/sainikhil1605/ApplyEase
