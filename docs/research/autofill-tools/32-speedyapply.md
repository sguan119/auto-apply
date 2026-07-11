# SpeedyApply —— 自动填表实现调研

- 项目地址/官网: https://www.speedyapply.com/ ；文档: https://docs.speedyapply.com/ ；Chrome 商店: https://chromewebstore.google.com/detail/speedyapply-job-applicati/mbgjopdedgonlbpikjfibkccpmhjbnag
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

SpeedyApply 是一个浏览器扩展（Chrome / Edge / Firefox 均有版本），核心思路是"建立一份结构化的求职者档案（Profile），在打开职位申请页面时自动检测表单并填充"。官网原文描述：打开一个职位申请页后，SpeedyApply 会自动运行填表流程，并弹出一个小的状态提示框告知填充进度。文档中明确写到"仍有一些包含自定义问题的表单需要用户自己补充填写"，说明其覆盖的是标准化字段，对高度定制化的问题字段处理能力有限。

**推测的技术实现**（未见源码，仅基于行为与商店描述推断）：
- 以浏览器扩展的 content script 注入目标页面 DOM，识别输入框（姓名、邮箱、电话、地址、教育经历、工作经历等常见字段）并写入本地保存的档案数据；官网称之为"powerful autofill scripts"（强大的自动填充脚本）。
- 字段识别很可能依赖对常见 ATS（如 Workday、Greenhouse）页面结构/DOM 特征、label 文本或 name/id 属性的规则匹配与模板适配，而非通用的语义理解引擎——因为多篇第三方评测反映其在"非主流/高度定制/较旧的申请系统"上经常失败（如"10 个网站里 3-7 个能正常工作"），这与"针对已知 ATS 模板做规则适配"的实现方式吻合，而非声称的"万能通用引擎"。
- 数据本地优先存储："SpeedyApply's data is stored locally on your computer and Chrome browser"，同时提供云同步选项（用于跨设备同步档案）。
- 应用追踪（Application Tracker）功能会在自动填表/提交后自动记录一条已投递历史，用于后续查看投递了哪些公司/职位。

## 技术栈（推测）

- 前端：Chrome/Edge/Firefox 浏览器扩展（Manifest V3 类扩展，未验证具体版本），体积约 1.13 MiB（Chrome 商店信息）。
- 表单交互：content script 注入 + DOM 操作（填值、模拟点击"下一步"/"提交"按钮）。
- AI 能力（Premium 付费层）：官网与文档提到 "Smart Profile Scoring"（AI 分析职位并推荐最匹配的档案）与 "Generated Responses"（基于用户档案与职位信息生成申请问答的定制回答），并有 "Smart Response Context" 允许用户补充背景信息影响 AI 生成的回答。未公开具体使用的模型/后端（是否调用第三方 LLM API 无法确认）。
- 后端：应为云端账号系统 + 档案存储服务（用于云同步、AI 生成功能），具体架构未公开。

## 支持平台/网站

- 官网宣称"兼容 25+ 种 ATS 平台"（Compatible with 25+ ATS platforms），并声称可访问"超过 100 万条职位"。
- Chrome 商店描述中明确点名的平台为 **Workday** 和 **Greenhouse**，其余平台名称未在公开材料中列出完整清单。
- 第三方评测提到其在 **LinkedIn** 及各公司自建招聘页面（company career pages）上也可使用。
- 多篇第三方评测反映实际兼容性不稳定：有评测者称"10 个职位网站里只有 3 个能正常工作"，另一评测者称"10 个里有 7 个失败"，且在美国以外地区表现更差。这说明官方宣传的"25+ 平台"覆盖范围与实际稳定性之间可能存在差距。

## 自动化程度（全自动 / 半自动，人工介入点）

SpeedyApply 提供**可配置的自动化程度**，而非单一模式：

- 默认/基础模式：仅自动填充表单字段，用户仍需自行检查并点击"提交"按钮（第三方评测原文："SpeedyApply only autofills the form fields. You still review the application and click submit yourself."）。
- 高级设置（文档 `docs.speedyapply.com/settings/autofill` 中列出）包含可开关的选项：
  - **Auto-Click Next Page**（自动点击"下一步"，用于多步骤申请表单的自动翻页）；
  - **Auto-Submit**（填充完成后自动提交申请）；
  - **Save Responses / Save Applications**（保存问答与投递记录以便复用/追踪）。
- 官网营销页面提到一个更高阶的付费功能 **"Auto Pilot"**，描述为"Complete automation that fills and submits applications from start to finish"（从头到尾全自动填写并提交），这意味着在开启该功能后可以实现**无需人工点击的全自动投递**。
- 文档同时提醒：即便开启全部自动化选项，遇到自定义问题（custom questions）时仍需要人工介入补充作答。

综合来看：SpeedyApply 同时支持"半自动（人工最终确认提交）"与"全自动（Auto-Submit / Auto Pilot 全流程无人工确认）"两种模式，具体行为由用户在设置中选择，而非固定为某一种。

## 反爬虫/验证码/风控应对

未在官网、文档、Chrome 商店描述及查阅到的第三方评测中找到任何关于 CAPTCHA 处理、反爬虫规避、IP/指纹伪装等风控应对机制的公开说明。也没有证据表明该工具内置了验证码识别或绕过能力。鉴于其运行在用户自己的浏览器会话内（而非云端无头浏览器批量抓取），遇到的验证码理论上仍需用户本人手动完成；但这一点纯属推测，官方未做说明。

## 局限性

- 官方宣称的"25+ ATS 平台"未给出完整清单，公开可确认的仅有 Workday、Greenhouse 及 LinkedIn/公司自建职位页面。
- 多篇第三方评测（jobcopilot.com、resumejudge.com）反映实际兼容性远低于宣传，在非主流或较旧的申请系统上经常失败或填充不完整，海外（非美国）网站表现更差。
- 对于包含自定义问答（custom screening questions）的申请表单，官方文档明确承认无法完全自动化，仍需人工补充。
- 有用户反馈存在数据丢失问题（保存的投递历史/档案信息在数月未使用后消失），以及客服响应差、退款纠纷等产品体验问题（第三方评测提及，未经官方证实）。
- AI 生成回答（Generated Responses）、智能档案评分（Smart Profile Scoring）等功能均为 Premium 付费专属，具体使用的模型/算法未公开。
- 由于是闭源产品且没有公开的技术白皮书，以上关于"规则匹配 / DOM 注入 / 模板适配"的实现推测均无法通过源码验证，仅供参考。

## 参考来源
- https://www.speedyapply.com/
- https://docs.speedyapply.com/
- https://docs.speedyapply.com/autofill
- https://docs.speedyapply.com/settings/autofill
- https://chromewebstore.google.com/detail/speedyapply-job-applicati/mbgjopdedgonlbpikjfibkccpmhjbnag
- https://jobcopilot.com/speedyapply-review/
- https://resumejudge.com/blog/speedyapply-review/
- https://addons.mozilla.org/en-US/firefox/addon/speedyapply-job-form-autofill/
- https://mypersonalrecruiter.com/speed-apply/
