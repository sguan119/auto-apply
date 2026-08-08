"""autoapply.core.deliver.dom —— DOM 精简 + 编号（决策四 OfferNow 式整页批量映射）。

`collect_page(page)` 用一次 `page.evaluate()` 走完整页 DOM，精简出可交互元素
并按文档流顺序编号，供 LLM 一次性对整页决策（省 token，决策四）。

**element_id ↔ selector 的存活策略**：编号不是只活在 Python 侧的字典——采集
JS 会把编号直接以 `data-deliver-id` 属性写回真实 DOM 节点，`selector_map`
里的值就是形如 `[data-deliver-id="3"]` 的 CSS 属性选择器。只要这个 DOM 节点
还挂在页面上（没被结构性替换/重建），随时可以用这个选择器重新定位到它——
不依赖 Python 侧的 `ElementHandle`（DOM 一变就可能失效，且没有天然的「重新
定位」手段）。

**何时必须重新 `collect_page`**：任何会替换/新增/删除交互元素的操作之后
（提交本页翻到下一页、点击「添加一段工作经历」等 repeater 操作、任何显著
的 DOM 重排）。这恰好与 `engine.py` 的循环节奏（每轮都重新 collect）天然
吻合，不需要额外的显式失效检测——旧编号对应的属性可能还残留在已经从
文档树摘除的节点上，但因为节点本身不在树上了，选择器查不到，安全失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import Page

from autoapply.core.llm.client import PageElement

SelectorMap = dict[int, str]

# 候选可交互元素：表单控件 + 可点击控件 + ARIA combobox/listbox（Workday 式
# 自定义下拉常见形态）+ 可编辑富文本区域；`input:not([type="hidden"])` 直接
# 在选择器层面剔除隐藏域，减少一轮 JS 侧的判断。
_CANDIDATE_SELECTOR = ",".join(
    [
        'input:not([type="hidden"])',
        "select",
        "textarea",
        "button",
        '[role="combobox"]',
        '[role="listbox"]',
        '[contenteditable="true"]',
    ]
)

# 单个 page.evaluate() 调用内完成：候选元素筛选 → 去噪（禁用/不可见/
# aria-hidden）→ 编号并写回 data-deliver-id 属性 → 提取 label/placeholder/
# name/type/options。一次往返拿到整页结构，比逐元素查询快得多。
_COLLECT_JS = """
() => {
  function labelFor(el) {
    if (el.labels && el.labels.length) {
      const text = Array.from(el.labels)
        .map((l) => l.innerText.trim())
        .filter(Boolean)
        .join(' ');
      if (text) return text;
    }
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy
        .split(/\\s+/)
        .map((id) => {
          const target = document.getElementById(id);
          return target ? target.innerText.trim() : '';
        })
        .filter(Boolean)
        .join(' ');
      if (text) return text;
    }

    const wrappingLabel = el.closest('label');
    if (wrappingLabel && wrappingLabel.innerText.trim()) {
      return wrappingLabel.innerText.trim();
    }

    const tag = el.tagName.toLowerCase();
    if (tag === 'button' && el.innerText && el.innerText.trim()) {
      return el.innerText.trim();
    }
    if (tag === 'input' && (el.type === 'submit' || el.type === 'button') && el.value) {
      return el.value.trim();
    }
    return null;
  }

  function optionsFor(el) {
    if (el.tagName.toLowerCase() === 'select') {
      return Array.from(el.options).map((o) => o.text.trim());
    }
    const listId = el.getAttribute('list');
    if (listId) {
      const datalist = document.getElementById(listId);
      if (datalist) {
        return Array.from(datalist.options).map((o) => o.value.trim());
      }
    }
    return null;
  }

  // 先清掉上一次快照留下的编号：旧编号可能还残留在已经被隐藏/挪出当前
  // 表单步骤的节点上（例如翻页后仍留在 DOM 里的上一页），如果不清空，
  // 新一轮编号从 1 开始会跟这些「隐藏的旧 1 号」在 selector 层面撞在一起
  // （`[data-deliver-id="1"]` 匹配到两个节点，`.first` 可能挑中那个已经
  // 不可见的旧节点，导致后续操作在等待「可见」上超时）。
  document
    .querySelectorAll('[data-deliver-id]')
    .forEach((el) => el.removeAttribute('data-deliver-id'));

  const nodes = Array.from(document.querySelectorAll(%s));
  const results = [];
  let nextId = 1;

  for (const el of nodes) {
    if (el.disabled) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden') continue;
    // getComputedStyle(el).display 只反映元素自身的 display 声明，不会因为
    // 祖先节点 display:none 而变成 "none"（那是「用值」，不是「计算值」）。
    // 用 offsetParent === null 判断「自身或祖先链上有 display:none」更准确；
    // position:fixed 元素 offsetParent 天然是 null 但可能真的可见，排除掉。
    if (el.offsetParent === null && style.position !== 'fixed') continue;

    const id = nextId++;
    el.setAttribute('data-deliver-id', String(id));

    results.push({
      element_id: id,
      tag: el.tagName.toLowerCase(),
      label: labelFor(el),
      placeholder: el.getAttribute('placeholder'),
      name: el.getAttribute('name') || el.getAttribute('id') || null,
      type: el.getAttribute('type'),
      options: optionsFor(el),
    });
  }
  return results;
}
""" % (repr(_CANDIDATE_SELECTOR),)


@dataclass
class PageSnapshot:
    """`collect_page()` 的返回：本次快照的编号元素列表 + 编号→选择器映射。"""

    elements: list[PageElement]
    selector_map: SelectorMap = field(default_factory=dict)

    def element_by_id(self, element_id: int) -> PageElement | None:
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None


def collect_page(page: Page) -> PageSnapshot:
    """走一次精简 DOM 提取：标注 `data-deliver-id` 属性 + 产出编号元素列表。"""
    raw_elements: list[dict] = page.evaluate(_COLLECT_JS)
    elements = [
        PageElement(
            element_id=item["element_id"],
            tag=item["tag"],
            label=item.get("label"),
            placeholder=item.get("placeholder"),
            name=item.get("name"),
            type=item.get("type"),
            options=item.get("options"),
        )
        for item in raw_elements
    ]
    selector_map: SelectorMap = {
        element.element_id: f'[data-deliver-id="{element.element_id}"]' for element in elements
    }
    return PageSnapshot(elements=elements, selector_map=selector_map)
