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
- 辅料口径（issue #4118，以 #3005 为准）：罗马圈**不得**由米数推导/默认单列，
  只走 `accessories` 显式入参（数量/单价由顾客给；缺项 fail-closed）
- 文档算例锚定（issue #4118 ②）：§7 的数值必须被代码**逐值复现**，改文档/改代码都变红

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）
"""
# case_ids: PR-013, PR-024, OR-022, CH-036, CH-038

import math
import re
from pathlib import Path

import pytest

from app.tools import curtain_calc as curtain_calc_module
from app.tools.curtain_calc import (
    DEFAULT_FULLNESS,
    DEFAULT_PROCESSING_PRICE,
    DEFAULT_CRAFT_TIERS,
    calculate_fabric_meters,
    calculate_fabric_by_pleats,
    calculate_multi_position,
    derive_pleat_count,
    explicit_accessories,
    margin_for_open_count,
    aggregate_by_fabric,
    build_quote,
)

#: 仓根（tests/ → ai-agent-service/ → backend/ → 仓根），与既有测试同惯例
REPO_ROOT = Path(__file__).resolve().parents[3]
QUOTE_RULES_DOC = REPO_ROOT / "docs" / "curtain-fabric-quote-rules.md"


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
    加工费 = 6.6 × 8 = 52.8        （按米打包，**已含罗马圈等辅料**，issue #3005/#4118）
    辅料费 = 孔带 6.6×8=52.8 + 罗马杆 3.4×25=85 + 绑带 15 = 152.8
    安装费 = 3.4 × 18 = 61.2
    总价 = 198 + 52.8 + 152.8 + 61.2 = 464.8

    ⚠️ 本条曾断言 `60 + 52.8 + 85 + 15` / 总价 `524.8`（罗马圈 40×1.5=60 由米数推导）
    —— 那是 issue #4118 ② 的「单测反向锚定偏离值」，已按 #3005 口径改正。
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
    # 辅料：孔带 52.8 + 罗马杆 85 + 绑带 15（罗马圈不进默认项 —— 见 TestAccessoryCaliber）
    assert quote["accessory_cost"] == pytest.approx(52.8 + 85 + 15)
    assert quote["install_cost"] == pytest.approx(61.2)
    assert quote["total"] == pytest.approx(198 + 52.8 + 152.8 + 61.2)


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

    async def test_tool_execute_craft_tier_economy(self, sample_tool_context):
        """工艺档位经工具生效：economy 档用料少于 standard 档（报价协商，issue #3990）"""
        from app.tools.curtain_calc import CurtainCalcTool
        tool = CurtainCalcTool()
        standard = await tool.execute(
            context=sample_tool_context,
            window_width=6.6, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8,
            open_count=2, craft_tier="standard",
        )
        economy = await tool.execute(
            context=sample_tool_context,
            window_width=6.6, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8,
            open_count=2, craft_tier="economy",
        )
        assert standard.success and economy.success
        assert economy.data["fabric_meters"] < standard.data["fabric_meters"]
        assert economy.data["craft_tier"] == "economy"
        assert standard.data["craft_tier"] == "standard"

    async def test_tool_execute_pleat_customer_quoted(self, sample_tool_context):
        """客户自报折数经工具生效：48 折双开 → 12.3 米且来源标记 customer_quoted（issue #3990）

        同时守 ④：工具响应里必须**能读到实际褶倍**（卡片载荷 = 本响应原样，见 chat.py 的
        `curtain_calc → quotation` 映射）—— 否则前端只能拿理论值渲染（issue #4118 ④）。
        """
        from app.tools.curtain_calc import CurtainCalcTool
        tool = CurtainCalcTool()
        result = await tool.execute(
            context=sample_tool_context,
            window_width=6.6, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8,
            open_count=2, pleat_count=48, source="customer_quoted",
        )
        assert result.success is True, f"折数法应成功: error={result.error}"
        assert result.data["pleat_count"] == 48
        assert result.data["fabric_meters"] == 12.3
        assert result.data["source"] == "customer_quoted"
        assert result.data["per_panel_pleats"] == 24
        assert result.data["fullness_actual"] == 1.86, (
            f"工具响应缺实际褶倍 ⇒ 报价卡只能显示理论值 2 倍，实际 {result.data.get('fullness_actual')!r}"
        )

    async def test_tool_execute_open_count_default_single(self, sample_tool_context):
        """open_count 默认单开（余量 0.2）"""
        from app.tools.curtain_calc import CurtainCalcTool
        tool = CurtainCalcTool()
        result = await tool.execute(
            context=sample_tool_context,
            window_width=5.0, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8,
            pleat_count=20,
        )
        assert result.success is True
        assert result.data["open_count"] == 1
        assert result.data["fabric_meters"] == 0.25 * 20 + 0.2


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


# ══════════════════════════════════════════════
# 实际褶倍透传（issue #4118 ④）：算了就丢 → 透传进响应，且与理论值语义分开
#
# 病根：`calculate_fabric_by_pleats` 第 184 行算出 `info["fullness_actual"]`，
# 但 `build_quote` 的 `pleat_fields` 不含它 ⇒ 响应里只有档位**理论**倍数 `fullness`，
# 前端卡片照它渲染 ⇒ 客户自报 48 折（实际用料 12.3÷6.6 = 1.86 倍）时显示「2 倍褶皱」。
# 治法：`fullness_actual` 随折数法一起透传；`fullness` 的既有语义（档位/款式理论倍数）**不改**。
# ══════════════════════════════════════════════

class TestFullnessActualPassthrough:
    """折数法必须同时给出理论倍数与实际倍数，二者不得互相顶替。"""

    @staticmethod
    def _customer_quoted_48_folds():
        """行业实证场景：6.6m 窗、韩褶双开、客户自报 48 折（issue 正文红证用例）。"""
        return build_quote(
            window_width=6.6, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8,
            pleat_count=48, open_count=2, source="customer_quoted",
        )

    def test_customer_quoted_48_folds_exposes_actual_fullness(self):
        """客户自报 48 折：响应里必须**能读到实际褶倍 1.86**（≠ 档位理论值 2.0）。"""
        q = self._customer_quoted_48_folds()
        assert q["fabric_meters"] == 12.3
        assert q["fullness"] == 2.0, "fullness 仍是档位/款式理论倍数（既有契约不得改义）"
        assert q["fullness_actual"] == 1.86, (
            f"实际褶倍（12.3÷6.6=1.86）必须透传进响应，实际拿到 {q.get('fullness_actual')!r}"
            " —— 算了就丢 ⇒ 卡片只能拿理论值骗顾客"
        )
        assert q["fullness_actual"] != q["fullness"], "理论值≠实际值时两者必须可分辨"

    def test_theory_value_tracks_tier_while_actual_tracks_meters(self):
        """档位理论值随档位走、实际值随用料走 —— 两个数不是一回事。"""
        kwargs = dict(
            window_width=6.6, window_height=2.6, mounting="s_hook",
            fabric_width=3.2, fabric_price=23.8, open_count=2,
        )
        std = build_quote(**kwargs, craft_tier="standard")
        eco = build_quote(**kwargs, craft_tier="economy")
        assert (std["fullness"], eco["fullness"]) == (2.0, 1.8), (
            "理论倍数 = 档位名义值（standard 2.0 / economy 1.8），语义不变"
        )
        # standard 52 折 → 13.3m → 2.02 倍；economy 46 折 → 11.8m → 1.79 倍
        assert std["fullness_actual"] == 2.02
        assert eco["fullness_actual"] == 1.79
        assert std["fullness_actual"] != std["fullness"], "标准档实际值也非名义值（13.3÷6.6=2.02）"

    def test_multiple_method_quote_has_no_actual_fullness(self):
        """倍数法没有「折数法反算」这一项 ⇒ 不得编造 `fullness_actual`（fail-closed）。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert q["fullness"] == 2.0
        assert "fullness_actual" not in q, (
            "倍数法响应里出现 fullness_actual = 给顾客一个没人算过的数（编造）"
        )

    def test_card_consumes_the_same_field_name(self):
        """字段名单点：响应键必须被报价卡消费 —— 否则「后端透传了」与「卡片渲染了」各自绿，
        合起来仍是「算了就丢」（跨模块契约，issue #4118 ④ 的前端半边）。"""
        card = (
            REPO_ROOT / "frontend" / "mini-app" / "src" / "components" / "cards" / "QuotationCard.tsx"
        )
        assert card.is_file(), f"报价卡路径不存在：{card}（路径变更须同步本锚点）"
        assert "fullness_actual" in card.read_text(encoding="utf-8"), (
            f"{card} 未消费响应键 `fullness_actual` ⇒ 卡片只能拿理论值 `fullness` 渲染"
        )


# ══════════════════════════════════════════════
# 默认档**静默**回落 ⇒ 显式告警（issue #4118 ⑤-B）
#
# 病根：韩褶（s_hook）折数法只在**显式**传 `craft_tier` / `pleat_count` 时生效
# （`pleat_mode` 判据在 `build_quote` 内），两者都缺 ⇒ **静默**回落倍数法
# （回落分支的 `warning` 为空）。实测 6.6m 窗 / 2.6m 高 / 双开 / 3.2m 门幅：
# 标准档折数法 **13.3 米（52 折）** vs 倍数法 **13.8 米**，差 0.5 米**且无任何告警**。
# 治法：回落分支**也**返回显式 `warning`（说明按倍数法计价、非标准档折数法）。
# ⚠️ 铁律：**数值一个字都不能变**（13.8 仍是 13.8）——本项治的是**静默**，不是数值。
# 「按 §9 接线默认标准档（13.8→13.3）」= 改既有报价口径 = 改钱，**不在本包**（转客户提问项）。
# ══════════════════════════════════════════════

class TestDefaultTierFallbackWarning:
    """漏传档位/折数时的倍数法回落必须**显式告警**，且数值逐值不变。"""

    #: ⑤-B 红证场景（与文档 §9 待裁定条目的实测场景一致）
    FALLBACK = dict(
        window_width=6.6, window_height=2.6, mounting="s_hook",
        open_count=2, fabric_width=3.2, fabric_price=50.0,
    )

    def test_fallback_to_multiplier_method_is_not_silent(self):
        """★红证①：漏传 `craft_tier`/`pleat_count` ⇒ 倍数法回落的 `warning` **必须非空**。

        改前形态：回落分支返回 `warning=""` ⇒ 顾客拿到的是倍数法的数（13.8 米），
        却**没有任何信号**说明它不等于标准档折数法（13.3 米）——「静默」就是本项的缺陷。
        """
        q = build_quote(**self.FALLBACK)
        assert q["formula_used"] == "fixed_height", (
            f"前提：漏传档位时走的应是倍数法，实际 formula_used={q['formula_used']!r}"
        )
        assert q["warning"], (
            "漏传档位/折数时**静默**走倍数法（warning 为空）—— 同一单与标准档折数法差 0.5 米"
            "却无任何告警（issue #4118 ⑤-B）"
        )
        assert "倍数法" in q["warning"], f"告警须点名本次口径是倍数法：{q['warning']!r}"
        assert "craft_tier" in q["warning"] and "pleat_count" in q["warning"], (
            f"告警须给出补救入口（传 craft_tier 或 pleat_count）：{q['warning']!r}"
        )

    def test_fallback_values_are_byte_for_byte_unchanged(self):
        """★红证②（防顺手改数）：回落分支**逐值**与改前相同，且 ≠ 标准档折数法。

        本项只补告警、**不动数值**：13.8 仍是 13.8（标准档折数法 13.3 是**另一个**口径，
        改它 = 改钱 ⇒ 不在本包）。任何"顺手把默认值接成标准档"的实现都会在此变红。
        """
        q = build_quote(**self.FALLBACK)
        assert {
            "fabric_meters": q["fabric_meters"],
            "fabric_cost": q["fabric_cost"],
            "processing_cost": q["processing_cost"],
            "accessory_cost": q["accessory_cost"],
            "install_cost": q["install_cost"],
            "total": q["total"],
            "fullness": q["fullness"],
            "formula_used": q["formula_used"],
        } == {
            "fabric_meters": 13.8, "fabric_cost": 690.0, "processing_cost": 138.0,
            "accessory_cost": 0.0, "install_cost": 126.0, "total": 954.0,
            "fullness": 2.0, "formula_used": "fixed_height",
        }, f"回落分支的数值被改动了（本项只治静默、不改钱）：{q}"
        assert "pleat_count" not in q and "fullness_actual" not in q, (
            "回落仍是倍数法 ⇒ 不得凭空长出折数字段（否则卡片会渲染一个没人算过的折数）"
        )
        # 对照：标准档折数法确实是**另一个**数（若两法同值，本告警无意义）
        std = build_quote(**self.FALLBACK, craft_tier="standard")
        assert (std["fabric_meters"], std["pleat_count"]) == (13.3, 52)
        assert std["warning"] == "", "显式传档位 ⇒ 折数法，不该有「回落」告警"
        assert q["fabric_meters"] != std["fabric_meters"]

    def test_no_false_alarm_when_method_is_explicit_or_not_applicable(self):
        """防噪音告警：非韩褶（倍数法本就是本口径）与显式传档位/折数 ⇒ 不得报「回落」。"""
        eyelet = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert eyelet["warning"] == "", "打孔帘走倍数法是本口径，不是「回落」"
        assert build_quote(**self.FALLBACK, craft_tier="standard")["warning"] == ""
        assert build_quote(**self.FALLBACK, craft_tier="economy")["warning"] == ""
        assert build_quote(
            **self.FALLBACK, pleat_count=48, source="customer_quoted",
        )["warning"] == "", "顾客自报折数 ⇒ 折数法，不是「回落」"


# ══════════════════════════════════════════════
# 辅料口径（issue #4118，以 #3005 为准）：**不推导、只显式**
#
# 病根：`ring_count = round(meters * ROMAN_RING_PER_METER)` 由米数推导罗马圈个数并单列费用，
# 而 §5 计价口径明令「罗马圈…不参与系统数量推导」（8 元/米加工费已含圈）
# ⇒ 同一单两种算法并存（加工费 8 元/米 + 单收 60 元圈费）。
# 治法：删掉推导与「每米 N 个」密度；顾客**显式**要单独买 ⇒ 走 accessories 显式入参。
# ══════════════════════════════════════════════

class TestAccessoryCaliber:
    """默认报价里**不得**出现按「个」的推导项；显式入参才计入。"""

    def test_no_ring_density_constants(self):
        """「每米布 N 个」密度常量必须不存在 —— 留着它就会再长出推导（#3005 无密度口径）。"""
        assert not hasattr(curtain_calc_module, "ROMAN_RING_PER_METER"), (
            "罗马圈密度常量又回来了 —— 它会诱使 `round(meters * density)` 式推导（违反 §5）"
        )
        assert not hasattr(curtain_calc_module, "ROMAN_RING_PRICE")

    def test_eyelet_default_breakdown_has_no_per_piece_item(self):
        """★红证①：把 `round(meters * ROMAN_RING_PER_METER)` 的圈费加回默认报价 ⇒ 本断言红。"""
        quote = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert [b["name"] for b in quote["breakdown"]] == [
            "面料", "加工费", "孔带", "罗马杆", "绑带", "安装费",
        ]
        assert [b["name"] for b in quote["breakdown"] if "个" in b["detail"]] == []
        assert quote["accessory_cost"] == pytest.approx(152.8)
        assert quote["total"] == pytest.approx(464.8)

    def test_more_meters_never_adds_a_per_piece_item(self):
        """米数变多（窗更宽）只让「孔带」按米变贵，**不**冒出按个的项。"""
        small = build_quote(window_width=1.0, window_height=2.5, mounting="eyelet",
                            fabric_width=2.8, fabric_price=30.0)
        big = build_quote(window_width=5.0, window_height=2.5, mounting="eyelet",
                          fabric_width=2.8, fabric_price=30.0)
        assert big["fabric_meters"] > small["fabric_meters"]
        assert big["accessory_cost"] > small["accessory_cost"]        # 孔带按米涨（真实项）
        for q in (small, big):
            assert [b["name"] for b in q["breakdown"] if "个" in b["detail"]] == []

    def test_explicit_accessories_counted_verbatim(self):
        """顾客显式单独买罗马圈（40 个 × 1.5 元）⇒ 原样计入，数量/单价都不许被"优化"。"""
        quote = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
            accessories=[{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}],
        )
        ring = [b for b in quote["breakdown"] if b["name"] == "罗马圈"]
        assert len(ring) == 1, f"显式辅料必须出现在明细里：{quote['breakdown']}"
        assert ring[0]["detail"] == "40个 × ¥1.5/个"
        assert ring[0]["cost"] == pytest.approx(60.0)
        assert quote["accessory_cost"] == pytest.approx(152.8 + 60.0)
        assert quote["total"] == pytest.approx(464.8 + 60.0)

    def test_default_and_explicit_quotes_differ_only_by_the_explicit_line(self):
        """同一算例：不给 accessories 与给 40 个圈的**差**必须恰好等于显式那一项（不推导的判据）。"""
        base = build_quote(window_width=3.0, window_height=2.7, mounting="eyelet",
                           fabric_width=3.0, fabric_price=30.0)
        with_ring = build_quote(window_width=3.0, window_height=2.7, mounting="eyelet",
                                fabric_width=3.0, fabric_price=30.0,
                                accessories=[{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}])
        assert with_ring["total"] - base["total"] == pytest.approx(60.0)

    def test_explicit_accessory_unit_defaults_to_piece(self):
        """unit 缺省 = 「个」；给 unit 则照用（辅料单位不猜成米）。"""
        rows, total = explicit_accessories([{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}])
        assert rows[0]["detail"] == "40个 × ¥1.5/个"
        assert total == pytest.approx(60.0)

    @pytest.mark.parametrize("bad", [
        {"name": "罗马圈"},                                       # 缺数量与单价
        {"quantity": 40, "unit_price": 1.5},                      # 缺名称
        {"name": "罗马圈", "quantity": 0, "unit_price": 1.5},       # 数量非正
        {"name": "罗马圈", "quantity": 40, "unit_price": -1.0},     # 单价为负
        {"name": "罗马圈", "quantity": "一堆", "unit_price": 1.5},  # 数量非数
        "罗马圈 40 个",                                            # 不是对象
    ])
    def test_malformed_accessories_rejected(self, bad):
        """fail-closed：缺项/非法值一律 **拒绝** —— 不猜默认、不静默丢弃顾客的显式选择。"""
        with pytest.raises(ValueError):
            build_quote(
                window_width=3.0, window_height=2.7, mounting="eyelet",
                fabric_width=3.0, fabric_price=30.0, accessories=[bad],
            )

    def test_multi_position_passes_explicit_accessories_through(self):
        """多部位批量不得静默丢掉显式辅料（`positions[i].accessories` 必须落到该部位报价）。"""
        res = calculate_multi_position([{
            "window_width": 3.0, "window_height": 2.7, "mounting": "eyelet",
            "fabric_width": 3.0, "fabric_price": 30.0, "fabric_code": "2698-11",
            "accessories": [{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}],
        }])
        assert res["positions"][0]["accessory_cost"] == pytest.approx(152.8 + 60.0)


class TestCurtainCalcAccessoryCaliberTool:
    """工具层（LLM 实际走的那条路）：schema 声明、传参生效、非法入参给出可自纠的原因。"""

    def test_schema_and_description_declare_explicit_only(self):
        from app.tools.curtain_calc import CurtainCalcTool
        props = CurtainCalcTool.parameters["properties"]
        assert "accessories" in props, "不给显式入口 ⇒ 顾客的显式选择无处表达（只能被推导）"
        assert props["accessories"]["items"]["required"] == ["name", "quantity", "unit_price"]
        desc = CurtainCalcTool.description
        assert "已含在按米单价里" in desc, "描述必须说明加工费已含辅料（否则模型仍会单列）"
        assert "不要" in desc and "推算辅料个数" in desc, "描述必须明令不得按米数推算辅料个数"

    async def test_tool_default_quote_has_no_ring(self, sample_tool_context):
        """★红证①（工具层）：推导复活 ⇒ message/明细里出现「罗马圈 40个」。"""
        from app.tools.curtain_calc import CurtainCalcTool
        result = await CurtainCalcTool().execute(
            context=sample_tool_context, window_width=3.0, window_height=2.7,
            mounting="eyelet", fabric_width=3.0, fabric_price=30.0,
        )
        assert result.success is True, f"报价应成功: error={result.error}"
        assert "罗马圈" not in str(result.data["breakdown"])
        assert result.data["total"] == pytest.approx(464.8)

    async def test_tool_applies_explicit_accessories(self, sample_tool_context):
        from app.tools.curtain_calc import CurtainCalcTool
        result = await CurtainCalcTool().execute(
            context=sample_tool_context, window_width=3.0, window_height=2.7,
            mounting="eyelet", fabric_width=3.0, fabric_price=30.0,
            accessories=[{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}],
        )
        assert result.success is True, f"显式辅料应被接受: error={result.error}"
        assert result.data["total"] == pytest.approx(524.8)
        assert "罗马圈" in str(result.data["breakdown"])

    async def test_tool_rejects_malformed_accessory_with_reason(self, sample_tool_context):
        """非法显式辅料 → 明确失败 + 原因回给模型（不落成笼统的「算料失败」）。"""
        from app.tools.curtain_calc import CurtainCalcTool
        result = await CurtainCalcTool().execute(
            context=sample_tool_context, window_width=3.0, window_height=2.7,
            mounting="eyelet", fabric_width=3.0, fabric_price=30.0,
            accessories=[{"name": "罗马圈"}],
        )
        assert result.success is False
        assert "罗马圈" in (result.message or ""), f"必须指出是哪项辅料: {result.message}"
        assert "quantity" in (result.message or "")
        assert result.suggestion


# ══════════════════════════════════════════════
# 文档算例锚定（issue #4118 ②）：真值源必须算得出自己写的数
#
# 病根：§7 算例写「总价 ≈ 505 元」，代码算出 524.8，单测还反向锚定了 524.8；
# 全仓 `505` 零命中 ⇒ 文档与实现**永久漂移且无人发现**。
# 治法：§7 的每个数值都做成锚点，断言 = 代码逐值复现；改文档任一个数 ⇒ 本类变红。
# ══════════════════════════════════════════════

class TestDocExampleAnchor:
    """`docs/curtain-fabric-quote-rules.md` §7 ↔ `build_quote` 逐值一致。"""

    @staticmethod
    def _section7() -> str:
        doc = QUOTE_RULES_DOC.read_text(encoding="utf-8")
        m = re.search(r"^## 7\..*?(?=^## 8\.)", doc, re.S | re.M)
        assert m, (
            f"{QUOTE_RULES_DOC} 里找不到 §7 算例小节（被改写/删除？）—— "
            "文档改写必须同步本锚点，禁止让判据静默失效"
        )
        return m.group(0)

    @staticmethod
    def _anchored(section: str, pattern: str, what: str) -> float:
        m = re.search(pattern, section)
        assert m, f"§7 里找不到「{what}」的锚点数值（期望形态：{pattern}）—— 文档改写后须同步本锚点"
        return float(m.group(1))

    def test_section7_example_matches_code(self):
        """§7 主算例（3m×2.7m / 3.0m 定高布 / 2 倍褶 / 打孔 / 30 元每米）逐值对齐代码输出。"""
        section = self._section7()
        quote = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        anchors = {
            "面料米数": (r"\*\*面料\*\*[^\n]*=\s*([\d.]+)m", quote["fabric_meters"]),
            "面料费": (r"\*\*面料费\*\*[^\n]*=\s*([\d.]+) 元", quote["fabric_cost"]),
            "加工费": (r"\*\*加工费\*\*[^\n]*=\s*([\d.]+) 元", quote["processing_cost"]),
            "辅料费": (r"\*\*辅料费\*\*[^\n]*=\s*([\d.]+) 元", quote["accessory_cost"]),
            "安装费": (r"\*\*安装费\*\*[^\n]*=\s*([\d.]+) 元", quote["install_cost"]),
            "总价": (r"\*\*总价\*\*[^\n]*=\s*\*\*([\d.]+) 元\*\*", quote["total"]),
        }
        for what, (pattern, expected) in anchors.items():
            assert self._anchored(section, pattern, what) == pytest.approx(expected), (
                f"§7 算例的「{what}」与代码输出不一致（文档锚点值取自文档，代码 = {expected}）"
            )
        assert self._anchored(section, r"≈\s*([\d.]+) 元/㎡", "折合窗面积单价") == pytest.approx(
            round(quote["total"] / (3.0 * 2.7), 1)
        )

    def test_section7_explicit_ring_variant_matches_code(self):
        """§7 第 7 条（显式买圈）：加价与总价可复现，且**只在**显式入参下出现。"""
        section = self._section7()
        m = re.search(r"单独买罗马圈[^\n]*?([\d.]+) 元，总价 \*\*([\d.]+) 元\*\*", section)
        assert m, "§7 找不到「显式买罗马圈」的加价/总价锚点 —— 文档改写后须同步本锚点"
        quoted_adder, quoted_total = float(m.group(1)), float(m.group(2))
        with_ring = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
            accessories=[{"name": "罗马圈", "quantity": 40, "unit_price": 1.5}],
        )
        base = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert quoted_adder == pytest.approx(with_ring["total"] - base["total"])
        assert quoted_total == pytest.approx(with_ring["total"])
        assert "罗马圈" not in [b["name"] for b in base["breakdown"]], (
            "文档承诺「不推导」⇒ 不给显式入参时明细里不得出现罗马圈"
        )

    def test_section5_caliber_states_no_derivation(self):
        """§5 计价口径（本单裁定的依据）必须仍在文档里 —— 锚点被删则判据失去依据。"""
        doc = QUOTE_RULES_DOC.read_text(encoding="utf-8")
        assert "不参与系统数量推导" in doc
        assert "accessories" in doc and "显式入参" in doc


class TestCraftSpecOutput:
    """工艺规格输出（issue #4346，包 1 · Python 生产端）

    设计：`docs/design/order-craft-spec-design.md` §4.9（报价单与落库「同源」）/ §6.1（米数拆两个）。
    目的：`curtain_calc` 的输出**就是**将来落进 `order_items.processing_info` 的那一份 craft spec ——
    报价卡直接渲染它、`order_create` 把同一个 dict 落库，**不重新拼装、不二次推导**。
    """

    CRAFT_KEYS = ("curtain_type", "craft", "is_shaped", "style", "special_options")

    def test_echoes_craft_spec_fields(self):
        """传入的工艺字段必须**原样回显**（不推导、不补默认值）。"""
        q = build_quote(
            window_width=3.0,
            window_height=2.7,
            fabric_price=30.0,
            curtain_type="纱帘",
            craft="打孔",
            is_shaped=False,
            style="拼色",
            special_options=["拼2次", "加铅块"],
        )
        assert q["curtain_type"] == "纱帘"
        assert q["craft"] == "打孔"
        assert q["is_shaped"] is False
        assert q["style"] == "拼色"
        assert q["special_options"] == ["拼2次", "加铅块"]

    def test_craft_spec_defaults_are_none_not_invented(self):
        """不传 ⇒ 键存在但为 `None` —— **不得替顾客发明部位/工艺**（口径纪律）。"""
        q = build_quote(window_width=3.0, window_height=2.7)
        for key in self.CRAFT_KEYS:
            assert key in q, f"craft spec 键 {key} 缺失（契约要求键恒在）"
            assert q[key] is None, f"{key} 非 None ⇒ 替顾客发明了默认值"

    def test_processing_meters_splits_from_fabric_meters(self):
        """§6.1 已裁定：米数拆两个字段；**单面料行时两值恒等**（现有单金额不变）。"""
        q = build_quote(window_width=3.0, window_height=2.7, fabric_price=30.0)
        assert "processing_meters" in q, "§6.1 要求输出 processing_meters"
        assert q["processing_meters"] == q["fabric_meters"]

    def test_split_does_not_change_existing_amounts(self):
        """**回归护栏**：拆字段不得改任何一个数值（现有单金额一字不变）。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert q["fabric_meters"] == pytest.approx(6.6)          # 文档 §7 算例锚定
        assert q["processing_meters"] == pytest.approx(6.6)
        assert q["total"] == pytest.approx(464.8)                # 文档 §7 算例锚定

    def test_open_count_and_pleats_are_usable_as_craft_spec(self):
        """**回归护栏**：打开方式/折数/每片折数已是既有输出 ⇒ 直接当 craft spec 用，不新增重复键。"""
        q = build_quote(
            window_width=6.6, window_height=2.92, mounting="s_hook",
            pleat_count=48, open_count=2,
        )
        assert q["open_count"] == 2
        assert q["pleat_count"] == 48
        assert q["per_panel_pleats"] == 24                       # 文档 §11 算例（48 折双开）

    def test_formula_used_is_the_cutting_mode_truth(self):
        """**回归护栏**：加工类型（定高买宽/定宽买高）的算料侧真值 = `formula_used`，不新增重复字段。"""
        assert build_quote(window_width=3.0, window_height=2.7,
                           fabric_width=3.0)["formula_used"] == "fixed_height"
        assert build_quote(window_width=3.0, window_height=2.7,
                           fabric_width=2.8)["formula_used"] == "fixed_width"


class TestCraftSpecToolPassthrough:
    """Tool 层：工艺规格必须**穿过 execute** 落到 `data` —— 否则 LLM 传了也白传。"""

    async def test_execute_passes_craft_spec_through(self, sample_tool_context):
        """execute → data 透传（含 §6.1 的米数拆两个字段）。"""
        from app.tools.curtain_calc import CurtainCalcTool

        result = await CurtainCalcTool().execute(
            context=sample_tool_context,
            window_width=3.0,
            window_height=2.7,
            fabric_price=30.0,
            curtain_type="纱帘",
            craft="打孔",
            is_shaped=False,
            style="拼色",
            special_options=["拼2次"],
        )
        assert result.success is True
        data = result.data
        assert data["curtain_type"] == "纱帘"
        assert data["craft"] == "打孔"
        assert data["is_shaped"] is False
        assert data["style"] == "拼色"
        assert data["special_options"] == ["拼2次"]
        assert data["processing_meters"] == data["fabric_meters"]

    def test_schema_declares_craft_spec_params(self):
        """schema 必须**声明**这些参数 —— 未声明则 LLM 传不进来（等于没实现）。"""
        from app.tools.curtain_calc import CurtainCalcTool

        props = CurtainCalcTool.parameters["properties"]
        for key in ("curtain_type", "craft", "is_shaped", "style", "special_options"):
            assert key in props, f"schema 缺 {key} ⇒ LLM 无法传该字段"
        assert props["craft"]["enum"] == ["韩褶", "打孔", "四爪钩", "穿杆", "平幔"], (
            "craft 枚举必须与工序库 production_routings.craft 逐字一致"
        )
        assert props["curtain_type"]["enum"] == ["布帘", "纱帘", "帘头"]


# ══════════════════════════════════════════════
# 幅数输出（issue #4374 · 交付物 3 / 设计文档 §4.3）
#
# 病根：`panels`（幅数）在 `calculate_fabric_meters` / `build_quote` 的 `fixed_width*`
# 分支里**只是局部变量**（只进告警文案），从不进返回值 ⇒ 报价卡「幅数」行**永不出现**
# （包 3 已登记该缺口），加工单快照的 `panels` 也永远取不到。
# 治法：把**已经算出来的那个数**透传出去 —— 只加键、不改任何金额/米数（本单不改钱）。
# ⚠️ 不发明数字：只有真的算了幅数（定宽买高）才有该键；定高买宽按宽买米、幅数无定义
# ⇒ **键缺席**（不得补 0，也不得补 1 冒充「1 幅」）。
# ══════════════════════════════════════════════

class TestPanelsOutput:
    """`build_quote` 必须透传幅数 `panels`（定宽买高时 = 幅数）。"""

    def test_fixed_width_quote_exposes_panels(self):
        """定宽买高（成品高超门幅定高上限）⇒ 输出含 `panels`，且与幅数公式一致。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=2.8, fabric_price=30.0,
        )
        assert q["formula_used"] == "fixed_width"
        expected = math.ceil((3.0 + 0.3) * 2.0 / 2.8)     # ceil((W+0.3)×N/G)
        assert q["panels"] == expected, (
            f"定宽买高的幅数未透传（期望 {expected}，输出 {q.get('panels')}）⇒ 报价卡「幅数」行永不出现"
        )

    def test_pattern_quote_panels_matches_meters(self):
        """对花只加**每幅长度**，不加幅数 —— `panels` 必须与米数口径自洽。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=2.8, fabric_price=30.0,
            has_pattern=True, pattern_repeat=0.5,
        )
        assert q["panels"] == math.ceil((3.0 + 0.3) * 2.0 / 2.8)
        assert q["fabric_meters"] == pytest.approx(q["panels"] * (2.7 + 0.3 + 0.5))

    def test_pleat_mode_fixed_width_exposes_panels(self):
        """折数法下成品高超限 ⇒ 走 `fixed_width_pleats`，幅数同样必须透传。

        期望值按同一公式独立算出：折数法用料（0.25×折数 + 余量）÷ 门幅 向上取整。
        """
        q = build_quote(
            window_width=6.6, window_height=2.92, mounting="s_hook",
            fabric_width=2.8, fabric_price=30.0, pleat_count=48, open_count=2,
        )
        assert q["formula_used"] == "fixed_width_pleats"
        pleat_meters = round(0.25 * 48 + 0.3, 2)             # 折数法用料（双开余量 0.3）
        assert q["panels"] == math.ceil(pleat_meters / 2.8)
        assert q["fabric_meters"] == pytest.approx(q["panels"] * (2.92 + 0.3))

    def test_panels_absent_when_not_computed(self):
        """定高买宽（按宽买米）幅数**无定义** ⇒ 键缺席（不得补 0/1 发明数字）。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=3.0, fabric_price=30.0,
        )
        assert q["formula_used"] == "fixed_height"
        assert "panels" not in q, (
            f"定高买宽不得造幅数（口径：不发明数字）—— 实得 panels={q.get('panels')}"
        )

    def test_panels_addition_does_not_change_amounts(self):
        """**回归护栏**：补 `panels` 不得动任何一个金额/米数（本单不改钱）。"""
        q = build_quote(
            window_width=3.0, window_height=2.7, mounting="eyelet",
            fabric_width=2.8, fabric_price=30.0,
        )
        assert q["fabric_meters"] == pytest.approx(9.0)      # 修前既有值（逐值不变）
        assert q["processing_meters"] == pytest.approx(9.0)
        assert q["total"] == pytest.approx(575.2)            # 修前既有值（逐值不变）

    def test_panels_never_defaults_to_zero(self):
        """负例护栏：任何分支都不得把 `panels` 兜底成 0（0 幅 = 无意义数字）。"""
        for kwargs in (
            {"window_width": 3.0, "window_height": 2.7, "fabric_width": 3.0},
            {"window_width": 3.0, "window_height": 2.7, "fabric_width": 2.8},
        ):
            q = build_quote(fabric_price=30.0, **kwargs)
            assert q.get("panels") != 0, f"幅数被兜底成 0：{kwargs}"

    async def test_execute_passes_panels_through(self, sample_tool_context):
        """Tool 层：幅数必须**穿过 execute** 落到 `data` —— 否则 LLM 拿不到、订单也落不了库。"""
        from app.tools.curtain_calc import CurtainCalcTool

        result = await CurtainCalcTool().execute(
            context=sample_tool_context,
            window_width=3.0, window_height=2.7,
            fabric_width=2.8, fabric_price=30.0,
        )
        assert result.success is True
        assert result.data["panels"] == math.ceil((3.0 + 0.3) * 2.0 / 2.8)
