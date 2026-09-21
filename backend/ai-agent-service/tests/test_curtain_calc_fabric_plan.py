# case_ids: CH-042, OR-040
"""门幅与加工类型的**自动选择**单元测试（issue #5013）。

口径真值源：`docs/design/door-width-auto-selection.md`（§4 判据表 1~7，每条都能**单独**变红）。

被测函数：`app.tools.curtain_calc.resolve_fabric_plan`（纯函数，不碰钱、不读库）。

算例公共参数（真单回归形态）：成品宽 3.0 / 2 倍褶 ⇒ **定高买宽用料 T = (3.0 + 0.3) × 2 = 6.6 米**
（本单不改用料公式 ⇒ `T` 由调用方算好传入，测试直接给 6.6）。

## issue #5038：文件末尾的 `TestCrossLanguagePanelsGolden`（**引擎腿**）

分幅数（`panels`）在 admin-web 有一份**副本**（`frontend/admin-web/src/lib/door-width-plan.ts`）：
改前用**浮点** `Math.ceil`、引擎用**毫米整数**除法 ⇒ 总用料恰为门幅整数倍时前端**多算 1 幅**
（`W=1.1` / 门幅 `2.8` / 褶倍 `2` ⇒ 浮点 2 幅 / 引擎 1 幅），并可能**翻转选中的门幅**。
本类读**共享 golden 算例表**（`tests/fixtures/panels-cross-language-golden.json`）逐值比对 ——
与静态腿（`tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py`）、
前端腿（`frontend/admin-web/tests/unit/lib/door-width-plan.test.ts`）**共读同一张表**。
"""
import json
from pathlib import Path

import pytest

from app.tools.curtain_calc import (
    CUTTING_MODE_FIXED_HEIGHT,
    CUTTING_MODE_FIXED_WIDTH,
    CUTTING_MODE_SPLICE,
    build_quote,
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
        # 四开：接高（口径 A）= 6.6 + ceil(4/32) × (6.6/4) = 8.25 米
        #       倒幅          = ceil(6.6/3.2) × 3.3 = 9.9 米
        # 接高**更省**，但行业口径（竖缝藏进褶皱 vs 可见横缝）⇒ **仍选倒幅**
        p = plan(window_height=3.0, open_count=4)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH, "接高不参与自动比较（裁定 4）"
        assert p["meters"] == pytest.approx(9.9)

    def test_narrow_window_splice_is_cheaper_but_rotated_still_wins(self):
        # 窄窗：T = (0.5 + 0.3) × 2 = 1.6 ⇒ 接高 3.2 米 < 倒幅 3.3 米，仍选倒幅
        p = plan(window_height=3.0, fixed_height_meters=1.6)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["meters"] == pytest.approx(3.3)


# ── 判据 4：人工覆盖选接高 ⇒ 按**口径 A** 算料 ──────────────────────────────
class TestSpliceBasisA:
    def test_explicit_splice_uses_strip_length_not_area(self):
        # 口径 A：M = T + 段数 × Wp = 6.6 + ceil(2 / floor(3.2/0.1)) × 3.3 = 9.9
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["splice"] is True
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["splice_gap"] == pytest.approx(0.1)
        assert p["splice_strips"] == 1
        assert p["meters"] == pytest.approx(9.9)

    def test_area_based_basis_is_rejected(self):
        # 红证：若实现改成「按缺口面积折料」T × (1 + d/g) = 6.6 × 1.03125 ≈ 6.81 ⇒ 本断言红
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["meters"] != pytest.approx(6.81, abs=0.05), "口径 A 不得退回面积折料"

    def test_explicit_fixed_height_over_limit_falls_to_splice(self):
        # 显式「定高买宽」而高度超限 ⇒ 接高（#4877 的旧语义，本单保留为人工覆盖路径）
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_FIXED_HEIGHT)
        assert p["splice"] is True
        assert p["meters"] == pytest.approx(9.9)

    def test_splice_uses_widest_width_to_minimize_gap(self):
        p = plan(window_height=3.0, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["door_width"] == 3.2, "接高取**最宽**门幅（缺口最小）"
        assert p["splice_gap"] == pytest.approx(0.1)

    def test_splice_single_open_is_two_piece_widths(self):
        # 单开：Wp = T = 6.6 ⇒ 段数 1 ⇒ M = 13.2（加高条整幅另买）
        p = plan(window_height=3.0, open_count=1, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["meters"] == pytest.approx(13.2)


# ── 判据 5：对花 ⇒ d_eff = d + 花距 ────────────────────────────────────────
class TestSplicePattern:
    def test_pattern_widens_strip_so_fewer_fit_side_by_side(self):
        # d = 0.1，花距 0.4 ⇒ d_eff = 0.5 ⇒ floor(3.2/0.5) = 6 条/段
        p = plan(
            window_height=3.0,
            open_count=2,
            cutting_mode=CUTTING_MODE_SPLICE,
            has_pattern=True,
            pattern_repeat=0.4,
        )
        assert p["meters"] == pytest.approx(9.9)  # ceil(2/6) = 1 段

    def test_pattern_never_shrinks_the_strip(self):
        # 红证：把 d_eff 写成 d（忽略花距）⇒ 缺口少算 ⇒ 本断言在窄门幅下红
        p = plan(
            window_height=3.0,
            open_count=8,
            cutting_mode=CUTTING_MODE_SPLICE,
            has_pattern=True,
            pattern_repeat=0.4,
        )
        # d_eff = 0.5 ⇒ 6 条/段 ⇒ 8 片要 2 段 ⇒ 6.6 + 2 × (6.6/8) = 8.25
        assert p["meters"] == pytest.approx(8.25)


# ── 判据 7：缺口大到一段裁不完 ⇒ 段数递增 ─────────────────────────────────
class TestSpliceStripCountIncrements:
    def test_gap_too_wide_for_one_piece(self):
        # H = 3.9 ⇒ need 4.2 > 3.2 ⇒ d = 1.0 ⇒ floor(3.2/1.0) = 3 条/段
        # 四开 ⇒ 段数 = ceil(4/3) = 2 ⇒ M = 6.6 + 2 × 1.65 = 9.9
        p = plan(window_height=3.9, open_count=4, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["splice_gap"] == pytest.approx(1.0)
        assert p["splice_strips"] == 2
        assert p["meters"] == pytest.approx(9.9)

    def test_floor_is_exact_at_millimetre_precision(self):
        # 3.2 / 0.1 在二进制浮点下可能是 31.999… ⇒ 浮点 floor 会算成 31 条/段（少一条、料变贵）。
        # 本实现按**毫米整数**除 ⇒ 恰好 32 条/段 ⇒ 双开只需 1 段。
        p = plan(window_height=3.0, open_count=2, cutting_mode=CUTTING_MODE_SPLICE)
        assert p["splice_strips"] == 1


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
        assert q["fabric_meters"] == pytest.approx(6.6)
        assert q["formula_used"] == "fixed_height"

    def test_candidates_fall_back_to_rotated(self):
        # 可行集为空 ⇒ 倒幅。显式 `fabric_width=3.2` 是**判别性**入参：既有单一门幅口径下
        # 3.3 > 3.2 也走倒幅，且 `panels`（同为 3）与 `fabric_meters`（同为 9.9）**逐值重合**
        # ⇒ 只断言它们分辨不出接线与否；接线后候选集**压过**显式门幅、取分幅并列中的较小门幅 2.8。
        # 红证（实测）：把 `_resolve_plan` 的 `if fabric_widths:` 变异成 `if False:` ⇒ 本断言红
        # （`door_width` → 3.2）。
        q = build_quote(
            window_width=3.0, window_height=3.0, fullness=2, fabric_price=98,
            fabric_width=3.2, fabric_widths=[2.8, 3.2],
        )
        assert q["door_width"] == 2.8, "候选集压过显式 fabric_width（schema 已声明后者被忽略）"
        assert q["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert q["panels"] == 3
        assert q["fabric_meters"] == pytest.approx(9.9)
        assert q["formula_used"] == "fixed_width"

    def test_explicit_splice_override_is_honored(self):
        q = build_quote(
            window_width=3.0, window_height=3.0, fullness=2, fabric_price=98,
            open_count=2, fabric_widths=[2.8, 3.2], cutting_mode=CUTTING_MODE_SPLICE,
        )
        assert q["splice"] is True
        assert q["fabric_meters"] == pytest.approx(9.9)

    def test_without_candidates_single_width_behaviour_is_unchanged(self):
        # 回归不变量：**不传候选集** ⇒ 既有单一门幅口径一字不变（2.75 + 0.3 > 2.8 ⇒ 倒幅）
        q = build_quote(
            window_width=3.0, window_height=2.75, fullness=2, fabric_price=98,
            fabric_width=2.8,
        )
        assert q["door_width"] == 2.8
        assert q["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert q["splice"] is False
        # 既有口径：3.05 > 2.8 ⇒ 倒幅 ceil(6.6 / 2.8) = 3 幅 × 3.05 米 = 9.15 米
        assert q["fabric_meters"] == pytest.approx(9.15)


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
            need = (case["width"] + cfg["side_margin"]) * case["fullness"]
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
            need = (case["width"] + cfg["side_margin"]) * case["fullness"]
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
            need = (case["width"] + cfg["side_margin"]) * case["fullness"]
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
