"""Agent Eval runner 真实验收守卫单测（tests/agent_eval/local_runner.py）

覆盖 _last_round_error_verdict：最后一轮 error 且用例未预期错误 → 判失败。
背景（issue #2887 验收复盘）：expectations 是「任意一轮命中即过」，clearing 卡后
发图轮报错时，前面轮次可能已命中 success=true / tool 等 expectation，
旧逻辑把用例计为通过（假验收 —— 线上 sess_806703a2dcca4059 图片崩溃正是此类）。
"""
# case_ids: CH-021, CH-026, OR-001, PR-001, DA-002, PP-003, PP-004, AS-001, AS-002
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


class TestLastRoundErrorVerdict:
    """最后一轮报错守卫（真实验收假阳性防线）"""

    def test_last_round_error_with_success_expectation_fails(self):
        """假验收回归：前面轮次命中 success=true，最后一轮（发图轮）报错 → 必须判失败。"""
        results = [
            {"error": None},
            {"error":  "抱歉，遇到问题: AttributeError: 'list' object has no attribute 'strip'"},
        ]
        verdict = lr._last_round_error_verdict(results, ["success=true"], [])
        assert verdict and "最后轮报错" in verdict

    def test_last_round_error_no_expectation_fails(self):
        results = [{"error": None}, {"error": "boom"}]
        assert lr._last_round_error_verdict(results, ["tool: product_search"], []) is not None

    def test_clean_last_round_passes(self):
        results = [{"error": None}, {"error": None}]
        assert lr._last_round_error_verdict(results, ["tool: product_search"], []) is None

    def test_mid_round_error_recovered_pass(self):
        """错误发生在中间轮、最后一轮正常 → 不影响（用例终点是干净的）。"""
        results = [{"error": "transient"}, {"error": None}]
        assert lr._last_round_error_verdict(results, [], []) is None

    def test_empty_results_passes(self):
        assert lr._last_round_error_verdict([], [], []) is None

    def test_expectation_error_code_exempts(self):
        """用例显式预期 error.code= → 不硬判失败（对抗用例 E001 类）。"""
        results = [{"error": None}, {"error": "error.code=NOT_FOUND"}]
        verdict = lr._last_round_error_verdict(
            results, ["tool: product_detail"], ["error.code=NOT_FOUND"]
        )
        assert not verdict

    def test_data_checks_suggestion_exempts(self):
        results = [{"error": None}, {"error": "suggestion returned"}]
        assert lr._last_round_error_verdict(
            results, ["tool: product_search"], ["suggestion 非空且包含 product_search"]
        ) is None


class TestFailureSignature:
    """失败指纹：判断两次失败是否同根因（波动分类基础）"""

    def test_same_failures_same_signature(self):
        a = {"failed": [("tool: order_create", "unmatched")], "last_error": None}
        b = {"failed": [("tool: order_create", "unmatched")], "last_error": None}
        assert lr._failure_signature(a) == lr._failure_signature(b)

    def test_signature_is_order_independent(self):
        a = {"failed": [("x", "1"), ("y", "2")], "last_error": None}
        b = {"failed": [("y", "2"), ("x", "1")], "last_error": None}
        assert lr._failure_signature(a) == lr._failure_signature(b)

    def test_different_failures_different_signature(self):
        a = {"failed": [("tool: product_search", "unmatched")], "last_error": None}
        b = {"failed": [("tool: order_query", "unmatched")], "last_error": None}
        assert lr._failure_signature(a) != lr._failure_signature(b)

    def test_error_included_in_signature(self):
        a = {"failed": [], "last_error": "AttributeError: 'list' object ..."}
        b = {"failed": [], "last_error": "KeyError: 'x'"}
        assert lr._failure_signature(a) != lr._failure_signature(b)


class TestClassifyAttempts:
    """波动分类（issue #2890）：噪声放行 / 复现型 block / 不稳定标注 / infra 区分"""

    def _r(self, score, failed=None, last_error=None):
        return {"score": score, "failed": failed or [], "last_error": last_error}

    def test_first_pass_is_pass(self):
        assert lr._classify_attempts(self._r(1.0), self._r(0.0)) == "pass"

    def test_second_pass_is_llm_noise(self):
        """首次失败 + 新 session 重试通过 → 噪声，自动放行（记台账）。"""
        first = self._r(0.5, [("tool: product_search", "unmatched")])
        second = self._r(1.0)
        assert lr._classify_attempts(first, second) == "llm-noise"

    def test_same_signature_twice_is_reproducible(self):
        """两次同指纹失败 → 确定性回归，禁止 rerun 掩盖。"""
        f = [("tool: order_create", "unmatched")]
        first = self._r(0.5, f)
        second = self._r(0.0, f)
        assert lr._classify_attempts(first, second) == "reproducible"

    def test_different_signature_twice_is_unstable(self):
        first = self._r(0.5, [("tool: A", "x")])
        second = self._r(0.0, [("tool: B", "y")])
        assert lr._classify_attempts(first, second) == "unstable"

    def test_infra_error_classified(self):
        first = self._r(0.0)
        second = self._r(0.0, last_error="All connection attempts failed (ConnectError)")
        assert lr._classify_attempts(first, second) == "infra"

    def test_infra_marker_detection(self):
        assert lr._is_infra_error("httpx.ConnectError: connection refused")
        assert lr._is_infra_error("timeout after 120s")
        assert lr._is_infra_error("Internal Server Error")
        assert not lr._is_infra_error("AttributeError: 'list' object has no attribute 'strip'")


class TestExpectationArgsValidation:
    """弱断言加固（issue #2854 P0-3）：check_expectation 支持 'tool(k=v)' 期望的关键字段校验

    背景：旧实现只做工具名子串匹配，args（action/days/item_ids）完全不校验，
    PP-003/PP-004 即使工具名对上、参数传错也不会被发现。
    """

    def _result(self, tool_calls):
        """构造 check_expectation 输入：工具调用列表 + 汇总名"""
        return {
            "tool_calls": tool_calls,
            "__all_tool_names": [tc["name"] for tc in tool_calls],
            "final_text": "",
            "error": None,
        }

    def test_tool_name_only_matches_either(self):
        result = self._result([{"name": "interact", "args": {}}])
        ok, _ = lr.check_expectation(result, "interact")
        assert ok

    def test_args_action_must_match(self):
        """action 关键字段不一致 → 失败（DA-002 指纹：期望 order_trend 实际 order_query）"""
        result = self._result([{"name": "dashboard_stats", "args": {"action": "order_query"}}])
        ok, detail = lr.check_expectation(result, "dashboard_stats(action=order_trend, days=7)")
        assert not ok
        assert "action" in detail

    def test_args_days_must_match(self):
        result = self._result([{"name": "dashboard_stats", "args": {"action": "order_trend", "days": 30}}])
        ok, detail = lr.check_expectation(result, "dashboard_stats(action=order_trend, days=7)")
        assert not ok
        assert "days" in detail

    def test_args_all_match_passes(self):
        result = self._result([{"name": "dashboard_stats", "args": {"action": "order_trend", "days": 7}}])
        ok, _ = lr.check_expectation(result, "dashboard_stats(action=order_trend, days=7)")
        assert ok

    def test_missing_args_for_wrong_tool_fails(self):
        """PP-003 指纹：实际只调 processing_item_query → 无法满足 add 期望"""
        result = self._result([{"name": "processing_item_query", "args": {"action": "list"}}])
        ok, _ = lr.check_expectation(result, "product_processing_item_manage(action=add, item_ids=[打孔])")
        assert not ok

    def test_item_ids_list_check(self):
        """item_ids 列表关键字段：期望 [打孔] 必须出现在实际 args 中"""
        result = self._result([{"name": "product_processing_item_manage", "args": {"action": "add", "item_ids": ["打孔"]}}])
        ok, _ = lr.check_expectation(result, "product_processing_item_manage(action=add, item_ids=[打孔])")
        assert ok

    def test_expectation_plain_tool_still_passes(self):
        """无 args 的期望保持向后兼容（纯工具名匹配）"""
        result = self._result([{"name": "order_query", "args": {}}])
        ok, _ = lr.check_expectation(result, "order_query")
        assert ok

    def test_query_action_synonyms_pass(self):
        """查询类动作枚举宽松（HR-004 回归）：list≈all≈query≈detail 业务等价。

        背景：role_manage 工具 read_only_actions={'list','all','detail',...}，
        LLM 对「系统有哪些角色」调 action=all（合法只读查询）而用例期望 action=list
        —— P0-3 收紧前弱断言放行，收紧后若仍要求字面相等会误伤合法 LLM 行为。
        """
        result = self._result([{"name": "role_manage", "args": {"action": "all"}}])
        ok, detail = lr.check_expectation(result, "role_manage(action=list)")
        assert ok, f"list≈all 应等价，实际 detail={detail}"

    def test_write_action_synonyms_strict(self):
        """写操作枚举保持严格：add≠update，不得被查询等价组放行"""
        result = self._result([{"name": "product_processing_item_manage", "args": {"action": "update"}}])
        ok, _ = lr.check_expectation(result, "product_processing_item_manage(action=add, item_ids=[打孔])")
        assert not ok


class TestRunCaseDataChecksScoring:
    """data_checks 落入评分（issue #2854 P0-3）：success=true 等机器可判定检查计入得分

    背景：旧 run_case 只对 expectations 计分，data_checks 完全不参与评分，
    PP-003/PP-004 的 'success=true' 形同虚设。
    """

    def _full_case(self):
        return lr.EvalCase(
            id="PP-003-TEST",
            legacy_id="",
            title="test",
            skill=lr.Skill.PRODUCT,
            difficulty=lr.Difficulty.NORMAL,
            user_inputs=["给遮光窗帘添加打孔加工"],
            expectations=["product_processing_item_manage(action=add, item_ids=[打孔])"],
            data_checks=["success=true"],
        )

    async def _run(self, case, error=None):
        async def fake_send(token, session_id, message, images=None):
            return {
                "user_message": message,
                "images": images or [],
                "tool_calls": [{"name": "product_processing_item_manage", "args": {"action": "add", "item_ids": ["打孔"]}}],
                "tool_results": [],
                "final_text": "ok",
                "error": error,
                "streamed": False,
                "done": True,
            }
        import unittest.mock as mock
        with mock.patch.object(lr, "send_message", new=fake_send):
            return await lr.run_case(case, "tok", "sess")

    def test_success_datacheck_scores(self):
        import asyncio
        case = self._full_case()
        result = asyncio.run(self._run(case, error=None))
        assert result["score"] == 1.0
        assert result["passed"] == result["total"]

    def test_error_with_success_datacheck_scores_zero(self):
        import asyncio
        case = self._full_case()
        result = asyncio.run(self._run(case, error="boom: 加工项解析失败"))
        # success=true 未满足 → 计为失败
        assert result["score"] < 1.0


class TestWantTextAssertion:
    """final_text 正向关键词断言（acceptance-protocol §3.4 正反关键词双轨）

    背景（2026-09-09）：forbidden_text 只防「说了不该说的」，防不住「该说的没说」——
    写操作完成不声明成果、兜底话术缺「转人工」出口等，工具调用全对但回复不完整，
    旧评测判过。want_text 补正向轨：任一关键词全程未出现 → 违规。
    """

    def _rounds(self, texts):
        return [{"__round": i + 1, "final_text": t, "error": None} for i, t in enumerate(texts)]

    def test_keyword_present_passes(self):
        assert lr.check_want_text(self._rounds(["好的，已为您创建订单，订单号 20260901"]), ["订单号"]) == []

    def test_keyword_missing_fails(self):
        issues = lr.check_want_text(self._rounds(["好的，已完成"]), ["订单号"])
        assert issues and "未出现" in issues[0]

    def test_keyword_in_any_round_passes(self):
        results = self._rounds(["先查一下", "订单已创建成功 ✅"])
        assert lr.check_want_text(results, ["创建成功"]) == []

    def test_multiple_keywords_any_missing_fails(self):
        issues = lr.check_want_text(self._rounds(["转人工请点击下方"]), ["转人工", "人工客服"])
        assert len(issues) == 1

    def test_empty_want_text_passes(self):
        assert lr.check_want_text(self._rounds(["随便说点"]), []) == []

    def test_want_text_wired_into_run_case(self):
        """want_text 缺失 → run_case 整体判失败（接入链路验证）。"""
        import asyncio
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None):
            return {
                "user_message": message,
                "images": images or [],
                "tool_calls": [],
                "tool_results": [],
                "final_text": "好的，处理完了",
                "error": None,
                "streamed": False,
                "done": True,
            }

        case = lr.EvalCase(
            id="WT-TEST", legacy_id="", title="test", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL,
            user_inputs=["帮我处理下"],
            expectations=["direct_reply"],
            data_checks=[],
            want_text=["订单号"],
        )
        with mock.patch.object(lr, "send_message", new=fake_send):
            result = asyncio.run(lr.run_case(case, "tok", "sess"))
        assert result["score"] == 0.0
        assert any("want_text" in e for e, _ in result["failed"])


class TestJsonParseDefense:
    """评测基础设施健壮性：非 JSON 响应（限流/瞬断/400 HTML）不得中断整个评测。

    背景（2026-09-09 实测）：对生产跑 normal 全量评测时，中途某次
    snapshot_product 的 GET /api/admin/products 返回非 JSON（瞬时限流/HTML），
    r.json() 抛 JSONDecodeError → 整个评测崩溃退出，后续用例全部未跑——
    评测基础设施的不健壮会让"能力基线"拿不到，比单个用例失败更伤。
    """

    def test_safe_json_valid(self):
        """合法 JSON → 正常解析。"""
        class FakeResp:
            def __init__(self, content):
                import json as _json
                self.content = _json.dumps(content).encode()
        assert lr._safe_json(FakeResp({"success": True}), {}) == {"success": True}

    def test_safe_json_non_json_returns_default(self):
        """非 JSON 内容（HTML 错误页）→ 返回默认值，不抛异常。"""
        class FakeResp:
            content = b"<!doctype html><html>Bad Request</html>"
        assert lr._safe_json(FakeResp(), {}) == {}

    def test_safe_json_empty_returns_default(self):
        """空响应体 → 返回默认值。"""
        class FakeResp:
            content = b""
        assert lr._safe_json(FakeResp(), {"data": []}) == {"data": []}

    def test_snapshot_product_non_json_no_crash(self):
        """snapshot_product 遇到非 JSON 响应 → 返回 None（跳过快照），不崩评测。

        实测崩溃（2026-09-09）：normal 全量跑到中途某用例触发 snapshot_product，
        响应为 400 HTML → JSONDecodeError 中断整个评测（CR-003 类 infra 干扰放大）。
        """
        import unittest.mock as mock

        class FakeResp:
            status_code = 400
            content = b"<!doctype html><title>HTTP Status 400</title>"

            def json(self):
                import json as _json
                raise _json.JSONDecodeError("Expecting value", "x", 0)

        async def fake_get(url, headers=None, params=None):
            return FakeResp()

        with mock.patch.object(lr.httpx, "AsyncClient") as m_cls:
            m_cls.return_value.__aenter__.return_value.get = fake_get
            import asyncio
            pid = asyncio.run(lr.snapshot_product("tok", "遮光窗帘"))
            assert pid is None

    def test_fetch_product_configs_non_json_no_crash(self):
        """_fetch_product_configs 遇到非 JSON → 返回 []（db_verify 视为无配置），不崩。"""
        import unittest.mock as mock

        class FakeResp:
            status_code = 400
            content = b"<!doctype html><title>HTTP Status 400</title>"

            def json(self):
                import json as _json
                raise _json.JSONDecodeError("Expecting value", "x", 0)

        async def fake_get(url, headers=None, params=None, timeout=None):
            return FakeResp()

        with mock.patch.object(lr.httpx, "AsyncClient") as m_cls:
            m_cls.return_value.__aenter__.return_value.get = fake_get
            import asyncio
            configs = asyncio.run(lr._fetch_product_configs("tok", "遮光窗帘"))
            assert configs == []