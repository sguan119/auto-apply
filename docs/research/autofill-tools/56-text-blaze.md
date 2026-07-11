# Text Blaze —— 自动填表实现调研

- 项目地址/官网: https://blaze.today/ （Chrome Web Store: https://chromewebstore.google.com/detail/text-blaze-templates-and/idgadaccgipmpannjkmfddolnnhmeklj）
- 类型: 闭源（通用文本/表单自动化工具，非求职专用）
- 调研日期: 2026-07-06
- 置信度: 基于公开资料推测,非源码验证

## 核心实现方式（推测）

Text Blaze 本质是一个「文本扩展器」（text expander），核心机制是：**浏览器扩展/桌面客户端监听用户输入的文本，一旦匹配到预设的快捷短语（shortcut，如 `/sig`），就在光标处用模板内容替换/插入**。据官方文档，快捷短语可配置为「Anywhere」触发模式，即在单词中间输入也会触发替换（例如把 `\e` 替换为 `é`）。这说明其底层很可能是在页面上下文中挂钩键盘事件监听器，实时匹配输入缓冲区与用户配置的 trigger 列表，一旦命中就模拟删除已输入字符并插入渲染后的模板内容（推测，未验证具体实现）。

在此之上，Text Blaze 提供了「Forms」（表单）能力：一个 snippet 可以内嵌多个可填字段命令（`{formtext}`、`{formparagraph}`、`{formtoggle}`、`{formmenu}`、`{formdate}`）。当用户触发一个包含表单字段的 snippet 时，**不会立即插入文本，而是先弹出一个填写弹窗（popup dialog）**，用户在弹窗里填写/选择各字段的值，确认后 Text Blaze 才会把渲染完成的最终文本一次性插入到当前光标所在的输入框。多个同名（`name` 相同）的表单字段会被联动 —— 一处更新，其余同名字段自动同步，从而支持「一次填写、多处复用」的效果。此外配合 `{if}`（条件判断，含可选 `else` 分支）等命令可以基于表单字段的值做动态分支渲染，从而实现「动态逻辑」。

真正与「多字段自动填网页表单」直接相关的是官方称为 **Autopilot** 的功能集，由三个命令组成：
- `{click}`：通过 CSS 选择器（可用「Select from website」按钮可视化拾取元素）模拟点击页面上的元素，支持跨标签页操作；默认等待 1 秒让元素变为可交互状态，可用 `maxdelay` 参数延长等待时间。
- `{key}`：模拟键盘按键，用于在字段间导航或触发网站快捷键。
- `{wait}`：插入延时，确保异步加载的页面元素就绪后再继续。

据文档描述，Autopilot 命令的运行方式是：**用户手动触发一次 snippet（仍然是打字触发快捷短语），触发后 Text Blaze 依次执行 `{click}`/`{key}`/`{wait}` 序列**，从而实现"点击某个字段 → 填入值 → 等待 → 点击下一个字段 → 填入值……"这样连续操作多个网页表单字段的效果，数据来源可以是表单字段、Data Blaze（其电子表格/数据库产品）中的表格数据、页面内容或 AI 摘要结果。需要强调：**触发方式仍是用户主动激活 snippet，并非全自动无人值守运行**；且官方文档明确提示，如果目标网站的页面结构发生变化，用户需要手动更新 CSS 选择器，Autopilot 不会自动适配页面改版（以上均为根据公开文档的推测，未见源码验证）。

## 技术栈（推测）

官方 FAQ 未公开具体前端/后端技术栈细节，只披露了基础设施与安全方面的信息：
- 客户端形态：Chrome/Edge/Chromium 系浏览器扩展（Brave、Opera、Arc、Vivaldi 等）+ 独立的 Windows / macOS 桌面客户端 + 云端管理后台 dashboard.blaze.today。
- 数据同步：snippet 数据云端存储并跨设备同步，登录依赖 Google 账号鉴权体系。
- 安全声明：传输层使用 TLS（其管理后台在 Qualys SSL Labs 评级为 A+），静态数据用 AES-256 加密；核心系统托管在 Google Cloud Platform，社区论坛托管在 Digital Ocean，均声称具备 SOC 1 / SOC 2 / ISO 27001 认证。
- 浏览器扩展默认不在隐身模式（Incognito）下运行，需手动开启。

以上均为官方公开披露内容，未见任何关于内部实现语言、前端框架或扩展 content script 架构的技术细节（推测部分已标注）。

## 支持平台/网站

官方宣称适用于「任意网站/任意应用」的输入框，包括 Gmail、Google Docs、LinkedIn、Salesforce 等常见办公与协作工具，也提供 LinkedIn 专用的 command pack（预制 snippet 集合）用于招聘/求职消息模板。由于其工作原理是监听通用的文本输入事件并操作 DOM，理论上可以覆盖绝大多数标准 HTML 表单页面；但社区反馈显示，在使用复杂前端框架（如 React 受控组件）的现代 Web 应用（例如 Workday 等 ATS 系统）中，可能出现 snippet 无法正常展开或表单值未被框架状态正确捕获的问题（这是文本扩展类工具的通用局限，官方论坛中有相关求助帖，但未见官方给出通用解决方案）。

## 自动化程度（全自动 / 半自动，人工介入点）

整体属于**半自动/人工触发式**工具，而非无人值守的全自动流程：
- 基础文本扩展：需要用户主动打出触发快捷短语（trigger）。
- Forms 表单填写：用户触发 snippet 后，需要在弹出的对话框中手动填写/选择各字段值，确认后才会插入最终内容——本质上是"填表助手"而非"自动提交"。
- Autopilot（`{click}`/`{key}`/`{wait}`）：虽然可以在一次触发后连续自动执行多步点击/填值操作，减少了人工逐字段填写的动作，但依然需要人工先手动触发该 snippet，且需要人工预先在可视化界面里为每个目标字段配置 CSS 选择器；网站改版后也需要人工重新配置选择器。
- 人工介入点集中在：配置阶段（编写模板、拾取页面元素、设置表单字段与条件逻辑）与触发阶段（打字触发或手动点击运行）。没有发现「定时/后台自动巡检并自动提交表单」这类完全无人值守的能力。

## 反爬虫/验证码/风控应对

未发现任何关于反爬虫、验证码（CAPTCHA）绕过或平台风控规避机制的公开资料。Text Blaze 定位是浏览器内的人工输入辅助工具，其操作（模拟点击、模拟按键、插入文本）都发生在用户已登录、已打开的真实浏览器会话中，行为模式上更接近真人操作，因而不需要也未见其涉及验证码破解或反检测相关技术。此项在其产品定位下大概率不适用/未见相关设计（推测）。

## 应用于求职投递场景的可行性简评

- 可取之处：Forms + Autopilot 的组合思路（可复用的字段模板 + 条件逻辑 + 模拟点击填值）与"投递模块"需要的"根据职位/平台差异填充不同字段"的需求在概念上是高度契合的，可以作为该项目"投递"模块中"如何组织可配置的字段模板与条件分支"的一个参考设计（例如 name 关联字段实现联动、`{if}` 实现按条件生成不同文案）。
- 限制较大：(1) Autopilot 的 CSS 选择器需要人工为每个目标网站手工配置，不具备跨网站/跨 ATS 系统通用适配能力，网站改版即失效，这与本项目希望覆盖多个招聘平台、降低维护成本的目标存在差距；(2) 触发方式仍是"半自动、用户在场触发"，不具备后台无人值守批量投递的能力；(3) 闭源、按订阅收费（Forms/Autopilot 为付费功能），无法直接复用其代码，只能借鉴设计思路；(4) 对 React 等现代前端框架的受控表单存在兼容性风险，而不少招聘平台（如基于 React 的 ATS）恰好属于这一类，实际投递场景可能会踩坑。
- 结论：Text Blaze 更适合作为"表单自动化产品设计"的参考案例（尤其是 Forms 的多字段联动与条件逻辑设计），而不适合直接作为本项目"投递"模块的技术底座或直接依赖对象。

## 局限性

- 本调研仅基于官方网站、帮助文档、Chrome Web Store 页面与社区论坛等公开资料，**未获得、也无法获得 Text Blaze 的源代码**，所有关于内部实现机制的描述均为基于公开行为与文档描述的合理推测，可能与实际实现存在偏差。
- 官方文档中未公开 Autopilot/表单填充的底层技术细节（例如具体如何模拟原生输入事件以兼容 React 等框架、是否使用 `document.execCommand`、`Object.getOwnPropertyDescriptor` 劫持 setter 等常见文本注入技巧），本报告未做该层面的确认，仅指出社区中存在相关兼容性问题反馈。
- 未找到官方对"是否/如何应对反爬虫、验证码"的直接说明，本报告中相关结论基于产品定位的合理推断，而非官方确认。
- AI 相关能力（AI Write 生成 snippet、AI Blaze 写作助手）与"求职投递自动化"关系有限，本报告未深入展开其 AI 模型细节（未在公开资料中找到具体使用的 LLM 提供商/模型名称）。

## 参考来源
- https://blaze.today/
- https://blaze.today/guides/forms/
- https://blaze.today/guides/autopilot/
- https://blaze.today/commands/click/
- https://blaze.today/commands/formtext/
- https://blaze.today/commands/formparagraph/
- https://blaze.today/faq/
- https://blaze.today/guides/ai-write/
- https://blaze.today/aiblaze/
- https://blaze.today/linkedin/
- https://blaze.today/command-packs/linkedin/
- https://chromewebstore.google.com/detail/text-blaze-templates-and/idgadaccgipmpannjkmfddolnnhmeklj
- https://community.blaze.today/t/snippets-w-forms-fields-arent-generating-a-popup/19348
- https://community.blaze.today/t/multiple-clipboard-for-filling-out-webform/21848
