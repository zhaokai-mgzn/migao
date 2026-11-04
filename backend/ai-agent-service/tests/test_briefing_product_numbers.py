# case_ids: MC-186
"""商品健康度 · 数值底座（`app/briefing/product_numbers.py`）—— issue #8290 拆分后的**行为钉子**

拆前这些 helper 与视图同住（`product_health.py` 893 行），拆后成为**仓内零依赖**的底层模块。
本文件只钉**行为**（拆分前后一个字没改），外加一条注入式红证：把 `_gross_margin` 换成
「未知当 0」的版本 ⇒ **同一条断言**必须变红（证明拆出去的接缝还在）。

判据（每条都能单独变红）：
1. `_dec`：非数值 / 非有限 / bool / 缺省 ⇒ `None`；合法值（含字符串形态）⇒ `Decimal`。
2. **未知 ≠ 0（双向）**：`None` ⇒ `None`；真 `0` ⇒ `Decimal("0")` —— 0 是**结论**，不是未知。
3. `_out`：4 位小数、`ROUND_HALF_UP`；`None` 原样透出（不是 0.0）。
4. `_int_or_none`：负数 / 非数值 ⇒ `None`；整数形态（含 `"7"`）⇒ `int`。
5. `_gross_margin`：任一端未知 ⇒ `None`；两端有值 ⇒ 差值。
"""

from decimal import Decimal

import pytest

from app.briefing.product_numbers import _OUTPUT_QUANT, _dec, _gross_margin, _int_or_none, _out


class TestDecNeverGuesses:
    """判据 1：读不出就是未知，**不猜 0**。"""

    @pytest.mark.parametrize("value", [None, "", "   ", "abc", Decimal("NaN"), "Infinity",
                                       True, False, [], {}, ["1"]])
    def test_unreadable_values_are_unknown(self, value):
        assert _dec(value) is None

    def test_readable_values_are_decimals(self):
        assert _dec(3) == Decimal("3")
        assert _dec(" 12.5 ") == Decimal("12.5")
        assert _dec(Decimal("7.25")) == Decimal("7.25")
        assert _dec(0) == Decimal("0"), "真 0 必须读成 0（它是结论，不是未知）"


class TestOutKeepsUnknownAndRounds:
    """判据 3 + 判据 2 的「未知」那一端：`None` 不许变成 `0.0`。"""

    def test_none_passes_through(self):
        assert _out(None) is None

    def test_quant_is_four_places_half_up(self):
        assert _OUTPUT_QUANT == Decimal("0.0001")
        assert _out(Decimal("1.00005")) == 1.0001      # HALF_UP：第 5 位进位
        assert _out(Decimal("1.00004")) == 1.0
        assert _out(Decimal("1.2345678")) == 1.2346


class TestIntOrNone:
    """判据 4：计数读不出 / 为负 ⇒ 未知（负数不是「0 条」）。"""

    def test_negative_and_garbage_are_unknown(self):
        assert _int_or_none(-1) is None
        assert _int_or_none("abc") is None
        assert _int_or_none(None) is None

    def test_counts(self):
        assert _int_or_none(7) == 7
        assert _int_or_none("7") == 7
        assert _int_or_none(0) == 0


class TestGrossMarginUnknownIsNotZero:
    """判据 5：这是「未知 vs 0」的**唯一接缝**，两个方向都要钉住。"""

    @staticmethod
    def _assert_unknown_is_not_zero(margin_fn) -> None:
        """同一条断言既跑绿版、也跑注入版（红证就是让它变红的那一次）。"""
        assert margin_fn(Decimal("10"), None) is None, "成本未知 ⇒ 毛利未知"
        assert margin_fn(None, Decimal("6")) is None, "售价未知 ⇒ 毛利未知"
        assert margin_fn(None, None) is None
        assert margin_fn(Decimal("10"), Decimal("6")) == Decimal("4"), "有真值 ⇒ 真差值"
        assert margin_fn(Decimal("6"), Decimal("6")) == Decimal("0"), "售价 = 成本 ⇒ 真 0"
        assert margin_fn(None, Decimal("6")) != Decimal("0"), "🔴 未知不得被写成 0"

    def test_the_real_function_satisfies_the_assertion(self):
        self._assert_unknown_is_not_zero(_gross_margin)

    def test_injected_zero_filling_turns_the_same_assertion_red(self):
        """🔴 注入式红证：「未知当 0」⇒ **同一条断言**必红（否则上面那条是空断言）。"""
        import app.briefing.product_numbers as numbers

        original = numbers._gross_margin
        numbers._gross_margin = lambda price, avg_cost: (price or Decimal(0)) - (avg_cost or Decimal(0))
        try:
            with pytest.raises(AssertionError):
                self._assert_unknown_is_not_zero(numbers._gross_margin)
        finally:
            numbers._gross_margin = original
        # 还原后必须回到绿（变红来自注入，不是夹具本身坏了）
        self._assert_unknown_is_not_zero(_gross_margin)
