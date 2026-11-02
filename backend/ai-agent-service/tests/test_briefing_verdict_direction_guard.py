"""方向性判定守卫 —— 传错 / 忘传方向**不可能**通过（issue #8293）

判据来源：issue #8293（由缺陷 #8280 触发）。

## 为什么要有它

`gross_margin_verdict` 的方向曾经是**反的**（#8280：毛利越低越判「好」），而**那条单测也一起写反了** ——
实现和测试互相印证，CI 一直是绿的。

这不是一个 bug，是**一类形态**：凡是「越大越好 / 越小越好」的判定，方向错了不会有任何东西变红，
除非恰好有人给这个指标写了一条**方向正确**的极值断言 —— 而那个人自己也可能写反。

## 三层守卫（本文件 = ②③；① 是 `_verdict` 的签名本身）

| # | 守卫 | 变红的形态 |
|---|---|---|
| ① | `_verdict(metric, ...)` 方向**从表查** | 调用方连传错的机会都没有；新指标没登记 ⇒ `KeyError` |
| ② | **调用点源码扫描**：`_verdict` 第一实参必须是**字面量**且在 `METRIC_DIRECTIONS` 里 | 用变量传 metric 绕过校验 / 新指标忘登记 |
| ③ | **极值双向断言**：对表里每个指标造极值数据，验证方向 | 把表里 `True` 改成 `False`（= #8280 的形态）⇒ 立刻红 |

③ 是最关键的一条：它钉的是**方向这个事实**，不是某个测试文件里的某一行 ——
所以「测试跟着实现一起写错」在这里不可能发生（数据和期望都由**方向表**驱动）。

case_ids：`DA-035`。

"""

# case_ids: DA-035

import ast
import json
from pathlib import Path

import pytest

from app.briefing.product_health import (
    METRIC_DIRECTIONS,
    VERDICT_BAD,
    VERDICT_GOOD,
    VERDICT_WATCH,
    product_health,
)

SOURCE = Path(__file__).resolve().parents[1] / "app/briefing/product_health.py"

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


def _sku(sku_id: str, price=100, cost=60) -> dict:
    return {
        "sku_id": sku_id,
        "product_id": sku_id.split("-")[0],
        "product_name": f"商品{sku_id}",
        "stock": 10,
        "sales_count": 10,
        "price": price,
        "avg_cost": cost,
    }


def _stat(product_id: str, tickets: int, lines: int) -> dict:
    return {"product_id": product_id, "return_tickets": tickets, "order_lines": lines}


class TestCallSitesPassALiteralMetric:
    """② 调用点守卫：`_verdict` 的第一实参必须是**字面量**且在表里。"""

    def _verdict_calls(self) -> list:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "_verdict":
                calls.append(node)
        return calls

    def test_every_call_site_passes_a_string_literal(self):
        calls = self._verdict_calls()
        assert calls, "一个 `_verdict` 调用点都没找到 —— 守卫变成空转"

        for node in calls:
            assert node.args, f"第 {node.lineno} 行的 `_verdict` 调用没有位置实参"
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"第 {node.lineno} 行：`_verdict` 的第一个实参必须是**字符串字面量**（指标名）。"
                "用变量传 metric 会绕过方向校验 —— 那正是本守卫要拦的形态"
            )

    def test_every_literal_metric_is_registered(self):
        for node in self._verdict_calls():
            metric = node.args[0].value
            assert metric in METRIC_DIRECTIONS, (
                f"第 {node.lineno} 行用了未登记的指标 `{metric}` —— "
                "新指标必须先定方向（`METRIC_DIRECTIONS`），否则方向靠猜"
            )

    def test_no_call_site_passes_direction_as_a_parameter(self):
        """方向**不许**由调用方传 —— 它只能来自登记表（这就是 #8280 的根因）。"""
        for node in self._verdict_calls():
            kwargs = {kw.arg for kw in node.keywords}
            assert "higher_is_better" not in kwargs, (
                f"第 {node.lineno} 行仍用关键字传 `higher_is_better` —— "
                "方向必须从 `METRIC_DIRECTIONS` 查，传参形式会让「忘传 / 传错」重新成为可能"
            )


class TestRegisteredDirectionsMatchSemantics:
    """③ 极值双向断言：表里每个指标的方向，用极值数据验证（**这条抓 #8280 的形态**）。"""

    def test_return_rate_is_lower_is_better(self):
        """退货率越低越好。

        ⚠️ 极值断言必须**混合数据**：`_verdict` 是**相对**判据（`<= peer_median ⇒ good`），
        当所有行退货率都是 100% 时基线也是 100% ⇒ 谁都不比谁差 ⇒ 全判 good。
        这是**合理**的（相对基线不制造「全员异常」），但极值测试因此不能拿「全员极值」当样本。
        """
        assert METRIC_DIRECTIONS["return_rate"] is False, "退货率越低越好"

        # 最低（0%）⇒ good
        good = product_health(
            _snapshot(
                [_sku(f"a{i}-s1") for i in range(6)],
                [_stat(f"a{i}", 0, 10) for i in range(6)],
            ),
            tenant_id=1,
        )
        assert all(row["return_rate_verdict"] == VERDICT_GOOD for row in good["rows"])

        # 混合：6 个 0% + 1 个 100% ⇒ 那个 100% 必须 bad（基线被压到 0）
        skus = [_sku(f"b{i}-s1") for i in range(6)] + [_sku("worst-s1")]
        stats = [_stat(f"b{i}", 0, 10) for i in range(6)] + [_stat("worst", 10, 10)]
        bad = product_health(_snapshot(skus, stats), tenant_id=1)
        rows = {row["sku_id"]: row for row in bad["rows"]}

        assert rows["worst-s1"]["return_rate_verdict"] == VERDICT_BAD, "最高的那个必须 bad"
        assert all(
            rows[f"b{i}-s1"]["return_rate_verdict"] == VERDICT_GOOD for i in range(6)
        ), "最低的那批必须 good"

    def test_gross_margin_is_higher_is_better(self):
        """🔴 #8280 的形态：把这里的方向改反 ⇒ 本条必红。"""
        assert METRIC_DIRECTIONS["gross_margin"] is True, "毛利越高越好"

        # 混合一批：最高毛利 ⇒ good；最低但 > 0 ⇒ watch（不是 good，也不是 bad）
        skus = [_sku(f"m{i}-s1", price=100, cost=60) for i in range(5)]  # margin 40
        skus.append(_sku("lo-s1", price=100, cost=95))                    # margin 5（最低）
        skus.append(_sku("hi-s1", price=100, cost=10))                    # margin 90（最高）
        view = product_health(_snapshot(skus), tenant_id=1)
        rows = {row["sku_id"]: row for row in view["rows"]}

        assert rows["hi-s1"]["gross_margin_verdict"] == VERDICT_GOOD, "毛利最高 ⇒ good"
        assert rows["lo-s1"]["gross_margin_verdict"] == VERDICT_WATCH, (
            "毛利最低（但为正）⇒ watch —— 一旦方向反了这里会变 good（#8280）"
        )

    def test_directions_table_is_not_empty(self):
        assert METRIC_DIRECTIONS, "方向表被清空 = 守卫空转（fail-closed）"
        for metric, higher in METRIC_DIRECTIONS.items():
            assert isinstance(higher, bool), f"{metric} 的方向必须是 bool（不许 None 混过去）"


class TestUnregisteredMetricFailsLoudly:
    """① 未登记指标 ⇒ `KeyError`（不是静默按默认方向走）。"""

    def test_unknown_metric_raises(self):
        from app.briefing.product_health import _verdict

        with pytest.raises(KeyError):
            _verdict("not_a_registered_metric", 1.0, {"peer_median": 0.5, "peer_p75": 0.8})

    def test_message_names_the_metric_and_the_table_json(self):
        from app.briefing.product_health import _verdict

        try:
            _verdict("brand_new_metric", 1.0, {"peer_median": 0.5, "peer_p75": 0.8})
        except KeyError as exc:
            text = str(exc)
            assert "brand_new_metric" in text, f"报错必须点名指标：{text}"
            assert "METRIC_DIRECTIONS" in text, f"报错必须指向登记表：{text}"
        else:
            raise AssertionError("未登记指标竟然算出了 verdict")
