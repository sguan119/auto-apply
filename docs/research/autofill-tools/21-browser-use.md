# Browser Use —— 自动填表实现调研

- 项目地址/官网: https://github.com/browser-use/browser-use ；文档: https://docs.browser-use.com ；云服务: https://cloud.browser-use.com
- 类型: 开源（通用浏览器/Agent自动化框架，非专为求职）
- 调研日期: 2026-07-06
- 置信度: 源码验证（通过 GitHub API 直接读取了 README.md 全文、`examples/use-cases/apply_to_job.py` 完整示例代码、`browser_use/dom/service.py`、`browser_use/dom/serializer/serializer.py`、`browser_use/dom/views.py`、`browser_use/tools/views.py`、`browser_use/agent/service.py`、`pyproject.toml` 等源码文件；未做本地安装运行，架构描述基于对上述源码的静读理解）

## 核心实现方式

Browser Use 用"索引化的 DOM/无障碍树（accessibility tree）文本表示"作为 LLM 感知页面的主要方式，而非纯截图坐标推理：

1. **抓取阶段**：`browser_use/dom/service.py` 中的 `DomService` 通过 CDP（Chrome DevTools Protocol）分别拉取完整的无障碍树（`GetFullAXTreeReturns`，来自 `cdp_use.cdp.accessibility`）和 DOM 树（`cdp_use.cdp.dom`），再结合 `enhanced_snapshot.py` 提取的布局快照（`computed_styles`、`bounds` 等），构建出携带可见性、位置、样式信息的 `EnhancedDOMTreeNode` 树。支持跨域 iframe（`cross_origin_iframes` 参数）、iframe 层级/数量限制，以及"视口阈值"判断——对滚出可视区域但仍存在的可交互元素，会在结果中给出提示（告知 agent 需要滚动多远才能看到）。
2. **筛选/序列化阶段**：`browser_use/dom/serializer/serializer.py` 的 `DOMTreeSerializer` 结合 `ClickableElementDetector`（识别可点击元素，包括无原生语义标签但通过 `<a>`、`<button>`、`role="button"/"combobox"` 等方式实现交互的元素）和 `PaintOrderRemover`（按绘制层级过滤被遮挡元素），把整棵树精简为 `SimplifiedNode`，并为每个判定为"可交互"的元素分配一个从 1 开始递增的整数索引（`_interactive_counter`），写入 `DOMSelectorMap`（即 `browser_state` 里对 LLM 可见的"元素编号表"）。
3. **提供给 LLM 的表示**：最终产出 `SerializedDOMState`，本质是一份"编号化的可交互元素列表 + 简化 DOM 结构"的文本，供 LLM 阅读后决定"对第几号元素做什么操作"。`browser_use/tools/views.py` 中 `ClickElementAction`、`InputTextAction` 等动作的参数就是 `index: int`，字段说明明确写着"Element index from browser_state"。同时框架也保留了截图能力（`ScreenshotAction`），可作为多模态输入的补充，但索引化文本树是决定"点哪个/填哪个"的主线机制。
4. **动作执行**：LLM 输出结构化的工具调用（如 `input_text(index, text, clear)`、`click(index)`、`upload_file_to_element`、`scroll`、`send_keys`、`extract_structured_data`、`done`），`browser_use/tools` 下的 registry 负责把这些结构化动作转成对应的浏览器操作。

## 技术栈

- 语言：Python（`>=3.11`，README 建议 3.12）
- **浏览器控制层**：早期版本基于 Playwright，但从源码看当前主线已转向**直接使用 CDP**——依赖清单（`pyproject.toml`）中核心依赖为 `cdp-use==1.4.5`，而 Playwright 仅作为**注释掉的可选开发依赖**出现（注释写着 "not actually needed I think"）。`browser_use/browser/` 目录下有 `chrome.py`、`session.py`、`_cdp_timeout.py`、`watchdogs/` 等文件，均围绕 CDP 会话管理展开。README 中还提到新一代 "Browser Use CLI 3.0" 由独立的 [Browser Harness](https://github.com/browser-use/browser-harness) 项目驱动，主打"给 agent 一个直接、可靠的浏览器操作层"而非厚重的抽象封装。
- **LLM 接入**：`ChatBrowserUse()` 是官方针对浏览器自动化优化的模型封装，支持自有模型（如 `bu-2-0`、开源预览模型 `bu-30b-a3b-preview`），也支持通过统一的 `BROWSER_USE_API_KEY` 以"provider/model"前缀调用第三方模型，如 `ChatBrowserUse(model='anthropic/claude-sonnet-4-6')`、`'openai/gpt-5.5'`、`'google/gemini-3-pro'`；同时也可以直接使用各家原生封装类（如示例代码中的 `ChatOpenAI(model='o3')`、`ChatAnthropic`），FAQ 明确提到本地模型可通过 Ollama 运行。
- 依赖库：`cdp-use`（CDP 客户端）、`filesystem`/`tools`/`controller`/`mcp`/`sandbox`/`skills` 等模块化子包（源码目录一览可见）。
- 许可证：MIT（README 明确写明开源库为 MIT License）。

## 支持平台/网站

不针对特定招聘网站做适配，是通用网页自动化框架，理论上可在任意网页运行。官方 README 的 Demos 部分明确给出"Form-Filling"演示，任务原文是 **"Fill in this job application with my resume and information."**，并附带可运行示例代码 `examples/use-cases/apply_to_job.py`；此外还有购物（Instacart 下单）、个人助理（PC 配件查找）等通用场景演示，说明其定位是通用 Agent 框架，求职投递只是众多用例之一，没有内置对 LinkedIn/Greenhouse/Workday 等 ATS 的专门适配层。

## 自动化程度（全自动 / 半自动，人工介入点）

- 默认是"自然语言任务 → Agent 自主规划多步操作 → 自动执行"的全自动模式，`apply_to_job.py` 示例中 Agent 会自行创建分步计划、逐字段填写、最后点击提交并确认成功页。
- 源码级确认了人工介入接口：`browser_use/agent/service.py` 中 `Agent` 类提供 `pause()`、`resume()`、`stop()` 方法，允许在运行中人工暂停/恢复/终止任务（例如在提交前人工复核，或遇到需要人工处理的验证码/异常弹窗时暂停接管）。
- 登录鉴权采取"人工预先完成、程序复用会话"的半自动模式：README FAQ "How do I handle authentication?" 建议复用真实 Chrome Profile（`examples/browser/real_browser.py`，即人工已登录过的浏览器配置文件）、使用临时邮箱账号（AgentMail），或通过 `curl ... | sh` 脚本把本地登录态同步到云端浏览器，而不是让 Agent 自己完成注册/验证码验证等强人工环节。
- `apply_to_job.py` 示例的任务提示里也显式写了"if anything pops up that blocks the form, close it out and continue"，即遇到弹窗类阻断时由 Agent 自行处理，而非等待人工，可见默认设计偏向"尽量全自动"，人工介入是可选的兜底手段而非强制流程。

## 反爬虫/验证码/风控应对

开源自托管版本本身**不包含**反爬虫/验证码破解能力。README 的 FAQ "How do I solve CAPTCHAs?" 原文回答是："For CAPTCHA handling, you need better browser fingerprinting and proxies. Use Browser Use Cloud which provides stealth browsers designed to avoid detection and CAPTCHA challenges."（验证码处理需要更好的浏览器指纹和代理，请使用 Browser Use Cloud，其提供专为规避检测和应对验证码设计的隐身浏览器）。"How do I go into production?" 一节进一步说明生产环境建议使用 Browser Use Cloud API，由其负责：可扩展的浏览器基础设施、内存管理、代理轮换（proxy rotation）、隐身浏览器指纹（stealth browser fingerprinting）、高性能并行执行。也就是说，反爬虫/验证码求解、代理池、指纹伪装均为**付费云服务能力**，开源库本身只提供浏览器操作框架，不解决目标网站的风控对抗问题。

## 应用于求职投递场景的可行性简评

优点：官方直接给出的 `apply_to_job.py` 示例几乎就是"求职投递自动化"的现成范本——它接受一个结构化的求职者信息 JSON（姓名、邮箱、电话、地址、是否需要签证担保、种族/退伍军人/残疾状况等 EEO 问询字段等）和简历文件路径，用自然语言任务描述 + 分步骤指令（按顺序：文本字段 → 简历上传 → 地址字段 → 单选/下拉题 → 开放问答 → 提交并验证成功页）驱动 Agent 完成整份申请表，并通过自定义工具（`@tools.action` 装饰器注册 `upload_resume`）扩展了简历上传能力，最后要求 Agent 用结构化 `final_result` 汇报"检测到的所有问题列表"（这对适配不同 ATS 的问卷字段很有价值，可用于反哺"改简历"模块了解目标表单需要哪些信息）。索引化 DOM/AX 树的方案相比纯截图坐标推理更贴合"精确定位到具体输入框/按钮"的表单填写需求。

局限：其一，示例本身针对单个招聘页面（Appcast/Rochester Regional Health 的申请页）手写了非常详细的分步提示词，说明稳定投递复杂 ATS 表单目前仍依赖较强的任务提示工程，而非"一句话即可泛化到任意 ATS"；其二，求职网站/ATS 普遍有较强的反爬虫与行为检测，而这部分能力（隐身指纹、代理轮换、验证码求解）在开源版中缺失，直接自建部署在真实招聘网站上批量投递时容易被拦截，需要额外接入第三方方案或购买官方云服务；其三，作为通用框架，没有内置"职位信息结构化""多平台投递状态追踪""简历字段到表单字段的语义映射"等求职场景专属逻辑，落地到本项目的"投递"模块仍需要在其之上自行搭建业务适配层；其四，多步骤 LLM 驱动的表单填写在成本与延迟上高于传统规则式脚本，批量投递场景下需要评估 token 成本与稳定性（README 也强调更贵的官方 `bu-*`/云端模型"3-5倍更快、准确率更高"，暗示开源默认路径在速度/准确率上有取舍）。

## 局限性

- 项目正处于架构迁移期（Playwright → 直接 CDP，README 已提到"CLI 3.0"由独立的 Browser Harness 项目驱动），部分历史资料/教程可能仍描述旧版 Playwright 架构，与当前主线代码存在出入。
- 反爬虫/验证码/代理能力是商业云服务的核心卖点，开源自托管版本在真实招聘网站上的可用性会明显弱于官方宣传的云端效果。
- 未实际本地安装运行并对真实招聘网站发起投递测试，`apply_to_job.py` 的执行成功率、跨 ATS 泛化能力等未做实测验证，仅基于源码与官方示例文档做静态解读。
- DOM/AX 树索引与截图两种信号如何在 Agent 决策循环中具体权衡组合（例如何时依赖截图辅助判断），未深入阅读 `agent/service.py` 的完整决策逻辑，仅确认了两者并存这一事实。

## 参考来源
- https://github.com/browser-use/browser-use
- https://raw.githubusercontent.com/browser-use/browser-use/main/README.md
- https://github.com/browser-use/browser-use/blob/main/examples/use-cases/apply_to_job.py
- https://github.com/browser-use/browser-use/blob/main/browser_use/dom/service.py
- https://github.com/browser-use/browser-use/blob/main/browser_use/dom/serializer/serializer.py
- https://github.com/browser-use/browser-use/blob/main/browser_use/dom/views.py
- https://github.com/browser-use/browser-use/blob/main/browser_use/tools/views.py
- https://github.com/browser-use/browser-use/blob/main/browser_use/agent/service.py
- https://github.com/browser-use/browser-use/blob/main/pyproject.toml
- https://docs.browser-use.com
