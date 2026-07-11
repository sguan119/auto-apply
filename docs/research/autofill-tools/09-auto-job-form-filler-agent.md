# Auto-Job-Form-Filler-Agent —— 自动填表实现调研

- 项目地址/官网: https://github.com/ajitsingh98/Auto-Job-Form-Filler-Agent （在线演示: https://auto-job-form-filler-agent.streamlit.app）
- 类型: 开源（海外，专门做求职自动投递）
- 调研日期: 2026-07-06
- 置信度: 源码验证（已通过 raw.githubusercontent.com 直接读取 README 及关键源码文件 `google_form_handler.py`、`rag_workflow_with_human_feedback.py` 的内容摘要，非仅凭猜测）

## 核心实现方式

这是一个基于 **Streamlit** 的单体 Web 小工具，而非浏览器自动化脚本或通用 Agent 框架（不使用 LangChain/AutoGPT/browser-use 等）。整体是"简历解析 + LLM 问答 + Google 表单专用适配层"的组合：

- `resume_processor.py`：调用 LlamaIndex + Llama Cloud（LlamaParse）解析用户上传的 PDF 简历，构建可检索的文档索引。
- `google_form_handler.py`：**不使用 Selenium/Playwright，也不调用 Google 官方 Forms API**，而是直接用 `requests` 库发 HTTP 请求。它从表单页面 HTML 中提取内嵌的 `var FB_PUBLIC_LOAD_DATA_ = ...` JavaScript 变量并反序列化，从中还原出全部字段结构（类型、选项、是否必填等），再构造带 entry ID 的 POST 请求提交答案。
- `rag_workflow_with_human_feedback.py`：核心编排逻辑，基于 **LlamaIndex Workflow**（事件驱动、`@step` 装饰器）实现，类名为 `RAGWorkflowWithHumanFeedback`。

因此严格来说，"Agent"一词更多指其采用了 LlamaIndex 的 Workflow/Agent 编排范式（事件驱动的多步骤流水线 + 人工反馈事件），而不是浏览器操作意义上的自动化 Agent；它并不会像 browser-use 类项目那样操控真实浏览器点击网页元素。

## 技术栈

- 语言: Python（仓库 100% Python）
- Web 界面: Streamlit
- 简历解析: LlamaIndex + LlamaParse（Llama Cloud API）
- LLM 接入: OpenRouter（支持 Mistral 7B、DeepSeek R1、Llama 2 70B、Claude 2.1、GPT-4、GPT-3.5 Turbo 等 7 种可选模型）
- 检索问答: LlamaIndex 查询引擎，`tree_summarize` 响应模式，回答失败时回退为直接 LLM 问答
- 嵌入模型: HuggingFace embeddings
- 表单交互: 纯 `requests` 库 + HTML 中的 `FB_PUBLIC_LOAD_DATA_` JSON 结构解析（非官方逆向方案）

## 支持平台/网站

仅支持 **Google 表单（Google Forms）**，不针对任何招聘网站或 ATS（如 Greenhouse、Workday、LinkedIn Easy Apply 等）做适配。README 明确限制：最多支持 20 个表单问题、不支持文件上传类字段、仅支持标准 Google 表单字段类型。定位更接近"用 AI 帮你填一份 Google 表单形式的求职申请"，而非通用求职网站投递工具。

## 自动化程度（全自动 / 半自动，人工介入点）

**半自动，且内置强制的人工审核环节**：

1. 用户上传简历 + 提供 Google 表单链接。
2. 系统解析表单字段，逐题通过 RAG/LLM 生成候选回答。
3. 触发 `InputRequiredEvent`，将生成的完整答卷交给用户审核。
4. 用户可反馈"OKAY"（同意）或提出修改意见（"FEEDBACK"）；若提出修改，工作流会带着反馈重新回到解析/生成步骤，循环迭代。
5. 只有在用户明确批准后，工作流才会进入最终提交步骤。

因此不存在"点一下就无人值守直接投递"的模式，提交前必须经过至少一轮人工确认。

## 反爬虫/验证码/风控应对

源码中**未发现任何**针对 CAPTCHA、速率限制或反自动化机制的处理逻辑。`google_form_handler.py` 纯粹通过普通 HTTP 请求解析和提交表单，一旦目标表单启用了验证码或更严格的反自动化保护，该方案会直接失败，项目本身也没有相应的规避或重试机制。

## 局限性

- 仅适配 Google 表单，无法用于主流招聘网站/ATS 的职位申请页面，实用范围有限。
- 最多处理 20 道题、不支持文件上传字段（意味着无法真正上传简历附件到目标表单）。
- 依赖第三方付费/限额服务（OpenRouter、Llama Cloud），需要用户自备 API Key。
- 无任何反爬虫/验证码应对能力，遇到保护措施会失败。
- 是否为"通用求职自动投递"工具存疑：更像是一个围绕 Google 表单场景的 LLM 辅助填表 Demo/小工具，而非面向各大招聘平台的规模化自动投递系统。

## 参考来源
- https://github.com/ajitsingh98/Auto-Job-Form-Filler-Agent
- https://raw.githubusercontent.com/ajitsingh98/Auto-Job-Form-Filler-Agent/main/README.md
- https://raw.githubusercontent.com/ajitsingh98/Auto-Job-Form-Filler-Agent/main/google_form_handler.py
- https://raw.githubusercontent.com/ajitsingh98/Auto-Job-Form-Filler-Agent/main/rag_workflow_with_human_feedback.py
- https://auto-job-form-filler-agent.streamlit.app
