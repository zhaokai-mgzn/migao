# case_ids: CH-042
"""接高口径的**文字面**守卫：用例库 + 设计文档必须与实现 `MAX_JOIN_GAP_M` **同源**（issue #5290）。

## 背景（为什么需要这一层）

用户 2026-09-23 裁定（issue #5213：**乙 = 统一到新口径** + **B = 回落倒幅**）取代了
`resolve_fabric_plan._splice()` 的**旧口径 A**（「缺口多大都行」+「加高条按片宽另买布」，
`M = T + 段数 × Wp` / 旧代码 `meters = total + strips * piece_width`）⇒ 生效口径三条：

| 情形（显式 `cutting_mode` + 候选门幅集） | 新行为 |
|---|---|
| 定高买宽**可行** | `_fixed_height()`（不变） |
| 不可行，且缺口 ≤ `MAX_JOIN_GAP_M` | **接高，且不参与算料**（`meters == T`、`splice_strips == 0`） |
| 不可行，且缺口 > `MAX_JOIN_GAP_M` | **回落倒幅**（`_fixed_width()`）（B 的固有代价：显式「接高」被改判，已知并接受） |

而**文字面**（CH-042 的 `data_checks` 与 `docs/design/door-width-auto-selection.md`）当时仍是旧口径。
静态门禁只管「生成物与用例源同源」——**不管文字内容对不对** ⇒ 口径改了而文字没改时
**没有任何东西会变红**（本单的成因；与 #5250「用例文字落后于实现」同族）。
本文件把「文字面与实现同源」落成机械判据。

## 判据与红证（红证 = 对**真文件文本**做单点变异后重跑同一纯函数）

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | CH-042 的 `data_checks` 里不再出现旧口径 A 的算式/措辞（且必须给出新口径） | 写回 `ceil(k / floor(g_eff/d_eff))` ⇒ 红 |
| 2 | 生成物与用例源**同源**（重渲染零 diff；且文字改动会传导到生成物） | 只改用例不重渲染 ⇒ 红 |
| 3 | 设计文档不得把旧口径 A 写成**现行**（要么改，要么标「已被 2026-09-23 裁定取代」） | 写回「现行口径 A」/ 抹掉退役标记 ⇒ 红 |
| 4 | 文档 / 用例里出现的接高上限必须与实现常量一致（且引用**符号**） | 写 `接高上限 0.2 米` ⇒ 红 |

⚠️ **豁免口径（有意）**：「**已被取代**的留档提及」不算违规 —— 判据 1/3 按**句**判定，
同句带 `退役 / 取代 / 留档 / 不并存 / 已废止` 之一即豁免（留档是资产，不是违规）。
"""
import copy
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts, to_eval_py, to_md  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
DOC_PATH = REPO_ROOT / "docs" / "design" / "door-width-auto-selection.md"
ENGINE_PATH = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools" / "curtain_calc.py"
EVAL_CASES_PATH = REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py"
CASEBOOK_PATH = REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md"

CASE_ID = "CH-042"
CAP_SYMBOL = "MAX_JOIN_GAP_M"

#: 「已退役」标记词：同句出现任一 ⇒ 该句的旧口径提及属**留档**，豁免。
RETIRED_MARKERS = ("退役", "取代", "留档", "不并存", "已废止")

#: **旧口径 A** 的形态指纹（算式与专属量；不是「口径」二字本身）。
LEGACY_A_PATTERNS = (
    r"floor\(\s*g_(?:eff|max)\s*/\s*d_eff\s*\)",   # 段数算式里的并排条数
    r"ceil\(\s*k\s*/\s*floor\(",                    # 段数 = ceil(k / floor(...))
    r"段数\s*[×x*]\s*(?:Wp|片宽|\d)",                # M = T + 段数 × Wp
    r"d_eff",                                       # 旧口径的「缺口 + 花距」加宽量（现行口径无此量）
    r"加高条按片宽另买",
    r"口径\s*A(?![0-9A-Za-z])",
)

#: 「**断言接高上限是多少**」的形态（只认断言式；引述裁定原文不算断言）。
CAP_ASSERT_PATTERNS = (
    r"上限\s*(?:=|为|是|＝)?\s*(\d+(?:\.\d+)?)\s*米",
    r"接高[^\n。；]{0,12}上限[^\n。；]{0,12}?(\d+(?:\.\d+)?)\s*米",
)


def _sentences(text: str):
    """按句切分（含换行 —— markdown 的一行/一个表格行 = 一个判定单位）。"""
    return re.split(r"(?<=[。；;！？!?\n])", text)


def unretired_legacy_hits(text: str):
    """返回**未被标注退役**的旧口径 A 命中句（留档句豁免）。判据 1 / 3 共用同一判定点。"""
    hits = []
    for sentence in _sentences(text):
        found = [p for p in LEGACY_A_PATTERNS if re.search(p, sentence)]
        if found and not any(marker in sentence for marker in RETIRED_MARKERS):
            hits.append(sentence.strip()[:100])
    return hits


def cap_literals(text: str):
    """返回文本里**被断言为接高上限**的数值（米）—— 去重升序（集合语义）。"""
    out = []
    for pattern in CAP_ASSERT_PATTERNS:
        out += [float(v) for v in re.findall(pattern, text)]
    return sorted(set(out))


def legacy_rendered_data_check_lines(text: str):
    """casebook（`mibao-verification-cases.md`）里**渲染出来的** `数据:` 行中带旧口径的（判据 2）。"""
    return [ln.strip()[:100] for ln in text.splitlines()
            if ln.strip().startswith("数据:") and unretired_legacy_hits(ln)]


def engine_cap() -> float:
    """真值源 = 引擎模块的 `MAX_JOIN_GAP_M` 字面赋值（**数字只在这里**，不写死在判据里）。"""
    src = ENGINE_PATH.read_text(encoding="utf-8")
    m = re.search(rf"^{CAP_SYMBOL}\s*(?::\s*float\s*)?=\s*(\d+(?:\.\d+)?)", src, re.M)
    assert m, f"{ENGINE_PATH.name} 里找不到 {CAP_SYMBOL} 的字面赋值 ⇒ 判据失去真值源"
    return float(m.group(1))


def join_gap_ok_body(src: str) -> str:
    """`_join_gap_ok()` 的函数体（判据 4 的「唯一判定点」靶子）。"""
    start = src.index("def _join_gap_ok(")
    rest = src[start:]
    nxt = rest.find("\ndef ", 10)
    return rest if nxt == -1 else rest[:nxt]


def cap_decision_point_uses_symbol(src: str) -> bool:
    return CAP_SYMBOL in join_gap_ok_body(src)


def ch042_checks():
    """CH-042 的 `data_checks`（单一源 = `.github/cases/chat.yml`，经渲染器同一 loader 读）。"""
    for case in load_case_dicts(str(CASES_DIR)):
        if case.get("id") == CASE_ID:
            return [str(c) for c in (case.get("data_checks") or [])]
    raise AssertionError(f"{CASE_ID} 不在用例库里 ⇒ 判据指向了不存在的用例")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


# ── 判据 1：CH-042 的 data_checks 不再出现旧口径公式 ─────────────────────────
class TestCriterion1CaseChecksHaveNoLegacyFormula:
    def test_no_unretired_legacy_in_case_checks(self):
        assert unretired_legacy_hits("\n".join(ch042_checks())) == []

    def test_case_checks_state_the_new_rule(self):
        text = "\n".join(ch042_checks())
        for marker in (CAP_SYMBOL, "meters == T", "不参与算料", "回落倒幅"):
            assert marker in text, f"CH-042 的 data_checks 缺新口径要素：{marker}"

    def test_red_proof_writing_the_old_formula_back(self):
        """红证：把 issue #5290 原文那条旧口径算式写回 ⇒ 判据 1 必红。"""
        old = ("人工覆盖选接高 ⇒ 按口径 A 算料："
               "M = T + ceil(k / floor(g_eff/d_eff)) × Wp")
        mutated = "\n".join(ch042_checks() + [old])
        assert unretired_legacy_hits(mutated) != []

    def test_retired_mention_is_exempt(self):
        """负控：**标注了退役**的留档提及不算违规 ⇒ 判据不是「提了就红」。"""
        assert unretired_legacy_hits("旧口径 A（已退役）：M = T + 段数 × Wp。") == []


# ── 判据 2：生成物与用例源同源（重渲染零 diff + 改动会传导）─────────────────
class TestCriterion2ArtifactsSameSource:
    def test_rerender_matches_committed_artifacts(self):
        cases = load_case_dicts(str(CASES_DIR))
        assert to_eval_py(cases) == EVAL_CASES_PATH.read_text(encoding="utf-8"), (
            "eval_cases.py 与 .github/cases/ 不同源 ⇒ 跑 .github/render_cases.py 并提交生成物")
        assert to_md(cases) == CASEBOOK_PATH.read_text(encoding="utf-8"), (
            "mibao-verification-cases.md 与 .github/cases/ 不同源 ⇒ 同上")

    def test_committed_artifacts_carry_the_new_wording(self):
        """生成物里必须**已是**新口径文字（否则「零 diff」可能只是两边都旧）。

        ⚠️ **有意不做全文件否定**：CH-042 的 `merge_log` 会**如实留档**旧口径算式
        （「改了什么」必须写清），故只否掉**已退役的 `data_checks` 原句**与**渲染出的 `数据:` 行**。
        """
        eval_cases = EVAL_CASES_PATH.read_text(encoding="utf-8")
        casebook = CASEBOOK_PATH.read_text(encoding="utf-8")
        assert "不参与算料" in eval_cases
        assert "不参与算料" in casebook
        assert "按口径 A 算料" not in eval_cases
        assert "按口径 A 算料" not in casebook
        assert legacy_rendered_data_check_lines(casebook) == []

    def test_red_proof_editing_cases_without_rerendering(self):
        """红证：只改用例文字、不重渲染 ⇒ 生成物与重渲染结果必不一致。"""
        cases = load_case_dicts(str(CASES_DIR))
        assert to_eval_py(cases) == EVAL_CASES_PATH.read_text(encoding="utf-8")
        mutated = copy.deepcopy(cases)
        for case in mutated:
            if case.get("id") == CASE_ID:
                case["data_checks"] = [d.replace("不参与算料", "参与算料")
                                       for d in case["data_checks"]]
        assert to_eval_py(mutated) != to_eval_py(cases), "用例文字改动未传导到生成物 ⇒ 判据失效"
        assert to_eval_py(mutated) != EVAL_CASES_PATH.read_text(encoding="utf-8")


# ── 判据 3：文档不得把旧口径 A 写成**现行** ─────────────────────────────────
class TestCriterion3DocDoesNotPresentLegacyAsCurrent:
    def test_no_unretired_legacy_in_doc(self):
        assert unretired_legacy_hits(read_doc()) == []

    def test_doc_states_the_new_rule_and_the_supersede_relation(self):
        doc = read_doc()
        assert CAP_SYMBOL in doc, "文档未引用实现常量符号 ⇒ 无法同源"
        assert "不参与算料" in doc
        explicit = [s for s in _sentences(doc)
                    if re.search(r"口径\s*A", s) and "已被" in s and "取代" in s]
        assert explicit != [], (
            "文档须**显式**（同一句内）写明「旧口径 A 已被 2026-09-23 裁定取代」——"
            "否则后人会把两种口径读成并存")

    def test_red_proof_writing_legacy_back_as_current(self):
        """红证①：把旧口径写回「现行」⇒ 判据 3 必红。"""
        mutated = read_doc() + (
            "\n\n### 2.3 现行接高口径（回退演示）\n\n"
            "现行口径 A：`M = T + 段数 × Wp`，缺口多大都行。\n")
        assert unretired_legacy_hits(mutated) != []

    def test_red_proof_dropping_the_supersede_markers(self):
        """红证②：抹掉退役标记（旧口径照旧留着、但不再标「已被取代」）⇒ 判据 3 必红。"""
        mutated = read_doc()
        for marker in RETIRED_MARKERS:
            mutated = mutated.replace(marker, "口径")
        assert unretired_legacy_hits(mutated) != []


# ── 判据 4：接高上限与实现同源 ──────────────────────────────────────────────
class TestCriterion4CapSameSourceAsImplementation:
    def test_doc_and_cases_reference_the_symbol(self):
        assert CAP_SYMBOL in read_doc(), "文档须引用符号（而不是各写一份数字）"
        assert CAP_SYMBOL in "\n".join(ch042_checks()), "用例须引用符号（同上）"

    def test_no_cap_literal_disagrees_with_the_constant(self):
        cap = engine_cap()
        targets = (
            ("docs/design/door-width-auto-selection.md", read_doc()),
            (".github/cases/chat.yml（CH-042）", "\n".join(ch042_checks())),
        )
        for name, text in targets:
            bad = [v for v in cap_literals(text) if v != cap]
            assert bad == [], f"{name} 里的接高上限 {bad} 与 {CAP_SYMBOL}={cap} 不一致"

    def test_engine_has_a_single_decision_point(self):
        src = ENGINE_PATH.read_text(encoding="utf-8")
        assert cap_decision_point_uses_symbol(src), (
            f"_join_gap_ok() 里的上限须复用 {CAP_SYMBOL}（不得各写一份数字）")

    def test_red_proof_writing_0_2_metres_as_the_cap(self):
        """红证：文档写 `接高上限 0.2 米` ⇒ 判据 4 必红（0.2 ≠ 实现常量）。"""
        mutated = read_doc() + "\n\n接高上限 0.2 米。\n"
        cap = engine_cap()
        assert [v for v in cap_literals(mutated) if v != cap] == [0.2]

    def test_red_proof_dropping_the_symbol(self):
        """红证：把符号换成裸数字（不再同源）⇒ 判据 4 必红。"""
        mutated = read_doc().replace(CAP_SYMBOL, "上限")
        assert CAP_SYMBOL not in mutated

    def test_red_proof_decision_point_without_the_symbol(self):
        """红证：把判定点改成字面量 ⇒ 同源判据必红（对真源码做单点变异）。"""
        src = ENGINE_PATH.read_text(encoding="utf-8")
        body = join_gap_ok_body(src)
        assert cap_decision_point_uses_symbol(src)
        mutated_src = src.replace(body, body.replace(CAP_SYMBOL, "0.1"))
        assert not cap_decision_point_uses_symbol(mutated_src)

    def test_cap_literal_check_accepts_a_matching_literal(self):
        """负控：写**与实现一致**的数字不算违规（判据不是「有数字就红」）。"""
        cap = engine_cap()
        assert [v for v in cap_literals(f"接高上限 {cap} 米。") if v != cap] == []