# LinkedIn-Easy-Apply-Bot（多分支）—— 自动填表实现调研

- 项目地址/官网:
  - https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot （独立实现，star 数最高：1134 star / 420 fork，最近一次 push 2025-11-28，本次调研的主要对象）
  - https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot （另一条独立代码线的最初作者，256 star / 86 fork，最后 push 2023-06-11，已停止维护）
  - https://github.com/madingess/EasyApplyBot （NathanDuma 版的下游 fork，由 voidbydefault、madingess 接力维护，173 star / 136 fork，最近 push 2025-03-12）
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: **源码验证**。三个仓库的 README、`config.yaml`、以及核心自动化脚本（`easyapplybot.py` / `linkedineasyapply.py`）均通过 `gh api` 直接拉取并逐行阅读确认，未依赖二手转述。

## 核心实现方式

"LinkedIn-Easy-Apply-Bot" 不是单一项目，而是**同名/近名但代码互不相关的至少两条独立谱系**，详见下方"各分支差异简述"。两条谱系的核心思路一致，均为：**Selenium 打开真实 Chrome → 用用户名密码登录 LinkedIn → 按关键词+地点拼 URL 翻页搜索 → 逐条职位点击 "Easy Apply" 按钮 → 遍历表单分组（`jobs-easy-apply-form-section__grouping` / `pb4`）→ 按预置规则匹配并作答 → 点击 Next/Review/Submit → 结果写入本地 CSV**。全程没有调用任何 LLM，答题逻辑是纯规则/关键词匹配。

以 star 数最高的 `nicolomantini/LinkedIn-Easy-Apply-Bot`（`easyapplybot.py`）为例，关键函数：

- `fill_out_fields()`：遍历 `jobs-easy-apply-form-section__grouping`，只专门处理"Mobile phone number"一种字段，直接把 `config.yaml` 里的 `phone_number` 填进去。
- `send_resume()`：一个 while 循环，按顺序检测"上传简历/求职信按钮是否存在" → 存在则 `send_keys(本地文件路径)` 上传；再检测 Submit / 报错提示(`artdeco-inline-feedback__message`) / Next / Review / Follow 按钮，出现报错提示（说明有必答题未填）时调用 `process_questions()` 逐题作答，循环直到出现 Submit 或 Easy Apply 按钮重新出现（视为跳过）。
- `process_questions()` + `ans_question()`：对每个问题文本做 `.lower()` 后的关键词匹配，例如包含 `"sponsor"` → 答 "No"；包含 `"do you "`/`"have you "`/`"are you "`/`"can you"` → 答 "Yes"；包含 `"salary"` → 答 `config.yaml` 里的 `salary`；包含 `"gender"`/`"race"`/`"lgbtq"`/`"ethnicity"`/`"nationality"` → 统一答 "Wish not to answer" / "I do not wish to self-identify"；**未命中任何规则时**，答案设为字符串 `"user provided"` 并 `time.sleep(15)`，同时把问题+答案追加写入本地 `qa.csv`，供人工事后检查或下次复用。
- 上传文件的匹配方式是"用输入框旁的标题文字去匹配 `config.yaml` 的 `uploads` 字段名"（README 原文：程序读取输入框标题，与 config 里的 key 做匹配），而不是结构化简历字段映射。

`NathanDuma/LinkedIn-Easy-Apply-Bot`（及其下游 `madingess/EasyApplyBot`）是另一套独立代码（`linkedineasyapply.py`），思路相同但配置结构更细：

- `__init__` 从 `config.yaml` 读取 `personalInfo`（姓名/电话/地址/GPA 等结构化字段）、`checkboxes`（driversLicence/requireVisa/legallyAuthorized/urgentFill/commute/degreeCompleted/backgroundCheck）、`industry`/`technology`（按行业和技术栈分别配置"工作年限"数字，含 `default` 兜底值）、`languages`、`eeo`（gender/race/veteran/disability/citizenship）等多组结构化配置。
- `fill_up()` 遍历表单分组 `pb4`，用分组标题（如 "home address" / "contact info"）分派到 `home_address()` / `contact_info()` 等专用函数；`contact_info()` 里对"phone number"分组会先选国家区号下拉框（`select_dropdown`），再填手机号。
- 额外问题的处理函数（README 中出现的 `additional_questions`，源码可见其分支逻辑）同样是**关键词匹配 + 选项模糊选择**：例如问题含 `"sponsor"` → 取 `checkboxes.requireVisa`，再在下拉选项里找包含 "no"/"yes" 字样的那一项点击；含 `"authorized"/"authorised"` → 取 `checkboxes.legallyAuthorized`；含 `"gender"/"veteran"/"race"/"disability"/"latino"` → 优先选选项文本里带 "prefer"/"decline"/"don't"/"none" 字样的那项（即优先"拒绝回答"）；未命中任何规则的选项类问题，兜底逻辑是"选包含 yes 的选项，否则选最后一个选项"。
- `send_resume()` 通过找到上传 `input[name='file']` 的**前置兄弟节点文字**判断是"resume"还是"cover letter"，再分别 `send_keys` 对应路径。

两套实现的共同点：**均无 AI/LLM**，纯 if/elif 关键词规则 + config.yaml 结构化字段；均用 CSV 记录投递结果（前者按职位记录 `output.csv`，后者按搜索关键词分文件 `output+地点.csv`）。

## 技术栈

- 语言：Python 3。
- 浏览器自动化：Selenium（`nicolomantini` 版用 `webdriver_manager` 自动管理 ChromeDriver 并显式检测本机 `chromedriver`/`chrome`/`chromium` 可执行文件路径；`NathanDuma`/`madingess` 版用较老的 Selenium API，如 `find_element_by_id`，需要手动放置 chromedriver）。
- 依赖库：`beautifulsoup4`（配合 `lxml` 解析页面）、`pandas`（记录/去重已投递的 jobID、读写 `qa.csv`）、`pyautogui`（`avoid_lock()` 用鼠标移动+按键防止系统休眠锁屏，`nicolomantini` 版实际调用被注释掉未启用）、`PyYAML`（读 `config.yaml`）。
- 配置格式：`config.yaml`（两条谱系字段结构完全不同，互不兼容）。
- 无任何 LLM/AI SDK 依赖（`requirements.txt` 中未见 `openai`、`langchain` 等包）。

## 支持平台/网站

仅 LinkedIn 一个平台，且专门针对其 "Easy Apply"（一键申请）功能；URL 拼接中显式带 `f_LF=f_AL`（LinkedIn Easy Apply 筛选参数）。未见对 Indeed、Glassdoor 等其他平台的支持（同名衍生项目 `wodsuz/EasyApplyJobsBot` 在描述中提到 "Linkedin, Glassdoor, etc"，但那是另一个独立仓库，不在本次核心调研范围内）。

## 自动化程度（全自动 / 半自动，人工介入点）

- **登录**：需要用户在 `config.yaml` 里明文填写 LinkedIn 邮箱+密码，脚本自动登录（`nicolomantini` 版代码中有一段被注释掉的 2FA 检测逻辑 `2fa_oneClick`，如启用则登录后固定 sleep 15 秒等待人工处理二次验证）；`NathanDuma` 版有更明确的 `security_check()` 函数：检测到 URL 含 `/checkpoint/challenge/` 或页面含 "security check" 字样时，会执行 Python 内置 `input("Please complete the security check and press enter in this console when it is done.")`，**阻塞式暂停脚本直到人工在命令行按回车**——这是该分支唯一显式设计的人工介入点。
- **搜索与投递循环**：职位搜索、翻页、点击 Easy Apply、上传简历/求信、点击 Next/Review/Submit 全部自动，无逐条职位人工确认或预览环节。
- **问答环节**：优先靠关键词规则/结构化配置自动作答；`nicolomantini` 版遇到未命中规则的问题时，是"自动填入占位字符串 `user provided` 并等待 15 秒"，README 和代码注释都未提供真正暂停等待人工输入的机制（`time.sleep(15)` 之后仍会继续走后续流程，相当于该题极可能未获得真实有效答案，需要用户提交后自行核查、并事后编辑 `qa.csv`）；`NathanDuma`/`madingess` 版对未覆盖的问题类型采用"兜底选 yes 或最后一个选项"的策略，同样不会真正暂停。
- 综合看：**默认按"全自动、不逐条人工审核"运行**，仅在触发 LinkedIn 安全验证（部分分支）或极少数未预期的题型上有轻量的人工兜底/事后复核机制，不存在提交前的人工二次确认环节。

## 反爬虫/验证码/风控应对

- Chrome 启动参数层面：`nicolomantini` 版在 `browser_options()` 里加了 `--disable-blink-features=AutomationControlled` 等参数以降低被识别为自动化浏览器的概率；`NathanDuma`/`madingess` 版未见类似专门的反检测参数。
- 随机化：翻页/滚动间隔使用 `random.uniform(...)` 生成的随机等待时间（`nicolomantini` 版部分随机 sleep 调用实际被注释掉未生效；`NathanDuma` 版的滚动函数 `scroll_slow` 每步之间有 `random.uniform(1.0, 2.6)` 秒随机延时），意图让操作节奏更接近人类。
- CAPTCHA：**没有任何自动识别/绕过 CAPTCHA 的实现**。对 LinkedIn 的安全验证/人机质询，`NathanDuma` 版靠 `security_check()` 暂停并要求人工在浏览器里完成后回车继续；`nicolomantini` 版对应的 2FA 检测代码整段被注释掉，处于未启用状态，相当于遇到验证时脚本行为不确定。
- 防休眠：`pyautogui` 实现的 `avoid_lock()`（Ctrl+Esc 组合键 + 鼠标移动）用于防止长时间挂机时系统休眠打断脚本，而非用于反爬虫。
- 频控：仅有"两天内已投递过的 jobID 不再重复投递"的本地去重（`get_appliedIDs`，靠读取历史 CSV 按时间戳过滤），没有账号级别的每日投递上限或退避策略。
- 两个 README 都明确写了"教育目的免责声明"，提示滥用可能导致 LinkedIn 账号被限制或封禁，风险由用户自担。

## 局限性

- 项目高度碎片化：同一功能定位有多个互不兼容的独立实现（见下），选择困难，且部分分支已多年未更新（`NathanDuma` 版最后一次提交在 2023 年）。
- 答题逻辑是纯关键词/规则匹配，覆盖不到的题型只能靠兜底策略（大概率答案不准确）或需要人工事后核查 `qa.csv` / 手动介入，无法像基于 LLM 的方案那样理解开放式问题语义。
- 严重依赖 LinkedIn 页面 DOM 结构（class 名、`aria-label` 等），LinkedIn 前端一旦改版，选择器容易失效（Issues 中可见如 "The Program is not really applying" 等因页面结构变化导致失效的反馈）。
- 无 CAPTCHA 自动处理能力，遇到安全验证需要人工干预，无法做到无人值守的长时间运行。
- 明文在 `config.yaml` 里存储 LinkedIn 账号密码，存在密钥/凭据泄露风险（README 特别提醒"编辑后不要把该文件提交进版本库"）。
- 仅支持 LinkedIn 一个平台，无法复用到 Indeed、Greenhouse 等其他招聘系统。

## 各分支差异简述

同名项目实际是至少两条独立谱系，彼此代码、配置格式、字段设计完全不同：

1. **`nicolomantini/LinkedIn-Easy-Apply-Bot`**：独立实现，star/fork/近期活跃度均最高（1134★/420 fork，2025-11-28 仍有 push）。`config.yaml` 结构较简单（username/password/positions/locations/salary/rate/uploads/blacklist/experience_level），上传文件靠"表单标题文字 ↔ config key"做模糊匹配；未命中的问题填占位符 `user provided` 并记录到 `qa.csv`。
2. **`NathanDuma/LinkedIn-Easy-Apply-Bot`**：另一条独立代码线的最初作者（256★/86 fork），`config.yaml` 字段远比 1 复杂（personalInfo/checkboxes/industry/technology/languages/eeo 等结构化配置），已停止维护（最后 push 2023-06）。
3. **`madingess/EasyApplyBot`**：README 明确写明是 `NathanDuma` 版的下游延续——先由 `voidbydefault`（`voidbydefault/EasyApplyBot`）接手改进和维护，后由 `madingess` 继续维护至今（173★/136 fork，2025-03 仍有更新），配置结构和核心逻辑与 `NathanDuma` 版一脉相承。
4. 生态中还存在若干名称相近但代码独立的第三方项目（如 `wodsuz/EasyApplyJobsBot`、`fao89/Easy-Apply-bot`、`JorgeFrias/LinkedIn-GPT-EasyApplyBot`），后者明确加入了 GPT 辅助答题，但均为独立仓库，不属于 "LinkedIn-Easy-Apply-Bot" 这一名称下的三个主要分支，本次未深入调研。

## 参考来源
- https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot
- https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot/blob/master/README.md
- https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot/blob/master/easyapplybot.py
- https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot/blob/master/config.yaml
- https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot/blob/master/requirements.txt
- https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot
- https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot/blob/master/README.md
- https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot/blob/master/linkedineasyapply.py
- https://github.com/madingess/EasyApplyBot
- https://github.com/madingess/EasyApplyBot/blob/master/README.md
- https://github.com/wodsuz/EasyApplyJobsBot
- https://github.com/fao89/Easy-Apply-bot
- https://github.com/JorgeFrias/LinkedIn-GPT-EasyApplyBot
