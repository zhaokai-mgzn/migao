"""窗帘算料报价核心函数单元测试（app/tools/curtain_calc.py）

覆盖（POC 小布增强 · 算料报价工具）：
- 定高布买宽公式：M = (W + 0.3) × N
- 定宽布买高公式（窗高超门幅上限）：P = ceil((W+0.3)×N/G)，M = P × (H+0.3)
- 褶皱倍数默认值（按悬挂方式：打孔/韩式褶/四爪钩=2.0，罗马帘=1.0）
- 对花损耗：每幅加花距
- 罗马帘公式：M = (W+0.2) × (H+0.3)
- 完整报价：面料费+加工费+辅料费+安装费=总价
- 超限告警：成品高超门幅定高上限时返回 warning

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）
"""
# case_ids: PR-013

import math
import pytest

from app.tools.curtain_calc import (
    DEFAULT_FULLNESS,
    DEFAULT_PROCESSING_PRICE,
    calculate_fabric_meters,
    build_quote,
)


# ──────────────────────────────────────────────
# 1. 定高布买宽（标准场景）
# ──────────────────────────────────────────────

def test_fixed_height_meters_standard():
    """定高布买宽：M = (W + 0.3) × N。

    窗宽 3m、窗高 2.5m、2 倍褶皱、门幅 2.8m（不超限）→ (3+0.3)×2 = 6.6m
    """
    meters, formula, warning = calculate_fabric_meters(
        window_width=3.0,
        window_height=2.5,
        fullness=2.0,
        fabric_width=2.8,
        mounting="eyelet",
    )
    assert meters == pytest.approx(6.6)
    assert formula == "fixed_height"
    assert warning == ""


def test_fixed_height_boundary_2_5m_ok():
    """边界：窗高 2.5m + 卷边 0.3 = 2.8 恰好等于门幅，仍可用定高布"""
    meters, formula, warning = calculate_fabric_meters(
        window_width=3.0, window_height=2.5, fullness=2.0, fabric_width=2.8
    )
    assert formula == "fixed_height"
    assert warning == ""


# ──────────────────────────────────────────────
# 2. 定宽布买高（窗高超限）
# ──────────────────────────────────────────────

def test_fixed_width_meters_when_over_limit():
    """窗高 2.7m + 卷边 0.3 = 3.0 > 门幅 2.8 → 定宽布。

    P = ceil((3+0.3)×2 / 2.8) = ceil(6.6/2.8) = ceil(2.357) = 3
    L = 2.7 + 0.3 = 3.0
    M = 3 × 3.0 = 9.0
    """
    meters, formula, warning = calculate_fabric_meters(
        window_width=3.0,
        window_height=2.7,
        fullness=2.0,
        fabric_width=2.8,
        mounting="eyelet",
    )
    assert meters == pytest.approx(9.0)
    assert formula == "fixed_width"
    assert warning  # 必须返回告警提示超限


def test_fixed_width_panel_round_up():
    """幅数必须向上取整：窄门幅 1.4m 时。

    (3+0.3)×2 / 1.4 = 6.6/1.4 = 4.714 → ceil = 5 幅
    """
    meters, formula, _ = calculate_fabric_meters(
        window_width=3.0,
        window_height=2.7,
        fullness=2.0,
        fabric_width=1.4,
    )
    # P=5, L=3.0, M=15.0
    assert meters == pytest.approx(15.0)
    assert formula == "fixed_width"


# ──────────────────────────────────────────────
# 3. 褶皱倍数默认值（按悬挂方式）
# ──────────────────────────────────────────────

def test_default_fullness_by_mounting():
    """悬挂方式决定默认褶皱倍数"""
    assert DEFAULT_FULLNESS["eyelet"] == 2.0   # 打孔帘
    assert DEFAULT_FULLNESS["s_hook"] == 2.0   # 韩式褶
    assert DEFAULT_FULLNESS["hook"] == 2.0     # 四爪钩
    assert DEFAULT_FULLNESS["roman"] == 1.0    # 罗马帘（无褶皱）


def test_default_processing_price_by_mounting():
    """悬挂方式决定默认加工费单价（元/米）"""
    assert DEFAULT_PROCESSING_PRICE["eyelet"] == 8.0
    assert DEFAULT_PROCESSING_PRICE["s_hook"] == 10.0
    assert DEFAULT_PROCESSING_PRICE["hook"] == 5.0
    assert DEFAULT_PROCESSING_PRICE["roman"] == 0.0


# ──────────────────────────────────────────────
# 4. 对花损耗
# ──────────────────────────────────────────────

def test_pattern_repeat_adds_to_panel_length():
    """对花时每幅加 1 个花距：L = H + 0.3 + 花距"""
    meters, formula, _ = calculate_fabric_meters(
        window_width=3.0,
        window_height=2.7,
        fullness=2.0,
        fabric_width=2.8,
        mounting="eyelet",
        has_pattern=True,
        pattern_repeat=0.4,
    )
    # P=3, L=2.7+0.3+0.4=3.4, M=10.2
    assert meters == pytest.approx(10.2)
    assert formula == "fixed_width"


# ──────────────────────────────────────────────
# 5. 罗马帘
# ──────────────────────────────────────────────

def test_roman_shade_meters():
    """罗马帘：M = (W + 0.2) × (H + 0.3)，无褶皱倍率"""
    meters, formula, _ = calculate_fabric_meters(
        window_width=2.0,
        window_height=2.0,
        fullness=1.0,
        fabric_width=2.8,
        mounting="roman",
    )
    # (2+0.2)×(2+0.3) = 2.2×2.3 = 5.06
    assert meters == pytest.approx(5.06)
    assert formula == "roman_panel"


# ──────────────────────────────────────────────
# 6. 完整报价（总价 = 面料 + 加工 + 辅料 + 安装）
# ──────────────────────────────────────────────

def test_quote_total_breakdown():
    """完整报价：打孔帘 3m×2.5m、2 倍褶、2.8m 定高、面料 30 元/米。

    M = 6.6m
    面料费 = 6.6 × 30 = 198
    加工费 = 6.6 × 8 = 52.8
    辅料费 = 罗马圈 40×1.5=60 + 孔带 6.6×8=52.8 + 罗马杆 3.4×25=85 + 绑带 15 = 212.8
    安装费 = 3.4 × 18 = 61.2
    总价 = 198 + 52.8 + 212.8 + 61.2 = 524.8
    """
    quote = build_quote(
        window_width=3.0,
        window_height=2.5,
        mounting="eyelet",
        fabric_width=2.8,
        fabric_price=30.0,
    )
    assert quote["fabric_meters"] == pytest.approx(6.6)
    assert quote["fabric_cost"] == pytest.approx(198.0)
    assert quote["processing_cost"] == pytest.approx(52.8)
    # 辅料：罗马圈 40×1.5=60 + 孔带 52.8 + 罗马杆 85 + 绑带 15
    assert quote["accessory_cost"] == pytest.approx(60 + 52.8 + 85 + 15)
    assert quote["install_cost"] == pytest.approx(61.2)
    assert quote["total"] == pytest.approx(198 + 52.8 + 212.8 + 61.2)


def test_quote_uses_default_fullness_when_not_provided():
    """未传 fullness 时按悬挂方式默认（打孔=2.0）"""
    quote = build_quote(
        window_width=3.0,
        window_height=2.5,
        mounting="eyelet",
        fabric_width=2.8,
        fabric_price=30.0,
    )
    assert quote["fabric_meters"] == pytest.approx(6.6)


def test_quote_warning_on_over_limit():
    """窗高超限时报价带告警，且改用定宽公式"""
    quote = build_quote(
        window_width=3.0,
        window_height=2.7,
        mounting="eyelet",
        fabric_width=2.8,
        fabric_price=30.0,
    )
    assert quote["fabric_meters"] == pytest.approx(9.0)
    assert quote.get("warning")  # 必须有告警


# ──────────────────────────────────────────────
# 7. GB/T 47746-2026 承诺边界：面料单价缺失 → 拒绝（不再按默认 30 元/米兜底）
# ──────────────────────────────────────────────

class TestCurtainCalcPriceGuard:
    """Tool 层 execute：无 fabric_price 必须失败并引导查价；报价成功须带「预估」限定"""

    async def test_missing_fabric_price_rejected_with_suggestion(self, sample_tool_context):
        """未提供 fabric_price → 失败且 suggestion 引导先查商品信息（不再输出默认 30 元报价）"""
        from app.tools.curtain_calc import CurtainCalcTool
        tool = CurtainCalcTool()
        result = await tool.execute(
            context=sample_tool_context,
            window_width=3.0,
            window_height=2.5,
            mounting="eyelet",
        )
        assert result.success is False, "缺少面料单价时必须拒绝报价，禁止默认兜底"
        assert result.error == "缺少面料单价"
        assert "面料单价" in (result.message or "")
        assert result.suggestion and "product_detail" in result.suggestion, (
            "suggestion 应引导先用 product_detail/product_search 查询面料单价"
        )
        assert result.data is None

    async def test_quote_success_message_contains_estimate_qualifier(self, sample_tool_context):
        """提供 fabric_price → 成功，且 message 含「估算/预估」限定（非精确报价承诺）"""
        from app.tools.curtain_calc import CurtainCalcTool
        tool = CurtainCalcTool()
        result = await tool.execute(
            context=sample_tool_context,
            window_width=3.0,
            window_height=2.5,
            mounting="eyelet",
            fabric_price=30.0,
        )
        assert result.success is True, f"提供面料单价应正常报价: error={result.error}"
        assert "预估" in (result.message or "") or "估算" in (result.message or ""), (
            f"报价 message 必须带预估限定: {result.message}"
        )
