# SPEC —— 投递模块（deliver）技术规格

> 承接 [deliver-prd.md](./deliver-prd.md)（做什么）→ 本文档写「怎么实现」的技术决策。
> 每条决策记录 **结论 + 理由 + 排除的替代方案**，目的是避免以后绕回来重新讨论。
> 本文档随讨论推进增补；技术选型（地基）与行为细节 / 数据契约均已定，剩余小项见文末「待续」。

## 决策速览

| 决策 | 结论 | 作用域 |
|---|---|---|
| 语言 / 运行时 | **Python** | 全系统 |
| CLI → Website 分层 | **core 纯 Python 包 + 薄入口层** | 全系统 |
| 浏览器驱动 | **Playwright** | deliver |
| 执行架构 | **A：自研「DOM 精简+编号 → LLM 决策 → Playwright 执行」循环** | deliver |
| 数据契约 | **Pydantic 模型 + 内存调用**；PDF 等大文件传路径 | 全系统 |
| 投递状态机 | 单职位 8 状态；**SUSPENDED 可恢复 = 重投而非恢复现场** | deliver |
| 遇阻问询 | **QuestionChannel 抽象 + 按页批量 + 超时挂起** | deliver |
| 去重 / 重试 | 投递记录唯一键回喂搜索；**默认不自动重试失败** | deliver |
| 存储 | **SQLite（记录/凭据）+ bio.yaml + JSONL 日志** | deliver（bio 全系统） |
| 配置与密钥 | **config.toml（非密钥）+ .env / 环境变量（密钥）** | 全系统 |

---

## 一、语言 / 运行时：Python（全系统统一）

**结论**：三大模块（search / resume / deliver）统一用 Python，单一运行时。

**理由**：
1. **搜索模块被 JobSpy 锚定**——JobSpy 是 Python 库（根 PRD 第三节写死），项目至少有一个模块躲不开 Python。
2. **单运行时成本最低**：开源 + 个人维护 + 未来打 Docker，双运行时意味着两套依赖管理、两套测试、两个 Docker base、贡献者装两套环境，代价很实。
3. Playwright-Python 是一等公民，跑得动执行架构 A；LLM 可插拔用 Python SDK 层抽象即可。

**排除的替代方案**：
- **Node / TS**：唯一站得住的理由是现成框架 Stagehand（TS-only），但选定架构 A 后不引 Stagehand 本体（只借其缓存思路），这个理由消失。前端 JS 不构成反例（见决策二）。

## 二、CLI → Website 分层（全系统）

**结论**：核心逻辑做成**纯 Python 包 `core`（零界面假设）**，CLI 与未来 Web 后端都是薄薄一层入口，共用同一套 core。对应 [CLAUDE.md](../CLAUDE.md) 「核心逻辑与界面分离」约束。

```
入口层：  CLI (typer/click, 薄)      Web 后端 (FastAPI, 薄, 未来加)
                    └──────────┬──────────┘
核心层：        core（search / resume / deliver，纯 Python）
                               │
表现层：              Web 前端（React/Vue/htmx，浏览器里天生 JS）
```

**要点**：
- **前端 JS 与后端语言无关**：任何 Web 应用前端都得是 JS/HTML，这是所有方案都躲不掉、且被隔离在最外层的一层，不影响「后端单运行时」的初衷。
- **CLI 与 Web 共用 core 的接缝**：PRD 第七节的 **API 模式**——每个模块写成可被调用的服务，CLI 和 Web 后端各自薄薄包一层。
- **「遇阻才问」的通道可替换**：CLI 在终端问，Web 用 FastAPI 的 WebSocket/SSE 往前端推问询，底层是同一套 core，只换问询通道的实现。
- deliver 跑的是**服务器端自己的 headless Playwright**，不碰用户浏览器 → Web 化无障碍。

## 三、浏览器驱动：Playwright（deliver）

**结论**：用 Playwright（Python）作为浏览器驱动层。

**理由**（多数由 PRD 约束反推得出）：
1. **PRD 要 headless + API 模式**（第七节）→ 能无头/服务器端跑。
2. **PRD 不打反检测战**（第五节：不自建反检测、不做代理池/IP 轮换）→ 反检测类驱动卖点归零，可挑 API 最干净的。
3. **表单动态且多步（Workday 尤甚）** → Playwright 的**自动等待**省掉大量手写等待与 flaky 代码。
4. **登录态问题**（LinkedIn / Workday 需账号）→ **持久化 context** 复用 profile cookie；必要时 `connect_over_cdp` 挂到真实已登录 Chrome。
5. **门开着**：browser-use / Skyvern 未来想用都在 Playwright 之上。

**排除的替代方案**：
- **Selenium**：更啰嗦、更 flaky；我们走 LLM+DOM 不抄硬编码选择器，吃不到它的生态红利。
- **浏览器扩展 / content script**（商业插件那套）：需挂在有界面的桌面 Chrome，**与 headless/API 模式冲突**。
- **undetected-chromedriver / nodriver 等反检测驱动**：唯一卖点被 PRD「不打反检测」直接砍掉。

> 注：Playwright 是**驱动层**；browser-use / Skyvern / Stagehand 是叠在其上的「大脑」层，与本决策正交。

## 四、执行架构：A —— 自研命令式循环（deliver）

**结论**：自研 **「DOM 精简+编号 → LLM 决策『填哪个编号、填什么』 → Playwright 执行 → 逐页重复」** 的命令式循环（即 PRD 第三节的技术方案）。借 **Stagehand 的缓存思路**（首次 LLM 推理 → 缓存选择器 → 页面改版才重算）作为**降 token 补丁**，但不引 Stagehand 本体。

**排除的替代方案**：
- **B：Agent + browser-MCP**（Claude/其它模型 + Playwright-MCP 等，ApplyPilot 路子的标准化版）：起步快，但**每步过大模型、成本高**、绑 Agent 生态、批量投递贵；缓存补丁本质是在给它省钱。
- **视觉 CUA / Computer Use**（OpenAI Operator、Anthropic Computer Use、Google Mariner）：**吃截图**，被 PRD「不用视觉截图」（第三节）直接排除。

---

## 五、数据契约：Pydantic 模型 + 内存调用（全系统）

**结论**：模块间契约用 **pydantic 模型**定义，模块间以 **Python 对象在进程内直接传递**（core 是单进程包，CLI / Web 后端都在进程内调 core，见决策二）。PDF 等大文件**不进对象体，只传路径**。需要落盘或跨进程时序列化成 JSON；契约本身可由 pydantic 自动导出 JSON Schema，供文档与贡献者参考。本条同时回答 [CLAUDE.md](../CLAUDE.md) 待定项「数据契约格式与传递方式」。

**deliver 侧核心契约**（字段清单实现期可微调，但**增删字段必须回来改这里**）：

```python
class JobRef(BaseModel):
    """搜索模块输出中 deliver 依赖的子集。唯一键 = (platform, job_id)。"""
    platform: str          # 来源平台，如 "linkedin" / "indeed"
    job_id: str            # 平台内职位 ID；无 ID 平台用规范化 URL 代替
    url: HttpUrl           # 投递入口（官网/ATS 优先，见 PRD 二）
    title: str
    company: str
    score: float           # 搜索模块评分，决定投递顺序

class DeliveryTask(BaseModel):
    """deliver 的输入：一个待投职位 + 为它定制的材料。"""
    job: JobRef
    resume_pdf: Path       # 改简历模块产物，路径约定见「九、存储」
    cover_letter_pdf: Path | None

class DeliveryRecord(BaseModel):
    """deliver 的输出：一次投递的结果记录（PRD 八）。"""
    job: JobRef
    status: DeliveryStatus            # 见「六、投递状态机」终态
    filled_fields: list[FilledField]  # 每个表单字段：问题原文、填入值、值来源(bio/LLM生成/用户回答)
    failure_reason: str | None        # 如 "captcha_unsolved" / "login_failed"
    run_id: str
    started_at: datetime
    finished_at: datetime

class BioWriteback(BaseModel):
    """用户回答回写 bio 的载体（PRD 四）。"""
    field_path: str        # bio 内的字段路径，如 "preferences.visa_sponsorship_needed"
    question: str          # 表单原始问题，留档
    answer: str
```

- **bio schema 属 bio 模块**，另立文档；deliver 只依赖「按字段路径读 + 回写」两个接口，不依赖其内部结构。
- **PDF 路径约定**：改简历模块把产物写到 `data/artifacts/<platform>/<job_id>/resume.pdf`（及 `cover_letter.pdf`），`DeliveryTask` 里仍显式传路径——约定只为可调试性，契约不隐式依赖目录结构。

**理由**：
1. 决策二已定 core 为单进程纯 Python 包，内存调用是最短路径；文件/队列在 MVP 阶段是自找的复杂度。
2. pydantic 给校验、序列化、JSON Schema 导出三件套，开源协作时契约不随代码漂移。
3. PDF 走路径避免大二进制在对象里传拷，与「记录进 SQLite、文件进目录」的存储分工一致。

**排除的替代方案**：
- **JSON 文件交换**：进程级解耦是优点，但多一层读写与文件生命周期管理，API 模式下反而绕。将来真要拆进程，pydantic 对象 `model_dump_json()` 即得同构 JSON，迁移成本已预留。
- **dataclass + 手写 JSON Schema**：省一个依赖，代价是校验/序列化/schema 导出全手写，不值。

## 六、投递状态机（deliver）

**结论**：单个职位的生命周期如下；**恢复 = 从头重投，不恢复浏览器现场**。

```
PENDING → OPENING → AUTHENTICATING → FILLING ⇄ WAITING_USER
                                        │
                          （手动模式停）READY_TO_SUBMIT
                                        │
                                   SUBMITTING → CONFIRMING → SUCCEEDED
任意阶段失败 → FAILED(reason)；WAITING_USER 超时 → SUSPENDED（非终态，可恢复）
```

- **PENDING**：进入本次 run 的投递队列（按分数降序）。
- **OPENING**：打开职位 URL，跟随跳转到官网 / ATS 落地页。
- **AUTHENTICATING**：需要账号时登录；无账号则自动注册（PRD 六）——注册表单复用 FILLING 同一套 LLM+DOM 循环，邮箱验证码经只读邮箱自动取回。凭据读写见「九、存储」。
- **FILLING**：逐页循环「DOM 精简+编号 → LLM 决策 → Playwright 执行」（决策四）。**验证码是 FILLING / AUTHENTICATING 内的子步骤**（识别类型 + sitekey → CapSolver 求解 → 注入），不是独立状态；求解失败 → `FAILED("captcha_unsolved")`，跳过不重试（PRD 五）。
- **WAITING_USER**：本页有拿不准字段，抛问询等回答（见「七」）。回答到达 → 回写 bio → 回到 FILLING；超时 → SUSPENDED。
- **READY_TO_SUBMIT**：仅手动投递模式（PRD 七，默认模式）停在此处，通过问询通道请求用户确认后才进 SUBMITTING；自动模式直接穿过。
- **CONFIRMING**：等待并识别**提交确认页**，看到即 SUCCEEDED，否则 FAILED（PRD 八的成功判定）。
- **终态**：`SUCCEEDED` / `FAILED(reason)`。**SUSPENDED 是持久化的非终态**：问题与职位入库，答案补上后（本次 run 末尾或下次 run 开头）**从 OPENING 重投**。

**理由（为什么恢复=重投）**：挂起可能长达几十分钟到跨天，保留 Playwright 现场（内存、会话有效期）不现实；重投前表单尚未提交，操作幂等，且 bio 已回写，理论上不会再卡同一字段，重投成本只是几次页面加载。

**排除的替代方案**：
- **挂起时冻结浏览器 context 等待原地续填**：会话过期、headless 服务器内存占用、崩溃后不可恢复，复杂度远超收益。
- **把验证码做成独立状态**：验证码可能出现在登录、注册、表单任意页，建模成任意状态内的子步骤更贴合现实。

## 七、遇阻问询机制（deliver）

**结论**：core 定义 **`QuestionChannel` 抽象接口**；**按页批量**问询；**超时挂起该职位、继续投下一个**。

- **通道抽象**：`QuestionChannel.ask(questions, timeout) -> answers | TIMEOUT`。CLI 实现 = 终端交互问答；未来 Web 实现 = FastAPI WebSocket/SSE 推给前端（决策二已预留接缝）。手动投递模式的「确认提交」也走同一通道，不另起机制。
- **按页批量**：LLM 本来就对整页一次决策，同一页内所有拿不准的字段（bio 缺失 / 低信心，PRD 四）合并为一次问询抛出。多步表单必须提交当前页才能见下一页，**按页就是批量上限**——跨页批量在物理上做不到。
- **超时挂起**：等待时长可配置（`question_timeout`，默认 30 分钟）。超时未答 → 职位置 SUSPENDED，未答问题持久化入库；run 继续投下一个职位。答案到达后（CLI 下次交互 / API 补答接口）先回写 bio，再按「六」的规则重投。
- **无人值守闭环**：一次 run 结束时，所有 SUSPENDED 职位的未答问题在汇总里集中列出（见「八」），用户一次性补答，下次 run 自动消化。

**排除的替代方案**：
- **无限阻塞等待**：严格贴合 PRD 四的字面流程，但用户离开时整个 run 卡死，直接违背「无人值守」核心原则。
- **超时按失败处理**：实现最简，但用户回来后已错过职位，答案也没地方补——白问。
- **逐字段问询**：同一页 3 个不确定字段打扰 3 次，问答间隔里流程空转，纯劣势。

## 八、跨运行去重、重试与 run 汇总（deliver）

**结论**：

- **去重**：投递记录表以 `(platform, job_id)` 为唯一键。**SUCCEEDED 的职位永不再投**；搜索模块通过 core 接口 `get_delivered_job_keys()` 查询已投列表做去重回喂（根 PRD 三「已投过的自动跳过」）——走接口不直读对方存储，守住模块解耦。
- **失败不自动重试**：验证码失败 PRD 五已定不重试；其余失败（登录失败、确认页未出现等）同样**默认不跨 run 自动重投**——失败原因大概率是环境性的（改版、风控），盲目重试烧 token 还可能重复提交。留 CLI 命令按 job key **手动重投单个职位**。
- **SUSPENDED 自动恢复**：例外——下次 run 开始时，凡问题已补答的挂起职位**优先于新职位**重投（分数排序在挂起组内保持）。
- **Easy Apply 日限计数**：滚动 24h 计数持久化入库（PRD 二的 ≈50 上限），到顶转官网投递或排队次日。
- **run 汇总**：每次 run 落一条 run 记录；结束时产出 `RunSummary`（pydantic 契约）：总数 / 成功 / 失败按原因分组 / 挂起 + 未答问题清单。CLI 打印表格，API 模式作为返回值。

**排除的替代方案**：
- **搜索模块直读投递库去重**：少一个接口但产生跨模块隐式存储耦合，违反 CLAUDE.md 约束。
- **失败自动重试 N 次**：对「页面改版/风控」这类主因无效，且自动重复提交有误投风险，与行业「安全阀」共识相悖（调研三.1）。

## 九、存储（deliver 为主，bio 全系统）

**结论**：**SQLite 单库 + bio 单文件 + JSONL 过程日志**，按数据形态分工：

| 数据 | 载体 | 说明 |
|---|---|---|
| 投递记录 / 凭据 / 挂起问题 / run 记录 / Easy Apply 计数 | **SQLite 单库** `data/app.db` | 需要按键查询（去重）、事务写入；future 多 worker 并发写也扛得住 |
| bio | **`data/bio.yaml` 单文件** | 用户要手工维护的单一事实源，必须人类可读可编辑；YAML 对多行文本（经历描述）友好 |
| 过程日志 | **JSONL** `logs/run-<run_id>.jsonl` | 按 run 切分、逐行追加（步骤、LLM 决策、验证码求解、报错），供调试与审计（PRD 八） |
| 简历产物 | 文件目录 `data/artifacts/…` | 见「五」的路径约定 |

- **凭据明文存储**是 PRD 六已定的决策，此处只落实现：进 `app.db` 的 credentials 表。
- **`.gitignore` 必须排除** `data/`、`logs/`、`.env`（下节）——落实 CLAUDE.md「敏感数据绝不入仓库」的硬约束。

**排除的替代方案**：
- **全 JSON 文件**：零依赖，但投递记录量大后去重要全量加载，并发追加写易损坏文件；SQLite 在 Python 是标准库，实际依赖成本为零。
- **全 SQLite（含 bio）**：统一但牺牲 bio 的可编辑性——用户没法用文本编辑器直接改自己的信息，违背「单一事实源、用户可维护」的定位。

## 十、配置与密钥（全系统）

**结论**：**非密钥配置进 `config.toml`，密钥走环境变量（本地开发用 `.env`，被 gitignore）**。仓库提供 `config.example.toml` 与 `.env.example` 作模板。

| 归属 | 内容 |
|---|---|
| `config.toml` | 投递模式开关（auto/manual，默认 manual）、评分阈值、`question_timeout`、Easy Apply 日限、LLM 模型名/`base_url`、密码生成方式（随机/模板）、邮箱 IMAP 地址等**行为参数** |
| 环境变量 / `.env` | `LLM_API_KEY`、`CAPSOLVER_API_KEY`、邮箱只读授权（IMAP 应用专用密码或 OAuth token 文件路径）等**密钥** |

- **阈值来源**：评分阈值是搜索模块的过滤参数，由用户在 `config.toml` 设置、搜索模块消费；deliver 只接收「已过阈值」的列表，不再判断（守住契约边界）。
- **LLM 可插拔**（根 PRD 四）：配置只需 `model` + `base_url` + key，core 内部用统一 LLM 客户端抽象，不绑供应商。

**理由**：配置/密钥分离是开源项目防误提交的标准做法；TOML 有 stdlib `tomllib` 原生解析、与 pyproject 同族，零额外依赖。

**排除的替代方案**：
- **密钥写进 config 文件**：一次误提交就是泄露事故，example 模板也容易被复制成真文件后忘记 ignore。
- **YAML 配置**：能力等价，但要引 pyyaml 才能读（bio 用 YAML 是因为它是**数据**且用户高频手编，两者取舍维度不同）。

---

## 待续（后续 spec 议题）

- **平台适配层抽象**：Workday 之外的平台（Greenhouse / Lever / LinkedIn Easy Apply）如何以最小接口接入通用 LLM+DOM 引擎——待 Workday 端到端跑通后按实际形态提炼（对应 CLAUDE.md 待定项）。
- **bio schema**：字段结构与读写接口，属 bio 模块，另立文档。
- **DOM 精简算法与选择器缓存的具体设计**（决策四的实现细节）：精简规则、编号稳定性、缓存失效判定，进实现阶段再定。
- **多 worker 暂停协调**（PRD 十的 future feature）：同一字段多 worker 撞车时合并问询——单 worker MVP 不阻塞。
