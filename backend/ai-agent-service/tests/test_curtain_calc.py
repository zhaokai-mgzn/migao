"""窗帘算料报价核心函数单元测试（app/tools/curtain_calc.py）

覆盖（POC 小布增强 · 算料报价工具）：
- 定高布买宽公式：M = (W + 0.3) × N
- 定宽布买高公式（窗高超门幅上限）：P = ceil((W+0.3)×N/G)，M = P × (H+0.3)
- 褶皱倍数默认值（按悬挂方式：打孔/韩式褶/四爪钩=2.0，罗马帘=1.0）
- 对花损耗：每幅加花距
- 罗马帘公式：M = (W+0.2) × (H+0.3)
- 完整报价：面料费+加工费+辅料费+安装费=总价
- 超限告警：成品高超门幅定高上限时返回 warning
- 韩折折数法（M2-C，issue #3982）：0.25×折数+余量（单开0.2/多开0.3）、
  倍数→折数派生（按开数取整）、工艺档位、来源标记、倍数<1.5 红线、
  开数整除调整、按货号-色号汇总（采购/套裁视图）

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）
"""
# case_ids: PR-013, PR-024, OR-022, CH-036

import math
import pytest

from app.tools.curtain_calc import (
    DEFAULT_FULLNESS,
    DEFAULT_PROCESSING_PRICE,
    DEFAULT_CRAFT_TIERS,
    calculate_fabric_meters,
    calculate_fabric_by_pleats,
    calculate_multi_position,
    derive_pleat_count,
    margin_for_open_count,
    aggregate_by_fabric,
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


class TestCurtainCalcDescriptionGuard:
    """工具描述必须写明"顾客直接报米数时不要算料"（issue #3395）。

    为什么守描述而不是只守 prompt：模型决定**要不要调这个工具**时，直接读的是工具描述
    （`bind_tools` 后的 function description）。实测 run 34748745308：顾客说「买…3 米」，
    模型按描述里的「需要窗宽/窗高」自行假设了窗宽 3 米、窗高 2.7 米就走了算料。
    """

    def test_description_warns_against_purchase_meters(self):
        from app.tools.curtain_calc import CurtainCalcTool
        desc = CurtainCalcTool.description
        assert "购买数量" in desc, "描述必须点明「顾客说的米数＝购买数量」"
        assert "不要" in desc and "调用本工具" in desc, "必须明确写「不要调用本工具」"
        assert "窗宽" in desc and "窗高" in desc, "必须说明只有窗户尺寸才调用"


# ──────────────────────────────────────────────
# 韩折折数法（【标】0.25 米/折 + 余量：单开 0.2 / 多开 0.3）
# 行业实证：6.6m 韩褶双开 48 折 → 0.25×48+0.3 = 12.3 米
# ──────────────────────────────────────────────
def test_pleat_fabric_industry_case():
    """行业实证：48 折双开 → 12.3 米（客户纸表/加工单一致）"""
    meters, warning, info = calculate_fabric_by_pleats(48, open_count=2)
    assert meters == 12.3
    assert warning == ""
    assert info["per_panel_pleats"] == 24
    assert info["margin"] == 0.3


def test_pleat_fabric_single_margin():
    """单开余量 0.2：20 折 → 5.2 米"""
    meters, _, _ = calculate_fabric_by_pleats(20, open_count=1)
    assert meters == 5.2


def test_margin_for_open_count():
    assert margin_for_open_count(1) == 0.2
    assert margin_for_open_count(2) == 0.3
    assert margin_for_open_count(4) == 0.3


def test_derive_pleat_count_from_fullness():
    """倍数意图→折数实现：6.6m × 2.0 双开 → 52 折（(13.2-0.3)/0.25=51.6→52），且为偶数"""
    pleats, warning = derive_pleat_count(6.6, 2.0, open_count=2)
    assert pleats == 52
    assert pleats % 2 == 0
    assert warning == ""


def test_derive_pleat_count_four_way_divisible():
    """四开：折数必须是 4 的倍数"""
    pleats, _ = derive_pleat_count(6.6, 2.0, open_count=4)
    assert pleats % 4 == 0


def test_fullness_red_line_rejected():
    """红线：倍数 < 1.5 拒绝（行业美学下限，见真值源 §1）"""
    with pytest.raises(ValueError):
        derive_pleat_count(3.0, 1.4, open_count=2)


def test_pleat_divisibility_adjustment():
    """47 折双开不可整除 → 自动取 48 并告警"""
    meters, warning, info = calculate_fabric_by_pleats(47, open_count=2)
    assert info["pleat_count"] == 48
    assert "47" in warning and "48" in warning
    assert meters == 12.3


def test_craft_tiers():
    """工艺档位：标准 2.0 / 经济 1.8，档位越高折数越多（换算唯一性）"""
    assert DEFAULT_CRAFT_TIERS["standard"]["fullness"] == 2.0
    assert DEFAULT_CRAFT_TIERS["economy"]["fullness"] == 1.8
    p_s, _ = derive_pleat_count(6.6, DEFAULT_CRAFT_TIERS["standard"]["fullness"], 2)
    p_e, _ = derive_pleat_count(6.6, DEFAULT_CRAFT_TIERS["economy"]["fullness"], 2)
    assert p_s > p_e


def test_pleat_source_marker():
    """取值来源标记：客户自报折数"""
    _, _, info = calculate_fabric_by_pleats(48, open_count=2, source="customer_quoted")
    assert info["source"] == "customer_quoted"


def test_aggregate_by_fabric():
    """按货号-色号汇总（手写单实证）：2698-11 跨 4 部位合计 9.2+4+5.5+9.3 = 28.0 米"""
    positions = [
        {"fabric_code": "2698-11", "meters": 9.2},
        {"fabric_code": "2698-11", "meters": 4.0},
        {"fabric_code": "2698-11", "meters": 5.5},
        {"fabric_code": "2698-11", "meters": 9.3},
        {"fabric_code": "25118-C31", "meters": 8.3},
    ]
    agg = aggregate_by_fabric(positions)
    assert agg["2698-11"] == 28.0
    assert agg["25118-C31"] == 8.3


def test_build_quote_pleat_mode():
    """build_quote 折数法：48 折双开（3.2m 定高布，对应行业 6.6×2.6 场景）→ 用料 12.3，且带折数/来源/档位信息"""
    q = build_quote(
        window_width=6.6, window_height=2.6, mounting="s_hook",
        fabric_width=3.2,
        pleat_count=48, open_count=2, source="customer_quoted",
        fabric_price=23.8,
    )
    assert q["fabric_meters"] == 12.3
    assert q["pleat_count"] == 48
    assert q["open_count"] == 2
    assert q["source"] == "customer_quoted"
    assert q["formula_used"] == "fixed_height_pleats"


def test_multi_position_quote():
    """多部位批量：两扇窗（3.2m 定高布）→ 各自报价 + 总用料 + 按货号汇总"""
    positions = [
        {"window_width": 4.64, "window_height": 2.6, "mounting": "s_hook",
         "pleat_count": 46, "open_count": 2, "fabric_width": 3.2,
         "fabric_code": "2698-11", "fabric_price": 23.8},
        {"window_width": 4.64, "window_height": 2.35, "mounting": "s_hook",
         "pleat_count": 33, "open_count": 2, "fabric_width": 3.2,
         "fabric_code": "25118-C31", "fabric_price": 30.0},
    ]
    res = calculate_multi_position(positions)
    assert len(res["positions"]) == 2
    # 33 折双开不可整除 → 自动调整为 34 折（8.8 米）
    expected = (0.25 * 46 + 0.3) + (0.25 * 34 + 0.3)
    assert abs(res["total_meters"] - expected) < 0.01
    assert res["positions"][1]["pleat_count"] == 34
    assert res["by_fabric"]["2698-11"] > 0
    assert res["by_fabric"]["25118-C31"] > 0
