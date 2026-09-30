# case_ids: OR-052
"""下单页「门幅依据 / 加工方案」文案**不得带 markdown 强调**（2026-09-30 现取实证）。

病根（**线上现取**，非推断）：门幅依据由服务端 `reason` 串**原样渲染**到下单页
（`frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx` 的 `door-width-plan-reason` /
`craft-plan-reason`），而 `app/tools/curtain_calc.py` 的 f-string 文案里写了 `**…**`
⇒ 商家在页面上看到的是**裸露的星号**、不是加粗。2026-09-30 多模态复核实测原文：
「取**可行集里最小门幅**（用料 6.4 米与门幅无关 ⇒ 取小 = 不占宽幅布）」。

判据：`app/tools/curtain_calc.py` 里**任何 f-string 字面量段**都不得含 `**`。

射程与边界（照实登记）：
- 只判 **f-string**（`ast.JoinedStr` 的字面量段）—— 本模块的 f-string = **插值出来的用户可见文案**
  （`reason` / `mode_clause` / `suggestion` …）。修前现取 **19 处**命中，修后 **0**。
- **不判** `Field(description=...)` 这类**静态字符串**：它们进的是 LLM 工具说明（markdown 合法），
  修前/修后现取均为 **9 处** —— 一并判红会把「给模型看的规格」与「给人看的文案」混成一件事。
- 也不判其它模块（`app/tools/confirm_value.py` / `app/tools/order_create.py` /
  `app/tools/product_batch_update.py` 的 `message` / `suggestion` 是**给 Agent / 顾客的对话文本**，
  不在下单页渲染面内）。
"""
from __future__ import annotations

import ast
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "app" / "tools" / "curtain_calc.py"


def _fstring_literal_parts(source: str):
    """产出 `(行号, 字面量段)` —— 只取 f-string 的**固定文本**部分（插值表达式不看）。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    yield node.lineno, value.value


def test_no_markdown_emphasis_in_interpolated_copy():
    offenders = [
        (line, text)
        for line, text in _fstring_literal_parts(MODULE.read_text(encoding="utf-8"))
        if "**" in text
    ]
    assert offenders == [], "用户可见文案里不能写 markdown 强调（页面上会显示成裸星号）：" + "; ".join(
        f"L{line}: {text.strip()[:60]}" for line, text in offenders
    )


def test_guard_can_actually_go_red():
    """红证（注入式，内存构造）：把 `**` 放进 f-string ⇒ 判据必须报出它。"""
    sample = 'x = f"取**最小门幅**（{n} 米）"'
    hits = [text for _, text in _fstring_literal_parts(sample) if "**" in text]
    assert hits, "注入的坏样本没有被判据识别 ⇒ 上面那条是空断言（永远绿）"
