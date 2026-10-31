"""`product_health` 视图 · 同行基线（peer baseline）与判断（verdict）—— issue #8234

判据来源：issue #8234（P0-a「参照系」）。本文件盯的是**视图语义**（`app/briefing/product_health.py`
新增的基线段），不是数据装配。

## 为什么要有它

视图原来只给 `return_rate: 0.18`，老板看到还要自己判断「这算高还是低」。
**没有参照系的数字不能用来做决定**（盘点见 `product/agent-decision-capability-gap.md` §四）。

基线 = **同一份快照里已有的全店 SKU 行**算出的分布（中位数 / 上四分位）——
零新增数据依赖、纯函数、确定性。

## 三条纪律（每条都有红证）

1. **未知不装懂**：指标未知 / 有效样本 < `MIN_BASELINE_SAMPLE` ⇒ `unknown`，
   **不得**回填 `good`（红证：注入式把样本降到阈值以下 ⇒ 同一断言变红）。
2. **毛利为负是绝对判据**：`gross_margin < 0` ⇒ `bad`，**不受基线影响**
   （红证：构造一个「全店都亏」的快照，基线中位数也是负 ⇒ 若实现退化成纯相对判断，该行会被判 `good`）。
3. **基线性质必须自述**：输出带 `baseline_basis` —— 明写这是**相对基线，不是绝对标准**。

case_ids 说明：`DA-028`（本单新增：跨域视图的**判断层** —— 数值之外给出同行基线与 `good/watch/bad/unknown`）。
"""

# case_ids: DA-028, DA-034

from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from app.briefing import product_health as view_module
from app.briefing.product_health import (
    BASELINE_BASIS,
    MIN_BASELINE_SAMPLE,
    VERDICT_BAD,
    VERDICT_GOOD,
    VERDICT_UNKNOWN,
    VERDICT_WATCH,
    product_health,
)

SKU_FIELDS = ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"]
STATS_FIELDS = ["product_id", "return_tickets", "order_lines"]
RETURN_FIELDS = ["return_no", "customer_id", "product_id", "returned_at", "amount"]


def _meta(count: int) -> Dict[str, Any]:
    return {"limit": 500, "count": count, "truncated": False}


def _snapshot(
    tickets: List[int],
    lines: int = 100,
    margins: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """构造 N 个 SKU 的快照：退货率 = tickets_i / lines，毛利 = price - avg_cost。"""
    margins = margins if margins is not None else [60.0] * len(tickets)
    skus: List[Dict[str, Any]] = []
    stats: List[Dict[str, Any]] = []
    for index, ticket_count in enumerate(tickets):
        product_id = f"P{index + 1}"
        cost = 100.0 - margins[index]
        skus.append(
            {
                "sku_id": f"S{index + 1}",
                "product_id": product_id,
                "product_name": f"商品{index + 1}",
                "stock": 500.0,
                "sales_count": 10.0,
                "price": 100.0,
                "avg_cost": cost,
            }
        )
        stats.append({"product_id": product_id, "return_tickets": ticket_count, "order_lines": lines})
    return {
        "biz_date": "2026-10-31",
        "row_fields": {
            "orders": [],
            "skus": list(SKU_FIELDS),
            "returns": list(RETURN_FIELDS),
            "product_return_stats": list(STATS_FIELDS),
        },
        "row_meta": {
            "skus": _meta(len(skus)),
            "returns": _meta(0),
            "product_return_stats": _meta(len(stats)),
        },
        "skus": skus,
        "returns": [],
        "product_return_stats": stats,
    }


def _rows_by_product(view: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(row["product_id"]): row for row in view["rows"]}


#: 8 个 SKU 的退货率：0 / 5% / 10% / 10% / 15% / 20% / 30% / 40%
#: 排序后中位数 = (10% + 15%) / 2 = 12.5%；p75（最近秩）= 20%
TICKETS = [0, 5, 10, 10, 15, 20, 30, 40]


class TestBaselineComputation:
    """基线本身怎么算。"""

    def test_median_and_p75_are_computed_from_known_rates(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        baseline = view["baselines"]["return_rate"]

        assert baseline["sample_size"] == 8
        assert baseline["peer_median"] == pytest.approx(0.125)
        assert baseline["peer_p75"] == pytest.approx(0.2)

    def test_rows_without_a_rate_do_not_enter_the_baseline(self):
        """算不出退货率的行（无分母）**不进样本** —— 否则基线被未知值污染。"""
        snap = _snapshot(TICKETS)
        snap["product_return_stats"].append(
            {"product_id": "P9", "return_tickets": 0, "order_lines": 0}
        )
        snap["skus"].append(
            {
                "sku_id": "S9", "product_id": "P9", "product_name": "无订单商品",
                "stock": 1.0, "sales_count": 0.0, "price": 100.0, "avg_cost": 40.0,
            }
        )
        view = product_health(snap, tenant_id=1)

        assert _rows_by_product(view)["P9"]["return_rate"] is None
        assert view["baselines"]["return_rate"]["sample_size"] == 8

    def test_baseline_is_deterministic(self):
        snap = _snapshot(TICKETS)
        first = product_health(snap, tenant_id=1)
        second = product_health(snap, tenant_id=1)

        assert first["rows"] == second["rows"]
        assert first["baseline_basis"] == second["baseline_basis"]


class TestVerdict:
    """判断怎么分档。"""

    def test_verdict_uses_peer_median_and_p75(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        rows = _rows_by_product(view)

        assert rows["P1"]["return_rate"] == pytest.approx(0.0)
        assert rows["P1"]["return_rate_verdict"] == VERDICT_GOOD      # <= 中位数

        assert rows["P5"]["return_rate"] == pytest.approx(0.15)
        assert rows["P5"]["return_rate_verdict"] == VERDICT_WATCH     # 中位数 < x <= p75

        assert rows["P7"]["return_rate"] == pytest.approx(0.3)
        assert rows["P7"]["return_rate_verdict"] == VERDICT_BAD       # > p75

    def test_threshold_boundaries_are_inclusive_on_the_lower_band(self):
        """边界值归属：== 中位数 ⇒ good；== p75 ⇒ watch（不是 bad）。"""
        view = product_health(_snapshot(TICKETS), tenant_id=1)
        rows = _rows_by_product(view)
        baseline = view["baselines"]["return_rate"]

        assert baseline["peer_median"] == pytest.approx(0.125)
        assert baseline["peer_p75"] == pytest.approx(0.2)
        # P6 = 20% == p75 ⇒ watch；P7 = 30% > p75 ⇒ bad
        assert rows["P6"]["return_rate_verdict"] == VERDICT_WATCH
        assert rows["P7"]["return_rate_verdict"] == VERDICT_BAD


class TestUnknownIsNotAGood:
    """纪律 1：未知不装懂（注入式红证）。"""

    def test_unknown_rate_yields_unknown_verdict(self):
        snap = _snapshot(TICKETS)
        snap["product_return_stats"].append(
            {"product_id": "P9", "return_tickets": 0, "order_lines": 0}
        )
        snap["skus"].append(
            {
                "sku_id": "S9", "product_id": "P9", "product_name": "无订单商品",
                "stock": 1.0, "sales_count": 0.0, "price": 100.0, "avg_cost": 40.0,
            }
        )
        view = product_health(snap, tenant_id=1)

        assert _rows_by_product(view)["P9"]["return_rate_verdict"] == VERDICT_UNKNOWN

    def test_sample_below_minimum_yields_unknown(self):
        """🔴 注入式红证：把样本从 8 降到阈值以下 ⇒ 判断必须**全部**变 unknown。

        若实现退化成「有值就给判断」，同一断言在此形态下会变绿 ⇒ 本用例捕获。
        """
        below = MIN_BASELINE_SAMPLE - 1
        view = product_health(_snapshot(TICKETS[:below]), tenant_id=1)

        assert MIN_BASELINE_SAMPLE > 1
        for row in view["rows"]:
            assert view["baselines"]["return_rate"] is None
            assert row["return_rate_verdict"] == VERDICT_UNKNOWN

    def test_sample_at_minimum_does_produce_a_verdict(self):
        """对照读数：恰好达到阈值 ⇒ 必须给出判断（否则「样本不足」被写死成永远 unknown）。"""
        view = product_health(_snapshot(TICKETS[:MIN_BASELINE_SAMPLE]), tenant_id=1)

        for row in view["rows"]:
            assert view["baselines"]["return_rate"] is not None
            assert row["return_rate_verdict"] != VERDICT_UNKNOWN


class TestNegativeMarginIsAbsolute:
    """纪律 2：毛利为负是绝对判据（注入式红证）。"""

    def test_negative_margin_is_bad_even_when_the_whole_store_loses_money(self):
        """🔴 注入式红证：全店都亏 ⇒ 基线中位数也是负。

        纯相对判断会把「亏得最少的那行」判成 `good` —— 那正是本单要防的形态。
        """
        margins = [-10.0, -20.0, -30.0, -40.0, -50.0]
        view = product_health(_snapshot([5] * 5, margins=margins), tenant_id=1)

        for row in view["rows"]:
            assert row["gross_margin"] is not None
            assert row["gross_margin"] < 0
            assert row["gross_margin_verdict"] == VERDICT_BAD

    def test_positive_margin_uses_the_peer_baseline(self):
        """🔴 毛利**越大越好** —— 方向曾经是反的（issue #8280）。

        旧断言写的是「毛利 10（最低）⇒ good、毛利 50（最高）⇒ bad」，等于把 bug 固化成期望：
        低毛利 SKU 标绿、且 P3 的选项永远不会给它建议（只给 bad/watch）。
        红证：把 `higher_is_better=True` 去掉 ⇒ 本用例必红。
        """
        margins = [10.0, 20.0, 30.0, 40.0, 50.0]
        view = product_health(_snapshot([5] * 5, margins=margins), tenant_id=1)
        rows = _rows_by_product(view)

        # 中位 = 30：>= 30 ⇒ good；< 30 且 > 0 ⇒ watch（值得看一眼，但不是「健康」）
        assert rows["P1"]["gross_margin_verdict"] == VERDICT_WATCH, "毛利最低 ⇒ 不该判 good"
        assert rows["P3"]["gross_margin_verdict"] == VERDICT_GOOD, "毛利 = 中位 ⇒ good"
        assert rows["P5"]["gross_margin_verdict"] == VERDICT_GOOD, "毛利最高 ⇒ good"

    def test_unknown_margin_yields_unknown_verdict(self):
        snap = _snapshot(TICKETS)
        snap["skus"][0]["avg_cost"] = None
        view = product_health(snap, tenant_id=1)
        row = _rows_by_product(view)["P1"]

        assert row["gross_margin"] is None
        assert row["gross_margin_verdict"] == VERDICT_UNKNOWN


class TestDisclosure:
    """纪律 3：基线性质必须自述 —— 别让调用方把「相对」读成「绝对」。"""

    def test_baseline_basis_is_present_and_says_it_is_relative(self):
        view = product_health(_snapshot(TICKETS), tenant_id=1)

        assert view["baseline_basis"] == BASELINE_BASIS
        assert "相对" in BASELINE_BASIS
        assert "非绝对" in BASELINE_BASIS

    def test_verdict_basis_is_declared_in_view_basis(self):
        """新口径必须进视图 `basis` 口径声明（否则下游不知道基线是怎么来的、阈值怎么分档）。"""
        view = product_health(_snapshot(TICKETS), tenant_id=1)

        assert "return_rate_baseline" in view["basis"]
        assert "return_rate_verdict" in view["basis"]
        assert "gross_margin_verdict" in view["basis"]


class TestToolMessageCarriesTheVerdict:
    """`message` 是模型的唯一摘要（`briefing_query.render_view_result` 的既有口径）。

    基线不进 message ⇒ 模型只会照念「8 个 SKU」，verdict 在 `data` 里也约等于不存在。
    """

    def _context(self):
        from app.tools.base import ToolContext

        return ToolContext(
            tenant_id=1, user_id="u-1", session_id="s-1", role="admin",
            permissions=["dashboard:view"],
        )

    def _message(self, snapshot):
        from app.tools.briefing_query import render_view_result

        return render_view_result("product_health", snapshot, self._context()).message

    def test_message_reports_baseline_and_verdict_counts(self):
        message = self._message(_snapshot(TICKETS))

        assert "同行基线" in message
        assert "12.5%" in message and "20.0%" in message
        assert "8 个样本" in message
        # tickets 30/40 两行 > p75(20%) ⇒ 2 个高于上四分位；15/20 两行居中
        assert "2 个 SKU 高于上四分位" in message
        assert "2 个居中" in message
        assert "相对基线" in message

    def test_message_says_sample_insufficient_instead_of_guessing(self):
        message = self._message(_snapshot(TICKETS[: MIN_BASELINE_SAMPLE - 1]))

        assert "样本不足" in message
        assert "同行基线" not in message
