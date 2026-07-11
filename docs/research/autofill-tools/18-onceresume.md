# OnceResume —— 自动填表实现调研

- 项目地址/官网: https://github.com/28H2O2/OnceResume
- 类型: 开源（国内，简历自动填写插件）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已直接拉取仓库全部源码文件：README.md、src/manifest.json、src/background.js、src/content.js、src/popup.js、src/popup.html、src/info_form.js、src/info_form.html、src/TODO.md，并逐一阅读确认）

## 核心实现方式

这是一个非常早期、体量很小的 Chrome 扩展（仓库仅 9 star、15 次提交、无正式 release），核心逻辑分散在三处，且存在"声明的内容脚本"与"实际生效的填表逻辑"不一致的情况：

1. **`src/manifest.json` 声明的内容脚本** 只匹配 `https://*.jobs.bytedance.com/*`，对应的 `src/content.js` 文件目前**整个文件的自动填充逻辑都被注释掉了**（`autoFillForm` 函数、`MutationObserver` 监听 DOM 出现表单后自动填充等代码全部是注释，未激活），即声明的内容脚本当前是空壳、不生效。
2. **`src/background.js`** 里有一个 `autoFillForm`，通过点击扩展图标触发 `chrome.scripting.executeScript` 注入执行，但里面用的是**写死的 id 选择器**（`document.getElementById("name-field")`、`"degree-field"`、`"experience-field"`、`"awards-field"`），代码注释自己也写"这里需要根据实际招聘网站的 DOM 结构修改选择器"，看起来更像是未完成的示例代码，而非针对字节招聘真实 DOM 校验过的实现。
3. **`src/popup.js`**（点击弹窗里"🌟一键填写🌟"按钮触发）是目前唯一相对"完整"、真正在使用的填表逻辑：通过 `chrome.tabs.query` 拿到当前激活标签页，再用 `chrome.scripting.executeScript` 把一段填表函数注入到当前页面执行。这段逻辑不针对某个特定网站写死选择器，而是实现了一个**通用的字段识别/打分算法**（细节见下）。

## 技术栈

- 纯原生 JavaScript + HTML（GitHub 语言统计：JS 74.8%，HTML 25.2%），**未使用 Plasmo/WXT/Vue/React 等任何框架或构建工具**，仓库里也没有 `package.json`。
- Manifest V3 Chrome 扩展（`manifest_version: 3`），权限为 `storage`、`activeTab`、`scripting`。
- 弹窗（`popup.html`/`popup.js`）+ 独立信息填写页（`info_form.html`/`info_form.js`）+ 后台 service worker（`background.js`）+ 内容脚本（`content.js`，当前未启用）四件套的标准扩展结构。
- 简历数据以单一扁平对象存于 `chrome.storage.local` 的 `resumeData` 键下，字段包括：`name`、`mobile`、`email`、`identification`、`school`、`degree`、`fieldOfStudy`、`company`、`jobTitle`、`jobPeriod`、`projectName`、`projectRole`、`projectDescription`、`skills`，均为单值字符串（不支持多段教育/工作经历的数组结构）。

## 字段识别算法（popup.js 中的实际实现）

`popup.js` 注入到页面的填表函数里维护了三张同义词表（`labelSynonyms`、`placeholderSynonyms`、`idNameSynonyms`），对页面上所有 `input, textarea` 元素做**加权打分匹配**：

- 检查关联的 `<label>` 文本（或向上遍历父节点查找 `span[class*="label"]`），命中权重 **1.5**；
- 检查 `placeholder` 属性文本，命中权重 **1.2**；
- 检查元素的 `id`/`name` 属性，命中权重 **1.0**；
- 完全匹配得 100 分，部分包含按 `(同义词长度/文本长度)*100` 计算得分，取每个输入框跨三种来源的最高分作为最终匹配字段；
- 匹配成功后对元素赋值并派发 `input`/`change` 事件（模拟用户输入，以兼容 React/Vue 等框架的受控组件）。

这是一种较通用的启发式字段识别方法，而非针对特定网站写死 CSS 选择器；但目前**只处理 `input`/`textarea` 两类元素**，对下拉框（select）、单选/多选、需要点击"+"号新增的动态字段（如多段工作经历）均未支持——这些正是 `src/TODO.md` 中列出的未完成项：
```
## 未完成
- [ ] 输入选择框自动填写
- [ ] 只可以选择的选项自动填写
- [ ] 需要+号的内容自动填写
- [ ] 解析网站的插件可用性
## 已完成
- [x] 简单的输入框自动填写：姓名、邮箱
```

## 支持平台/网站

README 明确写道："目前只适配了字节跳动招聘的极少量信息(*/ω＼*)，正在研究如何高效适配多个网站"。`manifest.json` 中声明的内容脚本匹配规则也只有 `https://*.jobs.bytedance.com/*` 一条。但因为实际生效的填表逻辑是通过 `popup.js` 里的通用 label/placeholder/id 打分算法、在用户当前激活的任意标签页上执行（`popup.js` 中检测"当前网站是否匹配"的域名判断代码同样被注释掉，替换为无条件显示"当前网站可用"），理论上可以在其它网站上尝试执行、但未经验证/未适配，效果不确定。总体上目前**仅正式适配/验证了字节跳动招聘（校园招聘）一个网站**。

## 自动化程度（全自动 / 半自动，人工介入点）

半自动、"一键辅助填充"型工具，人工介入点包括：

1. 用户需先手动在扩展的独立页面（`info_form.html`）里逐项填写自己的简历信息（姓名、手机、邮箱、身份证号、教育/工作/项目经历、技能等），点击"保存信息"存入 `chrome.storage.local`；
2. 在目标招聘网站上需要用户手动点击扩展图标并点击"🌟一键填写🌟"按钮才会触发填充（无自动检测表单出现即填充的行为，因为 `content.js` 里对应逻辑被注释掉了）；
3. README 原文明确提示："稍等片刻，简历信息将自动填写到当前页面中。请检查填写的信息是否正确"——即**填表后由用户人工核对**，工具不涉及"自动提交/自动投递"这一步，只做表单字段自动填充。

## 反爬虫/验证码/风控应对

阅读全部源码后**未发现任何针对反爬虫、验证码、风控（如滑块验证、行为特征伪装、请求限流等）的处理逻辑**。项目本质上是浏览器扩展在用户已登录、真实浏览器环境下操作 DOM（`element.value = ...` + 派发 `input`/`change` 事件），不涉及自动化框架（如 Selenium/Playwright）或后端请求模拟，因此天然不会触发常见的"自动化工具检测"（如 `navigator.webdriver`），但项目本身也没有专门为此设计任何机制——只是因为扩展本来就运行在真实浏览器里。

## 局限性

- 项目非常早期，仅 9 star、15 次提交，无 Chrome 应用商店发布，需手动"加载已解压的扩展程序"安装；
- 内容脚本（`content.js`）声明了但内部逻辑全部被注释、未生效；`background.js` 中的填表函数使用写死的、看起来是占位符性质的选择器（`name-field` 等 id 在字节招聘官网上并不存在），代码内部注释也承认需要"根据实际网站 DOM 结构修改"；
- 实际可用的填表逻辑（popup.js 中的打分算法）只支持文本类输入框（`input`/`textarea`），不支持下拉选择、单选/多选按钮、动态新增的多段经历字段（如多份工作经历），这些都在 TODO 中标记为未完成；
- 简历数据结构是扁平单值字段，无法表达多段教育经历/工作经历/项目经历；
- 不涉及自动提交投递，只做表单填充，投递动作仍需人工完成；
- 未使用 AI/LLM 做字段识别或内容生成，纯规则/同义词打分实现；
- 缺乏跨网站适配框架/插件式适配层，README 自述"正在研究如何高效适配多个网站"，尚处于探索阶段。

## 参考来源
- https://github.com/28H2O2/OnceResume
- https://github.com/28H2O2/OnceResume/blob/main/README.md
- https://github.com/28H2O2/OnceResume/blob/main/src/manifest.json
- https://github.com/28H2O2/OnceResume/blob/main/src/content.js
- https://github.com/28H2O2/OnceResume/blob/main/src/background.js
- https://github.com/28H2O2/OnceResume/blob/main/src/popup.js
- https://github.com/28H2O2/OnceResume/blob/main/src/info_form.js
- https://github.com/28H2O2/OnceResume/blob/main/src/info_form.html
- https://github.com/28H2O2/OnceResume/blob/main/src/TODO.md
