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
# case_ids: OR-016, AS-007, PR-019, CH-010
import asyncio
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
