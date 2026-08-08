"""autoapply.core.deliver.browser —— Playwright 持久化 context 封装（spec 决策三）。

两条构造路径：

1. **`BrowserSession(...)`（默认路径）**：`launch_persistent_context` 启动一个
   持久化 profile（cookie/登录态落盘复用，跨 run 不用重新登录）。`headless`
   与 `user_data_dir` 走 `Settings.browser`（见 `core.config.BrowserSettings`），
   不硬编码。
2. **`BrowserSession.connect_cdp(endpoint)`（决策三兜底）**：不启动新浏览器，
   而是通过 CDP 挂接到一个已经在跑、已经登录好的真实 Chrome（`chrome
   --remote-debugging-port=...` 起的实例），复用它的登录态/会话。测试不需要
   跑这条路径（要求用户手动起一个真实 Chrome），但接口必须存在、行为自洽。

两条路径产出的对象都是 context manager，`__enter__` 才真正启动 Playwright/
连接浏览器——**import 本模块不会启动任何浏览器进程**（只在 `with` 块内发生
IO），符合「可被安全 import 用于测试/类型检查」的要求。

`apply_action()` 是模块级函数而非方法：它只需要一个 `Page` + 选择器 +
(action, value)，不依赖 `BrowserSession` 自身状态，engine.py 用它把
`ElementDecision` 落到 DOM 上，刻意不在这里引入 `core.llm.client` 的类型
——browser 层只认最原始的 (action 字符串, value 字符串)，与 LLM 决策 schema
解耦，谁来拼装 (action, value) 是调用方（engine）的职责。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Playwright, sync_playwright

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_USER_DATA_DIR = _REPO_ROOT / "data" / "browser_profile"

# 原生 <select> 走 select_option；其它「select」动作目标（Workday 式可搜索
# 下拉、自定义 combobox）没有固定的 option value/id，走「键入文本 + Enter」
# 让组件自身的过滤/确认逻辑接管（Workday-Application-Automator 调研经验）。
_NATIVE_SELECT_TAG = "select"


class BrowserSession:
    """Playwright 浏览器会话的 context manager 封装。

    `__enter__` 前 `.page` 不可用（`self._context is None`）；`__exit__` 负责
    按启动路径对称地收尾（持久化 context 只需 close context，CDP 路径额外
    close 到远端浏览器的连接但不会关掉用户真实的 Chrome 进程本身）。
    """

    def __init__(
        self,
        user_data_dir: str | Path | None = None,
        headless: bool = True,
        **launch_kwargs: Any,
    ) -> None:
        self._user_data_dir = (
            Path(user_data_dir) if user_data_dir is not None else DEFAULT_USER_DATA_DIR
        )
        self._headless = headless
        self._launch_kwargs = launch_kwargs
        self._cdp_endpoint: str | None = None
        self._playwright: Playwright | None = None
        self._context = None  # type: ignore[assignment]  # BrowserContext，惰性创建
        self._browser = None  # type: ignore[assignment]  # 仅 CDP 路径用到

    @classmethod
    def connect_cdp(cls, endpoint: str, **launch_kwargs: Any) -> "BrowserSession":
        """挂接一个已登录的真实 Chrome（决策三兜底），不启动新浏览器进程。

        `endpoint` 形如 `http://localhost:9222`（Chrome 以
        `--remote-debugging-port=9222` 启动后暴露的 CDP 地址）。挂上后复用
        该浏览器现有的第一个 context（及其 cookie/登录态），没有则新建一个。
        """
        session = cls.__new__(cls)
        session._user_data_dir = None
        session._headless = False  # 真实浏览器早已起好，这个字段在 CDP 路径下无意义
        session._launch_kwargs = launch_kwargs
        session._cdp_endpoint = endpoint
        session._playwright = None
        session._context = None
        session._browser = None
        return session

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        if self._cdp_endpoint is not None:
            self._browser = self._playwright.chromium.connect_over_cdp(
                self._cdp_endpoint, **self._launch_kwargs
            )
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
        else:
            assert self._user_data_dir is not None
            self._user_data_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self._user_data_dir),
                headless=self._headless,
                **self._launch_kwargs,
            )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # 逐级收尾，且**每一级失败都不能阻断后面级别**——否则前一级 close()
        # 抛错会漏关底层 chromium 进程/playwright driver（泄漏进程）。用嵌套
        # try/finally 保证三步都尝试执行；playwright.stop() 放在最内层，最关键
        # （它负责结束 driver 子进程）。
        try:
            if self._context is not None:
                self._context.close()
        finally:
            try:
                if self._browser is not None:
                    self._browser.close()
            finally:
                if self._playwright is not None:
                    self._playwright.stop()

    @property
    def page(self) -> Page:
        """当前活动页；context 刚起来时用它已打开的第一个标签页，没有则新建。"""
        if self._context is None:
            raise RuntimeError("BrowserSession 尚未进入（先用 with 语句 __enter__）")
        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def goto(self, url: str, *, wait_until: str = "load") -> Page:
        """打开 URL 并跟随跳转（Playwright `goto` 本身会跟完重定向链）。

        依赖 Playwright 自动等待（决策三），不手写 sleep；`wait_until` 默认
        `"load"`，Workday 这类 SPA 分页表单如需等到网络空闲，调用方可传
        `wait_until="networkidle"`。
        """
        page = self.page
        page.goto(url, wait_until=wait_until)
        return page

    def upload_file(self, selector: str, path: str | Path) -> None:
        """给 selector 定位的文件输入框设置本地文件（简历/求职信 PDF 等）。"""
        self.page.locator(selector).set_input_files(str(path))


def apply_action(page: Page, selector: str, action: str, value: str | None = None) -> None:
    """把一个 `(action, value)` 应用到 `selector` 定位的元素上。

    `action` ∈ `fill`/`select`/`click`/`upload`/`skip`（与
    `core.llm.client.ElementDecision.action` 同名同义，但本函数本身不依赖
    那个类型——engine.py 负责把 `ElementDecision` 拆成这两个原始参数）。

    - `fill`：文本输入框，`locator.fill(value)`（Playwright 自动等待可编辑）。
    - `select`：先探测目标是不是原生 `<select>`——是则 `select_option`；
      不是则视为 Workday 式可搜索下拉/自定义 combobox，走「点开 → 逐字键入
      → Enter 确认」，不依赖固定 option value/id（Workday 调研经验）。
    - `click`：按钮/复选框/单选框/repeater 的「添加一段」按钮等。
    - `upload`：`value` 复用为文件路径字符串（不单独扩展一个字段——与
      `fill` 的「value 是这个动作的字符串负载」语义保持一致）。
    - `skip`：不动。
    """
    if action == "skip":
        return

    locator = page.locator(selector).first

    if action == "click":
        locator.click()
        return

    if action == "upload":
        if not value:
            raise ValueError(f"upload 动作缺少 value（文件路径）：selector={selector!r}")
        locator.set_input_files(value)
        return

    if action == "fill":
        locator.fill(value or "")
        return

    if action == "select":
        tag = (locator.evaluate("el => el.tagName") or "").lower()
        if tag == _NATIVE_SELECT_TAG:
            locator.select_option(label=value)
        else:
            locator.click()
            locator.press_sequentially(value or "")
            locator.press("Enter")
        return

    raise ValueError(f"未知 action: {action!r}（selector={selector!r}）")
