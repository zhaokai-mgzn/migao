# case_ids: CH-042, OR-040
"""门幅与加工类型的**自动选择**单元测试（issue #5013）。

口径真值源：`docs/design/door-width-auto-selection.md`（§4 判据表 1~7，每条都能**单独**变红）。

被测函数：`app.tools.curtain_calc.resolve_fabric_plan`（纯函数，不碰钱、不读库）。

算例公共参数（真单回归形态）：成品宽 3.0 / 2 倍褶 ⇒ **定高买宽用料 T = 3.0 × 2 = 6.0 米**
（issue #5030 后宽方向**没有**左右覆盖余量；本单不改用料公式 ⇒ `T` 由调用方算好传入，
测试直接给 6.0 —— 见 `TestBuildQuoteWiring` 的接线断言）。


## issue #5038：文件末尾的 `TestCrossLanguagePanelsGolden`（**引擎腿**）

分幅数（`panels`）在 admin-web 有一份**副本**（`frontend/admin-web/src/lib/door-width-plan.ts`）：
改前用**浮点** `Math.ceil`、引擎用**毫米整数**除法 ⇒ 总用料恰为门幅整数倍时前端**多算 1 幅**
（`W=1.1` / 门幅 `2.8` / 褶倍 `2` ⇒ 浮点 2 幅 / 引擎 1 幅），并可能**翻转选中的门幅**。
本类读**共享 golden 算例表**（`tests/fixtures/panels-cross-language-golden.json`）逐值比对 ——
与静态腿（`tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py`）、
前端腿（`frontend/admin-web/tests/unit/lib/door-width-plan.test.ts`）**共读同一张表**。


## issue #5213：接高口径**已统一**（用户 2026-09-23 裁定「乙 = 统一到新口径」+ 回落路线「B」）

`resolve_fabric_plan` 的接高分支（`_splice()`）曾与 `derive_plan()` 是**两份口径**（旧：「缺口多大都行」
+「加高条按片宽另买布」）。已统一为**同一真值一份口径**：缺口 ≤ `MAX_JOIN_GAP_M` ⇒ 接高且
**`meters = T`**（不另买加高条、`splice_strips = 0`）；缺口 > 上限 ⇒ **回落倒幅**。
⇒ 本文件里所有「接高 = `T + 段数 × 片宽`」的期望值随之改钉；四条判据 + 注入式红证见
`test_curtain_calc_join_height_unified.py`。

**不变量（没被这次统一动到）**：① agent 报价侧两条通路（`fabric_widths=…` / `fabric_width=…`，
**都不传 `cutting_mode`**）逐值不变；② 单一门幅既有路径逐值不变；③ 定高买宽**可行**时
`_fixed_height()` 逐值不变。⚠️ **不是**不变量：缺口 ≤ 0.1 的算例 —— 它们的 `meters` 从
`T + 加高条` 变成 `T`，**这正是裁定要的效果**。


## issue #5060：**单一门幅路径**也扩进同一张共享算例表（文件末尾 `TestSingleDoorPanelsGolden`）

`#5038` 只把**候选路径**（`resolve_fabric_plan`）钉进了 `tests/fixtures/panels-cross-language-golden.json`，
而**单一门幅路径**（`calculate_fabric_meters` 的定宽分支 + `build_quote` 的报价卡幅数复算）
当时一字未动 ⇒ 总用料恰为门幅整数倍时浮点多算 1 幅（`4.2 × 2 ÷ 2.8 = 3.0000000000000004`）。
用户 2026-09-25 裁定「**统一取整**」：全引擎的分幅数只留**一个**实现
`_panels_for_door(total, door)`（毫米整数），本类读共享表的 **`singleDoorCases` 段**跑**真引擎**逐值比对。
"""
import json
from pathlib import Path

import pytest

from app.tools.curtain_calc import (
    CUTTING_MODE_FIXED_HEIGHT,
    CUTTING_MODE_FIXED_WIDTH,
    CUTTING_MODE_SPLICE,
    MAX_JOIN_GAP_M,
    build_quote,
    calculate_fabric_meters,
    ceil_to_step,
    resolve_craft_calc_config,
    resolve_fabric_plan,
)

T = 6.6
CANDIDATES = [2.8, 3.2]


def plan(**kwargs):
    """默认算例 + 覆写（成品宽 3.0 / 2 倍褶 ⇒ T = 6.6）。"""
    base = dict(window_height=2.75, fixed_height_meters=T, door_widths=CANDIDATES)
    return resolve_fabric_plan(**{**base, **kwargs})


# ── 判据 1：定高买宽可行 ⇒ 取**可行集里最小门幅** ──────────────────────────────
class TestFixedHeightTakesSmallestFeasible:
    def test_275_height_picks_32_because_28_is_infeasible(self):
        # 2.75 + 0.3 = 3.05 > 2.8 ⇒ 2.8 不可行；3.05 ≤ 3.2 ⇒ 3.2 可行 ⇒ 取 3.2
        p = plan(window_height=2.75)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["door_width"] == 3.2
        assert p["splice"] is False
        assert p["meters"] == pytest.approx(T)

    def test_240_height_picks_28_smallest_feasible(self):
        # 2.4 + 0.3 = 2.7 ≤ 2.8 ⇒ 两个都可行 ⇒ 取**较小**门幅 2.8（不占宽幅布）
        p = plan(window_height=2.4)
        assert p["door_width"] == 2.8
        # 红证：改成取最大门幅 ⇒ 本断言红
        assert p["meters"] == pytest.approx(T), "定高买宽用料与门幅无关"

    def test_cutting_mode_is_always_one_of_the_two_real_values(self):
        # 接高**不是** cuttingMode 的取值（ERP 只有两项）—— 它是「定高买宽 + splice」
        p = plan(window_height=2.4, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["splice"] is False, "成品高未超门幅 ⇒ 无需接高"


# ── 判据 2：可行集为空 ⇒ **倒幅**（分幅最少） ────────────────────────────────
class TestFallsBackToRotated:
    def test_no_feasible_width_rotates(self):
        # 3.0 + 0.3 = 3.3 > 3.2 ⇒ 无可行门幅 ⇒ 倒幅；panels = ceil(6.6 / 3.2) = 3
        p = plan(window_height=3.0)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["panels"] == 3
        assert p["splice"] is False
        assert p["meters"] == pytest.approx(3 * 3.3)

    def test_rotated_takes_fewest_panels_then_smaller_width(self):
        # ceil(6.6/2.8) = 3 == ceil(6.6/3.2) = 3 ⇒ 并列 ⇒ 取较小门幅 2.8
        p = plan(window_height=3.0)
        assert p["door_width"] == 2.8

    def test_pattern_adds_one_repeat_per_panel(self):
        # 对花：每幅 +1 个花距（与既有定宽买高口径逐字同源）
        p = plan(window_height=3.0, has_pattern=True, pattern_repeat=0.4)
        assert p["meters"] == pytest.approx(3 * (3.3 + 0.4))

    def test_explicit_rotated_mode_is_respected(self):
        p = plan(window_height=2.4, cutting_mode=CUTTING_MODE_FIXED_WIDTH)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["auto"] is False


# ── 判据 3：**不自动选接高**（接高米数更省也不选） ───────────────────────────
class TestSpliceIsNeverChosenAutomatically:
    def test_four_open_splice_is_cheaper_but_rotated_still_wins(self):
        # 四开：接高（#5213 统一后口径）= T = 6.6 米
        #       倒幅                        = ceil(6.6/3.2) × 3.3 = 9.9 米
        # 接高**更省**，但行业口径（竖缝藏进褶皱 vs 可见横缝）⇒ **仍选倒幅**
        p = plan(window_height=3.0, open_count=4)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH, "接高不参与自动比较（裁定 4）"
        assert p["meters"] == pytest.approx(9.9)

    def test_narrow_window_splice_is_cheaper_but_rotated_still_wins(self):
        # 窄窗：T = (0.5 + 0.3) × 2 = 1.6 ⇒ 接高 1.6 米 < 倒幅 3.3 米，仍选倒幅
        p = plan(window_height=3.0, fixed_height_meters=1.6)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["meters"] == pytest.approx(3.3)


# ── 判据 4：人工覆盖选接高 ⇒ **接高不参与算料**（#5213 统一后口径）──────────────
class TestManualSpliceDoesNotBuyFabric:
    """缺口 ≤ `MAX_JOIN_GAP_M` 的显式「接高」：`splice=True`、`meters = T`、`splice_strips = 0`。

    红证：把米数改回旧口径「`T` + 段数 × 片宽」⇒ 本类 5 条里除门幅那条外全红。
    """

    def test_explicit_splice_keeps_meters_equal_to_fixed_height_total(self):
        # H=3.0 ⇒ need 3.3 > 最宽 3.2 ⇒ 缺口 0.1 ≤ 上限 ⇒ 接高；接高不参与算料 ⇒ meters = T
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["splice"] is True
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["splice_gap"] == pytest.approx(MAX_JOIN_GAP_M)
        assert p["splice_strips"] == 0, "接高不参与算料 ⇒ 不另买加高条（裁定 5）"
        assert p["meters"] == pytest.approx(T)

    def test_extra_strips_are_not_charged(self):
        # 红证：若把加高条加回米数（旧口径 6.6 + 1 × 3.3 = 9.9）⇒ 本断言红
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["meters"] != pytest.approx(9.9), "接高不得再另买加高条（乙 + 裁定 5）"

    def test_explicit_fixed_height_over_limit_joins_within_limit(self):
        # 显式「定高买宽」而高度超限、缺口 ≤ 上限 ⇒ 接高（人工覆盖路径保留）
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_FIXED_HEIGHT)
        assert p["splice"] is True
        assert p["meters"] == pytest.approx(T)

    def test_splice_uses_widest_width_to_minimize_gap(self):
        p = plan(window_height=3.0, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["door_width"] == 3.2, "接高取**最宽**门幅（缺口最小）"
        assert p["splice_gap"] == pytest.approx(MAX_JOIN_GAP_M)

    def test_single_open_is_not_charged_a_whole_piece(self):
        # 旧口径单开会把整幅片宽当加高条另买（13.2 米）—— 统一后与**开数无关**：meters = T
        p = plan(window_height=3.0, open_count=1, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["meters"] == pytest.approx(T)


# ── 判据 5：缺口 > 上限 ⇒ **回落倒幅**（不再「缺口多大都行」）────────────────────
class TestSpliceOverLimitFallsBackToRotated:
    """issue #5213（乙 + 回落 B）：缺口 > `MAX_JOIN_GAP_M` ⇒ 显式「接高」也走**倒幅**。

    红证：去掉 `_splice()` 里的 `_join_gap_ok` 闸门（= 恢复「缺口多大都行」）⇒ 本类前两条红。
    """

    def test_gap_over_limit_rotates_instead_of_joining(self):
        # H=3.9 ⇒ need 4.2、最宽 3.2 ⇒ 缺口 1.0 > 0.1 ⇒ 倒幅（ceil(6.6/3.2) = 3 幅 × 4.2 = 12.6）
        p = plan(window_height=3.9, open_count=4, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["splice"] is False
        assert p["splice_gap"] == 0.0
        assert p["splice_strips"] == 0
        assert p["panels"] == 3
        assert p["meters"] == pytest.approx(12.6)

    def test_explicit_fixed_height_over_limit_also_rotates(self):
        p = plan(window_height=3.9, cutting_mode=CUTTING_MODE_FIXED_HEIGHT)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["splice"] is False

    def test_boundary_exactly_at_the_limit_still_joins(self):
        # 缺口恰为 0.1（上限本身）⇒ 接高 —— 与 `derive_plan._join_gap_ok` 同源（含 `_JOIN_EPS` 容差）
        p = plan(window_height=3.0, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["splice"] is True
        assert p["splice_gap"] == pytest.approx(MAX_JOIN_GAP_M)

    def test_rotated_result_equals_the_auto_path_result(self):
        # B 的定义：缺口超限时旧通路与**自动路径**同一输入给同一结果（同一真值一份口径）
        explicit = plan(window_height=3.9, open_count=4, cutting_mode=CUTTING_MODE_SPLICE)
        auto = plan(window_height=3.9, open_count=4)
        assert ({k: v for k, v in explicit.items() if k != "auto"}
                == {k: v for k, v in auto.items() if k != "auto"}), (
            "显式接高在缺口超限时回落倒幅 ⇒ 除 `auto` 标志外与自动解**逐键相等**"
        )


# ── 判据 6：对花**不进接高判定**（它只服务过那笔已退场的「另买加高条」）──────────
class TestPatternNoLongerWidensTheJoinGap:
    """接高不参与算料 ⇒ 对花不再加宽「缺口」；唯一判据 = 物理缺口 ≤ `MAX_JOIN_GAP_M`。

    红证：把旧口径的 `d_eff = 缺口 + 花距` 加回判定 ⇒ 0.1 + 0.4 = 0.5 > 0.1 ⇒ 本类第一条
    从「接高」翻成「倒幅」⇒ 必红。
    """

    def test_pattern_does_not_widen_the_join_gap(self):
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE,
                 has_pattern=True, pattern_repeat=0.4)
        assert p["splice"] is True, "对花不得把 0.1 的物理缺口算成 0.5 ⇒ 不该翻成倒幅"
        assert p["splice_gap"] == pytest.approx(MAX_JOIN_GAP_M), "报的是**物理**缺口"
        assert p["meters"] == pytest.approx(T)

    def test_pattern_still_adds_one_repeat_per_panel_when_rotated(self):
        # 倒幅侧的对花口径**一字未动**（每幅 +1 花距）：3 幅 × (4.2 + 0.4) = 13.8
        p = plan(window_height=3.9, has_pattern=True, pattern_repeat=0.4,
                 cutting_mode=CUTTING_MODE_SPLICE)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["meters"] == pytest.approx(3 * (4.2 + 0.4))


# ── 边界：fail-closed，不静默回退 ─────────────────────────────────────────
class TestFailClosed:
    def test_unknown_cutting_mode_raises(self):
        with pytest.raises(ValueError):
            plan(window_height=3.0, cutting_mode="倒幅")

    def test_empty_candidates_raise(self):
        with pytest.raises(ValueError):
            plan(window_height=3.0, door_widths=[])

    def test_invalid_candidates_are_dropped_not_defaulted(self):
        # 非法值被剔除；剩下 3.2 仍可用 ⇒ 不得回退到任何缺省门幅
        p = plan(window_height=2.4, door_widths=[None, 0, -1, 3.2])
        assert p["door_width"] == 3.2

    def test_allowance_reduces_effective_width(self):
        # 有效余量 0.15 ⇒ 3.2 的有效门幅 3.05；2.75 + 0.3 = 3.05 ≤ 3.05 ⇒ 仍可行（边界相等）
        p = plan(window_height=2.75, allowance=0.15)
        assert p["effective_door_width"] == pytest.approx(3.05)
        assert p["splice"] is False

    def test_allowance_can_make_all_infeasible(self):
        p = plan(window_height=2.75, allowance=0.16)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH


# ── 接线：`build_quote(fabric_widths=...)` 真的走门幅规则（issue #5013） ──────
# ⚠️ 这是「函数写好了但没人调」的守卫。接线红证（实测）：把 `_resolve_plan` 里的
#    `if fabric_widths:` 变异成 `if False:`（= 删掉调用）⇒
#    `test_candidates_pick_widest_feasible_and_fixed_height` /
#    `test_explicit_splice_override_is_honored` / `test_candidates_fall_back_to_rotated` 三条红。
#    ⚠️ **不是「本类全红」**：`test_without_candidates_single_width_behaviour_is_unchanged` 是
#    **回归不变量**（故意走既有单一门幅口径）⇒ 它按设计**不**因该变异变红（issue #5040）。
class TestBuildQuoteWiring:
    def test_candidates_pick_widest_feasible_and_fixed_height(self):
        q = build_quote(
            window_width=3.0, window_height=2.75, fullness=2, fabric_price=98,
            fabric_widths=[2.8, 3.2],
        )
        assert q["door_width"] == 3.2
        assert q["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert q["splice"] is False
        # issue #5030：定高买宽用料 = 窗宽 × 褶倍 = 3.0 × 2 = 6.0（旧式含 0.3 余量 ⇒ 6.6）
        assert q["fabric_meters"] == pytest.approx(6.0)
        assert q["formula_used"] == "fixed_height"

    def test_candidates_fall_back_to_rotated(self):
        # 可行集为空 ⇒ 倒幅。显式 `fabric_width=3.2` 是**判别性**入参：既有单一门幅口径下
        # 3.3 > 3.2 也走倒幅，且 `panels` 与 `fabric_meters` **逐值重合** ⇒ 只断言它们分辨不出
        # 接线与否；接线后候选集**压过**显式门幅、取分幅并列中的较小门幅 2.8。
        # 🔴 issue #5030：宽方向余量退场 ⇒ 用料 = `窗宽 × 褶倍`（旧式含 0.3 ⇒ 判别性几何随之改）。
        # 本组几何（W=4.2 / N=2 ⇒ 8.4 米）：2.8 与 3.2 都 **3 幅**（毫米整数式）⇒ 并列取较小 2.8；
        # 显式 `fabric_width=3.2` 那条口径会取 3.2 ⇒ 两者可分辨（红证：把 `_resolve_plan` 的
        # `if fabric_widths:` 变异成 `if False:` ⇒ 本断言红，`door_width` → 3.2）。
        q = build_quote(
            window_width=4.2, window_height=3.0, fullness=2, fabric_price=98,
            fabric_width=3.2, fabric_widths=[2.8, 3.2],
        )
        assert q["door_width"] == 2.8, "候选集压过显式 fabric_width（schema 已声明后者被忽略）"
        assert q["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        # 幅数 = ceil_mm(窗宽 × 褶倍 ÷ 门幅) = ceil(8.4 / 2.8) = 3（与 3.2 档并列 ⇒ 取较小门幅 2.8；
        # 旧式含余量时该组是 ceil(9.0/2.8) = 4 幅 —— 口径变了，几何随之改，判别性不变）
        assert q["panels"] == 3
        # 倒幅米数由门幅规则给：幅数 3 × 每幅长 (3.0 + 0.3) = 9.9
        assert q["fabric_meters"] == pytest.approx(9.9)
        assert q["formula_used"] == "fixed_width"

    def test_explicit_splice_override_is_honored(self):
        q = build_quote(
            window_width=3.0, window_height=3.0, fullness=2, fabric_price=98,
            open_count=2, fabric_widths=[2.8, 3.2], cutting_mode=CUTTING_MODE_SPLICE,
        )
        assert q["splice"] is True
        # 缺口 0.1 ≤ 上限 ⇒ 接高；**接高不参与算料** ⇒ 米数 = T = 3.0 × 2 = 6.0（issue #5213 统一口径；
        # 旧口径会再另买 1 段加高条 ⇒ 9.0）
        assert q["fabric_meters"] == pytest.approx(6.0)

    def test_without_candidates_single_width_behaviour_is_unchanged(self):
        # 回归不变量：**不传候选集** ⇒ 既有单一门幅口径一字不变（2.75 + 0.3 > 2.8 ⇒ 倒幅）
        q = build_quote(
            window_width=3.0, window_height=2.75, fullness=2, fabric_price=98,
            fabric_width=2.8,
        )
        assert q["door_width"] == 2.8
        assert q["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert q["splice"] is False
        # 既有口径：3.05 > 2.8 ⇒ 倒幅 ceil(6.0 / 2.8) = 3 幅 × 3.05 米 = 9.15 米
        # （issue #5030 只改分幅分子 6.6 → 6.0；幅数 3 与每幅长 3.05 都不变）
        # ⚠️ 米数锚点 **9.15 → 9.2**（issue #5084 改钉）：旧值 = 未进位的缺陷证据（进位规则只覆盖 2/5 路径），
        #    声明口径 = 真值源 `docs/curtain-fabric-quote-rules.md` §8「一律向上进位到 0.1」
        #    ⇒ 期望值取进位后的值（算例对照见本 PR「改钉清单」）。本处只改期望值，幅数 / 门幅判定一字未动。
        assert q["fabric_meters"] == pytest.approx(9.2)


# ── 跨语言 golden 算例表（issue #5038）：引擎 `panels` == admin-web 副本逐值 ──
#: 共享表（**三腿共读**：本类 + 静态腿 + 前端腿）—— 路径从 `__file__` 推（不写死绝对路径）
GOLDEN_JSON = Path(__file__).resolve().parents[3] / "tests/fixtures/panels-cross-language-golden.json"


class TestCrossLanguagePanelsGolden:
    """同一组输入下，引擎 `panels` 必须与共享 golden 表**逐值相等**（issue #5038）。

    红证：① **前端腿**改回浮点 `Math.ceil` ⇒ `boundary-2.8-single` 在前端腿红（引擎腿一直是 1 幅）；
    ② 把**引擎**那行改回浮点（`math.ceil(total / ge)`）⇒ 本类 `boundary-2.8-single` /
    `boundary-1.4-*` 红（表里钉的是毫米整数结果），且静态腿 C1（源形态）同时红。
    """

    @staticmethod
    def _cases() -> list[dict]:
        assert GOLDEN_JSON.is_file(), (
            f"共享算例表不存在：{GOLDEN_JSON} —— 跨语言判据会空跑（fail-closed，不得静默通过）"
        )
        cases = json.loads(GOLDEN_JSON.read_text(encoding="utf8"))["cases"]
        assert cases, "共享算例表为空 —— 判据会空跑（fail-closed）"
        return cases

    def test_per_candidate_panels_match_golden(self):
        """逐候选（单候选调用一次）的分幅数与表逐值相等。"""
        cfg = resolve_craft_calc_config(None)
        for case in self._cases():
            if case["expected"]["state"] != "single_panel":
                continue
            need = case["width"] * case["fullness"]
            for i, door_width in enumerate(case["candidates"]):
                p = resolve_fabric_plan(
                    window_height=case["height"],
                    fixed_height_meters=need,
                    door_widths=[door_width],
                    allowance=case["allowance"],
                    cutting_mode=CUTTING_MODE_FIXED_WIDTH,
                )
                assert p["panels"] == case["expected"]["panelsPerCandidate"][i], (
                    f"{case['id']}：门幅 {door_width} 的引擎幅数 {p['panels']} ≠ "
                    f"共享表 {case['expected']['panelsPerCandidate'][i]}（`need = {need!r}`）—— "
                    "两侧分幅口径已分叉（浮点 vs 毫米整数）"
                )

    def test_chosen_door_width_and_panels_match_golden(self):
        """整候选集的**选中门幅 + 选中幅数**与表逐值相等（双键排序也在判据内）。"""
        cfg = resolve_craft_calc_config(None)
        for case in self._cases():
            if case["expected"]["state"] != "single_panel":
                continue
            need = case["width"] * case["fullness"]
            p = resolve_fabric_plan(
                window_height=case["height"],
                fixed_height_meters=need,
                door_widths=list(case["candidates"]),
                allowance=case["allowance"],
                cutting_mode=CUTTING_MODE_FIXED_WIDTH,
            )
            assert p["door_width"] == case["expected"]["chosenDoorWidth"], (
                f"{case['id']}：选中门幅 {p['door_width']} ≠ 共享表 "
                f"{case['expected']['chosenDoorWidth']} —— 分幅数的取整口径漂移会**翻转**双键排序"
            )
            assert p["panels"] == case["expected"]["chosenPanels"], (
                f"{case['id']}：选中幅数 {p['panels']} ≠ 共享表 {case['expected']['chosenPanels']}"
            )

    def test_all_candidates_filtered_by_allowance_fails_closed(self):
        """候选被有效余量全剔除 ⇒ **抛 ValueError**（与 TS 侧 `undecidable` 同一条口径）。"""
        cfg = resolve_craft_calc_config(None)
        checked = 0
        for case in self._cases():
            if case["expected"]["state"] != "undecidable":
                continue
            checked += 1
            need = case["width"] * case["fullness"]
            with pytest.raises(ValueError):
                resolve_fabric_plan(
                    window_height=case["height"],
                    fixed_height_meters=need,
                    door_widths=list(case["candidates"]),
                    allowance=case["allowance"],
                    cutting_mode=CUTTING_MODE_FIXED_WIDTH,
                )
        assert checked > 0, (
            "共享表里没有「候选全被剔除」的算例 ⇒ 本条会空跑（fail-closed 那一面无人钉）"
        )


# ── issue #5060：**单一门幅路径**扩进同一张共享算例表（判据 3）────────────────────
class TestSingleDoorPanelsGolden:
    """**单一门幅路径**（既有 `fabric_width=…` 口径）的分幅取整 —— 引擎腿。

    改前：候选路径毫米整数、单一门幅路径浮点 `ceil` ⇒ 边界输入上两条路径给出**两个**幅数
    （`W=4.2` / 2 倍褶 / 门幅 `2.8`：候选 3 幅 / 单一门幅 4 幅，真值 3）。用户裁定「统一取整」后
    三条落点（定宽买高米数 / 报价格 `panels` / 报价卡幅数复算）同调 `_panels_for_door`。
    本类跑**真引擎**、读共享表的 `singleDoorCases` 段（静态腿 = `tests/unit_ci_workflows/
    test_panels_cross_language_algorithm_guard.py` 的 C8 照源复算）⇒ 两腿共读同一张表。
    """

    @staticmethod
    def _data() -> dict:
        assert GOLDEN_JSON.is_file(), (
            f"共享算例表不存在：{GOLDEN_JSON} —— 跨语言判据会空跑（fail-closed，不得静默通过）"
        )
        data = json.loads(GOLDEN_JSON.read_text(encoding="utf8"))
        assert data.get("singleDoorCases"), (
            "共享算例表缺 `singleDoorCases` 段 —— **单一门幅路径**未被覆盖（issue #5060 判据 3）"
        )
        return data

    def test_table_hem_margin_equals_the_engine_config(self):
        """表的前提（每幅长 = `height + 卷边`）必须与引擎配置**同值**，否则期望米数与实际口径脱钩。"""
        hem = self._data()["singleDoorPremises"]["hemMargin"]
        engine_hem = resolve_craft_calc_config(None)["hem_margin"]
        assert hem == pytest.approx(engine_hem), (
            f"共享表 `hemMargin` = {hem} ≠ 引擎配置 `hem_margin` = {engine_hem} ⇒ 红"
        )

    def test_calculate_fabric_meters_matches_the_shared_table(self):
        """落点 ①：`calculate_fabric_meters` 的定宽买高米数 == 表里的「毫米整数幅数 × 幅长」。"""
        data = self._data()
        hem = data["singleDoorPremises"]["hemMargin"]
        boundary_checked = 0
        for row in data["singleDoorCases"]:
            meters, formula_used, _warning = calculate_fabric_meters(
                window_width=row["width"], window_height=row["height"],
                fullness=row["fullness"], fabric_width=row["door"],
            )
            assert formula_used == "fixed_width", f"{row['id']}：本例应走定宽买高（倒幅）"
            expected = round(ceil_to_step(row["expectedPanels"] * (row["height"] + hem), 0.1), 2)
            assert meters == pytest.approx(expected), (
                f"{row['id']}：米数 {meters} ≠ 真值 {expected}"
                f"（{row['expectedPanels']} 幅 × {row['height'] + hem} 米，向上进位到 0.1）"
            )
            assert meters == pytest.approx(row["expectedMeters"]), (
                f"{row['id']}：米数 {meters} ≠ 共享表 `expectedMeters` {row['expectedMeters']}"
            )
            if row["floatPanels"] != row["expectedPanels"]:
                boundary_checked += 1
                float_meters = round(
                    ceil_to_step(row["floatPanels"] * (row["height"] + hem), 0.1), 2)
                assert meters != pytest.approx(float_meters), (
                    f"{row['id']}：边界行的米数与**改前浮点幅数**（{row['floatPanels']} 幅 = "
                    f"{float_meters} 米）同值 ⇒ 取整口径没生效（浮点又回来了）"
                )
        assert boundary_checked >= 1, "共享表里没有边界行 ⇒ 本判据在边界面上空跑"

    def test_build_quote_panels_and_notice_match_the_shared_table(self):
        """落点 ②③：报价格 `panels` 与报价卡告警里的「幅数 N 幅」都必须 == 同一份真值。"""
        data = self._data()
        for row in data["singleDoorCases"]:
            quote = build_quote(
                window_width=row["width"], window_height=row["height"],
                fullness=row["fullness"], fabric_width=row["door"],
            )
            assert quote["formula_used"] == "fixed_width"
            assert quote["panels"] == row["expectedPanels"], (
                f"{row['id']}：报价幅数 {quote['panels']} ≠ 真值 {row['expectedPanels']}"
            )
            assert f"幅数 {row['expectedPanels']} 幅" in quote["warning"], (
                f"{row['id']}：报价卡告警里的幅数与真值不符（显示/计价分叉）—— 实际："
                f"{quote['warning']!r}"
            )
            if row["floatPanels"] != row["expectedPanels"]:
                assert f"幅数 {row['floatPanels']} 幅" not in quote["warning"], (
                    f"{row['id']}：告警里出现了**改前浮点**幅数 {row['floatPanels']} —— 又分叉了"
                )
