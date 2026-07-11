# 投递模块调研：自动/半自动填表工具清单

> 调研目的：为 `deliver`（投递）模块的设计提供参考，收集市面上已有的自动/半自动填表（求职投递方向为主）工具，仅列名称，不含实现细节。
> 调研时间：2026-07-06

## 一、开源项目（专门做"自动投递/填表"）

### 海外
- ApplyPilot
- AutoApplyMax
- Auto_Jobs_Applier_AIHawk（及其分支：linkedIn_auto_jobs_applier_with_AI、Auto_Jobs_Applier_AI_Agent、LinkedIn_AIHawk）
- Auto_job_applier_linkedIn (GodsScion)
- LinkedIn-Easy-Apply-Bot（nicolomantini 版 / NathanDuma 版 / madingess 的 EasyApplyBot）
- EasyApplyJobsBot
- Workday-Application-Automator
- job_app_filler
- Auto-Job-Form-Filler-Agent
- ApplyEase
- job-application-bot-by-ollama-ai

### 国内（中文平台）
- get_jobs（loks666，支持 BOSS/前程无忧/猎聘/拉勾/智联招聘）
- find-job（noBaldAaa）
- boss_batch_push
- Jobs_helper（海投助手）
- boss-cli
- boss-helper（Ocyss）
- OnceResume（简历自动填写插件）
- ats-screener（ATS 解析模拟，非投递但相关）

## 二、开源通用浏览器/Agent自动化框架（非专为求职，但可用于填表）
- Skyvern
- Browser Use
- Stagehand（Browserbase）
- UI.Vision RPA（iMacros/Selenium IDE 的开源替代）
- Selenium IDE

## 三、闭源——专门的求职自动投递/自动填表工具（多为 SaaS + Chrome 插件）
- Simplify Copilot
- JobFill / Autofill Smartly（jobfill.ai）
- OwlApply
- Anthropos 1-Click Apply
- Swooped
- Huntr（Job Application Autofill）
- Jobfillr
- SpeedyApply
- ResumeUp.ai
- Teal（Autofill Job Applications）
- Careerflow
- JobWizard
- NeuraClick / NeuraCV
- LoopCV（含 LinkedIn Auto Apply）
- LazyApply
- JobCopilot
- Sonara
- AIApply
- Jobright（Application Autofill）
- EarnBetter（Application Autofill）
- Wonsulting / AutoApplyAI（JobBoardAI）
- 自动投简历工具（Chrome Web Store 中文插件）
- OfferNow / 简历闪填
- 求职方舟AI
- 简历自动填写助手（Chrome Web Store）

## 四、闭源——干别的事、但也带自动填表功能的工具

### 密码管理器（表单自动填充是副产品功能）
- RoboForm（Form Filler 是其核心卖点之一）
- Dashlane
- Bitwarden
- 1Password（Universal Autofill）
- LastPass

### 通用文本/表单自动化工具（非求职专用）
- Magical（Text Expander & Autofill）
- Text Blaze

### 简历生成器/求职平台（附带自动填表功能）
- Kickresume
- Rezi
- Enhancv

### RPA 企业级工具（可配置用于网页表单填写）
- UiPath
- Microsoft Power Automate
- Automation Anywhere

### 浏览器原生功能（基线参考）
- Chrome 内置表单自动填充
- Edge 内置表单自动填充
