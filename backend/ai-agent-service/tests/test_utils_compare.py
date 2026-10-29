"""`app/utils/compare.py` —— 环比 / 归因共用的数值口径（issue #8157）

为什么单独判：`trend_compare` 与 `sales_attribution` 都声明「上期为 0 ⇒ 不算百分比」，
而这条口径过去是两份实现 —— 任何一份漂移都会让同一类问题给出两个答案（#3570 的教训）。
本文件把口径钉成**事实**：非有限值/布尔/字符串不是数字；上期为 0 没有百分比。
"""
# case_ids: DA-027

import math

from app.utils.compare import MAX_PERIOD_DAYS, MAX_WINDOW_DAYS, delta_pct, finite_number


class TestFiniteNumber:
    """结构异常识别：读不懂的数值一律 None（不得当 0 参与算术）"""

    def test_ints_and_floats_pass_through(self):
        assert finite_number(7) == 7
        assert isinstance(finite_number(7), int)
        assert finite_number(12.5) == 12.5

    def test_bool_string_none_and_non_finite_are_not_numbers(self):
        for value in (True, False, "3", "", None, float("nan"),
                      float("inf"), float("-inf"), [1], {"a": 1}):
            assert finite_number(value) is None, f"{value!r} 被当成了数字"

    def test_zero_is_a_number(self):
        # 0 是**合法**读数（真的没卖），与「读不出来」必须区分开
        assert finite_number(0) == 0
        assert finite_number(0.0) == 0.0
        assert math.isfinite(finite_number(0))


class TestDeltaPct:
    """上期为 0 ⇒ None（绝不 Infinity/NaN）；其余四舍五入到 2 位"""

    def test_zero_baseline_has_no_percentage(self):
        assert delta_pct(100, 0) is None
        assert delta_pct(0, 0) is None

    def test_rounding_and_sign(self):
        assert delta_pct(100, 400) == 25.0
        assert delta_pct(-140, 590.5) == -23.71
        assert delta_pct(1, 3) == 33.33
        assert delta_pct(0, 50) == 0.0

    def test_result_is_always_finite(self):
        for delta, previous in ((10, 3), (-10, 3), (10 ** 9, 0.5), (0, 1)):
            value = delta_pct(delta, previous)
            assert math.isfinite(value), f"delta={delta} previous={previous} → {value!r}"


class TestPeriodCap:
    """每期上限是**同一份**参数契约（trend_compare 与 sales_attribution 共用）"""

    def test_period_cap(self):
        assert MAX_PERIOD_DAYS == 30
        assert MAX_WINDOW_DAYS == 60
