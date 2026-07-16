# 投递模块（deliver）测试用例集 —— 按 PRD 预期行为编排

> 本文档把 [deliver-prd.md](./deliver-prd.md) 的每条需求翻译成「预期行为」测试用例，
> 作为 **验收标准 + 覆盖度核对表**。每条用例标注自动化状态与对应测试位置。
> 可执行版本见 `tests/test_prd_acceptance.py`（按 PRD 章节组织，端到端跑
> adapter→engine→submit→runner 全链路）。

## 覆盖状态图例

| 标记 | 含义 |
|---|---|
| ✅ | 已自动化（**验收级**，`tests/test_prd_acceptance.py`，走 `run_delivery` 全链路） |
| 🔵 | 已自动化（**单元/组件级**，对应 `tests/test_*.py`） |
| ⚠️ | **缺口**：尚无自动化覆盖 |
| ⬜ | 超出当前 MVP（Workday-only 单 worker）范围，暂不实现 |

## 总览

| PRD 章节 | 用例数 | ✅ | 🔵 | ⚠️ | ⬜ |
|---|---|---|---|---|---|
| 一 无人值守 | 1 | 1 | | | |
| 二 投递范围 | 5 | 2 | 1 | | 2 |
| 三 读页面填表 | 1 | 1 | | | |
| 四 字段处理 | 4 | 4 | | | |
| 五 验证码 | 3 | 1 | 2 | | |
| 六 账号凭据 | 6 | 3 | 3 | | |
| 七 运行模式 | 6 | 5 | 1 | | |
| 八 记录日志 | 5 | 5 | | | |
| 九 并发 | 3 | 2 | | | 1 |
| **合计** | **34** | **23** | **7** | **1** | **3** |

**结论**：PRD 核心行为已全部有自动化覆盖（验收 23 + 单元 7 = 30/34）。剩 1 个 ⚠️（注册/登录/邮箱验证的验收级全链路覆盖，组件级已充分）+ 3 个 ⬜（MVP 明确不做的 future feature）。

---

## 一、无人值守，遇阻才问

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| A-1 | 不含拿不准字段的表单，自动模式全自动填完并提交，全程零打扰 | auto 模式；表单只有可从 bio/LLM 填的字段 | 到达 SUCCEEDED；问询通道一次都没被调用 | ✅ | `TestPRD1_UnattendedHappyPath` |

## 二、投递范围（Workday 优先）

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| B-1 | Workday 链接路由到 Workday 适配器 | `myworkdayjobs.com` URL | `select_adapter()` 返回 `WorkdayAdapter` | ✅ | `TestPRD2::test_workday_url_routes_to_workday_adapter` |
| B-2 | 不在范围内的平台干净失败，不崩、不调 LLM | greenhouse URL | FAILED，reason=`no_adapter`；LLM 零调用 | ✅ | `TestPRD2::test_non_workday_url_has_no_adapter` |
| B-3 | Workday 登录门禁页被识别（→ AUTHENTICATING 的入口） | 含密码框 + "Sign In" 文本的页面 | `needs_auth()`=True；`open_application()` 返回 `needs_auth` | 🔵 | `test_workday_adapter::test_sign_in_gate_detected` |
| B-4 | 优先公司官网/ATS 投递（而非 Easy Apply） | 同时有 Easy Apply 与官网入口 | 选官网 | ⬜ | MVP 仅 Workday 官网，无 Easy Apply 分支 |
| B-5 | Easy Apply 每日 ≈50 上限，到顶转官网/次日 | 24h 内已投 50 次 | 触发限流处理 | ⬜ | 存储骨架已建（`increment_easy_apply`），MVP 不触发 |

## 三、读页面与填表（LLM + DOM）

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| C-1 | DOM 精简+编号 → LLM 决策 → Playwright 执行，逐页填完 | 任意表单 | 字段被正确填入并推进 | ✅ | 全部验收用例隐含驱动此链路；DOM 精简单测见 🔵 `test_dom` |

## 四、字段处理规则

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| D-1 | 开放式问答由 LLM 现场生成，**不阻塞** | "为什么加入我们" 类字段 | 无问询；记录 value_source=`llm_generated`；投成功 | ✅ | `TestPRD4::test_open_ended_question_is_generated_not_blocked` |
| D-2 | bio 缺失字段 → 问用户 → 回写 bio → **继续投完当前职位** | needs_user 字段，有人应答 | 当前 run 内到 SUCCEEDED（非挂起）；答案写入 bio | ✅ | `TestPRD4::test_uncertain_field_asks_then_writes_bio_then_completes_same_job` |
| D-3 | 拿不准字段无人应答（超时）→ 挂起该职位等补答 | needs_user 字段，无应答 | SUSPENDED；未答问题入库 | ✅ | `TestPRD4::test_unanswered_uncertain_field_suspends_job` |
| D-4 | 「填了但信心低」作为独立触发（≠ bio 缺失） | bio 已有该字段值，LLM 仍标低信心 | 照样问询（证明触发与 bio 缺失解耦） | ✅ | `TestPRD4::test_low_confidence_field_asks_even_when_bio_has_value` |

## 五、验证码 / 反爬

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| E-1 | 求解失败（未配打码服务）→ 标记失败、跳过、投下一个、**不重试** | 页面含 hCaptcha，无 CAPSOLVER_API_KEY | FAILED(`captcha_unsolved`)；下一职位成功；失败职位只打开一次 | ✅ | `TestPRD5::test_unsolvable_captcha_fails_and_continues` |
| E-2 | 检测类型 + sitekey（hCaptcha/reCAPTCHA/Turnstile/FunCaptcha） | 各类挂件 | 正确识别类型与 sitekey | 🔵 | `test_captcha::test_detects_*` |
| E-3 | 求解成功 → 注入 token → 继续投递 | 有 key，CapSolver 返回 token | outcome=`solved`，token 注入隐藏字段 | 🔵 | `test_captcha::test_solved_and_injected_returns_solved` |

## 六、账号与凭据管理

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| F-1 | 无账号时自动注册（复用 LLM+DOM 填注册表单） | 门禁页无已存凭据 | 走注册流程并落库凭据 | 🔵 | `test_auth::test_no_credential_registers_and_stores_credential` |
| F-2 | 邮箱验证码/验证链接自动只读取回 | 注册需邮箱验证 | 从邮箱取码/点链接完成验证 | 🔵 | `test_auth::test_registration_uses_email_verifier` / `test_email_verify` |
| F-3 | 已有账号则复用登录，不重复注册 | 已存凭据 | 走登录路径填账密 | 🔵 | `test_auth::test_existing_credential_fills_and_submits_login_form` |
| F-4 | 密码随机生成，够强 | random 模式 | 长度≥12，含大小写/数字 | ✅ | `TestPRD6::test_password_generation_random_mode_is_strong` |
| F-5 | 密码按用户模板生成，`{rand}` 被替换 | template 模式 | 符合模板且占位符已替换 | ✅ | `TestPRD6::test_password_generation_template_mode` |
| F-6 | 凭据本地明文存储、按 (平台,门户) 分组、可复用读回 | upsert 后 get | 明文原样读回；同雇主共享 portal_id，不同雇主分开 | ✅ | `TestPRD6::test_credentials_stored_plaintext_and_reusable` / `test_credentials_grouped_per_employer_portal` |

## 七、运行模式（自动 / 手动全局开关）

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| G-1 | 默认手动投递 | 不指定 mode | `DeliverSettings().mode == "manual"` | ✅ | `TestPRD7::test_default_mode_is_manual` |
| G-2 | 手动模式：提交前经问询通道确认 | manual，用户确认 | 提交前问 `submit_confirm`；确认后 SUCCEEDED | ✅ | `TestPRD7::test_manual_mode_asks_confirmation_before_submitting` |
| G-3 | 自动模式：填完直接提交，不问确认 | auto | 无 `submit_confirm` 问询；SUCCEEDED | ✅ | `TestPRD7::test_auto_mode_submits_without_confirmation_prompt` |
| G-4 | 手动模式用户拒绝 → 不提交 | manual，用户答 n | FAILED(`user_declined_submit`) | ✅ | `TestPRD7::test_manual_decline_does_not_submit` |
| G-5 | 模式全局生效，当次所有职位统一 | manual，多职位 | 每个职位都经确认 | ✅ | `TestPRD7::test_mode_applies_to_all_jobs_in_the_run` |
| G-6 | 支持 CLI 调用（API 模式即直接调 `run_delivery`） | `deliver run/answer/retry/status` | 命令正常执行 | 🔵 | `test_cli::*` |

## 八、记录与日志

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| H-1 | 成功判定 = 进入提交确认页 | 提交后出现确认页 | SUCCEEDED | ✅ | `TestPRD8::test_success_is_defined_by_confirmation_page` |
| H-2 | 看不到确认页 → 失败 | 提交后无确认页 | FAILED(`confirmation_page_not_detected`) | ✅ | `TestPRD8::test_no_confirmation_page_is_failure` |
| H-3 | 记录每个表单填了什么 | 投递完成 | DeliveryRecord.filled_fields 保留问题原文+值+来源 | ✅ | `TestPRD8::test_record_captures_which_fields_were_filled` |
| H-4 | 过程日志记录关键步骤 | 一次 run | JSONL 日志含 run_started / job_started / state_transition | ✅ | `TestPRD8::test_process_log_records_key_steps` |
| H-5 | 失败按原因分组统计（含验证码失败） | 一次 run 同时产生 no_adapter + captcha_unsolved + confirmation_page_not_detected | failed_by_reason 三类各计 1，不混淆 | ✅ | `TestPRD8::test_failures_grouped_by_reason` |

## 九、并发（MVP：单 worker）

| ID | 预期行为 | 前置 / 步骤 | 预期结果 | 状态 | 位置 |
|---|---|---|---|---|---|
| I-1 | 按分数从高到低顺序逐个投 | 乱序输入多职位 | 打开顺序按 score 降序 | ✅ | `TestPRD9::test_processes_jobs_in_score_descending_order` |
| I-2 | 所有过阈值职位都投，不设件数上限 | 5 个职位 | 全部处理 | ✅ | `TestPRD9::test_invests_all_jobs_no_cap` |
| I-3 | 多 worker 并行投递 + 暂停协调 | 多 worker | 并行且问询合并 | ⬜ | PRD 十 future feature |

---

## 缺口清单（⚠️）与建议

1. **B-3 / F-1~F-3 的验收级（run_delivery）覆盖** —— 注册/登录/邮箱验证目前只在组件级（`test_auth`）覆盖，未走 `run_delivery` 全链路（因为 `ScriptedBrowserSession` 单 URL→单 HTML，难表达「门禁页提交后跳到表单」的多态导航）。组件级已足够可靠，验收级补齐需要更强的浏览器桩，价值中等偏低。

## 运行方式

```bash
pytest tests/test_prd_acceptance.py -v      # 只跑 PRD 验收集
pytest                                        # 全量（含单元/组件级 🔵 用例）
```
