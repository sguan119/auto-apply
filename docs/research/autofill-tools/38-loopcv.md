# LoopCV（含 LinkedIn Auto Apply）—— 自动填表实现调研

- 项目地址/官网: https://www.loopcv.pro/ 、LinkedIn Auto Apply 落地页 https://www.loopcv.pro/linkedin-auto-apply/ 、博客 https://blog.loopcv.pro/
- 类型: 闭源（SaaS + Chrome 插件，专门的求职自动投递工具）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

LoopCV 的产品模型是"服务端批量匹配投递 + 浏览器插件兜底"的组合，整体分两条路径：

- **服务器端全自动投递（Auto-Apply / "Loop"）**：用户创建一个免费账号并上传简历，设置一个"Loop"（职位搜索任务：目标职位名称、地点、薪资预期、关键词/筛选条件），开启 Auto-Apply 后，LoopCV 声称其 AI 会在服务器端每天自动扫描 LinkedIn、Indeed、Glassdoor 及其他 30+ 招聘网站的新匹配职位，并自动完成投递——即使用户电脑关机、未登录也能持续运行。这部分投递主要针对**支持邮件投递或平台原生 API/表单可被服务端直接提交**的职位（厂商未公开具体技术边界）。
- **浏览器插件辅助投递（Chrome Extension）**：对于需要用户登录态（如 LinkedIn Easy Apply、Indeed、Reed、Dice、StepStone、GulfTalent 等）才能提交的职位，用户在 LoopCV 网页仪表盘中勾选想投递的职位后点击 "Apply"，此时 Chrome 插件被激活，浏览器会跳转到目标招聘网站页面，页面底部出现一条蓝色提示条表示插件正在工作，插件随后自动定位并填写申请表单字段（使用用户在 LoopCV 中已保存的简历/个人信息）。
- **筛选题/自定义问题处理**：若投递过程中遇到额外的筛选问题（screening questions），插件会先把这些问题收集起来，用户需要到 LoopCV 网站的 "Questions" 标签页手动填写答案后重新运行插件；付费用户可开启 "AI Question Answering"（AI 自动回答）功能，由 AI 直接生成并填入答案，无需人工介入。
- 官方文档未说明插件底层是通过 content script 直接操作 DOM，还是结合服务端下发的字段映射规则；结合"蓝色提示条 + 表单自动填充"的描述，推测大概率是 Chrome 插件 content script 扫描目标页面表单 DOM、按字段类型匹配用户 profile 数据填入，复杂/非标准问题则转发给云端服务处理或收集后人工/AI 补齐。
- 官网明确声明"LoopCV 不存储你的 LinkedIn 密码"，暗示投递动作依赖用户浏览器已有的登录会话（cookie/session），而非账号密码托管式登录。

以上均为基于官网、帮助文档及第三方评测文章的技术实现推测，无法确认具体代码实现（如是否使用无头浏览器、Manifest 版本、字段匹配算法细节等）。

## 技术栈（推测）

- 前端/交互层：Chrome 扩展（Manifest 版本未知），通过 content script 在目标招聘网站页面注入 UI 提示（蓝色状态条）并读写表单 DOM。
- 服务端：loopcv.pro 后端 SaaS，负责简历解析存储、职位抓取/匹配（"Loop"任务调度）、AI 问答生成、以及可能的服务端直接投递（针对邮件类或部分平台）。
- 插件与网页仪表盘之间通过账号登录态通信，用户需在目标招聘网站（LinkedIn 等）保持登录会话，插件才能代为提交。
- 未检索到该插件在 Chrome Web Store 的具体权限清单、用户规模、版本号等信息（本次调研未定位到其官方商店页面详情）。

## 支持平台/网站

厂商自述支持的招聘网站/渠道（未逐一验证）：

- 官网宣传"覆盖 LinkedIn、Indeed、Glassdoor 及 30+ 招聘网站"（服务器端自动投递范围）。
- 帮助文档中列出 Chrome 插件明确支持的、需要登录态才能投递的平台：LinkedIn、Indeed、Reed、Dice、StepStone、GulfTalent。
- LinkedIn 场景重点针对 "Easy Apply"（站内快速申请）及部分外部跳转投递（External Apply）形式，落地页标题为 "Auto-Submit Easy Apply & External Jobs"。

## 自动化程度（全自动 / 半自动，人工介入点）

介于全自动和半自动之间，具体取决于使用路径：

- **服务器端 Auto-Apply 模式**：官网宣传为"全自动"——用户设置一次 Loop 后，系统持续扫描并自动投递，全程无需人工确认；但用户仍可在仪表盘中筛选/预览职位后再决定是否纳入自动投递范围。
- **插件辅助模式（如 LinkedIn）**：需要用户在仪表盘中手动勾选具体职位并点击 "Apply" 触发插件；遇到额外筛选问题时，默认需人工在 "Questions" 页面手动作答（除非开通付费的 AI 自动问答）；官方帮助文档中未明确说明插件填完表单后是"自动提交"还是"停在确认页等待用户点击提交"，但第三方评测（resumejudge.com 的 14 天实测）明确指出插件**会自动提交申请**，且因此出现过投给已关闭职位、投给公司 CEO 邮箱、AI 生成语无伦次的问答内容等误投问题。
- 综合来看，人工介入点主要在"选择要投递的职位"和"人工问答兜底"两处，最终投递提交动作本身厂商宣传/第三方实测均倾向于自动完成，而非逐条人工确认点击提交。

## 反爬虫/验证码/风控应对

- 官网及官方帮助文档中**未检索到任何关于 CAPTCHA 处理、反爬虫绕过、请求限速、账号风控规避机制的公开说明**。
- 官网仅提及"不存储 LinkedIn 密码"这一安全承诺，未涉及自动化行为本身是否会触发平台的机器人检测。
- 第三方评测文章（resumejudge.com）中提到"招聘方/公司普遍反感自动化投递，且他们的系统有办法识别是否使用了自动化工具"，暗示存在被招聘方识别、简历被降权或直接拒绝的风险，但未提供 LoopCV 账号本身被 LinkedIn 封禁/限制的具体案例或数据。
- 结合行业背景常识：LinkedIn 自 2025 年下半年起加强了对第三方自动化/Easy Apply 机器人工具的检测（会识别无头浏览器、DOM 操作痕迹、异常高频操作等），并对触发检测的账号采取警告、功能限制（如暂停 Easy Apply、连接请求）乃至永久封号等措施；类似 LazyApply 等同类工具已被公开报道存在较高封号风险。LoopCV 的 Chrome 插件工作方式（在用户真实登录会话中通过 content script 操作页面 DOM 自动提交）在原理上与这类高风险工具相似，但本次调研**未找到专门针对 LoopCV 账号封禁的独立报道或 Reddit/HN 讨论**，无法确认其实际风险高低，只能视为"结构性存在同类风险，厂商未公开说明应对措施"。

## 局限性

- 官方营销页面（loopcv.pro、blog.loopcv.pro）对技术细节披露极少，"AI"、"自动"等表述多为营销语言，缺乏可验证的技术白皮书或架构说明。
- 未能获取 Chrome Web Store 上该插件的官方页面详情（权限清单、安装量、评分、版本历史等），本报告涉及插件行为的描述主要来自帮助文档（Freshdesk）与第三方评测文章的转述。
- 第三方评测（Trustpilot 4.1 分/122+ 评价、resumejudge.com 14 天实测、jobcopilot.com 对比评测）显示用户体验分化明显：部分用户反馈投递量提升、面试增加；也有较多用户反馈插件经常失效、投递内容出错（投给已关闭职位/错误邮箱）、AI 问答生成内容不合理等问题，说明"官方宣传"与"实际可靠性"之间可能存在较大差距。
- 未找到任何逆向工程、安全研究或技术拆解类文章对 LoopCV 的实现原理做过独立验证。
- 关于账号封禁/风控应对，本报告只能给出基于同类工具的推测性风险判断，无法给出 LoopCV 特有的、有实证支持的结论。

## 参考来源
- https://www.loopcv.pro/
- https://www.loopcv.pro/linkedin-auto-apply/
- https://www.loopcv.pro/autoapply/
- https://www.loopcv.pro/auto-apply-for-jobs/
- https://www.loopcv.pro/manual/
- https://www.loopcv.pro/jobseekers/
- https://www.loopcv.pro/pricing/
- https://www.loopcv.pro/loopcv-reviews/
- https://blog.loopcv.pro/linkedin-auto-apply-bot/
- https://loopcv.freshdesk.com/support/solutions/articles/103000280258-how-can-i-set-up-and-use-the-chrome-extension-
- https://loopcv.freshdesk.com/support/solutions/articles/103000399849-knowledge-base
- https://www.trustpilot.com/review/loopcv.pro
- https://resumejudge.com/blog/loopcv-review/
- https://jobcopilot.com/loopcv-best-alternative/
