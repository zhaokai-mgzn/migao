# case_ids: OR-074
"""order 技能的「无焦点指代 ⇒ 先追问」规则必须**在 prompt 里**（issue #8300 / #8173）。

## 为什么需要这条判据

run `41270943560`（B 端 normal，main `dc18a5542`）OR-074 首跑 trace：

```
R1 you=这单的明细
   tools=order_query,interact
   order_query(action=list, page_size=5) → interact(choice, 请选择要查看明细的订单)
   ai=你说的"这单"指哪一单？我这边没有上下文，先列出最近的几单，麻烦你点选一下
```

即：它**确实问了**，但走的是「先查列表 + 弹选择卡」——正是 #8173 明令禁止的形态
（`direct_reply` 要求零工具调用、`forbidden_tools: order_query` 全程禁用）。

根因在 prompt：`references/prompts/order.md` 的物流链一节写着「只有指代（「我最近一笔订单」）→
先 order_query(action=list) 拿真实 order_no」——模型把「这单」也归进了这条，于是先列列表。
修法 = 在 prompt 里加一节**显式区分**（纯指代 vs 自述式指代）并禁止列列表/弹卡。

## 本文件钉什么（每条都会红）

| 判据 | 内容 |
|---|---|
| a | order.md 有「无焦点 ⇒ 先追问」这一节，且点名三类禁止（列列表 / 弹 choice / 猜单） |
| b | 这一节**在**物流链一节之前（顺序即优先级：后写的会被前面的链条盖过） |
| c | 物流链那条「先 order_query(list)」被**收窄**成自述式指代（「最近一笔」），不再对纯指代开放 |
"""
from pathlib import Path

ORDER_MD = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills"
            / "references" / "prompts" / "order.md")

SECTION_HEAD = "指代但没有焦点"


def _prompt() -> str:
    return ORDER_MD.read_text(encoding="utf-8")


def test_order_prompt_has_the_no_focus_clarification_section():
    """a：小节在，且三类禁止都点名（列列表 / 弹选择卡 / 猜）。"""
    text = _prompt()
    assert SECTION_HEAD in text, (
        "order.md 缺「指代但没有焦点 ⇒ 先追问」小节 —— OR-074 的失败形态会回来")
    start = text.index(SECTION_HEAD)
    section = text[start:start + 900]
    for marker in ("order_query", "interact", "追问"):
        assert marker in section, f"该小节没点名 {marker}（禁止项不具体 ⇒ 模型照旧）"
    assert "禁止" in section, "该小节没有「禁止」措辞（只是建议 ⇒ 不构成硬约束）"


def test_no_focus_section_precedes_the_logistics_chain():
    """b：顺序即优先级 —— 追问小节必须在「订单 → 物流链」之前。"""
    text = _prompt()
    assert SECTION_HEAD in text
    assert "物流链" in text
    assert text.index(SECTION_HEAD) < text.index("物流链"), (
        "追问小节写在物流链之后 ⇒ 模型的「先查列表」惯性会盖过它（OR-074 的成因）")


def test_logistics_chain_scopes_listing_to_self_described_reference():
    """c：物流链那条「先 order_query(list)」只对**自述式**指代（最近一笔）开放。"""
    text = _prompt()
    start = text.index("物流链")
    chain = text[start:start + 700]
    assert "最近一笔" in chain, "物流链没保留自述式指代的入口（会误伤「我最近一笔订单」）"
    assert "这单" in chain or "纯指代" in chain, (
        "物流链没把纯指代排除在外 ⇒ 模型仍会把「这单」当自述式指代去列列表")
