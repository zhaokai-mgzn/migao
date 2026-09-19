"""算料公式选择 + 向上进位 + 可注入配置（issue #4527）。

用户 2026-09-19 裁定（逐字）：

> 「算出来的用料还要根据打开方式*系数，单开系数1，双开系数2，以此类推，最后用料米数保留一位小数，
> 除了使用韩折公式还有一种褶倍数计算公式，这都是用料计算方法，你得根据用户要求选择不同的计算公式，
> 默认用韩折的」

口径（三问澄清答复）：**乙** —— 公式吃「**每片宽**」（成品宽 ÷ 开数），**总用料 = 每片用料 × 开数**；
一位小数 = **向上进位**（`ceil(x*10)/10`）。公式入参 `formula`：`'pleat'`（韩折公式＝折数法，**默认**）｜
`'fullness'`（褶倍数公式＝倍数法）。

**ERP 实证锚点（不得违反，防口径漂移）**：加工单 `CSO260915-02615`（#4343 已取证）宽 5.5m / 双开 /
理论褶倍 2.00 ⇒ 操作记录每道工序 **11.00 米**，即 `5.5 × 2.00 = 11.00` ⇒ **双开不得把总宽再乘 2**
（「甲」口径会算成 22.00 米，差一倍、直接进订单金额，已被用户否决）。

红证（实现前，逐条）：
- 本文件 `from app.tools.curtain_calc import DEFAULT_CRAFT_CALC_CONFIG, ...` ⇒ **ImportError**
  （这些名字尚不存在）；
- 即使绕过 import 用模块属性访问：`build_quote(..., formula="fullness")` ⇒ **TypeError:
  unexpected keyword argument 'formula'**；
- 进位判据：`meters_rounding_step` 不存在 ⇒ 同上；改成截断 / 四舍五入 ⇒ 值级断言红
  （如 `x.05` 截断 6.3 / 四舍五入 6.3，而期望 6.4）；
- 逐片判据：现有实现按「总折数 × 每折吃布 + 余量」算，**每片用料 × 开数** 无法表达 ⇒ 红。

判据与实现**不共源**：期望值全部**写死**（纸表 + ERP 锚点 + 手算），**不得**从实现推导
（`X == X` 的断言不会红）。
"""

# case_ids: OR-041

import pytest

from app.tools import curtain_calc
from app.tools.curtain_calc import (
    DEFAULT_CRAFT_CALC_CONFIG,
    DEFAULT_CRAFT_TIERS,
    DEFAULT_FULLNESS,
    FORMULA_FULLNESS,
    FORMULA_PLEAT,
    build_quote,
    ceil_to_step,
    resolve_craft_calc_config,
    resolve_craft_rule,
)

# ── 冻结入参（两个公式共用同一组宽/开数，便于逐值对照）──
# `craft_tier="standard"`：折数法（韩折公式）由「显式档位 / 显式折数」触发（既有口径，issue #4118 ⑤-B）
# —— 本包**不动**这条触发条件，只在其上叠加 `formula` 选择。
ANCHOR = dict(window_width=5.5, window_height=2.5, mounting="s_hook",
              fabric_width=3.2, fabric_price=30.0, open_count=2, craft_tier="standard")
DOUBLE_6_6 = dict(window_width=6.6, window_height=2.5, mounting="s_hook",
                  fabric_width=3.2, fabric_price=30.0, open_count=2, craft_tier="standard")
SINGLE_6_6 = {**DOUBLE_6_6, "open_count": 1}


# ══════════════════════════════════════════════════════════════════════════
# 判据 1（ERP 实证锚点）：5.5m / 双开 / 褶倍 2.0 / formula='fullness' ⇒ 11.0 米
# ══════════════════════════════════════════════════════════════════════════

class TestErpAnchorFullness:
    """ERP 加工单 CSO260915-02615（#4343 取证）：每道工序 11.00 米 = 5.5 × 2.00。"""

    def test_erp_anchor_is_eleven_point_zero(self):
        """`5.5 × 2.00 = 11.00` ⇒ 用料必须是 **11.0**（22.0 ⇒ 红：那是「总宽再×开数」的甲口径）。"""
        q = build_quote(formula="fullness", **ANCHOR)
        assert q["fabric_meters"] == 11.0

    def test_erp_anchor_not_doubled_by_open_count(self):
        """同一成品宽下把开数当系数**再乘一遍**会得 22.0 —— 显式反证（差一倍直接进订单金额）。"""
        q = build_quote(formula="fullness", **ANCHOR)
        assert q["fabric_meters"] != 22.0

    def test_erp_anchor_is_a_whole_tenth(self):
        """11.00 米本身已是 0.1 的整数倍 ⇒ 向上进位**不得**把它抬到 11.1（进位不得是「+0.1」）。"""
        q = build_quote(formula="fullness", **ANCHOR)
        assert q["fabric_meters"] == round(q["fabric_meters"], 1)


# ══════════════════════════════════════════════════════════════════════════
# 判据 2（逐片口径）：总用料 = 每片用料 × 开数，期望值**写死**
# ══════════════════════════════════════════════════════════════════════════

class TestPerPanelPleatFormula:
    """宽 6.6 / 双开 / 褶倍 2.0 / `formula='pleat'` ⇒ 逐片算、总用料 = 每片 × 2。

    手算（与实现无关）：
      每片宽 = 6.6 ÷ 2 = 3.3m；每片折数 = round((3.3×2.0 − 0.15) ÷ 0.25) = round(25.8) = 26；
      每片用料 = 0.25×26 + 0.15 = 6.65m；总用料 = 6.65 × 2 = **13.3m**（= 纸表 `0.25×52+0.3`，逐值不变）。
    """

    def test_per_panel_pleats_and_meters(self):
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        assert q["pleat_count"] == 52
        assert q["per_panel_pleats"] == 26
        assert q["fabric_meters"] == 13.3

    def test_total_equals_per_panel_times_open_count(self):
        """总用料 === 每片用料 × 开数（逐片口径的可执行判据）。"""
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        per_panel = 0.25 * 26 + 0.15          # 写死：0.25×每片折数 + 每片余量
        assert q["fabric_meters"] == round(per_panel * 2, 2) == 13.3

    def test_every_panel_is_identical(self):
        """逐片 ⇒ 每片折数相同（总折数 = 每片 × 开数），不得出现「两片不同」的形态。"""
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        assert q["pleat_count"] == q["per_panel_pleats"] * q["open_count"]

    def test_single_open_per_panel_is_the_whole_curtain(self):
        """单开 ⇒ 只有一片：每片折数 === 总折数，且余量取**单开** 0.2（不是 0.3）。

        手算：折数 = round((6.6×2.0 − 0.2) ÷ 0.25) = round(52.0) = 52；
        用料 = 0.25×52 + 0.2 = 13.2（恰好 0.1 格点 ⇒ 进位不动它）。
        """
        q = build_quote(formula="pleat", **SINGLE_6_6)
        assert q["open_count"] == 1
        assert q["per_panel_pleats"] == q["pleat_count"] == 52
        assert q["margin"] == 0.2
        assert q["fabric_meters"] == 13.2


# ══════════════════════════════════════════════════════════════════════════
# 判据 3（向上进位到 0.1）：截断 / 四舍五入 ⇒ 红
# ══════════════════════════════════════════════════════════════════════════

class TestCeilToOneTenth:

    def test_ceil_to_step_rounds_up_not_truncates(self):
        """`x.05` 必须进到 `x.1`（截断给 6.3、四舍五入给 6.3 ⇒ 都红）。"""
        assert ceil_to_step(6.35, 0.1) == 6.4

    def test_ceil_to_step_keeps_exact_multiples(self):
        """已经是 0.1 整数倍 ⇒ 原样（进位不得变成「恒 +0.1」）。"""
        assert ceil_to_step(11.0, 0.1) == 11.0
        assert ceil_to_step(13.3, 0.1) == 13.3

    def test_ceil_to_step_absorbs_binary_float_noise(self):
        """`2.3×10 = 22.999999999999996` 这类二进制噪声**不得**被当成「要进位」（否则纸表 12.3 → 12.4）。"""
        assert ceil_to_step(2.3 * 10, 1.0) == 23.0

    def test_fabric_meters_is_a_whole_tenth(self):
        """端到端：用料米数一律落在 0.1 的格点上（构造 x.xx5 的输入 ⇒ 进位可见）。"""
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        assert q["fabric_meters"] == 13.3
        assert abs(q["fabric_meters"] * 10 - round(q["fabric_meters"] * 10)) < 1e-6

    def test_rounding_step_is_configurable(self):
        """进位步长来自配置（商家可配）：步长 0.05 ⇒ 13.3（= 0.05 整数倍）原样。

        判别性：把步长写死在公式体内（恒 0.1）⇒ 本条红（配置不生效）。
        """
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "meters_rounding_step": 0.05}
        q = build_quote(formula="pleat", config=cfg, **DOUBLE_6_6)
        assert q["fabric_meters"] == 13.3

    def test_coarser_rounding_step_changes_the_result(self):
        """粗步长 0.5 ⇒ 13.3 向上进位到 **13.5**（证明步长真的进了公式，不是装饰参数）。"""
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "meters_rounding_step": 0.5}
        q = build_quote(formula="pleat", config=cfg, **DOUBLE_6_6)
        assert q["fabric_meters"] == 13.5


# ══════════════════════════════════════════════════════════════════════════
# 判据 4（默认公式 = 韩折）：不传 ⇒ 走折数法，且公式串写明所用公式
# ══════════════════════════════════════════════════════════════════════════

class TestDefaultFormula:

    def test_default_is_pleat(self):
        """不传 `formula` ⇒ 折数法（静默走褶倍数公式 ⇒ 红：那是「默认用韩折」的反面）。"""
        q = build_quote(**DOUBLE_6_6)
        assert q["formula"] == FORMULA_PLEAT
        assert q["formula_used"] == "fixed_height_pleats"
        assert q["fabric_meters"] == 13.3

    def test_default_formula_text_names_the_formula(self):
        """`formula_text` 必须**明确写出所用公式**（韩折），不得只有算式没有公式名。"""
        q = build_quote(**DOUBLE_6_6)
        assert q["formula_text"].startswith("韩折公式：")
        assert q["formula_text"] == "韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米"
    def test_fullness_formula_text_names_the_formula(self):
        """`fullness` 的公式串同样写明公式名 + 逐片表达式 + 米数（与数值同源）。"""
        q = build_quote(formula="fullness", **ANCHOR)
        assert q["formula_text"].startswith("褶倍数公式：")
        assert "每片 2.75" in q["formula_text"]
        assert q["formula_text"].endswith("= 11.0米")

    def test_config_can_change_the_default_formula(self):
        """`default_formula` 可配（商家可改默认）—— 配置被忽略 ⇒ 红。"""
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "default_formula": FORMULA_FULLNESS}
        q = build_quote(config=cfg, **ANCHOR)
        assert q["formula"] == FORMULA_FULLNESS
        assert q["fabric_meters"] == 11.0

    def test_unknown_formula_is_rejected_not_silently_defaulted(self):
        """未知公式名 ⇒ 显式报错（静默回退默认 = 算错钱且无人知道）。"""
        with pytest.raises(ValueError, match="formula"):
            build_quote(formula="褶倍数", **DOUBLE_6_6)

    def test_explicit_formula_is_not_shadowed_by_craft_tier_or_pleat_count(self):
        """**新入参不得静默失效**：显式 `formula='fullness'` 时，`craft_tier` / `pleat_count`
        （折数法的触发条件）**不得**把请求抢回折数法 —— 那正是「传了却没用」的静默形态。

        判别性：若把 `pleat_mode` 判据写在 `formula` 判据之前（或漏了 `selected_formula` 判断），
        下面三条会全部落回折数法（`formula='pleat'` / 13.3 米 / 有 pleat_count）⇒ 红。
        """
        for extra in ({"craft_tier": "standard"}, {"pleat_count": 48},
                      {"craft_tier": "economy", "pleat_count": 48}):
            q = build_quote(formula="fullness", **{**ANCHOR, **extra})
            assert q["formula"] == FORMULA_FULLNESS, f"显式 formula 被 {extra} 遮蔽"
            assert q["fabric_meters"] == 11.0, f"显式 formula 被 {extra} 遮蔽"
            assert "pleat_count" not in q, f"褶倍数公式不该产出折数（收到 {extra}）"

    def test_pleat_formula_still_needs_a_tier_or_pleat_count(self):
        """反向：`formula='pleat'`（默认）在 s_hook 下**仍**需要 `craft_tier`/`pleat_count` 触发折数法
        —— 既有触发条件不得被新入参删掉（否则 6.6m 双开从 13.3 变 13.8 米 = 静默改钱）。"""
        q = build_quote(formula="pleat", window_width=6.6, window_height=2.5, mounting="s_hook",
                        fabric_width=3.2, fabric_price=30.0, open_count=2)
        assert q["formula_used"] == "fixed_height"
        assert q["fabric_meters"] == 13.8
        assert "未指定工艺档位" in q["warning"]


# ══════════════════════════════════════════════════════════════════════════
# 判据 5（开数系数不得翻倍）：同一成品宽下 单开 == 双开（fullness）
# ══════════════════════════════════════════════════════════════════════════

class TestFullnessIndependentOfOpenCount:

    def test_single_equals_double_same_width(self):
        """同一成品宽 5.5m：单开与双开的 `fullness` 结果**相等**（总宽再×开数 ⇒ 22.0 ⇒ 红）。"""
        single = build_quote(formula="fullness", **{**ANCHOR, "open_count": 1})
        double = build_quote(formula="fullness", **ANCHOR)
        assert single["fabric_meters"] == double["fabric_meters"] == 11.0

    def test_fullness_value_is_width_times_fullness(self):
        """逐值锚：`fullness` 用料 = 成品宽 × 褶倍（线性，不得漂移）。"""
        for width, expected in [(5.5, 11.0), (6.6, 13.2), (3.0, 6.0), (4.05, 8.1)]:
            q = build_quote(formula="fullness", **{**ANCHOR, "window_width": width})
            assert q["fabric_meters"] == expected, f"宽 {width} ⇒ 期望 {expected}，得到 {q['fabric_meters']}"

    def test_fullness_ignores_craft_tier(self):
        """褶倍数公式**不吃档位**：standard（2.0）与 economy（1.8）都是「总宽×档位倍数」，
        公式串里写的倍数必须与实际相乘的倍数**同一个数**（档位被静默忽略 ⇒ 红）。"""
        std = build_quote(formula="fullness", **{**ANCHOR, "craft_tier": "standard"})
        eco = build_quote(formula="fullness", **{**ANCHOR, "craft_tier": "economy"})
        assert std["fabric_meters"] == 11.0 and eco["fabric_meters"] == 11.0
        assert std["fullness"] == eco["fullness"] == 2.0
        assert "×2" in std["formula_text"]

    def test_fullness_expression_is_per_panel(self):
        """逐片**表达**（数值与「总宽×褶倍」逐值一致）：总 = 每片 × 开数，每片 = (宽÷开数)×褶倍。"""
        q = build_quote(formula="fullness", **ANCHOR)
        per_panel = (5.5 / 2) * 2.0
        assert per_panel == 5.5
        assert q["fabric_meters"] == per_panel * 2 == 11.0


# ══════════════════════════════════════════════════════════════════════════
# 追加裁定（用户 2026-09-19）：「**韩折用韩折公式算布料，打孔按倍数法算布料，默认选择 2 倍**」
# ⇒ 公式**由工艺推导**；`formula` 入参保留为**显式覆盖**（显式 > 推导 > 兜底默认）
# ══════════════════════════════════════════════════════════════════════════

class TestCraftDerivesFormula:
    """`craft → formula` 推导表是唯一口径；未登记工艺走兜底默认（不猜）。"""

    def test_resolver_is_the_single_source(self):
        """推导**入口**逐值写死：韩褶 → (折数法, s_hook) / 打孔 → (倍数法, eyelet)；未登记 ⇒ (None, None)。

        ⚠️ 用**入口函数**而不是「中文 key 的映射表」：后者会命中本仓
        `test_tool_input_contract_guards.py::TestNoNewChineseWordingJudgement` 的
        「中文措辞当判据」站点（基线只许缩短，`curtain_calc.py` 在基线里是 0 条）。
        """
        assert resolve_craft_rule("韩褶") == ("pleat", "s_hook")
        assert resolve_craft_rule("打孔") == ("fullness", "eyelet")
        assert resolve_craft_rule("四爪钩") == (None, None)
        assert resolve_craft_rule(None) == (None, None)
        assert resolve_craft_rule("") == (None, None)

    def test_hole_punch_uses_fullness_formula(self):
        """**红证①**：打孔 ⇒ 走**倍数法**且 `fullness = 2.0`（走折数法 ⇒ 红）。

        手算：5.5m × 2.0 = **11.0 米**（与 ERP 锚点同值）；折数法会得 11.3 米 ⇒ 判别性成立。
        """
        q = build_quote(window_width=5.5, window_height=2.5, mounting="eyelet",
                        fabric_width=3.2, fabric_price=30.0, open_count=2,
                        craft="打孔", craft_tier="standard")
        assert q["formula"] == FORMULA_FULLNESS
        assert q["fullness"] == 2.0
        assert q["fabric_meters"] == 11.0
        assert "pleat_count" not in q

    def test_hole_punch_default_fullness_reuses_the_standard_tier_value(self):
        """打孔默认 2 倍**复用** `DEFAULT_CRAFT_TIERS['standard'].fullness`，不新造第二个字面量。"""
        assert DEFAULT_FULLNESS["eyelet"] == DEFAULT_CRAFT_TIERS["standard"]["fullness"] == 2.0
        q = build_quote(window_width=5.5, window_height=2.5, mounting="eyelet",
                        fabric_width=3.2, fabric_price=30.0, craft="打孔")
        assert q["fullness"] == DEFAULT_CRAFT_TIERS["standard"]["fullness"]

    def test_s_hook_craft_uses_pleat_formula(self):
        """**红证②**：韩褶 ⇒ 走**折数法**（走倍数法 ⇒ 红）：6.6m 双开标准档 ⇒ 52 折 / 13.3 米。"""
        q = build_quote(window_width=6.6, window_height=2.5, fabric_width=3.2,
                        fabric_price=30.0, open_count=2, craft="韩褶", craft_tier="standard")
        assert q["formula"] == FORMULA_PLEAT
        assert q["pleat_count"] == 52
        assert q["fabric_meters"] == 13.3

    def test_craft_also_drives_mounting(self):
        """`craft` 同时决定悬挂方式（韩褶→s_hook / 打孔→eyelet）—— 打孔拿 eyelet 才有 2.0 倍默认。"""
        assert build_quote(window_width=5.5, window_height=2.5, fabric_width=3.2,
                           fabric_price=30.0, craft="打孔")["fullness"] == 2.0
        assert build_quote(window_width=6.6, window_height=2.5, fabric_width=3.2,
                           fabric_price=30.0, open_count=2, craft="韩褶",
                           craft_tier="standard")["pleat_count"] == 52

    def test_explicit_mounting_wins_over_craft(self):
        """显式 `mounting`（非默认值）优先：传 mounting=s_hook + craft=打孔 ⇒ 仍按 s_hook 的默认倍数。"""
        q = build_quote(window_width=5.5, window_height=2.5, mounting="s_hook", fabric_width=3.2,
                        fabric_price=30.0, craft="打孔")
        assert q["fullness"] == DEFAULT_FULLNESS["s_hook"] == 2.0

    def test_unregistered_craft_falls_back_to_default_formula(self):
        """未登记工艺（四爪钩/穿杆/平幔）⇒ 不猜公式，走配置兜底默认（韩折公式）。"""
        q = build_quote(window_width=5.5, window_height=2.5, mounting="hook", fabric_width=3.2,
                        fabric_price=30.0, craft="四爪钩")
        assert q["formula"] == DEFAULT_CRAFT_CALC_CONFIG["default_formula"] == FORMULA_PLEAT
        assert q["formula_used"] == "fixed_height"

    def test_explicit_formula_wins_over_craft_derivation(self):
        """显式 `formula` 覆盖推导（两条不冲突且都可测）：craft=韩褶 + formula=fullness ⇒ 倍数法。"""
        q = build_quote(window_width=5.5, window_height=2.5, mounting="s_hook", fabric_width=3.2,
                        fabric_price=30.0, open_count=2, craft="韩褶", craft_tier="standard",
                        formula=FORMULA_FULLNESS)
        assert q["formula"] == FORMULA_FULLNESS
        assert q["fabric_meters"] == 11.0

    def test_config_default_formula_is_the_fallback_not_a_competitor(self):
        """`default_formula` 的语义 = **推导表缺失时的兜底**（与推导表不打架）：
        配 default_formula=fullness 时，**已登记工艺**（韩褶）仍走折数法。"""
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "default_formula": FORMULA_FULLNESS}
        q = build_quote(config=cfg, window_width=6.6, window_height=2.5, fabric_width=3.2,
                        fabric_price=30.0, open_count=2, craft="韩褶", craft_tier="standard")
        assert q["formula"] == FORMULA_PLEAT
        assert q["pleat_count"] == 52


# ══════════════════════════════════════════════════════════════════════════
# 配置契约（可注入 + 默认值 = 现有常量逐值不变）
# ══════════════════════════════════════════════════════════════════════════

REQUIRED_CONFIG_KEYS = (
    "per_fold_single", "per_fold_mixed_times", "margin_single", "margin_multi",
    "min_fullness", "tiers", "default_formula", "side_margin", "meters_rounding_step",
)


class TestConfigContract:

    def test_default_config_values_match_existing_constants(self):
        """默认配置逐键 = 现有模块常量（**回归不变量**：不传配置 ⇒ 数值与改前一致）。"""
        cfg = DEFAULT_CRAFT_CALC_CONFIG
        assert set(REQUIRED_CONFIG_KEYS) <= set(cfg)
        assert cfg["per_fold_single"] == curtain_calc.PLEAT_FABRIC_PER_FOLD == 0.25
        assert cfg["per_fold_mixed_times"] == curtain_calc.MIXED_COLOR_PER_FOLD_BY_TIMES == {1: 0.65, 2: 1.2}
        assert cfg["margin_single"] == curtain_calc.MARGIN_SINGLE == 0.2
        assert cfg["margin_multi"] == curtain_calc.MARGIN_MULTI == 0.3
        assert cfg["min_fullness"] == curtain_calc.MIN_FULLNESS == 1.5
        assert cfg["tiers"] == curtain_calc.DEFAULT_CRAFT_TIERS
        assert cfg["default_formula"] == FORMULA_PLEAT == "pleat"
        assert cfg["side_margin"] == curtain_calc.SIDE_MARGIN == 0.3
        assert cfg["meters_rounding_step"] == 0.1

    def test_explicit_default_config_equals_no_config(self):
        """显式传 `DEFAULT_CRAFT_CALC_CONFIG` 与不传 ⇒ **逐值相同**（配置路径与默认路径同一份口径）。"""
        implicit = build_quote(formula="pleat", **DOUBLE_6_6)
        explicit = build_quote(formula="pleat", config=DEFAULT_CRAFT_CALC_CONFIG, **DOUBLE_6_6)
        assert explicit == implicit

    def test_config_changes_per_fold(self):
        """配置真的被公式消费（可注入）：`per_fold_single=0.5` ⇒ 用料按 0.5 米/折算。

        判别性：公式体里写死 0.25 ⇒ 本条红（配置不生效）。
        ⚠️ 同时传 `pleat_count=52`：折数是**输入**（客户自报/档位派生），不是本条的变量 ——
        否则 `per_fold_single` 会同时改变「派生出几个折」（0.5 米/折 ⇒ 26 折），
        两个变量混在一起就不是「配置被消费」的干净判据了。
        """
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "per_fold_single": 0.5}
        q = build_quote(formula="pleat", config=cfg,
                        **{**DOUBLE_6_6, "pleat_count": 52})
        assert q["per_fold"] == 0.5
        assert q["pleat_count"] == 52
        assert q["fabric_meters"] == 26.3      # 0.5×52 + 0.3 = 26.3

    def test_default_config_object_is_not_mutated(self):
        """调用方不得原地改到模块级默认配置（并发请求互相污染）。"""
        before = {k: (dict(v) if isinstance(v, dict) else v)
                  for k, v in DEFAULT_CRAFT_CALC_CONFIG.items()}
        build_quote(formula="pleat", config=DEFAULT_CRAFT_CALC_CONFIG, **DOUBLE_6_6)
        build_quote(formula="fullness", config=DEFAULT_CRAFT_CALC_CONFIG, **ANCHOR)
        after = {k: (dict(v) if isinstance(v, dict) else v)
                 for k, v in DEFAULT_CRAFT_CALC_CONFIG.items()}
        assert after == before


class TestConfigGuardrails:
    """护栏不因可配而消失：配置来自商家（不可信输入）⇒ 非法即显式报错，**不静默回退默认值**。"""

    @pytest.mark.parametrize("key,value", [
        ("per_fold_single", 0),
        ("per_fold_single", -0.25),
        ("margin_single", -0.1),
        ("margin_multi", -0.1),
        ("min_fullness", 0),
        ("side_margin", -0.3),
        ("meters_rounding_step", 0),
        ("meters_rounding_step", -0.1),
    ])
    def test_non_positive_numbers_rejected(self, key, value):
        with pytest.raises(ValueError):
            resolve_craft_calc_config({**DEFAULT_CRAFT_CALC_CONFIG, key: value})

    def test_empty_tiers_rejected(self):
        with pytest.raises(ValueError):
            resolve_craft_calc_config({**DEFAULT_CRAFT_CALC_CONFIG, "tiers": {}})

    def test_tier_without_positive_fullness_rejected(self):
        with pytest.raises(ValueError):
            resolve_craft_calc_config(
                {**DEFAULT_CRAFT_CALC_CONFIG, "tiers": {"standard": {"fullness": 0}}})

    def test_mixed_times_must_be_positive(self):
        with pytest.raises(ValueError):
            resolve_craft_calc_config(
                {**DEFAULT_CRAFT_CALC_CONFIG, "per_fold_mixed_times": {1: 0.65, 2: 0}})

    def test_min_fullness_guardrail_still_fires(self):
        """褶倍下限（护栏）仍生效：低于下限的倍数 ⇒ 显式报错，不是「配置了就不管」。"""
        with pytest.raises(ValueError, match="下限"):
            curtain_calc.derive_pleat_count(6.6, 1.2, open_count=2)
        with pytest.raises(ValueError, match="下限"):
            curtain_calc.derive_pleat_count(6.6, 1.2, open_count=2, config=DEFAULT_CRAFT_CALC_CONFIG)

    def test_configurable_min_fullness_is_honoured(self):
        """下限本身可配（商家可放宽/收紧）：配 1.0 ⇒ 1.2 倍被接受。"""
        cfg = {**DEFAULT_CRAFT_CALC_CONFIG, "min_fullness": 1.0}
        pleats, _ = curtain_calc.derive_pleat_count(6.6, 1.2, open_count=2, config=cfg)
        assert pleats > 0


# ══════════════════════════════════════════════════════════════════════════
# 判据 7（其余算料输出逐值回归）：改前值**写死**，只允许「用料米数」这一项因用户裁定而变
# ══════════════════════════════════════════════════════════════════════════

class TestLegacyOutputsRegression:
    """`formula='pleat'`（默认）⇒ 折数/每片折数/每折吃布/金额与改前**逐值相同**。

    期望值取自 `origin/main @fa7d36ca` 上的既有断言（**改前实测值**，不是从本实现推导）：
    6.6m/双开/标准档 ⇒ 52 折 / 每片 26 / 用料 13.3 米 / 实际褶倍 2.02。
    """

    def test_frozen_legacy_values(self):
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        assert (q["pleat_count"], q["per_panel_pleats"], q["fabric_meters"]) == (52, 26, 13.3)
        assert q["per_fold"] == 0.25
        assert q["fullness"] == 2.0
        assert q["fullness_actual"] == 2.02
        assert q["formula_used"] == "fixed_height_pleats"
        assert q["source"] == "formula"
        assert q["warning"] == ""

    def test_legacy_money_is_derived_from_the_new_meters(self):
        """金额口径：**只**用料米数按裁定变了口径，金额仍 = 米数 × 单价（不做第二套取整）。"""
        q = build_quote(formula="pleat", **DOUBLE_6_6)
        assert q["fabric_cost"] == round(13.3 * 30.0, 2)
        assert q["processing_cost"] == round(13.3 * 10.0, 2)
        assert q["processing_meters"] == q["fabric_meters"] == 13.3

    def test_economy_tier_unchanged(self):
        """经济档（46 折 / 11.8 米）逐值不变。"""
        q = build_quote(formula="pleat", **{**DOUBLE_6_6, "craft_tier": "economy"})
        assert (q["pleat_count"], q["fabric_meters"]) == (46, 11.8)

    def test_mixed_color_per_fold_unchanged(self):
        """拼色每折吃布（拼1次 0.65）逐值不变：52 折双开 ⇒ 34.1 米。"""
        q = build_quote(formula="pleat", style="拼色",
                        special_options=["拼1次"], **DOUBLE_6_6)
        assert q["per_fold"] == 0.65
        assert q["fabric_meters"] == 34.1
