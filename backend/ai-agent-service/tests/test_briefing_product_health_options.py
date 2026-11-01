"""`product_health` 视图 · 可选动作（next options）—— issue #8251

判据来源：issue #8251（P3「谋 / 权衡」）。本文件盯的是**视图语义**里的「然后呢」那一层。

## 为什么要有它

P0 让视图能说「这个 SKU 退货率判 bad」，但**然后呢？** 没有下文 ——
老板看到一个红标，还是要自己从头想「我该做什么」。
**给人一个方案叫「通知」，给三个选项带代价才叫「帮决策」。**

## 三条纪律（每条都有红证）

1. **只给问题行**：`good` / `unknown` **不给**选项 —— 没问题时推荐动作是噪音（注入式红证见 `TestGoodRowsGetNoOptions`）
2. **三要素齐全**：每个选项必须带 `action` / `cost` / `reversible`，外加 `verify`（怎么验证它有没有用）
3. **性质自述**：视图带 `options_basis`，明写这是行业常见做法、**需人工判断**

case_ids：`DA-030`（跨域视图的「下一步」层：确定性选项集，不交给 LLM 自由发挥）。
"""

# case_ids: DA-030

import json

import pytest

from app.briefing.product_health import (
    OPTIONS_BASIS,
    VERDICT_BAD,
    VERDICT_GOOD,
    VERDICT_UNKNOWN,
    VERDICT_WATCH,
    product_health,
)

SKU_FIELDS = ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"]
STATS_FIELDS = ["product_id", "return_tickets", "order_lines"]
RETURN_FIELDS = ["return_no", "customer_id", "product_id", "returned_at", "amount"]


def _meta(count: int) -> dict:
    return {"limit": 500, "count": count, "truncated": False}


def _snapshot(tickets, lines: int = 100, margins=None) -> dict:
    margins = margins if margins is not None else [60.0] * len(tickets)
    skus, stats = [], []
    for index, ticket_count in enumerate(tickets):
        product_id = f"P{index + 1}"
        skus.append({
            "sku_id": f"S{index + 1}", "product_id": product_id, "product_name": f"商品{index + 1}",
            "stock": 500.0, "sales_count": 10.0, "price": 100.0, "avg_cost": 100.0 - margins[index],
        })
        stats.append({"product_id": product_id, "return_tickets": ticket_count, "order_lines": lines})
    return {
        "biz_date": "2026-10-31",
        "row_fields": {
            "orders": [], "skus": list(SKU_FIELDS),
            "returns": list(RETURN_FIELDS), "product_return_stats": list(STATS_FIELDS),
        },
        "row_meta": {"skus": _meta(len(skus)), "returns": _meta(0), "product_return_stats": _meta(len(stats))},
        "skus": skus, "returns": [], "product_return_stats": stats,
    }


#: 8 个 SKU：退货率 0/5/10/10/15/20/30/40 ⇒ 中位 12.5%、p75 20%
TICKETS = [0, 5, 10, 10, 15, 20, 30, 40]


def _rows(view: dict) -> dict:
    return {str(row["product_id"]): row for row in view["rows"]}


class TestBadRowsGetOptions:
    def test_bad_return_rate_has_options_with_all_three_elements(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        row = _rows(view)["P7"]          # 30% > p75 ⇒ bad

        assert row["return_rate_verdict"] == VERDICT_BAD
        options = row["next_options"]
        assert options, "bad 行必须有可选动作"
        for option in options:
            assert option["action"] and isinstance(option["action"], str)
            assert option["cost"] in ("low", "medium", "high")
            assert isinstance(option["reversible"], bool)
            assert option["verify"], "每个选项都要说清「怎么验证它有没有用」"

    def test_options_are_tagged_with_the_metric_they_belong_to(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        row = _rows(view)["P7"]

        metrics = {option["metric"] for option in row["next_options"]}
        assert metrics <= {"return_rate", "gross_margin"}
        assert "return_rate" in metrics

    def test_watch_rows_also_get_options(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        row = _rows(view)["P5"]          # 15% ⇒ watch

        assert row["return_rate_verdict"] == VERDICT_WATCH
        assert row["next_options"]

    def test_negative_margin_gets_a_cost_check_option_first(self):
        """毛利为负时，第一条建议必须是「先核对成本价是否已维护」—— 成本未知时毛利根本不可算。"""
        view = product_health(_snapshot([5] * 5, margins=[-10.0, -20.0, -30.0, -40.0, -50.0]), tenant_id=1)
        row = _rows(view)["P1"]

        assert row["gross_margin_verdict"] == VERDICT_BAD
        assert "成本" in row["next_options"][0]["action"]


class TestGoodRowsGetNoOptions:
    """纪律 1：没问题时推荐动作 = 噪音（注入式红证：给 good 行配上选项 ⇒ 本类断言必红）。"""

    def test_good_rows_have_no_options(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        row = _rows(view)["P1"]          # 0% ⇒ good

        assert row["return_rate_verdict"] == VERDICT_GOOD
        assert row.get("next_options") in (None, [])

    def test_unknown_rows_have_no_options(self):
        snap = _snapshot(TICKETS)
        snap["product_return_stats"].append({"product_id": "P9", "return_tickets": 0, "order_lines": 0})
        snap["skus"].append({
            "sku_id": "S9", "product_id": "P9", "product_name": "无订单商品",
            "stock": 1.0, "sales_count": 0.0, "price": 100.0, "avg_cost": 40.0,
        })
        view = product_health(snap, tenant_id=1)
        row = _rows(view)["P9"]

        assert row["return_rate_verdict"] == VERDICT_UNKNOWN
        assert row.get("next_options") in (None, [])


class TestDeterminismAndDisclosure:
    def test_options_are_deterministic(self):
        snap = _snapshot(TICKETS)
        first = json.dumps(product_health(snap, tenant_id=1)["rows"], sort_keys=True, ensure_ascii=False)
        second = json.dumps(product_health(snap, tenant_id=1)["rows"], sort_keys=True, ensure_ascii=False)

        assert first == second

    def test_options_basis_says_it_needs_human_judgement(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)

        assert view["options_basis"] == OPTIONS_BASIS
        assert "人工判断" in OPTIONS_BASIS
        assert "行业" in OPTIONS_BASIS

    def test_options_basis_is_declared_in_view_basis(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)

        assert "next_options" in view["basis"]
