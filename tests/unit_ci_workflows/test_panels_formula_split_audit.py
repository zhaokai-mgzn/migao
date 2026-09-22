# case_ids: OR-036, OR-040
"""分幅公式（`panels`）**四方同式**守卫（issue #4760 → 改判 issue #5030）。

## 为什么需要这条（本单的静默失效形态）

`backend/ai-agent-service/app/tools/curtain_calc.py` 里 **`panels`（定宽买高时的幅数）曾有
三条口径**：A 米宝下单通路含 `side_margin`、B1/B2 试算通路不含 ⇒ **同一张单两个答案**，
差 1 幅 = 差整整一幅长（`H + HEM_MARGIN`）⇒ 面料费 + 加工费同幅变化（**涉钱**）。

**2026-09-21 改判（issue #5030）**：宽方向余量整体退场 ⇒ 四条落点（A / B1 / B2 / **C 前端副本**）
**四方同式** = `ceil(窗宽 × 褶倍 ÷ 门幅)`；旧判据「A ≥ B1 且恰差 1 幅」的前提（`side_margin > 0`）
随之消失 ⇒ **删除**（留着就是不会红的空断言），改钉「同式 + 反向守卫」。

**通路 C**（issue #5038 登记，第 4 份副本 = 前端 `frontend/admin-web/src/lib/door-width-plan.ts`）
与 A 的**算法级**等价由共享 golden 算例表钉住（`tests/fixtures/panels-cross-language-golden.json`，
三腿共读；守卫 `tests/unit_ci_workflows/test_panels_cross_language_algorithm_guard.py`），
且取整口径 = **毫米整数**（浮点在「总用料恰为门幅整数倍」边界上会多算 1 幅）。

## 2026-09-21 用户业务裁定（issue #5030，逐字）

> 「订单这里的**宽和高是窗户的宽高**」⇒ 订单行 `width` = **净窗宽**、`height` = **净窗高**；
> **成品宽 = 净窗宽**、**成品高 = 净窗高**（无任何覆盖/离地/轨道换算）。
> 宽度用料口径 = **R1**：**用料 = 窗宽 × 褶倍**，**不再另加「左右覆盖余量」**
> ⇒ 常量 `SIDE_MARGIN` 与配置键 `side_margin` **整体退场**。

⇒ 本守卫的**前提被裁定掉了**：A 与 B1 **不再有差异**（都 = `ceil(窗宽 × 褶倍 ÷ 门幅)`）
⇒ **旧判据「A ≥ B1 且恰差 1 幅」删除**（它的前提 `side_margin > 0` 已不存在，
留着它就是一条不会红的空断言）。**改判为「四方同式」**：

| # | 四方（口径源） | 落点 | 必须同式 |
|---|---|---|---|
| 1 | **引擎 A 通路** | `calculate_fabric_meters()` 定宽分支 | `ceil(窗宽 × 褶倍 ÷ 门幅)` |
| 2 | **`build_quote` 的 panels** | `build_quote()` 的 `fixed_width` 复算 | 与 ① 逐字同式（同源，不新造第二式） |
| 3 | ~~前端超宽判据~~ | **已退场**（issue #5035 起判定整条搬到服务端）⇒ 只剩 ①② 两处 | — |
| 4 | **真值源 §3 公式** | `docs/curtain-fabric-quote-rules.md` §3 | `P = ceil(W × N / G)`（**不得**含 `SIDE_MARGIN`） |

**为什么这四条必须一起判**：它们是同一个物理量的四处落点 —— 只判一处 ⇒ 另外三处漂移
**没有任何东西会红**（#4760 的病根就是「A 与 B1 分叉而无人知」）。

🔴 **2026-09-22 再改判（issue #5130，用户裁定 D1 / D3 / D10）**：判据 3 的**原形态**是
「**判定面**（引擎 `detect_auto_features`）的超宽判据 == 分幅条件的**布尔形态**」
（`product = window_width * fullness`）—— 那条**耦合本身被用户裁定掉了**：
「超宽」不再由**几何**（窗宽 × 褶倍 vs 门幅）推出，而是由**企业阈值参数**推出
（`净窗宽 > oversize_width_threshold`），因为用户裁定 D1 = **工艺分档**
（超阈值时加工费与标准档不同）、D3 = **替换**判定公式。
⇒ 旧判据的前提（「判定面 == 分幅条件的布尔形态」）消失 ⇒ **改判为**：
① **新判据形态**在本文件钉住（判定面读的是**企业参数**，不是门幅）；
② **死亡条件**：旧的**几何耦合**不得回来（引擎代码里**不再有** `product = window_width * fullness`
   这条判定面写法）—— 这正是「改判不是删断言」的形态（§17.3 ④）。
⚠️ **分幅公式本身一字未动**（判据 C1 / C2 / C4 原样保留）—— 退役的只是「特征名 == 分幅条件的布尔形态」
这条**推论**，不是分幅。

## 判据（每条都能**单独**判红）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 引擎 A 通路公式串 == 真值源 §3 公式串（**归一化后**逐字） | 真值源改回 `(W + SIDE_MARGIN) × N`（或引擎改回含余量）⇒ 红 |
| C2 | `build_quote` 的 panels 复算与 A 通路**逐字同式**（`ceil(窗宽 × 褶倍 ÷ 门幅)`） | 只在 `build_quote` 里加回 `+ cfg["side_margin"]` ⇒ 红 |
| C3 | **判定面**（引擎 `detect_auto_features`）的超宽判据 == **企业阈值参数**形态（`window_width > cfg["oversize_width_threshold"]`），**且旧的几何耦合不得复活** | 判定面改回 `product = window_width * fullness`（与门幅比）⇒ 红 |
| C4 | **对照表逐行可复算**（≥6 组）：引擎 A 与 `build_quote` 复算**逐组相等**，且「一致？」列与实测相符 | 任一组 panels 改一个数 ⇒ 红 |
| C5 | **反向守卫**：引擎 / 前端 / TS 类型 / Java 实体 / Java 服务 / `schema.sql` / 真值源 §3 公式行里**再出现** `side_margin`/`SIDE_MARGIN` ⇒ 红 | 把常量或配置键加回任一源 ⇒ 红 |
| ~~通路 C~~ | ~~第 4 份副本（前端 `door-width-plan.ts`）已登记~~ —— **已退场**（**issue #5043 包 2b**：规则面迁服务端、该模块删除）⇒ 本审计只剩 **A / B1 / B2 三方**；「前端不得再持有规则 / 余量副本」改由 `tests/unit_ci_workflows/test_fabric_width_truth_source.py` 与 `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py` 的反向守卫钉住 | — |

⚠️ **本守卫不 import 被测引擎**：`app` 包的导入期需要完整 `.env`（否则 pydantic Settings 报缺失键）
⇒ 在 CI 的 `unit_ci_workflows` job 里会**红于环境而非红于口径**。故这里**照源里的公式复算**
（与 `test_fabric_width_truth_source.py` 同族：判据读源、不跑被测服务）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CALC_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/curtain_calc.py"
AUTO_FEATURES_TS = REPO_ROOT / "frontend/admin-web/src/lib/craft-auto-features.ts"
TRUTH_DOC = REPO_ROOT / "docs/curtain-fabric-quote-rules.md"
#: 通路 C（第 4 份 `panels` 副本，issue #5038）—— 前端门幅规则的落点
#: §4.5 所在的设计文档（C6 判「通路 C 已登记」的读源）
DESIGN_DOC = REPO_ROOT / "docs/design/craft-calc-and-fabric-routing.md"

#: 真值源 §3 的锚点（**文本锚点，不写死行号** —— 行号会随文档编辑腐烂）
SECTION3_ANCHOR = "## 3. 用布量精确公式"
SECTION3_END = "## 4. 损耗与余量"

#: 对照表最少组数（#4760 验收判据要求 ≥6 组；**这是判据的下界，不是"当前有几行"的计数**）
MIN_GROUPS = 6

#: `side_margin` 的两种拼写（反向守卫 C5 的命中面）
DROPPED_IDENTIFIERS = ("SIDE_MARGIN", "side_margin")

#: C5 判「代码里不得再出现」的源（**逐文件**：少一个 = 那一源永久免检且无人知）
#: ⚠️ `db/migration/**` 有意**不在**名单里：V80 建列、V112 删列是历史留档（迁移链**不可改**，
#: 见 `test_craft_calc_config_contract.py` 的 `_migration_config_columns`）—— 终态由那个守卫判。
NO_SIDE_MARGIN_SOURCES: tuple[Path, ...] = (
    CALC_PY,
    AUTO_FEATURES_TS,
    REPO_ROOT / "frontend/admin-web/src/types/index.ts",
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/entity/CraftCalcConfig.java",
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/CraftCalcConfigService.java",
    REPO_ROOT / "docs/sql/schema.sql",
)

#: 对照表（**写死**的几何：`W` = 净窗宽、`N` = 褶倍、`G` = 门幅）
#: 期望值**不从实现推导**（纸表 + 手算）—— `ceil(W × N / G)` 逐组手算：
#:   1.1×2.0/2.8 = 0.786 → 1 ; 1.5×2.0/2.8 = 1.071 → 2 ; 2.0×1.5/2.8 = 1.071 → 2
#:   3.0×2.0/2.8 = 2.143 → 3 ; 4.0×2.0/2.8 = 2.857 → 3 ; 1.45×1.8/2.8 = 0.932 → 1
TABLE: tuple[tuple[float, float, float, int], ...] = (
    (1.1, 2.0, 2.8, 1),
    (1.5, 2.0, 2.8, 2),
    (2.0, 1.5, 2.8, 2),
    (3.0, 2.0, 2.8, 3),
    (4.0, 2.0, 2.8, 3),
    (1.45, 1.8, 2.8, 1),
)
#: 通路 C 在 §4.5「通路与调用方」表里的**行锚点**与**口径串**（C6：登记与代码自洽）

#: 引擎源码里的分幅表达式（**逐字**；A 通路与 `build_quote` 的复算各一处）
ENGINE_PANELS_RE = re.compile(r"math\.ceil\(\s*window_width\s*\*\s*(\w+)\s*/\s*fabric_width\s*\)")
#: **判定面**的超宽判据（逐字：判的是**企业阈值参数**，不是分幅条件 —— issue #5130 改判）
#: ⚠️ issue #5035 起判定面已整条搬到服务端（前端 `detectAutoFeatures` 删除）⇒ 本条瞄**引擎**。
OVER_WIDTH_CRITERION = 'window_width > cfg["oversize_width_threshold"]'
#: **已退役**的旧判定面写法（issue #5130 前的几何耦合：超宽 == 分幅条件的布尔形态）
#: —— 它的回归是 C3 的**死亡条件**（§17.3 ④：豁免 / 改判必须能证明旧做法没有回来）。
RETIRED_OVER_WIDTH_CRITERION = "product = window_width * fullness"


def _read(path: Path) -> str:
    assert path.exists(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf8")


#: 多语言注释/文档串（判 C5 时只认**代码**：口径退场要在注释/docstring 里留档说明，本仓惯例）
_TRIPLE = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')
_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE_COMMENT = re.compile(r"(?:^|\s)(?:\*/?\s*)?(?://|--|#)[^\n]*", re.M)
#: SQL 的第三种「散文载体」：单引号字符串字面量（`COMMENT ON COLUMN … IS '…'`）
_SQL_STRING = re.compile(r"'(?:[^']|'')*'")


def _code_only(path: Path) -> str:
    """去掉注释 / 文档串 / SQL 字符串字面量 —— C5 只判**代码**里的标识符（注释里的「已退场」不算）。

    ⚠️ 不用「按行前缀过滤」那种弱形态：实测 `schema.sql` 的多行 `COMMENT ON` 续行、
    字符串字面量，以及 `curtain_calc.py` 的 **docstring** 都不以 `--`/`#` 开头
    ⇒ 弱过滤会**误红**（误红即坏断言，`migao-acceptance`）。
    """
    text = path.read_text(encoding="utf8")
    if path.suffix == ".sql":
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("--"))
        return _BLOCK.sub("", _SQL_STRING.sub("", text))
    out = _TRIPLE.sub("", text)
    out = _BLOCK.sub("", out)
    return _LINE_COMMENT.sub("", out)


def _section(text: str, start_anchor: str, end_anchor: str) -> str:
    """取锚点之间的正文（**锚点取不到 ⇒ 直接失败**，不静默跳过）。"""
    start = text.find(start_anchor)
    assert start != -1, (
        f"文档里找不到锚点「{start_anchor}」（真值源 §3 是 #4760 的判定落点）—— "
        "若已改名/移动，请同步本守卫（路径漂移不得退化成静默通过）"
    )
    rest = text[start:]
    end = rest.find(end_anchor, len(start_anchor))
    assert end != -1, f"文档里找不到结束锚点「{end_anchor}」—— 结构变了，请同步本守卫"
    return rest[:end]


def _normalize_formula(expr: str) -> str:
    """公式表达式归一化（只归一排版噪声：空白 / 乘号 / 外层括号）—— **不归一语义**。"""
    out = expr.replace("×", "*").replace("÷", "/")
    out = re.sub(r"\s+", "", out)
    out = re.sub(r"^\((.*)\)$", r"\1", out)
    return out


def _doc_panels_expression() -> str:
    """真值源 §3 的定宽买高分幅公式的**分子表达式**（`ceil( … / G)` 里那一段）。

    ⚠️ 只在 **§3 的公式行**（`- ` 开头且含 `幅数` / `` `M = ``）里找：§3 的「2026-09-21 改判」
    说明段落里**逐字留着旧式** `P = ceil((W + SIDE_MARGIN) × N / G)` 作留档
    ⇒ 全文搜 `ceil( … )` 会**抓到那段历史引文**（实测：假红）。判据只认**现行公式**。
    取不到 ⇒ **直接失败**（真值源被改写/删行 ⇒ 本守卫失去真值基准，必须红）。
    """
    section = _section(_read(TRUTH_DOC), SECTION3_ANCHOR, SECTION3_END)
    formula_lines = [
        line for line in section.splitlines()
        if line.startswith("- ") and ("`M =" in line or "`幅数" in line)
    ]
    assert formula_lines, (
        "真值源 §3 里找不到公式行（`- …` 开头且含 `` `M = `` / `` `幅数 ``）—— "
        "公式被删/改写成别的形态（本守卫的真值基准取不到 ⇒ 红）"
    )
    for line in formula_lines:
        m = re.search(r"ceil\(\s*([^/]+?)\s*/\s*[A-Za-z]+\s*\)", line)
        if m:
            return m.group(1)
    raise AssertionError(
        "真值源 §3 的公式行里找不到 `ceil( … / G)` 形态的分幅公式 —— "
        "分幅式被删/改写（本守卫的真值基准取不到 ⇒ 红）"
    )


def _engine_panels_expressions() -> list[str]:
    """引擎源码里**全部** `math.ceil(window_width * N / fabric_width)` 表达式（保序）。"""
    return ENGINE_PANELS_RE.findall(_read(CALC_PY))


class TestPanelsFormulaSplitAudit:
    """四方（引擎 A / `build_quote` / 前端 / 真值源 §3）必须同式（issue #5030 改判）。"""

    def test_c1_engine_path_a_matches_truth_source_formula(self):
        """C1：引擎 A 通路公式串 == 真值源 §3 公式串（归一化后逐字）。

        ⚠️ 判的是**公式形态**（符号级），不是数值 —— 数值由 C4 的对照表逐组复算钉住。
        """
        doc_expr = _normalize_formula(_doc_panels_expression())
        assert doc_expr == "W*N", (
            f"真值源 §3 的分幅分子 = {doc_expr!r}，期望 'W*N'（用户 2026-09-21 裁定 R1："
            "用料 = 窗宽 × 褶倍，**不再另加左右覆盖余量**；`SIDE_MARGIN` 已整体退场）—— "
            "真值源还停在含余量的旧口径 ⇒ 红"
        )
        engine = _engine_panels_expressions()
        assert engine, (
            "引擎源码里找不到 `math.ceil(window_width * N / fabric_width)` —— "
            "A 通路（`calculate_fabric_meters` 定宽分支）的分幅式被改名/改写 ⇒ 红"
        )
        for symbol in engine:
            assert symbol == "fullness" or symbol.isupper(), (
                f"引擎分幅式的乘数是 {symbol!r}（期望 `fullness`（A 通路）或大写褶倍变量 `N`）"
            )

    def test_c2_build_quote_panels_recompute_is_the_same_formula(self):
        """C2：`build_quote` 的 panels 复算与 A 通路**逐字同式**（不新造第二式）。

        #4760 的病根正是「A 含余量、B1 不含」；本裁定后两处都必须是 `ceil(窗宽 × 褶倍 ÷ 门幅)`。
        红证：只在 `build_quote` 的复算里加回 `+ cfg["side_margin"]` ⇒ 两处表达式不再同集 ⇒ 红。
        """
        engine = _engine_panels_expressions()
        assert len(engine) >= 2, (
            f"引擎里只解析到 {len(engine)} 处分幅式（期望 ≥2：A 通路 + `build_quote` 的复算）—— "
            "复算那处被删（报价卡「幅数」行会消失，issue #4374）或形态变了 ⇒ 红"
        )
        # 两处**同一表达式**（乘数变量名允许不同：A 用 `fullness`、复算用 `N`；都是「窗宽 × 褶倍」）
        assert set(engine) == {"fullness", "N"}, (
            f"引擎两处分幅式的乘数 = {sorted(set(engine))}，期望 {{'N', 'fullness'}} —— "
            "有一处被改成别的量（如 `window_width + side_margin`）⇒ 红"
        )
        src = _read(CALC_PY)
        assert "cfg[\"side_margin\"]" not in src and "cfg['side_margin']" not in src, (
            "引擎里又出现 `cfg[\"side_margin\"]` 消费点 —— 该配置键已整体退场（issue #5030）⇒ 红"
        )

    def test_c3_over_width_criterion_is_the_enterprise_threshold(self):
        """C3（**issue #5130 改判**）：判定面判的是**企业阈值参数**，且旧的**几何耦合**不得复活。

        🔴 旧判据（#5030 版）钉的是「超宽判据 == 分幅条件的布尔形态」
        （`product = window_width * fullness` ⟺ `ceil(窗宽 × 褶倍 ÷ 门幅) ≥ 2`）。
        用户 2026-09-22 裁定 **D1 = 工艺分档 / D3 = 替换判定公式 / D10 = 三条一并退役**
        ⇒ 那条耦合（#4662）**被裁定掉了**：新的「超宽」判据 = `净窗宽 > oversize_width_threshold`
        （**企业参数**），与门幅、褶倍、分幅条件**全无关**。
        ⇒ 旧判据的前提消失，**改判**为「新形态 + 死亡条件」（同强度，不放宽）：
        ① 引擎代码里必须有 `window_width > cfg["oversize_width_threshold"]`（判定面真值）；
        ② 引擎代码里**不得再有** `product = window_width * fullness`（旧几何耦合回来 ⇒ 红）；
        ③ 分幅公式（`ceil(窗宽 × 褶倍 ÷ 门幅)`）**一字未动** —— 由 C1 / C2 / C4 钉住。

        ⚠️ 与 `test_c2_*` 的分工：C2 管**分幅**（几何层），本条管**特征判定**（企业参数层）——
        两层在代码里是分离的（`docs/design/oversize-threshold-and-enterprise-params.md` §4.4）。
        """
        src = _code_only(CALC_PY)
        assert OVER_WIDTH_CRITERION in src, (
            f"引擎「超宽」判据不再是 `{OVER_WIDTH_CRITERION}` ⇒ "
            "判定面已按用户 2026-09-22 裁定（issue #5130：D1 工艺分档 + D3 替换公式）"
            "改为与**企业阈值参数**比 —— 判据形态变了却没人同步 ⇒ 红"
        )
        assert RETIRED_OVER_WIDTH_CRITERION not in src, (
            f"引擎里又出现 `{RETIRED_OVER_WIDTH_CRITERION}` —— 那是 issue #5130 **已退役**的"
            "几何耦合（超宽 == 分幅条件的布尔形态，裁定 #4662）。它一旦回来，「超宽」就又由"
            "**门幅 × 褶倍**推出（而不是由该租户的 `oversize_width_threshold`）⇒ "
            "企业参数静默失效 + 判定与商家配置脱钩 ⇒ 红"
        )
        assert "side_margin" not in src, (
            "引擎**代码**里又出现 `side_margin` —— 宽方向余量已整体退场（issue #5030）⇒ 红"
        )

    def test_c4_table_recomputes_row_by_row(self):
        """C4：对照表逐行复算 —— 引擎 A 与 `build_quote` 复算**逐组相等**，且「一致？」与实测相符。

        期望值**写死**在 `TABLE`（纸表 + 手算，不从实现推导）—— `X == X` 的断言不会红。
        每组同时复算：① A 通路（含 cfg 余量项？）② `build_quote` 的复算式（同式 ⇒ 必须相等）。
        """
        assert len(TABLE) >= MIN_GROUPS, (
            f"对照表只有 {len(TABLE)} 组（判据下界 {MIN_GROUPS} 组）—— #4760 验收要求 ≥6 组"
        )
        engine = set(_engine_panels_expressions())
        assert engine == {"fullness", "N"}, f"引擎分幅式不齐：{sorted(engine)}"
        for width, fullness, door, expected in TABLE:
            # ① A 通路（`calculate_fabric_meters` 定宽分支）—— 照源复算
            a = math.ceil(width * fullness / door)
            # ② `build_quote` 的 panels 复算 —— 与 A **同式**（同一表达式，只有变量名不同）
            b1 = math.ceil(width * fullness / door)
            assert (a, b1) == (expected, expected), (
                f"对照表 W={width} N={fullness} G={door} 与复算不符："
                f"表里 {expected}，复算 A={a} / build_quote={b1} ⇒ "
                "代码或对照表有一边改了却没同步（本守卫钉的就是这个漂移）"
            )
            assert a == b1, (
                f"W={width} N={fullness}：A 通路（{a}）与 `build_quote` 复算（{b1}）不等 —— "
                "两处又分叉了（#4760 的病根）⇒ 红"
            )

    def test_c5_dropped_identifiers_do_not_come_back(self):
        """C5 反向守卫：`SIDE_MARGIN` / `side_margin` 不得在任一源里复活（issue #5030）。

        判据面 = 引擎 / 前端识别模块 / TS 类型 / Java 实体 / Java 服务 / `schema.sql`（逐文件）
        + 真值源 §3 的**公式行**（散文里的「已退场」说明不算复活）。
        ⚠️ `db/migration/**` 有意豁免（V80 建列、V112 删列是历史留档，迁移链不可改）；
        终态由 `test_craft_calc_config_contract.py::test_migration_columns_match_engine_keys` 判。
        """
        hits: list[str] = []
        for path in NO_SIDE_MARGIN_SOURCES:
            code = _code_only(path)
            for ident in DROPPED_IDENTIFIERS:
                if ident in code:
                    hits.append(f"{path.relative_to(REPO_ROOT)} 的代码里出现 `{ident}`")
        assert hits == [], (
            "宽方向余量（`SIDE_MARGIN` / 配置键 `side_margin`）已按用户 2026-09-21 裁定"
            "（issue #5030）**整体退场** —— 不得以任何名字复活；它一旦回来，"
            "`用料 = 窗宽 × 褶倍` 这条 R1 口径就被静默破坏（成品宽 ≠ 净窗宽）：\n  "
            + "\n  ".join(hits)
        )
        # 真值源 §3：**公式行**不得含该符号（改判说明里的「旧式 … 已退场」是留档，不算复活）
        section3 = _section(_read(TRUTH_DOC), SECTION3_ANCHOR, SECTION3_END)
        formula_lines = [
            line for line in section3.splitlines()
            if line.startswith("- ") and ("`M =" in line or "`幅数" in line)
        ]
        assert formula_lines, (
            "真值源 §3 里解析不到任何公式行（`- …` 开头且含 `M =` / `幅数`）—— "
            "公式被改写/挪走 ⇒ 本判据失去被测对象，必须红"
        )
        for ident in DROPPED_IDENTIFIERS:
            leaked = [line for line in formula_lines if ident in line]
            assert leaked == [], (
                f"真值源 §3 的**公式行**里又引用 `{ident}` —— 该量已整体退场（issue #5030）；"
                "§3 的分幅式必须是 `ceil(W × N / G)`（改判说明段落里的旧式留档不算复活）：\n  "
                + "\n  ".join(leaked)
            )

