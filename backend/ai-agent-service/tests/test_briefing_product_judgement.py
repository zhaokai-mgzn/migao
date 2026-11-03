# case_ids: MC-186
"""商品健康度 · 判断层（`app/briefing/product_judgement.py`）—— issue #8290 拆分后的**行为钉子**

判据（每条都能单独变红）：
1. `_median` / `_p75`：奇偶两种分位口径逐值钉住（`p75` = 最近秩法 `ceil(0.75n)`），空集 ⇒ `None`。
2. `_peer_baseline`：`None` **不进样本**；有效样本 < `MIN_BASELINE_SAMPLE` ⇒ `None`（不装懂）。
3. `_verdict`：分档边界（**等号归属**）逐值钉住；值未知 / 基线不可用 ⇒ `unknown`。
4. **方向登记即契约**：`METRIC_DIRECTIONS` 逐字；未登记指标 ⇒ `KeyError` 点名表名。
5. 🔴 注入式红证：把 `gross_margin` 的方向翻成 False（= 缺陷 #8280 的形态）⇒ 同一条极值断言必红。
"""

from decimal import Decimal

import pytest

from app.briefing.product_judgement import (
    MIN_BASELINE_SAMPLE,
    VERDICT_BAD,
    VERDICT_GOOD,
    VERDICT_UNKNOWN,
    VERDICT_WATCH,
    _median,
    _p75,
    _peer_baseline,
    _verdict,
)
from app.briefing.product_judgement import METRIC_DIRECTIONS


class TestQuantiles:
    """判据 1：口径逐值钉住（这两个函数是「同行基线」的唯一算术来源）。"""

    def test_median_odd_and_even(self):
        assert _median([]) is None
        assert _median([Decimal(7)]) == Decimal(7)
        assert _median([Decimal(3), Decimal(1), Decimal(2)]) == Decimal(2)
        assert _median([Decimal(4), Decimal(1), Decimal(3), Decimal(2)]) == Decimal("2.5")

    def test_p75_nearest_rank(self):
        # ceil(0.75n)：n=8 ⇒ 第 6 个；n=4 ⇒ 第 3 个；n=1 ⇒ 第 1 个（1-based）
        assert _p75([]) is None
        assert _p75([Decimal(i) for i in range(1, 9)]) == Decimal(6)
        assert _p75([Decimal(i) for i in range(1, 5)]) == Decimal(3)
        assert _p75([Decimal(9)]) == Decimal(9)


class TestPeerBaseline:
    """判据 2：`None` 不进样本；样本太少不装懂。"""

    def test_unknowns_are_excluded_from_the_sample(self):
        baseline = _peer_baseline([10.0, None, 20.0, None, 30.0, 40.0, 50.0])
        assert baseline == {"peer_median": 30.0, "peer_p75": 40.0, "sample_size": 5}

    def test_sample_below_minimum_yields_none(self):
        values = [10.0] * (MIN_BASELINE_SAMPLE - 1)
        assert _peer_baseline(values) is None
        assert _peer_baseline([None] * 10) is None


class TestVerdictBoundaries:
    """判据 3：等号归属是契约（`<= median` ⇒ good / `<= p75` ⇒ watch / `> p75` ⇒ bad）。"""

    BASELINE = {"peer_median": 10.0, "peer_p75": 20.0, "sample_size": 9}

    def test_return_rate_is_lower_is_better(self):
        assert _verdict("return_rate", 9.0, self.BASELINE) == VERDICT_GOOD
        assert _verdict("return_rate", 10.0, self.BASELINE) == VERDICT_GOOD      # 等号归 good
        assert _verdict("return_rate", 20.0, self.BASELINE) == VERDICT_WATCH     # 等号归 watch
        assert _verdict("return_rate", 20.1, self.BASELINE) == VERDICT_BAD

    def test_unknown_value_or_baseline_is_unknown(self):
        assert _verdict("return_rate", None, self.BASELINE) == VERDICT_UNKNOWN
        assert _verdict("return_rate", 5.0, None) == VERDICT_UNKNOWN

    def test_gross_margin_is_higher_is_better(self):
        assert _verdict("gross_margin", 10.0, self.BASELINE) == VERDICT_GOOD
        assert _verdict("gross_margin", 9.9, self.BASELINE) == VERDICT_WATCH

    def test_negative_margin_is_absolutely_bad(self):
        """全店都亏时中位数也是负 ⇒ 相对判据会判 good；绝对判据必须先兜成 bad。"""
        all_loss = {"peer_median": -5.0, "peer_p75": -1.0, "sample_size": 9}
        assert _verdict("gross_margin", -8.0, all_loss, absolute_bad=True) == VERDICT_BAD
        assert _verdict("gross_margin", -8.0, all_loss) == VERDICT_WATCH, "没有绝对判据就只剩相对"

    def test_unregistered_metric_fails_loudly(self):
        with pytest.raises(KeyError) as exc:
            _verdict("brand_new_metric", 1.0, self.BASELINE)
        text = str(exc.value)
        assert "brand_new_metric" in text and "METRIC_DIRECTIONS" in text


class TestDirectionsAreRegistered:
    """判据 4 + 判据 5：方向来自表，不来自调用方；翻方向 ⇒ 极值断言必红。"""

    @staticmethod
    def _assert_margin_direction(margin_is_higher_better: bool) -> None:
        table = {"peer_median": 10.0, "peer_p75": 20.0, "sample_size": 9}
        if margin_is_higher_better:
            assert _verdict("gross_margin", 99.0, table) == VERDICT_GOOD
            assert _verdict("gross_margin", 1.0, table) == VERDICT_WATCH
        else:
            assert _verdict("gross_margin", 99.0, table) == VERDICT_BAD
            assert _verdict("gross_margin", 1.0, table) == VERDICT_GOOD

    def test_table_content_is_the_contract(self):
        assert METRIC_DIRECTIONS == {"return_rate": False, "gross_margin": True}

    def test_the_registered_direction_holds(self):
        self._assert_margin_direction(METRIC_DIRECTIONS["gross_margin"])

    def test_flipping_the_registered_direction_turns_the_same_assertion_red(self):
        """🔴 注入式红证：缺陷 #8280 的形态 = 方向反了而单测一起写反 ⇒ 这里必须红。"""
        original = METRIC_DIRECTIONS["gross_margin"]
        METRIC_DIRECTIONS["gross_margin"] = not original
        try:
            with pytest.raises(AssertionError):
                self._assert_margin_direction(original)
        finally:
            METRIC_DIRECTIONS["gross_margin"] = original
        self._assert_margin_direction(METRIC_DIRECTIONS["gross_margin"])
