# case_ids: OR-032
"""算料引擎**自动推导**单元测试（issue #5201 = 母单 #5200 子单 A）。

规格书 = 母单 #5200 的**冻结契约 v1.1**（§三 候选枚举表 / 硬规则 R1~R7 / §四 响应契约 / §五 判据 1~10）。
被测函数 = `app.tools.curtain_calc.derive_plan`（**纯函数**：不读库、不碰钱、不写日志）。

契约定义（逐字）：
- `T` = **单色**定高买宽单幅用料（米）= 现有单色公式值（韩褶公式或倍数公式）；
- `need_h` = `H + hem`；
- `P` = `ceil(T / D)`。

| # | key | 可行条件 | 用料 | 拼接 | 接高/接宽 |
|---|---|---|---|---|---|
| 1 | `fixed_height` | `need_h ≤ D` | `T` | 0 | — |
| 2 | `fixed_height_join_height` | `0 < need_h − D ≤ 0.1` | `T`（接高不进算料） | 0 | 接高 gap = `need_h − D` |
| 3 | `fixed_width` | 恒可行 | `P × need_h` | `P − 1` | — |
| 4 | `fixed_width_join_width` | `T − (P−1)×D ≤ 0.1` 且 `P ≥ 2` | `(P−1) × need_h` | `P − 2` | 接宽 gap = `T − (P−1)×D` |
| 5 | `fixed_width_join_height` | **恒不可行**（倒幅幅长按米买、无上限） | — | `P − 1` | — |

选优顺序：① 用料最少 → ② 拼接最少 → ③ 接高/接宽最少 → ④ 候选表顺序。

⚠️ **v1.1 订正**（母单自检发现）：v1 把候选 4 的条件写成 `P×D − T ≤ 0.1`（几何上荒谬 ——
会得出「丢掉一整幅却仍需要 2.7 米布」）。正确条件 = `T − (P−1)×D ≤ 0.1`，接宽 gap 同式。
本文件的 `TestCriterion3JoinWidth` 两个方向都钉住（正例可行且选优 / 反例不可行）。
"""
import math

import pytest

from app.tools.curtain_calc import (
    CUTTING_MODE_FIXED_HEIGHT,
    CUTTING_MODE_FIXED_WIDTH,
    MAX_JOIN_GAP_M,
    SPLICE_OPTION_BY_TIMES,
    STYLE_MIXED,
    derive_plan,
)

# 公共算例（真单回归形态）：成品高 2.5 + 上下卷边 0.3 ⇒ need_h = 2.8 米
H = 2.5
D = 2.8
T = 6.0          # ⇒ P = ceil(6.0 / 2.8) = 3
NEED_H = 2.8     # 默认算例（H = 2.5）的 need_h

#: 成品高 3.0 的算例：need_h = 3.0 + 0.3 = **3.3**（> D ⇒ 定高买宽不可行，倒幅才是胜者）。
#: ⚠️ 用 `NEED_3_0` 而不是 `NEED_H` —— 把 2.8 写进 3.0 的算例 = 断言与几何脱钩（假绿）。
H_JOIN = 3.0
NEED_3_0 = 3.3


def plan(**kwargs):
    """默认算例 + 覆写。"""
    base = dict(window_height=H, fixed_height_meters=T, door_width=D)
    return derive_plan(**{**base, **kwargs})


def by_key(result, key):
    """候选表里按 key 取一条（缺失即红 —— 候选表**必须**含全部 5 条）。"""
    matches = [c for c in result["candidates"] if c["key"] == key]
    assert len(matches) == 1, f"候选表里 {key} 应恰有一条，实得 {len(matches)}：{result['candidates']}"
    return matches[0]


# ── 判据 1：need_h ≤ D ⇒ 定高买宽（候选选择） ─────────────────────────────────
class TestCriterion1FixedHeightWhenHeightFits:
    def test_height_fits_door_width_picks_fixed_height(self):
        # need_h 2.8 ≤ D 2.8 ⇒ 候选 1 可行；候选 2 要求缺口 > 0 ⇒ 不可行（0 不是缺口）
        p = plan()
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["splice_times"] == 0
        assert p["panels"] is None, "定高买宽按宽买米，幅数无定义 ⇒ null（不补 0/1）"
        assert p["splice_option"] is None, "0 次 ⇒ 无选项名（不得发明「拼0次」）"
        assert p["meters"] == pytest.approx(T)
        assert p["auto"] is True
        assert by_key(p, "fixed_height")["feasible"] is True
        assert by_key(p, "fixed_height_join_height")["feasible"] is False

    def test_short_total_alone_does_not_make_fixed_height_feasible(self):
        """候选 1 的可行条件是 **`need_h ≤ D`**，不是 `T ≤ D`（门幅同时是「宽方向的布长」）。

        红证形态：把条件误写成 `T ≤ D` 或恒可行 ⇒ 本条红（H=2.2 ⇒ need_h 2.5 ≤ 2.8 才是可行）。
        """
        tall = plan(window_height=3.0)          # T 6.0 > D 2.8，但 need_h 3.3 > 2.8 ⇒ 不可行
        assert tall["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        short = plan(window_height=2.2)         # need_h 2.5 ≤ 2.8 ⇒ 可行（用料 T 6.0 = 候选 1）
        assert short["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        # 同一 T、只改成品高 ⇒ 结论必须翻转（若有人把条件写成 `T ≤ D`，两例都会是定高买宽 ⇒ 红）
        assert by_key(tall, "fixed_height")["feasible"] is False
        assert by_key(short, "fixed_height")["feasible"] is True

    def test_door_width_shrunk_below_height_switches_to_fixed_width(self):
        # 门幅调到 2.7 ⇒ need_h 3.3 > 2.7 ⇒ 定高买宽不可行 ⇒ 倒幅；P = ceil(6.0/2.7) = 3
        p = plan(window_height=3.0, door_width=2.7)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH, "候选选择：定高买宽不可行 ⇒ 必须改判倒幅"
        assert p["panels"] == 3
        assert p["meters"] == pytest.approx(3 * NEED_3_0)
        assert by_key(p, "fixed_height")["feasible"] is False


# ── 判据 2：P 与 拼N次 的映射（N = panels − 1，单色公式） ──────────────────────
class TestCriterion2SpliceTimesEqualsPanelsMinusOne:
    def test_three_panels_is_splice_two(self):
        # ⚠️ 必须用「定高买宽不可行」的几何（need_h 3.3 > D 2.8）：否则候选 1 更省、它才是胜者
        p = plan(window_height=3.0)
        assert p["panels"] == 3
        assert p["splice_times"] == 2
        assert p["splice_option"] == "拼2次"
        assert p["meters"] == pytest.approx(3 * NEED_3_0), "倒幅用料 = P × need_h"

    def test_splice_option_map_is_by_times_not_by_panels(self):
        """红证形态：把 `splice_option` 的查表键改成 `P`（而不是 `N = P − 1`）⇒ 本条必红。

        `P = 3` 时正确选项是 `拼2次`；用 `P` 当键会给出 `拼3次`。
        """
        p = plan(window_height=3.0)
        assert SPLICE_OPTION_BY_TIMES[p["splice_times"]] == "拼2次"
        assert p["splice_option"] != SPLICE_OPTION_BY_TIMES[p["panels"]], (
            "splice_option 必须按**拼次**（P−1）查，不是按幅数（P）查"
        )


# ── 判据 3：候选 4（倒幅 + 接宽）—— v1.1 订正后的条件 ──────────────────────────
class TestCriterion3JoinWidthCondition:
    def test_remainder_over_limit_is_infeasible(self):
        # T=6.0 / D=2.8 ⇒ P=3 ⇒ T − (P−1)×D = 6.0 − 5.6 = 0.4 > 0.1 ⇒ 候选 4 不可行
        # （成品高 3.0 ⇒ need_h 3.3 > D ⇒ 定高买宽不可行，倒幅才是胜者）
        p = plan(window_height=3.0)
        c4 = by_key(p, "fixed_width_join_width")
        assert c4["feasible"] is False
        assert c4["meters"] is None, "不可行候选**不得**给估算用料（fail-closed）"
        assert "0.4" in c4["reason"] and "0.1" in c4["reason"], "理由要写出哪几个数比出来的"
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["meters"] == pytest.approx(3 * NEED_3_0), "候选 4 不可行 ⇒ 退回纯倒幅"

    def test_remainder_within_limit_wins_by_meters(self):
        # T=5.65 / D=2.8 ⇒ P=3 ⇒ 5.65 − 5.6 = 0.05 ≤ 0.1 ⇒ 候选 4 可行
        # 用料 (P−1) × need_h = 2 × 2.8 = 5.6 < 纯倒幅 3 × 2.8 = 8.4 ⇒ **选优必须选它**
        p = plan(window_height=3.0, fixed_height_meters=5.65)
        c4 = by_key(p, "fixed_width_join_width")
        assert c4["feasible"] is True
        assert c4["meters"] == pytest.approx(2 * NEED_3_0)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        # 契约订正 v1.2：`panels` = **实际买布幅数** = P − 1（第 P 幅被接宽布条顶掉）
        assert p["panels"] == 2
        assert p["splice_times"] == 1, "接宽方案拼接 P−2 = 1 次（且 splice_times == panels − 1）"
        assert p["splice_option"] == "拼1次"
        assert p["join_width_m"] == pytest.approx(0.05)
        assert p["join_height_m"] is None
        assert p["meters"] == pytest.approx(2 * NEED_3_0), "选优：省一整幅"

    def test_v1_wrong_condition_would_flip_both_directions(self):
        """红证形态：把条件改回 v1 的 `P×D − T ≤ 0.1` ⇒ 正反两例同时翻转。

        v1 写法下 `T=5.65`（正例）算得 `3×2.8 − 5.65 = 2.75 > 0.1` ⇒ **误判不可行**；
        而 `T=6.0`（反例）算得 `8.4 − 6.0 = 2.4 > 0.1` ⇒ 也判不可行（碰巧同结论）。
        ⇒ 钉住「正例必须可行」这一条即可把 v1 写法变红。
        """
        v1_predicate = lambda t, d: (math.ceil(t / d) * d - t) <= MAX_JOIN_GAP_M  # noqa: E731
        assert v1_predicate(5.65, 2.8) is False, "v1 写法会算出 2.75 > 0.1（荒谬：丢掉一幅还要 2.75 米布）"
        assert derive_plan(window_height=3.0, fixed_height_meters=5.65,
                           door_width=2.8)["join_width_m"] is not None, (
            "v1.1 口径：T−(P−1)×D = 0.05 ≤ 0.1 ⇒ 接宽必须可行"
        )

    def test_single_panel_never_join_width(self):
        """**P = 1 ⇒ 候选 4 必须不可行**（无「第 P 幅」可省）。

        契约 §三 的候选 4 条件写了两项（`remainder ≤ 0.1` 与 `P ≥ 2`），**两项都不可省** ——
        区分点是 `T` 的大小：

        - `T > 0.1`（P=1）：remainder = T > 0.1 ⇒ **两项都挡**（冗余）；
        - **`T ∈ (0, 0.1]`（P=1）：remainder = T ≤ 0.1 ⇒ 只剩 `P ≥ 2` 挡得住**
          （去掉它 ⇒ 候选 4 翻成可行，并给出 `meters = (P−1) × need_h = **0 米**` + 一条接宽布条
          的荒谬解 —— 契约 v1.1 订正段那句「丢掉一整幅却仍需 2.7 米布」的镜像：**不买布却要接宽**）。

        ⇒ **红证**：把 `feasible = panels >= 2 and _join_gap_ok(gap)` 里的 `>= 2` 去掉 ⇒ 下面
        `total ∈ (0.05, 0.08, 0.1)` 三条断言全红。
        """
        # `T ∈ (0, 0.1]` 是关键区（那里只剩 `P ≥ 2` 挡得住）；`T = 2.0` 是「两项都挡」的对照
        for total in (0.05, 0.08, 0.1, 2.0):
            p = plan(window_height=3.0, fixed_height_meters=total, door_width=2.8)
            c4 = by_key(p, "fixed_width_join_width")
            assert by_key(p, "fixed_width")["feasible"] is True, f"P = 1（T={total}）"
            assert c4["feasible"] is False, f"P=1 ⇒ 候选 4 必须不可行（T={total}）"
            assert c4["meters"] is None
            assert "无第 P 幅可省" in c4["reason"], "理由要写清「P=1 无第 P 幅可省」"

    def test_any_feasible_candidate_has_positive_meters(self):
        """**跨界不变量**：任何 `feasible` 候选的 `meters` 必须 **> 0**（0 米用料永远不是合法方案）。

        红证形态：去掉候选 4 的 `panels >= 2` ⇒ `T ∈ (0, 0.1]`（P=1）时候选 4 翻成可行、
        `meters = (P−1) × need_h = **0**` ⇒ 本条必红。
        """
        cases = [
            {}, {"window_height": 3.0}, {"window_height": 3.0, "fixed_height_meters": 5.65},
            {"window_height": 3.0, "fixed_height_meters": 0.05},   # P=1，`P ≥ 2` 的唯一判别区
            {"window_height": 3.0, "fixed_height_meters": 0.08},
            {"window_height": 3.0, "fixed_height_meters": 0.1},
            {"window_height": 3.0, "fixed_height_meters": 12.0},
        ]
        for kwargs in cases:
            p = plan(**kwargs)
            for c in p["candidates"]:
                if c["feasible"]:
                    assert c["meters"] > 0, (
                        f"可行候选 {c['key']} 的用料必须 > 0（{kwargs}：meters={c['meters']}）"
                        "—— 0 米用料 = 不买布却要接宽，永远不是合法方案"
                    )

    def test_candidate_splice_counts_are_never_negative(self):
        """P=1 时候选 4/5 的 `splice_times` 不得为负（负数会污染选优排序）。"""
        p = plan(window_height=3.0, fixed_height_meters=2.0, door_width=2.8)   # P = 1
        for key in ("fixed_width_join_width", "fixed_width_join_height"):
            assert by_key(p, key)["splice_times"] >= 0, f"{key} 的拼接次数不得为负"
        assert p["splice_times"] == 0 and p["splice_option"] is None


# ── 判据 4：接高/接宽缺口上限 0.1 米（R1） ─────────────────────────────────────
class TestCriterion4JoinGapLimit:
    def test_gap_025_is_infeasible_for_join_height(self):
        # H=3.0 ⇒ need_h=3.3；D=3.05 ⇒ 缺口 0.25 > 0.1 ⇒ 候选 2 不可行
        p = plan(window_height=3.0, door_width=3.05)
        c2 = by_key(p, "fixed_height_join_height")
        assert c2["feasible"] is False
        assert c2["meters"] is None
        assert "0.25" in c2["reason"] and "0.1" in c2["reason"]
        assert p["join_height_m"] is None

    def test_gap_005_is_feasible_and_meters_unchanged(self):
        # H=3.0 ⇒ need_h=3.3；D=3.25 ⇒ 缺口 0.05 ≤ 0.1 ⇒ 候选 2 可行，用料仍是 T（R2）
        p = plan(window_height=3.0, door_width=3.25)
        c2 = by_key(p, "fixed_height_join_height")
        assert c2["feasible"] is True
        assert c2["meters"] == pytest.approx(T)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["join_height_m"] == pytest.approx(0.05)
        assert p["meters"] == pytest.approx(T), "R2：接高不参与算料 ⇒ 米数与不接高逐值相等"
        assert p["splice_times"] == 0
        assert p["panels"] is None

    def test_limit_constant_is_exactly_point_one(self):
        assert MAX_JOIN_GAP_M == pytest.approx(0.1), "裁定 5：接高/接宽都只能最多接 0.1 米"

    def test_gap_exactly_at_limit_is_feasible(self):
        # 边界：缺口**恰为** 0.1 ⇒ 可行（条件是 ≤，不是 <）
        p = plan(window_height=3.0, door_width=3.2)
        assert by_key(p, "fixed_height_join_height")["feasible"] is True
        assert p["join_height_m"] == pytest.approx(0.1)


# ── 判据 5：R2 —— 接高/接宽**不参与算料** ─────────────────────────────────────
class TestCriterion5JoinDoesNotEnterMeters:
    def test_join_height_meters_identical_to_no_join(self):
        """红证形态：把「加高条米数」（旧口径 `_splice` 的 `T + 段数 × 片宽`）加回去 ⇒ 必红。"""
        with_join = plan(window_height=3.0, door_width=3.25)
        assert with_join["join_height_m"] == pytest.approx(0.05)
        assert with_join["meters"] == pytest.approx(T), (
            "R2：接高不进算料 —— 与同一几何下不接高的 T 逐值相等"
        )

    def test_join_width_uses_p_minus_1_panels_only(self):
        # 「省一整幅」是 (P−1) 幅的料，**不是** (P−1) 幅 + 接宽布条（边角料，不另买布）
        p = plan(window_height=3.0, fixed_height_meters=5.65)
        assert p["meters"] == pytest.approx(2 * NEED_3_0), (
            "接宽那条 ≤0.1 米的布条不另买布 ⇒ 用料只算 P−1 幅"
        )
        assert p["panels"] == 2, "v1.2：`panels` = 实际买布幅数 = P − 1（与 splice_times 自洽）"

    def test_candidate5_is_always_infeasible_without_meters(self):
        """候选 5（倒幅 + 接高）：几何上恒不成立 ⇒ 恒不可行，**且不得编用料公式**。"""
        for kwargs in ({}, {"fixed_height_meters": 5.65}, {"window_height": 3.0, "door_width": 3.25}):
            p = plan(**kwargs)
            c5 = by_key(p, "fixed_width_join_height")
            assert c5["feasible"] is False, f"候选 5 恒不可行（{kwargs}）"
            assert c5["meters"] is None, "候选 5 **不得**编一个用料公式"
            assert "幅长按米" in c5["reason"] or "无上限" in c5["reason"], (
                "理由要写清「倒幅下幅长按米买、无上限 ⇒ 无需接高」"
            )
            assert c5["splice_times"] == by_key(p, "fixed_width")["splice_times"]


# ── 判据 6：R4 —— 拼接（N ≥ 1）时款式只能单色 ─────────────────────────────────
class TestCriterion6MixedStyleConflict:
    def test_mixed_style_with_splice_is_told_explicitly(self):
        """红证形态：删掉这条告知 ⇒ 必红。"""
        # ⚠️ H=3.0 ⇒ need_h 3.3 > D 2.8 ⇒ 定高买宽不可行 ⇒ 胜者带拼接（否则拼接为 0，无从冲突）
        p = plan(window_height=3.0, style=STYLE_MIXED)
        assert p["splice_times"] == 2 >= 1
        assert p["notices"], "R4：款式=拼色 且 拼接 ≥1 ⇒ 必须显式告知冲突"
        joined = " ".join(p["notices"])
        assert "拼色" in joined and "单色" in joined
        # `derive_plan` **不**回显 `style`（它是入参、不是推导结论）⇒ 款式只能由调用方自己保留，
        # 「不静默改款式」= 本函数**一个字都没改**调用方的入参（下面这条断言就是这个意思）
        assert "style" not in p, "不得把款式塞进推导结果（那会变成第二份款式真相源）"

    def test_mixed_style_without_splice_has_no_conflict_notice(self):
        # 定高买宽（零拼接）+ 拼色 ⇒ 无冲突（两款并行不违裁定 1）
        assert plan(window_height=3.0, style=STYLE_MIXED)["splice_times"] == 2  # 对照：有拼接
        single = plan(window_height=2.2, style=STYLE_MIXED)   # need_h 2.5 ≤ D ⇒ 定高买宽、零拼接
        assert single["splice_times"] == 0
        assert not single["notices"], "零拼接 + 拼色 ⇒ 无冲突，不得乱报"


# ── 判据 7：R5 —— 拼N次的名字（1/2/3，否则 null；不得发明「拼4次」） ─────────────
class TestCriterion7SpliceOptionNames:
    def test_three_splices_maps_to_pin_three(self):
        # P = 4 ⇒ splice_times = 3 ⇒ 拼3次
        p = plan(window_height=3.0, fixed_height_meters=9.0)   # ceil(9.0/2.8) = 4
        assert p["panels"] == 4
        assert p["splice_times"] == 3
        assert p["splice_option"] == "拼3次"

    def test_four_splices_has_no_option_name_and_is_told(self):
        """红证形态：补一个「拼4次」选项名 ⇒ 必红。"""
        p = plan(window_height=3.0, fixed_height_meters=12.0)  # ceil(12.0/2.8) = 5 ⇒ splice_times = 4
        assert p["panels"] == 5
        assert p["splice_times"] == 4
        assert p["splice_option"] is None, "R5：N ≥ 4 ⇒ null，**不得发明「拼4次」**"
        assert p["notices"], "R5：N ≥ 4 时显式告知需人工处理"
        assert "需人工处理" in " ".join(p["notices"])
        # 反向断言：**选项名表里不得有第 4 项**（上面 `p["splice_option"] is None` 已钉住输出侧）
        assert 4 not in SPLICE_OPTION_BY_TIMES

    def test_option_name_map_covers_only_one_to_three(self):
        assert SPLICE_OPTION_BY_TIMES == {1: "拼1次", 2: "拼2次", 3: "拼3次"}, (
            "R5：值域恰为 {1,2,3}（第 4 项以后不存在）"
        )

    def test_splice_option_names_match_routing_join_keys(self):
        """选项名是**冻结的 join key**（进工序/计件）⇒ 必须与 `routing.SPECIAL_OPTION_ROUTINGS` 逐字一致。

        差一个字 ⇒ 拼次工序与计件**静默失效**（少发工人钱）。
        """
        from app.production.routing import SPECIAL_OPTION_ROUTINGS
        for times, option in SPLICE_OPTION_BY_TIMES.items():
            assert option in SPECIAL_OPTION_ROUTINGS, f"{option} 不在 SPECIAL_OPTION_ROUTINGS（改一个字就静默失效）"


# ── 判据 9：R7 —— 人工覆盖（逐字采用、auto=false、0.1 上限仍然管） ──────────────
class TestCriterion9ManualOverride:
    def test_manual_cutting_mode_is_adopted_verbatim(self):
        p = plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH)
        assert p["auto"] is False
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["panels"] == 3
        assert p["meters"] == pytest.approx(3 * NEED_H)
        assert "人工" in p["reason"]

    def test_manual_join_height_within_limit(self):
        # 人工加接高：恒可行（本算例自动判不可行 —— 缺口为 0），但**不进算料**
        p = plan(cutting_mode=CUTTING_MODE_FIXED_HEIGHT, join_height_m=0.05)
        assert p["auto"] is False
        assert p["join_height_m"] == pytest.approx(0.05)
        assert p["meters"] == pytest.approx(T), "R2：人工加接高同样不参与算料"

    def test_manual_join_height_over_limit_is_rejected(self):
        with pytest.raises(ValueError, match="0.1"):
            plan(cutting_mode=CUTTING_MODE_FIXED_HEIGHT, join_height_m=0.2)

    def test_manual_join_width_over_limit_is_rejected(self):
        with pytest.raises(ValueError, match="0.1"):
            plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, join_width_m=0.2)

    def test_manual_join_width_must_be_positive(self):
        with pytest.raises(ValueError):
            plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, join_width_m=0.0)

    def test_manual_join_height_conflicts_with_rotated_mode(self):
        # 倒幅的幅长按米买、高方向无缺口 ⇒ 定宽买高 + 接高 是矛盾输入，不得静默丢掉
        with pytest.raises(ValueError, match="接高"):
            plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, join_height_m=0.05)

    def test_manual_join_width_conflicts_with_fixed_height_mode(self):
        with pytest.raises(ValueError, match="接宽"):
            plan(cutting_mode=CUTTING_MODE_FIXED_HEIGHT, join_width_m=0.05)

    def test_manual_splice_times_drives_panels_and_meters(self):
        p = plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, splice_times=1)
        assert p["auto"] is False
        assert p["splice_times"] == 1
        assert p["panels"] == 2
        assert p["splice_option"] == "拼1次"
        assert p["meters"] == pytest.approx(2 * NEED_H)

    def test_manual_splice_times_out_of_range_is_rejected(self):
        with pytest.raises(ValueError):
            plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, splice_times=4)
        with pytest.raises(ValueError):
            plan(cutting_mode=CUTTING_MODE_FIXED_WIDTH, splice_times=-1)

    def test_unknown_cutting_mode_is_rejected(self):
        with pytest.raises(ValueError):
            plan(cutting_mode="接高")


# ── 判据 10 的引擎半边：meters 是**单点**（候选与结论同源） ────────────────────
class TestSingleSourceOfMeters:
    def test_plan_meters_equals_winning_candidate_meters(self):
        for kwargs in ({}, {"fixed_height_meters": 5.65}, {"window_height": 3.0, "door_width": 3.25},
                       {"window_height": 1.0, "fixed_height_meters": 2.0}):
            p = plan(**kwargs)
            feasible = [c for c in p["candidates"] if c["feasible"]]
            # v1.3 选优序（用户 2026-09-22 裁定）：拼接最少 → 用料最少 → 接高接宽最少 → 表序
            best = min(
                feasible,
                key=lambda c: (c["splice_times"], c["meters"], _joins(c)),
            )
            assert p["meters"] == pytest.approx(best["meters"]), (
                f"plan.meters 必须**就是**胜出候选的用料（{kwargs}）"
            )

    def test_door_width_is_echoed(self):
        assert plan()["door_width"] == pytest.approx(D)

    def test_candidates_contain_all_five_in_table_order(self):
        p = plan()
        assert [c["key"] for c in p["candidates"]] == [
            "fixed_height",
            "fixed_height_join_height",
            "fixed_width",
            "fixed_width_join_width",
            "fixed_width_join_height",
        ], "候选表顺序 = 契约 §三 的表序（也是选优的第 ④ 顺位）"

    def test_every_candidate_carries_a_reason(self):
        for c in plan()["candidates"]:
            assert c["reason"], f"{c['key']} 缺理由 —— 用户裁定 3 要求逐个说清依据"


def _joins(candidate):
    return sum(
        1 for k in ("join_height_m", "join_width_m")
        if candidate.get(k) is not None
    )


# ── 用户裁定（2026-09-22，契约 v1.3）：选优 = **拼接次数优先** ───────────────────
class TestV13SpliceFirstRanking:
    """选优顺位 = **① 拼接次数最少 → ② 用料最少**（用户裁定：「无拼接优先：定高买宽可行就用它」）。

    为什么这条重要：v1.1 把「用料最少」放第 ① ⇒ 会为了省 0.6 米布去选**多 3 道可见拼缝**的倒幅
    （实证 `economy / 门幅 3.2 / 宽 6.6 双开 / need_h 2.8`：倒幅 11.2 米拼 3 次 vs 定高买宽
    11.8 米零拼接）—— 省的是布，付的是**工序与计件**，且拼缝是**可见**的。

    红证形态：把 `_rank` 换回 `(round(c["meters"],3), c["splice_times"], joins, order[key])`
    ⇒ 下面两条必红（第 ① 条返回 11.2/拼3次，第 ② 条 winner 变成 8.4）。
    """

    def test_adjudicated_case_picks_fixed_height_over_cheaper_rotated(self):
        """用户裁定原文算例：`economy / 门幅 3.2 / 宽 6.6 双开 / need_h 2.8`。"""
        # T（经济档 46 折）= 0.25×46 + 0.3 = 11.8；门幅 3.2 ⇒ need_h 2.8 ≤ 3.2 ⇒ 候选 1 可行且零拼接
        p = derive_plan(window_height=2.5, fixed_height_meters=11.8, door_width=3.2)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT, "无拼接优先 ⇒ 定高买宽可行就用它"
        assert p["splice_times"] == 0 and p["panels"] is None
        assert p["meters"] == pytest.approx(11.8), "既有断言 11.8 不必改（这正是裁定要的效果）"
        # 对照：倒幅更省布（4 幅 × 2.8 = 11.2）但拼 3 次 ⇒ 必须**不选**它
        c3 = by_key(p, "fixed_width")
        assert c3["feasible"] is True and c3["meters"] == pytest.approx(11.2)
        assert c3["splice_times"] == 3
        assert p["meters"] > c3["meters"], "新增了 0.6 米布，换来零拼接（用户裁定的取向）"

    def test_zero_splice_candidate_beats_cheaper_multi_splice_candidate(self):
        """顺位 ① 的**判别性**：存在「用料更少但带拼接」的可行候选时，仍选零拼接那条。"""
        # 门幅 4.4 ⇒ 接宽候选可行且最省布（3 幅 × 2.8 = 8.4，拼 2 次），但候选 1 零拼接（13.3）
        p = plan(door_width=4.4)
        feasible = [c for c in p["candidates"] if c["feasible"]]
        cheaper = [c for c in feasible if c["meters"] < p["meters"]]
        assert p["splice_times"] == 0, "winner 必须是零拼接那条"
        assert cheaper, "本算例**必须**存在「用料更少但带拼接」的候选（否则这条断言无判别力）"
        assert all(c["splice_times"] >= 1 for c in cheaper), "更省的那些都带拼接（正是被顺位①淘汰的）"


# ── 判据 8：回归不变量（derive_plan 是纯函数，不改既有调用口径） ────────────────
class TestRegressionInvariant:
    def test_derive_plan_does_not_mutate_inputs(self):
        config = {"hem_margin": 0.3}
        derive_plan(window_height=H, fixed_height_meters=T, door_width=D, config=config)
        assert config == {"hem_margin": 0.3}, "不得就地修改调用方的配置对象（第二份口径会在这里诞生）"

    def test_hem_margin_comes_from_config_not_module_constant(self):
        # need_h = 2.5 + 0.5 = 3.0；D=2.9 ⇒ 缺口 0.1 ≤ 0.1 ⇒ 候选 2 可行（若读模块常量 0.3 ⇒ 缺口 0.2 不可行）
        p = derive_plan(window_height=H, fixed_height_meters=T, door_width=2.9,
                        config={"hem_margin": 0.5})
        assert by_key(p, "fixed_height_join_height")["feasible"] is True, (
            "缺口判定必须读**租户配置**的 hem_margin（读模块常量 = 第二份口径）"
        )


# ── 契约订正 v1.2：**跨界不变量** `splice_times == panels − 1` ──────────────────
class TestPanelsSpliceTimesInvariant:
    """`panels` **恒等于「实际买布幅数」**，因此对**任何**返回值都必须满足：

        `plan["panels"] is None or plan["splice_times"] == plan["panels"] - 1`

    为什么这条比单点断言值钱：候选 4（倒幅 + 接宽）实际只买 `P−1` 幅 —— 若把它写成几何 `P`，
    界面会显示「P 幅」而商家只为 `P−1` 幅付钱、加工单也只拼 `P−2` 次（**同一件事两处口径**）。
    单点断言只钉得住一个算例，这条钉住**整类**矛盾（含将来新加的候选）。

    红证形态：把候选 4 的 `panels` 改回几何 `P` ⇒ 本条必红（`splice_times` 仍是 `P−2`）。
    """

    CASES = [
        {},                                                    # 定高买宽可行（候选 1）
        {"window_height": 3.0},                                # 纯倒幅（候选 3）
        {"window_height": 3.0, "fixed_height_meters": 5.65},    # 倒幅 + 接宽（候选 4，省一幅）
        {"window_height": 3.0, "door_width": 2.45},             # 定高买宽 + 接高（候选 2）
        {"window_height": 3.0, "fixed_height_meters": 12.0},    # 拼接 4 次（R5 边界）
        {"cutting_mode": CUTTING_MODE_FIXED_WIDTH, "splice_times": 3},
        {"cutting_mode": CUTTING_MODE_FIXED_HEIGHT},
        {"join_width_m": 0.05},
        {"join_height_m": 0.05},
        {"splice_times": 2},
    ]

    def test_invariant_holds_for_every_case(self):
        for kwargs in self.CASES:
            p = plan(**kwargs)
            panels, times = p["panels"], p["splice_times"]
            if panels is None:
                assert times == 0, f"定高买宽 ⇒ 零拼接（{kwargs}：splice_times={times}）"
            else:
                assert times == panels - 1, (
                    f"`splice_times` 必须恒等于 `panels − 1`（{kwargs}：panels={panels}, "
                    f"splice_times={times}）—— 界面显示的幅数与商家付钱的幅数必须是同一个数"
                )

    def test_candidate4_splice_times_is_panels_minus_two(self):
        """候选表里候选 4 的 `splice_times` = **P − 2**（省掉的那一幅同时省掉一次拼接）。

        红证形态：把候选 4 的 `splice_times` 从 `max(0, panels - 2)` 改成 `panels - 3` ⇒ 本条必红。
        为什么用「反推 P」而不是直接读 `p["panels"]`：`p["panels"]` 是**胜出方案**的买布幅数
        （v1.2 之后 = P − 1），而候选表里的 `splice_times` 是**该候选**的拼接次数 ——
        反推 P 才是在核候选表自己的数（不是拿结论核结论）。
        """
        # 候选 4 可行算例（T=5.65 / D=2.8 ⇒ P=3、remainder 0.05 ⇒ 用料 (P−1) × need_h = 6.6）
        p = plan(window_height=3.0, fixed_height_meters=5.65)
        c4 = by_key(p, "fixed_width_join_width")
        assert c4["feasible"] is True and c4["meters"] == pytest.approx(6.6)
        assert c4["splice_times"] == 1, "候选 4 的拼接次数 = P − 2 = 1（P=3）"

        # 对照：候选 3（纯倒幅）恒 P − 1 = 2（同一几何、同一候选表里两条必须**不同**）
        c3 = by_key(p, "fixed_width")
        assert c3["splice_times"] == 2, "候选 3 的拼接次数 = P − 1 = 2"
        assert c4["splice_times"] == c3["splice_times"] - 1, (
            "接宽省掉一整幅 ⇒ 同时省掉一次拼接（候选 4 = 候选 3 − 1）"
        )

    def test_join_width_case_buys_one_panel_less(self):
        """候选 4 的「实际买布幅数」逐值锚（P=3 ⇒ 买 2 幅）。"""
        p = plan(window_height=3.0, fixed_height_meters=5.65)
        assert (p["panels"], p["splice_times"]) == (2, 1)
        assert p["join_width_m"] == pytest.approx(0.05)
        assert p["meters"] == pytest.approx(2 * NEED_3_0)


class TestManualJoinWidthDoesNotAutoSavePanel:
    """人工给 `join_width_m`（未给 `splice_times`）⇒ **不自动省幅**（R7 逐字采用人工值）。

    🟡 **待用户裁定**（母单早期复核 (b)）：自动候选 4 是「省一整幅」，而人工路径不做这个推断。
    本实现的取舍 = 人工覆盖**逐字采用**（R7），但**必须在 `reason` 里写明**，
    否则商家会以为加了接宽就省了一幅（**错钱且无感**）。
    """

    def test_manual_join_width_does_not_reduce_meters(self):
        # 人工接宽 0.05：用料 = P × need_h = 3 × 3.3 = 9.9（**不**省幅）
        p = plan(window_height=3.0, join_width_m=0.05)
        assert p["auto"] is False
        assert p["panels"] == 3
        assert p["splice_times"] == 2
        assert p["meters"] == pytest.approx(3 * NEED_3_0)
        assert p["join_width_m"] == pytest.approx(0.05)

    def test_manual_join_width_reason_says_it_does_not_save_a_panel(self):
        p = plan(window_height=3.0, join_width_m=0.05)
        assert "不自动省幅" in p["reason"], (
            "人工接宽不省幅必须**写在理由里**（商家看不到就会按「省了一幅」理解 = 错钱）"
        )
        assert "拼次" in p["reason"], "理由要给出可行动路径（显式改拼次才省幅）"


# ── 🟡 待裁定项的落地行为（人工拼次 ≥ 1 但未给加工类型） ────────────────────────
class TestManualSpliceTimesWithoutCuttingMode:
    """人工拼次 ≥ 1 而没给 `cutting_mode` ⇒ **蕴含倒幅**（不报错）。

    理由（母单早期复核 (a) 的推荐方向）：零拼接的「定高买宽」是**一整幅布、根本拼不起来**
    ⇒ 拼次 ≥ 1 已把加工类型蕴含为倒幅 —— 这是裁定 4「拼接也允许人工加」的落点，
    不是另立口径（没有发明任何新取值）。报错会让「只想改拼次」的商家收到一个必须自己
    推断加工类型的错误，而那个推断是确定性的。

    红证形态：把 `_implied_mode()` 的 `splice_times >= 1 ⇒ 倒幅` 去掉 ⇒ 本条红（会走
    `_auto_mode()`，在定高买宽可行时抛 ValueError）。
    """

    def test_splice_times_without_mode_implies_rotated(self):
        # 默认几何下候选 1（定高买宽）可行且更省 —— 但人工要拼 2 次 ⇒ 必须走倒幅
        p = plan(splice_times=2)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_WIDTH
        assert p["auto"] is False, "人工拼次 ⇒ auto=false（R7）"
        assert p["panels"] == 3 and p["splice_times"] == 2
        assert p["meters"] == pytest.approx(3 * NEED_H)
        assert "蕴含" in p["reason"], "理由要说明「为什么走了倒幅」（不静默改判）"

    def test_implied_mode_uses_the_same_ranking_as_selection(self):
        """**`_implied_mode()`（只给拼次不给加工类型时用）必须与选优同一份 `_rank`**。

        判别性算例：`T=13.3 / D=4.4` ⇒ 倒幅 3 幅 × 2.8 = **11.2**（拼 2 次）比定高买宽 **13.3**
        （零拼接）更省布 ⇒ 「用料优先」的 key 会推出**定宽买高**，与本实现的选优**结论不一致**
        （同一条口径两份实现 = 本仓最忌的形态）。

        红证形态：把 `_auto_mode()` 里的 `min(feasible, key=_rank)` 换回
        `key=lambda c: (round(c["meters"], 3), c["splice_times"])` ⇒ 本条必红（返回定宽买高）。
        """
        p = plan(door_width=4.4, fixed_height_meters=13.3, splice_times=0)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT, (
            "拼次优先：零拼接的定高买宽（13.3）胜过拼 2 次的倒幅（11.2）"
        )
        assert p["meters"] == pytest.approx(13.3)
        # 对照：被顺位 ① 淘汰的那条确实更省布（否则本条无判别力）
        assert by_key(p, "fixed_width")["meters"] == pytest.approx(11.2)

    def test_splice_times_zero_still_auto_picks(self):
        # `splice_times=0` 不蕴含倒幅 ⇒ 仍走自动择路（本几何选定高买宽）
        p = plan(splice_times=0)
        assert p["cutting_mode"] == CUTTING_MODE_FIXED_HEIGHT
        assert p["auto"] is False
        assert p["meters"] == pytest.approx(T)


# ── 口径分裂的**登记守卫**：旧通路（`resolve_fabric_plan`）仍是旧口径 ─────────────
class TestLegacySplicePathStaysLegacy:
    """把「旧通路仍是旧口径」钉住（issue #5201 复核要求，防将来有人顺手改了却没人知道）。

    ## 分裂事实（**照实登记，不是遗漏**）

    | 通路 | 触达条件 | 「接高」口径 |
    |---|---|---|
    | `resolve_fabric_plan._splice()` | `build_quote(fabric_widths=[...])`（`/production/door-width-plan`）或显式 `cutting_mode="接高"` | **旧**：缺口多大都行 + 加高条按片宽另买布 |
    | `derive_plan()` | 三项输入（`fabric_width` 通路）—— 下单页 | **新**：缺口 ≤0.1 米 + **不参与算料**（裁定 5） |

    **为什么不统一**：统一会把 ai-agent **报价侧**的既有结果静默改掉（blast radius 超出本单范围），
    且用户 2026-09-22 的裁定只针对**下单链路** ⇒ 留作跟随 issue（需用户裁定）。

    红证形态：把 `_splice()` 换成新口径（上限 0.1 米 / 不另买布）⇒ 本条必红。
    """

    def test_legacy_splice_has_no_gap_limit_and_buys_extra_strips(self):
        from app.tools.curtain_calc import CUTTING_MODE_SPLICE, resolve_fabric_plan

        plan = resolve_fabric_plan(
            window_height=3.0, fixed_height_meters=1.6, door_widths=[2.8],
            open_count=1, cutting_mode=CUTTING_MODE_SPLICE,
        )
        assert plan["splice"] is True
        # 旧口径 ①：**缺口 0.5 米也照接**（新口径下 > 0.1 米即不可行 —— 两个口径在此**结论相反**）
        assert plan["splice_gap"] == pytest.approx(0.5)
        # 旧口径 ②：加高条**按片宽另买布**（1 段 × 片宽 1.6 米 = 3.2 米总料）
        assert plan["splice_strips"] == 1
        assert plan["meters"] == pytest.approx(3.2)

    def test_same_inputs_diverge_between_the_two_paths(self):
        """同一几何下两条通路**结论不同** —— 这就是被登记的分裂（不是 bug 被藏起来）。"""
        from app.tools.curtain_calc import CUTTING_MODE_SPLICE, resolve_fabric_plan

        legacy = resolve_fabric_plan(
            window_height=3.0, fixed_height_meters=1.6, door_widths=[2.8],
            open_count=1, cutting_mode=CUTTING_MODE_SPLICE,
        )
        modern = derive_plan(window_height=3.0, fixed_height_meters=1.6, door_width=2.8)
        assert legacy["meters"] == pytest.approx(3.2), "旧口径：T + 加高条 1.6"
        assert modern["join_height_m"] is None, "新口径：缺口 0.5 > 0.1 ⇒ 不得判接高"
        assert modern["meters"] == pytest.approx(3.3), "新口径：倒幅（P=1）按幅长 3.3 米买 ⇒ 1 幅"
        assert modern["meters"] != legacy["meters"], "两条通路在同一几何上给出**不同**的用料"
