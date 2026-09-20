# case_ids: OR-040, MC-012
"""「**散文里硬编码数值常量**」的漂移守卫（issue #4819）。

## 病根（本单要治的静默失效形态）

`docs/curtain-fabric-quote-rules.md` 是本仓**反复被引用的真值源**（#4760 的判定逐字引它的 §3）。
而它的 §3 曾把算料引擎的余量常量**用散文抄了一遍**（`M = (W + 0.3) × N` / `M = P × (H + 0.3)` /
`M = (W + 0.2) × (H + 0.3)`，数值 = `backend/ai-agent-service/app/tools/curtain_calc.py` 的
`SIDE_MARGIN` / `HEM_MARGIN` / `ROMAN_SIDE`）。

这是「注释漂移 = 假绿来源」的**反向**形态：不是「注释说做了其实没做」，而是
「**注释说的数已经不是真数**」。危害比代码副本漂移更坏 —— 它会被后来人当成**权威**做判定。

⚠️ **本单实测的红证（改动前）**：把引擎与前端副本的余量同时改成 `0.35`（`frontend/admin-web/src/lib/craft-auto-features.ts`
的副本也改，以避开 #4656 的跨语言守卫）⇒ `tests/unit_ci_workflows/` 全量 **1442 passed**，
**文档仍写 0.3 而没有任何东西红** —— 散文里的数**完全没有守卫**。

## 本单的修法（候选①「消灭副本」，首选）

**不再把数抄进散文**：§3 等规范性小节只写符号名（`SIDE_MARGIN`），数值集中到 §0 的
「数值常量清单」**一处**，并由本守卫与引擎源码**逐值比对**。

> 候选②（给散文里的数加断言）**未采用**：散文格式自由，断言只能钉「某几个串里出现某个数」
> ⇒ 改措辞即静默失效（`test_declaration_truth_guards.py` 已实证这类守卫的脆弱面）。
> 消灭副本后「数说不说谎」这个问题**不存在**，而不是「被检测出来」。

## 判据（全部**读源**；本文件**不写死任何常量值**）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | §0 清单里每个符号的**声称值** == 引擎源码里该常量的**真值**（逐值读源） | 把引擎 `SIDE_MARGIN` 改成 `0.35` 而不改文档 ⇒ 红；把文档里的 `0.3` 改成 `0.35` ⇒ 红 |
| C2 | §3 的公式行里**不得出现**这些常量的数值字面量（消灭副本，防回退） | 把 §3 的 `(W + SIDE_MARGIN)` 改回 `(W + 0.3)` ⇒ 红 |
| C3 | **判别力下界（反恒真）**：符号表必须非空且覆盖 §3 实际引用的符号；每个符号必须在引擎源码里**真被消费**（除定义处外还有引用）；值必须为正数 | 删掉 §0 的表格 ⇒ 红；把 `ROMAN_SIDE` 内联成字面量（定义还在但无消费点）⇒ 红 |
| C4 | **文档不得同时声称同一个常量的两个不同数值**（`0.3` 与 `0.35` 并存 ⇒ 必有一处说谎） | 往 §0 之外再抄一份不同值的余量 ⇒ 红 |
| C5 | **注入式自证**：C1~C4 的判定函数在**构造的**缺陷载荷上必须报错；同一载荷不注入 ⇒ 通过 | 见 `TestGuardSelfProof`（证明主测试的绿不是空跑） |

⚠️ **本守卫不 import 被测引擎**（`app` 包的导入期需要完整 `.env` ⇒ 会红于环境而非红于口径）
—— 与 `test_hem_margin_cross_language_drift.py` / `test_fabric_width_truth_source.py` 同族，照源读常量。

⚠️ **边界（照实登记，别把「登记了」读成「治住了」）**：本守卫只覆盖 §0 清单登记的 **12 个标量常量**
+ §3 的公式行。字典型常量（`DEFAULT_FULLNESS` / `DEFAULT_PROCESSING_PRICE` / `DEFAULT_CRAFT_TIERS`）
与拼色系数表的散文副本仍散在 §1 / §5 / §8 / §10；`docs/design/**` 的引用面（`docs/design/` 不在
drift 受管引用面内）也**未收口** —— 均登记在 issue #4819 报告的分叉项里，不冒充已覆盖。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 真值源：算料引擎（**只读**，本单不改它）
CALC_PY = REPO / "backend/ai-agent-service/app/tools/curtain_calc.py"
#: 被判的文档（本仓反复引用的真值源）
DOC = REPO / "docs" / "curtain-fabric-quote-rules.md"

#: §0 清单的锚点（**文本锚点，不写死行号** —— 行号会随文档编辑腐烂）
SECTION0_ANCHOR = "## 0. 数值常量清单"
SECTION0_END = "## 1. 褶皱倍数 N"
#: §3 的锚点
SECTION3_ANCHOR = "## 3. 用布量精确公式"
SECTION3_END = "## 4. 损耗与余量"

#: 清单必须覆盖的常量（符号 → 引擎源码里的常量名）。**值一律从源码读，这里不写数。**
REQUIRED_CONSTANTS: dict[str, str] = {
    "SIDE_MARGIN": "SIDE_MARGIN",
    "HEM_MARGIN": "HEM_MARGIN",
    "ROMAN_SIDE": "ROMAN_SIDE",
    "ROD_EXTENSION": "ROD_EXTENSION",
    "PLEAT_FABRIC_PER_FOLD": "PLEAT_FABRIC_PER_FOLD",
    "MARGIN_SINGLE": "MARGIN_SINGLE",
    "MARGIN_MULTI": "MARGIN_MULTI",
    "MIN_FULLNESS": "MIN_FULLNESS",
    "EYELET_TAPE_PRICE": "EYELET_TAPE_PRICE",
    "ROD_PRICE": "ROD_PRICE",
    "TIEBACK_PRICE": "TIEBACK_PRICE",
    "INSTALL_PRICE": "INSTALL_PRICE",
}

#: §3 里**必须**以符号形态出现的量（公式的被引用面；缺一个 ⇒ 副本可能已被抄回散文）
REQUIRED_IN_SECTION3 = ("SIDE_MARGIN", "HEM_MARGIN", "ROMAN_SIDE")

#: 浮点字面量（`0.3` / `0.35` 都算；`W` / `2.8` 里的整数不算）
_FLOAT = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w.])")
#: 代码里的**消费点**（`NAME` 出现在定义行之外）——用 AST 数，不用正则（正则会被注释误命中）
_SCALAR_DEF = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*([0-9.]+)\s*(?:#.*)?$")


def _section(text: str, start_anchor: str, end_anchor: str) -> str:
    """取锚点之间的正文（**锚点取不到 ⇒ 直接失败**，不静默跳过 —— 路径/结构漂移不得退化成绿）。"""
    start = text.find(start_anchor)
    assert start != -1, (
        f"文档里找不到锚点「{start_anchor}」—— 它被改名/删除/移动了。"
        "锚点漂移不得退化成静默通过：请同步本守卫（issue #4819）"
    )
    rest = text[start:]
    end = rest.find(end_anchor, len(start_anchor))
    assert end != -1, f"文档里找不到结束锚点「{end_anchor}」—— 结构变了，请同步本守卫"
    return rest[:end]


def _doc_text() -> str:
    return DOC.read_text(encoding="utf8")


def _calc_text() -> str:
    return CALC_PY.read_text(encoding="utf8")


def _engine_value(source: str, name: str) -> float:
    """从引擎源码里取模块级标量常量（取不到 ⇒ **直接失败**，不静默跳过）。"""
    m = re.search(rf"^{name}\s*=\s*([0-9.]+)", source, re.M)
    assert m, (
        f"`curtain_calc.py` 里找不到常量 {name} —— 本守卫必须能读到真值；"
        "若该常量已改名/搬走，请同步 §0 清单与本守卫的 REQUIRED_CONSTANTS"
    )
    return float(m.group(1))


def _consumed_names(source: str) -> set[str]:
    """源码里**除定义处外**还被引用的模块级名字（AST，跳过 docstring ⇒ 注释不算消费）。

    ⚠️ 用 AST 而不是正则：正则会把**注释/docstring 里的提及**读成消费 ⇒ 判据退化成恒真
    （「常量还在、只是判定处内联了字面量」这种坏形态就抓不到）。
    """
    tree = ast.parse(source)
    defined: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                defined.add(t.id)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass  # `cfg["side_margin"]` 这类键名不是常量引用
    return used & defined


def _parse_checklist(section: str) -> dict[str, tuple[str, float]]:
    """解析 §0 清单表：`| 符号 | 定义 | 语义 | 当前值 |` ⇒ `{符号: (常量名, 声称值)}`。

    解析不到任何行 ⇒ **失败**（不静默空跑：表格被删 = 判据失去被测对象）。
    """
    out: dict[str, tuple[str, float]] = {}
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        symbol = cells[0].strip("`")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", symbol):
            continue
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cells[3]):
            continue
        name = re.search(r"`([A-Z][A-Z0-9_]*)`", cells[1])
        assert name, (
            f"§0 清单里 {symbol} 的「引擎常量定义」列读不出常量名（该列必须写清常量名）—— "
            "取不到真值来源 = 这一行无法比对，不得静默放行"
        )
        out[symbol] = (name.group(1), float(cells[3]))
    return out


def _doc_float_literals(section: str) -> list[float]:
    """取正文里的浮点字面量（跳过 markdown 表格行 —— 清单本身就要写值）。"""
    values: list[float] = []
    for line in section.splitlines():
        if line.strip().startswith("|"):
            continue
        values += [float(x) for x in _FLOAT.findall(line)]
    return values


# ── C1：清单声称值 == 引擎真值（判定体抽成纯函数，供注入式自证复用）────────────

def _checklist_drift(text: str, source: str) -> list[str]:
    """C1 判定体：§0 清单的「当前值」列 vs 引擎源码里的常量（**逐值读源**）⇒ 漂移清单。

    返回空列表 = 无漂移。抽成纯函数是**为了可注入自证**：自证直接喂构造载荷给同一个判定体，
    而不是另写一份"看起来像判据"的断言（那样自证与被证对象不同源 ⇒ 证明不了任何事）。
    """
    drift: list[str] = []
    rows = _parse_checklist(_section(text, SECTION0_ANCHOR, SECTION0_END))
    for symbol, (name, claim) in rows.items():
        truth = _engine_value(source, name)
        if truth <= 0:
            drift.append(f"{symbol}: 引擎 {name} 读出来不是正数（{truth}）")
        elif claim != truth:
            drift.append(f"{symbol}: 文档写 {claim} / 引擎 {name} = {truth}")
    return drift


def _section3_literal_hits(text: str, source: str) -> list[str]:
    """C2 判定体：§3 里出现的「清单常量数值字面量」⇒ 命中清单（空 = 干净）。"""
    rows = _parse_checklist(_section(text, SECTION0_ANCHOR, SECTION0_END))
    literals = _doc_float_literals(_section(text, SECTION3_ANCHOR, SECTION3_END))
    hits: list[str] = []
    for symbol, (name, _claim) in rows.items():
        value = _engine_value(source, name)
        if value in literals:
            hits.append(f"§3 里的 {value} = {symbol}")
    return hits


def test_checklist_values_equal_engine_truth() -> None:
    """C1：§0 清单的「当前值」列必须与引擎源码里的常量**逐值相等**（读源，不写死）。"""
    source = _calc_text()
    text = _doc_text()
    rows = _parse_checklist(_section(text, SECTION0_ANCHOR, SECTION0_END))
    assert len(rows) >= len(REQUIRED_CONSTANTS), (
        f"§0 清单只解析到 {len(rows)} 行（必须覆盖 {len(REQUIRED_CONSTANTS)} 个常量）—— "
        "清单被删/被截断 ⇒ 数值真值源回到散文里 ⇒ 红"
    )
    drift = _checklist_drift(text, source)
    assert drift == [], (
        "§0 清单与引擎常量漂移：" + "；".join(drift) +
        "。本文是**被反复引用的真值源**（#4760 的判定就逐字引它）⇒ 这处漂移会被当成权威用错；"
        "改常量请同改 §0（改哪边都要改另一边）"
    )


def test_checklist_covers_required_constants() -> None:
    """C1 补：清单必须覆盖**被引用面**的每个常量（少一个 = 那个常量回到散文里）。"""
    rows = _parse_checklist(_section(_doc_text(), SECTION0_ANCHOR, SECTION0_END))
    missing = sorted(set(REQUIRED_CONSTANTS) - set(rows))
    assert not missing, (
        f"§0 清单缺这些常量：{missing} —— 它们仍被 §3 等公式引用，缺登记 = 数值又只活在散文里"
    )


# ── C2：§3 的公式行不得出现数值字面量（消灭副本）──────────────────────────────

def test_section3_has_no_constant_literal() -> None:
    """C2：§3 只写符号名 —— 出现清单里任一个常量的数值字面量即判红（防副本回潮）。"""
    hits = _section3_literal_hits(_doc_text(), _calc_text())
    assert hits == [], (
        "§3 里出现了常量数值字面量（" + "；".join(hits) + "）—— "
        "散文又抄了一份副本：改常量它不会跟着变，且**没有任何东西会红**（issue #4819 的形态）。"
        "请改回符号名（数值只留在 §0 清单里）"
    )


def test_section3_references_symbols() -> None:
    """C2 补：§3 必须**真的**引用符号（否则「没有字面量」可能是把公式整段删了）。"""
    section3 = _section(_doc_text(), SECTION3_ANCHOR, SECTION3_END)
    for symbol in REQUIRED_IN_SECTION3:
        assert symbol in section3, (
            f"§3 里找不到符号 `{symbol}` —— 公式被删/被改写成别的形态（判据失去被测对象）⇒ 红"
        )


# ── C3：判别力下界（反恒真 / 常量必须真被消费）────────────────────────────────

def test_symbols_are_consumed_not_inlined() -> None:
    """C3：每个符号在引擎源码里必须**除定义处外**还有消费点（否则判定处已被内联成字面量）。"""
    source = _calc_text()
    consumed = _consumed_names(source)
    for symbol, (name, _claim) in _parse_checklist(
            _section(_doc_text(), SECTION0_ANCHOR, SECTION0_END)).items():
        assert name in consumed, (
            f"引擎源码里 {name} 只有定义处、没有消费点 —— 判定处很可能已被内联成字面量"
            f"（常量改了判定不跟），或该常量已成死码；此时 §0 清单里的 {symbol} 是一句**假承诺**"
        )


def test_guard_has_discriminating_power() -> None:
    """C3 补：清单非空、值全为正数、且至少两个不同值（防整表被填成同一个数）。"""
    rows = _parse_checklist(_section(_doc_text(), SECTION0_ANCHOR, SECTION0_END))
    assert rows, "§0 清单解析为空 ⇒ 判据空跑（不会红的断言 = 空断言）"
    values = {claim for _name, claim in rows.values()}
    assert all(v > 0 for v in values), f"§0 清单里出现非正值：{sorted(values)}"
    assert len(values) >= 2, (
        f"§0 清单的值全是 {values} ⇒ 解析口径很可能把整列读成同一个数（判据失去判别力）"
    )


# ── C4：同一常量不得有两个互相矛盾的声称值 ────────────────────────────────────

def _conflicting_claims(text: str, source: str) -> list[str]:
    """C4 判定体：清单登记的常量值**不得**在别处以**不同**数值出现（两个数并存 ⇒ 必有一处说谎）。

    §0 之外的**同值**副本不判（那是冗余，不是矛盾）；只抓「同一个量两个不同数」这种
    **自相矛盾**形态 —— 正是 #4819 里「改常量后文档静默说谎」的可见残影。

    ⚠️ 只判**等号标注**这一种形态（`` `SYMBOL` = 0.3 ``）—— 它是无歧义的「值声明」。
    **有意不判**括号式（`` `SYMBOL`（0.3） ``）：它与「公式里紧跟一个约束值」
    （如 `成品高 ≤ G − HEM_MARGIN（2.8m 定高上限…）`）**静态不可区分** ⇒ 判它会把正确文档判红
    （**误红即坏断言**，`migao-acceptance`）⇒ 按本仓口径「误红不判，如实登记」：
    括号式副本属**已登记未收口**（issue #4819 报告的分叉项）。
    """
    checklist = _section(text, SECTION0_ANCHOR, SECTION0_END)
    body = text.replace(checklist, "")
    conflicts: list[str] = []
    for symbol, (name, _claim) in _parse_checklist(checklist).items():
        truth = _engine_value(source, name)
        pattern = re.compile(rf"{re.escape(symbol)}`?\s*[=＝]\s*([0-9]+(?:\.[0-9]+)?)")
        for line in body.splitlines():
            for m in pattern.finditer(line):
                if float(m.group(1)) != truth:
                    conflicts.append(
                        f"`{symbol}`（= {truth}）在散文里被标成 {m.group(1)}：{line.strip()}"
                    )
    return conflicts


def test_no_conflicting_value_claimed_outside_checklist() -> None:
    """C4：清单登记的常量值不得在别处以不同数值出现（两个数并存 ⇒ 必有一处说谎）。"""
    conflicts = _conflicting_claims(_doc_text(), _calc_text())
    assert conflicts == [], (
        "同一条规则里出现两个互相矛盾的数值（两个数并存 ⇒ 必有一处说谎，"
        "后来人会按错的那个做判定）：\n  " + "\n  ".join(conflicts)
    )


# ── C5：注入式自证（证明上面的绿不是空跑）─────────────────────────────────────

def _payload(checklist: str, section3: str) -> str:
    """拼一份**最小文档载荷**（真实锚点 + 注入内容）—— 红只可能来自被注入的那一处。"""
    return (
        f"{SECTION0_ANCHOR}\n\n{checklist}\n\n{SECTION0_END}\n\n"
        f"{SECTION3_ANCHOR}\n{section3}\n\n{SECTION3_END}\n"
    )


#: 一个**语法正确**的清单行模板（值是占位符，由测试按「当前真值」或「陈旧值」填入）
_ROW = "| `SIDE_MARGIN` | `curtain_calc.py` 的 `SIDE_MARGIN` | 左右覆盖余量 | {v} |"


class TestGuardSelfProof:
    """注入式自证：**同一个判定体**在构造的缺陷载荷上必须报错，否则主测试的绿是空跑。

    ⚠️ 自证必须复用被测判定体（`_checklist_drift` / `_section3_literal_hits` /
    `_conflicting_claims` / `_consumed_names`）—— 另写一份"看起来像判据"的断言只能证明
    「那段新代码会红」，证明不了主判据会红（`migao-acceptance`：不会红的断言 = 空断言）。
    """

    def test_c1_detects_stale_claim(self) -> None:
        """C1 自证：清单声称值与引擎真值不符 ⇒ 同一判定体必须报出漂移。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        stale = f"{truth}5"          # 构造一个**必然不等于**真值的数（不写死任何常量值）
        payload = _payload(_ROW.format(v=stale), "`M = (W + SIDE_MARGIN) × N`")
        drift = _checklist_drift(payload, source)
        assert drift and "SIDE_MARGIN" in drift[0], (
            f"注入陈旧值 {stale}（真值 {truth}）后判定体没报漂移：{drift} ⇒ C1 是空断言"
        )

    def test_c1_clean_payload_passes(self) -> None:
        """C1 反向：同一载荷填**真值** ⇒ 判定体不得报漂移（证明红由注入引起）。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        payload = _payload(_ROW.format(v=truth), "`M = (W + SIDE_MARGIN) × N`")
        assert _checklist_drift(payload, source) == [], "干净载荷被判成漂移 ⇒ 判据误红"

    def test_c2_detects_literal_in_section3(self) -> None:
        """C2 自证：§3 抄回数值字面量 ⇒ 同一判定体必须报出来。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        payload = _payload(_ROW.format(v=truth), f"`M = (W + {truth}) × N`")
        hits = _section3_literal_hits(payload, source)
        assert hits and "SIDE_MARGIN" in hits[0], (
            f"注入 §3 字面量 {truth} 后判定体没报出来：{hits} ⇒ C2 是空断言"
        )

    def test_c2_clean_payload_passes(self) -> None:
        """C2 反向：同一载荷**不注入** ⇒ 判定体读不到字面量（证明红由注入引起）。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        payload = _payload(_ROW.format(v=truth), "`M = (W + SIDE_MARGIN) × N`")
        assert _section3_literal_hits(payload, source) == [], "干净载荷被判成有字面量 ⇒ 判据误红"

    def test_c3_detects_dead_constant(self) -> None:
        """C3 自证：常量只剩定义、没有消费点 ⇒ `_consumed_names` 必须认出来。"""
        live = _consumed_names(_calc_text())
        assert "SIDE_MARGIN" in live, "真源里 SIDE_MARGIN 竟无消费点 ⇒ 判据前提变了，请同步本守卫"
        dead = "SIDE_MARGIN = 0.3\nOTHER = 1\n"
        assert "SIDE_MARGIN" not in _consumed_names(dead), (
            "死常量（只有定义、无引用）被判成「已消费」⇒ C3 是空断言"
        )

    def test_c4_detects_conflicting_value(self) -> None:
        """C4 自证：同一条规则里两个不同数值并存 ⇒ 同一判定体必须报矛盾。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        other = f"{truth}5"
        payload = _payload(_ROW.format(v=truth), f"`SIDE_MARGIN` = {other}（覆盖余量）")
        conflicts = _conflicting_claims(payload, source)
        assert conflicts, f"注入矛盾值 {other}（真值 {truth}）后判定体没报矛盾 ⇒ C4 是空断言"

    def test_c4_clean_payload_passes(self) -> None:
        """C4 反向：同一载荷只写符号名 ⇒ 判定体不得报矛盾。"""
        source = _calc_text()
        truth = _engine_value(source, "SIDE_MARGIN")
        payload = _payload(_ROW.format(v=truth), "`SIDE_MARGIN` 覆盖余量按符号取")
        assert _conflicting_claims(payload, source) == [], "干净载荷被判成矛盾 ⇒ 判据误红"

    def test_anchor_missing_is_not_silent(self) -> None:
        """锚点缺失必须**抛错**而不是返回空串（否则整组判据会静默空跑）。"""
        try:
            _section("no anchors here", SECTION0_ANCHOR, SECTION0_END)
        except AssertionError as exc:
            assert "找不到锚点" in str(exc)
        else:
            raise AssertionError("锚点缺失却静默通过 ⇒ 判据会空跑（不会红的断言 = 空断言）")
