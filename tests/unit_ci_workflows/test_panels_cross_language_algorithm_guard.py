# case_ids: OR-040
"""分幅数（`panels`）的**算法级**跨语言守卫（issue #5038）。

## 病根（本单要治的静默失效形态）

`panels`（定宽买高时的分幅数）在两侧各有一份实现，而**取整口径不同**：

| 侧 | 落点 | 现式 |
|---|---|---|
| 真值源（引擎） | `backend/ai-agent-service/app/tools/curtain_calc.py` 的 `resolve_fabric_plan` | `-(-_mm(total) // max(1, _mm(ge)))` —— **毫米整数**向上取整（`_mm = int(round(v*1000))`） |
| 副本（前端） | `frontend/admin-web/src/lib/door-width-plan.ts` 的 `resolveCutPlan` | 改前 = 浮点 `Math.max(1, Math.ceil(need / g_eff))` |

总用料**恰为门幅整数倍**时，浮点除法给出 `1.0000000000000002` 这类值 ⇒ `ceil` **多算 1 幅**
（实测：`W=1.1` / 门幅 `2.8` / 褶倍 `2` ⇒ `(1.1 + 0.3) × 2 = 2.8000000000000003` ⇒ 浮点 **2** 幅 /
引擎 **1** 幅）。而幅数进 `(panels, 门幅)` **双键排序** ⇒ 还会**翻转选中的门幅**
（`W=1.1 / [2.8, 3.2]`：真值两档并列 1 幅 ⇒ 取较小 **2.8**；浮点 ⇒ 选中 **3.2**）。

## 为什么既有守卫看不到（本单补的就是这一面）

`tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py` 钉的是**常量值**（`0.3` vs `0.3`）
与注释引文 —— 它对**算法**（浮点 vs 毫米整数）**结构上看不见**。本守卫补算法面：
一份**共享 golden 算例表**（`tests/fixtures/panels-cross-language-golden.json`）被**三侧**共读：

| 腿 | 落点 | 跑什么 |
|---|---|---|
| ① 引擎腿 | `backend/ai-agent-service/tests/test_curtain_calc_fabric_plan.py` | **真引擎**（`resolve_fabric_plan`）逐候选 + 选中档比对 |
| ② 静态腿 | **本文件** | 照源复算（不 import 引擎）+ 钉 TS 源码**不再出现浮点直除形态** + 三腿共读同一张表 |
| ③ 前端腿 | `frontend/admin-web/tests/unit/lib/door-width-plan.test.ts` | **真 TS**（`resolveCutPlan`）逐候选 + 选中档比对 |

⇒ 「同组输入两侧 `panels` 逐值相等」不再靠人读，而是**可执行**判据；任一侧改回浮点即红。

## 判据（全部**读源**；本文件**不写死任何门幅 / 幅数**）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 引擎侧**仍是**毫米整数式：`_mm` 定义 + `-(-_mm(total) // max(1, _mm(ge)))` 逐字在源里 | 把引擎那行改成 `math.ceil(total / ge)` ⇒ 红 |
| C2 | TS 源码里**不得**再出现浮点直除形态（`Math.ceil(<x> / <y>.effectiveDoorWidth)` / `Math.ceil(<x> / selectedEffective)`） | 把 `panelsForFixedWidth(...)` 改回 `Math.max(1, Math.ceil(need / c.effectiveDoorWidth))` ⇒ 红 |
| C3 | TS 源码里**必须**有毫米整数形态（`Math.round(<x> * 1000)` + `Math.ceil(toMillimeters(` + `Math.max(1, toMillimeters(` + 候选过滤 `effectiveDoorWidth > 0`） | 删掉 `toMillimeters` / 去掉候选过滤 ⇒ 红 |
| C4 | golden 表逐例与**引擎式复算**逐值相等（逐候选 + 选中档 + 全剔除 ⇒ `undecidable`） | 改表里任一 `panels` ⇒ 红 |
| C5 | **判别力下界（反恒真）**：表里**至少一例**「浮点式 ≠ 引擎式」（否则这张表证明不了任何事） | 把边界算例换成非整数倍（两式同值）⇒ 红 |
| C6 | 三腿**真的共读同一张表**（引擎腿与前端腿都读 `panels-cross-language-golden.json`） | 前端腿改成自带期望值 ⇒ 红 |
| C7 | 表的**前提可判**：候选已升序去重、`panelsPerCandidate` 与候选同长、`undecidable` 例确实全被剔除 | 把候选写成乱序 / 让 `panelsPerCandidate` 短一格 ⇒ 红 |

⚠️ **本守卫不 import 被测引擎**（`app` 包的导入期需要完整 `.env` ⇒ 会红于环境而非红于口径）
—— 与 `test_panels_formula_split_audit.py` / `test_hem_margin_cross_language_drift.py` 同族：
**照源里的公式复算**，并由 C1 钉住「源里真的还是那个式」。

⚠️ **照实登记（已知边界，不在本单范围）**：`_mm` 的舍入在**半毫米**（`v*1000` 恰为 `.5`）上
两侧不同 —— Python `round` 是**银行家舍入**、JS `Math.round` 是**四舍五入**
（`2.7505 ⇒ Python 2750 / JS 2751`）。该形态要求输入精确落在半毫米上，**不在业务输入形态内**
（宽高按厘米报、褶倍是一位小数）；C7 断言算例表**不含**该形态，故本表的等价性前提成立。
⚠️ 本表只钉**取整口径**；A 通路与 B1/B2 的 `side_margin` 差异是**另一件事**，登记在
`docs/design/craft-calc-and-fabric-routing.md` §4.5（issue #4760），**不在本单范围、未动**。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 共享 golden 算例表（**三腿共读**：本文件 + 引擎腿 + 前端腿）
GOLDEN_JSON = REPO_ROOT / "tests/fixtures/panels-cross-language-golden.json"
#: 真值源：算料引擎
CALC_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/curtain_calc.py"
#: 副本：前端下单页门幅规则
PLAN_TS = REPO_ROOT / "frontend/admin-web/src/lib/door-width-plan.ts"
#: 前端腿（③）：必须**读同一张表**（C6）
TS_TEST = REPO_ROOT / "frontend/admin-web/tests/unit/lib/door-width-plan.test.ts"
#: 引擎腿（①）：必须**读同一张表**（C6）
ENGINE_TEST = REPO_ROOT / "backend/ai-agent-service/tests/test_curtain_calc_fabric_plan.py"

#: 引擎侧的分幅式（C1：逐字，**不得**退化成浮点）
ENGINE_PANELS_EXPR = "-(-_mm(total) // max(1, _mm(ge)))"
#: 引擎侧 `_mm` 的舍入式（C1）
ENGINE_MM_EXPR = "int(round(float(value) * _MM))"

#: C2：**禁止**出现的浮点直除形态（就是改前那两处；`\w+` 允许任意局部变量名）
FORBIDDEN_FLOAT_FORMS = (
    r"Math\.ceil\(\s*\w+\s*/\s*\w+\.effectiveDoorWidth\s*\)",
    r"Math\.ceil\(\s*\w+\s*/\s*selectedEffective\s*\)",
)
#: C3：**必须**存在的毫米整数形态
REQUIRED_MM_FORMS = (
    (r"Math\.round\(\s*\w+\s*\*\s*1000\s*\)", "米 ⇒ 整数毫米的舍入（与引擎 `_mm` 同源）"),
    (r"Math\.ceil\(toMillimeters\(", "整数向上取整除法的被除数"),
    (r"Math\.max\(1,\s*toMillimeters\(", "除数下限（与引擎 `max(1, _mm(ge))` 同式）"),
    (r"effectiveDoorWidth\s*>\s*0", "候选过滤（与引擎 `float(g) > allow` 同式）"),
)

#: 半毫米边界（两侧舍入口径不同 ⇒ 算例表必须避开；见文件头「照实登记」）
_HALF_MM = 0.5
_EPS = 1e-9


def _read(path: Path) -> str:
    assert path.exists(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf8")


def _golden() -> dict:
    data = json.loads(_read(GOLDEN_JSON))
    cases = data.get("cases")
    assert cases, "golden 算例表为空 —— 判据会空跑（fail-closed，不得静默通过）"
    return data


def _py_float(source: str, name: str) -> float:
    """从引擎源里取模块级浮点常量（取不到 ⇒ **直接失败**，不静默跳过）。"""
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", source, re.M)
    assert m, f"curtain_calc.py 里找不到常量 {name} —— 本守卫必须能读到真值（C4 的 `need` 依赖它）"
    return float(m.group(1))


def _mm(value: float) -> int:
    """与引擎 `_mm` **逐字同源**（C1 钉住源里那一行的形态）。"""
    return int(round(float(value) * 1000))


def _engine_panels(total: float, effective_door_width: float) -> int:
    """与引擎 `-(-_mm(total) // max(1, _mm(ge)))` **逐字同源**。"""
    return -(-_mm(total) // max(1, _mm(effective_door_width)))


def _float_panels(total: float, effective_door_width: float) -> int:
    """**改前的浮点式**（C5 的判别力下界基准；本文件任何判据都不用它出真值）。"""
    return max(1, math.ceil(total / effective_door_width))


def _round3(value: float) -> float:
    """与引擎 `round(g - allow, 3)` / TS `round3` 同口径（候选有效门幅）。"""
    return round(value, 3)


def _engine_candidates(candidates: list[float], allowance: float) -> list[float]:
    """与引擎同式的候选过滤：`float(g) > allow`（⇒ `g_eff > 0`）。"""
    return [g for g in candidates if g > allowance]


def _case_need(case: dict, side_margin: float) -> float:
    return (case["width"] + side_margin) * case["fullness"]


# ── C1：引擎侧仍是毫米整数式（源形态判据）────────────────────────────────────

def test_engine_source_uses_millimeter_integer_division() -> None:
    """C1：真值源的分幅式与 `_mm` 舍入式**逐字**仍在（改成浮点 ⇒ 红）。"""
    src = _read(CALC_PY)
    assert ENGINE_PANELS_EXPR in src, (
        f"引擎源里找不到分幅式「{ENGINE_PANELS_EXPR}」—— 真值源已改（改回浮点 / 换了写法）⇒ "
        "本守卫的复算基准与引擎脱钩，必须红（同步本守卫或撤回改动）"
    )
    assert ENGINE_MM_EXPR in src, (
        f"引擎源里找不到 `_mm` 的舍入式「{ENGINE_MM_EXPR}」—— 毫米整数口径的根没了 ⇒ 红"
    )
    assert re.search(r"_MM\s*=\s*1000", src), "引擎 `_MM` 比例常量不见了（米 ⇒ 毫米的换算基准）⇒ 红"


# ── C2 / C3：TS 侧不得再有浮点直除，且必须有毫米整数形态 ─────────────────────

def test_ts_source_has_no_float_direct_division() -> None:
    """C2：改前那两处浮点直除**不得**再出现（把 TS 改回浮点 ⇒ 红）。"""
    src = _read(PLAN_TS)
    for pattern in FORBIDDEN_FLOAT_FORMS:
        assert not re.search(pattern, src), (
            f"`frontend/admin-web/src/lib/door-width-plan.ts` 里又出现了浮点直除形态：/{pattern}/\n"
            "⇒ 总用料恰为门幅整数倍时会多算 1 幅（并可能翻转选中的门幅）。"
            "分幅数一律走 `panelsForFixedWidth`（毫米整数，与引擎同式）"
        )


def test_ts_source_has_millimeter_integer_forms() -> None:
    """C3：毫米整数形态与候选过滤**必须**在（删掉即失去与引擎的同式性）。"""
    src = _read(PLAN_TS)
    for pattern, why in REQUIRED_MM_FORMS:
        assert re.search(pattern, src), (
            f"`door-width-plan.ts` 里找不到「{why}」的形态 /{pattern}/ —— "
            "它已与引擎脱钩（浮点直除 / 无候选过滤）⇒ 红"
        )
    # 分幅助手必须被**两处**消费（`resolveCutPlan` 的候选排序 + `judgeDoorWidthChoice` 的所选幅数）
    assert src.count("panelsForFixedWidth(") >= 3, (
        "`panelsForFixedWidth` 只在声明处出现（无消费点）—— 判定处被内联回浮点 / 该助手已成死码 ⇒ 红"
    )


# ── C4 / C5 / C7：golden 表与引擎式复算逐值相等 + 判别力下界 + 前提可判 ────────

def test_golden_matches_engine_formula() -> None:
    """C4：逐例复算（引擎式）—— 逐候选幅数 / 选中档 / 全剔除 ⇒ 不可判定。"""
    side_margin = _py_float(_read(CALC_PY), "SIDE_MARGIN")
    assert side_margin > 0, "引擎 `SIDE_MARGIN` 读出来不是正数（解析口径变了，请同步本守卫）"
    for case in _golden()["cases"]:
        need = _case_need(case, side_margin)
        allowance = case["allowance"]
        kept = _engine_candidates(case["candidates"], allowance)
        expected = case["expected"]
        if expected["state"] == "undecidable":
            assert not kept, (
                f"{case['id']}：表里登记为 `undecidable`（候选全被有效余量剔除），"
                f"但按引擎式复算仍有候选存活 {kept} ⇒ 表与引擎式不符"
            )
            continue
        assert kept == case["candidates"], (
            f"{case['id']}：表里登记为有解，但引擎式会把候选剔除（存活 {kept} / 候选 {case['candidates']}）"
        )
        per_candidate = [
            _engine_panels(need, _round3(g - allowance)) for g in case["candidates"]
        ]
        assert per_candidate == expected["panelsPerCandidate"], (
            f"{case['id']}：逐候选幅数与引擎式不符 —— 表里 {expected['panelsPerCandidate']} / "
            f"复算 {per_candidate}（`need = {need!r}`）"
        )
        ranked = sorted(
            ((panels, _round3(g - allowance), g) for panels, g in zip(per_candidate, case["candidates"]))
        )
        assert (ranked[0][2], ranked[0][0]) == (
            expected["chosenDoorWidth"],
            expected["chosenPanels"],
        ), (
            f"{case['id']}：选中档与引擎式不符 —— 表里 {expected['chosenDoorWidth']} / "
            f"{expected['chosenPanels']} 幅，复算 {ranked[0][2]} / {ranked[0][0]} 幅"
        )


def test_golden_table_has_discriminating_power() -> None:
    """C5：**至少一例**「浮点式 ≠ 引擎式」—— 否则这张表证明不了任何事（反恒真）。"""
    side_margin = _py_float(_read(CALC_PY), "SIDE_MARGIN")
    differing: list[str] = []
    for case in _golden()["cases"]:
        if case["expected"]["state"] != "single_panel":
            continue
        need = _case_need(case, side_margin)
        allowance = case["allowance"]
        engine = [_engine_panels(need, _round3(g - allowance)) for g in case["candidates"]]
        floating = [_float_panels(need, _round3(g - allowance)) for g in case["candidates"]]
        if engine != floating:
            differing.append(case["id"])
    assert differing, (
        "golden 表里**没有任何一例**能把「浮点式」与「引擎式」区分开 ⇒ 表已失去判别力"
        "（边界算例被删/被改成非整数倍）—— 本守卫会变成恒真的空断言"
    )
    # 反向护栏：也要有「两式同值」的非边界算例（防有人把表改成「全边界」，那样就成了另一个极端）
    same = [
        case["id"]
        for case in _golden()["cases"]
        if case["expected"]["state"] == "single_panel"
        and [
            _engine_panels(_case_need(case, side_margin), _round3(g - case["allowance"]))
            for g in case["candidates"]
        ]
        == [
            _float_panels(_case_need(case, side_margin), _round3(g - case["allowance"]))
            for g in case["candidates"]
        ]
    ]
    assert same, (
        "golden 表里没有「非整数倍（两式同值）」的算例 ⇒ 无法证明「非边界输入不被误改」"
        "（判据 3 的反向护栏），请补回 `non-multiple-unchanged`"
    )


def test_golden_table_premises_are_checkable() -> None:
    """C7：表的前提可判（升序去重 / 逐候选同长 / 无半毫米舍入边界）。"""
    for case in _golden()["cases"]:
        candidates = case["candidates"]
        assert candidates == sorted(set(candidates)), (
            f"{case['id']}：候选必须**已升序去重**（两侧按升序对齐下标 ⇒ 否则两腿比的根本不是同一组）"
        )
        expected = case["expected"]
        if expected["state"] == "undecidable":
            assert "panelsPerCandidate" not in expected, (
                f"{case['id']}：不可判定的算例不得登记逐候选幅数（无门幅可用）"
            )
        else:
            assert len(expected["panelsPerCandidate"]) == len(candidates), (
                f"{case['id']}：`panelsPerCandidate` 长度 {len(expected['panelsPerCandidate'])} "
                f"≠ 候选数 {len(candidates)}（下标对齐的前提被破坏）"
            )
        # 半毫米边界：两侧舍入口径不同（Python 银行家 / JS 四舍五入）⇒ 表必须避开
        for value in (case["width"], case["allowance"], *candidates):
            frac = abs(_mm(value) - value * 1000)
            assert abs(frac - _HALF_MM) > _EPS, (
                f"{case['id']}：算例含**半毫米**输入 {value}（`v*1000` 恰为 .5）—— 两侧舍入口径不同，"
                "本表不能承载该形态（见文件头「照实登记」）"
            )


# ── C6：三腿真的共读同一张表（防「三份各自漂移的期望值」）────────────────────

def test_all_legs_read_the_same_golden_table() -> None:
    """C6：引擎腿与前端腿都必须读**这张表**（否则「跨语言相等」只是三份各自硬编码的巧合）。"""
    name = GOLDEN_JSON.name
    for path, leg in ((ENGINE_TEST, "引擎腿"), (TS_TEST, "前端腿")):
        src = _read(path)
        assert name in src, (
            f"{leg}（{path.relative_to(REPO_ROOT)}）没有引用共享算例表 `{name}` —— "
            "它已改成自带期望值 ⇒ 三腿会各自漂移，本守卫的「跨语言相等」结论失效"
        )
    assert "readFileSync" in _read(TS_TEST), (
        "前端腿没有真的读文件（`readFileSync` 不见）—— 共享表引用已退化成装饰 ⇒ 红"
    )
