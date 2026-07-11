# EasyApplyJobsBot —— 自动填表实现调研

- 项目地址/官网: https://github.com/wodsuz/EasyApplyJobsBot （作者 wodsuz；关联的旧仓库 https://github.com/wodsuz/LinkedinEasyApplyJobsBot ；官网/商业化产品已改名为 Apllie.com，原 automated-bots.com）
- 类型: 开源（海外，专门做求职自动投递），采用"开源免费版 + 付费 Pro 版"混合模式
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 WebFetch 直接抓取并解析 GitHub 仓库的 README.md、config.py、linkedin.py 原始文件内容；未做完整的逐行人工代码审查，个别细节可能有遗漏）

## 核心实现方式

EasyApplyJobsBot 是一个与"LinkedIn-Easy-Apply-Bot"系列（如 NathanDuma/LinkedIn-Easy-Apply-Bot）**不同的独立项目**，作者、仓库结构、配置方式均不同，不是同一项目的重命名或 fork，但功能定位高度相似（都是基于 Selenium 的 LinkedIn Easy Apply 自动投递脚本）。

其自动投递流程大致为：
1. 用 Selenium 启动浏览器，用配置的账号密码或已登录的浏览器 profile 登录 LinkedIn（及 AngelCo、GlobalLogic 等站点）。
2. 按 `config.py` 中设置的关键词、地区、经验等级、薪资、发布时间等条件搜索职位列表。
3. 对列表中标记为 "Easy Apply" 的职位点击进入，逐步翻页填写申请表单。
4. 表单填写目前主要针对**电话号码字段**做了较完善的处理：通过多种选择器（`input[type='tel']`、`input[name*='phone']`、`input[id*='phone']` 以及大小写不敏感的 XPath）定位电话输入框并填入配置中的号码。
5. 简历附件通过定位 `//div[contains(@class,'ui-attachment--pdf')]` 元素来选择，依据 `config.preferredCv` 指定的索引选取，若职位只关联一份简历则自动选用。
6. 对于"是否关注该公司"等复选框，代码里有专门针对 `label[for='follow-company-checkbox']` 的点击逻辑。
7. 翻页/提交按钮通过 `aria-label` 定位，如 `button[aria-label='Continue to next step']`、`button[aria-label='Review your application']`、`button[aria-label='Submit application']`，并通过页面进度百分比推算多步表单的总步数后逐步点击。

需要指出：从抓取到的 `linkedin.py` 内容看，脚本对**通用筛选问题（自定义单选/下拉/文本问题）的自动处理能力非常有限**——没有看到针对 radio button、下拉菜单的通用解析与填写逻辑，也没有看到把未回答问题落盘导出的具体代码路径（README 中提到的"未回答问题导出到文件、后续复用"更像是免费版设计目标/文档承诺，具体实现细节在抓取范围内未见到）。真正"通用问题自动作答"能力被明确放在 **付费 Pro 版**（AI 自动补全）。

## 技术栈

- 语言：Python 3
- 浏览器自动化：**Selenium**，配合 `webdriver_manager` 自动管理驱动，`selenium-stealth` 做反检测伪装
- 支持浏览器：免费版仅 Chrome；Pro 版支持 Chrome + Firefox，并支持无头（headless）模式
- 部署方式：推荐 Docker（`docker-compose up --build`），也可本地 `pip3 install -r requirements.yaml` 后直接 `python3 linkedin.py` 运行
- 配置：单一 `config.py` 文件，明文保存账号、密码、浏览器 profile 路径、职位偏好、个人信息、默认答案等

## 支持平台/网站

README 中列出的目标平台包括：**LinkedIn（主要）、Glassdoor、AngelCo(Wellfound)、Greenhouse、Monster、GlobalLogic、Djinni**。但从抓取的源码文件（`linkedin.py`）看，实际重点实现的是 LinkedIn Easy Apply 流程，其余平台的支持程度未在本次抓取范围内验证。

## 自动化程度（全自动 / 半自动，人工介入点）

- 默认目标是"全自动"投递：脚本会自动搜索、自动点翻页按钮、直至点击最终 Submit application 按钮完成投递。
- 提供 **dry-run（演练）模式**：开启后脚本会走完整个流程但**不点击最终提交按钮**，让用户可以先预览行为，是主要的人工确认点。
- 免费版对于个性化筛选问题（非标准字段）依赖用户预先在 `config.py`/YAML 中配置好默认答案（单选、复选框的默认选项等），本质上是"人工预先配置规则 + 脚本套用"，而非运行时智能理解问题语义；遇到未覆盖的问题时的行为（是否跳过/报错/导出）在抓取的源码片段中未见明确实现证据。
- Pro 版加入 AI 自动补全未回答问题的能力，减少人工预配置的工作量，但依然是"预先设置 + 自动执行"，未见有"提交前人工再次确认每一份具体申请内容"的强制审核环节。

## 反爬虫/验证码/风控应对

- 使用 `selenium-stealth` 做反检测（伪装浏览器指纹，规避基础的自动化检测）。
- README 中建议"在函数之间加入时间间隔以防止触发阈值"，并提到会"随机执行停顿、等待、跳过等动作"来模拟人类行为，属于比较基础的行为随机化手段。
- 官方建议**每日投递不超过约 200 个职位**，作为经验性的风控上限，未见有专门的验证码识别/绕过模块。
- 强调脚本运行在用户自己的设备上，流量来自用户自身 IP，以降低被识别为大规模机器流量的风险；未见分布式代理池、验证码打码服务等更工程化的反风控设施。
- README 中还提到市面上存在冒充该项目的"仿冒/钓鱼捐赠链接"仓库，提醒用户核实官方域名，这属于项目维护层面的风险提示，非技术层面的反爬能力。

## 局限性

- 通用筛选问题（自定义 radio/下拉/文本问题）的自动填写能力在免费版中较弱，很大程度依赖用户提前手工配置答案；智能语义理解/AI 作答是付费功能，未开源。
- 未见到成体系的表单字段类型识别引擎（如根据 label 文本自动匹配问题类型），目前明确用代码处理的只有电话号码字段、简历选择、"关注公司"复选框等少数固定场景。
- 反爬虫手段较基础（stealth + 随机延时 + 经验性投递上限），没有验证码自动识别/绕过能力，遇到平台风控升级容易失效。
- 项目已走向商业化（Docker 一键部署、付费 Pro 版、改名为 Apllie），免费开源版本的功能与付费版本存在明显功能分级，长期是否继续维护免费版存在不确定性。
- 多平台（Glassdoor、Greenhouse、Monster 等）支持广度在文档中宣称，但本次抓取的源码文件主要集中在 LinkedIn 逻辑，其余平台的实现深度未验证。

## 参考来源
- https://github.com/wodsuz/EasyApplyJobsBot
- https://raw.githubusercontent.com/wodsuz/EasyApplyJobsBot/main/README.md
- https://raw.githubusercontent.com/wodsuz/EasyApplyJobsBot/main/config.py
- https://raw.githubusercontent.com/wodsuz/EasyApplyJobsBot/main/linkedin.py
- https://github.com/wodsuz/LinkedinEasyApplyJobsBot
