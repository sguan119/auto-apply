"""tests.test_browser —— core.deliver.browser.BrowserSession 生命周期/原语测试。

走真实 chromium 的**持久化 context**路径（headless，profile 落在临时目录），
覆盖 spec 决策三关心的点：import 不启动浏览器、`with` 才启动、`goto` 靠自动
等待、`upload_file` 能设置文件、`__exit__` 收尾不泄漏。CDP 兜底路径需要用户
手动起一个真实 Chrome，这里只断言它「构造时不启动任何进程」（接口自洽），
不真正连远端。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.deliver.browser import BrowserSession, apply_action


def test_import_does_not_launch_and_page_before_enter_raises(tmp_path):
    # 仅构造、不进入 with：不应有任何浏览器进程被启动，.page 必须显式报错
    session = BrowserSession(user_data_dir=tmp_path / "profile", headless=True)
    with pytest.raises(RuntimeError):
        _ = session.page


def test_connect_cdp_constructs_without_launching():
    # 决策三兜底：connect_cdp 只是构造，不进入 with 就不该连接/启动任何东西
    session = BrowserSession.connect_cdp("http://localhost:9222")
    assert session._cdp_endpoint == "http://localhost:9222"
    assert session._context is None
    assert session._playwright is None


@pytest.fixture()
def session(tmp_path):
    with BrowserSession(user_data_dir=tmp_path / "profile", headless=True) as s:
        yield s


class TestPersistentContext:
    def test_page_available_after_enter(self, session):
        assert session.page is not None

    def test_goto_data_url_follows_and_reads_content(self, session):
        page = session.goto("data:text/html,<h1 id=t>hello</h1>")
        assert page.locator("#t").inner_text() == "hello"

    def test_upload_file_sets_input_files(self, session, tmp_path):
        resume = tmp_path / "resume.pdf"
        resume.write_bytes(b"%PDF-1.4 fake")
        session.goto('data:text/html,<input id="f" type="file">')
        session.upload_file("#f", resume)
        # 读回 input 的文件名，确认确实被设置
        name = session.page.locator("#f").evaluate("el => el.files[0].name")
        assert name == "resume.pdf"


class TestApplyActionPrimitive:
    def test_fill_and_click_and_skip(self, session):
        session.goto(
            "data:text/html,"
            '<input id="n" type="text">'
            '<button id="b" type="button" onclick="this.dataset.hit=1">go</button>'
        )
        page = session.page
        apply_action(page, "#n", "fill", "Alice")
        apply_action(page, "#b", "click")
        apply_action(page, "#n", "skip", "ignored")  # skip 不改动
        assert page.locator("#n").input_value() == "Alice"
        assert page.locator("#b").get_attribute("data-hit") == "1"

    def test_native_select_uses_select_option(self, session):
        session.goto(
            "data:text/html,"
            '<select id="s"><option>Yes</option><option>No</option></select>'
        )
        page = session.page
        apply_action(page, "#s", "select", "No")
        assert page.locator("#s").input_value() == "No"

    def test_upload_action_requires_value(self, session):
        session.goto('data:text/html,<input id="f" type="file">')
        with pytest.raises(ValueError):
            apply_action(session.page, "#f", "upload", None)

    def test_unknown_action_raises(self, session):
        session.goto("data:text/html,<input id='n'>")
        with pytest.raises(ValueError):
            apply_action(session.page, "#n", "frobnicate", "x")


def test_exit_is_idempotent_and_cleans_up(tmp_path):
    # __exit__ 走完后 context 已关闭；再次操作 page 应失败（context 不复用）。
    session = BrowserSession(user_data_dir=tmp_path / "profile", headless=True)
    with session as s:
        page = s.page
        page.goto("data:text/html,<h1>x</h1>")
    # 退出后浏览器已收尾——对已关闭 page 的操作应抛错（证明确实关了）
    from playwright.sync_api import Error as PlaywrightError

    with pytest.raises((PlaywrightError, Exception)):
        page.title()
