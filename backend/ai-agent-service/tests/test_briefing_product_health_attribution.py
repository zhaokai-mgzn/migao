"""`product_health` 视图 · 归因（attribution）—— issue #8279

判据来源：issue #8279（P3「归因」）。本文件盯的是**「为什么这个 SKU 差」**那一层。

## 🔴 先说一个写码时撞出来的事实（issue #8279 的自我纠正评论）

本单最初的设想是「按**退货率**做同款对照」。**它不成立**：

`DailyBriefingService.assembleProductReturnStats` 按 `product_id` 聚合
（`tickets.merge(String.valueOf(productId), 1, Integer::sum)`）⇒ `return_rate` 是**商品级**，
同一商品下所有 SKU 拿到**同一个**数 ⇒ 「本行 vs 最好兄弟」的 gap **恒等于 0**。

写测试时被迫把 `assert gap == 0.50` 改成 `assert gap == 0.0` —— **恒 0 的差值就是假归因的形态**。

⇒ 变体归因**只能用 SKU 级信号（毛利）**；退货率只能落成 `product_level_only`（明说指不到变体）。

## 四条纪律

1. 🔴 **退货率不许做变体对照**：只能 `product_level_only` + 明说原因。
2. 🔴 **没有对照就不给**：独款商品 ⇒ `attribution = None`（**不是**「没问题」）。
3. **兄弟毛利未知不算进来**：脏数据算出的差值本身是噪音。
4. **不给因果断言**：只说「差异指向这个变体的定价 / 成本维护」，不说「因为这个变体质量差」；
   样本量并排给出（`sample_note`）。

case_ids：`DA-034`。

"""

# case_ids: DA-034

import json

import pytest

from app.briefing.product_health import (
    ATTRIBUTION_BASIS,
    VERDICT_GOOD,
    product_health,
)

SKU_FIELDS = ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"]
STATS_FIELDS = ["product_id", "return_tickets", "order_lines"]
RETURN_FIELDS = ["return_no", "customer_id", "product_id", "returned_at", "amount"]


def _snapshot(skus: list, stats: list = None) -> dict:
    return {
        "skus": skus,
        "product_return_stats": stats or [],
        "returns": [],
        "row_fields": {
            "skus": SKU_FIELDS,
            "product_return_stats": STATS_FIELDS,
            "returns": RETURN_FIELDS,
        },
        "row_meta": {
            "skus": {"count": len(skus), "limit": 500, "truncated": False},
            "product_return_stats": {"count": len(stats or []), "limit": 500, "truncated": False},
            "returns": {"count": 0, "limit": 500, "truncated": False},
        },
        "stock_semantics": {"operator": "<=", "threshold": 5, "unit": "件"},
    }


def _sku(sku_id: str, product_id: str, price=100, cost=60, sales_count=10, stock=10) -> dict:
    return {
        "sku_id": sku_id,
        "product_id": product_id,
        "product_name": f"商品{product_id}",
        "stock": stock,
        "sales_count": sales_count,
        "price": price,
        "avg_cost": cost,
    }


def _stat(product_id: str, tickets: int, lines: int) -> dict:
    return {"product_id": product_id, "return_tickets": tickets, "order_lines": lines}


def _row_of(view: dict, sku_id: str) -> dict:
    for row in view["rows"]:
        if row["sku_id"] == sku_id:
            return row
    raise AssertionError(f"视图里没有 {sku_id}：" + json.dumps(view["rows"], ensure_ascii=False))


def _margin_contrast_view() -> dict:
    """一个商品三个变体，其中一个毛利只有 5、另外两个 40 —— **能指到变体**的场景。"""
    skus = [
        _sku("p1-s1", "p1", price=100, cost=95),
        _sku("p1-s2", "p1", price=100, cost=60),
        _sku("p1-s3", "p1", price=100, cost=60),
    ]
    for i in range(6):
        skus.append(_sku(f"c{i}-s1", f"c{i}", price=100, cost=60))
    return product_health(_snapshot(skus), tenant_id=7)


class TestSkuLevelMarginContrast:
    def test_worst_sku_gets_sibling_margin_attribution(self):
        row = _row_of(_margin_contrast_view(), "p1-s1")
        attr = row["attribution"]
        # 不用 `is not None` 凑数：直接断言内容（弱断言会被 QA Growth Gate 扫出来）
        assert attr["kind"] == "sibling_margin_contrast", "同商品有兄弟 + 毛利低于中位 ⇒ 必须给归因"
        assert attr["level"] == "sku", "毛利是 SKU 级 ⇒ 归因落在 SKU 层"
        assert attr["sibling_count"] == 3, "同商品共 3 个变体（含自己）"

    def test_gap_is_this_row_minus_best_sibling(self):
        row = _row_of(_margin_contrast_view(), "p1-s1")
        attr = row["attribution"]
        assert attr["best_sibling_gross_margin"] == pytest.approx(40.0)
        assert attr["gap"] == pytest.approx(5.0 - 40.0), "本行 − 最好的兄弟（负数 = 少赚）"
        assert attr["gap"] < 0

    def test_sample_counts_are_always_side_by_side(self):
        row = _row_of(_margin_contrast_view(), "p1-s1")
        note = row["attribution"]["sample_note"]
        assert note and "销量" in note
        assert "不是因果" in note, "必须自己说清「这是差异证据，不是因果结论」"

    def test_healthy_sku_gets_no_attribution(self):
        row = _row_of(_margin_contrast_view(), "p1-s2")
        assert row["gross_margin_verdict"] == VERDICT_GOOD
        assert row["attribution"] is None, "没毛病不解释「为什么好」（噪音）"


class TestProductLevelOnly:
    def test_high_return_rate_yields_product_level_only(self):
        skus = [_sku(f"r{i}-s1", f"r{i}") for i in range(7)]
        stats = [_stat("r0", 5, 10)] + [_stat(f"r{i}", 0, 10) for i in range(1, 7)]
        view = product_health(_snapshot(skus, stats), tenant_id=7)

        attr = _row_of(view, "r0-s1")["attribution"]
        assert attr["kind"] == "product_level_only", "退货率只有商品级数据"
        assert attr["level"] == "product"
        assert "指不到具体变体" in attr["reason"]
        assert "gap" not in attr, "🔴 不许给退货率 gap —— 同商品所有 SKU 退货率相同，gap 恒 0"


class TestNoAttributionWhenNoContrast:
    def test_single_sku_product_gets_no_attribution(self):
        skus = [_sku(f"p{i}-s1", f"p{i}", cost=60) for i in range(7)]
        skus[0] = _sku("p0-s1", "p0", cost=95)
        view = product_health(_snapshot(skus), tenant_id=7)

        row = _row_of(view, "p0-s1")
        assert row["attribution"] is None, "没有兄弟 ⇒ 没有对照 ⇒ 不给归因"

    def test_sibling_without_margin_is_excluded(self):
        skus = [_sku("p1-s1", "p1", cost=95), _sku("p1-s2", "p1", cost=60)]
        for i in range(6):
            skus.append(_sku(f"c{i}-s1", f"c{i}", cost=60))
        skus[1]["avg_cost"] = None
        view = product_health(_snapshot(skus), tenant_id=7)

        row = _row_of(view, "p1-s1")
        assert row["attribution"] is None, "唯一兄弟的毛利未知 ⇒ 无可比对象"


class TestBasis:
    def test_view_carries_attribution_basis(self):
        view = _margin_contrast_view()
        assert view["attribution_basis"] == ATTRIBUTION_BASIS
        assert "不是因果" in ATTRIBUTION_BASIS
        assert "商品级" in ATTRIBUTION_BASIS, "必须自述退货率的粒度限制"
