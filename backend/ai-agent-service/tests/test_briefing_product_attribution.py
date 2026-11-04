# case_ids: MC-186
"""商品健康度 · 归因（`app/briefing/product_attribution.py`）—— issue #8290 拆分后的**行为钉子**

判据（每条都能单独变红）：
1. 没问题（good / unknown）⇒ **不给归因**（`None`；不是「没发现问题」）。
2. SKU 级信号（毛利）才做同款对照 ⇒ `sibling_margin_contrast` / `level=sku`，gap 有方向。
3. 🔴 退货率是**商品级**数据 ⇒ 只给 `product_level_only` 且**没有** `gap`（变体 gap 恒为 0 = 假归因）。
4. 单独一个 SKU / 兄弟毛利未知 / 兄弟都不比本行好 ⇒ `None`（没有对照就没有差异）。
5. `_sales_text`：销量未知说「未知」，有值说「N 件」。
"""

from app.briefing.product_attribution import ATTRIBUTION_BASIS, _attribution, _sales_text


def _row(**overrides):
    row = {"sku_id": "S1", "product_id": "P1", "sales_count": 5.0,
           "gross_margin": 10.0, "return_rate": 0.4,
           "return_rate_verdict": "good", "gross_margin_verdict": "good"}
    row.update(overrides)
    return row


class TestNoVerdictMeansNoAttribution:
    """判据 1：good 行解释「为什么好」是噪音。"""

    def test_good_row_gets_none(self):
        assert _attribution(_row(), [_row()]) is None

    def test_unknown_row_gets_none(self):
        assert _attribution(
            _row(return_rate_verdict="unknown", gross_margin_verdict="unknown"),
            [_row()],
        ) is None


class TestSkuLevelContrast:
    """判据 2：毛利是 SKU 级 ⇒ 差异可以指到变体。"""

    def test_bad_margin_points_at_the_variant(self):
        me = _row(gross_margin=10.0, gross_margin_verdict="bad", sales_count=5.0)
        sibling = _row(sku_id="S2", gross_margin=50.0, gross_margin_verdict="good", sales_count=7.0)

        attribution = _attribution(me, [me, sibling])

        assert attribution["kind"] == "sibling_margin_contrast"
        assert attribution["level"] == "sku"
        assert attribution["sibling_count"] == 2
        assert attribution["best_sibling_sku_id"] == "S2"
        assert attribution["best_sibling_gross_margin"] == 50.0
        assert attribution["gap"] == -40.0, "gap = 本行 − 最好的兄弟（负数 = 比它差）"
        assert "5 件" in attribution["sample_note"] and "7 件" in attribution["sample_note"]
        assert "差异证据" in attribution["sample_note"], "只说差异，不给因果"


class TestNoContrastNoAttribution:
    """判据 4：没有对照就没有差异。"""

    def test_single_sku_gets_none(self):
        me = _row(gross_margin_verdict="bad")
        assert _attribution(me, [me]) is None

    def test_sibling_with_unknown_margin_is_excluded(self):
        me = _row(gross_margin_verdict="bad")
        dirty = _row(sku_id="S2", gross_margin=None)
        assert _attribution(me, [me, dirty]) is None, "脏数据算出的差值是噪音"

    def test_best_sibling_is_not_better_means_none(self):
        me = _row(gross_margin=10.0, gross_margin_verdict="bad")
        weaker = _row(sku_id="S2", gross_margin=4.0)
        assert _attribution(me, [me, weaker]) is None, "自己已经是同款里最好的 ⇒ 没有可指的差异"


class TestReturnRateIsProductLevelOnly:
    """判据 3：退货率按 product_id 聚合 ⇒ 变体 gap 恒为 0，不许给假归因。"""

    def test_high_return_rate_yields_product_level_only(self):
        row = _row(return_rate_verdict="bad", gross_margin_verdict="good")
        attribution = _attribution(row, [row, _row(sku_id="S2")])

        assert attribution["kind"] == "product_level_only"
        assert attribution["level"] == "product"
        assert "gap" not in attribution, "🔴 变体 gap 恒为 0 —— 那是假归因"
        assert "商品级" in attribution["reason"]

    def test_margin_signal_wins_when_both_are_bad(self):
        me = _row(gross_margin=10.0, gross_margin_verdict="bad", return_rate_verdict="bad")
        attribution = _attribution(me, [me, _row(sku_id="S2", gross_margin=50.0)])
        assert attribution["kind"] == "sibling_margin_contrast", "能指到变体时优先指到变体"


class TestSalesText:
    """判据 5：样本量读数（销量并排给出，由人判断）。"""

    def test_unknown_and_known(self):
        assert _sales_text({"sales_count": None}) == "未知"
        assert _sales_text({"sales_count": 12}) == "12 件"

    def test_basis_says_difference_is_not_causation(self):
        assert "差异证据，不是因果结论" in ATTRIBUTION_BASIS
