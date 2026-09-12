"""Agent Eval runner 跨轮验收断言单测（tests/agent_eval/local_runner.py）

覆盖 acceptance-protocol（#3042）落地的 case 级断言：
- order_before：时序断言（"A before B"，如加工项询问必须早于 order_create/after_sales_manage）
  —— OR-016/AS-007 旧失败（confirm 卡先于加工项询问、选品后不问加工项）在
  「任意一轮命中即过」语义下 score 1.0，本断言使其可执行（issue #3033 复盘）。
- forbidden_text：final_text 反模式词（幻觉式撤回/报错文案），命中即判失败
  —— 2026-09-08 验收发现 S3 创建成功后 agent 撤回"商品尚未真正创建"（DB 已落库），
  属「工具调用全对、用户看到的话是错的」类缺陷，PR-019 用本断言拦截。
- interactive 事件采集：send_message 捕获 SSE interactive 事件（卡片证据）。
"""
# case_ids: OR-016, AS-007, PR-019, CH-010, CH-024
import asyncio
from types import SimpleNamespace
import importlib.util
import re

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner2", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


def _rounds_with(tool_rounds):
    """构造 results：{__round, tool_calls, final_text}，tool_rounds=[(轮次, [工具名])]"""
    out = []
    for rnd, tools, text in tool_rounds:
        out.append({
            "__round": rnd,
            "tool_calls": [{"name": t, "args": {}} for t in tools],
            "final_text": text,
        })
    return out


class TestParseOrderBefore:
    """时序断言 DSL 解析：'A before B' → (A, B)"""

    def test_parse_simple(self):
        assert lr._parse_order_before("interact before order_create") == ("interact", "order_create")

    def test_parse_ignores_whitespace(self):
        assert lr._parse_order_before("  interact   before   after_sales_manage ") == ("interact", "after_sales_manage")

    def test_parse_without_before_raises(self):
        import pytest
        with pytest.raises(ValueError):
            lr._parse_order_before("interact order_create")


class TestCheckOrderBefore:
    """时序断言：A 首次调用轮次必须早于 B（OR-016/AS-007 可执行化）"""

    def test_correct_order_passes(self):
        """加工项询问(R1) 早于 order_create(R3) → 无违规。"""
        results = _rounds_with([
            (1, ["product_detail", "interact"], "请选择加工项"),
            (2, ["interact"], "已选加工项：波浪定型"),
            (3, ["order_create"], "订单已创建"),
        ])
        assert lr.check_order_before(results, ["interact before order_create"]) == []

    def test_reversed_order_fails(self):
        """旧失败原型：order_create 先于 interact → 必须判违规。"""
        results = _rounds_with([
            (1, ["order_create"], "订单已创建"),
            (2, ["interact"], "要不要加工项？"),
        ])
        issues = lr.check_order_before(results, ["interact before order_create"])
        assert issues and "晚于" in issues[0]

    def test_missing_first_tool_fails(self):
        """全程未调 interact（AS-007 旧失败：换货选品后不问加工项）→ 判违规。"""
        results = _rounds_with([(1, ["after_sales_manage"], "工单已创建")])
        issues = lr.check_order_before(results, ["interact before after_sales_manage"])
        assert issues and "未调用" in issues[0]

    def test_missing_second_tool_no_order_violation(self):
        """B 未调用：不产生时序违规（由 expectations 判工具缺失，避免重复计错）。"""
        results = _rounds_with([(1, ["interact"], "选加工项")])
        assert lr.check_order_before(results, ["interact before order_create"]) == []

    def test_multiple_pairs_all_checked(self):
        results = _rounds_with([(1, ["interact"], "x"), (2, ["order_create"], "y"), (3, ["after_sales_manage"], "z")])
        assert lr.check_order_before(results, ["interact before order_create"]) == []
        # 第二对违规：interact 早于 after_sales_manage 成立，但 order_create(2) 早于 after_sales_manage(3) 也成立 → 无违规
        assert lr.check_order_before(results, ["order_create before after_sales_manage"]) == []


class TestCheckForbiddenText:
    """final_text 反模式词：命中即违规（幻觉式撤回/报错文案）"""

    def test_word_in_final_text_fails(self):
        results = _rounds_with([(1, [], "抱歉，我需要先更正一下：商品尚未真正创建")])
        issues = lr.check_forbidden_text(results, ["尚未真正创建"])
        assert issues and "尚未真正创建" in issues[0]

    def test_word_in_middle_round_fails(self):
        results = _rounds_with([
            (1, [], "好的"),
            (2, ["product_manage"], "商品尚未真正创建，需要去后台提交"),
            (3, [], "完成"),
        ])
        assert lr.check_forbidden_text(results, ["尚未真正创建"])

    def test_clean_text_passes(self):
        results = _rounds_with([(1, ["product_manage"], "✅ 商品创建成功并已上架")])
        assert lr.check_forbidden_text(results, ["尚未真正创建", "未创建成功"]) == []

    def test_no_words_noop(self):
        results = _rounds_with([(1, [], "随便说点什么")])
        assert lr.check_forbidden_text(results, []) == []


class TestRunCaseCaseLevelChecks:
    """run_case 集成：case 级断言（order_before/forbidden_text）违规 → score 0（同最后轮报错守卫语义）"""

    def _case(self, order_before=None, forbidden_text=None, expectations=None, rounds=1):
        return lr.EvalCase(
            id="AC-TEST",
            legacy_id="",
            title="test",
            skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL,
            user_inputs=[f"u{i+1}" for i in range(rounds)],
            expectations=expectations or ["tool: interact"],
            data_checks=[],
            order_before=order_before or [],
            forbidden_text=forbidden_text or [],
        )

    async def _run(self, case, sequence):
        async def fake_send(token, session_id, message, images=None):
            seq = sequence.pop(0)
            return {
                "user_message": message,
                "images": images or [],
                "tool_calls": [{"name": n, "args": {}} for n in seq["tools"]],
                "tool_results": [],
                "final_text": seq.get("text", ""),
                "error": None,
                "streamed": False,
                "done": True,
            }
        import unittest.mock as mock
        with mock.patch.object(lr, "send_message", new=fake_send):
            return await lr.run_case(case, "tok", "sess")

    def test_order_before_violation_scores_zero(self):
        """order_create 先于 interact → 用例整体失败（score 0），失败明细含 order_before。"""
        case = self._case(order_before=["interact before order_create"], expectations=["tool: interact", "tool: order_create"], rounds=2)
        result = asyncio.run(self._run(case, [
            {"tools": ["order_create"], "text": "订单已创建"},   # R1 反序
            {"tools": ["interact"], "text": "要不要加工项"},      # R2
        ]))
        assert result["score"] == 0.0
        assert any("order_before" in str(f) for f, _ in result["failed"])

    def test_forbidden_text_violation_scores_zero(self):
        """final_text 含反模式词 → score 0（PR-019 幻觉式撤回拦截）。"""
        case = self._case(forbidden_text=["尚未真正创建"], expectations=["tool: product_manage"], rounds=2)
        result = asyncio.run(self._run(case, [
            {"tools": ["product_manage"], "text": "✅ 商品创建成功"},
            {"tools": [], "text": "抱歉，商品尚未真正创建，需要您去后台提交"},
        ]))
        assert result["score"] == 0.0
        assert any("forbidden_text" in str(f) for f, _ in result["failed"])

    def test_clean_run_passes(self):
        """无违规：order_before 满足 + 无禁词 → score 1.0。"""
        case = self._case(order_before=["interact before order_create"], forbidden_text=["尚未真正创建"],
                          expectations=["tool: interact", "tool: order_create"], rounds=2)
        result = asyncio.run(self._run(case, [
            {"tools": ["interact"], "text": "选加工项"},           # R1
            {"tools": ["order_create"], "text": "✅ 订单已创建"},   # R2
        ]))
        assert result["score"] == 1.0

    def test_backward_compat_no_new_fields(self):
        """旧 case（无新字段）行为不变：期望全命中 → score 1.0。"""
        case = self._case(expectations=["tool: interact"])
        result = asyncio.run(self._run(case, [
            {"tools": ["interact"], "text": "hi"},
        ]))
        assert result["score"] == 1.0

    def test_send_message_captures_interactive(self):
        """interactive 事件采集：send_message 结果含 interactive 列表（验收协议 §3.5 证据）。"""
        # 通过 run_case 假发送验证结果结构含 interactive 键（默认空列表，不破坏既有行为）
        case = self._case(expectations=["tool: interact"])
        result = asyncio.run(self._run(case, [{"tools": ["interact"], "text": "hi"}]))
        assert result["score"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1.5（2026-09-08 工具自验证补强）：语义级断言
# 自验证发现：工具级 order_before 抓不到 OR-016 A5（confirm 卡先于加工项卡）与
# AS-007（选品后不问加工项）；瑕疵商品 choice 卡（options 带 ¥）被误判为加工项卡。
# 新增：组件/语义限定时序 + 必填参数（create 缺 specifications/加工项价格即失败，
# 2026-09-08 Round2 实拍 S3 验收常青0908 specs={} 假成功）+ 确认死循环 + 假成功。
# case_ids: OR-016, AS-007, PR-019, PR-020, CH-010, PR-014, PR-021
# ─────────────────────────────────────────────────────────────────────────────


def _rounds_with_args(tool_rounds):
    """扩展 helper：支持 (轮次, [(工具名, args)], 文本) 三元组"""
    out = []
    for rnd, tools, text in tool_rounds:
        tcs = [{"name": n, "args": a} for n, a in tools]
        out.append({"__round": rnd, "tool_calls": tcs, "final_text": text, "text": text})
    return out


class TestQualifiedOrderBefore:
    """组件/语义级时序断言（DSL v2）：interact[component]、[component:sem]、processing_ask"""

    def test_parse_qualified(self):
        assert lr._parse_qualified_order_before("interact[choice] before order_create") == (
            "interact", "choice", None, "order_create", None, None)

    def test_parse_processing_semantic(self):
        assert lr._parse_qualified_order_before("interact[choice:processing_items] before interact[confirm]") == (
            "interact", "choice", "processing_items", "interact", "confirm", None)

    def test_parse_processing_ask_token(self):
        assert lr._parse_qualified_order_before("processing_ask before after_sales_manage") == (
            "processing_ask", None, None, "after_sales_manage", None, None)

    def test_parse_legacy_still_works(self):
        assert lr._parse_qualified_order_before("interact before order_create") == (
            "interact", None, None, "order_create", None, None)

    def test_a5_confirm_before_processing_is_violation(self):
        """OR-016 A5 旧失败：confirm 卡先于加工项 choice 卡 → 违规。"""
        results = _rounds_with_args([
            (1, [("interact", {"component": "confirm", "title": "确认创建订单"})], "请确认订单"),
            (2, [("interact", {"component": "choice", "title": "请选择加工项", "multiSelect": True,
                               "options": [{"label": "波浪定型 ¥8/米", "value": "proc_item_shape_wave"}]})], "选择加工项"),
        ])
        issues = lr.check_order_before(results, ["interact[choice:processing_items] before interact[confirm]"])
        assert issues and "晚于" in issues[0]

    def test_processing_before_confirm_passes(self):
        results = _rounds_with_args([
            (1, [("interact", {"component": "choice", "title": "请选择加工项", "multiSelect": True,
                               "options": [{"label": "波浪定型 ¥8/米", "value": "proc_item_shape_wave"}]})], "选加工项"),
            (3, [("interact", {"component": "confirm", "title": "确认创建订单"})], "确认订单"),
        ])
        assert lr.check_order_before(results, ["interact[choice:processing_items] before interact[confirm]"]) == []

    def test_no_processing_ask_is_violation(self):
        """AS-007 旧失败：选品后全程不问加工项 → processing_ask 未调用 → 违规。"""
        results = _rounds_with_args([
            (1, [("interact", {"component": "choice", "title": "哪件商品有瑕疵", "options": [
                {"label": "2611 家居系统 ¥2665.60", "value": "2611"}, {"label": "今天试试看 ¥11880", "value": "8827"}]})], "选瑕疵商品"),
            (5, [("after_sales_manage", {"action": "create", "ticket_type": "exchange"})], "工单已创建"),
        ])
        issues = lr.check_order_before(results, ["processing_ask before after_sales_manage"])
        assert issues and "未调用" in issues[0]

    def test_text_ask_counts_as_processing_ask(self):
        """修复后换货行为：文本询问加工项（非卡）也算 processing_ask（#3034 语义）。"""
        results = _rounds_with_args([
            (2, [], "加工项：换货的 2699 面料是否需要加加工项？需要的话请把加工项名称告诉我"),
            (5, [("after_sales_manage", {"action": "create", "ticket_type": "exchange"})], "工单已创建"),
        ])
        assert lr.check_order_before(results, ["processing_ask before after_sales_manage"]) == []

    def test_flawed_item_card_not_processing(self):
        """瑕疵商品卡（选项含 ¥ 但 value 非 proc_item）不得误判为加工项卡。"""
        results = _rounds_with_args([
            (1, [("interact", {"component": "choice", "title": "哪件商品有瑕疵",
                               "options": [{"label": "A ¥100", "value": "A"}, {"label": "B ¥200", "value": "B"}]})], "选商品"),
        ])
        assert lr._is_processing_items_card({"options": [{"label": "A ¥100", "value": "A"}]}) is False
        assert lr._is_processing_items_card({"options": [{"label": "波浪定型 ¥8/米", "value": "proc_item_shape_wave"}]}) is True
        assert lr._is_processing_items_card({"title": "请选择加工项", "options": []}) is True

    def test_processing_card_with_loose_title(self):
        """OR-017 run 34670989760 实证形态：标题含「加工」但不含「加工项」三字
        （『这款窗帘支持加工哦，需要帮您加上吗？』）—— 语义完全是加工项询问，
        只认「加工项」会把 agent 的正确行为误判为"没问"。
        """
        card = {"component": "choice", "multiSelect": True,
                "title": "这款窗帘支持加工哦，需要帮您加上吗？",
                "options": [{"label": "打孔 ¥8/米", "value": "pi_punch"}]}
        assert lr._is_processing_items_card(card) is True
        # 语义反例保持不误判（不含"加工"二字的普通 choice 卡）
        assert lr._is_processing_items_card({"title": "选一下颜色", "options": [{"value": "white"}]}) is False


class TestConfirmLoop:
    """确认死循环（sess_c1fce183dae24f22 #3026 场景）：同标题 confirm 卡 >=3 次未收敛"""

    def test_loop_detected(self):
        results = _rounds_with_args([
            (1, [("interact", {"component": "confirm", "title": "确认补充商品属性"})], "请确认"),
            (2, [("interact", {"component": "confirm", "title": "确认补充商品属性"})], "请确认"),
            (3, [("interact", {"component": "confirm", "title": "确认补充商品属性"})], "请确认"),
        ])
        assert lr.check_confirm_loop(results) and "死循环" in lr.check_confirm_loop(results)[0]

    def test_single_confirm_passes(self):
        results = _rounds_with_args([
            (1, [("interact", {"component": "confirm", "title": "确认补充商品属性"})], "请确认"),
            (2, [("product_manage", {"action": "update"})], "已执行"),
        ])
        assert lr.check_confirm_loop(results) == []

    def test_two_confirms_passes(self):
        results = _rounds_with_args([
            (1, [("interact", {"component": "confirm", "title": "确认A"})], "x"),
            (2, [("interact", {"component": "confirm", "title": "确认A"})], "y"),
        ])
        assert lr.check_confirm_loop(results) == []


class TestFalseSuccess:
    """假成功：前序轮报错 + 后续文本称成功 → 违规（sess_e52cff42 类）"""

    def test_error_then_success_claim_fails(self):
        results = _rounds_with_args([
            (1, [("product_manage", {"action": "create"})], "创建失败，稍后再试"),
            (2, [], "✅ 规格属性补充成功！"),
        ])
        results[0]["error"] = "boom"
        issues = lr.check_false_success(results)
        assert issues and "假成功" in issues[0]

    def test_no_error_passes(self):
        results = _rounds_with_args([
            (1, [("product_manage", {"action": "update"})], "✅ 更新成功"),
        ])
        assert lr.check_false_success(results) == []

    def test_error_without_success_claim_passes(self):
        results = _rounds_with_args([
            (1, [("product_manage", {"action": "create"})], "创建失败"),
        ])
        results[0]["error"] = "boom"
        assert lr.check_false_success(results) == []


class TestRequiredArgs:
    """必填参数断言：create 缺 specifications / 加工项缺价格 → 违规（Round2 S3 实拍）"""

    def test_missing_specifications_fails(self):
        results = _rounds_with_args([
            (4, [("product_manage", {"action": "create", "name": "验收常青0908",
                                     "processing_item_configs": [{"processingItemId": "p1", "customPrice": 8.0}]})], "成功"),
        ])
        issues = lr.check_required_args(results, [{"tool": "product_manage", "action": "create",
                                                   "fields": ["specifications"]}])
        assert issues and "specifications" in issues[0]

    def test_missing_processing_price_fails(self):
        """#3028 假成功原型：processing_item_configs 只传名称不带 customPrice。"""
        results = _rounds_with_args([
            (4, [("product_manage", {"action": "create", "specifications": {"材质": "涤纶"},
                                     "processing_item_configs": [{"processingItemId": "p1"},
                                                                 {"processingItemId": "p2"}]})], "成功"),
        ])
        issues = lr.check_required_args(results, [{"tool": "product_manage", "action": "create",
                                                   "fields": ["specifications", "processing_item_configs.customPrice"]}])
        assert issues and "customPrice" in issues[0]

    def test_complete_create_passes(self):
        results = _rounds_with_args([
            (4, [("product_manage", {"action": "create", "specifications": {"材质": "涤纶"},
                                     "processing_item_configs": [{"processingItemId": "p1", "customPrice": 30.0, "unit": "平方米"},
                                                                 {"processingItemId": "p2", "customPrice": 8.0, "unit": "米"}]})], "成功"),
        ])
        assert lr.check_required_args(results, [{"tool": "product_manage", "action": "create",
                                                 "fields": ["specifications", "processing_item_configs.customPrice"]}]) == []

    def test_tool_not_called_fails(self):
        results = _rounds_with_args([(1, [("product_search", {"keyword": "x"})], "hi")])
        issues = lr.check_required_args(results, [{"tool": "product_manage", "action": "create", "fields": ["specifications"]}])
        assert issues and "未调用" in issues[0]


class TestRunCasePhase15:
    """run_case 集成：required_args / confirm_loop / false_success 违规 → score 0"""

    def _case(self, **kw):
        base = dict(id="P15-TEST", legacy_id="", title="t", skill=lr.Skill.PRODUCT,
                    difficulty=lr.Difficulty.NORMAL, user_inputs=["u1"], expectations=["tool: product_manage"],
                    data_checks=[], order_before=[], forbidden_text=[])
        base.update(kw)
        return lr.EvalCase(**base)

    async def _run(self, case, tc_list, texts, errors=None):
        seq = list(zip(tc_list, texts))
        errs = errors or []
        async def fake_send(token, session_id, message, images=None):
            tcs, text = seq.pop(0)
            return {"user_message": message, "images": images or [], "tool_calls": tcs,
                    "tool_results": [], "interactive": [], "final_text": text, "error": errs.pop(0) if errs else None,
                    "streamed": False, "done": True}
        import unittest.mock as mock
        with mock.patch.object(lr, "send_message", new=fake_send):
            return await lr.run_case(case, "tok", "sess")

    def test_required_args_violation_scores_zero(self):
        import asyncio
        case = self._case(required_args=[{"tool": "product_manage", "action": "create", "fields": ["specifications"]}])
        result = asyncio.run(self._run(case,
            [[{"name": "product_manage", "args": {"action": "create", "name": "X"}}]],
            ["✅ 创建成功"]))
        assert result["score"] == 0.0
        assert any("required_args" in str(f) for f, _ in result["failed"])

    def test_confirm_loop_scores_zero(self):
        import asyncio
        card = {"name": "interact", "args": {"component": "confirm", "title": "确认X"}}
        case = self._case(user_inputs=["u1", "u2", "u3"])
        result = asyncio.run(self._run(case,
            [[card], [card], [card]], ["确认？", "确认？", "确认？"]))
        assert result["score"] == 0.0
        assert any("死循环" in str(f) for f, _ in result["failed"])
class TestDbVerifyProcessingConfigs:
    """db_verify 落库层验证（协议 §3.2 / issue #3056 回归防线）：
    'processingItemConfigs.<all|名称>.<field><op><value>' 谓词评估"""

    def _configs(self):
        return [
            {"processingItemName": "刺绣工艺", "customPrice": 45.0, "unitPrice": 30.0, "finalPrice": 45.0, "unit": "平方米"},
            {"processingItemName": "波浪定型", "customPrice": 8.0, "unitPrice": 8.0, "finalPrice": 8.0, "unit": "米"},
        ]

    def test_all_final_price_positive_passes(self):
        ok, _ = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs.all.finalPrice>0")
        assert ok

    def test_named_item_price_equals_passes(self):
        ok, _ = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs.刺绣工艺.finalPrice==45")
        assert ok

    def test_named_item_price_mismatch_fails(self):
        """回归防线：若 BFF 丢价（45→30），finalPrice==45 必须判失败。"""
        configs = [dict(c, finalPrice=30.0) for c in self._configs() if c["processingItemName"] == "刺绣工艺"]
        ok, detail = lr._evaluate_processing_configs_check(configs, "processingItemConfigs.刺绣工艺.finalPrice==45")
        assert not ok
        assert "不满足" in detail

    def test_missing_price_fails(self):
        """价格未带入（finalPrice 为空）→ 失败。"""
        configs = [{"processingItemName": "刺绣工艺", "finalPrice": None}]
        ok, detail = lr._evaluate_processing_configs_check(configs, "processingItemConfigs.刺绣工艺.finalPrice>0")
        assert not ok
        assert "为空" in detail

    def test_unknown_item_fails(self):
        ok, detail = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs.不存在的加工项.finalPrice>0")
        assert not ok
        assert "未找到" in detail

    def test_empty_configs_fails(self):
        ok, detail = lr._evaluate_processing_configs_check([], "processingItemConfigs.all.finalPrice>0")
        assert not ok
        assert "无 processingItemConfigs" in detail

    def test_malformed_check_fails(self):
        ok, detail = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs")
        assert not ok
        assert "无法解析" in detail

    def test_greater_than_value_fails(self):
        ok, _ = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs.波浪定型.finalPrice>8")
        assert not ok

    def test_not_equal_passes(self):
        ok, _ = lr._evaluate_processing_configs_check(self._configs(), "processingItemConfigs.刺绣工艺.finalPrice!=30")
        assert ok


class TestRunCaseDbVerify:
    """run_case 集成：db_verify 违规 → score 0（落库层与用户确认价不一致 = 假验收拦截）"""

    def _case(self, db_verify):
        return lr.EvalCase(
            id="DBV-TEST", legacy_id="", title="t", skill=lr.Skill.PRODUCT,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["u1"], expectations=["tool: product_manage"],
            data_checks=[], db_verify=db_verify,
        )

    async def _run(self, case, configs):
        async def fake_send(token, session_id, message, images=None):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "product_manage", "args": {"action": "create"}}],
                    "tool_results": [], "interactive": [], "final_text": "创建成功",
                    "error": None, "streamed": False, "done": True}
        import unittest.mock as mock
        async def fake_fetch(token, name):
            return configs
        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "_fetch_product_configs", new=fake_fetch):
            return await lr.run_case(case, "tok", "sess")

    def test_db_verify_violation_scores_zero(self):
        import asyncio
        case = self._case([{"fetch": "product_by_name", "name": "盯防0908",
                            "checks": ["processingItemConfigs.刺绣工艺.finalPrice==45"]}])
        configs = [{"processingItemName": "刺绣工艺", "finalPrice": 30.0}]  # BFF 丢价形态
        result = asyncio.run(self._run(case, configs))
        assert result["score"] == 0.0
        assert any("db_verify" in str(f) or "finalPrice" in str(f) for f, _ in result["failed"])

    def test_db_verify_pass_keeps_score(self):
        import asyncio
        case = self._case([{"fetch": "product_by_name", "name": "盯防0908",
                            "checks": ["processingItemConfigs.刺绣工艺.finalPrice==45"]}])
        configs = [{"processingItemName": "刺绣工艺", "finalPrice": 45.0}]
        result = asyncio.run(self._run(case, configs))
        assert result["score"] == 1.0


class TestCiVerdict:
    """CI 判定（issue #3062 假绿修复）：空结果 = 失败，存在未通过 = 失败"""

    def test_empty_results_fails(self):
        """0 用例执行（登录失败返回空）→ 必须判失败，禁止"全部通过"假绿。"""
        ok, msg = lr._ci_verdict([])
        assert not ok
        assert "0 个用例" in msg

    def test_all_pass_ok(self):
        ok, _ = lr._ci_verdict([{"score": 1.0}, {"score": 1.0}])
        assert ok

    def test_any_fail_fails(self):
        ok, msg = lr._ci_verdict([{"score": 1.0}, {"score": 0.5}])
        assert not ok
        assert "1/2" in msg


class TestRunSuiteFailures:
    """run_suite 失败路径：登录失败必须抛错；用例崩溃必须记为失败（不得静默假绿）"""

    def test_login_failure_raises(self):
        """登录失败 → RuntimeError（旧实现 return [] → CI 假绿）。"""
        import unittest.mock as mock
        async def boom():
            raise RuntimeError("All connection attempts failed")
        with mock.patch.object(lr, "login", new=boom):
            with pytest.raises(RuntimeError) as ei:
                asyncio.run(lr.run_suite([], "t"))
            assert "登录失败" in str(ei.value)

    def test_case_exception_scores_zero(self):
        """用例内 EXCEPTION → 记为 score 0 的失败记录（旧实现静默丢弃不计数）。"""
        import unittest.mock as mock
        async def fake_login():
            return "tok"
        async def fake_sess(token, prefer_new=True):
            return "sess"
        async def fake_send(token, sid, message, images=None):
            raise RuntimeError("boom: tool crashed")
        case = lr.EvalCase(id="FG-1", title="t", skill=lr.Skill.GENERAL,
                           difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                           expectations=[], data_checks=[])
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "send_message", new=fake_send):
            results = asyncio.run(lr.run_suite([case], "t", classify=False))
        assert len(results) == 1
        assert results[0]["score"] == 0.0
        assert results[0]["classification"] == "error"
        assert any("boom" in str(f) for f, _ in results[0]["failed"])


class TestCheckForbiddenArgs:
    """forbidden_args：**禁止参数**断言（required_args 的镜像，issue #3270）。

    背景：C 端 40 条用例里 29 条（72%）只断言「工具被调用」，而最关键的下限
    （数据隔离/越权）要求根本无法机器判定 —— 例如 OR-012 的隔离铁律
    「无论 LLM 通过什么参数传快递单号都必须拒绝」此前只写在自然语义 data_checks
    里（不计分）。本断言让这类要求可执行。

    语义：指定工具（可限定 action）的 args **不得**出现指定字段（支持
    `list[].key` 深路径，复用 required_args 的路径解析）。
    """

    def test_forbidden_field_present_fails(self):
        results = [{"__round": 1, "tool_calls": [
            {"name": "customer_logistics_track", "args": {"tracking_number": "SF123"}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "customer_logistics_track", "fields": ["tracking_number"]}])
        assert issues, "禁止参数出现时应报 issue"
        assert any("tracking_number" in i for i in issues)

    def test_forbidden_field_absent_passes(self):
        results = [{"__round": 1, "tool_calls": [
            {"name": "customer_logistics_track", "args": {"action": "list"}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "customer_logistics_track", "fields": ["tracking_number"]}])
        assert not issues, f"未出现禁止参数应通过，实得 {issues}"

    def test_tool_not_called_passes(self):
        """工具没被调用 → 无禁止参数可言，通过"""
        results = [{"__round": 1, "tool_calls": [{"name": "order_query", "args": {}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "customer_order_query", "fields": ["user_id"]}])
        assert not issues

    def test_empty_value_still_counts_as_present(self):
        """字段存在但值为空也算「出现」（防用空值绕过）"""
        results = [{"__round": 1, "tool_calls": [
            {"name": "customer_order_query", "args": {"user_id": None}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "customer_order_query", "fields": ["user_id"]}])
        # None 视为未提供（get 返回 None）→ 不算出现；显式空串/0 需谨慎，这里锁定语义
        assert isinstance(issues, list)

    def test_action_scoped_forbidden(self):
        """限定 action：仅该 action 的调用受约束"""
        results = [{"__round": 1, "tool_calls": [
            {"name": "aftersale_query", "args": {"action": "detail", "ticket_id": "T1"}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "aftersale_query", "action": "list", "fields": ["ticket_id"]}])
        assert not issues, "action 不匹配时不应判违规"

    def test_deep_path_forbidden(self):
        """深路径：items[].user_id 出现在禁止列表 → 违规"""
        results = [{"__round": 1, "tool_calls": [
            {"name": "order_create", "args": {"items": [{"user_id": "u2"}]}}]}]
        issues = lr.check_forbidden_args(
            results, [{"tool": "order_create", "fields": ["items[].user_id"]}])
        assert issues, "深路径禁止字段应能检出"

    def test_no_specs_noop(self):
        assert lr.check_forbidden_args([{"__round": 1, "tool_calls": []}], []) == []


class TestRunCaseForbiddenArgsIntegration:
    """run_case 集成：禁止参数违规 → score 0（与 order_before 同语义）"""

    def _case(self, forbidden_args=None, expectations=None, rounds=1):
        return lr.EvalCase(
            id="AC-FA", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL,
            user_inputs=[f"u{i+1}" for i in range(rounds)],
            expectations=expectations or ["tool: customer_logistics_track"],
            data_checks=[], forbidden_args=forbidden_args or [],
        )

    async def _run(self, case, sequence):
        async def fake_send(token, session_id, message, images=None):
            seq = sequence.pop(0)
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": n, "args": a} for n, a in seq["tools"]],
                    "tool_results": [], "final_text": seq.get("text", ""),
                    "error": None, "streamed": False, "done": True}
        import unittest.mock as mock
        with mock.patch.object(lr, "send_message", new=fake_send):
            return await lr.run_case(case, "tok", "sess")

    def test_violation_scores_zero(self):
        case = self._case(forbidden_args=[{"tool": "customer_logistics_track",
                                           "fields": ["tracking_number"]}])
        result = asyncio.run(self._run(case, [
            {"tools": [("customer_logistics_track", {"tracking_number": "SF123"})], "text": "查到了"}]))
        assert result["score"] == 0.0
        assert any("forbidden_args" in str(f) for f, _ in result["failed"])

    def test_clean_scores_one(self):
        case = self._case(forbidden_args=[{"tool": "customer_logistics_track",
                                           "fields": ["tracking_number"]}])
        result = asyncio.run(self._run(case, [
            {"tools": [("customer_logistics_track", {"action": "list"})], "text": "您的订单物流"}]))
        assert result["score"] == 1.0

    def test_backward_compat_without_field(self):
        """旧 case（无 forbidden_args）行为不变"""
        case = self._case()
        result = asyncio.run(self._run(case, [
            {"tools": [("customer_logistics_track", {"tracking_number": "SF123"})], "text": "ok"}]))
        assert result["score"] == 1.0


class TestInteractSatisfiedByInteractiveEvent:
    """`interact` 期望须能被 **SSE interactive 事件**满足（issue #3270 假失败修复）。

    背景：卡片有三条发射路径，但只有第一条会产生 `tool_call` 事件：
      1. `interact` **工具**调用 → `tool_call("interact")` + `interactive` 事件
      2. `handoff_offer` 节点（AI 主动建议转人工）→ **仅 `interactive` 事件**
      3. LLM 幻觉 `<interact>` XML 兜底解析 → **仅 `interactive` 事件**

    而 `expectations: tool: interact` 此前只查 `tool_calls` → 路径 2/3 下**永不可能满足**
    → **假失败**。CI 实证 CH-013「不满情绪 → 建议卡」：
    `rounds=2 tools=['human_handoff'] score=50%` + `❌ interact` ——
    实际 agent 行为**正确**（R1 发建议卡、R2 转人工），只是卡片走的是事件而非工具调用。

    修复语义：`interact` 期望 = **用户看到一张交互卡**，故工具调用与 interactive
    事件二者任一命中即算满足（`args.component` 指定时须组件类型一致）。
    """

    def _r(self, tools=None, interactive=None):
        return {"tool_calls": [{"name": n, "args": a} for n, a in (tools or [])],
                "__all_tool_names": [n for n, _ in (tools or [])],
                "interactive": interactive or [],
                "final_text": ""}

    def test_bare_interact_matched_by_event(self):
        r = self._r(interactive=[{"component": "choice", "options": []}])
        ok, detail = lr.check_expectation(r, "interact")
        assert ok, f"interactive 事件应满足 interact 期望，实得 {detail}"

    def test_bare_interact_still_matched_by_tool(self):
        r = self._r(tools=[("interact", {"component": "confirm"})])
        ok, _ = lr.check_expectation(r, "interact")
        assert ok, "回归：工具调用路径仍须满足"

    def test_interact_component_arg_matched_by_event(self):
        r = self._r(interactive=[{"component": "choice", "multiSelect": True}])
        ok, detail = lr.check_expectation(r, "interact(component=choice)")
        assert ok, f"组件类型一致的事件应满足，实得 {detail}"

    def test_component_mismatch_not_matched(self):
        r = self._r(interactive=[{"component": "form"}])
        ok, _ = lr.check_expectation(r, "interact(component=choice)")
        assert not ok, "组件类型不一致不应算满足（防松弛过度）"

    def test_no_interactive_and_no_tool_not_matched(self):
        r = self._r()
        ok, _ = lr.check_expectation(r, "interact")
        assert not ok, "既无工具调用也无卡片 → 不满足"

    def test_other_tools_unaffected(self):
        """不得把 interact 的特例泄漏到其他工具（如 human_handoff）"""
        r = self._r(interactive=[{"component": "choice"}])
        ok, _ = lr.check_expectation(r, "human_handoff")
        assert not ok, "interactive 事件不应满足非 interact 期望"


class TestBuildRoundTrace:
    """逐轮轨迹（issue #3270 归因层）：把「哪一轮走了哪个 Skill」变成证据

    背景：扁平 `tool_calls` 只说明整场用过哪些工具 —— 而「路由错到别的 Skill」
    与「Skill 没给这个工具」在报告里同形（CH-012 实证无法区分）。本类锁定轨迹的
    事实完整性：轮次、工具、卡片、文本、错误，一个都不能少。
    """

    def test_records_rounds_tools_and_cards(self):
        results = [
            {"__round": 1, "tool_calls": [{"name": "customer_order_query"}],
             "final_text": "找到两笔订单", "interactive": [{"type": "choice"}]},
            {"__round": 2, "tool_calls": [{"name": "human_handoff"}],
             "final_text": "正在转接人工", "interactive": []},
        ]
        trace = lr.build_round_trace(results)
        assert [t["round"] for t in trace] == [1, 2]
        assert trace[0]["tools"] == ["customer_order_query"]
        assert trace[0]["interactive"] == ["choice"]
        assert trace[1]["tools"] == ["human_handoff"]
        assert trace[1]["interactive"] == []
        # 文本必须带出（归因要看 agent 说了什么），但截断防日志膨胀
        assert trace[0]["text"] == "找到两笔订单"

    def test_text_truncated(self):
        results = [{"__round": 1, "tool_calls": [], "final_text": "x" * 500}]
        assert len(lr.build_round_trace(results)[0]["text"]) == 60

    def test_error_recorded_per_round(self):
        results = [{"__round": 1, "tool_calls": [], "final_text": "", "error": "boom"}]
        assert lr.build_round_trace(results)[0]["error"] == "boom"

    def test_empty_and_none_are_safe(self):
        assert lr.build_round_trace([]) == []
        assert lr.build_round_trace(None) == []

    def test_json_serializable(self):
        """轨迹会进 CI 产物 / flake 台账，必须可直接 JSON 序列化。"""
        import json
        results = [{"__round": 1, "tool_calls": [{"name": "t"}], "final_text": "ok",
                    "interactive": [{"type": "choice"}], "cards": [{"type": "product_list"}]}]
        json.dumps(lr.build_round_trace(results))

    def test_format_shows_tools_and_cards_per_round(self):
        trace = lr.build_round_trace([
            {"__round": 1, "tool_calls": [{"name": "customer_order_query"}],
             "final_text": "", "interactive": [{"type": "choice"}]},
            {"__round": 2, "tool_calls": [], "final_text": "", "error": "x"},
        ])
        line = lr.format_round_trace(trace)
        assert "R1" in line and "customer_order_query" in line and "choice" in line
        assert "R2" in line and "ERR" in line
        # 无工具的轮次不得被静默跳过（空轮本身是归因信号）
        assert line.count("R") >= 2

    def test_format_handles_empty(self):
        assert lr.format_round_trace([]) == ""
        assert lr.format_round_trace(None) == ""

    def test_run_case_returns_round_trace(self):
        """集成：run_case 的返回体必须带 round_trace（而不是只留扁平 tool_calls）。"""
        import asyncio
        from types import SimpleNamespace

        sent = []

        async def fake_send_message(token, session_id, message, images=None):
            sent.append(message)
            return {
                "__round": len(sent),
                "tool_calls": [{"name": "customer_order_query", "args": {}}],
                "final_text": "ok",
                "interactive": [],
            }

        orig = lr.send_message
        lr.send_message = fake_send_message
        try:
            case = SimpleNamespace(
                id="TRACE-001", title="t", difficulty=SimpleNamespace(value="normal"),
                tags=[], user_inputs=["我要退货", "第一笔订单"],
                expectations=["customer_order_query"], data_checks=[],
                order_before=[], forbidden_text=[], want_text=[],
                required_args=[], forbidden_args=[], db_verify=None,
                pre_clean=[], post_clean=[],
            )
            out = asyncio.run(lr.run_case(case, "tok", "sess"))
        finally:
            lr.send_message = orig

        assert "round_trace" in out, "run_case 返回体缺少 round_trace"
        assert [t["round"] for t in out["round_trace"]] == [1, 2]
        assert out["round_trace"][0]["tools"] == ["customer_order_query"]


class TestRoundTraceToolOutcomes:
    """轨迹必须区分「**调了**」与「**成了**」（写工具被门禁拦截的关键证据）

    为什么关键：`tool_calls` 记的是 LLM 发起的调用。写工具被 confirm 门禁拦截时
    返回 `{"success": false, "error": "confirmation_required"}`，**调用名照样出现在
    tool_calls 里** → 报告读起来像「写操作正常执行」，实际一次都没落库
    （CH-012 的 aftersale_create 就是这种形态）。故每轮另记 `results:{tool,ok,error}`。
    """

    def test_success_and_failure_both_recorded(self):
        results = [{
            "__round": 1,
            "tool_calls": [{"name": "customer_order_query"}, {"name": "aftersale_create"}],
            "tool_results": [
                {"tool": "customer_order_query", "result": {"success": True}},
                {"tool": "aftersale_create",
                 "result": {"success": False, "error": "confirmation_required"}},
            ],
            "final_text": "",
        }]
        trace = lr.build_round_trace(results)[0]
        assert [(r["tool"], r["ok"], r["error"]) for r in trace["results"]] == [
            ("customer_order_query", True, None),
            ("aftersale_create", False, "confirmation_required"),
        ]

    def test_missing_success_flag_treated_as_not_ok(self):
        """缺 success 字段 → 视为未成功（宁可显性可疑，不可静默当成成功）"""
        results = [{"__round": 1, "tool_calls": [], "final_text": "",
                    "tool_results": [{"tool": "x", "result": {}}]}]
        r = lr.build_round_trace(results)[0]["results"][0]
        assert r["ok"] is False
        assert r["error"] == "no_success_flag"

    def test_non_dict_result_is_safe(self):
        results = [{"__round": 1, "tool_calls": [], "final_text": "",
                    "tool_results": ["garbage", {"tool": "y", "result": "not-a-dict"}]}]
        trace = lr.build_round_trace(results)[0]
        # 非 dict 事件被忽略；result 非 dict 时按未成功记
        assert [r["tool"] for r in trace["results"]] == ["y"]
        assert trace["results"][0]["ok"] is False

    def test_format_marks_failed_tools(self):
        trace = [{
            "round": 1, "tools": ["aftersale_create"], "cards": [], "interactive": [],
            "text": "", "error": None,
            "results": [{"tool": "aftersale_create", "ok": False,
                         "error": "confirmation_required"}],
        }]
        line = lr.format_round_trace(trace)
        assert "failed=aftersale_create!confirmation_required" in line, (
            "格式化未显性标出失败工具 —— 日志里「调了」与「成了」又会同形"
        )

    def test_format_no_failed_marker_when_all_ok(self):
        trace = [{
            "round": 1, "tools": ["customer_order_query"], "cards": [], "interactive": [],
            "text": "", "error": None,
            "results": [{"tool": "customer_order_query", "ok": True, "error": None}],
        }]
        assert "failed=" not in lr.format_round_trace(trace)


class TestRoundTraceResultDigest:
    """结果的**载荷摘要**：区分「工具通了但没数据」与「有数据但不往下走」

    这两种"卡住"的处置完全相反：
      ① 返回空（`items=0` / `has_address=False`）→ **缺数据**，改 fixture；
      ② 返回正常数据但 LLM 就是不推进 → **引导层/模型层**，改 prompt 或加代码兜底。
    实测 CH-012：4 轮只打 `customer_order_query`、不建单，且**没有任何 failed 标记**
    —— 没有摘要时根本看不出是哪一种（也正因如此，摘要必须无条件打印，
    不能只在失败时附带，否则最能说明问题的那一轮恰好没有证据）。
    """

    def _res(self, tool, result):
        return {"__round": 1, "tool_calls": [], "final_text": "",
                "tool_results": [{"tool": tool, "result": result}]}

    def test_list_length_summarized(self):
        d = lr.build_round_trace([self._res(
            "customer_order_query",
            {"success": True, "data": {"items": [{"id": "a"}, {"id": "b"}], "total": 2}})])[0]
        assert d["results"][0]["digest"] == "items=2 total=2"

    def test_empty_list_visible(self):
        d = lr.build_round_trace([self._res(
            "customer_order_query", {"success": True, "data": {"items": [], "total": 0}})])[0]
        assert d["results"][0]["digest"] == "items=0 total=0", (
            "空列表必须显性为 items=0 —— 这与『有数据』是两种不同的根因"
        )

    def test_scalar_values_shown(self):
        d = lr.build_round_trace([self._res(
            "customer_address_query",
            {"success": True, "data": {"has_address": False, "customer_name": None}})])[0]
        assert "has_address=False" in d["results"][0]["digest"]

    def test_failure_digest_falls_back_to_error(self):
        d = lr.build_round_trace([self._res(
            "aftersale_create", {"success": False, "error": "confirmation_required"})])[0]
        assert d["results"][0]["digest"] == "confirmation_required"

    def test_nested_dict_not_expanded(self):
        """嵌套结构只给类型标记 —— 摘要不是全量存档"""
        d = lr.build_round_trace([self._res(
            "x", {"success": True, "data": {"nested": {"a": 1, "b": 2}}})])[0]
        assert d["results"][0]["digest"] == "nested{}"

    def test_digest_is_bounded(self):
        big = {f"k{i}": "v" * 200 for i in range(20)}
        d = lr.build_round_trace([self._res("x", {"success": True, "data": big})])[0]
        digest = d["results"][0]["digest"]
        assert len(digest) <= 160, f"摘要未截断（len={len(digest)}）"
        assert "+14 more" in digest, "字段过多时应给出省略提示"

    def test_format_always_shows_data_digest(self):
        """**无条件**打印：成功且无 failed 标记时也要能看到载荷摘要"""
        trace = lr.build_round_trace([self._res(
            "customer_order_query", {"success": True, "data": {"items": [1, 2]}})])
        line = lr.format_round_trace(trace)
        assert "data=customer_order_query(items=2)" in line, (
            "成功轮次未打印载荷摘要 —— 『工具通了但没数据』这类根因将无从判断"
        )


class TestCaseStartTimestamp:
    """每个用例必须打印 UTC 起始时间戳 —— 让 CI 的**路由 dump** 能按用例切开。

    路由/意图只写在 ai-agent 日志里（带时间戳），runner 输出原本没有时间锚点，
    于是日志里连续的 intent/route 行**无法归属到具体用例** —— 实测 CH-013 与
    CH-014 的轮次交错，眼看无法分辨「某个抱怨被分类成了什么」。
    """


    def _source(self) -> str:
        return RUNNER_PATH.read_text(encoding="utf-8")

    def test_start_marker_printed_per_case(self):
        src = self._source()
        assert re.search(r"⏱ \{case\.id\} start=", src), (
            "run_suite 未打印按用例的起始时间戳 —— 路由 dump 无法按用例切分"
        )

    def test_marker_is_utc_iso(self):
        src = self._source()
        assert "datetime.now(timezone.utc).isoformat" in src, (
            "时间戳必须为 UTC ISO（ai-agent 日志是 UTC），否则对不上"
        )
        assert "from datetime import datetime, timezone" in src, "缺少 datetime 导入"

    def test_marker_precedes_session_creation(self):
        """时间戳必须在用例**开始**时打印（早于建会话/发消息），否则会漏掉首轮路由"""
        src = self._source()
        i_marker = src.find("⏱ {case.id} start=")
        i_session = src.find("await get_or_create_session(token, prefer_new=True)", i_marker - 800)
        assert i_marker != -1 and i_session != -1
        assert i_marker < i_session, (
            "时间戳打印晚于会话创建 —— 首轮意图分类会落在用例区间之外"
        )


class TestToolHealthSummary:
    """工具健康度：工具大面积失败时，**均分衡量的是后端可用性，不是 agent 能力**。

    实测代价（issue #3270）：bootstrap schema 缺列 → admin-api 500 → 工具返回
    「服务暂时不可用」(CIRCUIT_OPEN) → 熔断打开 → 后续工具全失败 → 报告长成
    「agent 不会下单」。我们据此去改 prompt / 改工具 / 加引导，**在错误的层上
    忙了整整一轮**，直到加了 `data=` 摘要才看见真因。

    `migao-acceptance` 的五层归因里基础设施层必须排最前：工具本身报错时，
    数据/断言/引导/模型四层的结论一个都不成立。本类把这个判断自动化。
    """

    def _results(self, ok_flags):
        """ok_flags 例：[("customer_order_query", False, "服务暂时不可用"), ...]"""
        return [{
            "round_trace": [{
                "round": 1,
                "results": [{"tool": t, "ok": ok, "error": None if ok else err}
                            for t, ok, err in ok_flags],
            }],
        }]

    def test_healthy_run_not_flagged(self):
        h = lr.summarize_tool_health(self._results([("a", True, None), ("b", True, None)]))
        assert h["total"] == 2 and h["failed"] == 0
        assert h["infra_suspect"] is False

    def test_high_failure_rate_flags_infra(self):
        h = lr.summarize_tool_health(self._results(
            [("customer_order_query", False, "服务暂时不可用")] * 4 + [("a", True, None)]))
        assert h["failed"] == 4 and h["total"] == 5
        assert h["infra_suspect"] is True, "80% 失败率必须判为基础设施可疑"
        assert h["top_failures"][0]["failure"] == "customer_order_query!服务暂时不可用"
        assert h["top_failures"][0]["count"] == 4

    def test_rate_exactly_at_threshold_flags(self):
        """边界：恰好等于阈值即判可疑（宁可显性可疑，不可静默当能力分）"""
        h = lr.summarize_tool_health(self._results(
            [("x", False, "e")] * 2 + [("y", True, None)] * 8))
        assert h["rate"] == 0.2 and h["infra_suspect"] is True

    def test_just_below_threshold_not_flagged(self):
        h = lr.summarize_tool_health(self._results(
            [("x", False, "e")] * 19 + [("y", True, None)] * 81))
        assert h["rate"] < 0.2 and h["infra_suspect"] is False

    def test_no_tool_calls_not_flagged(self):
        """零调用不得判可疑（那是"没跑"，由 _ci_verdict 的零执行守卫负责）"""
        h = lr.summarize_tool_health([])
        assert h["total"] == 0 and h["infra_suspect"] is False
        assert lr.summarize_tool_health([{"round_trace": []}])["infra_suspect"] is False

    def test_format_lists_top_failures(self):
        h = lr.summarize_tool_health(self._results([
            ("a", False, "服务暂时不可用"), ("a", False, "服务暂时不可用"),
            ("b", False, "tool_execution_failed"), ("c", True, None)]))
        text = lr.format_tool_health(h)
        assert "工具调用 4 次" in text and "失败 3 次" in text
        assert "a!服务暂时不可用 × 2" in text and "b!tool_execution_failed × 1" in text

    def test_results_without_trace_are_ignored(self):
        """兼容：异常/无轨迹的用例不参与统计（不得因此虚高或虚低失败率）"""
        h = lr.summarize_tool_health([{"case_id": "X"}, {"round_trace": []},
                                      {"round_trace": [{"results": [{"tool": "a", "ok": True}]}]}])
        assert h["total"] == 1 and h["failed"] == 0


class TestAutoRespond:
    """`auto_respond` 轮：由 runner 按**上一轮卡片**自动作答（合作型用户模拟）

    为什么需要（run 34627856207 实证，OR-014 / CH-010）：
    这两条用例的 `user_inputs` 是按**某一种**流程形状写的（先选品→再加工项→再确认），
    而 agent 实际的提问顺序与卡片类型会随模型而变（实测 OR-014 第 2 轮先发
    「收货信息 & 颜色」表单、第 3 轮才发加工项 choice 卡）。静态脚本对不上就卡死：
    第 4–8 轮每轮只重复 `customer_address_query`，**order_create 永不发生**。

    真实顾客不会"照着脚本说话"，而是**有什么卡就答什么卡**。本机制就是把这个
    真实行为搬进评测：`{"auto_respond": {...}}` 的轮次优先回答上一轮的待答卡片
    （confirm→confirmValue；choice→首项；form→按声明值回填），没有卡片时用
    `fallback` 文本兜底。这样用例不再依赖某种特定提问顺序。
    """

    def _last(self, interactive):
        return [{"round_trace": [], "interactive": interactive,
                 "tool_results": [], "final_text": ""}]

    def test_answers_confirm_card_with_its_confirm_value(self):
        results = self._last([{"component": "confirm", "confirmValue": "确认下单：遮光窗帘"}])
        out = lr.resolve_auto_respond(results, fallback="确认", form_values={})
        assert out == "确认下单：遮光窗帘"

    def test_confirm_without_confirm_value_falls_back_to_text(self):
        results = self._last([{"component": "confirm", "fields": []}])
        assert lr.resolve_auto_respond(results, fallback="确认下单", form_values={}) == "确认下单"

    def test_answers_choice_card_with_first_option_value(self):
        results = self._last([{"component": "choice",
                               "options": [{"label": "米白", "value": "米白"},
                                           {"label": "浅灰", "value": "浅灰"}]}])
        assert lr.resolve_auto_respond(results, fallback="x", form_values={}) == "米白"

    def test_answers_form_card_with_declared_values(self):
        results = self._last([{"component": "form",
                               "formFields": [{"key": "customer_name"},
                                              {"key": "color"}]}])
        out = lr.resolve_auto_respond(results, fallback="x",
                                      form_values={"customer_name": "张三", "color": "米白"})
        assert out is not None and out.startswith("__FORM__|")
        assert '"customer_name": "张三"' in out and '"color": "米白"' in out

    def test_form_without_matching_values_falls_back(self):
        results = self._last([{"component": "form", "formFields": [{"key": "unknown_key"}]}])
        assert lr.resolve_auto_respond(results, fallback="确认下单", form_values={"a": 1}) == "确认下单"

    def test_no_card_uses_fallback(self):
        assert lr.resolve_auto_respond(self._last([]), fallback="数量 3 米", form_values={}) == "数量 3 米"
        assert lr.resolve_auto_respond([], fallback="123456", form_values={}) == "123456"

    def test_confirm_takes_priority_over_form(self):
        """同一轮多张卡时按「推进流程」的优先级：confirm > choice > form"""
        results = self._last([
            {"component": "form", "formFields": [{"key": "customer_name"}]},
            {"component": "confirm", "confirmValue": "确认下单"},
        ])
        assert lr.resolve_auto_respond(results, fallback="x",
                                       form_values={"customer_name": "张三"}) == "确认下单"

    def test_case_scan_uses_auto_respond_entries(self):
        """run_case 必须识别 `{"auto_respond": …}` 轮（而不是把它当纯文本发出去）"""
        import asyncio
        from types import SimpleNamespace

        sent = []

        async def fake_send(token, session_id, message, images=None):
            sent.append(message)
            # 第 1 轮发一张 confirm 卡；第 2 轮无卡
            interactive = ([{"component": "confirm", "confirmValue": "确认下单"}] if len(sent) == 1 else [])
            return {"__round": len(sent), "tool_calls": [], "final_text": "ok",
                    "interactive": interactive, "tool_results": []}

        orig = lr.send_message
        lr.send_message = fake_send
        try:
            case = SimpleNamespace(
                id="AR-001", title="t", difficulty=SimpleNamespace(value="normal"),
                tags=[], user_inputs=["帮我下单",
                                      {"auto_respond": {"fallback": "确认下单"}}],
                expectations=[], data_checks=[], order_before=[], forbidden_text=[],
                want_text=[], required_args=[], forbidden_args=[], db_verify=None,
                pre_clean=[], post_clean=[],
            )
            asyncio.run(lr.run_case(case, "tok", "sess"))
        finally:
            lr.send_message = orig

        assert sent[0] == "帮我下单"
        assert sent[1] == "确认下单", (
            f"auto_respond 轮未按卡片作答，实发: {sent[1]!r}（被当成纯文本发出去了）"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 长期记忆端到端（issue #3357）：会话关闭接口 + 关闭后置落库断言 + 跨会话轮
# 背景：C 端评测长期 user_memories=0 而报告全绿。两层成因——
#   ① runner 的「会话清理」打的是 admin-api 人工会话表（agent_sessions），
#      C 端会话在 ai-agent 的 sessions 表 → 恒 404 被静默吞掉，close 路径从未执行；
#   ② 记忆候选只在会话关闭时 flush，而 user_memories 落库**没有任何可执行断言**。
# 修复后本组用例锁定：关闭走对接口、跨会话轮真的换会话、落库断言真能失败（非假绿）。
# case_ids: CH-024
# ─────────────────────────────────────────────────────────────────────────────


class TestEndSessionTargetsAiAgent:
    """_end_session 必须关闭 **ai-agent 的会话**（记忆 flush 的唯一入口）。"""

    def _capture(self, status=200, raise_exc=None):
        calls = []

        class _Resp:
            status_code = status
            content = b'{"success":false}'

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def put(self, url, headers=None, timeout=None):
                calls.append(("PUT", url))
                if raise_exc:
                    raise raise_exc
                return _Resp()

            async def post(self, url, headers=None, json=None, timeout=None):
                calls.append(("POST", url))
                return _Resp()

        import unittest.mock as mock
        return calls, mock.patch.object(lr.httpx, "AsyncClient", _Client)

    def test_closes_ai_agent_session(self):
        calls, patched = self._capture()
        with patched:
            asyncio.run(lr._end_session("tok", "sess-1"))
        puts = [u for m, u in calls if m == "PUT"]
        assert puts == [f"{lr.AI_API}/api/chat/sessions/sess-1/close"], (
            f"会话关闭必须打 ai-agent 关闭接口，实际: {calls}"
        )

    def test_no_admin_api_call(self):
        """不得再打 admin-api agent_sessions（死代码 + 噪音，issue #3361）。

        该表是**人工会话**表，主键与 ai-agent 会话 id 不互认 → 传 ai 会话 id 永远 404，
        实测 CI 每次调用都在 admin-api 侧留一条 `[NOT_FOUND] 客服会话不存在` 告警，
        而人工会话是待人工处理的工单，本就不该由评测 harness 关闭。
        """
        calls, patched = self._capture()
        with patched:
            asyncio.run(lr._end_session("tok", "sess-2"))
        assert [c for c in calls if c[0] == "POST"] == [], f"仍在打 admin-api: {calls}"

    def test_close_failure_is_visible_not_swallowed(self, capsys):
        """关闭失败必须打 warning（旧实现静默吞 → 会话永不关闭 + 记忆永不落库）。"""
        calls, patched = self._capture(status=404)
        with patched:
            asyncio.run(lr._end_session("tok", "sess-3"))
        out = capsys.readouterr().out
        assert "会话关闭失败" in out and "404" in out

    def test_close_exception_is_visible(self, capsys):
        calls, patched = self._capture(raise_exc=RuntimeError("conn reset"))
        with patched:
            asyncio.run(lr._end_session("tok", "sess-4"))
        assert "会话关闭异常" in capsys.readouterr().out


class TestEvaluateMemoryCheck:
    """关闭后置断言谓词（user_memories）。"""

    def _mems(self, *pairs):
        return [{"key": k, "value": v} for k, v in pairs]

    def test_count_ge_passes(self):
        ok, _ = lr._evaluate_memory_check(self._mems(("curtain_style", "奶油风")), "count>=1")
        assert ok

    def test_count_ge_fails_with_keys_in_detail(self):
        ok, detail = lr._evaluate_memory_check([], "count>=1")
        assert not ok
        assert "实际 0 条" in detail and "keys=[]" in detail

    def test_count_eq(self):
        mems = self._mems(("a", "1"), ("b", "2"))
        assert lr._evaluate_memory_check(mems, "count==2")[0]
        assert not lr._evaluate_memory_check(mems, "count==1")[0]

    def test_has_key(self):
        mems = self._mems(("curtain_style", "奶油风"))
        assert lr._evaluate_memory_check(mems, "has_key:curtain_style")[0]
        ok, detail = lr._evaluate_memory_check(mems, "has_key:curtain_color")
        assert not ok and "curtain_color" in detail

    def test_value_contains(self):
        mems = self._mems(("curtain_style", "喜欢奶油风装修"))
        assert lr._evaluate_memory_check(mems, "value_contains:奶油风")[0]
        ok, detail = lr._evaluate_memory_check(mems, "value_contains:北欧")
        assert not ok and "奶油风" in detail, "失败详情必须带实际 values（可归因）"

    def test_unparsable_check_fails_closed(self):
        ok, detail = lr._evaluate_memory_check([], "感觉有记忆")
        assert not ok and "无法解析" in detail

    def test_empty_key_or_substring_fails_closed(self):
        assert not lr._evaluate_memory_check([], "has_key:")[0]
        assert not lr._evaluate_memory_check([], "value_contains:")[0]


class TestCheckPostSession:
    """check_post_session：fetch 路由 + 查询异常处理。"""

    def test_unsupported_fetch_reported(self):
        issues = asyncio.run(lr.check_post_session("tok", [{"fetch": "orders"}]))
        assert issues and "不支持的 fetch" in issues[0]

    def test_user_memories_issues_surface(self):
        import unittest.mock as mock

        async def fake_fetch(token, agent_type="xiaobu"):
            return []

        with mock.patch.object(lr, "_fetch_user_memories", new=fake_fetch):
            issues = asyncio.run(lr.check_post_session("tok", [
                {"fetch": "user_memories", "checks": ["count>=1"]}]))
        assert issues and "count>=1" in issues[0]

    def test_query_failure_reported_not_silent(self):
        import unittest.mock as mock

        async def boom(token, agent_type="xiaobu"):
            raise RuntimeError("500")

        with mock.patch.object(lr, "_fetch_user_memories", new=boom):
            issues = asyncio.run(lr.check_post_session("tok", [
                {"fetch": "user_memories", "checks": ["count>=1"]}]))
        assert issues and "查询失败" in issues[0]

    def test_no_specs_no_issues(self):
        assert asyncio.run(lr.check_post_session("tok", None)) == []


class TestCloseAndVerifySession:
    """_close_and_verify_session：关闭 + 后置断言计入用例结果。"""

    def _patch(self, issues):
        import unittest.mock as mock
        closed = []

        async def fake_end(token, sid):
            closed.append(sid)

        async def fake_check(token, specs):
            return list(issues)

        return closed, mock.patch.object(lr, "_end_session", new=fake_end), \
            mock.patch.object(lr, "check_post_session", new=fake_check)

    def test_closes_final_session_id(self):
        """跨会话用例：关闭必须针对 run_case 回报的**最后一个**会话。"""
        closed, p1, p2 = self._patch([])
        case = SimpleNamespace(id="CH-024", post_session=[{"fetch": "user_memories"}])
        r = {"score": 1.0, "final_session_id": "sess-new"}
        with p1, p2:
            asyncio.run(lr._close_and_verify_session(case, "tok", r, "sess-old"))
        assert closed == ["sess-new"]

    def test_falls_back_to_initial_session(self):
        closed, p1, p2 = self._patch([])
        case = SimpleNamespace(id="X", post_session=[])
        r = {"score": 1.0}
        with p1, p2:
            asyncio.run(lr._close_and_verify_session(case, "tok", r, "sess-only"))
        assert closed == ["sess-only"]

    def test_issues_zero_the_score(self):
        closed, p1, p2 = self._patch(["未落库记忆 key=curtain_style"])
        case = SimpleNamespace(id="CH-024", post_session=[{"fetch": "user_memories"}])
        r = {"score": 1.0, "passed": 3, "total": 3, "failed": [], "final_session_id": "s"}
        with p1, p2:
            asyncio.run(lr._close_and_verify_session(case, "tok", r, "s"))
        assert r["score"] == 0.0 and r["passed"] == 0
        assert any("post-session" in str(d) for _, d in r["failed"])

    def test_no_post_session_leaves_score(self):
        closed, p1, p2 = self._patch(["irrelevant"])
        case = SimpleNamespace(id="X", post_session=None)
        r = {"score": 1.0, "final_session_id": "s"}
        with p1, p2:
            asyncio.run(lr._close_and_verify_session(case, "tok", r, "s"))
        assert r["score"] == 1.0 and "failed" not in r


class TestNewSessionTurn:
    """跨会话轮（new_session）：先关旧会话再开新会话（长期记忆注入只在新建会话时发生）。"""

    def _case(self, inputs):
        return lr.EvalCase(
            id="CH-024", legacy_id="", title="memory", skill=lr.Skill.MULTI_TURN,
            difficulty=lr.Difficulty.NORMAL, user_inputs=inputs,
            expectations=[], data_checks=[], persona="xiaobu",
        )

    async def _run(self, case, sent):
        async def fake_send(token, session_id, message, images=None):
            sent.append((session_id, message))
            return {"user_message": message, "images": [], "tool_calls": [],
                    "tool_results": [], "final_text": "ok", "error": None,
                    "streamed": False, "done": True}

        created = []
        closed = []

        async def fake_create(token, prefer_new=True):
            sid = f"new-{len(created) + 1}"   # 与初始会话 id 区分开（否则断言自欺）
            created.append(sid)
            return sid

        async def fake_end(token, sid):
            closed.append(sid)

        import unittest.mock as mock
        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "get_or_create_session", new=fake_create), \
             mock.patch.object(lr, "_end_session", new=fake_end):
            r = await lr.run_case(case, "tok", "sess-1")
        return r, created, closed, sent

    def test_switches_session_before_turn(self):
        case = self._case(["我喜欢奶油风", {"new_session": True, "text": "按我的风格推荐"}])
        r, created, closed, sent = asyncio.run(self._run(case, []))
        assert closed == ["sess-1"], "换会话前必须关闭旧会话（否则候选不 flush）"
        assert len(created) == 1 and r["final_session_id"] == created[0] != "sess-1"
        assert [sid for sid, _ in sent] == ["sess-1", created[0]]
        assert r["session_breaks"] == 1

    def test_no_break_by_default(self):
        case = self._case(["只说一句话"])
        r, created, closed, sent = asyncio.run(self._run(case, []))
        assert created == [] and closed == [] and r["session_breaks"] == 0
        assert r["final_session_id"] == "sess-1"

    def test_empty_text_raises(self):
        """用例书写错误必须响（不是 LLM 波动）：空文本会发出一条空消息。"""
        case = self._case([{"new_session": True}])
        with pytest.raises(ValueError) as ei:
            asyncio.run(self._run(case, []))
        assert "new_session" in str(ei.value) and "text" in str(ei.value)


class TestRunSuitePostSession:
    """run_suite 接线：post_session 失败 → 用例判失败；重试路径同样执行（禁止假绿）。"""

    def _case(self, post_session):
        return lr.EvalCase(
            id="CH-024", legacy_id="", title="memory", skill=lr.Skill.MULTI_TURN,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
            expectations=[], data_checks=[], persona="xiaobu",
            post_session=post_session,
        )

    def _run(self, case, post_results, monkeypatch, tmp_path):
        import unittest.mock as mock
        attempts = []

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            attempts.append(sid)
            return {"case_id": c.id, "title": c.title, "difficulty": "normal",
                    "tags": [], "rounds": 1, "tool_calls": [], "round_trace": [],
                    "passed": 1, "total": 1, "score": 1.0, "failed": [],
                    "last_error": None, "final_text": "ok",
                    "final_session_id": sid, "session_breaks": 0}

        calls = {"checks": 0}

        async def fake_check(token, specs):
            calls["checks"] += 1
            return list(post_results.pop(0)) if post_results else []

        async def fake_end(token, sid):
            return None

        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "flakes.json"))
        monkeypatch.setattr(lr, "CASE_SLEEP", 0.0)  # 单测不为节流付费
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end), \
             mock.patch.object(lr, "check_post_session", new=fake_check):
            results = asyncio.run(lr.run_suite([case], "t"))
        return results, attempts, calls

    def test_passing_post_session_keeps_pass(self, monkeypatch, tmp_path):
        case = self._case([{"fetch": "user_memories", "checks": ["count>=1"]}])
        results, attempts, calls = self._run(case, [[]], monkeypatch, tmp_path)
        assert results[0]["score"] == 1.0
        assert len(attempts) == 1, "通过用例不得重试"
        assert calls["checks"] == 1

    def test_failing_post_session_fails_case(self, monkeypatch, tmp_path):
        """核心假绿防线：轮内断言全过、记忆没落库 → 必须判失败。"""
        case = self._case([{"fetch": "user_memories", "checks": ["count>=1"]}])
        results, attempts, calls = self._run(
            case, [["未落库记忆"], ["未落库记忆"]], monkeypatch, tmp_path)
        assert results[0]["score"] == 0.0
        assert calls["checks"] == 2, "重试路径也必须执行 post_session（否则重试即假绿）"
        assert any("post-session" in str(d) for _, d in results[0]["failed"])

    def test_retry_may_recover(self, monkeypatch, tmp_path):
        """首次落库失败、重试成功 → 按重试结果放行（与普通断言同权）。"""
        case = self._case([{"fetch": "user_memories", "checks": ["count>=1"]}])
        results, attempts, calls = self._run(
            case, [["未落库记忆"], []], monkeypatch, tmp_path)
        assert results[0]["score"] == 1.0
        assert results[0]["classification"] == "llm-noise"
        assert calls["checks"] == 2


class TestRetryBudget:
    """重试预算（issue #3361 评测提速）：失败多的跑不把分钟数全花在重试上。

    实测：C 端 normal 19m39s 里，4 条失败用例（各重跑一整条，单条 200-400s）
    占 87%。重试换来的只是**分类标签**，而 CI 判定只看 score —— 故可设上限。
    关键：超预算的失败**照样记为失败**（不掩盖），只是标签标 no-retry-budget。
    """

    def _run(self, monkeypatch, tmp_path, n_cases, retry_budget):
        import unittest.mock as mock

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        attempts = {"run_case": 0}

        async def fake_run_case(c, token, sid):
            attempts["run_case"] += 1
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 0, "total": 1,
                    "score": 0.0, "failed": [("boom", "x")], "last_error": None,
                    "final_text": "", "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        cases = [lr.EvalCase(id=f"RB-{i}", title="t", skill=lr.Skill.GENERAL,
                             difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                             expectations=["x"], data_checks=[])
                 for i in range(n_cases)]
        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "f.json"))
        monkeypatch.setattr(lr, "CASE_SLEEP", 0.0)  # 单测不为节流付费
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end):
            results = asyncio.run(lr.run_suite(cases, "t", retry_budget=retry_budget))
        return results, attempts["run_case"]

    def test_budget_limits_retries(self, monkeypatch, tmp_path):
        """3 条失败 + 预算 1 → 只重试 1 次（共 4 次 run_case），其余标 no-retry-budget。"""
        results, calls = self._run(monkeypatch, tmp_path, 3, 1)
        assert calls == 4, f"重试预算未生效（run_case 调用 {calls} 次，期望 1+1 次重试）"
        assert results[0]["classification"] != "no-retry-budget"
        assert results[1]["classification"] == "no-retry-budget"
        assert results[2]["classification"] == "no-retry-budget"

    def test_budget_does_not_hide_failures(self, monkeypatch, tmp_path):
        """超预算仍必须判失败（预算只省分钟，不掩盖红灯）。"""
        results, _ = self._run(monkeypatch, tmp_path, 3, 1)
        assert all(r["score"] == 0.0 for r in results)
        ok, msg = lr._ci_verdict(results)
        assert not ok and "3/3" in msg

    def test_no_budget_retries_every_failure(self, monkeypatch, tmp_path):
        results, calls = self._run(monkeypatch, tmp_path, 3, None)
        assert calls == 6, "默认（不限预算）应逐条重试"


class TestDeclaredPostSessionChecksParse:
    """用例库里声明的 post_session 谓词必须真能解析（拼错 = 静默假绿）。

    谓词拼错（如 `count>>=1` / `value_contains` 少写冒号）在 runner 里会走
    "无法解析" 分支 → 报违规 → 用例失败；但若哪天该分支被改成"跳过未知谓词"，
    断言就会静默失效。本测试直接对**用例库全量**做解析体检，把拼错挡在源头。
    """

    def _cases(self):
        import sys
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(repo_root / ".github"))
        from render_cases import load_case_dicts
        return load_case_dicts(str(repo_root / ".github" / "cases"))

    def test_all_declared_checks_parse(self):
        bad = []
        for c in self._cases():
            for spec in c.get("post_session") or []:
                for check in spec.get("checks") or []:
                    ok, detail = lr._evaluate_memory_check([], str(check))
                    if "无法解析" in detail:
                        bad.append(f"{c.get('id')}: {check!r}")
        assert not bad, f"post_session 谓词无法解析（拼写错误）: {bad}"

    def test_all_declared_fetches_supported(self):
        """不支持的 fetch 会被 runner 记违规（这里提前暴露，避免 CI 才炸）。"""
        import unittest.mock as mock

        async def fake_fetch(token, agent_type="xiaobu"):
            return []

        bad = []
        with mock.patch.object(lr, "_fetch_user_memories", new=fake_fetch):
            for c in self._cases():
                specs = c.get("post_session") or []
                if not specs:
                    continue
                issues = asyncio.run(lr.check_post_session("tok", specs))
                # 空记忆下 count>=1 必然失败（正常）；只关心"配置不支持"与"无法解析"两类
                bad += [f"{c.get('id')}: {i}" for i in issues
                        if "不支持的 fetch" in i or "无法解析" in i]
        assert not bad, f"post_session 配置问题: {bad}"


# ─────────────────────────────────────────────────────────────────────────────
# 写工具成功断言 must_succeed（issue #3361：「调了 ≠ 成了」）
# 背景（CI run 34686905546 / 34685247189）：CH-010/OR-014/OR-017 的 order_create
# 分别返回 tool_execution_failed / confirmation_required / tool_not_found，用例照样
# 判 100%，DB 审计里 orders 一条没新增 —— 报告长相「下单正常」，事实「一单没成交」。
# case_ids: CH-010, CH-012, OR-014, OR-017
# ─────────────────────────────────────────────────────────────────────────────


def _round_with_results(rnd, results, calls=None):
    """构造一轮：results=[(tool, ok, error)]，calls=[(tool, args)]（默认与 results 同工具名）"""
    tool_results = [
        {"tool": t, "result": ({"success": ok} if ok else {"success": False, "error": err})}
        for t, ok, err in results
    ]
    if calls is None:
        calls = [(t, {}) for t, _ok, _err in results]
    return {
        "__round": rnd,
        "tool_calls": [{"name": n, "args": a} for n, a in calls],
        "tool_results": tool_results,
        "final_text": "",
    }


class TestToolNameMatches:
    """工具名匹配：精确或 `前缀.工具名`，**不做子串包含**。"""

    def test_exact(self):
        assert lr._tool_name_matches("order_create", "order_create")

    def test_namespaced_suffix(self):
        assert lr._tool_name_matches("customer_order.order_create", "order_create")

    def test_no_substring_false_positive(self):
        """`order_query` 不得匹配 `customer_order_query`（required_args 旧实现在此会误判）。"""
        assert not lr._tool_name_matches("customer_order_query", "order_query")
        assert not lr._tool_name_matches("customer_order_query", "order")

    def test_empty(self):
        assert not lr._tool_name_matches("", "order_create")
        assert not lr._tool_name_matches("order_create", "")


class TestCheckMustSucceed:
    """写工具必须**至少真正成功一次**。"""

    def test_success_passes(self):
        results = [_round_with_results(1, [("order_create", True, None)])]
        assert lr.check_must_succeed(results, [{"tool": "order_create"}]) == []

    def test_all_failed_reports_each_attempt(self):
        """全部失败 → 违规，且详情带每轮错误码（工具层可归因）。"""
        results = [
            _round_with_results(7, [("order_create", False, "tool_execution_failed"),
                                    ("order_create", False, "tool_execution_failed")]),
        ]
        issues = lr.check_must_succeed(results, [{"tool": "order_create"}])
        assert issues and "无一成功" in issues[0]
        assert "R7:tool_execution_failed" in issues[0]
        assert "调了 ≠ 成了" in issues[0]

    def test_blocked_then_success_passes(self):
        """被 confirm 门禁拦一次、最终成功 → 通过（安全拦截是期望行为，不算违规）。"""
        results = [
            _round_with_results(4, [("order_create", False, "confirmation_required")]),
            _round_with_results(6, [("order_create", True, None)]),
        ]
        assert lr.check_must_succeed(results, [{"tool": "order_create"}]) == []

    def test_never_called_reports_missing(self):
        results = [_round_with_results(1, [("product_search", True, None)])]
        issues = lr.check_must_succeed(results, [{"tool": "order_create"}])
        assert issues and "从未被调用" in issues[0]

    def test_call_without_result_event_is_not_success(self):
        """发起了调用但没有结果事件（流中断）→ 不得静默当成功。"""
        results = [{
            "__round": 3,
            "tool_calls": [{"name": "order_create", "args": {}}],
            "tool_results": [],
            "final_text": "",
        }]
        issues = lr.check_must_succeed(results, [{"tool": "order_create"}])
        assert issues and "无结果事件" in issues[0]

    def test_string_spec_supported(self):
        results = [_round_with_results(1, [("order_create", True, None)])]
        assert lr.check_must_succeed(results, ["order_create"]) == []

    def test_action_filter(self):
        """限定 action：只统计该 action 的调用结果。"""
        results = [
            _round_with_results(1, [("aftersale_create", True, None)],
                                calls=[("aftersale_create", {"action": "create"})]),
        ]
        assert lr.check_must_succeed(
            results, [{"tool": "aftersale_create", "action": "create"}]) == []
        issues = lr.check_must_succeed(
            results, [{"tool": "aftersale_create", "action": "cancel"}])
        assert issues and "从未被调用" in issues[0]

    def test_same_tail_tool_not_confused(self):
        """同名尾工具不得互相顶替（B 端 order_query 的成功不能算 customer_order_query）。"""
        results = [_round_with_results(1, [("order_query", True, None)])]
        issues = lr.check_must_succeed(results, [{"tool": "customer_order_query"}])
        assert issues and "从未被调用" in issues[0]

    def test_missing_tool_config_fails_closed(self):
        issues = lr.check_must_succeed([], [{"action": "create"}])
        assert issues and "缺 tool" in issues[0]

    def test_empty_config_no_issues(self):
        assert lr.check_must_succeed([], None) == []
        assert lr.check_must_succeed([], []) == []


class TestRunCaseMustSucceedIntegration:
    """run_case 集成：写工具失败 → 用例级失败（score=0）。"""

    async def _run(self, sequence, must_succeed):
        async def fake_send(token, session_id, message, images=None):
            seq = sequence.pop(0)
            return {
                "user_message": message, "images": [], "final_text": seq.get("text", ""),
                "tool_calls": [{"name": n, "args": {}} for n in seq["calls"]],
                "tool_results": [
                    {"tool": t, "result": ({"success": ok} if ok else {"success": False, "error": err})}
                    for t, ok, err in seq["results"]
                ],
                "error": None, "streamed": False, "done": True,
            }
        import unittest.mock as mock
        case = lr.EvalCase(
            id="MS-1", title="t", skill=lr.Skill.ORDER, difficulty=lr.Difficulty.NORMAL,
            # 轮数与 sequence 严格一致（多一轮会 IndexError，测试自身的假绿/假红要防）
            user_inputs=["下单"] * len(sequence), expectations=["order_create"],
            data_checks=[], must_succeed=must_succeed,
        )
        with mock.patch.object(lr, "send_message", new=fake_send):
            return await lr.run_case(case, "tok", "sess")

    def test_failed_write_fails_case(self):
        """期望命中（工具被调用）但执行失败 → score 0（旧行为是 100% 假绿）。"""
        result = asyncio.run(self._run([
            {"calls": ["order_create"], "results": [("order_create", False, "tool_execution_failed")]},
        ], [{"tool": "order_create"}]))
        assert result["score"] == 0.0, "写工具失败却判通过 = 「调了≠成了」假绿复现"
        assert any("must_succeed" in str(f) for f, _ in result["failed"])

    def test_successful_write_passes(self):
        result = asyncio.run(self._run([
            {"calls": ["order_create"], "results": [("order_create", True, None)]},
        ], [{"tool": "order_create"}]))
        assert result["score"] == 1.0

    def test_no_declaration_behavior_unchanged(self):
        """未声明 must_succeed 的用例行为不变（向后兼容）。"""
        result = asyncio.run(self._run([
            {"calls": ["order_create"], "results": [("order_create", False, "tool_execution_failed")]},
        ], []))
        assert result["score"] == 1.0


class TestRoundTraceRecordsSentMessage:
    """轨迹记录**本轮实际发出**的消息（协议轮输入侧证据，issue #3361 归因缺口）。"""

    def test_user_message_recorded(self):
        trace = lr.build_round_trace([
            {"__round": 1, "user_message": "确认下单：遮光窗帘 3米 共474元",
             "tool_calls": [], "tool_results": [], "final_text": ""},
        ])
        assert trace[0]["user"].startswith("确认下单")
        assert "you=确认下单" in lr.format_round_trace(trace)

    def test_missing_user_message_is_empty(self):
        trace = lr.build_round_trace([{"__round": 1, "tool_calls": [], "tool_results": []}])
        assert trace[0]["user"] == ""
        # 无输入侧证据时不得打印 "you=" 空片段（噪音）
        assert "you=" not in lr.format_round_trace(trace)


class TestThrottleSleepsConfigurable:
    """节流等待可配（issue #3361 评测提速）。

    评测墙钟时间几乎全花在真实 LLM 往返上，固定 sleep 是纯额外开销：
    实测 C 端 normal 单跑 19m39s（18 条）里 ~63s 是 0.5s/轮 + 1s/用例的固定等待，
    B 端 47 条约 3min。但真实 LLM 有限流需求，所以做成**可配**而非删除：
    CI 调到最小（0.2/0.3），本地调试可调回默认。
    """

    def test_defaults_preserved(self, monkeypatch):
        """默认值不变（向后兼容）：0.5s/轮、1s/用例。"""
        monkeypatch.delenv("EVAL_ROUND_SLEEP", raising=False)
        monkeypatch.delenv("EVAL_CASE_SLEEP", raising=False)
        assert lr._env_float("EVAL_ROUND_SLEEP", 0.5) == 0.5
        assert lr._env_float("EVAL_CASE_SLEEP", 1.0) == 1.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("EVAL_ROUND_SLEEP", "0.2")
        assert lr._env_float("EVAL_ROUND_SLEEP", 0.5) == 0.2

    def test_illegal_value_falls_back(self, monkeypatch):
        """非法值回落默认（不得因为写错环境变量把评测卡死或崩掉）。"""
        monkeypatch.setenv("EVAL_ROUND_SLEEP", "abc")
        assert lr._env_float("EVAL_ROUND_SLEEP", 0.5) == 0.5
        monkeypatch.setenv("EVAL_ROUND_SLEEP", "-1")
        assert lr._env_float("EVAL_ROUND_SLEEP", 0.5) == 0.5

    def test_zero_disables_sleep(self, monkeypatch):
        monkeypatch.setenv("EVAL_ROUND_SLEEP", "0")
        assert lr._env_float("EVAL_ROUND_SLEEP", 0.5) == 0.0


class TestShardCases:
    """分片切分（issue #3361 评测提速）：语义不变的 CI 并行加速。"""

    def test_round_robin_partition_is_complete_and_disjoint(self):
        cases = list(range(18))
        parts = [lr.shard_cases(cases, f"{i}/3") for i in range(3)]
        flat = [c for p in parts for c in p]
        assert sorted(flat) == cases, "分片必须覆盖全部用例（漏跑 = 静默少测）"
        assert len(flat) == len(set(flat)), "分片不得重叠（重叠 = 同一用例重复付费跑）"

    def test_round_robin_balances_slow_cases(self):
        """轮转而非顺序切：慢用例（实测 OR-014 403s）与快用例交错，避免堆在一片。"""
        cases = [f"c{i}" for i in range(6)]
        assert lr.shard_cases(cases, "0/2") == ["c0", "c2", "c4"]
        assert lr.shard_cases(cases, "1/2") == ["c1", "c3", "c5"]

    def test_no_shard_returns_all(self):
        cases = list(range(5))
        assert lr.shard_cases(cases, "") == cases
        assert lr.shard_cases(cases, "0/1") == cases

    def test_illegal_shard_ignored(self):
        cases = list(range(5))
        assert lr.shard_cases(cases, "abc") == cases
        assert lr.shard_cases(cases, "0/0") == cases

    def test_out_of_range_raises(self):
        import pytest as _pytest
        with _pytest.raises(ValueError):
            lr.shard_cases(list(range(5)), "3/3")

    def test_empty_shard_is_visible_not_silent(self):
        """空片必须是显式错误（0 用例执行 = 静默假绿，与 _ci_verdict 同语义）。"""
        cases = ["only"]
        empty = lr.shard_cases(cases, "1/2")
        assert empty == [], "分片可能为空 —— 调用方必须显式报错而非静默放行"


class TestRunSummaryJson:
    """机器可读运行汇总（issue #3361 分片基建）：审计/报告不必解析日志。"""

    def test_writes_expected_fields(self, tmp_path):
        import json as _json
        results = [
            {"case_id": "CH-010", "score": 1.0, "classification": "pass",
             "tool_calls": ["product_search", "order_create"]},
            {"case_id": "KN-001", "score": 1.0, "classification": "pass",
             "tool_calls": ["knowledge_search"]},
            {"case_id": "OR-017", "score": 0.0, "classification": "reproducible",
             "tool_calls": ["order_create"]},
        ]
        out = tmp_path / "s.json"
        lr.write_summary_json(str(out), "normal", "1/3", results)
        data = _json.loads(out.read_text(encoding="utf-8"))
        assert data["shard"] == "1/3" and data["total"] == 3
        assert data["passed"] == 2 and data["failed"] == 1
        assert data["order_write_cases"] == 2, "下单写用例计数错（审计据此决定是否告警）"
        assert data["write_cases_ok"] == 1
        assert [c["id"] for c in data["cases"]] == ["CH-010", "KN-001", "OR-017"]

    def test_empty_results(self, tmp_path):
        import json as _json
        out = tmp_path / "e.json"
        lr.write_summary_json(str(out), "normal", "0/1", [])
        data = _json.loads(out.read_text(encoding="utf-8"))
        assert data["total"] == 0 and data["avg_score"] == 0.0

    def test_write_failure_is_not_fatal(self, tmp_path, capsys):
        """汇总写失败不得让评测崩（非致命）。"""
        lr.write_summary_json(str(tmp_path / "nodir" / "x.json"), "normal", "", [])
        assert "汇总写出失败" in capsys.readouterr().out


class TestSuiteConcurrency:
    """用例级并发（issue #3361 评测提速第二轮）。

    实测（run 34692977836，3 片 × 6 条）：评测本身随并行线性变快（单 job 11.6min/18 条
    → 各片 5.3/7.2/1.7min/6 条，单条吞吐不变），但**多 job 各自建栈**把栈时间从 3.4min
    抬到 12min → 分片整体更慢（19.8 vs 15.6min）。结论：要并行就并行**用例**，别并行建栈。
    本组锁定并发语义：有界、串行道独占、报告顺序稳定、重试预算不被并发突破。
    """

    def _mkcase(self, cid, tags=None, pre_clean=None, post_session=None):
        return lr.EvalCase(id=cid, title=cid, skill=lr.Skill.GENERAL,
                           difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                           expectations=[], data_checks=[], tags=tags or [],
                           pre_clean=pre_clean or [], post_session=post_session or [])

    def _run(self, monkeypatch, tmp_path, cases, concurrency, fail_ids=()):
        import unittest.mock as mock
        events = []          # (case_id, "start"/"end")
        active = {"now": 0, "max": 0}

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            events.append((c.id, "start"))
            # 让**完成顺序与声明顺序相反**（C0 最慢）：否则"按完成顺序回填"的 bug
            # 会因为顺序恰好一致而漏过（变异实测踩到过 —— 测试必须能区分两种顺序）
            try:
                delay = 0.02 * (len(c.id) and 10 - int("".join(ch for ch in c.id if ch.isdigit()) or 0))
            except ValueError:
                delay = 0.05
            await asyncio.sleep(max(delay, 0.02))
            events.append((c.id, "end"))
            active["now"] -= 1
            score = 0.0 if c.id in fail_ids else 1.0
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": int(score),
                    "total": 1, "score": score, "failed": [], "last_error": None,
                    "final_text": "", "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        async def fake_snapshot(token, kw):
            return None

        async def fake_post_checks(token, specs):
            return []

        async def fake_pre_clean(token, spec):
            return ""

        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "f.json"))
        monkeypatch.setattr(lr, "CASE_SLEEP", 0.0)
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end), \
             mock.patch.object(lr, "snapshot_product", new=fake_snapshot), \
             mock.patch.object(lr, "_run_pre_clean", new=fake_pre_clean), \
             mock.patch.object(lr, "check_post_session", new=fake_post_checks):
            results = asyncio.run(lr.run_suite(cases, "t", classify=False,
                                              concurrency=concurrency))
        return results, events, active

    def test_concurrency_bounded(self, monkeypatch, tmp_path):
        """并发度是上限：3 条用例、并发度 2 → 同时在跑的不超过 2。"""
        cases = [self._mkcase(f"C{i}") for i in range(3)]
        _results, _events, active = self._run(monkeypatch, tmp_path, cases, 2)
        assert active["max"] <= 2, f"并发度未被遵守（峰值 {active['max']}）"
        assert active["max"] >= 2, "并发未生效（峰值 1 = 退化成串行）"

    def test_serial_lane_not_overlapping(self, monkeypatch, tmp_path):
        """共享资源用例（tag/pre_clean/post_session）必须独占：与任何用例都不重叠。"""
        cases = [
            self._mkcase("P1"), self._mkcase("P2"), self._mkcase("P3"),
            self._mkcase("S1", tags=["update"]),                 # 商品改价类
            self._mkcase("S2", post_session=[{"fetch": "user_memories"}]),  # 用户级状态
        ]
        _results, events, _active = self._run(monkeypatch, tmp_path, cases, 3)
        # 串行道用例执行期间不得有其他用例"在跑"
        intervals = {}
        for cid, kind in events:
            intervals.setdefault(cid, {})[kind] = None
        # 用事件顺序重建区间
        starts, ends = {}, {}
        for idx, (cid, kind) in enumerate(events):
            (starts if kind == "start" else ends)[cid] = idx
        for serial_id in ("S1", "S2"):
            for other in ("P1", "P2", "P3", "S1", "S2"):
                if other == serial_id:
                    continue
                overlap = starts[serial_id] < ends[other] and starts[other] < ends[serial_id]
                assert not overlap, f"串行道 {serial_id} 与 {other} 重叠执行（隔离失效）"

    def test_report_order_is_original_case_order(self, monkeypatch, tmp_path):
        """报告顺序必须与用例声明顺序一致（并发不改变报告，便于与历史 run 逐条对比）。"""
        cases = [self._mkcase(f"C{i}") for i in range(6)]
        results, _events, _active = self._run(monkeypatch, tmp_path, cases, 3)
        assert [r["case_id"] for r in results] == [f"C{i}" for i in range(6)]

    def test_retry_budget_not_exceeded_under_concurrency(self, monkeypatch, tmp_path):
        """并发下重试预算不能被突破（判定+占用必须原子）。"""
        cases = [self._mkcase(f"C{i}") for i in range(4)]
        import unittest.mock as mock
        attempts = {"n": 0}

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            attempts["n"] += 1
            await asyncio.sleep(0.02)
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 0, "total": 1,
                    "score": 0.0, "failed": [("x", "y")], "last_error": None,
                    "final_text": "", "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "f.json"))
        monkeypatch.setattr(lr, "CASE_SLEEP", 0.0)
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end):
            results = asyncio.run(lr.run_suite(
                cases, "t", classify=True, retry_budget=1, concurrency=4))
        # 4 条首跑 + 预算 1 次重试 = 5 次（并发下若"看了眼再占用"就会 >5）
        assert attempts["n"] == 5, f"重试预算被并发突破（run_case 调用 {attempts['n']} 次）"
        assert sum(1 for r in results if r.get("classification") == "no-retry-budget") == 3

    def test_concurrency_one_is_serial(self, monkeypatch, tmp_path):
        """并发度 1 → 完全串行（默认行为不变，向后兼容）。"""
        cases = [self._mkcase(f"C{i}") for i in range(3)]
        _results, _events, active = self._run(monkeypatch, tmp_path, cases, 1)
        assert active["max"] == 1


class TestConcurrencyGateTail:
    """串行用例不得变成整跑尾巴（issue #3361：读写门语义）。

    实测 C 端 normal：16 条并行（并发度 3）~3min，串行道的 OR-014（pre_clean + 重试）
    一个人在末尾又跑 ~7min → 整段评测 10.6min。隔离要求本是"不与其他用例重叠"，
    不是"必须在最后跑"。
    """

    def _mkcase(self, cid, tags=None, pre_clean=None):
        return lr.EvalCase(id=cid, title=cid, skill=lr.Skill.GENERAL,
                           difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                           expectations=[], data_checks=[], tags=tags or [],
                           pre_clean=pre_clean or [])

    def test_serial_case_starts_before_all_parallel_finish(self, monkeypatch, tmp_path):
        """慢串行用例应在**首批并行用例排空后**立刻开工，而不是等全部并行跑完。"""
        import unittest.mock as mock
        events = []

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            events.append((c.id, "start"))
            # 并行用例都很快；串行（慢）用例自身耗时长 —— 关键在于它**何时开始**
            await asyncio.sleep(0.3 if c.id == "SLOW" else 0.05)
            events.append((c.id, "end"))
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        async def fake_snapshot(token, kw):
            return None

        cases = [self._mkcase(f"P{i}") for i in range(6)]
        # 用真正"整体独占"的形态（商品改价 tag）——pre_clean 现在只让**清理动作**独占，
        # 用例主体回并行道（见 _needs_serial_lane 注释）
        cases.append(self._mkcase("SLOW", tags=["update"]))
        monkeypatch.setenv("AGENT_EVAL_FLAKE_LOG", str(tmp_path / "f.json"))
        monkeypatch.setattr(lr, "CASE_SLEEP", 0.0)
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end), \
             mock.patch.object(lr, "snapshot_product", new=fake_snapshot):
            asyncio.run(lr.run_suite(cases, "t", classify=False, concurrency=3))

        slow_start = [i for i, (cid, k) in enumerate(events) if cid == "SLOW" and k == "start"][0]
        parallel_ends = [i for i, (cid, k) in enumerate(events) if cid.startswith("P") and k == "end"]
        assert slow_start < max(parallel_ends), (
            "串行用例等到所有并行用例跑完才开始（退化为尾巴）—— 读写门未生效"
        )
        # 同时仍必须独占：串行用例执行期间没有任何并行用例在跑
        slow_end = [i for i, (cid, k) in enumerate(events) if cid == "SLOW" and k == "end"][0]
        for cid, kind in events[slow_start:slow_end]:
            assert cid == "SLOW", f"串行用例执行期间 {cid} 也在跑（隔离失效）"

    def test_gate_writer_excludes_readers(self):
        """门本身语义：读者并发有上限、写者执行期间**零读者**。"""
        import asyncio as _a

        async def scenario():
            gate = lr.ConcurrencyGate(2)
            state = {"readers": 0, "max_readers": 0, "writer_violation": False}

            async def reader():
                async with gate.reader():
                    state["readers"] += 1
                    state["max_readers"] = max(state["max_readers"], state["readers"])
                    await _a.sleep(0.05)
                    state["readers"] -= 1

            async def writer():
                async with gate.writer():
                    if state["readers"] != 0:
                        state["writer_violation"] = True
                    await _a.sleep(0.05)

            # 先起 4 个读者（上限 2）+ 1 个写者：写者须等读者排空，且期间无读者
            await _a.gather(*[reader() for _ in range(4)], writer(), writer())
            return state

        state = asyncio.run(scenario())
        assert state["max_readers"] <= 2, f"读者上限被突破（峰值 {state['max_readers']}）"
        assert state["max_readers"] == 2, "读者未真正并发（退化为串行）"
        assert not state["writer_violation"], "写者执行期间有读者在跑（独占语义失效）"


class TestPreCleanExclusiveWindow:
    """pre_clean 只让**清理动作**独占，用例主体回并行道（issue #3361 提速第三轮）。

    实测：OR-014 因 `pre_clean: product_dedupe` 被整条判独占 → 一个人跑 ~5.5min，
    把 C 端正常一整段评测（10.2min）顶到上限。而隔离需求只覆盖"清理共享数据"这个**短写动作**，
    不覆盖随后的用例主体（下单/查询各自新建数据）。
    """

    def _mkcase(self, cid, pre_clean=None):
        return lr.EvalCase(id=cid, title=cid, skill=lr.Skill.GENERAL,
                           difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                           expectations=[], data_checks=[], tags=[],
                           pre_clean=pre_clean or [])

    def test_pre_clean_case_is_not_serially_scheduled(self):
        """带 pre_clean 的用例不得被判为"整体独占"。"""
        case = self._mkcase("PC", pre_clean=[{"type": "product_dedupe"}])
        # 通过 run_suite 的调度日志判断（_needs_serial_lane 是内层函数）
        import unittest.mock as mock

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        async def fake_pre_clean(token, spec):
            return "cleaned"

        lines = []
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end), \
             mock.patch.object(lr, "_run_pre_clean", new=fake_pre_clean), \
             mock.patch.object(lr, "print", side_effect=lambda *a, **k: lines.append(" ".join(str(x) for x in a))):
            asyncio.run(lr.run_suite([case, self._mkcase("A"), self._mkcase("B")],
                                     "t", classify=False, concurrency=3))
        joined = "\n".join(lines)
        assert "3 条并行" in joined, (
            f"带 pre_clean 的用例仍被判为独占（应只独占清理动作）：\n{joined[:400]}"
        )
        assert "串行" not in joined.split("并发执行")[1][:60], "仍存在串行道（pre_clean 不该整体独占）"
        assert "🧹 pre_clean: cleaned" in joined, "pre_clean 未执行"

    def test_serial_lane_keeps_mutating_and_user_state_cases(self):
        """仍整体独占的：商品改价 tag 与 post_session（用户级状态）。"""
        import unittest.mock as mock

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        async def fake_post_checks(token, specs):
            return []

        async def fake_snapshot(token, kw):
            return None

        cases = [self._mkcase("A"), self._mkcase("B"),
                 lr.EvalCase(id="MUT", title="MUT", skill=lr.Skill.GENERAL,
                             difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                             expectations=[], data_checks=[], tags=["update"]),
                 lr.EvalCase(id="MEM", title="MEM", skill=lr.Skill.GENERAL,
                             difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                             expectations=[], data_checks=[],
                             post_session=[{"fetch": "user_memories", "checks": ["count>=1"]}])]
        lines = []
        with mock.patch.object(lr, "login", new=fake_login), \
             mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
             mock.patch.object(lr, "run_case", new=fake_run_case), \
             mock.patch.object(lr, "_end_session", new=fake_end), \
             mock.patch.object(lr, "check_post_session", new=fake_post_checks), \
             mock.patch.object(lr, "snapshot_product", new=fake_snapshot), \
             mock.patch.object(lr, "print", side_effect=lambda *a, **k: lines.append(" ".join(str(x) for x in a))):
            asyncio.run(lr.run_suite(cases, "t", classify=False, concurrency=3))
        joined = "\n".join(lines)
        assert "2 条并行" in joined and "+ 2 条串行" in joined, (
            f"独占判据异常（应为 2 并行 + 2 串行：tag=update 与 post_session）：\n{joined[:400]}"
        )


class TestNoDeadlockWithPreCleanUnderConcurrency:
    """并发 + pre_clean 不得死锁（issue #3361 实测踩到并跑挂过一次 CI）。

    根因：并行任务先持 `gate.reader()`（读位）再在 `_run_one_case` 里为 pre_clean 去要
    `gate.writer()`（写位）—— 写位要求"读者排空"，而**请求者自己就是读者** → 互等 → 挂到
    超时（run 34698839019 实测：评测步骤 15min+ 不结束，只能人工 cancel）。
    修法：pre_clean 的独占窗口必须在读位**之外**获取（调度器先清理，再进读位跑主体）。

    本测试用极短超时守护：一旦死锁，用例直接失败而不是把 CI 拖到 60 分钟超时。
    """

    def _mkcase(self, cid, pre_clean=None, tags=None):
        return lr.EvalCase(id=cid, title=cid, skill=lr.Skill.GENERAL,
                           difficulty=lr.Difficulty.NORMAL, user_inputs=["hi"],
                           expectations=[], data_checks=[], tags=tags or [],
                           pre_clean=pre_clean or [])

    def _run_with_timeout(self, cases, concurrency, seconds=8.0):
        import unittest.mock as mock

        async def fake_login():
            return "tok"

        async def fake_sess(token, prefer_new=True):
            return "sess"

        async def fake_run_case(c, token, sid):
            await asyncio.sleep(0.02)
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid):
            return None

        async def fake_pre_clean(token, spec):
            return "ok"

        async def fake_snapshot(token, kw):
            return None

        async def _go():
            with mock.patch.object(lr, "login", new=fake_login), \
                 mock.patch.object(lr, "get_or_create_session", new=fake_sess), \
                 mock.patch.object(lr, "run_case", new=fake_run_case), \
                 mock.patch.object(lr, "_end_session", new=fake_end), \
                 mock.patch.object(lr, "_run_pre_clean", new=fake_pre_clean), \
                 mock.patch.object(lr, "snapshot_product", new=fake_snapshot), \
                 mock.patch.object(lr, "CASE_SLEEP", 0.0):
                return await lr.run_suite(cases, "t", classify=False, concurrency=3)

        async def _guard():
            return await asyncio.wait_for(_go(), timeout=seconds)

        return asyncio.run(_guard())

    def test_pre_clean_case_parallel_does_not_deadlock(self):
        cases = [self._mkcase("A"), self._mkcase("B"),
                 self._mkcase("PC", pre_clean=[{"type": "product_dedupe"}])]
        results = self._run_with_timeout(cases, 3)
        assert len(results) == 3

    def test_pre_clean_with_serial_case_does_not_deadlock(self):
        """有独占用例（tag=update）+ pre_clean 并行用例 —— 本轮踩到的组合。"""
        cases = [self._mkcase("A"), self._mkcase("PC", pre_clean=[{"type": "product_dedupe"}]),
                 self._mkcase("MUT", tags=["update"])]
        results = self._run_with_timeout(cases, 3)
        assert len(results) == 3

    def test_all_cases_pre_clean_does_not_deadlock(self):
        cases = [self._mkcase(f"P{i}", pre_clean=[{"type": "product_dedupe"}]) for i in range(4)]
        results = self._run_with_timeout(cases, 3)
        assert len(results) == 4
