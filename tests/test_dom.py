"""tests.test_dom —— core.deliver.dom.collect_page 测试。

真实 chromium（headless）驱动，不 mock Playwright——DOM 精简/编号/去噪逻辑
本身就是拿真实浏览器的 `getComputedStyle`/`offsetParent` 语义在判断，mock
掉浏览器测不出真实行为。用 `page.set_content()` 灌入静态 HTML fixture，不
需要起 HTTP server。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from core.deliver.dom import collect_page


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


class TestBasicExtraction:
    def test_extracts_expected_elements_with_labels_and_placeholder(self, page):
        page.set_content(
            """
            <form>
              <label for="fname">Full Name</label>
              <input id="fname" name="full_name" type="text" placeholder="Jane Doe">
              <label>Email<input name="email" type="email"></label>
              <select name="visa"><option>Yes</option><option>No</option></select>
              <button type="submit">Continue</button>
            </form>
            """
        )
        snapshot = collect_page(page)
        tags = [e.tag for e in snapshot.elements]
        assert tags == ["input", "input", "select", "button"]

        name_field = snapshot.elements[0]
        assert name_field.label == "Full Name"
        assert name_field.placeholder == "Jane Doe"
        assert name_field.name == "full_name"
        assert name_field.type == "text"

        email_field = snapshot.elements[1]
        assert email_field.label == "Email"

        visa_field = snapshot.elements[2]
        assert visa_field.options == ["Yes", "No"]

        continue_button = snapshot.elements[3]
        assert continue_button.label == "Continue"

    def test_element_ids_start_at_1_and_are_sequential(self, page):
        page.set_content('<input name="a"><input name="b"><input name="c">')
        snapshot = collect_page(page)
        assert [e.element_id for e in snapshot.elements] == [1, 2, 3]

    def test_selector_map_relocates_the_stamped_element(self, page):
        page.set_content('<input name="full_name" type="text">')
        snapshot = collect_page(page)
        selector = snapshot.selector_map[1]
        assert page.locator(selector).get_attribute("name") == "full_name"

    def test_element_by_id_lookup(self, page):
        page.set_content('<input name="a"><input name="b">')
        snapshot = collect_page(page)
        assert snapshot.element_by_id(2).name == "b"
        assert snapshot.element_by_id(99) is None


class TestNoisePruning:
    def test_hidden_input_and_disabled_and_display_none_are_pruned(self, page):
        page.set_content(
            """
            <input name="visible" type="text">
            <input name="csrf" type="hidden" value="abc">
            <input name="disabled_field" type="text" disabled>
            <input name="invisible" type="checkbox" style="display:none">
            <input name="collapsed" type="text" style="visibility:hidden">
            """
        )
        snapshot = collect_page(page)
        names = {e.name for e in snapshot.elements}
        assert names == {"visible"}

    def test_ancestor_display_none_prunes_descendants(self, page):
        # display:none 加在祖先节点上：子元素自身的 computed style 不会报
        # display:none（那是 used value 不是 computed value），必须靠
        # offsetParent 判断才能正确剪掉。
        page.set_content(
            """
            <div id="page1"><input name="visible_field" type="text"></div>
            <div id="page2" style="display:none"><input name="hidden_field" type="text"></div>
            """
        )
        snapshot = collect_page(page)
        names = {e.name for e in snapshot.elements}
        assert names == {"visible_field"}

    def test_toggling_visibility_changes_next_snapshot(self, page):
        page.set_content(
            """
            <div id="page1"><input name="step1" type="text"></div>
            <div id="page2" style="display:none"><input name="step2" type="text"></div>
            """
        )
        first = collect_page(page)
        assert {e.name for e in first.elements} == {"step1"}

        page.evaluate(
            "document.getElementById('page1').style.display='none';"
            "document.getElementById('page2').style.display='block';"
        )
        second = collect_page(page)
        assert {e.name for e in second.elements} == {"step2"}

    def test_restamp_does_not_leave_colliding_ids_on_stale_hidden_nodes(self, page):
        """回归：翻页后旧编号必须从残留的隐藏节点上清掉。

        page1 的输入框首轮拿到 id=1；翻到 page2（page1 变 display:none 但仍留在
        DOM 里）后重新采集，page2 的输入框又从 1 开始编号。如果不先清掉旧
        `data-deliver-id`，`[data-deliver-id="1"]` 会同时匹配到「隐藏的旧 1 号」
        和「可见的新 1 号」两个节点——后续 `.first` 可能挑中隐藏的那个，卡在
        「等待可见」上超时。断言：重采后 id=1 只匹配一个节点，且是可见的 step2。
        """
        page.set_content(
            """
            <div id="page1"><input name="step1" type="text"></div>
            <div id="page2" style="display:none"><input name="step2" type="text"></div>
            """
        )
        collect_page(page)  # 首轮：step1 拿到 id=1
        page.evaluate(
            "document.getElementById('page1').style.display='none';"
            "document.getElementById('page2').style.display='block';"
        )
        second = collect_page(page)  # 重采：step2 应拿到干净的 id=1

        matches = page.locator('[data-deliver-id="1"]')
        assert matches.count() == 1  # 没有和隐藏的旧节点撞号
        assert matches.get_attribute("name") == "step2"
        # 旧 step1 节点上的编号已被清除
        assert page.locator('[name="step1"]').get_attribute("data-deliver-id") is None
        assert second.selector_map[1] == '[data-deliver-id="1"]'

    def test_aria_hidden_ancestor_is_pruned(self, page):
        page.set_content(
            """
            <input name="visible" type="text">
            <div aria-hidden="true"><input name="decoy" type="text"></div>
            """
        )
        snapshot = collect_page(page)
        assert {e.name for e in snapshot.elements} == {"visible"}
