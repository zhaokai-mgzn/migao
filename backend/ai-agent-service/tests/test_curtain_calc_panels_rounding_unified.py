# case_ids: OR-036, OR-041, OR-042
"""**单一门幅路径**的分幅取整口径统一（issue #5060，用户 2026-09-25 裁定「统一取整」）。

## 病根（引擎内部两条分幅路径在边界分叉）

| 路径 | 落点（`backend/ai-agent-service/app/tools/curtain_calc.py`） | 取整方式（改前） |
|---|---|---|
| 候选集路径 | `resolve_fabric_plan` / `derive_plan` | **毫米整数**（`-(-_mm(total) // max(1, _mm(ge)))`）✅ |
| 单一门幅路径 | `_resolve_plan` 的既有分支 `count = math.ceil(T / G)` | **浮点 `ceil`** ❌ |
| 定宽买高米数 | `calculate_fabric_meters` 的定宽分支 `math.ceil(W × N / G)` | **浮点 `ceil`** ❌ |
| 报价卡幅数复算 | `build_quote` 的 `math.ceil(W × N / G)` | **浮点 `ceil`** ❌ |

总用料**恰为门幅整数倍**时浮点除法给出 `k + ε`（实测 `8.4 ÷ 2.8 = 3.0000000000000004`）⇒
浮点 `ceil` **多算 1 幅**，而幅数直接进 `M = P × (H + 卷边)` ⇒ **多收一整幅长**的面料费与加工费
（实测 `W=4.2 / H=3.0 / 2 倍褶 / 门幅 2.8`：改前 4 幅 = 13.2 米、改后 3 幅 = 9.9 米）。

## 判据（本文件四条，每条都能**单独**判红）

| # | 判据 | 红证 |
|---|---|---|
| C1 | 三条落点（米数 / 报价 `panels` / notices 复算）在边界族上给**毫米整数**幅数 | 任一落点改回浮点 `ceil` ⇒ 边界族逐例红 |
| C2 | 米数与幅数**同源**：`fabric_meters == P × (H + 卷边)`（显示与计价不得分叉） | 幅数复算与米数复算用不同分母 ⇒ 红 |
| C3 | **两条分幅路径同值**（候选路径 vs 单一门幅路径，同一 `T` / 同一门幅） | 只把一处改回浮点 ⇒ 两路径在边界族上不等 ⇒ 红 |
| C4 | 非边界族**逐值不变**（反向护栏：「统一取整」不得变成「到处改数」） | 非边界族的幅数被改成 ±1 ⇒ 红 |

⚠️ **本文件只跑边界族与非边界族，不跑全网格**（全网格的「零意外变化」读数见 issue #5060 的
影响面扫描：13440 组单门幅输入里 21 组变化，全部是上述边界族，且**全部为「少算的错被改对」**）。
⚠️ **未固化项**：`_resolve_plan` 的分子是 `T`（`ceil_to_step(W × N, 0.1)` 的进位值）、
`calculate_fabric_meters` 的分子是 `W × N` —— 本单只统一**取整口径**，**不动分子**
（改分子 = 另一笔改钱，需单独裁定，issue #5060 范围外）。
"""
from __future__ import annotations

import math

import pytest

from app.tools.curtain_calc import (
    build_quote,
    calculate_fabric_meters,
    ceil_to_step,
    resolve_craft_calc_config,
    resolve_fabric_plan,
)

#: 上下卷边（读引擎配置，不写死 —— 与 `_meters` 的期望值同源）
HEM_MARGIN = resolve_craft_calc_config(None)["hem_margin"]
#: 净窗高：`H + 卷边 > 门幅` ⇒ 定宽买高（倒幅）⇒ 三条落点都会算幅数
HEIGHT = 3.0

#: 边界族（**分子 = W × N 恰为门幅整数倍** ⇒ 浮点给 `k+ε`、浮点 `ceil` 多算 1 幅）
#: 每行 =（净窗宽 W, 褶倍 N, 门幅 G, 真值幅数 P, 改前浮点幅数）
SINGLE_DOOR_BOUNDARY = (
    (4.2, 2.0, 2.8, 3, 4),
    (2.1, 2.0, 1.4, 3, 4),
    (4.2, 2.0, 1.4, 6, 7),
    (4.9, 2.0, 1.4, 7, 8),
    (5.4, 1.5, 2.7, 3, 4),
    (6.4, 1.5, 3.2, 3, 4),
    (4.2, 3.0, 1.4, 9, 10),
    (7.0, 3.0, 1.4, 15, 16),
    (2.7, 3.0, 2.7, 3, 4),
    (5.4, 3.0, 2.7, 6, 7),
    (3.2, 3.0, 3.2, 3, 4),
    (6.4, 3.0, 3.2, 6, 7),
)

#: 倍数法（`formula="fullness"` ⇒ `_resolve_plan` 既有单一门幅分支）：分子 = `T = ceil_to_step(W × N, 0.1)`
FULLNESS_BOUNDARY = (
    (4.2, 2.0, 2.8, 3, 4),
    (5.6, 1.5, 2.8, 3, 4),
    (6.7, 2.5, 2.8, 6, 7),
    (2.8, 3.0, 2.8, 3, 4),
    (5.6, 3.0, 2.8, 6, 7),
    (7.3, 2.5, 3.05, 6, 7),
    (6.1, 3.0, 3.05, 6, 7),
    (2.1, 2.0, 1.4, 3, 4),
)

#: 非边界族（两式**同值**）—— C4 的反向护栏：证明「非边界输入不被改坏」
NON_BOUNDARY = (
    (3.0, 2.0, 2.8, 3),
    (1.45, 1.8, 2.8, 1),
    (2.0, 1.5, 2.8, 2),
    (1.1, 2.0, 2.8, 1),
    (6.6, 2.0, 3.05, 5),
)


def _mm(value: float) -> int:
    """与引擎 `_mm` 同源（米 ⇒ 整数毫米）。"""
    return int(round(float(value) * 1000))


def _panels_millimeter_integer(total: float, door: float) -> int:
    """**真值式**：毫米整数向上取整（引擎 `_panels_for_door` 的口径）。"""
    return -(-_mm(total) // max(1, _mm(door)))


def _panels_float(total: float, door: float) -> int:
    """**改前**的浮点式 —— 只用于判别力下界（C1 的红证基准），本文件不用它出期望值。"""
    return math.ceil(total / door)


def _meters(panels: int, pattern: float = 0.0) -> float:
    """幅数 ⇒ 用料米数（定宽买高：`M = P × (H + 卷边 + 花距)`）。"""
    return panels * (HEIGHT + HEM_MARGIN + pattern)


class TestGoldenTablePremises:
    """表的**前提可判**（否则下面四条判据都是空跑）。"""

    def test_every_boundary_row_discriminates_float_from_millimeter(self):
        """判别力下界：每行都必须「浮点 ≠ 毫米整数」，且浮点恰好多 1 幅。"""
        undiscriminating = [
            (w, n, g, float_panels)
            for w, n, g, _panels, float_panels in SINGLE_DOOR_BOUNDARY
            if _panels_float(w * n, g) == _panels_millimeter_integer(w * n, g)
        ]
        assert undiscriminating == [], (
            f"边界族里有 {len(undiscriminating)} 行两式同值（表已失去判别力，判据会变空断言）："
            f"{undiscriminating}"
        )

    def test_boundary_rows_are_exact_multiples_and_float_overcounts_by_one(self):
        for w, n, g, panels, float_panels in SINGLE_DOOR_BOUNDARY:
            assert w * n == pytest.approx(panels * g, abs=1e-9), (
                f"W={w} N={n} G={g}：分子 W×N={w * n} 不是门幅整数倍 ⇒ 该行不属边界族"
            )
            assert _panels_millimeter_integer(w * n, g) == panels
            assert float_panels == panels + 1, (
                f"W={w} N={n} G={g}：改前浮点幅数应为 {panels + 1} 幅（多算 1 幅）"
            )

    def test_fullness_rows_match_their_carried_total(self):
        """倍数法边界族：真值幅数必须等于「**进位后**的 T ÷ 门幅」的毫米整数。"""
        for w, n, g, panels, _float_panels in FULLNESS_BOUNDARY:
            total = ceil_to_step(w * n, 0.1)
            assert _panels_millimeter_integer(total, g) == panels, (
                f"W={w} N={n} G={g}：T={total} 的毫米整数幅数 ≠ 表里 {panels}"
            )
            assert _panels_float(total, g) == panels + 1, (
                f"W={w} N={n} G={g}：改前浮点在 T={total} 上没多算 1 幅 ⇒ 该行不属边界族"
            )

    def test_no_half_millimeter_inputs(self):
        """避开半毫米（两侧舍入口径不同：Python 银行家 / JS 四舍五入）。"""
        for row in SINGLE_DOOR_BOUNDARY + FULLNESS_BOUNDARY:
            w, n, g = row[0], row[1], row[2]
            for value in (w, n, w * n, ceil_to_step(w * n, 0.1), g):
                frac = abs(_mm(value) - value * 1000)
                assert abs(frac - 0.5) > 1e-9, f"算例含半毫米输入 {value}（本表不能承载该形态）"


class TestSingleDoorLegsUseMillimeterInteger:
    """C1 / C2：三条落点（米数 / 报价 `panels` / notices 复算）在边界族上给毫米整数幅数。"""

    def test_calculate_fabric_meters_gives_millimeter_integer_panels(self):
        for w, n, g, panels, _float_panels in SINGLE_DOOR_BOUNDARY:
            meters, formula_used, _warning = calculate_fabric_meters(
                window_width=w, window_height=HEIGHT, fullness=n, fabric_width=g,
            )
            assert formula_used == "fixed_width", f"W={w} G={g}：本例应走定宽买高（倒幅）"
            assert meters == pytest.approx(_meters(panels)), (
                f"W={w} N={n} G={g}：用料 {meters} 米 ≠ {panels} 幅 × {HEIGHT + HEM_MARGIN} 米"
                f"（浮点少算的那 1 幅又回来了）"
            )

    def test_build_quote_panels_agree_with_the_money(self):
        """报价格 `panels` 必须与**同一份**米数自洽（显示与计价不得分叉）。"""
        for w, n, g, panels, _float_panels in SINGLE_DOOR_BOUNDARY:
            quote = build_quote(
                window_width=w, window_height=HEIGHT, fullness=n, fabric_width=g,
            )
            assert quote["panels"] == panels, (
                f"W={w} N={n} G={g}：报价幅数 {quote['panels']} ≠ 真值 {panels}"
            )
            assert quote["fabric_meters"] == pytest.approx(_meters(panels), abs=0.011), (
                f"W={w} N={n} G={g}：米数 {quote['fabric_meters']} 与 {panels} 幅不自洽"
            )
            assert quote["formula_used"] == "fixed_width"
            assert f"幅数 {panels} 幅" in quote["warning"], (
                f"W={w} N={n} G={g}：定宽买高告警里的幅数不是真值 {panels} —— 实际告警："
                f"{quote['warning']!r}"
            )

    def test_fullness_formula_leg_uses_the_same_rounding(self):
        """`formula="fullness"` ⇒ `_resolve_plan` 的既有单一门幅分支（`count = ceil(T / G)`）。"""
        for w, n, g, panels, _float_panels in FULLNESS_BOUNDARY:
            quote = build_quote(
                window_width=w, window_height=HEIGHT, fullness=n, fabric_width=g,
                formula="fullness",
            )
            assert quote["formula_used"] == "fixed_width_fullness", (
                f"W={w} N={n} G={g}：倍数法应回 `fixed_width_fullness`（既有词表，含后缀）—— "
                f"实际 {quote['formula_used']!r}"
            )
            assert quote["panels"] == panels, (
                f"W={w} N={n} G={g}：倍数法报价幅数 {quote['panels']} ≠ 真值 {panels}"
            )
            assert quote["fabric_meters"] == pytest.approx(_meters(panels), abs=0.011)

    def test_non_boundary_rows_keep_their_panels_and_money(self):
        """C4 反向护栏：非边界族逐值不变（「统一取整」不是「到处改数」）。"""
        for w, n, g, panels in NON_BOUNDARY:
            quote = build_quote(
                window_width=w, window_height=HEIGHT, fullness=n, fabric_width=g,
            )
            assert quote["panels"] == panels, (
                f"W={w} N={n} G={g}：非边界输入被改动（{quote['panels']} ≠ {panels}）—— "
                "统一取整只许影响「总用料恰为门幅整数倍」的边界"
            )
            assert quote["fabric_meters"] == pytest.approx(_meters(panels), abs=0.011)


class TestTwoPanelPathsAgree:
    """C3：**候选路径**（#5038 已统一）与**单一门幅路径**在同一 `T` 上必须同值。"""

    def test_candidate_path_and_single_door_path_agree_on_boundary_rows(self):
        for table in (SINGLE_DOOR_BOUNDARY, FULLNESS_BOUNDARY):
            for w, n, g, panels, _float_panels in table:
                total = ceil_to_step(w * n, 0.1)
                plan = resolve_fabric_plan(
                    window_height=HEIGHT, fixed_height_meters=total, door_widths=[g],
                )
                assert plan["cutting_mode"] == "定宽买高", (
                    f"W={w} G={g}：成品高 {HEIGHT + HEM_MARGIN} > 门幅 ⇒ 应倒幅"
                )
                assert plan["panels"] == panels, (
                    f"W={w} N={n} G={g}：候选路径 {plan['panels']} 幅 ≠ 真值 {panels} 幅"
                )
                meters, _formula_used, _warning = calculate_fabric_meters(
                    window_width=w, window_height=HEIGHT, fullness=n, fabric_width=g,
                )
                assert meters == pytest.approx(_meters(panels)), (
                    f"W={w} N={n} G={g}：单一门幅路径米数 {meters} 与候选路径 {panels} 幅不等"
                )


class TestNoPanelsDivergenceAcrossGrid:
    """C2 的网格版：全网格上「幅数 × 幅长 = 米数」恒成立，且定高买宽**不造幅数**。"""

    def test_panels_always_reconstruct_the_meters(self):
        mismatched: list[str] = []
        for i in range(56):
            width = round(0.5 + 0.1 * i, 2)
            for fullness in (1.5, 1.8, 2.0, 2.5, 3.0):
                for door in (1.4, 2.7, 2.8, 2.9, 3.05, 3.2):
                    quote = build_quote(
                        window_width=width, window_height=HEIGHT,
                        fullness=fullness, fabric_width=door,
                    )
                    if quote["formula_used"] != "fixed_width":
                        continue
                    expected = _meters(quote["panels"])
                    if abs(quote["fabric_meters"] - round(expected, 2)) > 0.011:
                        mismatched.append(
                            f"W={width} N={fullness} G={door}: {quote['panels']} 幅 × "
                            f"{HEIGHT + HEM_MARGIN} = {expected} ≠ {quote['fabric_meters']}"
                        )
        assert mismatched == [], (
            f"{len(mismatched)} 组输入的「幅数 × 幅长」与米数不自洽（显示/计价分叉）："
            f"{mismatched[:10]}"
        )

    def test_fixed_height_has_no_panels_key(self):
        """定高买宽按宽买米、幅数无定义 ⇒ 键缺席（既有口径，本单不动）。"""
        quote = build_quote(window_width=3.0, window_height=2.0, fullness=2.0, fabric_width=2.8)
        assert quote["formula_used"] == "fixed_height"
        assert "panels" not in quote