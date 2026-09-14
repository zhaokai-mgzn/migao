# case_ids: OR-026, CU-005, PG-016
"""**声明的 `action` 必须真实存在于该工具的 action 枚举**（L0 静态不变式，issue #3689）。

## 为什么是 L0（`migao-dev-flow` §16.1）
「声明了工具**不存在**的 action」是**结构性**配置错误：断言永不满足（假红），
或更糟 —— 断言器根本**看不见**它（假绿）。这类缺陷必须由零 LLM、秒级的静态不变式拦住，
不允许流到真实 LLM 重放去撞。先例：CU-005 的 `customer_manage(action=query)`
（该工具枚举无 `query`，已在 #3683 修正）。

## 本文件补的是既有门禁**拦不住**的三处（实测，见 issue #3689）
既有判据 = `scripts/case_coverage.py` 的 `action_dangling`（阻塞 + 存量豁免清单），
但它有三处盲区，**恰恰覆盖不住 OR-026 登记的那个静默空转形态**：

| 盲区 | 实测（origin/main） | 后果 |
|---|---|---|
| 只遍历 `action_catalog()`（**有** action 维度的工具）—— `case_coverage.py:625` `for tool, acts in rep.action_tools.items()` | `must_fail: [{tool: order_create, action: create}]`（`order_create` 无 action 属性）**不被报出** | 正是 OR-026 里"整条静默跳过"的形态，门禁放行 |
| 只扫 `select_cases_for_persona()` 选中的用例（`skip_reason` 非空即丢） | OR-006 声明 `order_query(action=detail)`（枚举只有 `list/statistics/follow_status_stats`）因该用例 skip 而**不可见** | 用例一旦解 skip 即带着永不满足的断言上场 |
| `case_declared_actions()` 不收 `repeat_until.action`（#3667 新增的 action 级停条件） | `repeat_until: {tool_called: X, action: <拼错>}` 不被检查 | 停条件永不命中 → 用例空转到轮数耗尽 |

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
    ACTION_TOOL_FLOOR, action_catalog, case_declared_actions, tool_declared_actions,
)
from eval_case_filter import XIAOBU_TOOLS, mibao_real_toolset  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

# ── 存量登记（burn-down）：一条一登记，销账即删 ────────────────────────────────
# 判据在加入本文件前**从未生效**（既有门禁只扫"可跑用例 + 有 action 维度的工具"），
# 故这条是**新暴露出来的存量缺口**，不是本次改动引入的：
#   OR-006（`order.yml:174`）声明 `order_query(action=detail)`，而该工具枚举 =
#   `list / statistics / follow_status_stats`（`app/tools/order_query.py:61`）——
#   该 expectation 永不满足。用例当前 `skip_reason` 非空（缺"可全流转的测试订单"，#3599）
#   故跑不到，属于隐藏的假红。**归用例资产包销账**（本包不碰 cases/*.yml）。
# 销账后本表**必须删条目**（`test_known_exemption_is_not_stale` 会红），清单只可能变短。
_KNOWN_DANGLING: dict = {
    ("OR-006", "order_query", "detail"): {
        "issue": "#3599",
        "reason": "order_query 枚举无 detail；用例待解 skip（#3599）时须一并按真实语义修正"
                  "（runner/门禁口径见 #3689）",
        "added": "2026-09-15",
    },
}


def _registered_tools() -> set:
    """两端注册表并集（B 端米宝 + C 端小布）—— 未注册工具由 `dangling_cases` 判据管。"""
    return set(mibao_real_toolset()) | set(XIAOBU_TOOLS)


def _action_enum(tool: str) -> set | None:
    """工具源码声明的 action 枚举；`None` = **该工具没有 action 维度**（schema 无 action 属性）。

    真值口径与 `case_coverage.tool_declared_actions` 同一份实现（源码 `action.enum`），
    只是把"无 action 维度"与"枚举为空"区分开 —— 前者是**结构性**错误（声明任何 action 都悬空），
    后者同样悬空，故判据上用不到这个区分；这里保留区分只为把报错信息写准。
    """
    if not (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools" / f"{tool}.py").exists():
        return None                       # 未注册工具：另由工具存在性判据负责
    return tool_declared_actions(tool)


def _repeat_until_bindings(case) -> list:
    """用例 `user_inputs[].repeat_until.action` 声明的 (tool, action)（#3667 的 action 级停条件）。"""
    out = []
    for ui in (case.get("user_inputs") or []):
        if not isinstance(ui, dict):
            continue
        spec = ui.get("repeat_until")
        for s in (spec if isinstance(spec, list) else [spec]):
            if not isinstance(s, dict):
                continue
            tool = str(s.get("tool_called") or s.get("tool") or "").strip()
            action = str(s.get("action") or "").strip()
            if tool and action:
                out.append((tool, action))
    return out


def declared_bindings(cases) -> list:
    """全库声明的 `(case_id, tool, action)` —— expectations/must_* /required_args/output_verify/
    db_verify（经 `case_declared_actions`）+ `repeat_until.action`（本文件补的盲区）。"""
    out = []
    for case in cases:
        cid = case.get("id") if isinstance(case, dict) else getattr(case, "id", "?")
        for tool, acts in case_declared_actions(case).items():
            for a in sorted(acts):
                out.append((cid, tool, a))
        for tool, a in _repeat_until_bindings(case):
            out.append((cid, tool, a))
    return out


def action_binding_violations(cases) -> list:
    """`[(case_id, tool, action, kind)]`；kind ∈ {no_action_param, not_in_enum}。

    `no_action_param` = 该工具 schema 根本没有 action 属性（声明什么 action 都不可能命中）；
    `not_in_enum`     = 有 action 维度，但枚举里没有这个值。
    两者都是"断言永不满足"，**不静默跳过**（这就是 fail-closed 的落点）。
    """
    tools = _registered_tools()
    out = []
    for cid, tool, action in declared_bindings(cases):
        if tool not in tools:
            continue                       # 未注册工具由既有 dangling_cases 判据负责
        enum = _action_enum(tool)
        if enum is None:
            continue
        if not enum:
            out.append((cid, tool, action, "no_action_param"))
        elif action not in enum:
            out.append((cid, tool, action, "not_in_enum"))
    return out


def _unregistered_violations(violations) -> list:
    """扣掉显式登记的存量条目 → 其余即阻塞项。"""
    return [v for v in violations if (v[0], v[1], v[2]) not in _KNOWN_DANGLING]


# ── 红证：合成"行为确实错了"的用例 → 判据必须红 ────────────────────────────────

class TestRedEvidenceDanglingActionBlocks:
    """**红证**：把行为改坏（声明一个工具没有的 action）→ 不变式必须报出，不许静默通过。"""

    def test_must_fail_declaring_action_on_tool_without_action_param_is_red(self):
        """**OR-026 被拒的那条写法**：`must_fail: [{tool: order_create, action: create}]`。

        `order_create` 无 action 参数（`app/tools/order_create.py` 无 `"action"` 属性）
        ⇒ runner 里 `if not called: continue` 整条静默跳过（假绿）。
        既有门禁（只遍历有 action 维度的工具）**看不见它**，本不变式必须看见。
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
        """`must_succeed` / `db_verify.source` 的 action 同受约束（不漏面）。"""
        cases = [{"id": "T-RED-4",
                  "must_succeed": [{"tool": "product_manage", "action": "no_such_action"}],
                  "db_verify": [{"fetch": "processing_order", "source": "processing_order_update",
                                 "action": "jump", "checks": ["status==completed"]}]}]
        v = {x[1:] for x in action_binding_violations(cases)}
        assert ("product_manage", "no_such_action", "not_in_enum") in v, v
        assert ("processing_order_update", "jump", "not_in_enum") in v, v


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
        assert _action_enum("order_create") == set(), (
            "order_create 被判定为『有 action 维度』—— 判据口径漂移（OR-026 的静默空转拦不住）")
        assert len(action_catalog(_registered_tools())) >= ACTION_TOOL_FLOOR

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
        """**清单只能变短**：登记条目对应的违规若已消失 → 红，逼删条目（防白名单腐烂）。"""
        current = {(c, t, a) for c, t, a, _k in action_binding_violations(self.cases)}
        for key in _KNOWN_DANGLING:
            assert key in current, (
                f"存量登记已销账但条目未删: {key} —— 删除 `_KNOWN_DANGLING` 里的该条目")
