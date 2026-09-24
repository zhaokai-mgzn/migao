# case_ids: MC-012, CH-042
"""接高「旧口径」在 main 上的 3 处**文字残余**：收口判据 + **扫描面收窄**负例（issue #5296）。

## 病根（本单要治的静默失效形态）

`resolve_fabric_plan._splice()` 的**旧口径 A**（「缺口多大都行」+「加高条按片宽另买布」）已被
**用户 2026-09-23 裁定（乙+B / issue #5213，落码 PR #5288）**统一：缺口 ≤ `MAX_JOIN_GAP_M` ⇒
接高且 `meters == T`；缺口超限 ⇒ **回落倒幅**。实现（`_splice()`）与用例库 / `docs/design/door-width-auto-selection.md`
（#5290）都同步了，但 main 上仍留着 **3 处文字**：

| 处 | 失真 |
|---|---|
| `CHANGELOG.md` 的 `[Unreleased]` 边界段 | ① 口径**已**统一；②「会改 agent 报价」这个前提**已被实测推翻**（agent 两条真实通路 800 例命中旧口径 0 次、改前后 sha256 一致）；③ 它在 `[Unreleased]` ⇒ **未发布 ⇒ 属可改面** |
| `docs/design/oversize-threshold-and-enterprise-params.md` | 把**已退役**的旧口径 A 写成**现行** |
| `docs/design/door-width-auto-selection.md` §6 | dated 登记「实现落后于本文件」—— #5290 写作时 #5213 尚未合并，如今两条都已合并 ⇒ **它自己写的删除条件已满足** |

⚠️ **为什么需要机械判据**：这三处是**纯文字**，静态门禁只管「生成物与用例源同源」，**不管文字内容对不对**
⇒ 口径改了而文字没改时**没有任何东西会变红**（与 #5290 / #5250 同族）。

## 判据与红证（每条都能单独变红；①③④ 是**自然红证** —— 本 PR 改动前实测即红）

| # | 判据 | 红证 |
|---|---|---|
| 1 | `[Unreleased]` 内不得出现旧断言「两条通路上口径不同」/「统一需另立裁定」；且原边界段须**如实记述统一已发生**（不是删掉不提） | 写回旧句 ⇒ 红（改动前实测 **1 条**命中）；把边界段整段删掉 ⇒ 也红 |
| 2 | `[Unreleased]` 里**被断言为接高上限**的数必须 == 引擎 `MAX_JOIN_GAP_M`（**读源解析**，判据不写死数字） | 写成 `0.2` ⇒ 红；`[Unreleased]` 里一个上限断言都没有（无从同源）⇒ 也红 |
| 3 | `docs/design/**` 不得再把旧口径 A 写成**现行**（退役句豁免）；**且**「工具 schema / `execute` 签名 / 加工类型 chips 都**没有**「接高」这一档」这条**可达性结论必须在**（**双向钉住**，防修过头）；**且**该结论必须**仍为真**（读源复核：长出「接高」档 ⇒ 红） | ① 写回现行口径 ⇒ 红（改动前实测 **1 条**命中）；② 删掉可达性结论 ⇒ 也红；③ 工具 schema / chips 长出「接高」档而无改判 ⇒ 红 |
| 4 | `door-width-auto-selection.md` 不得再含 dated「实现落后于本文件」登记；**且删除前提**（`_splice()` 的缺口闸门在位）必须为真；相邻的#5040 可达性条目**不许连带删** | 写回登记 ⇒ 红（改动前实测 **3 行**）；回退闸门却仍删登记 ⇒ 也红 |
| 5 | **负例**：扫描面只覆盖 `[Unreleased]` + `docs/design/**` —— `acceptance/**`（历史读数）与**已发布区段**里的旧口径字句**不得**被判红 | 把扫描面放宽到含 `acceptance/**` / 含已发布区段 ⇒ **必红**（证明扫描面确实收窄了） |

⚠️ **有意不写成「全仓不得出现『口径 A』」**：`acceptance/**` 的历史读数与改前的**留档提及**
（含 `CHANGELOG.md` 里 #5213 条目如实写的「改前…两份口径」）**应当**保留 —— 那是当时的诚实记录。
判据 3 沿用 #5290 守卫的**句级退役豁免**（同句带 `退役/取代/留档/不并存/已废止` 之一即豁免）。

⚠️ **边界（照实登记，别把「登记了」读成「治住了」）**：`CHANGELOG.md` 目前**没有**已发布区段
（文件头自陈 POC 期「尚未发布首个公开版本」，实测 `^## ` 只有 `## [Unreleased]` 一条）
⇒ 「排除已发布区段」这半条今天在真实文件上是**空操作**（`released_text()` 为空串），
它的判别力由**构造的**已发布区段钉住（判据 5）；真实文本上的收窄锚点 = `acceptance/**`
（判据 1 的「两条通路上口径不同」在那里**逐字存在**）。
⇒ 本文件**不**声称「扩到全 `CHANGELOG.md` 就会红」（今天不会：全文件都属 `[Unreleased]`），
那样写会是一条**永不触发的假判据**。

⚠️ **复用而非新写第二份**：上限真值源与「未退役旧口径」判定点直接取 #5290 的守卫
（`tests/unit_ci_workflows/test_join_height_legacy_sync.py` 的 `engine_cap` / `cap_literals` /
`unretired_legacy_hits`）—— 同一真值只允许一份实现。
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: 复用 #5290 守卫的判定点（同目录，与 `test_admin_web_devserver_identity.py` 同范式）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / ".github"))

from test_join_height_legacy_sync import (  # noqa: E402
    cap_literals,
    engine_cap,
    unretired_legacy_hits,
)

CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
DESIGN_DIR = REPO_ROOT / "docs" / "design"
OVERSIZE_DOC_PATH = DESIGN_DIR / "oversize-threshold-and-enterprise-params.md"
DOOR_WIDTH_DOC_PATH = DESIGN_DIR / "door-width-auto-selection.md"
ENGINE_PATH = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools" / "curtain_calc.py"
CHIPS_PATH = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "order-craft-fields.ts"
ACCEPTANCE_HISTORY_PATH = REPO_ROOT / "acceptance" / "2026-09-23" / "order-auto-derivation" / "report.md"

CAP_SYMBOL = "MAX_JOIN_GAP_M"

#: 判据 1：**已被推翻**的两个旧断言（逐字）。历史面（`acceptance/**` / 已发布区段）里**应当**保留。
FORBIDDEN_STALE_CLAIMS = ("两条通路上口径不同", "统一需另立裁定")

#: `[Unreleased]` / 已发布区段的标题形态（Keep a Changelog）。
UNRELEASED_HEADING_RE = re.compile(r"^##\s*\[Unreleased\]\s*$", re.M)
RELEASED_HEADING_RE = re.compile(r"^##\s*\[(?P<version>\d+\.\d+[^\]]*)\]", re.M)

#: 判据 4：dated「实现落后于本文件」登记的形态指纹。
DATED_STALENESS_PATTERNS = (
    r"实现落后于本文件",
    r"落码合并后本行即可删",
    r"口径\s*vs\s*实现落地状态",
)

#: 判据 3 后半：可达性结论必须在文档里（删掉 ⇒ 红）。
REACHABILITY_MARKERS = (
    "只在引擎 API 层可达",
    "CurtainCalcTool.parameters",
    "CurtainCalcTool.execute",
    "chips",
)
#: 「工具 schema / 签名 / chips 里**没有**『接高』这一档」的否定式（markdown 强调已剥）。
NO_JOIN_ENTRY_RE = re.compile(r"没有[^\n]{0,8}接高[^\n]{0,8}这一档")
#: 「接高」档在 schema / 签名 / chips 里的**任何**落点形态（参数名 / 英文键 / 中文档位）。
JOIN_ENTRY_TOKENS = ("cutting_mode", "splice", "join_height", "join_width", "接高")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _plain(text: str) -> str:
    """剥掉 markdown 行内强调 / 代码标记 —— 判据读的是**内容**，不该被 `**` 绊倒。"""
    return text.replace("*", "").replace("`", "")


def unreleased_text(changelog: str) -> str:
    """`[Unreleased]` 区段正文（判据 1/2 的**唯一**扫描面）。"""
    head = UNRELEASED_HEADING_RE.search(changelog)
    assert head, "CHANGELOG.md 里找不到 `## [Unreleased]` 标题 ⇒ 判据失去扫描面"
    tail = changelog[head.end():]
    released = RELEASED_HEADING_RE.search(tail)
    return tail if released is None else tail[:released.start()]


def released_text(changelog: str) -> str:
    """**已发布区段**正文（历史记录面，判据**有意不扫**；判据 5 的负例靶子）。"""
    head = UNRELEASED_HEADING_RE.search(changelog)
    tail = changelog[head.end():] if head else changelog
    released = RELEASED_HEADING_RE.search(tail)
    return "" if released is None else tail[released.start():]


def stale_claim_hits(text: str):
    """旧断言命中（判据 1 的判定点，判据 5 负例共用同一处）。"""
    return [claim for claim in FORBIDDEN_STALE_CLAIMS if claim in text]


def dated_staleness_hits(text: str):
    """dated「实现落后于本文件」登记命中行（判据 4）。"""
    return [ln.strip()[:100] for ln in text.splitlines()
            if any(re.search(p, ln) for p in DATED_STALENESS_PATTERNS)]


def unretired_legacy_in_design_dir():
    """`docs/design/**` 里**未被标注退役**的旧口径 A 命中（判据 3 的扫描面 = 整个目录）。"""
    out = {}
    for path in sorted(DESIGN_DIR.rglob("*.md")):
        hits = unretired_legacy_hits(read(path))
        if hits:
            out[str(path.relative_to(REPO_ROOT))] = hits
    return out


def reachability_conclusion_present(doc: str) -> bool:
    """文档里**可达性结论**是否还在（判据 3 后半：不许连带删）。"""
    return (all(m in doc for m in REACHABILITY_MARKERS)
            and NO_JOIN_ENTRY_RE.search(_plain(doc)) is not None)


def _nested_function_body(src: str, signature: str) -> str:
    """嵌套函数（4 空格缩进）的函数体 —— 到下一个同级 `def` 为止。"""
    start = src.index(signature)
    rest = src[start:]
    nxt = re.search(r"\n    def ", rest)
    return rest if nxt is None else rest[:nxt.start()]


def tool_parameters_block(src: str) -> str:
    """`CurtainCalcTool.parameters` 的字典字面量（工具 schema = agent 侧可达面）。"""
    start = src.index("class CurtainCalcTool(")
    return src[start:src.index("\n    async def execute", start)]


def execute_signature(src: str) -> str:
    """`CurtainCalcTool.execute` 的签名段。"""
    start = src.index("class CurtainCalcTool(")
    body = src[src.index("\n    async def execute", start):]
    nxt = re.search(r"\n    async def |\n    def ", body[10:])
    return body if nxt is None else body[:nxt.start() + 10]


def chips_array(src: str) -> str:
    """`CUTTING_MODE_OPTIONS` 的数组字面量（admin-web 加工类型 chips 的单一源）。"""
    m = re.search(r"CUTTING_MODE_OPTIONS\s*=\s*\[([^\]]*)\]", src)
    assert m, "order-craft-fields.ts 里找不到 CUTTING_MODE_OPTIONS 字面数组 ⇒ 判据失去真值源"
    return m.group(1)


def join_entry_violations(src: str, chips_src: str):
    """可达性结论**是否仍为真** —— 返回违规点（空 = 与文档一致）。"""
    bad = []
    if any(tok in tool_parameters_block(src) for tok in JOIN_ENTRY_TOKENS):
        bad.append("工具 schema（CurtainCalcTool.parameters）里长出了「接高」档")
    signature = execute_signature(src)
    if "cutting_mode" in signature or "splice" in signature:
        bad.append("CurtainCalcTool.execute 签名里长出了 cutting_mode")
    if "接高" in chips_array(chips_src):
        bad.append("admin-web 加工类型 chips（CUTTING_MODE_OPTIONS）里长出了「接高」档")
    return bad


def splice_gate_in_place(src: str) -> bool:
    """判据 4 的**删除前提**：缺口超限 ⇒ 回落倒幅（闸门在位）。"""
    body = _nested_function_body(src, "def _splice(")
    if "_join_gap_ok(gap)" not in body or "return _fixed_width()" not in body:
        return False
    return body.index("_join_gap_ok(gap)") < body.index("return _fixed_width()")


# ── 判据 1：`[Unreleased]` 不再出现被推翻的旧断言 ─────────────────────────────
class TestCriterion1UnreleasedDropsTheStaleClaim:
    def test_no_stale_claim_in_unreleased(self):
        assert stale_claim_hits(unreleased_text(read(CHANGELOG_PATH))) == []

    def test_former_boundary_bullet_records_the_unification(self):
        """防「删掉不提」：原边界段须如实记述统一已发生 + 引裁定（判据不是「不提就绿」）。"""
        lines = [ln for ln in unreleased_text(read(CHANGELOG_PATH)).splitlines()
                 if "人工覆盖通路" in ln]
        assert len(lines) == 1, f"`[Unreleased]` 里「人工覆盖通路」的记述行数变成了 {len(lines)}"
        assert "统一" in lines[0] or "同一份口径" in lines[0], "原边界段未如实记述口径已统一"
        assert "#5213" in lines[0], "原边界段未引裁定（issue #5213 / 乙+B）"

    def test_red_proof_writing_the_stale_claim_back(self):
        unreleased = unreleased_text(read(CHANGELOG_PATH))
        mutated = unreleased + (
            "\n- **边界（如实登记）**：「接高」在**两条通路上口径不同** —— 人工覆盖通路仍是旧口径；"
            "统一需另立裁定（会改 agent 报价，另有跟随单）。\n")
        assert stale_claim_hits(mutated) != []


# ── 判据 2：`[Unreleased]` 的接高上限与引擎常量同源 ───────────────────────────
class TestCriterion2CapSameSourceAsEngine:
    def test_unreleased_cap_literals_agree_with_the_engine(self):
        cap = engine_cap()
        hits = cap_literals(unreleased_text(read(CHANGELOG_PATH)))
        assert cap in hits, (
            f"`[Unreleased]` 里没有任何接高上限断言（真值 = {CAP_SYMBOL} {cap} 米）⇒ 判据退化成恒真")
        assert [v for v in hits if v != cap] == []

    def test_red_proof_writing_0_2_metres_as_the_cap(self):
        unreleased = unreleased_text(read(CHANGELOG_PATH))
        cap = engine_cap()
        mutated = unreleased.replace(f"{cap} 米", "0.2 米")
        assert mutated != unreleased, "真实文本里没有可替换的上限字面量 ⇒ 红证是空跑"
        assert [v for v in cap_literals(mutated) if v != cap] == [0.2]

    def test_negative_control_non_cap_numbers_are_not_collected(self):
        """负控：不是「有数字就红」—— 例示值 / 加工费不该被当成上限。"""
        cap = engine_cap()
        assert [v for v in cap_literals("推导出「接高 0.05 米」；接高加工费 1.0 元/幅。") if v != cap] == []


# ── 判据 3：oversize 文档**双向**钉住（口径不写现行 + 可达性结论不许删，且须为真）──
class TestCriterion3OversizeDocBothDirections:
    def test_design_dir_does_not_present_legacy_as_current(self):
        assert unretired_legacy_in_design_dir() == {}

    def test_reachability_conclusion_is_still_in_the_doc(self):
        assert reachability_conclusion_present(read(OVERSIZE_DOC_PATH)), (
            "可达性结论（工具 schema / `execute` 签名 / chips 都没有「接高」这一档）被删掉了 —— "
            "它是**与口径无关**的独立结论，不许连带删")

    def test_reachability_conclusion_is_still_true(self):
        violations = join_entry_violations(read(ENGINE_PATH), read(CHIPS_PATH))
        assert violations == [], (
            "可达性结论已过时（引擎 / chips 长出了「接高」档）⇒ 文档须同步改判：" + str(violations))

    def test_red_proof_writing_legacy_back_as_current(self):
        mutated = read(OVERSIZE_DOC_PATH) + "\n- 现行口径 A：加高条按片宽另买、缺口多大都行。\n"
        assert unretired_legacy_hits(mutated) != []

    def test_red_proof_deleting_the_reachability_conclusion(self):
        doc = read(OVERSIZE_DOC_PATH)
        assert reachability_conclusion_present(doc)
        assert not reachability_conclusion_present(doc.replace("只在引擎 API 层可达", ""))

    def test_red_proof_tool_schema_growing_a_join_entry(self):
        src = read(ENGINE_PATH)
        assert join_entry_violations(src, read(CHIPS_PATH)) == []
        block = tool_parameters_block(src)
        mutated = src.replace(block, block.replace('"window_width"', '"cutting_mode"', 1))
        assert join_entry_violations(mutated, read(CHIPS_PATH)) != []

    def test_red_proof_chips_growing_a_join_entry(self):
        chips = read(CHIPS_PATH)
        array = chips_array(chips)
        assert "接高" not in array
        assert join_entry_violations(read(ENGINE_PATH), chips.replace(array, array + ", '接高'")) != []


# ── 判据 4：door-width §6 的 dated 登记删除 + 删除前提仍在位 ────────────────────
class TestCriterion4DoorWidthRegistrationDeleted:
    def test_no_dated_staleness_registration(self):
        assert dated_staleness_hits(read(DOOR_WIDTH_DOC_PATH)) == []

    def test_adjacent_reachability_item_survives(self):
        """防修过头：删的是**口径登记**，相邻的「接高当前『无活入口』」（#5040，可达性）不许连带删。"""
        doc = read(DOOR_WIDTH_DOC_PATH)
        assert "接高当前「无活入口」" in doc
        assert "#5040" in doc

    def test_deletion_precondition_holds_in_the_engine(self):
        assert splice_gate_in_place(read(ENGINE_PATH)), (
            "`_splice()` 的缺口闸门不在位 ⇒ 实现落后于文档，那条 dated 登记**不许删**")

    def test_red_proof_writing_the_registration_back(self):
        mutated = read(DOOR_WIDTH_DOC_PATH) + (
            "\n- 🔴 **本文件的口径 vs 实现落地状态（issue #5290 登记，dated）**：落码 PR 在本文件"
            "写作时尚未合并 ⇒ 若有人读到 `resolve_fabric_plan._splice()` 仍是旧口径，"
            "那是**实现落后于本文件**。落码合并后本行即可删。\n")
        assert dated_staleness_hits(mutated) != []

    def test_red_proof_reverting_the_gate(self):
        src = read(ENGINE_PATH)
        assert splice_gate_in_place(src)
        body = _nested_function_body(src, "def _splice(")
        assert not splice_gate_in_place(src.replace(body, body.replace("return _fixed_width()", "pass")))


# ── 判据 5（负例）：扫描面确实**收窄**了 ─────────────────────────────────────
class TestCriterion5ScanSurfaceIsNarrowed:
    def test_history_really_carries_the_stale_claim(self):
        """判别力下界（反恒真）：负例锚点必须在**真实历史文本**里逐字存在。"""
        assert "两条通路上口径不同" in read(ACCEPTANCE_HISTORY_PATH)

    def test_red_proof_widening_the_surface_to_history(self):
        """负例：把扫描面放宽到含 `acceptance/**`（历史读数）+ 已发布区段 ⇒ 必红。"""
        changelog = read(CHANGELOG_PATH)
        live = unreleased_text(changelog)
        widened = live + released_text(changelog) + read(ACCEPTANCE_HISTORY_PATH)
        assert stale_claim_hits(live) == []
        assert stale_claim_hits(widened) != []

    def test_released_sections_are_excluded_from_the_judged_surface(self):
        """已发布区段是历史记录面 ⇒ 判据有意不扫（用**构造的**区段钉住判别力）。"""
        fixture = (read(CHANGELOG_PATH) + "\n## [0.1.0] - 2026-10-01\n\n"
                   "- 边界：接高在两条通路上口径不同；统一需另立裁定。\n")
        assert stale_claim_hits(unreleased_text(fixture)) == []
        assert stale_claim_hits(released_text(fixture)) != []

    def test_unreleased_and_released_split_the_file_losslessly(self):
        """结构性不变量：两段拼接 == 标题之后的全文（既不漏扫、也不重复扫）。"""
        changelog = read(CHANGELOG_PATH)
        head = UNRELEASED_HEADING_RE.search(changelog)
        assert unreleased_text(changelog) + released_text(changelog) == changelog[head.end():]