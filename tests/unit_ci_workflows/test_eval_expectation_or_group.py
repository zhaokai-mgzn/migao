# case_ids: ST-005, PR-006
"""`expectations` 的 **OR 面**：一类「恒判 50%」的用例资产缺陷 + 只许缩短的分支登记表。

## 病灶（同一形态在仓库里复发过两次）

runner **逐条**计分（`local_runner.py::run_case` 的
`score = passed_expectations / total_exp`），每条 expectation **独立必需**。而
`check_expectation` 原生支持 `A or B`（拆法见该函数：`parts = split(" or ")`）——
**OR 只写在"一条 entry 的 tool 串"里才生效**。于是把「同一次运行只可能走一条的等价路径」
写成**两条并列 entry**，用例**恒判 50%**：跑哪条路径都只可能命中其中一条。

| 实例 | 形态 | 读数 |
|---|---|---|
| PR-006（#3781） | `inventory_manage(...)` 与 `product_search(...)` 两条 entry | 该用例注释已写死「**不能**写成两条独立声明」 |
| ST-005（#7048 P7） | `notification_manage(action=mark_read)` + `direct_reply or interact` 两条 entry | P6 复跑：`score=50%`，红在 `notification_manage(action=mark_read) → arg 'action' expected mark_read got unread_count`（「先确认再改」路径本轮真值只有 list/unread_count + confirm 卡） |

本文件把这一类**钉成机器判据**，并**不放宽任何面**：`forbidden_text` / `must_succeed` /
`db_verify` 照旧各自独立必需（ST-005 的两格逐条钉死见 `TestST005Wiring`）。

## ST-005 的实例判据（双向两问都答）

`migao-acceptance`「写断言时的完成判据」要求两问都答得上：

1. **把被测行为改坏，它会红吗** —— 「一次工具都没调、纯文本」须判红；
2. **按真实链路喂一遍，它会绿吗** —— 「真去改（`mark_read` 成功）」与「给出写确认卡」两条合格路径都须绿。

## 为什么用单测（零 LLM / 零网络）

`check_expectation` / `check_must_succeed` / `check_forbidden_text` 都是**纯函数**；
真值源 = `.github/cases/*.yml` 的**声明**（`render_cases.load_case_dicts`，与生成物同源）。

⚠️ 本目录在 CI 只 `pip install pytest pytest-xdist pyyaml`，而 `local_runner` 有模块级
`import httpx` ⇒ 用下方最小替身（与 `test_eval_runner_conditional_effect.py` 同形）。
"""
import importlib.util
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_taxonomy():
    """导入 `.github/assertion_taxonomy.py`（纯模块，importable 且零重依赖）。

    用它而**不是** `local_runner._WRITE_TOOL_NAMES`：后者是**工具级**历史集合
    （含 `customer_manage` 这类**已只读化**的工具，且**不含** `notification_manage`
    —— 后者的 `mark_read` 属**action 级**写）。真值源 = `is_write_expectation(tool, args)`。
    """
    spec = importlib.util.spec_from_file_location(
        "assertion_taxonomy", REPO_ROOT / ".github" / "assertion_taxonomy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


taxonomy = _load_taxonomy()


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()

# 文本可满足的分支（runner 语义：`direct_reply` = 「本轮无 tool_calls 且有 final_text」）。
# 与**具名写规则**同组时，纯文本就能顶替「真去改」= 假绿通道。
_TEXT_SATISFIABLE_BRANCHES = frozenset({"direct_reply"})

# ── 只许缩短的分支登记表（`migao-dev-flow` §23：未登记即红 / 台账只许缩短 / 条数现取）──────
# 语义 = 「**裸工具名分支**」（该分支后面**没有** `(...)`）的允许集。两条判据：
#   ① 语料里出现**不在表内**的裸分支名 ⇒ 红（新形态必须显式登记后才可能进用例库）；
#   ② 表内条目**实际不再被任何用例使用** ⇒ 红（销账未删 ⇒ 表会腐烂成噪音）。
# ⚠️ 登记的是**分支写法**（这些名字在语料里以裸名出现过），**不是**工具能力背书
#    （`customer_manage` 已整条只读化，见 `assertion_taxonomy.WRITE_TOOL_ACTIONS` 的注释）。
BARE_BRANCH_LEDGER = frozenset({
    "customer_manage", "direct_reply", "interact", "nav_guide",
    "order_query", "product_detail", "product_search", "validate_input",
})

# 现取读数（语料规模）：防「把语料清空 ⇒ 循环体不执行 ⇒ 恒真（vacuous）」（§19.1）。
MIN_CASES = 600
MIN_OR_EXPECTATIONS = 15

_BRANCH_TOOL_RE = re.compile(r"^([a-z][a-z0-9_]*)")


def _cases() -> list[dict]:
    """读 `.github/cases/*.yml` 的声明（与生成物同源，走 `render_cases` 的严格判定）。"""
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    from render_cases import load_case_dicts
    return load_case_dicts(str(REPO_ROOT / ".github" / "cases"))


def _render():
    """`render_cases` 模块（`exp_to_str` 是生成物用的同一份归一）。"""
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    import render_cases
    return render_cases


def _split_branches(exp: object) -> list[str]:
    """一条 expectation 的 OR 分支原文（**纯文本**，不 import runner）。

    与 `check_expectation` 的拆法同源（落 ` or ` 拆，大小写不敏感）；支持 dict
    （`{"tool": "A or B"}`）与归一字符串两种形态。
    """
    raw = str(exp.get("tool") or "") if isinstance(exp, dict) else str(exp or "")
    return [p.strip() for p in re.split(r"\s+or\s+", raw, flags=re.IGNORECASE) if p.strip()]


def _branch_tool(branch: str) -> str:
    """分支的工具名（`tool(args=…)` / `tool: …` / 裸工具名 均取首词）。"""
    m = _BRANCH_TOOL_RE.match(branch.strip())
    return m.group(1) if m else ""


def _has_args(branch: str) -> bool:
    """该分支是否**带 args**（`tool(...)` 形态；`direct_reply` 这类文本分支天然无 args）。"""
    return "(" in branch and ")" in branch


def _has_or(exp: object) -> bool:
    """该 expectation 是否**用了 OR 面**（只有用了 OR 的 entry 才进本文件的判据）。"""
    raw = str(exp.get("tool") or "") if isinstance(exp, dict) else str(exp or "")
    return " or " in raw.lower()


def _bare_branches(cases: list[dict]) -> set[str]:
    """真语料里所有**裸分支**的工具名（**只扫 OR entry** —— 无 ` or ` 的期望是工具级声明，
    带不带 args 由其它判据管，不属本文件射程）。"""
    out: set[str] = set()
    for c in cases:
        for exp in (c.get("expectations") or []):
            if not _has_or(exp):
                continue
            for b in _split_branches(exp):
                if not _has_args(b):
                    out.add(_branch_tool(b))
    return out


def _branch_write_expectation(branch: str) -> bool:
    """该 OR 分支是否为**具名写规则**（真值源 = `assertion_taxonomy.is_write_expectation`）。

    ⚠️ 不能按 `local_runner._WRITE_TOOL_NAMES` 判：那是**工具级**历史集合 —— 既含
    `customer_manage`（**已只读化**，会把只读分支误判成写），又**不含** `notification_manage`
    （它的 `mark_read` 是 **action 级**写）。故取 tool+args 的权威判定。
    """
    m = re.match(r"^([a-z][a-z0-9_]*)\s*(?:\((.*)\))?$", branch.strip())
    if not m:
        return False
    name, inner = m.group(1), m.group(2) or ""
    args: dict = {}
    for kv in inner.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            args[k.strip()] = v.strip()
    return bool(taxonomy.is_write_expectation(name, args))


def _has_empty_branch(raw: str) -> bool:
    """是否含**空分支**：`"A or "` / `" or B"` / `"A or  or B"`。

    按落 ` or ` 拆（**不丢空段**）—— `"A or "` 拆出尾段 `" "`（strip 后空）⇒ 判出。
    带正则 `\\s+` 的拆法会把脏写吃成「少一支」，正是要防的静默降级。
    """
    return any(not p.strip() for p in re.split(r" or ", raw, flags=re.IGNORECASE))


def or_branch_issues(cases: list[dict]) -> list[str]:
    """期望 OR 分支的**机械判据**（纯函数，吃 cases 声明、吐违规清单）。

    射程（**有意窄于**「写期望」全集，如实登记 `migao-dev-flow` §19.1）：只裁
    「**args 里真写了写动作**」的具名写规则 —— 那种规则被写进 OR 组时，组里**不得**
    再有文本可满足的分支。

    判据（每条都配了注入式自证，见 `TestObserverGuard`）：
      1. **无空分支**：`"A or "` / `" or B"`（含首尾空白）会静默少判一支 ⇒ 红；
      2. **具名写规则不得与文本可满足分支同组**：`A(action=mark_read) or direct_reply` 里
         后者由「纯文本」满足 ⇒ 具名写动作可被「一次工具都没调」顶替（假绿通道）⇒ 红；
      3. **裸分支必须已登记**（`BARE_BRANCH_LEDGER`）。

    ⚠️ **为什么不裁「裸写工具名」**（实测会误伤）：`customer_manage` 这类工具**已只读化**
    （写 action 已删除，见 `cross.yml` 的说明与 CH-009 的注释），名字却仍在
    `local_runner._WRITE_TOOL_NAMES` 的历史集合里 ⇒ 按名字判会把 CH-009 的**只读**分支
    误判成写分支。故本判据只认「**args 里真写了写动作**」这一形态。
    """
    issues: list[str] = []
    for c in cases:
        cid = str(c.get("id") or "?")
        for exp in (c.get("expectations") or []):
            raw = str(exp.get("tool") or "") if isinstance(exp, dict) else str(exp or "")
            if " or " not in raw.lower():
                continue
            if _has_empty_branch(raw):
                issues.append(f"{cid}: 期望含**空分支**（静默少判一支）: {raw!r}")
            named = _split_branches(exp)
            if any(_branch_write_expectation(b) for b in named):
                for b in named:
                    if _branch_tool(b) in _TEXT_SATISFIABLE_BRANCHES:
                        issues.append(
                            f"{cid}: OR 组含**具名写规则**，却又并列文本可满足分支 "
                            f"`{_branch_tool(b)}` ⇒ 纯文本可顶替写落地形态（假绿通道）: {raw!r}")
    unregistered = sorted(_bare_branches(cases) - BARE_BRANCH_LEDGER)
    if unregistered:
        issues.append(
            f"出现**未登记**的裸分支 {unregistered} —— 新形态必须先登记才可使用"
            f"（台账只许缩短；判据见 {Path(__file__).name}）")
    return issues


def stale_ledger_issues(cases: list[dict]) -> list[str]:
    """台账**销账未删**（表内条目已无人使用）—— 只在**真语料**上判（合成夹具不算）。"""
    unused = sorted(BARE_BRANCH_LEDGER - _bare_branches(cases))
    if unused:
        return [f"台账条目 {unused} 已**销账但仍留在表内**（表会腐烂成噪音）⇒ 请从 "
                f"BARE_BRANCH_LEDGER 删除"]
    return []


def _round(rnd, calls=(), results=(), text="", cards=()):
    """构造一轮 `results` 条目（与 `test_eval_runner_conditional_effect.py` 同形）。"""
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [{"tool": t, "result": {"success": ok}} for t, ok in results],
        "final_text": text,
        "interactive": list(cards),
        "__all_tool_names": sorted({t for t, _ in calls}),
    }


def _score(expectations: list[str], rounds: list) -> float:
    """复刻 `run_case` 的计分（逐条 expectation，任一轮命中即该条过）。"""
    passed = 0
    for exp in expectations:
        if any(lr.check_expectation(r, exp)[0] for r in rounds):
            passed += 1
    return passed / len(expectations) if expectations else 1.0


def _st005_expectations() -> list[str]:
    """ST-005 **声明**的 expectations（真值源 = 用例库，不是本文件里抄的常量）。"""
    exp_to_str = _render().exp_to_str
    for c in _cases():
        if c.get("id") == "ST-005":
            return [exp_to_str(e) for e in (c.get("expectations") or [])]
    raise AssertionError("用例库解析不到 ST-005 —— 判据坐标失效")


# ══════════════════════════════════════════════════════════════════════════════
# 一、类级元守卫：OR 分支形态（注入式自证 + 真语料）
# ══════════════════════════════════════════════════════════════════════════════

class TestObserverGuard:
    """观察者守卫：坏形态**在内存里**必须判红；合规形态**不得**红。"""

    def test_live_corpus_is_clean(self):
        """真语料（全部用例）零违规 —— 本包之后不得再有同类形态进来（未登记即红）。"""
        cases = _cases()
        assert len(cases) >= MIN_CASES, (
            f"语料规模异常（{len(cases)} < {MIN_CASES}）—— 判据可能落在空集上（恒真）")
        ors = [e for c in cases for e in (c.get("expectations") or [])
               if " or " in str(e.get("tool") if isinstance(e, dict) else e).lower()]
        assert len(ors) >= MIN_OR_EXPECTATIONS, (
            f"含 OR 的期望仅 {len(ors)} 条 < {MIN_OR_EXPECTATIONS} —— 语料被改动或判据退化")
        issues = or_branch_issues(cases) + stale_ledger_issues(cases)
        assert issues == [], "用例库出现期望 OR 面的坏形态：\n  - " + "\n  - ".join(issues)

    def test_empty_branch_is_red(self):
        """① 空分支（脏写把参数段整段吃掉）⇒ 判红 + 具名报出用例。"""
        bad = [{"id": "ZZ-001", "expectations": [{"tool": "notification_manage or "}]}]
        issues = or_branch_issues(bad)
        assert any("空分支" in i and "ZZ-001" in i for i in issues), issues

    def test_named_write_rule_with_text_satisfiable_peer_is_red(self):
        """② 具名写规则 + `direct_reply` 同组 ⇒ 判红（本包收紧掉的那条假绿通道）。"""
        bad = [{"id": "ZZ-002",
                "expectations": [{"tool": "notification_manage(action=mark_read) or direct_reply"}]}]
        issues = or_branch_issues(bad)
        assert any("具名写规则" in i and "direct_reply" in i and "ZZ-002" in i for i in issues), issues

    def test_unregistered_bare_branch_is_red(self):
        """③ 未登记的裸分支 ⇒ 判红（新形态必须先登记）。"""
        bad = [{"id": "ZZ-003", "expectations": [{"tool": "ntf_read or interact"}]}]
        issues = or_branch_issues(bad)
        assert any("未登记" in i and "ntf_read" in i for i in issues), issues

    def test_stale_ledger_entry_is_red(self):
        """④ 销账未删（表内条目已无人使用）⇒ 判红（台账只许缩短，不许留死条目）。"""
        saved = globals()["BARE_BRANCH_LEDGER"]
        try:
            globals()["BARE_BRANCH_LEDGER"] = saved | {"legacy_read_tool"}
            issues = stale_ledger_issues(_cases())
            assert any("销账但仍留在表内" in i and "legacy_read_tool" in i for i in issues), issues
        finally:
            globals()["BARE_BRANCH_LEDGER"] = saved

    def test_clean_or_groups_are_not_red(self):
        """反向对照：**合规的** OR 组不得红（防「加断言 = 恒红」）。

        两格都是**仓库里真实存在**的形态：各分支带自己的 args（PR-006）、既有裸分支与
        **只读**工具同组（CH-009 的 `customer_manage` 已只读化）。
        """
        assert or_branch_issues([{
            "id": "ZZ-004",
            "expectations": [{"tool": "inventory_manage(action=low_stock_alert) or "
                                      "product_search(stock_status=low_stock)"}],
        }]) == []
        assert or_branch_issues([{
            "id": "ZZ-005",
            "expectations": [{"tool": "direct_reply or interact or customer_manage"}],
        }]) == []
        assert or_branch_issues([{
            "id": "ZZ-006",
            "expectations": [{"tool": "direct_reply or validate_input"}],
        }]) == []


# ══════════════════════════════════════════════════════════════════════════════
# 二、ST-005 实例判据：两条合格路径绿 / 纯文本红（双向两问）
# ══════════════════════════════════════════════════════════════════════════════

class TestST005DeclaredExpectation:
    """用**声明的** expectation 喂三条真实形态轨迹（零 LLM、确定性）。"""

    @staticmethod
    def _direct_write_round():
        """合格形态甲：本轮直接改 —— `mark_read` 真发且成功。"""
        return _round(1,
                      calls=[("notification_manage", {"action": "mark_read"})],
                      results=[("notification_manage", True)],
                      text="已将「您有一笔新订单待处理」标记为已读")

    @staticmethod
    def _confirm_card_round():
        """合格形态乙：先确认再改 —— P6 实测轨迹（list + unread_count + confirm 卡）。"""
        return _round(
            1,
            calls=[("notification_manage", {"action": "list"}),
                   ("notification_manage", {"action": "unread_count"}),
                   ("interact", {"component": "confirm",
                                 "confirmValue": "确认将 ntf_eval_new_order_0001 标记为已读"})],
            results=[("notification_manage", True), ("notification_manage", True)],
            text="我先查一下你当前有哪些未读通知。",
            cards=[{"component": "confirm", "title": "确认标记这条通知为已读？"}],
        )

    @staticmethod
    def _text_only_round():
        """不合格形态：一次工具都没调、纯文本（`direct_reply` 能顶替的那条通道）。"""
        return _round(1, text="好的，我来帮您看看这条通知。")

    def test_declared_form_is_a_single_or_entry(self):
        """收口后 ST-005 的期望面 = **一条** OR 文本（两条并列 entry = 恒 50% 的原病灶）。"""
        exps = _st005_expectations()
        assert exps == ["notification_manage(action=mark_read) or interact"], (
            f"ST-005 的期望面被改动（原病灶 = 两条并列 entry ⇒ 恒 50%）：{exps}")

    def test_direct_write_scores_full(self):
        """合格形态甲（真去改）⇒ 100%。"""
        assert _score(_st005_expectations(), [self._direct_write_round()]) == 1.0

    def test_confirm_card_scores_full(self):
        """合格形态乙（先确认再改，P6 实测轨迹）⇒ 100%（**这就是本包要修的那 50%**）。"""
        assert _score(_st005_expectations(), [self._confirm_card_round()]) == 1.0

    def test_text_only_scores_zero(self):
        """反向对照（假绿方向）：纯文本 ⇒ 判红（写用例不得由文本满足）。"""
        assert _score(_st005_expectations(), [self._text_only_round()]) == 0.0

    def test_old_two_entry_form_would_score_half(self):
        """红证（注入式）：期望退回**两条并列 entry**（旧形态）⇒ 确认卡路径当场 50%。"""
        old = ["notification_manage(action=mark_read)", "direct_reply or interact"]
        assert _score(old, [self._confirm_card_round()]) == 0.5
        # 且旧形态下「纯文本」也判 50%（= 判绿那半）—— 正是本包去掉 `direct_reply` 分支的理由。
        assert _score(old, [self._text_only_round()]) == 0.5


class TestST005Wiring:
    """用例里**声明的** `forbidden_text` / `must_succeed` == 运行期真正判的断言。

    为什么必须有一格：只测期望时，「声明写错键名 / 渲染丢失 / 效果层被摘掉」两边都不会红。
    """

    @staticmethod
    def _case():
        for c in _cases():
            if c.get("id") == "ST-005":
                return c
        raise AssertionError("用例库解析不到 ST-005 —— 判据坐标失效")

    def test_forbidden_text_unchanged_and_still_fires(self):
        """`forbidden_text` **一字未动**（5 条），且在谎称话术上判红（本包红线：不许放宽）。"""
        c = self._case()
        assert c.get("forbidden_text") == [
            "已标记为已读", "已标为已读", "已全部标记", "已经帮您标记", "已为您标记",
        ], f"ST-005 的 forbidden_text 被改动: {c.get('forbidden_text')}"
        lying = _round(1, calls=[("notification_manage", {"action": "list"})],
                       results=[("notification_manage", True)],
                       text="已为您标记为已读")
        issues = lr.check_forbidden_text([lying], c.get("forbidden_text"))
        assert issues and "已为您标记" in issues[0], issues

    def test_must_succeed_unchanged_and_still_conditional(self):
        """`must_succeed[notification_manage, only_if_called]` **一字未动**：三态都照旧。"""
        c = self._case()
        spec = c.get("must_succeed") or []
        assert spec == [{"tool": "notification_manage", "only_if_called": True}], (
            f"ST-005 的效果层被改动（本包红线：不许放宽）: {spec}")
        cls = TestST005DeclaredExpectation
        # ① 确认卡路径：本轮没执行写 ⇒ `only_if_called` 放过（合格形态，不得假红）
        assert lr.check_must_succeed([cls._confirm_card_round()], spec) == []
        # ② 真去改且成功 ⇒ 过
        assert lr.check_must_succeed([cls._direct_write_round()], spec) == []
        # ③ 去改但**没成** ⇒ 判红（「调了 ≠ 成了」仍由效果层把守）
        failed = _round(1,
                        calls=[("notification_manage", {"action": "mark_read"})],
                        results=[("notification_manage", False)])
        issues = lr.check_must_succeed([failed], spec)
        assert issues and "无一成功" in issues[0], issues
