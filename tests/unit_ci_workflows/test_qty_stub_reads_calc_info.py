# case_ids: PG-022
"""算料数量桩**不得**自带米轴平行真值（issue #4337 的类级锁）。

## 病根（一类缺陷，不是一个缺陷 —— 与「同一真值两处投影」同族）

`ProcessingOrderServiceTest` 的共用桩 `stubQty()` 曾对**米类**工序恒定返回 `12.3` / `fabric_meters`，
**与请求体里的 `calc_info` 完全无关**（平行真值）。两面后果本单都实测过：

* **假绿**：该文件里所有「米类 `qty` / `qty_source`」断言，对「`fabric_meters` 压根没送出去」
  不敏感；端到端用例那条 blanket「全部实例 `qty` ≠ 订单数量」对米类**在现实中为假**
  （米类应当等于订单行数量），它当时之所以绿，唯一原因就是这根桩（#4337）；
* **假红**：任何人**正确地**把桩改成 calc_info-aware 时，那些断言会红，而红的原因不是他改错了
  —— 实测读数 `Tests run: 3, Failures: 3`，三条都是 `expected: 2 but was: 12.3`
  （`generateTakesQtyFromCalcEngineNotFromOrderQuantity` / `generateInstantiatesOperationsVerbatimFromOperationLibrary`
  / `derivePositionPayloadUsesOperationLibrary`）。

JUnit 侧的真判据（把实例 `qty` 钉到**请求体里的** `calc_info.fabric_meters`，见
`ProcessingOrderServiceTest#generateTakesQtyFromCalcEngineNotFromOrderQuantity`）能挡住「桩回退」这一路，
**挡不住下一个人把断言重新钉回常量** —— 而那正是本缺陷产生的路径。故本文件锁**夹具属性本身**：
**凡把 `fabric_meters` 写进米轴 `qty_source` 映射的测试供数点，其所在上下文必须读请求体 `calc_info`。**

## 判据（机械）

- 语料 = `backend/admin-api/src/test/java` 下的 `*.java`（逐文件读原文，**去注释后**再判 ——
  「把 `calc_info` 写进注释」不算读请求体，实测过：不去注释时注入式红证**不红**，属空断言）；
- 供数点 = 正则 `source.put(<标识符>, "fabric_meters")`；
- 每处供数点往前 `_WINDOW` 个字符内**必须**出现 `calc_info` / `calcInfoOf(`（= 读请求体），否则红并**逐处**报出路径与文本；
- **无豁免台账**（当前 0 处合法豁免）：任何新出现的米轴常量桩一律红，无需登记。

## 红证（注入式，实跑过）

把 `ProcessingOrderServiceTest.stubQty()` 的米轴改回平行真值形态
（`qty.put(operation, new BigDecimal(CALC_FABRIC_METERS))` + `source.put(operation, "fabric_meters")`）
⇒ 本文件红（报出 `backend/admin-api/src/test/java/com/migao/admin/service/ProcessingOrderServiceTest.java`
的该供数点）。扫描器判别力另有**内存自证**（合成样本，不写盘）：平行真值桩必被检出、读 `calc_info` 的桩必放行。

## 边界（如实登记，**不是**「已覆盖」）

- 形态靠**文本**识别（同族守卫的既有取舍）：判据在**去注释后**的原文上跑，但 `//` 出现在**字符串字面量**里
  会被一并去掉（错切方向对本判据无影响：它只看 `calc_info` 与供数点是否同框）；供数点若改用别的写法
  （先装配 Map 再整体 put / 名字拼出来）⇒ 本普查看不见；
- `_WINDOW` 是**同框**近似：跨方法渗进来的 `calc_info` 会让某处常量桩漏报（假绿方向，不误伤）；
- **不**检查非米轴（折/幅/套/孔）的桩取值是否等于端点真实行为 —— 那一轴属 #4273 领地，
  本单（#4337）有意只治米轴；
- 只登记 `backend/admin-api/src/test/java` 一个面（其它模块的测试面不在内）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: 语料根（结构化射程；本文件的判据只读这一棵树内的 `*.java`）
CORPUS_ROOT = REPO_ROOT / "backend" / "admin-api" / "src" / "test" / "java"

#: 米轴供数点：桩把 `fabric_meters` 写进「工序 → 来源」映射
_METER_SOURCE_PUT = re.compile(r'source\.put\(\s*[\w.]+\s*,\s*"fabric_meters"\s*\)')
#: 读请求体的形态（`calc_info` 键 / `calcInfoOf(...)` 助手）
_CALC_INFO_READ = re.compile(r"calc_info|calcInfoOf\s*\(")
#: 供数点往前看多少字符（够覆盖同一 answer lambda 内的 calc_info 读取，实测 ~400）
_WINDOW = 900
#: 注释形态（**必须去掉**：实测不去注释时「把 calc_info 写进注释」会让注入式红证不红 = 空断言）
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    """把 Java 注释**原地涂白**（非换行字符 → 空格）⇒ **长度、偏移、行号三者都不变**，报错读数可逐字对齐原文。"""
    def blank(m: "re.Match[str]") -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


def java_test_files() -> list[Path]:
    """语料 = `CORPUS_ROOT` 下的全部 `*.java`（确定性排序，便于报错逐处对齐）。"""
    return sorted(CORPUS_ROOT.rglob("*.java"))


def offenders_in(text: str, rel: str) -> list[str]:
    """返回 `text` 里「米轴供数点但上下文不读 calc_info」的逐处读数（行号 + 原文行）。

    ⚠️ 判据在**去注释**后的文本上跑（`strip_comments` 原地涂白 ⇒ 偏移与行号都不变）—— 见模块 docstring 的红证脚注。
    """
    out: list[str] = []
    stripped = strip_comments(text)
    for m in _METER_SOURCE_PUT.finditer(stripped):
        window = stripped[max(0, m.start() - _WINDOW):m.start()]
        if _CALC_INFO_READ.search(window):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        line = text.splitlines()[line_no - 1].strip()
        out.append(f"{rel}:{line_no} — {line}")
    return out


def scan_repo() -> list[str]:
    findings: list[str] = []
    for path in java_test_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        findings += offenders_in(path.read_text(encoding="utf-8"), rel)
    return findings


def test_米轴供数点必须读请求体_calc_info():
    """承重判据：每一处米轴供数点都必须读请求体 `calc_info`（缺键 ⇒ 兜底由端点口径决定，不由桩发明）。"""
    findings = scan_repo()
    assert findings == [], (
        "米轴平行真值（issue #4337 同族缺陷）：下列供数点把 `fabric_meters` 当常量写进来源映射，"
        "却不读请求体 `calc_info` ⇒ 「米类 qty」一族断言对 `fabric_meters` 是否送出**不敏感**"
        "（假绿），且任何人把它改成 calc_info-aware 时会**假红**。\n"
        "怎么改：读该部位自己的 `calc_info`（`calcInfoOf(position).get(\"fabric_meters\")`；"
        "缺键 ⇒ `BigDecimal.ONE` + `fallback`，与 ai-agent `routing.py::_qty_for` 的 METER_KEYS 口径一致）。\n"
        + "\n".join("  - " + f for f in findings)
    )


def test_扫描器判别力自证():
    """判别力自证（不写盘）：平行真值桩必被检出、读 calc_info 的桩必放行、语料非空。"""
    parallel_truth = (
        'if ("米".equals(unit)) {\n'
        '    qty.put(operation, new BigDecimal(CALC_FABRIC_METERS));\n'
        '    source.put(operation, "fabric_meters");\n'
        '}\n'
    )
    calc_info_aware = (
        'Object meters = calcInfoOf(position).get("fabric_meters");\n'
        'if (meters == null) {\n'
        '    qty.put(operation, BigDecimal.ONE);\n'
        '    source.put(operation, "fallback");\n'
        '} else {\n'
        '    source.put(operation, "fabric_meters");\n'
        '}\n'
    )
    # 去注释的判别力（实测过的空断言形态：不去注释时「把 calc_info 写进注释」会让注入式红证不红）
    comment_only = (
        '// 本桩"读了" calc_info（只在注释里说）\n'
        'qty.put(operation, new BigDecimal(CALC_FABRIC_METERS));\n'
        'source.put(operation, "fabric_meters");\n'
    )
    assert offenders_in(parallel_truth, "合成样本.java") != [], "平行真值桩未被检出 ⇒ 扫描器失效"
    assert offenders_in(calc_info_aware, "合成样本.java") == [], "读 calc_info 的桩被误报 ⇒ 假红方向"
    assert offenders_in(comment_only, "合成样本.java") != [], "注释里的 calc_info 骗过了判据 ⇒ 空断言"
    files = java_test_files()
    assert files, f"语料为空 ⇒ 判据空转（检查 {CORPUS_ROOT}）"