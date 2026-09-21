# case_ids: OR-040
"""`HEM_MARGIN` **跨语言常量副本**的漂移守卫（issue #4656；issue #5030 改判）。

## 病根（本单要治的静默失效形态）

`frontend/admin-web/src/lib/craft-auto-features.ts` 里的高方向余量常量是**算料引擎的副本**：

| 前端副本 | 真值源（`backend/ai-agent-service/app/tools/curtain_calc.py`） | 语义 | 方向 |
|---|---|---|---|
| `HEM_MARGIN = 0.3` | `HEM_MARGIN = 0.3  # 定宽布：上下卷边合计（脚位+止口）` | 上下卷边 | **高**（`超高`） |

两边**各自独立存在** ⇒ 引擎改了卷边、前端没跟（或反之）⇒ **同一张单前端判「超高」、
后端算料不这么算**。而「超高」进的是**加工费组合键**
（`ProcessingFeeQueryService.featureNames()` 只读 `processingInfo.processingItems[]`）
⇒ 漂移的后果是**静默算错价**（与 #4592「正幅污染组合键 ⇒ 加工费恒 ¥0.00」同族）。

## 2026-09-21 改判（issue #5030）：`SIDE_MARGIN` 整体退场

用户裁定「订单这里的**宽和高是窗户的宽高**」⇒ 成品宽 = 净窗宽 ⇒ **宽方向没有余量**
⇒ 常量 `SIDE_MARGIN` 与配置键 `side_margin` 一并删除。
**旧判据 C2**（「两个方向不得合并：前端必须**同时**导出 `SIDE_MARGIN` 与 `HEM_MARGIN`」）
的前提（该常量存在）随之消失 ⇒ **删掉**，替换为**同强度的反向守卫**：
前端源码里**再出现** `SIDE_MARGIN`/`side_margin` ⇒ 红（新判据 C2'）。
⚠️ `HEM_MARGIN`（高方向）**保留**，它的逐值/逐字/消费点/引文守卫**一条都不放宽**。

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
| C2' | **宽方向余量不得复活**：前端源码里出现 `SIDE_MARGIN` / `side_margin` ⇒ 红（issue #5030） | 把 `export const SIDE_MARGIN = 0.3` 加回前端 ⇒ 红 |
| C3 | 前端注释引用的引擎行**逐字**一致（值 **+ 语义注释**；空白归一后比对） | 只改引擎注释措辞（`脚位+止口` → `脚位`）⇒ 红 |
| C4 | **判别力下界（反恒真）**：两侧都必须解析到正数；前端**真的消费**了 `HEM_MARGIN`；前端代码里**不得**出现第二份与引擎余量同值的字面量（判定处内联 = 常量改了判定不跟） | 判定处 `height + HEM_MARGIN` → `height + 0.3` ⇒ 红 |
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
#: 余量常量的**消费点**（issue #5035 起：判定/提示实现已退场，只剩规则面在读这两个常量）
PLAN_TS = REPO_ROOT / "frontend/admin-web/src/lib/door-width-plan.ts"

#: 本守卫钉的余量常量 —— **只剩高方向**（`SIDE_MARGIN` 已按 issue #5030 整体退场）
MARGINS: tuple[str, ...] = ("HEM_MARGIN",)

#: 已退场的宽方向标识符（C2' 反向守卫）
DROPPED_IDENTIFIERS: tuple[str, ...] = ("SIDE_MARGIN", "side_margin")

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


# ── C1 / C2'：两侧逐值相等（高方向各自跟自己的引擎常量）+ 宽方向余量不得复活 ──────

def test_frontend_no_longer_holds_margin_copies() -> None:
    """（**issue #5043 包 2b 改判**）前端**不得再持有余量常量副本** —— 规则面已迁服务端。

    迁移前本文件钉的是「前端副本与引擎**逐值相等** + 注释引文逐字一致 + 副本真的被消费」。
    用户 2026-09-21 裁定「规则面迁服务端」后，副本的唯一消费者
    `frontend/admin-web/src/lib/door-width-plan.ts` **已删除**，`HEM_MARGIN` 随之下线
    （`SIDE_MARGIN` 更早已按 issue #5030 退场）⇒ 三条判据的前提**全部消失**。
    本判据把它们合并升级为**同强度的死亡条件 + 引擎侧存活**：

    ① **前端任何源文件**都不得再定义这些常量（副本回来 ⇒ 红 —— 第二份会与租户配置脱钩）；
    ② **引擎侧**的定义必须仍然存在且为正（真值源被删 ⇒ 红 —— 否则「不许有副本」会退化成
       「两边都没有」的假绿）。

    红证：在 `frontend/admin-web/src/lib/craft-auto-features.ts` 里加回
    `export const HEM_MARGIN = 0.3` ⇒ 红；删掉 `curtain_calc.py` 的 `HEM_MARGIN = 0.3` ⇒ 红。
    """
    calc = CALC_PY.read_text(encoding="utf8")
    for name in MARGINS:
        assert _py_value(calc, name) > 0, f"引擎侧 {name} 不在了 / 不是正数 ⇒ 真值源缺失（红）"
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "frontend/admin-web/src").rglob("*.ts")):
        src = path.read_text(encoding="utf8")
        for name in MARGINS:
            if f"export const {name}" in src:
                offenders.append(f"{path.relative_to(REPO_ROOT)} → export const {name}")
    assert not offenders, (
        "前端又出现了余量常量副本（规则面已迁服务端 ⇒ 副本会与**租户配置**脱钩）："
        + "; ".join(offenders)
    )


def test_side_margin_does_not_come_back_in_frontend() -> None:
    """C2'（issue #5030 改判）：宽方向余量不得在前端复活（旧 C2 的前提已被裁定删除）。

    旧判据 C2 要求「前端必须**同时**导出 `SIDE_MARGIN` 与 `HEM_MARGIN`」—— 它的前提是
    `SIDE_MARGIN` **存在**。用户 2026-09-21 裁定「订单宽 = 净窗宽、成品宽 = 净窗宽」⇒
    宽方向**没有余量** ⇒ 该常量与配置键 `side_margin` 一并退场 ⇒ 旧判据改成**反向守卫**
    （同强度：新判据凭「源码里再出现该标识符 ⇒ 红」单独判红）。

    ⚠️ 注释里的「已退场」说明不算复活（本仓惯例：口径退场要在注释里留档）。
    """
    lib = _strip_comments(_lib_source())
    hits = [ident for ident in DROPPED_IDENTIFIERS if ident in lib]
    assert hits == [], (
        f"前端代码里又出现 {hits} —— 宽方向余量已按用户 2026-09-21 裁定（issue #5030）"
        "**整体退场**（订单宽 = 净窗宽、成品宽 = 净窗宽 ⇒ 判据 = `窗宽 × 褶倍 > 门幅`）；"
        "它一旦回来，前端判定就与引擎分幅条件静默脱钩 ⇒ 红"
    )


# ── C3：前端注释引用的引擎行逐字一致（值 + 语义注释）──────────────────────────

# ⚠️ 原「注释引文逐字一致」（C3）与「副本必须被消费」（C4）**已随 issue #5043 包 2b 退场** ——
# 两者的主体（前端副本常量及其消费点 `door-width-plan.ts`）都不存在了；
# 「前端不得再持有副本」由上面的 `test_frontend_no_longer_holds_margin_copies`（死亡条件）钉住。


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
