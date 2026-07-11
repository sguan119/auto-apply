# Skyvern —— 自动填表实现调研

- 项目地址/官网: https://github.com/Skyvern-AI/skyvern ; 官网/文档: https://www.skyvern.com/docs
- 类型: 开源（通用浏览器/Agent自动化框架，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（README、GitHub 仓库页、官方文档站的公开介绍性内容；未实际克隆源码逐行阅读 agent 循环 / DOM+视觉融合的具体实现代码，故标注为"基于公开资料推测"而非"源码验证"）

## 核心实现方式

Skyvern 的核心卖点是"用 Vision LLM 替代基于选择器（XPath/CSS selector）的传统 RPA 自动化"。官方 README 原文描述其思路为使用"a swarm of agents to comprehend a website, and plan and execute its actions"（一组智能体协同理解网站、规划并执行操作）。

具体机制上，它在 Playwright 之上叠加了一层 AI 推理层：Playwright 负责浏览器的实际控制（打开页面、点击、输入、截图等），而 Skyvern 的视觉大模型（Vision LLM）负责"看懂"页面截图，把页面上的视觉元素（输入框、按钮、下拉框等）映射为可执行的动作，而不是依赖预先写死的 XPath/DOM 选择器。README 中给出的三个核心优势原文是：

- Zero-shot capability："Skyvern can operate on websites it's never seen before, as it's able to map visual elements to actions"（可以在从未见过的网站上运行，因为它能把视觉元素映射为动作）
- Layout resilience："Skyvern is resistant to website layout changes, as there are no pre-determined XPaths"（对页面改版有韧性，因为不依赖预先确定的 XPath）
- Generalization："Skyvern is able to take a single workflow and apply it to a large number of websites"（同一套工作流可以套用到大量不同网站）

在使用层面，Skyvern 提供 Python SDK（`act`、`extract`、`validate`、`prompt` 等自然语言指令）以及一个无代码可视化工作流编排器（Workflow Builder），支持多步骤任务、循环、条件判断、文件操作等，官方文档还提到复杂多步场景（如"登录 → 跳转到账单页 → 下载发票"）可用 `page.agent.run_task(prompt)` 触发"完整的 AI 任务循环"，即让模型自主规划并执行多轮"感知—决策—操作"。但公开抓取到的文档页面（quickstart/introduction）并未详细展开这个循环内部 DOM 分析与视觉信号如何具体融合、如何逐字段决策的算法细节，只能确认其"视觉优先、辅以 Playwright 执行"的总体设计，未能源码级验证。

## 技术栈

- 后端：Python（GitHub 仓库语言占比约 73.3%）
- 前端（Workflow Builder 界面）：TypeScript（约 23.7%）
- 浏览器自动化底层：Playwright
- LLM 调用：通过 liteLLM 一类的多提供商适配层对接各类模型 API
- 部署：支持 pip 直接安装、Docker Compose、Kubernetes；数据库支持 SQLite（本地）或 PostgreSQL（生产）

## 支持平台/网站

不针对特定招聘网站或平台做适配，定位是通用型网页自动化框架，理论上可以在任意网页上运行，因为它不依赖预先为某个网站编写选择器规则。官方列举的典型应用场景包括：跨网站批量下载发票、自动化求职投递（automated job applications）、物料采购自动化、政府表单填写、保险报价获取、联系表单填写等，"自动化求职投递"被官方明确列为其示例用例之一，但并未提供针对招聘网站（如 LinkedIn、Greenhouse、Workday 等 ATS）的专门优化或内置模板。

## 自动化程度（全自动 / 半自动，人工介入点）

- 默认定位为全自动：给定一个自然语言任务（prompt）后，Agent 自主规划多步操作并执行，无需人工逐步确认。
- 提供人工介入/监督机制：README 提到"livestreaming the viewport of the browser to your local machine"，即可以实时观看浏览器操作画面，便于人工监督、调试或在必要时介入接管，而非强制性的人工审核环节。
- 支持多种 2FA（TOTP、邮箱、短信）以及密码管理器集成（Bitwarden、1Password、LastPass），意味着涉及登录鉴权的流程可以半自动地衔接人工提供的凭据/验证码，而不是完全免人工。

## 反爬虫/验证码/风控应对

开源自托管版本本身不包含专门的反爬虫/验证码破解能力；README 原文明确指出这是开源版与云版的核心区别之一："All of the core logic powering Skyvern is available in this open source repository licensed under the AGPL-3.0 License, with the exception of anti-bot measures available in our managed cloud offering."（核心逻辑开源，但反爬虫措施仅在托管云服务中提供）。托管的 Skyvern Cloud 服务额外提供"anti-bot detection mechanisms, proxy network, and CAPTCHA solvers"（反爬虫检测规避机制、代理网络、验证码求解器），但具体实现细节未公开。也就是说：自建部署需要自行解决 CAPTCHA/风控问题，官方的验证码/反爬能力是商业化云端能力，不随开源代码提供。

## 应用于求职投递场景的可行性简评

优点：官方将"自动化求职投递"列为明确应用场景之一，说明其通用表单填写能力（视觉理解 + 自然语言驱动）理论上可以直接套用到求职投递流程——比如在 Greenhouse/Workday/Lever 等 ATS 页面上自动定位并填写姓名、联系方式、简历上传、问卷题目等，不需要为每个 ATS 单独写选择器脚本，理论上对页面改版有较强鲁棒性；同时其 2FA/密码管理器集成也适配招聘网站常见的账号登录场景。

局限：其一，招聘网站（尤其是求职门户和 ATS）普遍有较强的反爬虫/行为检测机制，而这部分能力在开源版中缺失，若不使用官方付费云服务，自建部署很可能在实际投递中频繁被拦截或触发验证码，需要自行接入第三方反检测/代理/验证码方案；其二，Skyvern 是通用框架，没有为简历字段映射、职位信息结构化、多平台投递状态追踪等"求职场景专属"逻辑做优化，需要在其之上自行搭建业务层（对应本项目"投递"模块所需的职位适配、字段映射等）；其三，视觉/LLM 驱动意味着调用成本和延迟高于传统规则式脚本，且存在模型误判导致误填、漏填的风险，批量投递场景下的稳定性和成本需要额外评估。

## 局限性

- 未获取到其"DOM 分析 + 视觉模型 + LLM 推理"具体融合算法的源码级细节（例如是否真正解析 DOM 辅助定位，还是纯靠截图+坐标推理），公开文档在架构细节上披露有限。
- 反爬虫/验证码能力是云端商业功能，开源自托管版本能力有限，直接影响其在真实招聘网站上的可用性。
- 是通用自动化框架，缺少针对招聘/ATS 网站的专门优化、模板或案例库，落地到"全自动投递"仍需自行开发适配层。
- 本次调研未能直接抓取更底层的架构文档页面（`skyvern.com/docs/llms.txt` 等聚合入口未展开细读），部分细节引用自 README 与仓库主页概览性描述，可能不完全反映最新版本实现。

## 参考来源
- https://github.com/Skyvern-AI/skyvern
- https://raw.githubusercontent.com/Skyvern-AI/skyvern/main/README.md
- https://www.skyvern.com/docs/introduction
