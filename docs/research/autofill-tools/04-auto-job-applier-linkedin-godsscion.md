# Auto_job_applier_linkedIn (GodsScion) —— 自动填表实现调研

- 项目地址/官网: https://github.com/GodsScion/Auto_job_applier_linkedIn
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测（README + 部分 config 源码通过 WebFetch 摘要获取，未在本地克隆运行代码逐行验证，细节以官方仓库最新版本为准）

## 核心实现方式

项目是一个针对 LinkedIn "Easy Apply" 职位的全流程自动化机器人：自动搜索职位 → 打开 Easy Apply 表单 → 用本地配置好的答案自动填写/回答筛选问题 → 上传简历 → 提交申请，并把结果记录到 CSV（`all excels/all_applied_applications_history.csv`、`all_failed_applications_history.csv`）。README 中宣传可以"一小时内投递 100+ 职位"。

表单字段的回答不是靠实时语义理解，而是靠用户预先在 `config/questions.py` 中为常见问题（工作经验年限、是否需要签证、国籍/工作权限、期望薪资/当前薪资、通知期、作品集/LinkedIn 链接、自我介绍等）写好答案，机器人做字符串/关键词匹配后填入对应表单控件；其中还内置了一些"智能"数值转换逻辑（例如识别问题里提到 "lakhs" 就把年薪数字转换成万分位格式，识别按月填写就把年薪除以 12）。

## 技术栈

- Python
- 浏览器自动化：Selenium WebDriver，配合 `undetected-chromedriver` 包装以降低被识别为自动化脚本的概率（`pip install undetected-chromedriver ...`）
- 驱动安装：可手动下载 ChromeDriver，也提供 `windows-setup.bat` 一键安装脚本（Windows）
- 辅助库：`pyautogui`（模拟鼠标/键盘等人类操作）、`flask`/`flask-cors`（内置一个本地 Web/API 组件）
- 配置以 Python 文件形式存放在 `config/` 目录：
  - `personals.py`：姓名、电话、地址等个人信息
  - `questions.py`：筛选问题的预设答案、简历路径（`default_resume_path`，README 标注为"开发中"）、`pause_before_submit`、`pause_at_failed_question`、`overwrite_previous_answers` 等控制项
  - `search.py`：职位搜索关键词/筛选条件
  - `secrets.py`：LinkedIn 登录凭据，以及可选的 OpenAI API key
  - `settings.py`：机器人运行行为参数（见下）

## LLM 使用情况

支持（但为可选功能）：通过 `secrets.py` 中配置的 OpenAI API key，可以让 GPT 根据职位描述中的技能要求、公司信息等，生成"针对该职位定制"的简历和求职信，或从 JD 中提取技能关键词。README 描述该功能会在本地没有默认简历时触发生成。这并非用于"实时回答任意开放式筛选问题"的通用问答，而更偏向"离线批量生成定制简历/求职信"的辅助功能；`settings.py` 里的 `showAiErrorAlerts` 开关专门用于控制是否显示 AI（OpenAI）接口调用失败的提示。筛选问题本身的自动作答主要还是靠 `questions.py` 里预先配置的静态答案，而非 LLM 实时生成。

## 支持平台/网站

仅支持 LinkedIn，且专门针对 LinkedIn 的 "Easy Apply" 一键申请职位（非 Easy Apply、需要跳转到第三方 ATS 的职位不在自动投递范围内）。

## 自动化程度（全自动 / 半自动，人工介入点）

介于全自动与半自动之间，具体行为由用户配置决定：

- 如果 `questions.py` 里预设的答案覆盖了遇到的所有问题，且 `pause_before_submit = False`、`pause_at_failed_question = False`，可以做到端到端全自动连续投递（`settings.py` 里还有 `run_non_stop` 支持不间断运行）。
- 提供人工介入开关：`pause_before_submit`（提交前暂停等待人工确认）、`pause_at_failed_question`（遇到无法自动回答的问题时暂停，等待用户手动输入答案）。README 特别说明如果 `run_in_background = True`（后台无窗口运行），该暂停机制会失效，因为此时无法弹出界面让用户操作。
- 其余安全/效率相关开关：跳过已投递职位、跳过黑名单公司，避免重复投递；`click_gap` 控制点击/操作之间的最大等待秒数，被描述为"让点击间隔随机化，看起来更像人类行为"。

## 反爬虫/验证码/风控应对

- 使用 `undetected-chromedriver` 而非原生 Selenium ChromeDriver，专门用来降低被网站识别为自动化脚本的概率。
- `settings.py` 提供 `stealth_mode`（默认 True，README 标注为"实验性"的反检测/绕过机制）。
- `safe_mode`（默认 True）：以 Chrome 访客(guest)身份/独立配置文件打开，与用户日常登录状态隔离。
- `run_in_background`（默认 False）、`disable_extensions`、`smooth_scroll`（模拟平滑滚动而非瞬移）、`keep_screen_awake` 等，都是围绕"让自动化过程更像人在正常操作电脑，同时减少对用户日常使用的干扰"设计的。
- `click_gap` 引入操作间随机等待，用于模拟人类点击节奏。
- 项目 README 未提供任何针对图形验证码（reCAPTCHA/hCaptcha 等）的自动破解或识别机制；也没有专门的"CAPTCHA 检测后转人工"逻辑说明，风控应对主要停留在"降低触发概率"（stealth/undetected driver + 随机延时 + 访客模式），而非"遇到验证码后如何处理"。
- README 中包含明确免责声明："This program is for educational purposes only... The creators and contributors of this program emphasize that they bear no responsibility or liability for any misuse, damages, or legal consequences resulting from its usage."，并提示用户需自行承担违反 LinkedIn 服务条款、网页抓取相关法律风险的责任。项目采用 AGPLv3 协议。

## 局限性

- 仅支持 LinkedIn Easy Apply，无法覆盖跳转到外部 ATS 的职位，也不支持其他招聘网站。
- 简历上传/定制（`default_resume_path` 及相关自动生成简历功能）README 中标注部分仍处于"开发中"状态，成熟度有待确认。
- 筛选问题的自动作答本质是"预设静态答案 + 关键词匹配"，不是通用语义理解，遇到未覆盖的问题类型仍需人工预先配置或运行时手动介入（除非放弃 `pause_at_failed_question`，风险是可能提交错误/不完整的答案）。
- 反爬虫手段主要依赖 undetected-chromedriver、随机延时和访客模式等"降低被发现概率"的工程手法，没有解决验证码这一类主动风控挑战的能力，长期高频使用仍存在被 LinkedIn 限制或封号的风险，项目本身也明确声明不为此类后果负责。
- LLM（OpenAI）功能是可选、需要用户自备 API key 的增值特性，并非核心投递流程的必需组件，且描述偏向"生成定制简历/求职信"而非"回答任意开放式问题"。

## 参考来源

- https://github.com/GodsScion/Auto_job_applier_linkedIn
- https://raw.githubusercontent.com/GodsScion/Auto_job_applier_linkedIn/main/README.md
- https://raw.githubusercontent.com/GodsScion/Auto_job_applier_linkedIn/main/config/settings.py
- https://raw.githubusercontent.com/GodsScion/Auto_job_applier_linkedIn/main/config/questions.py
