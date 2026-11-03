# case_ids: MC-186
"""商品健康度 · 刻度与可选动作（`app/briefing/product_options.py`）—— issue #8290 拆分后的**行为钉子**

判据（每条都能单独变红）：
1. `_money`：**成本未知不许当 0**（`stock_value=None` + 自述 `cost_unknown`）；库存未知 ⇒ `stock_unknown`。
2. `_money`：`price_up_5pct_per_unit = price × PRICE_UP_STEP`，**不乘销量**（周期口径未标注，乘上去就是编）。
3. `_money`：`margin_gap_per_unit` 有方向（正数 = 比同行中位**少赚**）；没有基线 ⇒ 不给差额 + 自述原因。
4. `_option_money`：算得出才给（算不出的不给字段，而不是给 0）。
5. `_next_options`：**没问题不给动作**（good / unknown ⇒ `None`）；规则表三要素齐全、内部标记不外泄、可复算。
"""

from decimal import Decimal

from app.briefing.product_options import (
    MONEY_BASIS,
    PRICE_UP_STEP,
    _money,
    _next_options,
    _option_money,
)

BASELINE = {"peer_median": 50.0, "peer_p75": 70.0, "sample_size": 9}


class TestStockValueNeverFillsZero:
    """判据 1：把未知写成 0 等于说「这批货不占钱」，与事实正好相反。"""

    def test_unknown_cost_is_not_zero_capital(self):
        money = _money({"stock": 10, "avg_cost": None, "price": 100, "gross_margin": None}, BASELINE)
        assert money["stock_value"] is None
        assert money["stock_value_basis"] == "cost_unknown"

    def test_unknown_stock_is_not_zero_capital(self):
        money = _money({"stock": None, "avg_cost": 20, "price": 100}, BASELINE)
        assert money["stock_value"] is None
        assert money["stock_value_basis"] == "stock_unknown"

    def test_known_both_sides_multiplies(self):
        money = _money({"stock": 10, "avg_cost": 20}, BASELINE)
        assert money["stock_value"] == 200.0
        assert money["stock_value_basis"] == "stock × avg_cost"


class TestPriceStep:
    """判据 2：步长固定 5%，只算「每件多赚多少」。"""

    def test_price_step_per_unit(self):
        assert PRICE_UP_STEP == Decimal("0.05")
        assert _money({"price": 100}, BASELINE)["price_up_5pct_per_unit"] == 5.0

    def test_price_step_does_not_multiply_by_sales_count(self):
        low = _money({"price": 100, "sales_count": 3}, BASELINE)["price_up_5pct_per_unit"]
        high = _money({"price": 100, "sales_count": 3000}, BASELINE)["price_up_5pct_per_unit"]
        assert low == high == 5.0, "销量口径未标注 ⇒ 乘上去就是编"

    def test_unknown_price_gives_no_step(self):
        assert _money({"price": None}, BASELINE)["price_up_5pct_per_unit"] is None


class TestMarginGapDirection:
    """判据 3：方向写反是最难发现的错，正负两种行都断言。"""

    def test_worse_than_peer_is_positive(self):
        money = _money({"gross_margin": 20.0}, BASELINE)
        assert money["margin_gap_per_unit"] == 30.0, "正数 = 每件比同行中位少赚"
        assert "正数 = 每件比同行中位少赚" in money["margin_gap_basis"]

    def test_better_than_peer_is_negative(self):
        assert _money({"gross_margin": 70.0}, BASELINE)["margin_gap_per_unit"] == -20.0

    def test_insufficient_baseline_says_so(self):
        money = _money({"gross_margin": 20.0}, None)
        assert money["margin_gap_per_unit"] is None
        assert money["margin_gap_basis"].startswith("基线样本不足")


class TestOptionMoney:
    """判据 4：算得出才给。"""

    def test_price_step_option_carries_per_unit(self):
        impact = _option_money({"price": 200}, "price_step")
        assert impact == {
            "per_unit": 10.0,
            "premise": "销量不变假设下每件多赚这么多；销量会怎么变没有弹性数据（不猜）",
        }

    def test_uncomputable_option_has_no_money_impact(self):
        assert _option_money({"price": None}, "price_step") is None
        assert _option_money({"price": 200}, "unknown_kind") is None


class TestNextOptions:
    """判据 5：没问题不给动作；给了就必须三要素齐全且不外泄内部标记。"""

    def test_good_and_unknown_rows_get_no_options(self):
        assert _next_options({"return_rate_verdict": "good", "gross_margin_verdict": "good"}) is None
        assert _next_options({"return_rate_verdict": "unknown", "gross_margin_verdict": "unknown"}) is None
        assert _next_options({}) is None

    def test_bad_return_rate_gets_three_element_options(self):
        options = _next_options({"return_rate_verdict": "bad"})
        assert len(options) == 2, "规则表 v1 = 两条低成本可逆动作"
        for option in options:
            assert option["action"] and option["verify"], "动作必须可执行、可验证"
            assert option["cost"] in {"low", "medium", "high"} and option["cost_note"]
            assert option["reversible"] is True
            assert option["metric"] == "return_rate" and option["for_verdict"] == "bad"

    def test_bad_margin_carries_computable_money_and_hides_internal_marker(self):
        options = _next_options({"gross_margin_verdict": "bad", "price": 100})
        assert len(options) == 3
        assert options[0]["action"].startswith("先核对成本价是否已维护"), "成本未知时先别调价"
        money_option = options[-1]
        assert money_option["money_impact"]["per_unit"] == 5.0
        assert "money_kind" not in money_option, "规则表的内部标记不得外泄"

    def test_watch_gets_the_short_list(self):
        assert len(_next_options({"gross_margin_verdict": "watch"})) == 1

    def test_deterministic(self):
        row = {"return_rate_verdict": "bad", "gross_margin_verdict": "bad", "price": 100}
        assert _next_options(dict(row)) == _next_options(dict(row))

    def test_basis_says_not_a_recommendation(self):
        assert "不是" in MONEY_BASIS and "弹性" in MONEY_BASIS
