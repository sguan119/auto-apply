# 投递模块调研：自动填表技术方案总结

> 目的：在 [deliver-autofill-tools.md](./deliver-autofill-tools.md) 列出的工具清单基础上，通读 `autofill-tools/` 目录下全部调研文档，按**技术方案类型**归纳提炼，为 `deliver`（投递）模块的架构设计提供参考。
> 调研时间：2026-07-06 ～ 2026-07-09

## 一、六类核心技术方案

### 1. 选择器/DOM 规则硬编码式（最古老、最常见）
**代表**：LinkedIn-Easy-Apply-Bot 系列、GodsScion、find-job、Jobs_helper、Workday-Application-Automator、job_app_filler

**原理**：预先为目标网站写死 XPath/CSS 选择器 + if/elif 关键词规则（如问题含"sponsor"→答"No"），Selenium/Playwright 驱动点击填写。

**优点**：实现简单、无 API 成本、可预测。

**缺点**：极脆弱——网站一改版选择器就失效（多个项目 Issue 里反复出现"改版后失效"反馈）；跨网站零复用；对开放式问答只能靠关键词兜底，命中率低。这是目前"国内外求职自动化开源项目"里数量最多、但技术含量最低的一类。

### 2. 浏览器插件 + Content Script 注入式（当前商业主流）
**代表**：几乎所有闭源 SaaS 插件（Simplify Copilot、JobFill、OwlApply、Huntr、Careerflow、JobWizard 等 20+ 款）、以及开源的 AutoApplyMax、job_app_filler、ApplyEase

**原理**：Chrome 扩展 content script 扫描页面 `input/select/textarea`，用 label/placeholder/name/id 文本做规则匹配或加权打分，写入值并派发 `input/change` 事件（兼容 React/Vue 受控组件）。

**关键设计共性**：
- **几乎全部商业闭源工具都止步于"填表"，不自动点击最终提交**（Simplify、Huntr、Careerflow、JobWizard 等均在帮助文档明确写"you review and submit yourself"）——这是行业默认的安全阀，用来降低误投和平台风控风险。
- 少数工具（SpeedyApply、JobCopilot、LazyApply、AIApply）提供可选的 "Auto-Submit"/"Full Auto" 开关，但用户反馈这类全自动模式误投率、封号率明显更高（LazyApply 被列入 LinkedIn 插件黑名单，Trustpilot 仅 2.3 分）。

**缺点**：闭源产品完全不披露字段匹配算法；对 Shadow DOM、多步表单、动态渲染组件（Workday 尤甚）兼容性普遍不稳定，是几乎每篇第三方评测的共同吐槽点。

### 3. 逆向内部 API / 协议直连式（国内 BOSS 直聘生态特色）
**代表**：boss_batch_push、boss-helper (Ocyss)、boss-cli

**原理**：不走 DOM 点击，直接调用平台内部接口（如 `wapi/zpgeek/friend/add.json`）或用 protobufjs 手工构造 IM 协议消息挂到页面已有 WebSocket 上发送，复用浏览器已登录的 Cookie/token。

**优点**：无浏览器渲染开销、速度快、不易被"点击行为分析"类风控发现。

**缺点**：完全依赖对私有接口的逆向工程，平台一旦改字段名/加密算法就整体失效（boss_batch_push 的更新日志反复印证）；不处理验证码/滑块；封号风险由逆向 API direct call 本身带来（boss-cli 作者同类项目 wx-cli 就有真实封号案例）。

### 4. Vision LLM / 截图坐标驱动式
**代表**：Skyvern

**原理**：不依赖 DOM 选择器，用视觉大模型"看"页面截图，把视觉元素映射为点击/输入动作，Playwright 只负责执行。

**优点**：对页面改版、从未见过的网站有天然鲁棒性（零样本泛化）。

**缺点**：成本和延迟显著高于规则式；开源自托管版本不含验证码/反爬能力（这些是官方云服务的付费功能）；缺少求职场景专属逻辑。

### 5. LLM + DOM 结构化理解混合式（技术上最先进的一类）
**代表**：Browser Use、Stagehand、ApplyPilot（用 Claude Code 作为投递执行大脑）

**原理**：把 DOM/无障碍树精简、编号化后转成文本喂给 LLM，LLM 输出"对第几号元素做什么操作"的结构化指令，而非直接看截图坐标。Stagehand 额外做了"首次 LLM 推理→动作缓存→后续零 LLM 成本重放，页面变化才重新触发"的工程优化，这个思路对批量投递同一 ATS 模板的不同职位很有价值。

**优点**：比纯视觉方案更精确、更省 token；比纯规则方案更抗改版；Browser Use 官方甚至直接提供 `apply_to_job.py` 求职投递示例。

**缺点**：同样是通用框架，反爬虫/验证码能力都在各自的付费云服务里（Browserbase、Browser Use Cloud），开源自托管版本裸奔；需要自建求职场景的业务适配层。

### 6. RPA 录制回放式
**代表**：Selenium IDE、UI.Vision RPA、UiPath、Power Automate、Automation Anywhere

**原理**："人工演示一遍→生成脚本→批量重放"，为每个元素维护多个候选选择器做容错降级，部分工具（UI.Vision、UiPath）叠加视觉匹配/计算机视觉作为兜底。

**特点**：企业级 RPA（UiPath/Power Automate/Automation Anywhere）技术成熟但为企业内部系统设计，授权成本极高（个人版每年数百至数千美元，无人值守版本更高），且完全不含反爬虫/验证码能力，不适合面向公网、有对抗性风控的招聘网站场景。

## 二、另外两条辅助/参考线

**密码管理器式通用填充**（RoboForm、Bitwarden、1Password、Dashlane、LastPass）：基于固定字段分类法（姓名/地址/电话/信用卡等）+ 关键词匹配或轻量 ML 分类，只解决"基础联系信息"这一层，完全没有简历/工作经历/开放问答能力，不能作为投递引擎，但 Dashlane 的 **SAWF 语义标注体系 + 云端 GenAI 离线打标、生产环境本地小模型毫秒级推理**的架构思路，以及 Bitwarden 的开源字段常量表（多语言关键词库），对设计"字段识别层"有参考价值。

**浏览器原生能力**（Chrome/Edge Autofill）：三层优先级判定（`autocomplete` 属性 > 众包统计 > 本地正则启发式）是一个可复用的设计范式；Edge 的 "Copilot Actions" 已把"提交求职申请"列为官方演示场景，代表浏览器厂商也在探索同一方向，但目前仍是实验性、地域受限的闭源功能。

## 三、贯穿全行业的关键共性发现

1. **"填表"与"提交"被主动分离是行业共识**：几乎所有严肃的商业工具都不自动点击最终提交按钮，只有小部分标榜"全自动"的工具（LazyApply、部分 JobCopilot/AIApply 模式）真正自动提交，但这些工具无一例外伴随着更高的误投率、封号风险和更差的用户口碑。
2. **验证码/反爬能力普遍是"云服务差异化付费项"，开源方案基本不解决**：Skyvern、Browser Use、Stagehand 三个最先进的开源 Agent 框架都把 CAPTCHA 求解、代理池、"可信"浏览器指纹划给各自的商业云服务（Browserbase 等），自托管版本裸奔。
3. **国内平台（尤其 BOSS 直聘）风控是持续军备竞赛**：get_jobs 项目的 Discussion #250 详细记录了 Boss 用 WebAssembly 神经网络分析键鼠轨迹的检测手段，反制手段包括 hook `console.log`/`Function.prototype.toString`、伪装真实 Chrome profile。这类对抗成本高、且随时可能被平台升级打破。
4. **简历字段映射策略分两派**：一派是固定 profile schema（用户手工结构化维护姓名/教育/工作经历等字段，工具做规则匹配），一派是 AI 语义映射（OfferNow 的技术分享最具体：DOM 剪枝去噪 → 整页字段一次性交给 LLM 做批量映射推断，而非逐字段调用，既省 token 又能处理无语义字段名如 `q1_v2`）。后者代表更先进的方向。

## 四、对本项目 deliver 模块的建议

结合"CLI 优先、模块解耦、数据契约"的项目定位（见 [CLAUDE.md](../../CLAUDE.md)），建议技术路线组合：

- **分层架构**：`deliver` 模块内部再分"平台适配层"（少量高频国内平台走专门适配）+ "通用兜底引擎"（覆盖长尾平台），二者共享同一份"简历结构化数据 → 表单字段"的映射接口，符合模块解耦原则。
- **高频平台（BOSS 直聘等）优先做专门适配**，但**不要走逆向私有 API 这条路**（boss-cli/boss-helper 反复印证的接口失效、封号风险，且法律灰色地带不适合开源项目），改用 Playwright + 真实登录态 + 有头/持久化 context 的方式，参考 get_jobs 的 `PlaywrightManager` 单例 + 多 Page 复用 Cookie 设计。
- **通用兜底引擎**优先选 **LLM+DOM 结构化理解**这条路线（参考 Browser Use / Stagehand 思路），而非纯视觉方案：把简化后的 DOM/可交互元素编号列表喂给 LLM 做字段级决策，成本和精度都优于截图坐标推理；Stagehand 的"首次 LLM 推理→选择器缓存→改版才重新触发"思路值得直接借鉴，能大幅降低批量投递同一 ATS 模板（如公司自建 Workday 门户）的 token 成本。
- **默认"只填不交"，提交为显式的、可关闭的最后一步**：这是全行业验证过的安全阀，既降低误投风险，也天然规避大部分基于"批量自动提交"的风控检测——用户可通过配置开关（如 ApplyPilot 的 `--dry-run`）逐步建立信任后再开启全自动提交。
- **验证码等强风控场景不强求自动突破**：不自建打码/反检测能力（该领域投入产出比低、法律风险高），遇到验证码时优雅降级为"暂停+人工处理"或直接跳过标记失败，这也是 get_jobs、GodsScion 等成熟开源项目的共同选择。
- **简历字段映射**采用 OfferNow 展示的"DOM 剪枝 + 批量语义推断"模式，而非逐字段正则匹配：既能处理无语义字段名，又比逐字段调用 LLM 更省成本。

## 参考来源

详见 `autofill-tools/` 目录下各工具单篇调研文档及 [deliver-autofill-tools.md](./deliver-autofill-tools.md) 工具清单。
