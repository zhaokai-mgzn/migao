# case_ids: OR-026, CU-005, PG-016, OR-006
"""**声明的 `action` 必须真实存在于该工具的 action 枚举**（L0 静态不变式，issue #3689）。

## 为什么是 L0（`migao-dev-flow` §16.1）
「声明了工具**不存在**的 action」是**结构性**配置错误：断言永不满足（假红），
或更糟 —— 断言器根本**看不见**它（假绿）。这类缺陷必须由零 LLM、秒级的静态不变式拦住，
不允许流到真实 LLM 重放去撞。先例：CU-005 的 `customer_manage(action=query)`
（该工具枚举无 `query`，已在 #3683 修正）。

## 判据的**单一实现点**（issue #3701 收口）
判据函数 `action_binding_violations` 住在 `scripts/case_coverage.py`，由
**门禁**（`build_coverage_report` → 两个 CLI 的 `--check`）与**本文件**共同调用 ——
本文件不再自带一份平行实现（此前正因门禁那份有三处盲区，才出现"单测层绿 ≠ 门禁绿"）。
`TestGateAndInvariantAgree` 锁住两侧**同一口径**（同输入 → 同结果）。

| 盲区（#3701 修前，门禁实测放行） | 修后 |
|---|---|
| 只遍历 `action_catalog()`（**有** action 维度的工具）：`must_fail: [{tool: order_create, action: create}]`（`order_create` 无 action 属性，OR-026 被拒的写法）不被报出 | 工具**没有** action 维度时声明 action = `no_action_param`，必报 |
| 只扫 `select_cases_for_persona()` 选中的用例（`skip_reason` 非空即丢）：OR-006 的 `order_query(action=detail)` 被藏住（#3702） | 扫**全库**用例（含 skip）—— skip 只免"参与覆盖统计"，不免"声明合法性"（该用例的非法声明已由 #3702 改为 `action: list`） |
| `case_declared_actions()` 不收 `repeat_until.action`（#3667 的 action 级停条件） | 收（停条件悬空 → 用例空转到轮数耗尽） |

## 红证（本文件自带）
`TestRedEvidence*` 组用**合成用例**（行为确实错了）证明判据会红：
① `must_fail: [{tool: order_create, action: create}]`（OR-026 被拒的写法）→ 必须报出；
② `repeat_until.action` 悬空 → 必须报出；③ 合法声明 → **不得**误报（假红面）。

## 与 runner 侧的分工（诚实标注）
runner（`check_must_fail`）**无法**自行判断"该工具没有 action 参数" —— 它只看逐轮
`tool_calls`/`tool_results`，没有工具 schema；而"声明 action 但整场从未以该 action 调用"
在语义上仍是**合格通过**（`must_fail` 的镜像语义：从未调用 = 通过；反例：`order_query`
有 `"default": "list"`，模型不带 action 参数调用也是合法的）。
⇒ fail-closed 的落点只能是**有 schema 真值**的这一层（本文件），
runner 侧只对**可判定**的配置错误报错（未支持的键 / 非映射 `args`，见
`test_eval_runner_must_fail_scope.py::TestMustFailConfigIsFailClosed`）。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / ".github", REPO_ROOT / "tests" / "agent_eval", REPO_ROOT / "scripts"):
    sys.path.insert(0, str(_p))

from case_coverage import (  # noqa: E402
    ACTION_TOOL_FLOOR, action_binding_violations, action_catalog, action_enum,
    build_coverage_report, registered_tools, tool_declared_actions, toolset_for,
)
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

# ── 存量登记（burn-down）：一条一登记，销账即删 ────────────────────────────────
# **已归零**（2026-09-15，issue #3702）：最后一条是 OR-006 —— 它声明
# `order_query(action=detail)`，而该工具枚举 = `list / statistics / follow_status_stats`
# （`app/tools/order_query.py`）→ 该 expectation 声明的取值在真实链路里不存在。
# 该用例已按真实语义改为 `action: list`，门禁侧同一缺口（`.github/eval-coverage-baseline.yml`
# 的 `order_query` / `action_dangling` / persona mibao）也在同一个 PR 删除 —— 两处登记与销账
# 必须配对，且各自都有"陈旧即红"的守卫（门禁：`check_problems()` 的 `baseline_stale_blocking`；
# 本文件：`test_known_exemption_is_not_stale`），故漏删任何一处都会被 CI 抓住。
# ⚠️ 清单归零后「遍历 `_KNOWN_DANGLING` 逐个断言」会**空转恒真**（循环体不执行 = 空断言，
# `migao-acceptance` v1.3）—— 故守卫改为**注入式自证**（见 `_stale_exemptions` 与该测试）。
# 新增存量登记时照旧往里加；销账后**必须删条目**（清单只可能变短）。
_KNOWN_DANGLING: dict = {}


def _unregistered_violations(violations) -> list:
    """扣掉显式登记的存量条目 → 其余即阻塞项。"""
    return [v for v in violations if (v[0], v[1], v[2]) not in _KNOWN_DANGLING]


def _stale_exemptions(current: set, registry: dict | None = None) -> list:
    """`registry` 里**语料中已不存在**的登记 → 陈旧登记（销账后必须删条目，防白名单腐烂）。

    抽出成函数是为了让"守卫会响"这件事**可注入地证明**：清单归零后，直接遍历
    `_KNOWN_DANGLING` 的写法循环体不执行 = 恒真（守卫静默失效），故改由本函数承担，
    测试里用合成 registry 走红/绿两面（见 `test_known_exemption_is_not_stale`）。
    """
    reg = _KNOWN_DANGLING if registry is None else registry
    return [k for k in reg if k not in current]


# ── 红证：合成"行为确实错了"的用例 → 判据必须红 ────────────────────────────────

class TestRedEvidenceDanglingActionBlocks:
    """**红证**：把行为改坏（声明一个工具没有的 action）→ 不变式必须报出，不许静默通过。"""

    def test_must_fail_declaring_action_on_tool_without_action_param_is_red(self):
        """**OR-026 被拒的那条写法**：`must_fail: [{tool: order_create, action: create}]`。

        `order_create` 无 action 参数（`app/tools/order_create.py` 无 `"action"` 属性）
        ⇒ runner 里 `if not called: continue` 整条静默跳过（假绿）。
        #3701 前的门禁（只遍历有 action 维度的工具）**看不见它**，判据必须看见。
        """
        cases = [{"id": "T-RED-1", "must_fail": [{"tool": "order_create", "action": "create"}]}]
        v = action_binding_violations(cases)
        assert v == [("T-RED-1", "order_create", "create", "no_action_param")], v

    def test_expectation_action_not_in_enum_is_red(self):
        """枚举不含该值（`customer_manage(action=query)` 的 CU-005 形态）→ 必须报出。"""
        cases = [{"id": "T-RED-2",
                  "expectations": [{"tool": "customer_manage", "args": {"action": "query"}}]}]
        v = action_binding_violations(cases)
        assert v and v[0][0] == "T-RED-2" and v[0][3] == "not_in_enum", v

    def test_repeat_until_dangling_action_is_red(self):
        """**盲区③**：`repeat_until.action` 悬空 → 停条件永不命中，必须报出。"""
        cases = [{"id": "T-RED-3",
                  "user_inputs": [{"repeat_until": {"tool_called": "order_query",
                                                    "action": "detail", "max": 3}}]}]
        v = action_binding_violations(cases)
        assert v == [("T-RED-3", "order_query", "detail", "not_in_enum")], v

    def test_must_succeed_and_db_verify_sources_are_covered(self):
        """`must_succeed` / `db_verify.source` 的 action 同受约束（不漏面）。

        ⚠️ 2026-09-15（#3917）：fixture 里的 `processing_order_update` 已从注册表移除
        （未注册工具由 `dangling_cases` 判据管，不在此函数）→ 改用 `order_manage`
        （已注册的多 action 工具），断言语义不变。
        """
        cases = [{"id": "T-RED-4",
                  "must_succeed": [{"tool": "product_manage", "action": "no_such_action"}],
                  "db_verify": [{"fetch": "processing_order", "source": "order_manage",
                                 "action": "jump", "checks": ["status==completed"]}]}]
        v = {x[1:] for x in action_binding_violations(cases)}
        assert ("product_manage", "no_such_action", "not_in_enum") in v, v
        assert ("order_manage", "jump", "not_in_enum") in v, v


class TestNoFalsePositives:
    """**假红面**：合法声明不得被误报（否则门禁变成一堵红墙，逼后代删判据）。"""

    def test_valid_action_is_green(self):
        cases = [{"id": "T-OK-1",
                  "expectations": [{"tool": "order_manage", "args": {"action": "cancel"}}],
                  "must_fail": [{"tool": "product_manage", "action": "create"}],
                  "user_inputs": [{"repeat_until": {"tool_called": "processing_order_update",
                                                    "action": "complete", "max": 3}}]}]
        assert action_binding_violations(cases) == []

    def test_tool_without_action_param_and_no_action_declared_is_green(self):
        """裸工具名（`must_fail: [order_create]` / `expectations: [{tool: order_create}]`）→ 绿。"""
        cases = [{"id": "T-OK-2", "must_fail": ["order_create"],
                  "expectations": [{"tool": "order_create"}]}]
        assert action_binding_violations(cases) == []

    def test_unregistered_tool_is_left_to_dangling_tool_judgement(self):
        """未注册工具（拼错/已删除）不在这里重复报 —— 那是 `dangling_cases` 的判据。"""
        cases = [{"id": "T-OK-3",
                  "expectations": [{"tool": "no_such_tool", "args": {"action": "x"}}]}]
        assert action_binding_violations(cases) == []


class TestRepoActionBinding:
    """仓库真值：全库（**含 skip 用例**）声明的 action 必须都能在该工具枚举里找到。"""

    @classmethod
    def setup_class(cls):
        cls.cases = load_case_dicts(str(CASES_DIR))

    def test_truth_source_is_not_silently_empty(self):
        """真值解析下界：解析口径漂移（文件改名/枚举挪走）会让本判据**假绿**，必须拦住。"""
        assert tool_declared_actions("order_manage") == {
            "update_status", "update_logistics", "cancel", "confirm_payment", "refund"}
        assert action_enum("order_create") == set(), (
            "order_create 被判定为『有 action 维度』—— 判据口径漂移（OR-026 的静默空转拦不住）")
        assert action_enum("no_such_tool") is None, (
            "不存在的工具必须返回 None（与『无 action 维度』区分）—— 否则工具名拼错会被误判成悬空 action")
        assert len(action_catalog(registered_tools())) >= ACTION_TOOL_FLOOR

    def test_repo_has_no_unregistered_action_bindings(self):
        """全库阻塞项 = 0（存量条目已显式登记，见 `_KNOWN_DANGLING`）。"""
        v = _unregistered_violations(action_binding_violations(self.cases))
        assert v == [], (
            "用例声明了工具不存在的 action（断言永不满足 —— 假红/假绿）:\n  "
            + "\n  ".join(f"{c} {t}(action={a}) [{k}]" for c, t, a, k in v))

    def test_skipped_cases_are_scanned_too(self):
        """**盲区②**：`skip_reason` 非空的用例同样要扫 —— 用例解 skip 时不能带着悬空 action 上场。

        红证方式（注入真实 skip 用例，而不是断言"仓库里恰好有违规"）：
        往一条**真实的** skip 用例副本里塞一个悬空 action → 必须被报出。
        """
        skipped = [c for c in self.cases if str(c.get("skip_reason") or "").strip()]
        assert skipped, "仓库里应存在 skip 用例（否则本断言失去意义）"
        probe = dict(skipped[0])
        probe["must_fail"] = [{"tool": "order_create", "action": "create"}]
        v = action_binding_violations([probe])
        assert v and v[0][1] == "order_create" and v[0][3] == "no_action_param", v

    def test_known_exemption_is_not_stale(self):
        """**清单只能变短**：登记条目对应的违规若已消失 → 红，逼删条目（防白名单腐烂）。

        ⚠️ #3702 销账后 `_KNOWN_DANGLING` 已归零 ⇒ 旧写法 `for key in _KNOWN_DANGLING:`
        的**循环体不执行 = 恒真**（守卫静默失效，正是 `migao-acceptance` v1.3 的"空断言"）。
        故改为**注入式自证**（三面都要锁，缺一即降强度）：
          ① 仓库真值：全库（含 skip）声明的 action 全部合法 ⇒ **无任何陈旧登记**；
          ② **红证**：注入一条"语料里已不存在"的登记 → 必须判为陈旧（守卫会响）；
          ③ **假红面**：注入一条"语料里确实存在"的登记 → **不得**误判陈旧。
        """
        current = {(c, t, a) for c, t, a, _k in action_binding_violations(self.cases)}
        # ① 仓库真值（同时是下面 ② 判据的"锚"：这一集合已为空，不能再拿它当非空前提）
        stale = _stale_exemptions(current)
        assert stale == [], (
            "存量登记已销账但条目未删: "
            + ", ".join(map(str, stale)) + " —— 删除 `_KNOWN_DANGLING` 里的该条目")

        # ② 红证：借用一条**真实存在过**的违规形态，但它不在语料里 ⇒ 必判陈旧
        ghost = {("T-STALE", "order_query", "detail"):
                 {"issue": "#0000", "reason": "红证夹具（语料里不存在）", "added": "2026-09-15"}}
        assert _stale_exemptions(current, ghost) == [("T-STALE", "order_query", "detail")], (
            "陈旧的存量登记没有被判红 —— 守卫空转（白名单会腐烂）")

        # ③ 假红面：合成一条**真违规**进语料，同一登记必须被判为"仍在使用"（不得误红）
        live_cases = [{"id": "T-LIVE",
                       "expectations": [{"tool": "order_query", "args": {"action": "detail"}}]}]
        live_current = {(c, t, a) for c, t, a, _k in action_binding_violations(live_cases)}
        assert live_current == {("T-LIVE", "order_query", "detail")}, live_current
        live = {("T-LIVE", "order_query", "detail"):
                {"issue": "#0000", "reason": "红证夹具（语料里存在）", "added": "2026-09-15"}}
        assert _stale_exemptions(live_current, live) == [], (
            "仍在抑制真实缺口的登记被判成陈旧 —— 假红（会逼人删掉有效豁免）")


class TestGateAndInvariantAgree:
    """**门禁与 L0 不变式必须同一口径**（issue #3701 的核心验收）。

    #3701 的病根不是"判据写错"，而是**同一个判据存在两份实现**（门禁那份漏了三处，
    单测那份补上了）→ 「单测层绿 ≠ 门禁绿」。收口方式：判据函数只有一份
    （`case_coverage.action_binding_violations`），本组测试把"两侧同口径"变成**可执行断言** ——
    将来任何一方被单独改成另一套逻辑，这里立刻红。
    """

    @classmethod
    def setup_class(cls):
        cls.cases = load_case_dicts(str(CASES_DIR))

    # 注入夹具（合成语料副本）：两端各一条悬空声明，语义与真实链路无关，只为让关系式
    # 在**非空集合**上有判别力。`order_query` 属 B 端、`aftersale_query` 属 C 端（实测）。
    _INJECT = (
        {"id": "T-AGREE-M", "expectations": [{"tool": "order_query", "args": {"action": "detail"}}]},
        {"id": "T-AGREE-X", "expectations": [{"tool": "aftersale_query",
                                              "args": {"action": "no_such_action"}}]},
    )

    def test_gate_reports_exactly_the_invariant_violations(self):
        """逐端比对：门禁报出的 `(tool, action)` == 不变式报出的合法映射（含 skip 用例）。

        ⚠️ 关系式的**前提必须由构造保证非空**：#3702 销账后仓库真值已归零
        （全库零悬空声明）—— 直接拿它比"空集 == 空集"是**没有判别力**的空断言
        （`migao-acceptance` v1.3）。故在**语料副本**上追加合成悬空声明，让关系式在
        **非空集合**上成立。这是**加强**不是放宽：
          ① 仓库真值必须为空（新引入的悬空声明会立刻打红本断言）；
          ② 注入后 门禁 vs 不变式 仍必须**逐端一致**（这才是本组的原始目的）。
        """
        assert action_binding_violations(self.cases) == [], (
            "仓库真值：全库（含 skip）不得有悬空 action 声明 —— 新增的会在此暴露")
        cases = self.cases + list(self._INJECT)
        invariant = {(t, a) for _c, t, a, _k in action_binding_violations(cases)}
        assert invariant == {("order_query", "detail"), ("aftersale_query", "no_such_action")}, (
            f"注入后的悬空集合与预期不符（判据口径漂移）: {sorted(invariant)}")
        for persona in ("mibao", "xiaobu"):
            rep = build_coverage_report(cases, persona)
            expected = {p for p in invariant if p[0] in toolset_for(persona)}
            assert expected, f"{persona}: 注入夹具没落在该端 —— 本断言退化为空集比对"
            assert set(rep.action_dangling) == expected, (
                f"{persona}: 门禁与 L0 不变式的悬空 action 口径不一致"
                f"（门禁 {sorted(rep.action_dangling)} vs 不变式 {sorted(expected)}）"
            )

    def test_union_of_both_ends_covers_every_violation(self):
        """两端并集 = 全库违规（防"某条用例被 persona 过滤掉 → 两端都不扫"的漏网）。

        门禁按端归属报（一个 tool 只属一端），故单端看不见另一端工具上的悬空声明 ——
        本断言锁住"合起来不漏"，并锁住报错信息里**带得出用例 ID**（销账靠它定位）。
        前提同样**由构造保证非空**（注入两端的悬空声明，见 `_INJECT`）：仓库真值已归零，
        空集上的"并集相等"没有判别力。
        """
        cases = self.cases + list(self._INJECT)
        invariant = {(t, a) for _c, t, a, _k in action_binding_violations(cases)}
        assert len(invariant) == 2, f"注入夹具失效（应有两端各一条）: {sorted(invariant)}"
        union = set()
        for persona in ("mibao", "xiaobu"):
            rep = build_coverage_report(cases, persona)
            union |= set(rep.action_dangling)
            for pair in rep.action_dangling:
                assert rep.action_dangling_cases.get(pair), (
                    f"{persona}: 悬空 action {pair} 没有关联到任何用例 ID —— "
                    f"报了错但定位不到用例（销账无从下手）")
        assert union == invariant, (
            f"两端并集 {sorted(union)} 未覆盖全库违规 {sorted(invariant)}")

