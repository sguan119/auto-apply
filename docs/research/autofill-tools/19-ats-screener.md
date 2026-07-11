# ats-screener —— 实现方式调研

- 项目地址/官网: https://github.com/sunnypatell/ats-screener
- 类型: 开源（ATS 解析模拟工具，非投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（README + 仓库目录结构已核实，但未逐行阅读核心源码文件的具体实现逻辑，故不算"源码验证"）

## 核心实现方式

ats-screener 是一个"模拟 ATS（Applicant Tracking System）如何解析/打分简历"的工具，**不是投递工具**。它的定位是：模拟 6 家主流企业级 ATS 平台（Workday、Taleo/Oracle、iCIMS、Greenhouse、Lever、SuccessFactors）各自不同的简历解析和打分规则，让求职者上传简历后，一次性看到 6 个平台"大概会怎么打分"。项目作者称是学生个人项目，动机是不满市面上付费简历检测工具的"黑箱通用打分"。

处理流程（Processing Pipeline）：
1. 用户上传 PDF/DOCX 简历，文件在浏览器端通过 Web Worker 解析（不上传到服务器）。
2. 解析出结构化文本（章节、日期、联系方式等）。
3. 分别套用 6 个平台各自的打分规则（不同平台在"格式可解析性、关键词匹配方式、必需章节、经验深度与近期性、教育相关性"5 个维度上权重不同，例如 Taleo 是严格字面关键词匹配，iCIMS 是基于 ML 的语义匹配，Greenhouse 号称不做自动打分）。
4. 可选：用户粘贴职位描述（JD），做针对性关键词匹配（Targeted 模式）；不粘贴则是通用 ATS 可读性评估（General 模式）。
5. 将解析出的简历文本（及 JD）发给 LLM，生成按影响力排序的具体修改建议。

仓库目录结构（已通过 GitHub 页面核实）：
- `src/routes/` —— 落地页、扫描页、登录页、历史记录页、API 代理
- `src/lib/components/` —— 打分展示、上传、导航等 UI 组件
- `src/lib/engine/` —— 核心引擎，下设 `parser/`（PDF/DOCX 提取）、`job-parser/`（职位描述解析）、`scorer/`（6 个平台打分规则）、`nlp/`（TF-IDF 与技能分类）、`llm/`（Gemini/Groq 客户端与提示词）、`suggestions/`（生成改进建议）
- `src/lib/stores/` —— Svelte runes 状态管理
- `docs/` —— Astro Starlight 文档站
- `tests/` —— 单元测试与端到端测试

## 技术栈

| 层 | 技术 |
|---|---|
| 前端框架 | SvelteKit 5（Svelte 5 runes），编译型、运行时约 15KB |
| 样式 | 作用域 CSS + 自定义属性，未用 Tailwind |
| 文件解析 | pdfjs-dist（PDF）、mammoth（DOCX），均为浏览器端解析 |
| NLP | 自研 TF-IDF 分词器 + 技能分类词表（覆盖 8+ 行业） |
| LLM | 主用 Google Gemini（README 中提及 Gemma 3 27B / Gemini 3 说法不一致，均来自不同抓取结果，需以仓库实际代码为准），备用 Groq 上的 Llama 3.3 70B；也支持通过 `OLLAMA_BASE_URL` 接入本地 Ollama |
| 鉴权/存储 | Firebase Authentication（Google/邮箱登录）+ Cloud Firestore 存扫描历史；也支持自托管模式下用 LDAP 或纯本地 localStorage |
| 部署 | Vercel 免费层，号称整体基础设施成本为 $0 |
| 测试 | Vitest、Playwright、@testing-library/svelte |

简历文本的**实际打分规则**由自研的 TF-IDF/关键词匹配 + 规则引擎（`scorer/` 下 6 个平台 profile）完成，LLM 只负责在此基础上生成"针对该平台文档化行为"的建议文本，即打分本身不完全依赖 LLM，是"规则引擎打分 + LLM 生成建议"的混合架构。

## 与自动投递/填表流程的关系

ats-screener **明确不包含自动投递/自动填表功能**，README 中直接说明"No auto-apply or autofill functionality"、"No submission to actual ATS platforms"。它的定位是投递流程之前的一个"体检/预检"环节：求职者可以先用它检测自己的简历在目标平台的 ATS 系统下大概能拿多少分、哪里会被解析错、哪些关键词缺失，然后根据建议修改简历，再决定是否/如何投递。

对于"全自动投递脚本"项目而言，这类工具可以作为**简历改写（resume）模块的前置校验环节**：在改写简历后、投递前，插入一个"模拟 ATS 打分"步骤，用规则/关键词匹配方式验证改写后的简历是否会被目标平台的解析器正确识别（比如格式、章节、关键词密度），如果分数过低则退回重新改写，分数达标才进入投递（deliver）模块。这与项目 CLAUDE.md 中"搜索 → 改简历 → 投递"三段式流程可以对应到"改简历"与"投递"之间。但需注意：ats-screener 的打分是"近似模拟"，README 中明确声明分数是基于公开资料和社区报告的近似值，不代表任何平台的真实专有算法，不能作为投递决策的唯一依据。

## 自动化程度（全自动 / 半自动，人工介入点）

整个打分/建议生成过程本身是全自动的（上传后自动解析、自动打分、自动生成建议，无需人工审核这一步）。但工具的"输出结果"是给人看的建议报告，后续是否修改简历、是否投递、投递到哪个平台，完全由用户手动决定和执行——工具本身不会自动修改简历、不会自动投递。因此严格说：**打分/建议生成环节是全自动的，但它只是一个独立的"检测/建议"工具，不构成任何自动化投递链路的执行部分，人工介入点在于"看建议 → 手动改简历 → 手动决定投递与否"。**

## 局限性

- 打分是对 6 家平台文档化行为和社区报告的**近似模拟**，并非这些平台的真实专有算法，作者在 README 中明确声明"do not reflect the actual proprietary algorithms of any platform"。
- 不做真实投递、不做自动填表，与"投递"模块没有直接的代码/API 集成关系，如果要整合进自动投递流程，需要自己开发适配层（例如把打分结果作为决策阈值接入 pipeline）。
- 依赖外部免费层 LLM API（Gemini/Groq）及 Firebase，虽然号称零成本，但涉及第三方服务的可用性和速率限制（README 提到约 14,400 RPD 的限额）。
- 本次调研基于 WebFetch 抓取的 README 内容摘要及 GitHub 目录树页面，**未能逐行阅读 `scorer/`、`nlp/`、`llm/` 目录下的具体源码实现**，因此关于"5 维度打分权重具体如何计算"“TF-IDF 具体实现细节”等技术细节的表述来自 README 摘要转述，无法做到逐行源码级验证；两次抓取对 LLM 具体型号的表述略有出入（一次提到 "Gemma 3 27B primary"，另一次提到 "Google Gemini 3 (primary)"），可能是抓取工具的概括误差或项目本身文档不同版本表述不一致，建议如需精确引用请直接查阅仓库当前的 `src/lib/engine/llm/` 源码或 `README.md` 原文确认。

## 参考来源
- https://github.com/sunnypatell/ats-screener
- https://raw.githubusercontent.com/sunnypatell/ats-screener/main/README.md
- https://github.com/sunnypatell/ats-screener/tree/main/src/lib/engine
