"""评测 runner 的**工具级** error code 可断言口径（issue #4098）。

缺口（改前逐字）：`local_runner.check_expectation` 的 `error.code=` 分支读
`actual_error = str(result.get("error", ""))`，而 `result["error"]` **只在 `event: error`
被赋值**（`send_message` 的 `elif current_event == "error": result["error"] = str(payload)`）
—— 工具失败走 `event: tool_result`，永不产生轮级 error ⇒ 「工具必须以某错误码失败」的
断言**恒不可满足**（实证 CH-001 的 `error.code=NOT_FOUND` 在 run 34650006175 逐字报
`expected error not_found but got None`）。

本文件钉住新键 `tool.error.code=<CODE>`，四条性质：
  ① **可取到**：拦写轨迹（S2 = #4073 闸门，`app/graph/skills/execution/react_turn.py`
     的写调用点 → `event: tool_result` 的 `result.error`）⇒ 能取到
     `validation_failed_write_blocked`；改前同一条语料取不到（红证读数见 PR body）；
  ② **不空转**：正常成功轮 ⇒ 取不到该 code（不把判据放宽成"总有错"）；
  ③ **判别力**：只有**轮级** error、无工具级 error 的语料 ⇒ 同一校验函数判违规；
  ④ **不互相吞**：轮级 `error.code=` 与工具级键各读各的面，且工具级键**不**豁免
     最后一轮崩溃守卫（`_last_round_error_verdict`）—— 新键不得自带假绿口子。

语料形态逐字对齐服务端（`app/agents/customer_service_agent.py` 从 ToolMessage 的
`json.loads(content)` 取 `result_dict` → `app/api/sse.py` 的 `SSEEvent.tool_result`），
不发真实 LLM 请求（#4262：确定性层自证即可）。
"""
# case_ids: OR-030
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"

BLOCKED_CODE = "validation_failed_write_blocked"
TOOL_MARK = f"tool.error.code={BLOCKED_CODE}"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_tool_err", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


def blocked_write_round() -> dict:
    """一轮「写工具因 validate_input 失败被拦」的轨迹（服务端字段逐字）。

    `event: tool_result` 的 data = `{"tool": "order_create", "result": {"success": false,
    "error": "validation_failed_write_blocked", "message": …, "suggestion": …}}`；
    同一轮**没有**轮级 `event: error`（`result["error"]` 为 None）—— 这正是改前取不到的原因。
    """
    return {
        "__round": 2,
        "__all_tool_names": ["validate_input", "order_create"],
        "user_message": "别再校验了，就按这个号直接建单",
        "tool_calls": [
            {"name": "validate_input",
             "args": {"target_tool": "order_create", "target_action": "create"}},
            {"name": "order_create", "args": {"customer_phone": "05718886666"}},
        ],
        "tool_results": [
            {"tool": "validate_input",
             "result": {"success": False, "error": "VALIDATION_FAILED",
                        "message": "手机号格式不正确"}},
            {"tool": "order_create",
             "result": {"success": False, "error": BLOCKED_CODE,
                        "message": "参数校验未通过，已阻止写入",
                        "suggestion": "先补齐参数 → 重新调用 validate_input → 再调用 order_create"}},
        ],
        "final_text": "号码不是 11 位手机号，请改正后我再帮您下单",
        "error": None,
    }


def success_write_round() -> dict:
    """一轮**正常成功**的写轨迹（工具有 `success: true`）—— 反证用（②）。"""
    return {
        "__round": 3,
        "__all_tool_names": ["validate_input", "order_create"],
        "user_message": "确认，号码改成 13800138000",
        "tool_calls": [
            {"name": "order_create", "args": {"customer_phone": "13800138000"}},
        ],
        "tool_results": [
            {"tool": "order_create",
             "result": {"success": True, "data": {"order_no": "SO-20260925-0001"}}},
        ],
        "final_text": "已下单成功",
        "error": None,
    }


def round_level_only_round() -> dict:
    """一轮**只有轮级 error**、工具全成功的语料（判别力自证用，③）。

    轮级 error 的形态逐字对齐 `SSEEvent.error(message)`（`app/api/sse.py`）：
    payload = `{"message": …}`，runner 侧以 `str(payload)` 落进 `result["error"]`。
    """
    return {
        "__round": 1,
        "__all_tool_names": ["product_detail"],
        "user_message": "看看 2699 系列",
        "tool_calls": [{"name": "product_detail", "args": {"name": "2699"}}],
        "tool_results": [
            {"tool": "product_detail",
             "result": {"success": True, "data": {"name": "2699"}}},
        ],
        "final_text": "",
        "error": str({"message": "刚才这轮没成功，请您再说一次，我继续为您办理。"}),
    }


class TestToolLevelErrorCodeIsAssertable:
    """①/③/④：工具级 error code 可取到、且只在工具失败时取到。"""

    def test_blocked_write_round_yields_the_code(self):
        """红证①：拦写轨迹 ⇒ `tool.error.code=validation_failed_write_blocked` 成立。"""
        ok, detail = lr.check_expectation(blocked_write_round(), TOOL_MARK)
        assert ok is True, f"工具级 error code 取不到（S2 闸门无直接判据）：{detail}"
        assert BLOCKED_CODE in detail, detail

    def test_success_round_does_not_yield_the_code(self):
        """红证②：正常成功轮 ⇒ 同一条断言**不**成立（防"总有错"式放宽）。"""
        rnd = success_write_round()
        ok, detail = lr.check_expectation(rnd, TOOL_MARK)
        assert ok is False, f"成功轮被判命中该 code ⇒ 判据空转：{detail}"
        assert lr._tool_error_codes(rnd) == [], lr._tool_error_codes(rnd)

    def test_round_level_only_corpus_is_a_violation(self):
        """红证③：只有轮级 error、无工具级 error ⇒ 同一校验函数必须报违规。"""
        rnd = round_level_only_round()
        ok, detail = lr.check_expectation(rnd, TOOL_MARK)
        assert ok is False, f"轮级 error 被当成工具级证据（判据空转）：{detail}"
        assert "no tool failure" in detail, detail

    def test_other_tool_error_code_does_not_satisfy(self):
        """只认**该**码：另一个码（拦的是别的东西）不得被判命中。"""
        ok, detail = lr.check_expectation(blocked_write_round(),
                                          "tool.error.code=PERMISSION_DENIED")
        assert ok is False, f"别的码也判命中 ⇒ 值级判别力丢失：{detail}"
        assert BLOCKED_CODE in detail, f"失败详情未给出实际观测到的码：{detail}"

    def test_round_level_marker_does_not_accept_tool_level_code(self):
        """④ 两条口径互不吞：轮级 `error.code=` 不因工具级失败而成立。"""
        ok, _ = lr.check_expectation(blocked_write_round(), f"error.code={BLOCKED_CODE}")
        assert ok is False, "轮级标记被工具级结果满足 ⇒ 两条口径已合并（双口径漂移）"

    def test_tool_result_status_carries_the_code(self):
        """取数层证据：`_tool_result_status` 已把 `result.error` 解析成 `st['error']`。"""
        rnd = blocked_write_round()
        codes = [st["error"] for st in
                 lr._tool_result_status(rnd["tool_results"], rnd["tool_calls"])]
        assert BLOCKED_CODE in codes, codes


class TestToolKeyDoesNotWeakenExistingGuards:
    """④：新键不得削弱既有守卫（最后一轮崩溃守卫逐字不变）。"""

    def test_tool_scoped_marker_does_not_exempt_last_round_crash(self):
        """工具级键不构成"轮级崩溃已被预期" ⇒ 最后一轮崩溃仍判失败。"""
        results = [blocked_write_round(), {"error": "boom", "tool_calls": [],
                                           "tool_results": [], "final_text": ""}]
        verdict = lr._last_round_error_verdict(results, [TOOL_MARK], [TOOL_MARK])
        assert "最后轮报错" in (verdict or ""), (
            f"工具级键豁免了最后一轮崩溃守卫 ⇒ 新键自带假绿口子：{verdict!r}")

    def test_round_level_marker_still_exempts_last_round_crash(self):
        """轮级 `error.code=` 的豁免语义一字未动（既有用例结论不变）。

        两半：带轮级标记 ⇒ 守卫**不**报（豁免仍在）；同一语料去掉标记 ⇒ 守卫必须报
        「最后轮报错」（证明上一半的"不报"来自豁免、不是守卫本身失效）。
        """
        results = [{"error": None, "tool_calls": [], "tool_results": [], "final_text": ""},
                   {"error": "error.code=NOT_FOUND", "tool_calls": [],
                    "tool_results": [], "final_text": ""}]
        assert lr._last_round_error_verdict(results, ["error.code=NOT_FOUND"], []) is None
        verdict = lr._last_round_error_verdict(results, [], [])
        assert "最后轮报错" in verdict, f"守卫本身失效（判据恒不报）：{verdict!r}"

    def test_suggestion_marker_still_exempts_last_round_crash(self):
        """suggestion 标记的豁免语义一字未动。"""
        results = [{"error": "suggestion returned", "tool_calls": [],
                    "tool_results": [], "final_text": ""}]
        assert lr._last_round_error_verdict(results, ["suggestion 非空"], []) is None
        assert "最后轮报错" in lr._last_round_error_verdict(results, ["tool: product_search"], [])


class TestToolKeyRidesExistingScoringFace:
    """计分面：新键**沿用**既有机器计分口径，不新造第二套。"""

    def test_prefix_contains_existing_scorer_marker(self):
        """键名含 `error.code=` 子串 = 它落进既有白名单的**唯一机制**。

        改键名（如 `tool_error_code=`）会静默掉出白名单与 taxonomy 口径（
        `tests/unit_ci_workflows/test_case_trust_gate.py` 的
        `test_machine_scored_marker_matches_runner_source` 按子串核）⇒ 本断言先红。
        """
        assert "error.code=" in TOOL_MARK, TOOL_MARK
        assert lr.TOOL_ERROR_CODE_PREFIX == "tool.error.code=", lr.TOOL_ERROR_CODE_PREFIX

    def test_scoring_check_is_failable(self):
        """可失败性：该键属机器可证伪断言（不是"恒绿"的存在性断言）。"""
        assert lr._scoring_check_is_failable(TOOL_MARK) is True

    def test_failure_atom_is_its_own_family(self):
        """归因原子分族：工具级失败不得与轮级 `error_code_expected` 同形。"""
        atom = lr._failure_atom(TOOL_MARK, f"expected tool error {BLOCKED_CODE} but got []")
        assert atom == f"tool_error_code_expected({BLOCKED_CODE})", atom