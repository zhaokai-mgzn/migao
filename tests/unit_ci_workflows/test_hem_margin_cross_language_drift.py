# case_ids: OR-040
"""`HEM_MARGIN` / `SIDE_MARGIN` **跨语言常量副本**的漂移守卫（issue #4656）。

## 病根（本单要治的静默失效形态）

`frontend/admin-web/src/lib/craft-auto-features.ts` 里的两个余量常量是**算料引擎的副本**：

| 前端副本 | 真值源（`backend/ai-agent-service/app/tools/curtain_calc.py`） | 语义 | 方向 |
|---|---|---|---|
| `SIDE_MARGIN = 0.3` | `SIDE_MARGIN = 0.3  # 定高布：左右覆盖余量合计（各 15cm）` | 左右覆盖余量 | **宽**（`超宽`） |
| `HEM_MARGIN = 0.3` | `HEM_MARGIN = 0.3  # 定宽布：上下卷边合计（脚位+止口）` | 上下卷边 | **高**（`超高`） |

两边**各自独立存在** ⇒ 引擎改了卷边、前端没跟（或反之）⇒ **同一张单前端判「超宽/超高」、
后端算料不这么算**。而「超宽/超高」进的是**加工费组合键**
（`ProcessingFeeQueryService.featureNames()` 只读 `processingInfo.processingItems[]`）
⇒ 漂移的后果是**静默算错价**（与 #4592「正幅污染组合键 ⇒ 加工费恒 ¥0.00」同族）。

## 本守卫**不新造口径**，补的是既有守卫结构上看不到的两面

前端腿**已有**值级守卫：`frontend/admin-web/tests/unit/lib/craft-auto-features.test.ts`
（`pyConst()` 读 Python 源比对，漂移即红 —— 本单核清时**已在 main**，不是本单新增）。
本守卫是同族（`test_panels_formula_split_audit.py` / `test_fabric_width_truth_source.py`）的
**Python 腿**，补的是前端腿**结构上做不到**的两件事：

1. **独立腿**：`ci-workflow-tests` 与 `admin-web-test` 是**两个 job** —— 前端腿被过滤/跳过时，
   本腿仍判（前端腿只比**常量值**，本腿还比**注释里的引文**）；
2. **注释里的引值**：前端注释**逐字引用**了引擎那一行（值 **+ 语义注释**）。引擎改了值或改了
   语义（如 `脚位+止口` → `脚位`），前端注释会**静默说谎**，而只看常量的值级断言
   **看不到**这一面 —— §19.2 ③「注释 / docstring 里的数字与标识符引用也会腐烂」，
   落码先例 = `test_declaration_truth_guards.py`（#4259）。

## 判据（全部**读源**；本文件**不写死任何余量值**）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 两侧逐值相等（引擎源 vs 前端源） | 前端 `HEM_MARGIN` → `0.31`（或引擎 → `0.35`）⇒ 红 |
| C2 | **两个方向不得合并**：前端必须**同时**导出两个名字、各自跟自己的引擎常量（#4661 的回归形态 = 两处都用 `HEM_MARGIN`） | 前端删掉 `SIDE_MARGIN`（或把它的初值指到 `HEM_MARGIN` 的值）⇒ 红 |
| C3 | 前端注释引用的引擎行**逐字**一致（值 **+ 语义注释**；空白归一后比对） | 只改引擎注释措辞（`脚位+止口` → `脚位`）⇒ 红 |
| C4 | **判别力下界（反恒真）**：两侧都必须解析到正数；前端**真的消费**了这两个常量；前端代码里**不得**出现第二份与引擎余量同值的字面量（判定处内联 = 常量改了判定不跟） | 判定处 `height + HEM_MARGIN` → `height + 0.3` ⇒ 红 |
| C5 | 前端注释里引用的守卫文件**真的存在**且真的读源（引文不得腐烂，同 §19.2 ③） | 删掉/改名 `craft-auto-features.test.ts` ⇒ 红 |

⚠️ **本守卫不 import 被测引擎**（`app` 包的导入期需要完整 `.env` ⇒ 会红于环境而非红于口径）
—— 照源里的赋值复算，与 `test_fabric_width_truth_source.py` 同族。

⚠️ **本单不动 `backend/ai-agent-service/**`**（用户裁定 ai-agent 改动待排期，分叉 #4652）：
引擎侧的 `_FABRIC_WIDTH` 硬编码门幅与 docstring 里的公式散文**不在本守卫范围**，照实登记。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 真值源：算料引擎
CALC_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/curtain_calc.py"
#: 副本：前端下单页自动识别模块
LIB_TS = REPO_ROOT / "frontend/admin-web/src/lib/craft-auto-features.ts"
#: 前端腿守卫（C5：前端注释引用的那个文件，必须真的存在且真的读源）
TS_GUARD = REPO_ROOT / "frontend/admin-web/tests/unit/lib/craft-auto-features.test.ts"

#: 本守卫钉的两个方向余量（两侧**同名**；两个方向**各自**跟自己的引擎常量，不得合并）
MARGINS: tuple[str, ...] = ("SIDE_MARGIN", "HEM_MARGIN")

#: 注释引文里的空白会被排版改写（引擎侧对齐用多空格、前端注释用两空格）⇒ 比对前归一空白
_WS = re.compile(r"\s+")


def _normalize(line: str) -> str:
    return _WS.sub(" ", line).strip()


def _py_value(source: str, name: str) -> float:
    """从引擎源里取模块级浮点常量（取不到 ⇒ **直接失败**，不静默跳过）。"""
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", source, re.M)
    assert m, (
        f"curtain_calc.py 里找不到常量 {name} —— 本守卫必须能读到真值；"
        "若该常量已改名/搬走，请同步本守卫与 craft-auto-features.ts 的登记"
    )
    return float(m.group(1))


def _py_line(source: str, name: str) -> str:
    """引擎里**整行**常量定义（值 + 语义注释）—— C3 的引文比对基准。"""
    m = re.search(rf"^{name}\s*=\s*[0-9.]+\s*#.*$", source, re.M)
    assert m, f"curtain_calc.py 里找不到 {name} 的「值 + 语义注释」整行定义（C3 的基准取不到）"
    return m.group(0)


def _ts_value(source: str, name: str) -> float:
    """从前端源里取 `export const NAME = <v>`（取不到 ⇒ **直接失败**，不静默跳过）。"""
    m = re.search(rf"^export\s+const\s+{name}\s*=\s*([0-9.]+)", source, re.M)
    assert m, (
        f"craft-auto-features.ts 里找不到 `export const {name} = …` —— "
        "副本没了（或被内联成字面量）⇒ 守卫失去判别力，必须红"
    )
    return float(m.group(1))


def _quoted_engine_line(source: str, name: str) -> str:
    """前端注释里**反引号引用**的引擎行（`NAME = <值>  # <语义注释>`）。"""
    m = re.search(rf"`\s*{name}\s*=\s*([^`]*)`", source)
    assert m, (
        f"craft-auto-features.ts 的注释里找不到对 {name} 的逐字引文（`` `{name} = …` ``）—— "
        "引文是 C3 的被测对象，删了它 C3 会空跑 ⇒ 必须红"
    )
    return f"{name} = {m.group(1)}"


def _strip_comments(text: str) -> str:
    """去掉 `/* … */` 与 `// …` —— C4 只认**代码**里的字面量（注释里引用真值不算抄）。"""
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//[^\n]*", "", text)


def _float_literals(code: str) -> list[float]:
    """代码里的浮点字面量（`0.3` / `0.30` 都算；整数（如 `toFixed(3)`）不算）。"""
    return [float(x) for x in re.findall(r"(?<![\w.])(\d+\.\d+)(?![\w.])", code)]


def _calc_source() -> str:
    return CALC_PY.read_text(encoding="utf8")


def _lib_source() -> str:
    return LIB_TS.read_text(encoding="utf8")


# ── C1 / C2：两侧逐值相等（两个方向各自跟自己的引擎常量）────────────────────────

def test_margins_equal_engine_truth() -> None:
    """C1+C2：前端两个余量常量 == 引擎**同名**常量（逐值读源，不写死）。"""
    calc, lib = _calc_source(), _lib_source()
    for name in MARGINS:
        engine, frontend = _py_value(calc, name), _ts_value(lib, name)
        assert engine > 0, f"引擎 {name} 读出来不是正数（{engine}）—— 解析口径变了，请同步本守卫"
        assert frontend == engine, (
            f"跨语言常量漂移：{name} 前端 = {frontend} / 引擎 = {engine}。"
            "「超宽/超高」进加工费组合键 ⇒ 这处漂移 = 静默算错价；"
            "改哪边都要改另一边（前端值不得单独改）"
        )


# ── C3：前端注释引用的引擎行逐字一致（值 + 语义注释）──────────────────────────

def test_frontend_comment_quotes_engine_line_verbatim() -> None:
    """C3：注释里的引文也是**副本** —— 引擎改了值或语义，引文不得静默说谎。"""
    calc, lib = _calc_source(), _lib_source()
    for name in MARGINS:
        quoted, engine_line = _normalize(_quoted_engine_line(lib, name)), _normalize(_py_line(calc, name))
        assert quoted == engine_line, (
            f"{name} 的注释引文已腐烂：\n  前端注释 = {quoted!r}\n  引擎真值 = {engine_line!r}\n"
            "（引擎改了值或语义注释 ⇒ 请同步 craft-auto-features.ts 里那一行引文）"
        )


# ── C4：判别力下界（反恒真 / 防「声明了但判定处内联」）────────────────────────

def test_frontend_actually_consumes_margins_and_has_no_second_literal() -> None:
    """C4：常量必须被**消费**，且代码里不得出现第二份同值字面量（否则改常量判定不跟）。"""
    calc, lib = _calc_source(), _lib_source()
    code = _strip_comments(lib)

    for name in MARGINS:
        # 出现次数 > 1 ⇒ 除了声明处，至少有一处**消费**（判定/文案）
        assert code.count(name) > 1, (
            f"{name} 在前端代码里只出现在声明处（无消费点）—— "
            "要么判定处被内联成字面量（常量改了判定不跟），要么该常量已成死码"
        )

    # 引擎余量值在前端代码里**恰好**出现在同名常量的声明处（按值分组：两方向同值时合计 2 处）
    by_value: dict[float, list[str]] = {}
    for name in MARGINS:
        by_value.setdefault(_py_value(calc, name), []).append(name)
    literals = _float_literals(code)
    for value, names in by_value.items():
        assert literals.count(value) == len(names), (
            f"前端代码里与引擎余量同值的字面量 {value} 出现 {literals.count(value)} 次，"
            f"但声明处只应有 {len(names)} 处（{names}）—— "
            "多出来的是**第二份副本**（内联字面量）：改引擎/改常量时它不会跟着变 ⇒ 静默漂移"
        )


# ── C5：注释引用的守卫文件真的存在且真的读源（引文不得腐烂）──────────────────

def test_cited_frontend_guard_exists_and_reads_source() -> None:
    """C5：前端注释里点名了守卫文件 —— 那个文件必须真的存在，且真的**读 Python 源**。"""
    assert TS_GUARD.is_file(), (
        f"前端注释引用的守卫文件不存在：{TS_GUARD.relative_to(REPO_ROOT)} —— "
        "引文腐烂（§19.2 ③）⇒ 要么恢复该守卫，要么改注释里的引用"
    )
    guard = TS_GUARD.read_text(encoding="utf8")
    assert "readFileSync" in guard and "curtain_calc.py" in guard, (
        "前端守卫没有读 Python 源（`readFileSync` + `curtain_calc.py` 都不见）—— "
        "它已退化成硬编码比对（守卫自己会漂移），必须红"
    )
    for name in MARGINS:
        assert f"pyConst('{name}')" in guard, (
            f"前端守卫里找不到 `pyConst('{name}')` —— 该常量的**前端腿**值级守卫没了，"
            "注释里那句「本副本有守卫」变成假话"
        )
