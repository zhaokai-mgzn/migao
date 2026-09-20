# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 结构类 L0 不变式统一挂 MC-012）
"""「拼色加价：**报价侧与订单侧同源同价**」的跨语言漂移守卫（issue #4855）。

## 病根（本单要治的静默失效形态）

用户 2026-09-21 裁定逐字：「**拼色计价规则就是拼色款另加 2.4 元/米 先按这个算吧**」＋
「**两处都按 2.4 元/米（订单侧撤掉元/套）**」。两处**各自独立实现**：

| 侧 | 实现（副本） | 顾客在哪看到 |
|---|---|---|
| 报价侧（AI 报价卡） | `backend/ai-agent-service/app/tools/curtain_calc.py` 的 `MIXED_COLOR_SURCHARGE_PER_METER` | 小布报价卡 `total` / `mixed_color_surcharge` |
| 订单侧（订单金额） | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingFeeCalculator.java` 的**同名**常量 | 下单页「拼色加价」行 → 订单金额（`lineAmount()`） |

⇒ **只改一侧**（或把订单侧改回 V82 那笔元/套）⇒ **顾客看到的价 ≠ 下单收的价**，
而两侧**各自的单测都会绿**（各测各的常量/各测各的期望值）—— 这正是「同一个量的两份副本」
形态（同族先例：`test_hem_margin_cross_language_drift.py` / 前端 `craft-auto-features.test.ts`）。

**本守卫以后会拦住什么**：① 有人只改一侧的单价（例如只把报价侧调成 2.5）；
② 有人把订单侧改回「按元/套」收（删掉 `per_meter` 分派）；③ 有人为省事去**编辑已发布迁移 V82**
（改口径 ≠ 改数据：库里那两笔元/套价是历史事实，改它 = 篡改已发布迁移，issue #4235）；
④ 有人只改一侧的算例期望值（两侧算出的加价不再相等）。

## 判据（全部**读源**；**不 import 任何被测模块**）

`app` 包的导入期需要完整 `.env`（会红于环境而非红于口径）⇒ 照源读常量、照源读分派分支，
与 `test_prose_constant_drift_guard.py` / `test_fabric_width_truth_source.py` 同族。

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| G1 | 两侧常量**逐值相等**（Python 真值源 = Java 副本） | 任一侧 `2.4` → `2.5` ⇒ 红 |
| G2 | 两侧常量**都真被消费**（不是死码、且**算钱那一处**真的用常量，不是内联字面量） | 任一侧把 `米数 × 常量` 换成 `米数 × 2.4` ⇒ 红 |
| G3 | 订单侧「改按元/米」的拼次集合**恰好** = `拼1次` / `拼2次`，且真的分派到 `per_meter`（不是按元/套） | 删掉分派分支 / 把 `拼3次` 也塞进集合 ⇒ 红 |
| G4 | **数据面未动**：V82 那两行元/套价仍在（改口径 ≠ 改数据） | 编辑 V82 删掉/置空那两行 ⇒ 红 |
| G5 | **同价算例向量**：两侧常量 × 算例米数 == 同一个期望值，且两侧**测试文件**都钉着它 | 只改一侧的期望值 ⇒ 红 |
| G6 | 判别力下界（反恒真）+ 注入式自证：判据体在构造的缺陷载荷上**必报** | 见 `TestGuardSelfProof` |

⚠️ **边界（照实登记）**：本守卫只判「两侧同源同价 + 订单侧不再按元/套收那两项 + 数据面未动」。
**不判**：`拼3次`（纸表未登记用料系数 ⇒ 不在本裁定范围，仍按元/套）、其它 15 项特殊选项的元/套价
（本裁定只覆盖拼色计价 —— 动它们 = 未经裁定的改钱）、前端展示形态。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 真值源（报价侧）：算料引擎常量
CALC_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/curtain_calc.py"
#: 副本（订单侧）：admin-api 取价
FEE_JAVA = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingFeeCalculator.java"
#: 已发布迁移（**数据面**：库里那两笔元/套价 —— 只许读，不许本单改）
V82_SQL = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration/V82__seed_option_customer_unit_price.sql"
#: 两侧的算例钉点（G5：两侧算出的加价必须相等 ⇒ 两处的期望值字面量必须相同）
CALC_TEST_PY = REPO_ROOT / "backend/ai-agent-service/tests/test_curtain_calc.py"
FEE_TEST_JAVA = REPO_ROOT / "backend/admin-api/src/test/java/com/migao/admin/service/ProcessingFeeCalculatorTest.java"

#: 常量名（两侧**同名** —— 名字不同就是两份口径）
CONST = "MIXED_COLOR_SURCHARGE_PER_METER"
#: 订单侧「改按元/米」的拼次集合（用户裁定只覆盖这两项）
PER_METER_OPTIONS = ("拼1次", "拼2次")
#: 同价算例向量（真值源 §10：52 折双开 拼1次 34.1 米 / 拼2次 62.7 米）
VECTORS: tuple[tuple[float, str], ...] = ((34.1, "81.84"), (62.7, "150.48"))

_NUM = re.compile(r"^\s*(?:static\s+final\s+)?(?:public\s+|private\s+)?(?:BigDecimal\s+)?" + CONST
                  + r"\s*=\s*(?:new\s+BigDecimal\(\s*)?\"?([0-9]+(?:\.[0-9]+)?)\"?", re.M)
_JAVA_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_JAVA_LINE_COMMENT = re.compile(r"//[^\n]*")


# ──────────────────────────────────────────────────────────────────────────────
# 读源（纯函数；取不到 ⇒ 由判据报缺陷，不静默跳过）
# ──────────────────────────────────────────────────────────────────────────────

def _java_code_only(text: str) -> str:
    """去掉 Java 注释后的源码（**注释里提到常量名不算消费** —— 否则 G2 会退化成恒真）。"""
    return _JAVA_LINE_COMMENT.sub("", _JAVA_BLOCK_COMMENT.sub("", text))


def _python_code_only(text: str) -> str:
    """去掉 Python `#` 注释后的源码（同因：注释里的数字/常量名不得充当判据 —— §19.2 ③）。"""
    return re.sub(r"#[^\n]*", "", text)


def _asserted_expectation(text: str, expected: str, *, java: bool) -> bool:
    """该期望值是否出现在**断言**里（随便一处代码 / 注释里的数字不算钉点 —— §19.2 ③）。

    两侧的断言形态不同（Java `isEqualByComparingTo("81.84")` / Python `== 81.84`）⇒ 各判各的形态；
    ⚠️ 这正是「两侧测试真的钉着同一个数」的判据：**只改一侧的断言** ⇒ 该侧读不到断言形态 ⇒ 红。
    """
    number = r"(?<![\d.])" + re.escape(expected) + r"(?![\d])"
    if java:
        return re.search(r"isEqualByComparingTo\(\s*\"" + re.escape(expected) + r"\"\s*\)",
                         text) is not None
    return re.search(r"==" + r"\s*" + number, text) is not None


def _constant_value(text: str) -> float | None:
    """从源码里读常量值（两侧同一条正则；读不到 ⇒ None）。"""
    match = _NUM.search(text)
    return float(match.group(1)) if match else None


def _price_used_in_multiplication(calc_text: str, java_text: str) -> list[str]:
    """G2 判定体：两侧都必须**真的用它算钱**（乘法），而不是只引用 / 内联字面量。

    ⚠️ 为什么不是「名字出现 ≥2 次」：常量在 detail 里被引用一次也算「出现」——
    把**算钱那一处**内联成字面量后（改了常量金额不跟）计数仍是 2 ⇒ 判据退化成恒真。
    故判据是**消费形态**：报价侧 = AST 里的 `… * 常量` 乘法节点；订单侧 = `常量.multiply(`。
    """
    defects: list[str] = []
    tree = ast.parse(calc_text)
    multiplied = False
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for side in (node.left, node.right):
                if isinstance(side, ast.Name) and side.id == CONST:
                    multiplied = True
    if not multiplied:
        defects.append(
            f"报价侧没有「米数 × {CONST}」的乘法 —— 算钱那一处很可能已内联成字面量（改常量金额不跟）")
    if not re.search(re.escape(CONST) + r"\s*\.\s*multiply\(", _java_code_only(java_text)):
        defects.append(
            f"订单侧没有「{CONST} × 米数」的乘法 —— 算钱那一处很可能已内联成字面量（改常量金额不跟）")
    return defects


# ──────────────────────────────────────────────────────────────────────────────
# G1 + G2：同源 + 两侧都真消费
# ──────────────────────────────────────────────────────────────────────────────

def _consumed_in_python(source: str, name: str) -> bool:
    """Python：该模块级名字在**定义之外**被 Load（AST；注释/docstring 不算）。"""
    tree = ast.parse(source)
    loads = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
             and isinstance(n.ctx, ast.Load) and n.id == name]
    return bool(loads)


def sync_defects(calc_text: str, java_text: str) -> list[str]:
    """G1/G2 判定体：空列表 = 两侧同源且都被消费（算钱那一处真的用常量）。"""
    defects: list[str] = []
    py_value = _constant_value(calc_text)
    java_value = _constant_value(java_text)
    if py_value is None:
        defects.append(f"报价侧（curtain_calc.py）读不到常量 {CONST} —— 真值源缺失，判据失去被测对象")
    if java_value is None:
        defects.append(f"订单侧（ProcessingFeeCalculator.java）读不到常量 {CONST} —— 副本缺失")
    if py_value is not None and java_value is not None and py_value != java_value:
        defects.append(
            f"两侧拼色加价单价**漂移**：报价侧 {py_value} ≠ 订单侧 {java_value} —— "
            "顾客看到的价与下单收的价会不一致（用户裁定要求「两处都按 2.4 元/米」）")
    if py_value is not None and not _consumed_in_python(calc_text, CONST):
        defects.append(f"报价侧 {CONST} 只有定义、没有消费点 —— 判定处很可能已内联成字面量（改了常量判定不跟）")
    defects += _price_used_in_multiplication(calc_text, java_text)
    return defects


# ──────────────────────────────────────────────────────────────────────────────
# G3：订单侧「改按元/米」的分派（防改回元/套）
# ──────────────────────────────────────────────────────────────────────────────

def per_meter_dispatch_defects(java_text: str) -> list[str]:
    """G3 判定体：订单侧必须把这两个拼次**分派到 per_meter**（不是按元/套）。"""
    code = _java_code_only(java_text)
    defects: list[str] = []
    for option in PER_METER_OPTIONS:
        if f'"{option}"' not in code:
            defects.append(f"订单侧的「改按元/米」拼次集合里没有 {option} —— 它会退回按元/套收（用户裁定要求撤掉）")
    if "PER_METER_MIXED_OPTIONS.contains(" not in code:
        defects.append("订单侧没有「命中改按元/米的拼次 ⇒ 走 per_meter 分支」的分派（取价会回到按元/套）")
    elif not re.search(r"if\s*\(\s*PER_METER_MIXED_OPTIONS\.contains\(\s*\w+\s*\)\s*\)\s*\{", code):
        defects.append(
            "订单侧的 per_meter 分派不是可执行的 `if (PER_METER_MIXED_OPTIONS.contains(x)) { … }` 形态"
            "（被短路 / 否定 / 改写 ⇒ 取价会回到按元/套）")
    if "BILLING_PER_METER" not in code:
        defects.append("订单侧没有 per_meter 计价口径标记（选项会被读成「按套」或「未定价」）")
    return defects


# ──────────────────────────────────────────────────────────────────────────────
# G4：数据面未动（V82 那两行元/套价仍在）
# ──────────────────────────────────────────────────────────────────────────────

def seed_data_defects(sql_text: str) -> list[str]:
    """G4 判定体：V82 里那两行拼次价必须仍在（改口径 ≠ 改数据；已发布迁移不可改）。"""
    defects: list[str] = []
    for option in PER_METER_OPTIONS:
        row = re.search(r"\(\s*'" + re.escape(option) + r"'\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)", sql_text)
        if not row:
            defects.append(
                f"V82 种子里找不到 {option} 的元/套价 —— 数据面被改动了。"
                "本裁定只改**取价口径**（库里那笔价是历史事实，改它 = 编辑已发布迁移，issue #4235）；"
                "确需动数据必须走**新迁移**（V100+）")
        elif float(row.group(1)) <= 0:
            defects.append(f"V82 种子里 {option} 的元/套价被置成非正数（{row.group(1)}）—— 同上，改口径 ≠ 改数据")
    return defects


# ──────────────────────────────────────────────────────────────────────────────
# G5：同价算例向量（两侧算出的加价必须相等）
# ──────────────────────────────────────────────────────────────────────────────

def vector_defects(py_value: float | None, java_value: float | None,
                   calc_test_text: str, java_test_text: str) -> list[str]:
    """G5 判定体：两侧常量 × 算例米数 == 同一个期望值，且两侧测试**代码**都钉着它。

    ⚠️ 期望值只在**注释**里出现不算（§19.2 ③：注释里的数字也会腐烂）⇒ 两侧都先去注释再判；
    且用「独立数字」边界匹配（`1571.84` 里的 `81.84` 不算 —— 防子串假命中）。
    """
    defects: list[str] = []
    py_code = _python_code_only(calc_test_text)
    java_code = _java_code_only(java_test_text)
    for meters, expected in VECTORS:
        want = float(expected)
        for side, value in (("报价侧", py_value), ("订单侧", java_value)):
            if value is None:
                continue
            got = round(value * meters, 2)
            if got != want:
                defects.append(
                    f"{side}：{value} 元/米 × {meters} 米 = {got}，而两侧共同的算例期望值是 {expected}"
                    f"（{want}）—— 两侧算出的加价不再相等")
        if not _asserted_expectation(py_code, expected, java=False):
            defects.append(f"报价侧测试**断言**里找不到算例期望值 {expected}（改了一侧 ⇒ 另一侧无感）")
        if not _asserted_expectation(java_code, expected, java=True):
            defects.append(f"订单侧测试**断言**里找不到算例期望值 {expected}（改了一侧 ⇒ 另一侧无感）")
    return defects


# ──────────────────────────────────────────────────────────────────────────────
# 主判据（读真源）
# ──────────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    assert path.exists(), f"守卫的被测文件不存在：{path}（路径漂移不得退化成绿）"
    return path.read_text(encoding="utf-8")


def test_two_sides_share_one_price() -> None:
    """G1/G2：报价侧与订单侧的拼色加价单价**逐值相等**，且两侧都真消费它。"""
    defects = sync_defects(_read(CALC_PY), _read(FEE_JAVA))
    assert defects == [], "拼色加价两侧不同源：\n  " + "\n  ".join(defects)


def test_order_side_dispatches_per_meter() -> None:
    """G3：订单侧把 `拼1次`/`拼2次` 分派到 per_meter（不再按元/套）。"""
    defects = per_meter_dispatch_defects(_read(FEE_JAVA))
    assert defects == [], "订单侧未改按元/米：\n  " + "\n  ".join(defects)


def test_seed_data_untouched() -> None:
    """G4：V82 那两行元/套价仍在（改口径 ≠ 改数据）。"""
    defects = seed_data_defects(_read(V82_SQL))
    assert defects == [], "数据面被改：\n  " + "\n  ".join(defects)


def test_same_example_vector_on_both_sides() -> None:
    """G5：两侧常量 × 算例米数 == 同一个期望值，且两侧测试都钉着它。"""
    calc_text = _read(CALC_PY)
    java_text = _read(FEE_JAVA)
    defects = vector_defects(_constant_value(calc_text), _constant_value(java_text),
                             _read(CALC_TEST_PY), _read(FEE_TEST_JAVA))
    assert defects == [], "两侧算例期望值不一致：\n  " + "\n  ".join(defects)


def test_guard_has_discriminating_power() -> None:
    """G6：两处都解析到正数、常量名两侧同名、算例向量非空（防整表被填成同一形态）。"""
    py_value = _constant_value(_read(CALC_PY))
    java_value = _constant_value(_read(FEE_JAVA))
    assert py_value is not None and py_value > 0, f"报价侧常量读出来不是正数：{py_value}"
    assert java_value is not None and java_value > 0, f"订单侧常量读出来不是正数：{java_value}"
    assert VECTORS, "算例向量为空 ⇒ G5 空跑（不会红的断言 = 空断言）"
    assert len({expected for _m, expected in VECTORS}) >= 2, "算例向量全是同一个期望值 ⇒ 判据失去判别力"


# ──────────────────────────────────────────────────────────────────────────────
# G6 补：注入式自证（**同一个判定体**在构造的缺陷载荷上必报 ⇒ 主测试的绿不是空跑）
# ──────────────────────────────────────────────────────────────────────────────

class TestGuardSelfProof:
    """注入式自证（同族先例：`test_prose_constant_drift_guard.py::TestGuardSelfProof`）。"""

    #: 最小载荷：两侧源码各一行常量定义 + 一处消费
    PY_OK = f"{CONST} = 2.4\n\n\ndef f(meters):\n    return meters * {CONST}\n"
    JAVA_OK = (
        f"class X {{\n    static final BigDecimal {CONST} = new BigDecimal(\"2.4\");\n"
        f"    BigDecimal g(BigDecimal m) {{ return {CONST}.multiply(m); }}\n}}\n"
    )

    def test_clean_payload_passes(self) -> None:
        """干净载荷 ⇒ 判定体不报（证明下面的红由注入引起，而不是判据误红）。"""
        assert sync_defects(self.PY_OK, self.JAVA_OK) == []

    def test_detects_one_sided_price_change(self) -> None:
        """只改一侧的单价（订单侧 2.4 → 2.5）⇒ G1 必报。"""
        defects = sync_defects(self.PY_OK, self.JAVA_OK.replace("2.4", "2.5"))
        assert any("漂移" in d for d in defects), f"只改一侧没报漂移：{defects}"

    def test_detects_inlined_literal(self) -> None:
        """把常量内联成字面量（只剩定义）⇒ G2 必报（改了常量判定不跟）。"""
        inlined = self.JAVA_OK.replace(f"{CONST}.multiply(m)", "new BigDecimal(\"2.4\").multiply(m)")
        assert any("没有消费点" in d or "乘法" in d for d in sync_defects(self.PY_OK, inlined)), \
            "内联字面量没被认出来 ⇒ G2 是空断言"

    def test_detects_inlined_price_in_amount_only(self) -> None:
        """只把**算钱那一处**内联（常量仍在别处被引用）⇒ G2 仍必报（引用 ≠ 消费）。"""
        java_inlined = self.JAVA_OK.replace(f"{CONST}.multiply(m)", "new BigDecimal(\"2.4\").multiply(m)")
        assert any("乘法" in d for d in sync_defects(self.PY_OK, java_inlined)), \
            "订单侧「算钱处内联」没被认出来 ⇒ G2 会退化成「名字出现 ≥2 次」"
        py_inlined = self.PY_OK.replace(f"meters * {CONST}", "meters * 2.4")
        assert any("乘法" in d for d in sync_defects(py_inlined, self.JAVA_OK)), \
            "报价侧「算钱处内联」没被认出来 ⇒ G2 是空断言"

    def test_detects_comment_only_expectation(self) -> None:
        """期望值只在**注释**里出现 ⇒ G5 必报（注释里的数字不算钉点）。"""
        defects = vector_defects(2.4, 2.4, "# 期望 81.84 / 150.48\nassert True\n",
                                 "// 期望 81.84 / 150.48\n")
        assert any("测试**断言**里找不到" in d for d in defects), \
            "只在注释里的期望值被判成已钉 ⇒ G5 是空断言"

    def test_non_assertion_code_is_not_a_pin(self) -> None:
        """期望值只出现在**非断言**代码里（构造入参 / 别的字面量）⇒ 不算钉点。"""
        defects = vector_defects(
            2.4, 2.4,
            "x = new BigDecimal('81.84')\nassert True\n",
            'x.put("v", new BigDecimal("81.84"));\n')
        assert any("测试**断言**里找不到" in d for d in defects), \
            "非断言代码里的数字被判成钉点 ⇒ G5 可以靠构造入参蒙混过关"

    def test_substring_expectation_is_not_a_pin(self) -> None:
        """`1571.84` 里的 `81.84` 不算钉点（防子串假命中）。"""
        assert not _asserted_expectation("assert total == 1571.84", "81.84", java=False), \
            "子串被判成钉点 ⇒ G5 可以靠别的数字蒙混过关"
        assert _asserted_expectation("assert surcharge == 81.84", "81.84", java=False)
        assert _asserted_expectation('isEqualByComparingTo("81.84")', "81.84", java=True)

    def test_detects_reverted_per_set_dispatch(self) -> None:
        """把订单侧改回按元/套（删掉 per_meter 分派 / 把它短路）⇒ G3 必报。"""
        reverted = self.JAVA_OK.replace("PER_METER_MIXED_OPTIONS.contains(", "").replace(
            "BILLING_PER_METER", "")
        assert per_meter_dispatch_defects(reverted), "删掉分派后没报 ⇒ G3 是空断言"
        # 反向：干净载荷（含集合定义 + 分派）⇒ 不报
        ok = (self.JAVA_OK
              + '    static final Set<String> PER_METER_MIXED_OPTIONS = Set.of("拼1次", "拼2次");\n'
              + "    boolean perMeter(String name) { return PER_METER_MIXED_OPTIONS.contains(name); }\n"
              + "    void dispatch(String name) { if (PER_METER_MIXED_OPTIONS.contains(name)) { x(); } }\n"
              + '    String b() { return BILLING_PER_METER; }\n')
        assert per_meter_dispatch_defects(ok) == [], "干净载荷被判红 ⇒ G3 误红"
        # 短路形态（`false && …contains(name)`）⇒ 仍必报（分支被禁用 = 回到按元/套）
        shorted = ok.replace("if (PER_METER_MIXED_OPTIONS.contains(name))",
                             "if (false && PER_METER_MIXED_OPTIONS.contains(name))")
        assert per_meter_dispatch_defects(shorted), "短路掉分派后没报 ⇒ G3 是空断言"

    def test_detects_edited_seed_migration(self) -> None:
        """编辑已发布迁移（删掉/置空那两行）⇒ G4 必报。"""
        ok = "UPDATE x SET customer_unit_price = v.p FROM (VALUES ('拼1次', 3.00), ('拼2次', 5.00)) AS v;\n"
        assert seed_data_defects(ok) == [], "干净种子被判红 ⇒ G4 误红"
        assert seed_data_defects("UPDATE x SET customer_unit_price = NULL;\n"), "删掉那两行后没报 ⇒ G4 是空断言"
        assert seed_data_defects(ok.replace("3.00", "0.00")), "置成 0 后没报 ⇒ G4 是空断言"

    def test_detects_one_sided_vector_change(self) -> None:
        """只改一侧的算例期望值 ⇒ G5 必报（两侧算出的加价不再相等）。"""
        py_test = "assert q['mixed_color_surcharge'] == 81.84\nassert q['total'] == 150.48\n"
        java_test = ('assertThat(x).isEqualByComparingTo("81.84");\n'
                     'assertThat(y).isEqualByComparingTo("150.48");\n')
        assert vector_defects(2.4, 2.4, py_test, java_test) == [], "干净向量被判红 ⇒ G5 误红"
        assert vector_defects(2.4, 2.4, py_test.replace("== 81.84", "== 99.99"), java_test), \
            "只改一侧期望值没报 ⇒ G5 是空断言"
        assert vector_defects(2.4, 2.5, py_test, java_test), "只改一侧常量没报 ⇒ G5 是空断言"
