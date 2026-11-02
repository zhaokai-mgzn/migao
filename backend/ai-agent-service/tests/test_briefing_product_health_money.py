"""`product_health` 视图 · 权衡的刻度（money）—— issue #8276

判据来源：issue #8276（P6「权衡」补刻度）。本文件盯的是**第 6 层从「等级」补到「金额」**。

## 为什么要有它

P3（#8251）给了「可逆性 + 成本等级」，但**没有一个数字**。老板看到
「小范围试调价（如 +5%）」时真正想知道的是：这批货**压了多少钱**、+5% **每件多赚多少**、
我的毛利离同行**还差多少**。只有「高/中/低」的选项表，答不出任何一条 —— 权衡没有刻度。

## 四条纪律（前两条有红证）

1. **成本未知 ⇒ 不算钱**，`stock_value = None` + `stock_value_basis = "cost_unknown"`。
   **不得当 0** —— 「压货资金 = 0」会把「算不出来」说成「不占钱」，正好反了。
   红证：把 `None` 换成 `Decimal(0)` ⇒ `test_unknown_cost_is_not_zero_capital` 必红。
2. **只算给定情景的算术，不做预测**：`+5%` 只出「每件多赚多少」，**不乘销量**说「月增 X」——
   `sales_count` 的周期口径在快照契约里没有标注，乘上去就是编。
   红证：把 `price_up_5pct_per_unit` 改成乘 `sales_count` ⇒ 同一条断言必红。
3. **钱是事实、选项是建议**：`good` 行**不给选项**（P3 纪律不变），但**照样给钱** ——
   「这批货压了 5000 元」对好卖的 SKU 同样是事实，不该因为没毛病就不说。
4. **差额有方向**：`margin_gap_per_unit = peer_median − 本行毛利`，**正数 = 比同行少赚**。
   方向写反是最容易犯又最难发现的错，所以判据里正负两种行都断言。

case_ids：`DA-033`。

"""

# case_ids: DA-033

import json

import pytest

from app.briefing.product_health import (
    MONEY_BASIS,
    PRICE_UP_STEP,
    VERDICT_BAD,
    VERDICT_GOOD,
    product_health,
)

SKU_FIELDS = ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"]
STATS_FIELDS = ["product_id", "return_tickets", "order_lines"]
RETURN_FIELDS = ["return_no", "customer_id", "product_id", "returned_at", "amount"]


def _meta(count: int) -> dict:
    return {
        "skus": {"count": count, "limit": 500, "truncated": False},
        "product_return_stats": {"count": count, "limit": 500, "truncated": False},
        "returns": {"count": 0, "limit": 500, "truncated": False},
    }


def _snapshot(rows: list, stats: list = None) -> dict:
    return {
        "skus": rows,
        "product_return_stats": stats or [],
        "returns": [],
        "row_fields": {
            "skus": SKU_FIELDS,
            "product_return_stats": STATS_FIELDS,
            "returns": RETURN_FIELDS,
        },
        "row_meta": _meta(len(rows)),
        "stock_semantics": {"operator": "<=", "threshold": 5, "unit": "件"},
    }


def _sku(sku_id: str, stock, price, avg_cost, sales_count=10) -> dict:
    return {
        "sku_id": sku_id,
        "product_id": sku_id.split("-")[0],
        "product_name": f"商品{sku_id}",
        "stock": stock,
        "sales_count": sales_count,
        "price": price,
        "avg_cost": avg_cost,
    }


def _view(rows: list, stats: list = None) -> dict:
    return product_health(_snapshot(rows, stats), tenant_id=7)


def _row_of(view: dict, sku_id: str) -> dict:
    for row in view["rows"]:
        if row["sku_id"] == sku_id:
            return row
    raise AssertionError(f"视图里没有 {sku_id}：" + json.dumps(view["rows"], ensure_ascii=False))


class TestStockValue:
    """压货占用资金 —— 决策的机会成本。"""

    def test_stock_value_is_stock_times_cost(self):
        row = _row_of(_view([_sku("p1-s1", 10, 100, 60)]), "p1-s1")

        money = row["money"]
        assert money["stock_value"] == pytest.approx(600.0), "10 件 × 成本 60 = 600"
        assert money["stock_value_basis"] == "stock × avg_cost"

    def test_unknown_cost_is_not_zero_capital(self):
        """🔴 成本未知 ⇒ `None`，**不是 0**（红证：换 0 必红）。"""
        row = _row_of(_view([_sku("p1-s1", 10, 100, None)]), "p1-s1")

        money = row["money"]
        assert money["stock_value"] is None, "成本未知时压货资金**不可算**"
        assert money["stock_value_basis"] == "cost_unknown", "必须自述为什么算不出来"

    def test_unknown_stock_is_not_zero_capital(self):
        row = _row_of(_view([_sku("p1-s1", None, 100, 60)]), "p1-s1")

        money = row["money"]
        assert money["stock_value"] is None
        assert money["stock_value_basis"] == "stock_unknown"


class TestPriceStep:
    """试调价 +5% 的刻度 —— **每件**，不乘销量。"""

    def test_price_up_step_per_unit(self):
        row = _row_of(_view([_sku("p1-s1", 10, 100, 60, sales_count=50)]), "p1-s1")

        money = row["money"]
        assert money["price_up_5pct_per_unit"] == pytest.approx(float(100 * PRICE_UP_STEP))
        assert money["price_up_5pct_per_unit"] == pytest.approx(5.0)

    def test_price_step_does_not_multiply_by_sales_count(self):
        """🔴 销量口径未标注 ⇒ 乘上去就是编（红证：乘销量必红）。"""
        cheap = _row_of(_view([_sku("p1-s1", 10, 100, 60, sales_count=1)]), "p1-s1")
        busy = _row_of(_view([_sku("p1-s1", 10, 100, 60, sales_count=999)]), "p1-s1")

        assert cheap["money"]["price_up_5pct_per_unit"] == pytest.approx(
            busy["money"]["price_up_5pct_per_unit"]
        ), "同一价格、不同销量 ⇒ 每件增量必须相同（不许偷偷乘销量）"

    def test_unknown_price_gives_no_step(self):
        row = _row_of(_view([_sku("p1-s1", 10, None, 60)]), "p1-s1")

        assert row["money"]["price_up_5pct_per_unit"] is None


class TestMarginGap:
    """离同行中位还差多少 —— **正数 = 比同行少赚**（方向写反是最难发现的错）。"""

    def test_worse_than_peer_is_positive(self):
        # 5 个「卖得好」的 SKU 把毛利基线抬到 40，再放一个毛利只有 5 的
        good = [_sku(f"g{i}-s1", 1, 100, 60) for i in range(5)]
        bad = _sku("p1-s1", 1, 100, 95)  # 毛利 5
        view = _view(good + [bad])

        money = _row_of(view, "p1-s1")["money"]
        assert money["margin_gap_per_unit"] > 0, "比同行差 ⇒ 正数"
        assert "peer_median" in money["margin_gap_basis"]

    def test_better_than_peer_is_negative(self):
        weak = [_sku(f"w{i}-s1", 1, 100, 95) for i in range(5)]  # 毛利 5
        strong = _sku("p1-s1", 1, 100, 40)  # 毛利 60
        view = _view(weak + [strong])

        money = _row_of(view, "p1-s1")["money"]
        assert money["margin_gap_per_unit"] < 0, "比同行好 ⇒ 负数"

    def test_insufficient_baseline_says_so(self):
        view = _view([_sku("p1-s1", 1, 100, 60)])

        money = _row_of(view, "p1-s1")["money"]
        assert money["margin_gap_per_unit"] is None
        assert "样本" in money["margin_gap_basis"] or "未知" in money["margin_gap_basis"]


class TestOptionsMoneyImpact:
    """选项带钱：能算的给数 + 前提，算不出的不给（不是给 0）。"""

    def test_price_option_carries_money_impact(self):
        # 毛利为负 ⇒ bad ⇒ 出「试调价 +5%」这个选项
        view = _view([_sku("p1-s1", 10, 100, 120)])
        row = _row_of(view, "p1-s1")
        assert row["gross_margin_verdict"] == VERDICT_BAD

        price_option = [
            o for o in row["next_options"] if "试调价" in o["action"]
        ]
        assert price_option, "毛利 bad 必须给「试调价」选项"
        impact = price_option[0]["money_impact"]
        assert impact["per_unit"] == pytest.approx(5.0), "100 元 +5% = 每件 5 元"
        assert "销量不变" in impact["premise"], "前提必须写出来（不写就是把假设当事实）"

    def test_uncomputable_option_has_no_money_impact(self):
        view = _view([_sku("p1-s1", 10, 100, 120)])
        row = _row_of(view, "p1-s1")

        others = [o for o in row["next_options"] if "试调价" not in o["action"]]
        assert others, "还应有别的选项"
        for option in others:
            assert "money_impact" not in option, (
                f"「{option['action']}」算不出钱 ⇒ 不给字段，而不是给 0"
            )


class TestMoneyIsFactNotAdvice:
    """钱是事实：good 行不给选项，但照样给钱。"""

    def test_good_row_still_has_money(self):
        good = [_sku(f"g{i}-s1", 20, 100, 60) for i in range(6)]
        view = _view(good)
        row = _row_of(view, "g0-s1")

        assert row["gross_margin_verdict"] == VERDICT_GOOD
        assert row["next_options"] is None, "P3 纪律不变：没问题不给选项"
        assert row["money"]["stock_value"] == pytest.approx(1200.0), "但钱照样要说（20 × 60）"


class TestBasis:
    def test_view_carries_money_basis(self):
        view = _view([_sku("p1-s1", 10, 100, 60)])

        assert view["money_basis"] == MONEY_BASIS
        assert "不是预测" in view["money_basis"]
        assert "未知" in view["money_basis"]

    def test_basis_mentions_no_elasticity(self):
        assert "弹性" in MONEY_BASIS, "必须自述「销量会怎么变我们不知道」"


class TestToolMessageCarriesTheMoney:
    """`message` 是模型的唯一摘要 —— 钱不进 message，模型只会念「N 个 SKU」。"""

    def _context(self):
        from app.tools.base import ToolContext

        return ToolContext(
            tenant_id=1, user_id="u-1", session_id="s-1", role="admin",
            permissions=["dashboard:view"],
        )

    def _message(self, snapshot):
        from app.tools.briefing_query import render_view_result

        return render_view_result("product_health", snapshot, self._context()).message

    def test_message_reports_total_stock_value(self):
        message = self._message(_snapshot([_sku("p1-s1", 10, 100, 60)]))

        assert "库存成本合计" in message
        assert "600" in message, f"10 × 60 = 600 必须出现在摘要里：{message}"

    def test_message_says_unknown_cost_is_uncomputable(self):
        """🔴 成本未知的部分必须说「算不出来」，不许沉默（沉默 = 读成 0）。"""
        message = self._message(
            _snapshot([_sku("p1-s1", 10, 100, 60), _sku("p2-s1", 5, 100, None)])
        )

        assert "算不出来" in message
        assert "不是 0" in message
