"""autoapply.core.deliver.captcha —— CapSolver 打码：FILLING / AUTHENTICATING 内的子步骤（决策六）。

**不是独立状态**（spec 决策六「排除的替代方案」）：验证码可能出现在登录页、
注册页、表单任意一页，建模成「谁遇到谁调用」的子步骤最贴合现实。本模块只
提供三个可独立测试的原语 + 一个把它们串起来的便捷函数：

1. `detect_captcha(page)` —— 看当前页 DOM 里有没有验证码挂件，有则识别出
   类型 + sitekey；没有返回 `None`。**检测顺序 hCaptcha 先于 reCAPTCHA**
   （ApplyPilot 调研经验：两者挂件都可能同时出现在同一页，hCaptcha 优先判）。
2. `solve_captcha(challenge, settings, ...)` —— 调 CapSolver：`createTask`
   拿 `taskId` → 轮询 `getTaskResult` 直到 `ready`/超时 → 返回解出的 token。
   `CAPSOLVER_API_KEY` 未配置 → `CaptchaUnconfigured`；创建/轮询失败或超时
   → `CaptchaSolveError`。`http_client` 可注入（测试用假客户端，不打真实
   CapSolver 网络）。
3. `inject_solution(page, challenge, token)` —— 把 token 写回页面对应的
   隐藏字段（`g-recaptcha-response` / `h-captcha-response` /
   `cf-turnstile-response` / `fc-token`），并尽力触发挂件的 `data-callback`
   回调（很多站点靠回调才会真正「解锁」提交按钮）。

`handle_captcha_if_present()` 把三步串成调用方（`auth.py` / 未来的
`submit.py`）真正会用的一个函数：**优雅降级**——未配置 key 或求解失败都不
抛异常给调用方，映射成 `"failed"`；调用方据此把这次投递标 `FAILED
("captcha_unsolved")`，跳过不重试（PRD 五），不阻塞其它职位。不做任何自动
重试（同一条 PRD 五约束）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from autoapply.core.config import Settings
from autoapply.core.storage.run_log import RunLogger

CaptchaType = Literal["hcaptcha", "recaptcha_v2", "recaptcha_v3", "turnstile", "funcaptcha"]
CaptchaOutcome = Literal["none", "solved", "failed"]

_DEFAULT_BASE_URL = "https://api.capsolver.com"


class CaptchaUnconfigured(Exception):
    """`CAPSOLVER_API_KEY` 未配置时抛出（`handle_captcha_if_present` 捕获，映射为 `"failed"`）。"""


class CaptchaSolveError(Exception):
    """CapSolver `createTask`/`getTaskResult` 失败、返回错误或轮询超时时抛出。"""


@dataclass
class CaptchaChallenge:
    """`detect_captcha()` 的产出：一个页面上识别出的验证码挑战。"""

    type: CaptchaType
    sitekey: str
    url: str
    extra: dict | None = None  # 预留：个别类型（如 FunCaptcha）可能需要的额外参数


# ---------------------------------------------------------------------------
# 1. 检测：类型 + sitekey
# ---------------------------------------------------------------------------

# 只认官方标准集成标记（容器 div 的 class + data-sitekey），不追踪 iframe src——
# 追踪 iframe 意味着依赖挂件脚本真的加载渲染出 iframe，测试环境下会触发真实
# 网络请求；容器 div 标记是挂件加载前就存在的静态 DOM，检测更快也更安全。
# reCAPTCHA v3 没有可见容器，只能从内联脚本里找 `grecaptcha.execute(sitekey, ...)`
# 调用（同样不依赖加载远程脚本，只扫内联 `<script>` 文本）。
_DETECT_JS = """
() => {
  const hcaptchaEl = document.querySelector('.h-captcha[data-sitekey]');
  if (hcaptchaEl) {
    const sitekey = hcaptchaEl.getAttribute('data-sitekey');
    if (sitekey) return {type: 'hcaptcha', sitekey};
  }

  const turnstileEl = document.querySelector('.cf-turnstile[data-sitekey]');
  if (turnstileEl) {
    const sitekey = turnstileEl.getAttribute('data-sitekey');
    if (sitekey) return {type: 'turnstile', sitekey};
  }

  const recaptchaEl = document.querySelector('.g-recaptcha[data-sitekey]');
  if (recaptchaEl) {
    const sitekey = recaptchaEl.getAttribute('data-sitekey');
    if (sitekey) return {type: 'recaptcha_v2', sitekey};
  }

  const inlineScripts = Array.from(document.querySelectorAll('script:not([src])'));
  for (const script of inlineScripts) {
    const match = (script.textContent || '').match(/grecaptcha\\.execute\\(\\s*['"]([^'"]+)['"]/);
    if (match) return {type: 'recaptcha_v3', sitekey: match[1]};
  }

  const funcaptchaEl = document.querySelector('[data-pkey]');
  if (funcaptchaEl) {
    const pkey = funcaptchaEl.getAttribute('data-pkey');
    if (pkey) return {type: 'funcaptcha', sitekey: pkey};
  }

  return null;
}
"""


def detect_captcha(page: Page) -> CaptchaChallenge | None:
    """检查当前页有没有验证码挂件；有则返回类型 + sitekey，没有返回 `None`。

    检测顺序 hCaptcha → Turnstile → reCAPTCHA v2 → reCAPTCHA v3 → FunCaptcha
    （ApplyPilot 经验：hCaptcha 先于 reCAPTCHA 判）。
    """
    result = page.evaluate(_DETECT_JS)
    if result is None:
        return None
    return CaptchaChallenge(type=result["type"], sitekey=result["sitekey"], url=page.url)


# ---------------------------------------------------------------------------
# 2. 求解：CapSolver createTask → poll getTaskResult
# ---------------------------------------------------------------------------

# 我们的 CaptchaType → CapSolver task type（都用 ProxyLess 变体：PRD 五「不打
# 反检测战」，deliver 本身不管代理，交给 CapSolver 免代理任务类型处理）。
_TASK_TYPE_MAP: dict[CaptchaType, str] = {
    "hcaptcha": "HCaptchaTaskProxyLess",
    "recaptcha_v2": "ReCaptchaV2TaskProxyLess",
    "recaptcha_v3": "ReCaptchaV3TaskProxyLess",
    "turnstile": "AntiTurnstileTaskProxyLess",
    "funcaptcha": "FunCaptchaTaskProxyLess",
}


def solve_captcha(
    challenge: CaptchaChallenge,
    settings: Settings,
    *,
    http_client: httpx.Client | None = None,
    poll_interval: float | None = None,
    poll_timeout: float | None = None,
) -> str:
    """调 CapSolver 求解一个 `CaptchaChallenge`，返回解出的 token。

    `http_client` 缺省时用 `settings.capsolver.base_url` 现开一个 `httpx.Client`
    并在函数退出前关闭；测试传入一个假客户端（只需实现 `.post(url, json=...)
    -> 带 `.json()` 的响应对象`），不打真实网络。
    """
    api_key = settings.capsolver.api_key
    if not api_key:
        raise CaptchaUnconfigured("CAPSOLVER_API_KEY 未配置，验证码求解跳过")

    task_type = _TASK_TYPE_MAP.get(challenge.type)
    if task_type is None:
        raise CaptchaSolveError(f"不支持的验证码类型: {challenge.type!r}")

    interval = poll_interval if poll_interval is not None else settings.capsolver.poll_interval
    timeout = poll_timeout if poll_timeout is not None else settings.capsolver.poll_timeout

    client = http_client
    owns_client = client is None
    if owns_client:
        client = httpx.Client(base_url=settings.capsolver.base_url or _DEFAULT_BASE_URL, timeout=30.0)

    try:
        # FunCaptcha 的 sitekey 字段名是 `websitePublicKey`（CapSolver
        # FunCaptchaTaskProxyLess 的约定），其余类型统一用 `websiteKey`——
        # 用错字段名会让 CapSolver 直接 errorId 拒单，FunCaptcha 永远解不出。
        task: dict = {"type": task_type, "websiteURL": challenge.url}
        if challenge.type == "funcaptcha":
            task["websitePublicKey"] = challenge.sitekey
        else:
            task["websiteKey"] = challenge.sitekey
        create_data = _post(client, "/createTask", {"clientKey": api_key, "task": task})
        if create_data.get("errorId"):
            raise CaptchaSolveError(
                f"CapSolver createTask 失败: {create_data.get('errorDescription')}"
            )
        task_id = create_data.get("taskId")
        if not task_id:
            raise CaptchaSolveError("CapSolver createTask 未返回 taskId")

        deadline = time.monotonic() + timeout
        while True:
            time.sleep(interval)
            result_data = _post(client, "/getTaskResult", {"clientKey": api_key, "taskId": task_id})
            if result_data.get("errorId"):
                raise CaptchaSolveError(
                    f"CapSolver getTaskResult 失败: {result_data.get('errorDescription')}"
                )
            status = result_data.get("status")
            if status == "ready":
                solution = result_data.get("solution") or {}
                token = solution.get("gRecaptchaResponse") or solution.get("token")
                if not token:
                    raise CaptchaSolveError("CapSolver 返回 ready 但 solution 里没有 token")
                return token
            if status == "failed":
                raise CaptchaSolveError("CapSolver 求解失败（status=failed）")
            if time.monotonic() >= deadline:
                raise CaptchaSolveError(f"CapSolver 求解超时（{timeout}s）")
    finally:
        if owns_client:
            client.close()


def _post(client, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    return response.json()


# ---------------------------------------------------------------------------
# 3. 注入：把 token 写回页面
# ---------------------------------------------------------------------------

# 每种验证码类型约定俗成的隐藏响应字段名（供应商标准集成方式）。
_INJECT_FIELD_MAP: dict[CaptchaType, str] = {
    "hcaptcha": "h-captcha-response",
    "recaptcha_v2": "g-recaptcha-response",
    "recaptcha_v3": "g-recaptcha-response",
    "turnstile": "cf-turnstile-response",
    "funcaptcha": "fc-token",
}

# 容器选择器，用来找 `data-callback` 属性并触发挂件自身的回调（很多站点靠
# 回调才会「解锁」提交按钮，光填字段值不够）；reCAPTCHA v3 没有容器，回调
# 由业务代码自行调用 `grecaptcha.execute()` 拿结果，这里无从触发，跳过。
_CONTAINER_SELECTOR_MAP: dict[CaptchaType, str | None] = {
    "hcaptcha": ".h-captcha[data-sitekey]",
    "recaptcha_v2": ".g-recaptcha[data-sitekey]",
    "recaptcha_v3": None,
    "turnstile": ".cf-turnstile[data-sitekey]",
    "funcaptcha": "[data-pkey]",
}

_INJECT_JS = """
({fieldName, token, containerSelector}) => {
  let el = document.querySelector(`textarea[name="${fieldName}"]`) || document.getElementById(fieldName);
  if (!el) {
    el = document.createElement('textarea');
    el.name = fieldName;
    el.id = fieldName;
    el.style.display = 'none';
    document.body.appendChild(el);
  }
  el.value = token;
  el.textContent = token;

  if (containerSelector) {
    const container = document.querySelector(containerSelector);
    const callbackName = container ? container.getAttribute('data-callback') : null;
    if (callbackName && typeof window[callbackName] === 'function') {
      window[callbackName](token);
    }
  }
}
"""


def inject_solution(page: Page, challenge: CaptchaChallenge, token: str) -> None:
    """把求解出的 `token` 写回页面对应的隐藏响应字段，并尽力触发挂件回调。"""
    field_name = _INJECT_FIELD_MAP.get(challenge.type)
    if field_name is None:
        raise CaptchaSolveError(f"不支持注入的验证码类型: {challenge.type!r}")
    container_selector = _CONTAINER_SELECTOR_MAP.get(challenge.type)
    page.evaluate(
        _INJECT_JS,
        {"fieldName": field_name, "token": token, "containerSelector": container_selector},
    )


# ---------------------------------------------------------------------------
# 便捷函数：detect → solve → inject，一次调用给调用方
# ---------------------------------------------------------------------------


def handle_captcha_if_present(
    page: Page,
    settings: Settings,
    run_logger: RunLogger | None = None,
    *,
    http_client: httpx.Client | None = None,
) -> CaptchaOutcome:
    """检测→求解→注入的一站式入口，调用方（`auth.py`、未来 `submit.py`）只认这一个函数。

    - 页面上没有验证码 → `"none"`（最常见路径，多数页面不需要走后面两步）。
    - 求解并注入成功 → `"solved"`。
    - 未配置 `CAPSOLVER_API_KEY` 或求解失败/超时 → `"failed"`，**不抛异常**给
      调用方——调用方据此把这次投递标 `FAILED("captcha_unsolved")` 并跳过，
      不重试、不阻塞其它职位（PRD 五）。

    每个子步骤都记一条 run log（决策九审计），不 log token 本身（避免把求解
    出的响应串写进日志——虽非传统意义的密钥，但没有理由多留一份）。
    """
    challenge = detect_captcha(page)
    if challenge is None:
        return "none"

    if run_logger:
        run_logger.log(
            "captcha_detected", type=challenge.type, sitekey=challenge.sitekey, url=challenge.url
        )

    try:
        token = solve_captcha(challenge, settings, http_client=http_client)
    except (CaptchaUnconfigured, CaptchaSolveError) as exc:
        if run_logger:
            run_logger.log("captcha_solve_failed", type=challenge.type, error=str(exc))
        return "failed"

    try:
        inject_solution(page, challenge, token)
    except (CaptchaSolveError, PlaywrightError) as exc:
        # 求解已成功但写回页面失败（未支持的注入类型 / 页面已跳转或关闭）——
        # 同样不该把异常抛给调用方，映射成 "failed" 走跳过逻辑（PRD 五）。
        if run_logger:
            run_logger.log("captcha_inject_failed", type=challenge.type, error=str(exc))
        return "failed"
    if run_logger:
        run_logger.log("captcha_solved", type=challenge.type)
    return "solved"
