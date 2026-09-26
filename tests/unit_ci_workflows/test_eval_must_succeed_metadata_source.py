# case_ids: AS-003
"""`must_succeed[source: metadata]` —— 落库面（read side）断言形态（issue #4097）。

## 本文件锁什么

#4097 的缺口：写侧自 #4052 起就把 `{tool, success, error}` 落进会话消息的
`metadata.tool_results`，**读侧不暴露、runner 不消费** ⇒ 评测只能断言「模型说它调了」，
不能断言「确实调了 / 确实成了」。本文件锁这条新通路的**四件事**（缺一即空转）：

| # | 判据 | 会怎么红 |
|---|---|---|
| ① | **面选择**：`source: metadata` 走落库面、缺省走 SSE 面、取值拼错判配置错误 | 取数面被静默忽略 ⇒ 断言降级/空转 |
| ② | **fail-closed**：落库面取数不可用（读侧没暴露该键 / HTTP 失败 / 用例跨会话）⇒ 判「断言未评估」 | 读侧一挂，断言静默消失、用例照旧判绿 |
| ③ | **归因**：上面那类红必须折叠成**独立原子**（`config_error(must_succeed_metadata)`），不与行为失败同形 | 读侧回归被读成「工具没跑」= 归因错人、修复方向反过来 |
| ④ | **可达/接线**：用例里声明的 `source` 经 `load_cases_from_yaml`（CI 走的就是这条）原样到达 runner，**且真被消费** | 声明了没人读 = #3391/#3417 的静默失效形态 |

## ④ 为什么要两半（声明的可达性 + 消费的存在性）

**只测"加载器把 source 带过来了"不够**：一个带过来却没人消费的键，在 `only_if_called: true`
的条目上会**静默判绿**（SSE 面没调用 ⇒ 条件档放过）。故 `TestDeclaredCaseIsWired` 拿
**用例库里真实声明的** spec 喂**真实的消费者**（`check_must_succeed`），并用
"SSE 面成功 vs 落库面失败"这对**互相矛盾**的输入做**判别性**断言：
honored ⇒ 红；`source` 被拿掉（= 声明无消费者）⇒ 绿。后者就是"声明了却没人读"的红证。

⚠️ 本目录跑在 CI 的 `ci workflow helper unit tests` job（只 `pip install pytest pyyaml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 见下方 `_load_runner()` 的最小替身。
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
WELLFORMED_TEST = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_assertion_specs_wellformed.py"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
CASES_DIR = REPO_ROOT / ".github" / "cases"


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，且一旦被调用即抛错）。"""
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

CASE_ID = "AS-003"          # 声明 `source: metadata` 的用例（见 .github/cases/aftersales.yml）


def _fn_body_rounds(calls, results, rnd=1):
    """SSE 面的一轮（与 `test_eval_runner_same_round_scope.py` 同形）。"""
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [{"tool": t, "result": {"success": ok}} for t, ok in results],
    }


def _history_payload(entries):
    """`GET /api/chat/history/{sid}` 的成功响应（entries 为 assistant 消息列表）。

    `expose_key=False` 复现**读侧未暴露**的形态（键整个不存在）—— 这不是"空结果"，
    而是 issue #4097 本身的缺陷形态。
    """
    messages = [{"role": "user", "content": "客户手机号 13800138000 最近的订单"}]
    for e in entries:
        msg = {"role": "assistant", "content": "好的"}
        if e.get("expose_key", True):
            msg["tool_results"] = e.get("tool_results")
        if e.get("tool_calls") is not None:
            msg["tool_calls"] = e.get("tool_calls")
        messages.append(msg)
    return {"code": 0, "data": {"session_id": "sess_x", "messages": messages}}


# ══════════════════════════════════════════════════════════════════════════════
# ① 词汇表单一源（静态门禁的常量 vs runner 的常量）
# ══════════════════════════════════════════════════════════════════════════════

class TestVocabularyHasSingleSource:
    """两处各写一份「支持哪些面」⇒ 必然漂移（静态放行、运行期判红，或反之）。"""

    def _wellformed_constant(self, name: str):
        tree = ast.parse(WELLFORMED_TEST.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return set(ast.literal_eval(node.value))
        raise AssertionError(f"test_assertion_specs_wellformed.py 里找不到 {name} —— 解析失效")

    def test_runner_and_static_gate_agree(self):
        assert set(lr.MUST_SUCCEED_SOURCES) == self._wellformed_constant(
            "SUPPORTED_MUST_SUCCEED_SOURCES"), (
            "静态门禁词汇表与 runner 的支持集不一致 —— 会一边放行一边判红")

    def test_default_face_is_sse(self):
        """缺省面必须是 SSE（存量用例语义一字不变：不写 `source` = 老行为）。"""
        assert "sse" in lr.MUST_SUCCEED_SOURCES
        assert lr.check_must_succeed(
            [_fn_body_rounds([("order_create", {})], [("order_create", True)])],
            [{"tool": "order_create"}]) == []


# ══════════════════════════════════════════════════════════════════════════════
# ② 面选择 + fail-closed
# ══════════════════════════════════════════════════════════════════════════════

class TestFaceSelection:
    SPEC = [{"tool": "order_create", "source": "metadata"}]

    def test_metadata_face_success_passes(self):
        rounds, err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "order_create", "success": True, "error": None}]}]))
        assert err == ""
        assert lr.check_must_succeed([], self.SPEC, metadata_rounds=rounds) == []

    def test_metadata_face_failure_is_red(self):
        rounds, _err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "order_create", "success": False,
                               "error": "tool_execution_failed"}]}]))
        issues = lr.check_must_succeed([], self.SPEC, metadata_rounds=rounds)
        assert len(issues) == 1 and "无一成功" in issues[0], issues
        assert "落库面" in issues[0], f"判红必须标出读的是哪一面：{issues[0]}"

    def test_metadata_face_does_not_read_sse_face(self):
        """两面**显式二选一**：SSE 面成功不能让落库面断言通过（否则等于没换面）。"""
        sse_ok = [_fn_body_rounds([("order_create", {})], [("order_create", True)])]
        rounds, _err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "order_create", "success": False, "error": "x"}]}]))
        issues = lr.check_must_succeed(sse_ok, self.SPEC, metadata_rounds=rounds)
        assert len(issues) == 1 and "无一成功" in issues[0], issues

    def test_missing_metadata_face_is_fail_closed(self):
        """取数不可用 ⇒ 判「断言未评估」（不是通过、也不是"从未被调用"）。"""
        issues = lr.check_must_succeed([], self.SPEC, metadata_rounds=None,
                                       metadata_error="读侧取数 HTTP 404")
        assert len(issues) == 1 and "断言未评估" in issues[0], issues
        assert "HTTP 404" in issues[0], f"原因必须带出来（可归因）：{issues[0]}"

    def test_unknown_source_is_config_error(self):
        issues = lr.check_must_succeed([], [{"tool": "order_create", "source": "metdata"}])
        assert len(issues) == 1 and "source=" in issues[0] and "支持集" in issues[0], issues

    def test_action_scope_survives_on_metadata_face(self):
        """`action` 作用域在落库面同样成立（同形 rounds ⇒ 复用同一段对齐逻辑）。

        落库面 `tool_calls` 带 args（写侧 `tool_calls_info` 就存 `{tool, args}`）⇒
        同名工具不同 action 的成败不会互相顶替。
        """
        rounds, _err = lr.rounds_from_history_payload(_history_payload([{
            "tool_calls": [{"tool": "after_sales_manage", "args": {"action": "detail"}},
                           {"tool": "after_sales_manage", "args": {"action": "create"}}],
            "tool_results": [{"tool": "after_sales_manage", "success": True, "error": None},
                             {"tool": "after_sales_manage", "success": False, "error": "denied"}],
        }]))
        assert lr.check_must_succeed(
            [], [{"tool": "after_sales_manage", "action": "detail", "source": "metadata"}],
            metadata_rounds=rounds) == []
        issues = lr.check_must_succeed(
            [], [{"tool": "after_sales_manage", "action": "create", "source": "metadata"}],
            metadata_rounds=rounds)
        assert len(issues) == 1 and "无一成功" in issues[0], (
            f"别的 action 成功顶替了 create（假绿）：{issues}")

    def test_only_if_called_on_metadata_face(self):
        """条件档在落库面同样生效：落库面没有该调用 ⇒ 放过；有但没成 ⇒ 判红。"""
        empty, _err = lr.rounds_from_history_payload(_history_payload([{"tool_results": None}]))
        spec = [{"tool": "order_create", "source": "metadata", "only_if_called": True}]
        assert lr.check_must_succeed([], spec, metadata_rounds=empty) == []
        failed, _err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "order_create", "success": False, "error": "e"}]}]))
        assert len(lr.check_must_succeed([], spec, metadata_rounds=failed)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# ③ 读侧回归 = 独立原子（归因不许错人）
# ══════════════════════════════════════════════════════════════════════════════

class TestReadSideRegressionHasItsOwnAtom:
    def test_exposed_key_absent_is_an_error_not_an_empty_face(self):
        """「读侧没暴露该键」必须与「确实没有工具结果」区分开（#4097 的病根）。"""
        rounds, err = lr.rounds_from_history_payload(_history_payload([
            {"expose_key": False, "tool_calls": [{"tool": "order_create", "args": {}}]}]))
        assert rounds == [] and "读侧未暴露" in err, (rounds, err)
        # 反向：键在、值为空 ⇒ **不是**错误（确实没调过工具）
        rounds2, err2 = lr.rounds_from_history_payload(_history_payload([{"tool_results": []}]))
        assert rounds2 == [] and err2 == "", (rounds2, err2)

    def test_missing_messages_is_an_error(self):
        assert lr.rounds_from_history_payload({"data": {}})[1] != ""

    def test_failure_folds_to_its_own_token(self):
        """配置/取数类红 → `config_error(must_succeed_metadata)`，**不**与行为失败同形。"""
        msg = lr.check_must_succeed([], [{"tool": "order_create", "source": "metadata"}],
                                    metadata_rounds=None, metadata_error="x")[0]
        assert lr._case_issue_atom(msg) == "config_error(must_succeed_metadata)", (
            f"读侧回归被折叠成 {lr._case_issue_atom(msg)} —— 会被读成「工具没跑」")
        # 行为失败仍是原来的原子（两面**同一个** no_success，不是新造一个）
        rounds, _err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "order_create", "success": False, "error": "e"}]}]))
        msg2 = lr.check_must_succeed([], [{"tool": "order_create", "source": "metadata"}],
                                     metadata_rounds=rounds)[0]
        assert lr._case_issue_atom(msg2) == "no_success(order_create)", (
            f"落库面的行为失败折叠成了 {lr._case_issue_atom(msg2)} —— 与 SSE 面不同源")


# ══════════════════════════════════════════════════════════════════════════════
# ④ 可达性：声明 → 装载（CI 路径）→ 真被消费
# ══════════════════════════════════════════════════════════════════════════════

def _yaml_cases():
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    from render_cases import load_case_dicts
    return {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}


def _loaded_cases():
    return {c.id: c for c in lr.load_cases_from_yaml(str(CASES_DIR))}


class TestDeclaredCaseIsWired:
    """用例库里声明的 `source` 必须**原样**到达 runner，并且**真被消费**。"""

    def test_loader_maps_must_succeed_specs_verbatim(self):
        """装载器对 `must_succeed` 的**嵌套键**逐值保真（CI 走的就是这条路径）。

        这正是 #3391/#3417 的病根面：`must_succeed` 整体映射看着没问题，
        但只要装载器对 spec 做了重建/白名单化，`source` 就会在这一步**静默消失**
        ⇒ 用例声明了落库面、跑的却是 SSE 面（"声称查了而其实没查"）。
        """
        yaml_cases, loaded = _yaml_cases(), _loaded_cases()
        assert yaml_cases, "用例库读空了 —— 判据会变成恒真断言"
        bad = [cid for cid, c in loaded.items()
               if (yaml_cases.get(cid, {}).get("must_succeed") or []) != (c.must_succeed or [])]
        assert not bad, f"这些用例的 must_succeed 在装载时被改写了：{bad}"

    def test_case_declares_the_metadata_face(self):
        spec = [s for s in (_loaded_cases()[CASE_ID].must_succeed or [])
                if isinstance(s, dict) and s.get("source") == "metadata"]
        assert spec, (f"{CASE_ID} 未声明 `source: metadata` —— 新通路**零消费者**"
                      f"（读者会以为有覆盖；见用例内注释）")

    def test_declared_spec_is_actually_consumed(self):
        """判别性断言：拿**用例库里真声明的** spec 喂真消费者。

        SSE 面说「成了」、落库面说「没成」——两个互相矛盾的输入：
          · `source` honored ⇒ 读落库面 ⇒ **判红**（本断言成立）；
          · `source` 无人消费（= 声明了没人读）⇒ 读 SSE 面 ⇒ 放过 ⇒ **本断言失败**。
        所以这半条就是「声明必须有消费者」的红证。
        """
        spec = [s for s in (_loaded_cases()[CASE_ID].must_succeed or [])
                if isinstance(s, dict) and s.get("source") == "metadata"]
        assert spec, f"{CASE_ID} 未声明落库面断言"
        sse_says_ok = [_fn_body_rounds([("aftersale_create", {})], [("aftersale_create", True)])]
        meta, _err = lr.rounds_from_history_payload(_history_payload([
            {"tool_results": [{"tool": "aftersale_create", "success": False, "error": "e"}]}]))
        issues = lr.check_must_succeed(sse_says_ok, spec, metadata_rounds=meta)
        assert len(issues) == 1 and "无一成功" in issues[0], (
            f"声明的落库面断言没被消费（读的还是 SSE 面）：{issues}")
        # 反向红证：把 `source` 拿掉 ⇒ 同一输入**放过** —— 证明上面那条红是 `source` 挣来的
        stripped = [{k: v for k, v in s.items() if k != "source"} for s in spec]
        assert lr.check_must_succeed(sse_says_ok, stripped, metadata_rounds=meta) == [], (
            "去掉 source 后仍判红 —— 说明那条红不是 source 的作用，本判据没有判别力")


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 被拒后自愈率（报告型读数；#4097 评论）
# ══════════════════════════════════════════════════════════════════════════════

def _round(*events):
    """events: [(tool, success, error)] → 一轮同形 results 条目。"""
    return {"__round": 1, "tool_calls": [], "tool_results": [
        {"tool": t, "result": {"success": ok, "error": e}} for t, ok, e in events]}


class TestDenialRecoveryStats:
    """口径（本类的定义即判据）：被拒 = 白名单拒码且 success=false；
    自愈 = 其后 3 个事件内出现至少一次成功。"""

    def test_recovered_within_window(self):
        stats = lr.denial_recovery_stats([
            _round(("validate_input", False, "cross_skill_target")),
            _round(("customer_order_query", True, "")),
        ])
        assert (stats["denials"], stats["recovered"], stats["recovery_rate"]) == (1, 1, 1.0)
        assert stats["unrecovered"] == []

    def test_not_recovered_is_reported_with_position(self):
        """#4123 的 AS-003 形态：被拒之后再无成功调用 ⇒ 未自愈，且给出定位。"""
        stats = lr.denial_recovery_stats([
            _round(("validate_input", False, "cross_skill_target")),
        ])
        assert (stats["denials"], stats["recovered"], stats["recovery_rate"]) == (1, 0, 0.0)
        assert stats["unrecovered"][0]["error"] == "cross_skill_target"

    def test_window_boundary(self):
        """窗口是**其后 3 个事件**：第 3 个算自愈、第 4 个不算（边界写死在判据里）。"""
        near = [_round(("validate_input", False, "cross_skill_target"))] + [
            _round(("t", False, "")) for _ in range(2)] + [_round(("t", True, ""))]
        far = [_round(("validate_input", False, "cross_skill_target"))] + [
            _round(("t", False, "")) for _ in range(3)] + [_round(("t", True, ""))]
        assert lr.denial_recovery_stats(near)["recovered"] == 1
        assert lr.denial_recovery_stats(far)["recovered"] == 0

    def test_unregistered_error_code_is_not_a_denial(self):
        """未登记的码不进分母（白名单制：宁少报，不把普通失败算成"被拒"）。"""
        stats = lr.denial_recovery_stats([_round(("order_create", False, "tool_execution_failed"))])
        assert stats["denials"] == 0 and stats["recovery_rate"] is None

    def test_empty_face_is_not_a_denial(self):
        assert lr.denial_recovery_stats([])["denials"] == 0
