"""core.deliver.adapters.base —— 平台适配层最小接口 + 注册表（阶段 7）。

**为什么需要适配层**：`engine.run_form()`（阶段 5）只认「已经站在表单第一页
上的 `Page`」，不知道怎么从一个职位 URL 走到那一页——「打开职位链接 → 跟随
跳转到 ATS 落地页 → 点击 Apply 进入真正的申请表单 → 判断是否要先登录」这一段
（状态机的 OPENING）天生因平台而异（Workday 的落地页结构、Apply 按钮位置、
登录门禁跟 Greenhouse/Lever/LinkedIn Easy Apply 完全不是一回事），没有 DOM
可以通用推断——这是唯一「不能交给通用 LLM+DOM 循环」的部分，所以单独切一层
适配。**FILLING 本身仍然是通用的**：适配层只负责把 `Page` 带到表单第一页，
之后照样是调用方直接用 `engine.run_form()`，不经过适配层（阶段 7 交给阶段 8
的编排顺序见 `submit.py` 模块文档/report）。

ABC 刻意保持小：

- `matches(url)`：`select_adapter()` 用它路由——「这个职位链接归哪个适配器管」。
- `portal_id(job)`：稳定的「按雇主分组的凭据 key」提取（PRD 二：Workday 每个
  雇主门户各自独立账号，同一雇主的所有职位必须映射到同一个 `portal`，登录/
  凭据表才不会给每个职位各开一行）——这一步只有平台自己懂自己的 host/path
  规则，通用不了。
- `needs_auth(page)`：判断当前页是不是「要求登录/注册」的门禁页——同样是纯
  平台特异的页面结构判断（Workday 的门禁页 vs 表单页长得完全不同，没有通用
  规则）。
- `open_application(browser, job, settings, run_logger)`：OPENING 的完整执行——
  打开链接、跟平台特异地一路点到表单第一页或门禁页。
- `confirmation_hint(page)`：可选（默认 `None`＝不表态），submit.py 的
  `is_confirmation_page()` 优先问它，问不出结果（`None`）才退回通用文本
  启发式——大多数平台不需要覆盖它，只有想加平台专属信号的适配器才实现。

其余「怎么点 Apply」「怎么判断提交确认页」的具体启发式全部下放到
`workday.py`/`submit.py`，不进 ABC——ABC 只声明「这一步存在、返回值长什么样」，
不规定「怎么做」。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from playwright.sync_api import Page

from core.config import Settings
from core.contracts import JobRef
from core.storage.run_log import RunLogger

OpenOutcome = Literal["on_form", "needs_auth", "failed"]


@dataclass
class OpenResult:
    """`PlatformAdapter.open_application()` 的返回：OPENING 这一步走到哪了。

    - `"on_form"`：已经站在申请表单第一页（未登录也不需要，或已经是登录态）——
      调用方可以直接进 `engine.run_form()`（状态机 OPENING → FILLING）。
    - `"needs_auth"`：撞上登录/注册门禁页——调用方应转 AUTHENTICATING，用
      `Authenticator.authenticate(job, adapter.portal_id(job))`。
    - `"failed"`：打不开/打不进（如验证码卡死），`reason` 给出原因字符串，
      调用方直接 `FAILED(reason)`（状态机 OPENING → FAILED 是合法边）。
    """

    outcome: OpenOutcome
    reason: str | None = None


class PlatformAdapter(ABC):
    """平台适配最小接口（见模块文档「为什么需要适配层」）。"""

    @abstractmethod
    def matches(self, url: str) -> bool:
        """这个 URL 归本适配器管吗？`select_adapter()` 用它路由。"""
        raise NotImplementedError

    @abstractmethod
    def portal_id(self, job: JobRef) -> str:
        """从职位信息提取稳定的「按雇主门户分组」凭据 key（PRD 二）。"""
        raise NotImplementedError

    @abstractmethod
    def needs_auth(self, page: Page) -> bool:
        """当前页是不是登录/注册门禁页（还是已经在表单/已登录）？"""
        raise NotImplementedError

    @abstractmethod
    def open_application(
        self,
        browser,
        job: JobRef,
        settings: Settings,
        run_logger: RunLogger | None = None,
    ) -> OpenResult:
        """OPENING：打开 `job.url`，跟随跳转，走完平台特异的「进入申请流程」步骤。

        `browser` 只需要暴露 `.page`/`.goto()`（`BrowserSession` 接口子集，同
        `auth.Authenticator` 的约定，测试可传任意鸭子类型对象）。
        """
        raise NotImplementedError

    def confirmation_hint(self, page: Page) -> bool | None:
        """可选：本平台对「这是不是提交确认页」有没有专属信号？

        默认 `None`＝不表态，`submit.is_confirmation_page()` 退回通用文本
        启发式判断。返回 `True`/`False` 会覆盖通用判断——只在平台有明确、
        可靠的结构信号（如 `data-automation-id`）时才应该表态。
        """
        return None

    def login_succeeded(self, page: Page, *, pre_auth_url: str | None = None) -> bool:
        """可选：登录/注册提交后，验证是否真的进入了登录态。

        `Authenticator.authenticate()`（阶段 6）返回 `"authenticated"` 是**乐观**
        的——它只保证「提交了登录/注册表单」，没验证提交后是否真的登录成功。
        阶段 8 runner 在 `AUTHENTICATING → FILLING` 之前应调用本方法复核：返回
        `False` 时不要推进到 FILLING，而应落 `FAILED`（避免把一次失败的登录
        误当作已认证、继续去填一个根本没解锁的表单）。`pre_auth_url` 传入提交
        登录表单前的 URL，供实现判断「有没有发生跳转」。

        默认 `True`＝不额外验证（认为 `authenticate()` 的乐观结果可信）——只有
        能识别本平台登录失败信号（错误提示条 / 未跳转）的适配器才应覆盖它。
        放在 ABC 上（而非仅 Workday）是为了让阶段 8 能对任意 `PlatformAdapter`
        统一调用，不必 `hasattr`/类型转换。
        """
        return True


# ---------------------------------------------------------------------------
# 注册表：`register_adapter` 装饰器 + `select_adapter()` 查找
# ---------------------------------------------------------------------------

_REGISTRY: list[type[PlatformAdapter]] = []


def register_adapter(adapter_cls: type[PlatformAdapter]) -> type[PlatformAdapter]:
    """类装饰器：把一个 `PlatformAdapter` 子类登记进全局注册表。

    新增平台适配器只需要在自己的模块里 `@register_adapter` 一下，并确保
    `core.deliver.adapters.__init__` import 到这个模块（加一行 import）——
    `select_adapter()` 不需要跟着改。
    """
    _REGISTRY.append(adapter_cls)
    return adapter_cls


def select_adapter(url: str) -> PlatformAdapter | None:
    """按注册顺序找到第一个 `matches(url)` 的适配器，实例化后返回；找不到给 `None`。

    调用方（阶段 8 runner）拿到 `None` 时应当把这次投递标 `FAILED("no_adapter")`
    ——当前 MVP 只落地了 Workday，非 Workday 链接本就不在范围内。
    """
    for adapter_cls in _REGISTRY:
        adapter = adapter_cls()
        if adapter.matches(url):
            return adapter
    return None
