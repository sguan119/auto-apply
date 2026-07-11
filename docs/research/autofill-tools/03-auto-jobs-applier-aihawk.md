# Auto_Jobs_Applier_AIHawk —— 自动填表实现调研

- 项目地址/官网: https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk （原名 `linkedIn_auto_jobs_applier_with_AI` / `Auto_Jobs_Applier_AIHawk`；仓库已于 2026-05-17 被作者归档，只读）。知名镜像/延续仓库：`AIHawk-FOSS/Auto_Jobs_Applier_AI_Agent`（内容与主仓一致）。
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: **源码验证（部分）+ 基于公开资料推测（部分）**。原因：仓库当前保留的源码（`main.py`、`src/libs/llm_manager.py`、`src/resume_schemas/*`、`data_folder_example/*.yaml` 等）可直接读取并确认了「简历/求职信 LLM 生成」这部分的实现细节；但真正驱动 LinkedIn Easy Apply 表单点击/填写的核心引擎（`ai_hawk/bot_facade.py`、`ai_hawk/job_manager.py`、`ai_hawk/llm/llm_manager.py` 中的 `GPTAnswerer` 类）在 `main.py` 里的 import 已被注释掉（`# from ai_hawk.bot_facade import AIHawkBotFacade` 等），说明这部分代码已从当前公开仓库中被整体移除。该部分的实现方式只能依据历史报道、社区讨论及仓库残留的接口/命名反推，不能逐行核对源码，故整体定为"部分源码验证"。

## 核心实现方式

该项目号称 "the first Jobs Applier AI Web Agent"，其被媒体广泛报道（Business Insider、TechCrunch、The Verge、404 Media 等）的核心能力是：**登录用户自己的 LinkedIn 账号 → 按条件筛选职位 → 对每个 Easy Apply 职位自动点击并用 LLM 逐题作答 → 提交投递**，据 TechCrunch 报道单账号可做到「一小时投递 17 个职位」的量级（累计 2843 个职位）。

从仓库残留代码可确认的 LLM 答题逻辑（`src/libs/llm_manager.py` 中 `GPTAnswerer` 类）：

- `answer_question_textual_wide_range(question)`：先用 LLM 把问题分类到简历的某个语义分区（`personal_information`、`self_identification`、`legal_authorization`、`work_preferences`、`education_details`、`experience_details`、`projects`、`availability`、`salary_expectations`、`certifications`、`languages`、`interests`、`cover_letter` 之一），再用对应分区的数据 + 该分区专属 prompt 模板生成具体回答。
- `answer_question_numeric(question, default_experience=3)`：让 LLM 结合简历中的教育/工作/项目经历推断数字类回答（如"你有几年 XX 经验"），用正则从 LLM 输出中抽取数字，抽取失败则回退到默认值。
- `answer_question_from_options(question, options)`：LLM 先给出倾向性文本答案，再用 `Levenshtein` 编辑距离 (`find_best_match`) 把 LLM 输出与表单里真实存在的选项做模糊匹配，纠正 LLM 自由文本和下拉框固定选项之间的偏差。
- `is_job_suitable()`：投递前先让 LLM 给当前职位描述与简历打"匹配分数 + 理由"，低于阈值 (`JOB_SUITABILITY_SCORE`) 的职位可被跳过，起到自动化职位过滤的作用。
- `resume_schemas/job_application_profile.py` 定义了与 LinkedIn Easy Apply 常见题型高度对应的结构化字段（self identification / legal authorization / work preferences / salary expectations / availability / certifications / languages 等），说明该 profile 就是为回答 LinkedIn 申请表单里的 EEO 自我认定、工作授权、期望薪资等标准问题而设计的。

主仓库当前仍然可用、且未被移除的功能，只剩"简历/求职信生成"这一条链路（`main.py` → `ResumeFacade` → `ResumeGenerator`/`StyleManager`）：读取 `plain_text_resume.yaml`，结合目标职位 URL 抓取的 JD，用 LLM 生成定制化简历 PDF 或求职信 PDF（通过 Selenium 调 Chrome DevTools 的 `Page.printToPDF` 把生成的 HTML 转成 PDF，见 `src/utils/chrome_utils.py` 中的 `HTML_to_PDF`）。真正"打开 LinkedIn → 搜索职位 → 点击 Easy Apply → 逐题填表 → 提交"的自动化引擎已不在当前公开代码里。

## 技术栈

- 语言：Python。
- 浏览器自动化：`selenium==4.9.1` + `webdriver-manager`（自动下载/管理 ChromeDriver），`requirements.txt` 中还包含 `undetected-chromedriver==3.5.5`，这是社区常用于降低 Selenium 特征、规避网站反爬检测的 ChromeDriver 补丁包（说明历史版本确实在意被 LinkedIn 识别为自动化流量的问题，但仓库残留代码里目前找不到调用它的具体位置）。
- LLM 层：基于 `langchain`（`langchain-openai`、`langchain-anthropic`、`langchain-google-genai`、`langchain-ollama`、`langchain-community` 等）封装的多模型适配器 `AIAdapter`，`llm_manager.py` 中明确定义了 `OpenAIModel`、`ClaudeModel`、`OllamaModel`、`GeminiModel`、`HuggingFaceModel`、`PerplexityModel` 等类，`utils/constants.py` 中也列出了 `OPENAI`/`CLAUDE`/`OLLAMA`/`GEMINI`/`HUGGINGFACE`/`PERPLEXITY` 常量，说明支持多种 LLM 提供商可切换（含本地 Ollama）。
- 简历相似度/选项匹配：`Levenshtein` 库做编辑距离模糊匹配。
- 简历解析/生成：`pdfminer.six`（解析已有简历 PDF）、`reportlab`（生成 PDF 样式）、独立仓库 `lib_resume_builder_AIHawk`（`requirements.txt` 里通过 `git+https://github.com/feder-cr/lib_resume_builder_AIHawk.git` 引入）。
- 配置/CLI：`click`、`inquirer`（终端交互式选择）、`PyYAML`、`python-dotenv`。

## 支持平台/网站

以 LinkedIn 为唯一目标平台（工具全名 `linkedIn_auto_jobs_applier_with_AI`，专门针对 LinkedIn 的 "Easy Apply" 一键申请功能）。未见对 Indeed、Greenhouse、Lever 等其他平台的支持。

## 自动化程度（全自动 / 半自动，人工介入点）

- **登录环节**：需要用户手动登录自己的真实 LinkedIn 账号（工具复用用户本人 session，而非做账号池/代投），这是主要的人工介入点。
- **职位筛选条件**：通过 `work_preferences.yaml` 一次性配置（remote/hybrid/onsite、经验等级、工作类型、发布时间范围、目标职位关键词、目标城市、公司/职位/地区黑名单、`apply_once_at_company` 去重开关、搜索半径 `distance` 等），配置完成后按报道描述是**批量自动运行、无需逐条人工确认**地投递（这也是其被媒体称为"投递垃圾邮件式攻击 LinkedIn 招聘方"、引发争议的原因之一——TechCrunch/404 Media 报道的案例中一小时自动投递 17 个职位，累计 2843 个，期间没有人工逐条审核）。
- **简历/求职信生成分支**（当前仓库里仍保留、可运行的部分）里有 `inquirer` 交互式命令行提示（选择简历样式、输入目标职位 URL），这部分需要人工在命令行里做选择，但仍是"生成文件"而非"逐题审核投递内容"。
- 综合来看：AIHawk 定位为**尽量全自动**的批量投递工具，人工介入主要在"配置阶段"（登录、填 YAML、选风格），而不是"审核阶段"（默认不会在提交前逐题弹出人工确认）。这一点在多篇媒体报道中被列为主要风险点。

## 反爬虫/验证码/风控应对

- 依赖 `undetected-chromedriver`（用于对抗常见的 Selenium/WebDriver 指纹检测），以及 `chrome_browser_options()`（`src/utils/chrome_utils.py`）里设置的一系列 Chrome 启动参数（禁用扩展、GPU、动画、翻译提示、弹窗拦截、`--disable-web-security` 等），但这些参数目前只出现在"生成 PDF 用的浏览器实例"里，看不到专门针对 LinkedIn 反自动化的定制逻辑。
- 仓库当前代码里**没有找到**任何 CAPTCHA 自动识别/绕过的实现，也没有找到显式的请求限速/随机延时策略的源码证据。
- 由于账号使用用户本人真实登录态操作（而非无头刷号），封号风险由用户自己承担；多家媒体（Business Insider、Business Insider 报道标题即含 "risks, inaccuracies, mistakes"）明确提示：批量自动投递可能违反 LinkedIn 用户协议，存在被限流/封号的风险,官方文档/README 中目前也没有查到关于"如何应对 LinkedIn 封号"的具体章节（该部分内容可能随引擎代码一起被移除）。

## 局限性

- **最核心的"自动投递引擎"已从公开仓库移除**：作者在 README 中说明"由于版权原因移除了第三方 provider 插件"，但从 `main.py` 里被注释掉的 `ai_hawk.bot_facade` / `ai_hawk.job_manager` / `ai_hawk.llm.llm_manager` 三个 import 来看，实际被移除的是驱动 LinkedIn Easy Apply 全流程的核心模块，当前仓库只保留了"简历/求职信 LLM 生成"这一个子功能，**不能直接拿来跑通"自动登录 LinkedIn 并投递"的完整流程**。
- 仓库已于 2026-05-17 被官方归档（只读），不再接受 PR/Issue，官方表态"聚焦于面向企业招聘方的商业化产品"，社区维护处于停滞状态。
- 媒体和用户反馈中提到 LLM 生成的回答存在"信息不准确/张冠李戴"的问题（如把不相关的经历填进申请表），需要人工事后核对。
- 缺乏 CAPTCHA/风控应对的公开实现，长期或高频使用有被 LinkedIn 限制账号的现实风险。
- 目前只支持 LinkedIn 一个平台，跨平台扩展性有限。

## 主要分支简述

- `AIHawk-FOSS/Auto_Jobs_Applier_AI_Agent`：经核对文件树与 `feder-cr/Jobs_Applier_AI_Agent_AIHawk` 完全一致（同样只保留简历生成部分，同样没有 `ai_hawk` 引擎目录），更像是官方主仓的镜像/延续，而非功能更完整的独立分支。
- 其余在 GitHub 搜索中出现的大量个人 fork（如 `Intusar/Auto_Jobs_Applier_AI_Agent`、`us/linkedIn_auto_jobs_applier_with_AI_fast`、`jomacs/linkedIn_auto_jobs_applier_with_AI`、`pillow34/aihawk`、`11844/Auto_Jobs_Applier_AIHawk` 等）多为个人维护的历史版本快照或小修小补，命名沿用了项目改名前的旧名（`linkedIn_auto_jobs_applier_with_AI` → `Auto_Jobs_Applier_AIHawk` → `Jobs_Applier_AI_Agent_AIHawk`），未逐一深入代码核实差异，只能确认"改名"这条演进线索，具体功能差异未做进一步调研（超出本次调研时间范围）。

## 参考来源
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/main.py
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/src/libs/llm_manager.py
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/requirements.txt
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/data_folder_example/work_preferences.yaml
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/data_folder_example/secrets.yaml
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/data_folder_example/plain_text_resume.yaml
- https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk/blob/main/src/utils/chrome_utils.py
- https://github.com/AIHawk-FOSS/Auto_Jobs_Applier_AI_Agent
- https://techcrunch.com/2024/10/10/a-reporter-used-ai-to-apply-to-2843-jobs/
- https://www.businessinsider.com/aihawk-applies-jobs-for-you-linkedin-risks-inaccuracies-mistakes-2024-11
- https://www.theverge.com/2024/10/10/24266898/ai-is-enabling-job-seekers-to-think-like-spammers
- https://www.404media.co/i-applied-to-2-843-roles-the-rise-of-ai-powered-job-application-bots/
