# case_ids: CH-042, OR-032
"""接高口径**统一**的四条判据 + 注入式红证（issue #5213）。

用户 2026-09-23 裁定：**「乙 = 统一到新口径」** + 回落路线 **「B」**（缺口超限 ⇒ 倒幅）。

## 生效口径（`resolve_fabric_plan`，显式 `cutting_mode` + 候选门幅集）

| 情形 | 行为 |
|---|---|
| 定高买宽**可行** | `_fixed_height()`（**不变**） |
| 不可行 **且缺口 ≤ `MAX_JOIN_GAP_M`（0.1 米）** | **接高**：`splice=True`、`splice_gap` = 物理缺口、`splice_strips = 0`、**`meters = T`** |
| 不可行 **且缺口 > `MAX_JOIN_GAP_M`** | **回落 `_fixed_width()`（倒幅）** |

⚠️ 已知并接受：显式要求「接高」而缺口超限 ⇒ **静默改成倒幅**（B 的固有代价，用户已选）。

## 四条判据

判据本体 = 本文件的 `criterion_1..4`（**同一份函数**既给绿测也给红测用）；每条的红证 =
对**真源码**做**单点变异**后重跑同一判据 ⇒ 必须翻成 `False`（`TestRedEvidenceByMutation`）。
"不会红的断言 = 空断言"，故红证与绿测共用判据本体，而不是各写一份措辞。

| # | 判据 | 红证（单点变异） |
|---|---|---|
| 1 | 缺口 > 0.1 ⇒ 倒幅、`splice=False` | `if not _join_gap_ok(gap):` → `if False:`（= 恢复「缺口多大都行」） |
| 2 | 缺口 ≤ 0.1 ⇒ `splice=True` 且 `meters = T`、`splice_strips = 0` | `_splice()` 米数/段数改回旧口径（`meters = T + 3.3`、`splice_strips = 1`） |
| 3 | **agent 报价侧逐值不变**（两条通路**都不传** `cutting_mode`）：240 + 240 例快照摘要逐位相等（现行锚 = `AGENT_QUOTE_DIGEST_AFTER_5060`，**#5060 重锚**，见下方 ③） | `_fixed_width()` 的米数漂 `+0.1`（⚠️ 漂 `+0.001` 会被 `ceil_to_step` 的 0.1 进位步长**吸收** ⇒ 红证空跑，实测踩过） |
| 4 | 阈值**与 `derive_plan` 同源**：判定点只调 `_join_gap_ok`，**不内联**该数值 | `_splice()` 里内联 `gap <= 0.1` |

判据 4 钉的是「**判定点不内联数值**」，不是「文件里不许出现 `0.1`」—— 后者会因
`meters_rounding_step = 0.1` / `MAX_JOIN_GAP_M` 定义本身等**正交用途**误红（判别力不足）。

## ③ 的快照摘要取自**改动前**（`origin/main`）

`AGENT_QUOTE_DIGEST_BEFORE_5213` 是在**未改动的检出**上跑同一张网格算出来的
（sha256 of canonical JSON）⇒ 绿 = 「逐值不变」；它同时也证明判据 3 是**回归不变量**而不是
「跟着实现一起改钉的期望值」。网格 = 10 成品宽 × 6 成品高 × 2 褶倍 × 2 对花档，
每条算例各跑 `fabric_widths=[2.8, 3.2]` 与 `fabric_width=2.8` 两条 agent 真实通路。

🔴 **2026-09-25 重锚（issue #5060，用户裁定「统一取整」）**：**单一门幅路径**（`fabric_width=2.8`）
的分幅取整由浮点 `ceil` 改为**毫米整数**（与候选路径**同一函数** `_panels_for_door`）⇒
本网格里 `single|4.2|{2.75,3.0,3.3,3.9}|2.0|{False,True}` **8/480** 行的 `panels` 由 **4 → 3**
（`4.2 × 2 ÷ 2.8 = 3.0000000000000004` ⇒ 浮点**多算 1 幅**），米数/金额随之**下降一幅长**
（实测 `single|4.2|3.0|2.0|False`：13.2 → 9.9 米、总额 1717.6 → 1341.4）。
⇒ 判据 3 的锚**改为 `AGENT_QUOTE_DIGEST_AFTER_5060`**（原锚保留在上面，仍被 `TestReAnchor…` 引用）；
候选路径（`fabric_widths=…`）**逐值不变**（240 例全中）。
**重锚不是「跟着实现改钉期望值」**：`TestReAnchorIsFullyExplainedBy5060` 用**注入式**证明——
把**那两处**取整还原成浮点后，摘要**恰好**回到 `AGENT_QUOTE_DIGEST_BEFORE_5213`（逐位相等）
⇒ 差量 100% 由本单的两处取整解释、别无其它改动；差量行清单亦被逐行钉住（`DELTA_ROWS_5060`）。
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path

import pytest

SRC_PATH = Path(__file__).resolve().parents[1] / "app/tools/curtain_calc.py"

T = 6.6                     # 成品宽 3.0 × 褶倍 2.0（本文件基准算例的定高买宽用料）
CANDIDATES = [2.8, 3.2]
OVER_LIMIT_HEIGHT = 3.9     # need_h = 4.2 > 3.2 ⇒ 缺口 1.0（> 上限）
AT_LIMIT_HEIGHT = 3.0       # need_h = 3.3 − 3.2 = 缺口 0.1（恰为上限）

#: 判据 3 的**改动前**快照摘要（240 + 240 例；见模块 docstring）
AGENT_QUOTE_DIGEST_BEFORE_5213 = (
    "f5e2e258628a9d5425bad78e87dc8f23b3568a3d9002411892967834333e8404"
)

#: 判据 3 的**现行**锚 = #5060（统一取整）**之后**的摘要。重锚理由与内容级证明见模块 docstring ③
#: 与 `TestReAnchorIsFullyExplainedBy5060`（还原两处取整 ⇒ 摘要逐位回到上面那个原锚）。
AGENT_QUOTE_DIGEST_AFTER_5060 = (
    "e55954690b48094f613994bd444ec92b209eeafeb035e5224e8b8ef13f24539e"
)

#: 判据 3 网格（与「改动前」那次测量逐值同参）—— 只放 agent 工具参数表里**真实存在**的两种调用形态
GRID_WIDTHS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.2, 5.0)
GRID_HEIGHTS = (1.0, 2.4, 2.75, 3.0, 3.3, 3.9)
GRID_FULLNESS = (1.8, 2.0)
GRID_PATTERNS = ((False, 0.0), (True, 0.4))


# ── 判据本体（绿测与红测**共用**同一份函数）────────────────────────────────────
def criterion_1(src: str, mod: dict) -> bool:
    """缺口 > `MAX_JOIN_GAP_M` ⇒ **倒幅**（`cutting_mode = 定宽买高`、`splice=False`），不再接高。"""
    plan = mod["resolve_fabric_plan"](
        window_height=OVER_LIMIT_HEIGHT, fixed_height_meters=T, door_widths=CANDIDATES,
        cutting_mode=mod["CUTTING_MODE_SPLICE"],
    )
    return plan["cutting_mode"] == mod["CUTTING_MODE_FIXED_WIDTH"] and plan["splice"] is False


def criterion_2(src: str, mod: dict) -> bool:
    """缺口 ≤ `MAX_JOIN_GAP_M` ⇒ 接高且 `meters == T`（不含加高条）、`splice_strips == 0`。"""
    plan = mod["resolve_fabric_plan"](
        window_height=AT_LIMIT_HEIGHT, fixed_height_meters=T, door_widths=CANDIDATES,
        cutting_mode=mod["CUTTING_MODE_SPLICE"],
    )
    return (
        plan["splice"] is True
        and plan["cutting_mode"] == mod["CUTTING_MODE_FIXED_HEIGHT"]
        and plan["splice_gap"] == pytest.approx(mod["MAX_JOIN_GAP_M"])
        and plan["splice_strips"] == 0
        and plan["meters"] == pytest.approx(T)
    )


def agent_quote_rows(mod: dict) -> list:
    """agent 报价侧两条真实通路（**都不传 `cutting_mode`**）的逐值快照。"""
    rows = []
    for width in GRID_WIDTHS:
        for height in GRID_HEIGHTS:
            for fullness in GRID_FULLNESS:
                for has_pattern, repeat in GRID_PATTERNS:
                    common = dict(window_width=width, window_height=height, fullness=fullness,
                                  fabric_price=98, has_pattern=has_pattern, pattern_repeat=repeat)
                    for label, extra in (("widths", {"fabric_widths": CANDIDATES}),
                                         ("single", {"fabric_width": 2.8})):
                        quote = mod["build_quote"](**common, **extra)
                        rows.append({
                            "case": f"{label}|{width}|{height}|{fullness}|{has_pattern}",
                            "result": {k: round(v, 6) if isinstance(v, float) else v
                                       for k, v in sorted(quote.items())},
                        })
    return rows


def agent_quote_digest(mod: dict) -> str:
    blob = json.dumps(agent_quote_rows(mod), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf8")).hexdigest()


def criterion_3(src: str, mod: dict) -> bool:
    """**agent 报价侧逐值不变**：两条通路的结果快照与**改动前**逐位相等。"""
    rows = agent_quote_rows(mod)
    if len(rows) != 480:  # fail-closed：网格被改小/踩空 ⇒ 判据会静默变弱
        raise AssertionError(f"判据 3 的网格应为 480 例，实得 {len(rows)} 例 —— 不得静默缩表")
    return agent_quote_digest(mod) == AGENT_QUOTE_DIGEST_AFTER_5060


#: 判定点（接高阈值）—— 两处都必须**只调**共享判据 `_join_gap_ok`
_JOIN_JUDGEMENT_SITES = ("derive_plan", "_splice")


def criterion_4(src: str, mod: dict) -> bool:
    """阈值**同源**：两处接高判定都只调 `_join_gap_ok`，且**不内联**该数值。"""
    tree = ast.parse(src)
    threshold = mod["MAX_JOIN_GAP_M"]
    for name in _JOIN_JUDGEMENT_SITES:
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if fn is None:
            return False
        if "_join_gap_ok(" not in ast.get_source_segment(src, fn):
            return False
        for node in ast.walk(fn):
            if (isinstance(node, ast.Constant) and isinstance(node.value, float)
                    and node.value == threshold):
                return False
    return True


# ── 变异机具（真源码 → 单点变异 → 重新 exec）────────────────────────────────
#: 块定位一律**先锚到 `resolve_fabric_plan`**：`_fixed_width` / 派发语句在文件里**各有两份**
#: （`derive_plan` 也有一份同名内嵌函数与同名分支）⇒ 裸 `index()` 会锚到错的那一份，
#: 结果是「变异没生效而判据仍绿」的**假红证**（实测踩过：命中 0 次）。
RESOLVE_START = "def resolve_fabric_plan("
SPLICE_START = "    def _splice() -> Dict[str, Any]:"
FIXED_WIDTH_START = "    def _fixed_width() -> Dict[str, Any]:"
CUTTING_MODE_DISPATCH = "    if cutting_mode == CUTTING_MODE_FIXED_WIDTH:"


def _replace_in_block(src: str, start: str, end: str, old: str, new: str) -> str:
    """在 `resolve_fabric_plan` 内 `start`..`end` 之间的**函数块**做单点替换（锚点须唯一命中）。"""
    scope = src.index(RESOLVE_START)
    begin = src.index(start, scope)
    stop = src.index(end, begin)
    block = src[begin:stop]
    hits = block.count(old)
    assert hits == 1, f"变异锚点命中 {hits} 次（要求恰好 1 次）：{old!r}"
    return src[:begin] + block.replace(old, new) + src[stop:]


def load_variant(src: str) -> dict:
    """把（可能已变异的）模块源码 exec 成一个独立命名空间。"""
    ns: dict = {"__name__": "curtain_calc_variant", "__file__": str(SRC_PATH)}
    exec(compile(src, str(SRC_PATH), "exec"), ns)
    return ns


def _real() -> tuple:
    src = SRC_PATH.read_text(encoding="utf8")
    return src, load_variant(src)


# 四条判据 × 各自的红证变异
MUTATIONS = {
    "1": lambda src: _replace_in_block(
        src, SPLICE_START, FIXED_WIDTH_START,
        "        if not _join_gap_ok(gap):", "        if False:  # 旧口径：缺口多大都行",
    ),
    "2": lambda src: _replace_in_block(
        _replace_in_block(
            src, SPLICE_START, FIXED_WIDTH_START, '            "meters": total,',
            '            "meters": total + 3.3,  # 旧口径：加高条另买布',
        ),
        SPLICE_START, FIXED_WIDTH_START, '            "splice_strips": 0,',
        '            "splice_strips": 1,',
    ),
    "3": lambda src: _replace_in_block(
        src, FIXED_WIDTH_START, CUTTING_MODE_DISPATCH,
        '            "meters": panels * (need_height + repeat),',
        '            "meters": panels * (need_height + repeat) + 0.1,  # 漂一点',
    ),
    "4": lambda src: _replace_in_block(
        src, SPLICE_START, FIXED_WIDTH_START,
        "        if not _join_gap_ok(gap):", "        if not (gap <= 0.1):  # 内联第二份阈值",
    ),
}
CRITERIA = {"1": criterion_1, "2": criterion_2, "3": criterion_3, "4": criterion_4}


# ── #5060 重锚的**内容级**证明（不是「跟着实现改钉期望值」）─────────────────────
#: #5060 的两处取整落点（**逐字**）—— 还原成**改前的浮点形态**后，摘要必须**恰好**回到 #5213 的原锚
PANELS_ROUNDING_SITES = (
    ("    panels = _panels_for_door(window_width * fullness, fabric_width)",
     "    panels = math.ceil(window_width * fullness / fabric_width)"),
    ("                panels = _panels_for_door(window_width * N, fabric_width)",
     "                panels = math.ceil(window_width * N / fabric_width)"),
)

#: #5060 在 agent 单一门幅通路上改变的行（**全量** 8/480；值 = 网格键，与 `agent_quote_rows` 同构）
DELTA_ROWS_5060 = (
    "single|4.2|2.75|2.0|False", "single|4.2|2.75|2.0|True",
    "single|4.2|3.0|2.0|False", "single|4.2|3.0|2.0|True",
    "single|4.2|3.3|2.0|False", "single|4.2|3.3|2.0|True",
    "single|4.2|3.9|2.0|False", "single|4.2|3.9|2.0|True",
)


class TestReAnchorIsFullyExplainedBy5060:
    """#5060（统一取整）重锚了判据 3 的摘要 —— 差量必须**只**由那两处取整解释。"""

    def test_reverting_the_two_rounding_sites_reproduces_the_pre_5060_anchor(self):
        """注入式：把两处取整还原成浮点 ⇒ 摘要**逐位**回到 #5213 的原锚（差量 = 本单，别无其它）。"""
        src, mod = _real()
        assert agent_quote_digest(mod) == AGENT_QUOTE_DIGEST_AFTER_5060, (
            "现行源与重锚摘要不符 ⇒ 又有人改了行为却没重锚（或重锚值抄错）"
        )
        reverted = src
        for old, new in PANELS_ROUNDING_SITES:
            hits = reverted.count(old)
            assert hits == 1, (
                f"取整落点锚点命中 {hits} 次（要求恰好 1 次）：{old!r} —— 锚点漂移会让本证明空跑"
            )
            reverted = reverted.replace(old, new)
        assert agent_quote_digest(load_variant(reverted)) == AGENT_QUOTE_DIGEST_BEFORE_5213, (
            "把两处取整还原成浮点后，摘要没有回到 #5213 的原锚 ⇒ 重锚的差量**不止**由 #5060 解释"
            "（有别的行为改动混进来了，必须逐行查清后再决定重锚）"
        )

    def test_the_delta_rows_are_exactly_the_single_door_boundary_rows(self):
        """全量差量行 = 「单一门幅路径 + 总用料恰为门幅整数倍」那 8 行（多/少一行都说明影响面不符）。"""
        _src, mod = _real()
        door = 2.8
        actual = []
        for width in GRID_WIDTHS:
            for height in GRID_HEIGHTS:
                for fullness in GRID_FULLNESS:
                    for has_pattern, repeat in GRID_PATTERNS:
                        quote = mod["build_quote"](
                            window_width=width, window_height=height, fullness=fullness,
                            fabric_price=98, has_pattern=has_pattern, pattern_repeat=repeat,
                            fabric_width=door,
                        )
                        if quote["formula_used"] != "fixed_width":
                            continue
                        if quote["panels"] != math.ceil(width * fullness / door):
                            actual.append(f"single|{width}|{height}|{fullness}|{has_pattern}")
        assert tuple(actual) == DELTA_ROWS_5060, (
            f"#5060 在 agent 单一门幅通路上改变的行 = {actual}（期望 {list(DELTA_ROWS_5060)}）—— "
            "多一行 = 有未登记的改钱面；少一行 = 该改的没改（边界又在多算幅数）"
        )


# ── 绿：四条判据在真源码上成立 ────────────────────────────────────────────────
class TestCriteriaHold:
    def test_1_over_limit_gap_rotates(self):
        assert criterion_1(*_real()) is True

    def test_2_within_limit_join_charges_only_the_fixed_height_total(self):
        assert criterion_2(*_real()) is True

    def test_3_agent_quote_paths_are_value_identical(self):
        assert criterion_3(*_real()) is True

    def test_4_threshold_has_a_single_source(self):
        assert criterion_4(*_real()) is True

    def test_no_criterion_is_vacuous_on_the_real_source(self):
        """四条一起成立，且判据 3 的摘要**非空占位**（480 例、无 `splice` 命中）。"""
        src, mod = _real()
        assert [CRITERIA[k](src, mod) for k in ("1", "2", "3", "4")] == [True] * 4
        rows = agent_quote_rows(mod)
        assert sum(1 for r in rows if r["result"].get("splice")) == 0, (
            "agent 两条通路本就不该命中接高（实测 0/480）—— 命中即为口径漏进报价侧"
        )


# ── 红：每条判据都能被**单点变异**打红（且不与别的判据一起红 ⇒ 有判别力）───────
class TestRedEvidenceByMutation:
    """红证形态 = 「改坏一处 ⇒ **那一条**判据翻 False」，逐条独立。"""

    @pytest.mark.parametrize("key", ["1", "2", "3", "4"])
    def test_mutation_flips_its_own_criterion(self, key):
        src, _ = _real()
        mutated = MUTATIONS[key](src)
        assert mutated != src, "变异没生效 ⇒ 红证会空跑（fail-closed）"
        assert CRITERIA[key](mutated, load_variant(mutated)) is False, (
            f"判据 {key} 的红证没变红 ⇒ 该判据是空断言"
        )

    def test_mutation_1_keeps_the_other_criteria_green(self):
        # 「缺口多大都行」只影响判据 1；缺口 ≤ 0.1 的算例（判据 2）与报价侧（判据 3）不受影响。
        # ⚠️ 判据 4**会**跟着红（该变异同时抹掉了共享判据的调用）—— 那正是判据 4 要抓的形态，
        # 故此处**不**把它列进「应保持绿」的集合（诚实的耦合登记，不是漏测）。
        src, _ = _real()
        mutated = MUTATIONS["1"](src)
        mod = load_variant(mutated)
        assert [criterion_2(mutated, mod), criterion_3(mutated, mod)] == [True, True]

    def test_mutation_4_keeps_the_other_criteria_green(self):
        # 内联 0.1 **数值等价** ⇒ 行为面（判据 1/2/3）全绿，只有「同源」这条（判据 4）红
        src, _ = _real()
        mutated = MUTATIONS["4"](src)
        mod = load_variant(mutated)
        assert [criterion_1(mutated, mod), criterion_2(mutated, mod), criterion_3(mutated, mod)] \
            == [True, True, True]


# ── 逐条可读的行为断言（判据之外，把口径写清楚）────────────────────────────────
class TestUnifiedRuleInPlainAssertions:
    def test_over_limit_rotated_meters(self):
        _, mod = _real()
        plan = mod["resolve_fabric_plan"](
            window_height=OVER_LIMIT_HEIGHT, fixed_height_meters=T, door_widths=CANDIDATES,
            cutting_mode=mod["CUTTING_MODE_SPLICE"],
        )
        assert plan["cutting_mode"] == "定宽买高"
        assert plan["panels"] == 3, "ceil_mm(6.6 / 3.2) = 3 幅"
        assert plan["meters"] == pytest.approx(12.6), "3 幅 × 4.2 米"

    def test_within_limit_join_reports_the_gap_but_charges_nothing_extra(self):
        _, mod = _real()
        plan = mod["resolve_fabric_plan"](
            window_height=AT_LIMIT_HEIGHT, fixed_height_meters=T, door_widths=CANDIDATES,
            cutting_mode=mod["CUTTING_MODE_SPLICE"],
        )
        assert plan["splice_gap"] == pytest.approx(0.1), "缺口照报（读面要用）"
        assert plan["meters"] == pytest.approx(T), "但不进米数"

    def test_feasible_fixed_height_is_untouched(self):
        """③ 定高买宽**可行**时 `_fixed_height()` 逐值不变（统一不该动它）。"""
        _, mod = _real()
        plan = mod["resolve_fabric_plan"](
            window_height=2.4, fixed_height_meters=T, door_widths=CANDIDATES,
            cutting_mode=mod["CUTTING_MODE_SPLICE"],
        )
        assert plan["cutting_mode"] == "定高买宽"
        assert plan["splice"] is False
        assert plan["meters"] == pytest.approx(T)
        assert plan["door_width"] == 2.8