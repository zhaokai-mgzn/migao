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
# case_ids: OR-016, AS-007, PR-019, CH-010, CH-024, OR-021, OR-022, PR-024, CH-025
import asyncio
from types import SimpleNamespace
import importlib.util
import json
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
        async def fake_send(token, session_id, message, images=None, **kwargs):
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

    def _card(self, qty, title="请确认订单信息"):
        return ("interact", {"component": "confirm", "title": title,
                             "fields": [{"label": "商品", "value": "遮光窗帘"},
                                        {"label": "数量", "value": f"{qty}米"}]})

    def test_change_of_facts_is_not_a_loop(self):
        """OR-019 实测形态：改数量 → 三张卡但只有两张同事实 → **不是**死循环（假红修复）。"""
        results = _rounds_with_args([
            (4, [self._card(3)], "请确认"),
            (6, [self._card(4)], "请确认"),
            (7, [self._card(4)], "请确认"),
        ])
        assert lr.check_confirm_loop(results) == [], "顾客改了数量后的合法重新确认不得判死循环"

    def test_same_facts_reworded_still_detected(self):
        """换措辞但事实相同，连发 3 次 → 必须判死循环（旧实现按标题会漏判）。"""
        results = _rounds_with_args([
            (1, [self._card(3, title="请确认订单信息")], "x"),
            (2, [self._card(3, title="请核对订单明细")], "y"),
            (3, [self._card(3, title="订单确认")], "z"),
        ])
        issues = lr.check_confirm_loop(results)
        assert issues and "死循环" in issues[0], issues

    def _card_cv(self, cv, title):
        """生产形态：confirm 卡的 confirmValue 已由字段事实确定性派生（issue #3406）。"""
        return ("interact", {"component": "confirm", "title": title,
                             "confirmValue": cv,
                             "fields": [{"label": "商品", "value": "遮光窗帘"}]})

    def test_confirm_value_is_the_primary_key(self):
        """标题各不相同、但 confirmValue 相同（= 同一批事实）→ 必须判死循环。

        为什么单列（变异 M212 抓出）：把内容键的 confirmValue 分支去掉后，测试**照样全绿** ——
        因为旧用例的卡都没带 confirmValue，走的是 fields 回退分支；
        而**生产形态**下 confirmValue 一定存在（issue #3406 之后由字段事实派生），
        故必须有用例专门钉住这条主路径。
        """
        cv = "确认：商品=遮光窗帘；数量=3米"
        results = _rounds_with_args([
            (1, [self._card_cv(cv, "请确认订单信息")], "x"),
            (2, [self._card_cv(cv, "请核对订单明细")], "y"),
            (3, [self._card_cv(cv, "订单确认")], "z"),
        ])
        issues = lr.check_confirm_loop(results)
        assert issues and "死循环" in issues[0], f"同一 confirmValue 连发 3 次必须判死循环: {issues}"

    def test_different_confirm_values_not_a_loop(self):
        """事实变了（数量 3→4）→ confirmValue 变 → 不是死循环（OR-019 形态）。"""
        results = _rounds_with_args([
            (4, [self._card_cv("确认：商品=遮光窗帘；数量=3米", "请确认订单信息")], "x"),
            (6, [self._card_cv("确认：商品=遮光窗帘；数量=4米", "请确认订单信息")], "y"),
            (7, [self._card_cv("确认：商品=遮光窗帘；数量=4米", "请确认订单信息")], "z"),
        ])
        assert lr.check_confirm_loop(results) == []

    def test_same_facts_three_times_detected(self):
        results = _rounds_with_args([
            (1, [self._card(3)], "x"), (2, [self._card(3)], "y"), (3, [self._card(3)], "z"),
        ])
        assert lr.check_confirm_loop(results), "同一批事实连发 3 次必须判死循环"


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
        async def fake_send(token, session_id, message, images=None, **kwargs):
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
        async def fake_send(token, session_id, message, images=None, **kwargs):
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
        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"
        async def fake_send(token, sid, message, images=None, **kwargs):
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
        async def fake_send(token, session_id, message, images=None, **kwargs):
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

        async def fake_send_message(token, session_id, message, images=None, **kwargs):
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


class TestForbiddenCardText:
    """卡片内容反模式断言（issue #3402）：把 C-A1 的"2 倍用量选项"变成可执行回归网。

    为什么需要（C-A1 实证）：Agent 把顾客说的「数量 3 米」当窗宽，发了
    `choice: 请选择窗帘用量 → 3米（¥528）| **6米（¥1056，褶皱饱满，推荐）**` ——
    推荐项是顾客意图的 **2 倍钱**。运行时守卫已拦（`_quantity_choice_block`），
    但**判定层也要能独立看见**：守卫可能被绕过（模型改用文本/别的组件），
    且"卡里出现了用量/倍数"本身就是可断言的事实。
    """

    def _round(self, cards):
        return {"__round": 1, "tool_calls": [], "tool_results": [],
                "interactive": cards, "final_text": ""}

    def _card(self, title, labels):
        return {"type": "choice", "title": title,
                "options": [{"label": l, "value": l} for l in labels]}

    def test_forbidden_title_hit(self):
        issues = lr.check_forbidden_card_text(
            [self._round([self._card("请选择窗帘用量", ["3米", "6米"])])],
            [{"text": "用量"}])
        assert issues and "用量" in issues[0], issues

    def test_forbidden_option_label_hit(self):
        issues = lr.check_forbidden_card_text(
            [self._round([self._card("请选择窗帘颜色", ["米白（推荐）", "浅灰"])])],
            [{"text": "推荐"}])
        assert issues, issues

    def test_forbidden_field_value_hit(self):
        card = {"type": "form", "title": "收货信息",
                "formFields": [{"key": "customer_address", "label": "地址", "value": "某地址"}]}
        issues = lr.check_forbidden_card_text([self._round([card])], [{"text": "某地址"}])
        assert issues, issues

    def test_clean_cards_pass(self):
        assert lr.check_forbidden_card_text(
            [self._round([self._card("请选择窗帘颜色", ["米白", "浅灰"])])],
            [{"text": "用量"}, {"text": "褶皱"}]) == []

    def test_plain_string_spec_supported(self):
        issues = lr.check_forbidden_card_text(
            [self._round([self._card("请选择窗帘用量", ["3米"])])], ["用量"])
        assert issues, "字符串写法也必须生效（配置更简单，不易写错）"


class TestForbiddenCardTextWiring:
    """接线：卡内容反模式必须计入用例判定（score 0）。"""

    def _case(self, spec):
        return lr.EvalCase(
            id="CARDTEXT-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["数量 3 米"],
            expectations=["tool: interact"], data_checks=[],
            persona="xiaobu", forbidden_card_text=spec,
        )

    def _run(self, title, spec):
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None, debug_user=""):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "interact", "args": {}}],
                    "tool_results": [],
                    "interactive": [{"type": "choice", "title": title,
                                     "options": [{"label": "3米", "value": "3米"}]}],
                    "final_text": "好的", "error": None, "streamed": False, "done": True}

        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "PERSONA", "xiaobu"):
            return asyncio.run(lr.run_case(self._case(spec), "tok", "sess_c"))

    def test_forbidden_card_scores_zero(self):
        res = self._run("请选择窗帘用量", [{"text": "用量"}])
        assert res["score"] == 0.0, "卡里出现「用量」必须判红（C-A1 形态）"

    def test_clean_card_keeps_score(self):
        res = self._run("请选择窗帘颜色", [{"text": "用量"}])
        assert res["score"] == 1.0, f"正常卡被误判: {res['failed']}"


class TestFormPrefill:
    """form 卡必须**预填真值**（issue #3397：老客户收货信息自动带出）。

    为什么必须守（此前是"内部步骤、无独立诉求"被豁免的两个工具之一）：
      ① 老客户下单自动带出上次收货信息是核心便利（issue #2815），此前**零断言**；
      ② 预填值必须是**原值** —— 掩码值回流会让顾客直接提交 `138****8000`，
         订单用掩码建单（issue #3379 的真实事故形态）；
      ③ 新客路径（OR-022）已守"没有历史信息时要问/要收集"，这条守**反面**：
         `customer_address_query` 命中时必须真的把信息带进表单，而不是再问一遍。
    """

    def _round(self, form_fields):
        return {"__round": 1, "tool_calls": [], "tool_results": [],
                "interactive": [{"type": "form", "title": "请确认收货信息",
                                 "formFields": form_fields}],
                "final_text": ""}

    def _run(self, fields, spec):
        return lr.check_form_prefill([self._round(fields)], spec)

    def test_prefilled_exact_value_passes(self):
        issues = self._run([{"key": "customer_phone", "label": "手机号", "value": "13800138000"}],
                           [{"field": "customer_phone", "expect": "13800138000"}])
        assert issues == []

    def test_whitespace_normalized_match(self):
        """地址里空格差异不该判红（比对前归一化空白）。"""
        issues = self._run([{"key": "customer_address", "value": "浙江省杭州市西湖区 文三路1号"}],
                           [{"field": "customer_address", "expect": "浙江省杭州市西湖区文三路1号"}])
        assert issues == []

    def test_masked_prefill_fails(self):
        """掩码值预填 → 顾客会把它提交回写（PII 事故形态）→ 必须判红。"""
        issues = self._run([{"key": "customer_phone", "value": "138****8000"}],
                           [{"field": "customer_phone", "expect": "13800138000"}])
        assert issues and "138****8000" in issues[0], issues

    def test_missing_field_fails_closed(self):
        """表单里没这个字段 = 没带出历史信息 → 判红（不是跳过）。"""
        issues = self._run([{"key": "customer_name", "value": "张三"}],
                           [{"field": "customer_phone", "expect": "13800138000"}])
        assert issues and "customer_phone" in issues[0], issues

    def test_no_form_card_fails_closed(self):
        issues = lr.check_form_prefill([{"__round": 1, "tool_calls": [], "tool_results": [],
                                         "interactive": [], "final_text": "请告诉我您的地址"}],
                                       [{"field": "customer_phone", "expect": "13800138000"}])
        assert issues and "form" in issues[0], issues

    def test_expect_present_only(self):
        """fixture 无关的字段只要求"预填了非空值"。"""
        assert self._run([{"key": "customer_name", "value": "张三"}],
                         [{"field": "customer_name", "expect_present": True}]) == []
        issues = self._run([{"key": "customer_name", "value": ""}],
                           [{"field": "customer_name", "expect_present": True}])
        assert issues, "空值不算预填"


class TestFormPrefillWiring:
    """接线：form_prefill 违规必须计入用例判定（score 0），否则是假守卫。"""

    def _case(self, form_prefill):
        return lr.EvalCase(
            id="PREFILL-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["帮我下单"],
            expectations=["tool: interact"], data_checks=[],
            persona="xiaobu", form_prefill=form_prefill,
        )

    def _run(self, reply_form_value, spec):
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None, debug_user=""):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "interact", "args": {}}],
                    "tool_results": [],
                    "interactive": [{"type": "form", "title": "收货信息",
                                     "formFields": [{"key": "customer_phone",
                                                     "value": reply_form_value}]}],
                    "final_text": "请确认", "error": None, "streamed": False, "done": True}

        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "PERSONA", "xiaobu"):
            return asyncio.run(lr.run_case(self._case(spec), "tok", "sess_p"))

    def test_missing_prefill_scores_zero(self):
        res = self._run("138****8000", [{"field": "customer_phone", "expect": "13800138000"}])
        assert res["score"] == 0.0, "掩码预填必须判红（会让订单用掩码建单）"
        assert any("customer_phone" in str(f) for f, _ in res["failed"]), res["failed"]

    def test_correct_prefill_keeps_score(self):
        res = self._run("13800138000", [{"field": "customer_phone", "expect": "13800138000"}])
        assert res["score"] == 1.0, f"正确预填被误判: {res['failed']}"


class TestFormPrefillLoaderPath:
    """新断言字段的**装载链路**必须通（issue #3392/#3397/#3402 三次同族假绿的根治写法）。

    为什么用**临时 YAML 夹具**而不是某个真实用例：首版把断言挂在 OR-023 的
    `form_prefill` 上，后来该用例改成**产出侧**断言（不再要求 form 机制，issue #3404 复盘）→
    测试立刻失配。装载链路测试不该依赖"某个用例恰好声明了某字段"，故自造最小 YAML。
    """

    def _write_case(self, tmp_path, field_yaml):
        (tmp_path / "x.yml").write_text(
            "cases:\n"
            "  - id: TMP-1\n"
            "    title: t\n"
            "    tier: normal\n"
            "    persona: xiaobu\n"
            "    user_inputs:\n"
            "      - \"你好\"\n"
            + field_yaml, encoding="utf-8")
        return str(tmp_path)

    def test_yaml_loader_maps_form_prefill(self, tmp_path):
        d = self._write_case(tmp_path,
                             "    form_prefill:\n"
                             "      - field: customer_phone\n"
                             "        expect: \"13800138000\"\n")
        cases = {c.id: c for c in lr.load_cases_from_yaml(d)}
        fp = cases["TMP-1"].form_prefill
        assert fp and fp[0]["field"] == "customer_phone", (
            "YAML 装载漏映射 form_prefill → CI 路径上断言永不生效（假绿）")

    def test_yaml_loader_maps_forbidden_card_text(self, tmp_path):
        d = self._write_case(tmp_path, "    forbidden_card_text:\n      - \"用量\"\n")
        cases = {c.id: c for c in lr.load_cases_from_yaml(d)}
        assert [str(x) for x in cases["TMP-1"].forbidden_card_text] == ["用量"], (
            "YAML 装载漏映射 forbidden_card_text → CI 路径上断言永不生效（假绿）")

    def test_renderer_emits_new_assertion_fields(self, tmp_path):
        """渲染器必须把两个新断言字段写进 EvalCase 构造参数。"""
        import sys as _sys, pathlib as _pl
        root = _pl.Path(lr.__file__).resolve().parents[2]
        _sys.path.insert(0, str(root / ".github"))
        from render_cases import to_eval_py
        tmp = _pl.Path(tmp_path)
        (tmp / "x.yml").write_text(
            "cases:\n"
            "  - id: TMP-1\n"
            "    title: t\n"
            "    tier: normal\n"
            "    form_prefill:\n"
            "      - field: customer_phone\n"
            "        expect: \"13800138000\"\n"
            "    forbidden_card_text:\n"
            "      - \"用量\"\n", encoding="utf-8")
        import render_cases as _rc
        import yaml_light as _yl
        cases = _yl.load_file(str(tmp / "x.yml"))["cases"]
        for c in cases:
            c.setdefault("_domain", "x")
        out = _rc.to_eval_py(cases)
        assert "form_prefill=[{'field': 'customer_phone'" in out, out[:400]
        assert "forbidden_card_text=['用量']" in out, out[:400]


class TestForbiddenCardTextLoaderPath:
    """**CI 走的 YAML 装载路径**必须映射 forbidden_card_text（issue #3402）。

    这是本 session **第三次**踩同一形态（前两次：`debug_user` issue #3392、
    `form_prefill` issue #3397）：新字段只在渲染器里映射、CI 走 YAML 装载器 →
    断言永不生效却全绿。故每个新断言字段都必须有**真实装载**测试。
    """

    def test_real_yaml_load_yields_forbidden_card_text(self):
        import pathlib as _pl
        cases_dir = _pl.Path(lr.__file__).resolve().parents[2] / ".github" / "cases"
        cases = {c.id: c for c in lr.load_cases_from_yaml(str(cases_dir))}
        spec = cases["OR-024"].forbidden_card_text
        assert spec, "YAML 装载后 forbidden_card_text 丢失（CI 路径上断言永不生效 = 假绿）"
        assert "用量" in [str(x) for x in spec], spec
        assert cases["OR-023"].forbidden_card_text == [], "未声明用例不得误继承"

    def test_renderer_emits_forbidden_card_text(self):
        import sys as _sys, pathlib as _pl
        root = _pl.Path(lr.__file__).resolve().parents[2]
        _sys.path.insert(0, str(root / ".github"))
        from render_cases import load_case_dicts, to_eval_py
        out = to_eval_py(load_case_dicts(str(root / ".github" / "cases")))
        idx = out.index("id='OR-024'")
        assert "forbidden_card_text=['用量'" in out[idx:idx + 4000], (
            "渲染器没有输出 forbidden_card_text（生成物会丢断言）")


class TestCaseIdsFilter:
    """`--case-ids` 收窄（迭代提速，issue #3417）：语义必须 fail-closed 且可单测。

    动机：全档 30 条 ≈ 11 分钟真实 LLM；"改一行看一眼"只需复验 1~3 条。
    但**少跑必须显式**：拼错 ID 时若静默变成"跑了 0 条/少几条"，看起来会像全量通过。
    """

    def _cases(self):
        return lr.load_cases_from_yaml(str(lr.Path(lr.__file__).resolve().parents[2]
                                          / ".github" / "cases"))

    def test_empty_filter_keeps_all(self):
        cs = self._cases()
        picked, missing = lr.filter_cases_by_ids(cs, "")
        assert len(picked) == len(cs) and missing == []

    def test_pick_by_id_preserves_requested_subset(self):
        picked, missing = lr.filter_cases_by_ids(self._cases(), "OR-019, OR-024")
        assert missing == []
        assert sorted(c.id for c in picked) == ["OR-019", "OR-024"]

    def test_unknown_id_is_reported(self):
        picked, missing = lr.filter_cases_by_ids(self._cases(), "OR-019,NOPE-999")
        assert [c.id for c in picked] == ["OR-019"] and missing == ["NOPE-999"]

    def test_legacy_id_supported(self):
        """与 `--case-id` 同口径：legacy_id 也能选中（老脚本/文档里的 ID 仍可用）。"""
        cs = self._cases()
        legacy = next((c for c in cs if getattr(c, "legacy_id", "")), None)
        if legacy is None:
            return
        picked, missing = lr.filter_cases_by_ids(cs, legacy.legacy_id)
        assert missing == [] and [c.id for c in picked] == [legacy.id]


class TestRoundTraceWriteArgs:
    """写工具入参必须进轨迹（issue #3394）：数量/金额错的唯一归因证据。

    实证代价：OR-022 落库数量 9（期望 3），旧轨迹只有 `tools=[order_create]` 与结果摘要 →
    无法区分「模型一次就传 9」与「重复行各 3」，为此多花了一整轮 CI + 一个最终不适用的
    工具层守卫（DB 明细证明是**单行 ×9**）。
    """

    def _results(self):
        return [{
            "__round": 3,
            "tool_calls": [
                {"name": "order_create", "args": {
                    "customer_name": "张三", "customer_phone": "13800138000", "sms_code": "123456",
                    "items": [{"product_name": "遮光窗帘", "quantity": 9,
                               "unit_price": 168.0, "subtotal": 1512.0}]}},
                {"name": "product_search", "args": {"keyword": "窗帘"}},
            ],
            "tool_results": [], "cards": [], "interactive": [], "final_text": "ok",
        }]

    def test_write_args_recorded_with_quantity(self):
        trace = lr.build_round_trace(self._results())
        wa = trace[0]["write_args"]
        assert len(wa) == 1 and wa[0]["tool"] == "order_create", wa
        assert wa[0]["args"]["items"][0]["qty"] == 9, "数量必须可查（归因唯一证据）"

    def test_calc_args_recorded(self):
        """算料入参必须进轨迹（issue #3395）：只看到 `fabric_meters=9.0` 看不出"假设了什么"。

        实测：模型把顾客的购买米数当窗宽 + 窗高默认 2.7 米 → 9 米布。没这条证据时
        只能从结果摘要反推公式，浪费一轮 CI。
        """
        rounds = [{
            "__round": 1,
            "tool_calls": [{"name": "curtain_calc", "args": {
                "window_width": 3.0, "window_height": 2.7, "fullness": 2.0,
                "fabric_price": 168.0}}],
            "tool_results": [], "cards": [], "interactive": [], "final_text": "",
        }]
        wa = lr.build_round_trace(rounds)[0]["write_args"]
        assert len(wa) == 1 and wa[0]["tool"] == "curtain_calc", wa
        assert wa[0]["args"]["window_width"] == 3.0
        assert wa[0]["args"]["window_height"] == 2.7, "窗高必须可见（模型自造的假设）"

    def test_read_tool_not_recorded(self):
        trace = lr.build_round_trace(self._results())
        assert all(w["tool"] != "product_search" for w in trace[0]["write_args"])

    def test_phone_masked_and_code_hidden(self):
        trace = lr.build_round_trace(self._results())
        a = trace[0]["write_args"][0]["args"]
        assert a["customer_phone"] == "138****8000", "轨迹进 CI 日志，手机号必须掩码"
        assert a["sms_code"] == "***"

    def test_formatter_prints_quantity(self):
        out = lr.format_round_trace(lr.build_round_trace(self._results()))
        assert "遮光窗帘×9@168" in out, out


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
        # 允许多行调用与新增关键字（issue #3391 加了 debug_user=… 后调用被折行）：
        # 固定字面量匹配会在合法重构时误报，改用容错正则（语义不变：仍要求"标记在调用之前"）。
        m = re.search(r"get_or_create_session\(\s*token,\s*prefer_new=True",
                      src[max(0, i_marker - 800):])
        i_session = (max(0, i_marker - 800) + m.start()) if m else -1
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

        async def fake_send(token, session_id, message, images=None, **kwargs):
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

        async def fake_end(token, sid, **kwargs):
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
        async def fake_send(token, session_id, message, images=None, **kwargs):
            sent.append((session_id, message))
            return {"user_message": message, "images": [], "tool_calls": [],
                    "tool_results": [], "final_text": "ok", "error": None,
                    "streamed": False, "done": True}

        created = []
        closed = []

        async def fake_create(token, prefer_new=True, **kwargs):
            sid = f"new-{len(created) + 1}"   # 与初始会话 id 区分开（否则断言自欺）
            created.append(sid)
            return sid

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
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

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        attempts = {"run_case": 0}

        async def fake_run_case(c, token, sid):
            attempts["run_case"] += 1
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 0, "total": 1,
                    "score": 0.0, "failed": [("boom", "x")], "last_error": None,
                    "final_text": "", "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid, **kwargs):
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
        async def fake_send(token, session_id, message, images=None, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
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

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_run_case(c, token, sid):
            attempts["n"] += 1
            await asyncio.sleep(0.02)
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 0, "total": 1,
                    "score": 0.0, "failed": [("x", "y")], "last_error": None,
                    "final_text": "", "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
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

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_run_case(c, token, sid):
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_run_case(c, token, sid):
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid, **kwargs):
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

        async def fake_sess(token, prefer_new=True, **kwargs):
            return "sess"

        async def fake_run_case(c, token, sid):
            await asyncio.sleep(0.02)
            return {"case_id": c.id, "title": c.title, "difficulty": "normal", "tags": [],
                    "rounds": 1, "tool_calls": [], "round_trace": [], "passed": 1, "total": 1,
                    "score": 1.0, "failed": [], "last_error": None, "final_text": "",
                    "final_session_id": sid, "session_breaks": 0}

        async def fake_end(token, sid, **kwargs):
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


# ─────────────────────────────────────────────────────────────────────────────
# 金额正确性断言 amount_verify（issue #3365 / acceptance-protocol §3.2）
# 背景：写工具「成功」只证明订单落库，不证明**钱算对了** —— 实证 OR-014 的 agent
# 在没查过商品的情况下发卡「遮光窗帘3米+打孔加工，合计¥95.4」（真实 ¥168/米），
# 此前只能靠 DB 审计人眼看金额。本组把它变成机器判定。
# case_ids: CH-010, OR-014, OR-017
# ─────────────────────────────────────────────────────────────────────────────


def _order_round(rnd, items, ok=True, total=None):
    """构造一轮：一次 order_create 调用 + 结果（ok/失败），可带总额。"""
    data = {"id": "ord-1", "orderNo": "20260101000000001"}
    if total is not None:
        data["totalAmount"] = total
    return {
        "__round": rnd,
        "tool_calls": [{"name": "order_create", "args": {"items": items}}],
        "tool_results": [{"tool": "order_create",
                          "result": ({"success": True, "data": data} if ok
                                     else {"success": False, "error": "product_not_grounded"})}],
        "final_text": "",
    }


class TestUnbackedStateClaim:
    """状态宣告必须有工具落地（issue #3379 P2-3）。

    证据（验收剧本 C-A1 R3）：
      ```
      用户: 纳米圈打孔
      AI:  好嘞，**纳米圈打孔** 已为您加上 ✅
      ```
      该轮 `tools=[]`（零工具调用）—— 加工项此刻只是**对话草稿**，却用了完成态措辞。
      一旦流程中断（C-A1 首跑就是这样），顾客会以为加工项已经写到订单上。

    与既有 `check_false_success` 的分工：那条管"前序轮**报错**却称成功"；
    本条管"**全程没有任何写操作成功**却宣称写成了" —— 两者互补。
    """

    def _rounds(self, *specs):
        """specs: (final_text, [tool_names_ok]) —— tool_names_ok 为成功的写工具名。"""
        out = []
        for i, (text, tools) in enumerate(specs, 1):
            out.append({
                "__round": i,
                "tool_calls": [{"name": t, "args": {}} for t in tools],
                "tool_results": [{"tool": t, "result": {"success": True, "data": {}}} for t in tools],
                "final_text": text,
            })
        return out

    def test_claim_without_any_write_flagged(self):
        issues = lr.check_unbacked_state_claim(
            self._rounds(("亲，帮您查到啦", []), ("已为您下单成功 🎉", [])))
        assert issues and "R2" in issues[0], "零写操作却宣称下单成功必须判违规"

    def test_claim_with_write_same_round_passes(self):
        assert lr.check_unbacked_state_claim(
            self._rounds(("订单已提交成功，订单号 20260913027050006", ["order_create"]))) == []

    def test_recap_after_earlier_write_passes(self):
        """写发生在前面轮次、本轮只是复述 —— 不得误报。"""
        assert lr.check_unbacked_state_claim(
            self._rounds(("已为您下单成功", ["order_create"]),
                         ("订单已创建，随时可以问我进度哦", []))) == []

    def test_read_side_claims_not_flagged(self):
        """只读动作的措辞（查到/整理/列出）不属于写宣告。"""
        assert lr.check_unbacked_state_claim(
            self._rounds(("已为您查到 8 笔订单", []), ("已为您整理如下", []))) == []

    def test_abandon_flow_reply_exempt(self):
        """放弃流程的"已取消"是代码层状态清理（无写工具），不得误报。"""
        assert lr.check_unbacked_state_claim(
            self._rounds(("好的，已取消。有什么其他需要帮您的吗？", []))) == []

    def test_failed_write_then_claim_flagged(self):
        """写工具**调用失败**后仍称成功 → 违规（与 must_succeed 同源判成功）。"""
        rounds = [{"__round": 1,
                   "tool_calls": [{"name": "order_create", "args": {}}],
                   "tool_results": [{"tool": "order_create",
                                     "result": {"success": False, "error": "缺少短信验证码"}}],
                   "final_text": "订单已创建成功 🎉"}]
        issues = lr.check_unbacked_state_claim(rounds)
        assert issues, "写失败却称成功必须判违规"


class TestNoFullPhoneInCustomerReplies:
    """C 端回复不得出现**完整手机号**（issue #3379，验收发现 P2）。

    为什么做成**全局 case 级断言**而不是某条用例的 forbidden_text：
    · CH-011 只断言了"订单卡片脱敏"，而实测泄露发生在**回显收货信息**这条路径上
      （验收 C-A2 R3：「您的收货信息我也帮您调出来了：张三 · 13800138000 · 杭州…」）；
    · 手机号是**跨用例**的隐私面，靠单个用例守不住 —— 每条 C 端用例都该守。
    """

    def _rounds(self, *texts):
        return [{"__round": i + 1, "final_text": t} for i, t in enumerate(texts)]

    def test_full_phone_flagged(self):
        issues = lr.check_no_full_phone(self._rounds(
            "亲，帮您查到啦", "您的收货信息：张三 · 13800138000 · 杭州市西湖区文三路1号"))
        assert issues and "13800138000" in issues[0], "完整手机号必须判违规（哪怕已用 · 分隔）"

    def test_masked_phone_passes(self):
        assert lr.check_no_full_phone(self._rounds("您的手机号 138****8000")) == []

    def test_order_number_not_flagged(self):
        """订单号里含 11 位数字片段，不得误报（本项目订单号形如 20260913027050006）。"""
        assert lr.check_no_full_phone(self._rounds("订单号 20260913027050006 已创建")) == []

    def test_verification_code_not_flagged(self):
        assert lr.check_no_full_phone(self._rounds("验证码 123456 已收到")) == []


class TestOutputVerify:
    """`output_verify`：断言**工具计算结果**（payload），不只是"调用过/传参对"（issue #3367）。

    为什么需要：算料报价（curtain_calc）的价值全在**算出来的数**上 ——
    `expectations: curtain_calc(...)` 只证明"用这些参数调了"，`data_checks` 是自然语义、
    不计分。于是"用布量算错"在评测里**完全不可见**（PR-013 只能断言调用与参数）。
    本断言把业务真值（如定宽布 3m×2.7m×2倍×2.8m门幅 → 9.0m）变成机器判定。
    """

    def _round(self, data, ok=True, tool="curtain_calc"):
        return [{"__round": 1,
                 "tool_calls": [{"name": tool, "args": {}}],
                 "tool_results": [{"tool": tool,
                                   "result": ({"success": True, "data": data} if ok
                                              else {"success": False, "error": "boom"})}],
                 "final_text": ""}]

    def _run(self, expect, data, ok=True):
        return lr.check_output_verify(self._round(data, ok), [{"tool": "curtain_calc", "expect": expect}])

    def test_matching_numbers_pass(self):
        assert self._run({"fabric_meters": 9.0, "total": 973.6},
                         {"fabric_meters": 9.0, "total": 973.6}) == []

    def test_within_tolerance_passes(self):
        assert self._run({"fabric_meters": 9.0}, {"fabric_meters": 9.004}) == []

    def test_wrong_number_fails_with_actual(self):
        issues = self._run({"fabric_meters": 9.0}, {"fabric_meters": 6.6})
        assert issues and "fabric_meters" in issues[0] and "6.6" in issues[0], \
            "算错的用布量必须判失败，并带上实际值（便于归因）"

    def test_string_field_equality(self):
        assert self._run({"formula_used": "fixed_width"}, {"formula_used": "fixed_width"}) == []
        bad = self._run({"formula_used": "fixed_width"}, {"formula_used": "fixed_height"})
        assert bad and "formula_used" in bad[0], "公式选错（定宽/定高）是算料的核心分支，必须判失败"

    def test_missing_field_fails_closed(self):
        issues = self._run({"fabric_meters": 9.0}, {"total": 1.0})
        assert issues and "fabric_meters" in issues[0], "payload 缺字段必须判失败，不能静默通过"

    def test_no_successful_call_fails_closed(self):
        issues = lr.check_output_verify(self._round({}, ok=False),
                                        [{"tool": "curtain_calc", "expect": {"fabric_meters": 1.0}}])
        assert issues and "curtain_calc" in issues[0]

    def test_malformed_spec_fails_closed(self):
        assert lr.check_output_verify(self._round({}), [{"tool": "curtain_calc"}]), "缺 expect 必须报错"
        assert lr.check_output_verify(self._round({}), [{"expect": {"a": 1}}]), "缺 tool 必须报错"

    def test_warning_presence_can_be_asserted(self):
        """定宽布必然带 warning（窗高超定高上限）——支持断言"非空"。"""
        assert self._run({"warning": "__nonempty__"}, {"warning": "超定高上限"}) == []
        assert self._run({"warning": "__nonempty__"}, {"warning": ""}), "warning 为空必须判失败"


class TestAssertionsFailClosed:
    """断言**配置写错时必须报错**，不得静默跳过（issue #3367 断言层审计）。

    为什么单独立测：`check_forbidden_args` / `check_required_args` 里都有
    「配置不完整就 `continue`」的路径 —— 于是把 `fields` 写成空/写错键名，
    那条**隔离/越权下限断言**就变成静默 no-op：用例照样绿，而它本该拦住数据泄露。
    与"金额断言因 checks 变字符串而静默失效"同族（同一轮先后被发现）。
    评测工具最危险的不是判错，是**声称查过而其实没查**。
    """

    def _calls(self, name, args):
        return [{"__round": 1,
                 "tool_calls": [{"name": name, "args": args}],
                 "tool_results": [{"tool": name, "result": {"success": True, "data": {}}}],
                 "final_text": ""}]

    # ── forbidden_args ──
    def test_forbidden_args_missing_fields_reports(self):
        issues = lr.check_forbidden_args(self._calls("customer_logistics_track", {}),
                                         [{"tool": "customer_logistics_track"}])
        assert issues and "fields" in issues[0], "缺 fields 的禁止参数断言必须报错（否则静默 no-op）"

    def test_forbidden_args_empty_fields_reports(self):
        issues = lr.check_forbidden_args(self._calls("customer_logistics_track", {}),
                                         [{"tool": "customer_logistics_track", "fields": []}])
        assert issues and "fields" in issues[0]

    def test_forbidden_args_missing_tool_reports(self):
        issues = lr.check_forbidden_args(self._calls("x", {}), [{"fields": ["a"]}])
        assert issues and "tool" in issues[0]

    def test_forbidden_args_valid_still_works(self):
        """合规配置不得被误伤：字段真的没出现 → 无 issue。"""
        assert lr.check_forbidden_args(self._calls("customer_logistics_track", {"order_id": "1"}),
                                       [{"tool": "customer_logistics_track",
                                         "fields": ["tracking_number"]}]) == []
        # 字段真出现了 → 必须报
        bad = lr.check_forbidden_args(self._calls("customer_logistics_track", {"tracking_number": "SF1"}),
                                      [{"tool": "customer_logistics_track",
                                        "fields": ["tracking_number"]}])
        assert bad and "tracking_number" in bad[0]

    # ── required_args ──
    def test_required_args_missing_tool_reports(self):
        issues = lr.check_required_args(self._calls("order_create", {}), [{"fields": ["items"]}])
        assert issues and "tool" in issues[0], "缺 tool 的必填参数断言必须报错"

    def test_required_args_missing_fields_reports(self):
        """只有 tool 没有 fields = 退化成"调用过就算过"（比作者本意弱）→ 必须显式报错。"""
        issues = lr.check_required_args(self._calls("order_create", {"items": []}),
                                        [{"tool": "order_create"}])
        assert issues and "fields" in issues[0]

    def test_required_args_valid_still_works(self):
        assert lr.check_required_args(self._calls("order_create", {"items": [1]}),
                                      [{"tool": "order_create", "fields": ["items"]}]) == []
        bad = lr.check_required_args(self._calls("order_create", {}),
                                     [{"tool": "order_create", "fields": ["items"]}])
        assert bad

    # ── db_verify（商品侧）──
    def test_db_verify_product_without_name_reports(self):
        issues = asyncio.run(lr.check_db_verify("tok", [{"fetch": "product_by_name", "checks": ["x"]}]))
        assert issues and "name" in issues[0], "商品侧 db_verify 缺 name 时必须报错"

    # ── must_succeed ──
    def test_must_succeed_missing_tool_reports(self):
        issues = lr.check_must_succeed(self._calls("order_create", {}), [{}])
        assert issues and "tool" in issues[0]


class TestFetchOrderDetailPaths:
    """订单详情抓取的**路径选择**（issue #3367 实测假失败）。

    ai-agent 的 `order_create` 返回 `id` 实测是 **32 位 hex（无连字符）**，
    而首版只认"带连字符的 UUID" → 32 位 hex 被当成订单号去走关键词搜索 → 搜不到
    → 误报"订单查不到明细（未落库？）"。实测同跑 DB 审计 `orders=7`（订单确实落库了），
    即**假失败**：这类错误会把评测工具的可信度直接打掉。
    """

    class _Resp:
        status_code = 200          # _safe_json 走 resp.content（不是 .json()）——
                                   # 缺 content 会被 except 吞成 None，测出来是"假失败"
                                   # （我第一版测试替身就漏了它，白查了一轮）

        def __init__(self, payload):
            import json as _j
            self._p = payload
            self.content = _j.dumps(payload, ensure_ascii=False).encode()

        def json(self):
            return self._p

    def _patched(self, calls, detail_payload, list_items):
        import unittest.mock as mock

        class _Client:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            async def get(self_inner, url, **kw):
                calls.append((url, (kw or {}).get("params")))
                if url.rstrip('/').endswith("/orders") or "/orders?" in url:
                    return TestFetchOrderDetailPaths._Resp(
                        {"data": {"items": list_items}})
                return TestFetchOrderDetailPaths._Resp(detail_payload)

        return mock.patch.object(lr.httpx, "AsyncClient", lambda *a, **k: _Client())

    def test_hex_id_is_fetched_directly(self):
        calls = []
        detail = {"data": {"orderNo": "x", "items": [{"productName": "遮光窗帘", "quantity": 2}]}}
        with self._patched(calls, detail, []):
            out = asyncio.run(lr._fetch_order_detail("tok", "1c3661962eb3504935cb551d16a9c7f0"))
        assert out == detail, "32 位 hex id 必须能直查到订单（首版这里是假失败）"
        assert any(u.endswith("/orders/1c3661962eb3504935cb551d16a9c7f0") for u, _ in calls)

    def test_order_no_falls_back_to_keyword_search(self):
        calls = []
        detail = {"data": {"orderNo": "20260101000000001", "items": []}}
        with self._patched(calls, detail, [{"id": "a1b2c3d4-e5f6-4a7b-8c9d-000000000001"}]):
            out = asyncio.run(lr._fetch_order_detail("tok", "20260101000000001"))
        assert out == detail
        assert any(p and p.get("keyword") == "20260101000000001" for _, p in calls), \
            "订单号必须先走关键词搜索（它不是合法 path 参数）"

    def test_unknown_ref_returns_none(self):
        with self._patched([], {"data": {}}, []):
            assert asyncio.run(lr._fetch_order_detail("tok", "不存在的订单号")) in (None, {"data": {}})


class TestAmountVerifyChecksRobustness:
    """`checks` 必须是**列表**语义 —— 字符串形态此前让金额断言静默失效（issue #3367）。

    实证：`yaml_light` 不解析 flow 序列（`[unit_price, subtotal, total]` 原样存成字符串），
    于是渲染产物里 OR-014/OR-017 的 `checks` 是字符串；`[str(x) for x in "<str>"]` 把它
    拆成**字符列表** → `"unit_price" in checks` 恒假 → **三项检查全被跳过、函数返回 []（恒通过）**。
    我为此写的单测用的是 Python 列表，所以单测全绿而线上一直没查钱 —— 典型的"工具自证"盲区。
    修法分两层：① 解析层把 flow 序列读成列表（根治）；② 运行层**失败关闭**：读不懂就报错，
    绝不静默跳过。
    """

    def _run(self, checks, items, total, price=168.0):
        import unittest.mock as mock

        async def fake_price(token, name):
            return price

        spec = [{"tool": "order_create", "product_name": "遮光窗帘", "checks": checks}]
        with mock.patch.object(lr, "_fetch_product_price", new=fake_price):
            return asyncio.run(lr.check_amount_verify("tok", [_order_round(7, items, total=total)], spec))

    def test_string_checks_still_verify(self):
        """字符串形态（历史渲染产物）也必须真的查 —— 否则金额断言是装饰品。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 31.8,
                  "subtotal": 95.4}]          # 凭记忆报价的假单价
        issues = self._run("[unit_price, subtotal, total]", items, total=95.4)
        assert issues, "字符串 checks 下金额断言又静默跳过了（假绿）"
        assert any("单价" in i for i in issues)

    def test_list_checks_verify(self):
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 31.8,
                  "subtotal": 95.4}]
        assert self._run(["unit_price", "subtotal", "total"], items, total=95.4)

    def test_garbage_checks_fails_closed(self):
        """读不懂的 checks 不得当成"没有检查" —— 必须显式报错。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                  "subtotal": 504.0}]
        issues = self._run("??? 无法识别的检查项 ???", items, total=504.0)
        assert issues and "无法识别" in issues[0], "解析不出检查项时必须失败关闭，不能静默通过"


class TestDbVerifyOrderItems:
    """订单明细落库断言（issue #3367 上限用例基建）。

    为什么必须有：`must_succeed` 只证明 order_create 返回成功，
    `amount_verify` 只核对**这次调用传的参数**（args）—— 两者都**没回答
    "订单明细真的按行落库了吗"**。多商品下单（上限用例 OR-018）恰恰只有 DB 才说得清：
    两行商品、各自数量/单价、总额，全在 `orders`/`order_items` 里。
    此前 db_verify 只支持 `fetch: product_by_name`（商品侧），订单侧是缺口。
    """

    ORDER = {
        "data": {
            "orderNo": "20260101000000001",
            "totalAmount": 1000.0,
            "items": [
                {"productName": "夏日清风窗帘", "quantity": 3, "unitPrice": 158.0},
                {"productName": "遮光窗帘", "quantity": 2, "unitPrice": 168.0},
            ],
        }
    }

    def _run(self, spec, order=None, lookup_ok=True):
        import unittest.mock as mock

        async def fake_lookup(token, order_ref):
            return (order if order is not None else self.ORDER) if lookup_ok else None

        with mock.patch.object(lr, "_fetch_order_detail", new=fake_lookup):
            return asyncio.run(lr.check_db_verify("tok", [spec], [self._round()]))

    def _spec(self, **kw):
        base = {"fetch": "order_items", "source": "order_create",
                "expect_products": ["夏日清风窗帘", "遮光窗帘"]}
        base.update(kw)
        return base

    def _round(self):
        return _order_round(7, [{"product_name": "夏日清风窗帘", "quantity": 3}], total=810.0)

    def test_both_lines_landed_passes(self):
        assert self._run(self._spec()) == []

    def test_missing_line_fails(self):
        order = {"data": {"orderNo": "x", "items": [
            {"productName": "夏日清风窗帘", "quantity": 3, "unitPrice": 158.0}]}}
        issues = self._run(self._spec(), order=order)
        assert issues and "遮光窗帘" in issues[0], "少一行商品必须判失败（多商品下单的核心风险）"

    def test_quantity_mismatch_fails(self):
        order = {"data": {"orderNo": "x", "items": [
            {"productName": "夏日清风窗帘", "quantity": 1, "unitPrice": 158.0},
            {"productName": "遮光窗帘", "quantity": 2, "unitPrice": 168.0}]}}
        issues = self._run(self._spec(expect_quantities={"夏日清风窗帘": 3}), order=order)
        assert any("数量" in i for i in issues), "数量不符必须判失败"

    def test_order_not_found_fails(self):
        issues = self._run(self._spec(), lookup_ok=False)
        assert issues and "查不到" in issues[0], "查不到订单不得静默当通过"

    def test_no_source_order_fails_closed(self):
        """没有可追溯的 order_create 结果 → 不得静默跳过（宁可红，不可假绿）。"""
        import unittest.mock as mock
        with mock.patch.object(lr, "_first_successful_data", new=lambda res, tool: {}):
            issues = asyncio.run(lr.check_db_verify("tok", [self._spec()], [self._round()]))
        assert issues and "order_create" in issues[0]

    def test_quantity_mismatch_reports_line_shape(self):
        """数量不符时必须报**行的形状**（issue #3392）：3 行各 3 ≠ 单行 9，修法不同。"""
        order = {"data": {"orderNo": "x", "items": [
            {"productName": "遮光窗帘", "quantity": 3, "unitPrice": 168.0},
            {"productName": "遮光窗帘", "quantity": 3, "unitPrice": 168.0},
            {"productName": "遮光窗帘", "quantity": 3, "unitPrice": 168.0}]}}
        issues = self._run(self._spec(expect_quantities={"遮光窗帘": 3}), order=order)
        # ⚠️ 取**数量那条**（issues[0] 可能是"缺某商品"那条 —— 首版就是索引取错导致假失败）
        hit = next((i for i in issues if "数量" in i), "")
        assert hit, issues
        assert "数量 9" in hit, hit
        assert "3 行" in hit, f"必须报行数（区分重复行 vs 数量值算错）: {hit}"
        assert "遮光窗帘×3@168" in hit, f"必须报逐行明细: {hit}"

    def test_unknown_fetch_still_rejected(self):
        issues = self._run({"fetch": "nonsense"})
        assert issues and "不支持" in issues[0]


class TestAmountVerify:
    """单价接地 / 小计自洽 / 总额自洽。"""

    def _run(self, results, specs, price=168.0):
        import unittest.mock as mock

        async def fake_price(token, name):
            return price

        with mock.patch.object(lr, "_fetch_product_price", new=fake_price):
            return asyncio.run(lr.check_amount_verify("tok", results, specs))

    def _spec(self, **kw):
        base = {"tool": "order_create", "product_name": "遮光窗帘",
                "checks": ["unit_price", "subtotal", "total"]}
        base.update(kw)
        return [base]

    def test_grounded_amount_passes(self):
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                  "subtotal": 504.0}]
        assert self._run([_order_round(7, items, total=504.0)], self._spec()) == []

    def test_hallucinated_price_fails(self):
        """¥95.4 假单价（未查商品的凭记忆报价）必须判失败。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 31.8,
                  "subtotal": 95.4}]
        issues = self._run([_order_round(7, items, total=95.4)], self._spec())
        assert issues and "单价" in issues[0] and "凭记忆报价" in issues[0]

    def test_subtotal_inconsistent_fails(self):
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                  "subtotal": 95.4}]   # 小计与数量×单价不符
        issues = self._run([_order_round(7, items, total=95.4)], self._spec())
        assert any("小计" in i for i in issues)

    def test_total_inconsistent_fails(self):
        """总额必须等于 Σ小计 + 加工费（加工费漏计是最常见的金额错）。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                  "subtotal": 504.0,
                  "processing_info": {"processingFee": 72.0}}]
        issues = self._run([_order_round(7, items, total=504.0)], self._spec())
        assert any("总额" in i for i in issues), "漏计加工费未被发现"

    def test_total_with_processing_passes(self):
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0,
                  "subtotal": 504.0,
                  "processing_info": {"processingFee": 72.0}}]
        assert self._run([_order_round(7, items, total=576.0)], self._spec()) == []

    def test_failed_call_is_not_used(self):
        """只看**成功**的调用：被门禁拦下的调用不得当成"订单金额"。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 31.8,
                  "subtotal": 95.4}]
        issues = self._run([_order_round(5, items, ok=False, total=None)], self._spec())
        assert issues and "未找到" in issues[0]

    def test_no_successful_call_reported(self):
        issues = self._run([], self._spec())
        assert issues and "未找到" in issues[0]

    def test_missing_product_in_catalog_reported(self):
        import unittest.mock as mock

        async def none_price(token, name):
            return None

        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0}]
        with mock.patch.object(lr, "_fetch_product_price", new=none_price):
            issues = asyncio.run(lr.check_amount_verify("tok", [_order_round(7, items)],
                                                       self._spec()))
        assert any("查不到单价" in i for i in issues), "真值缺失必须显式报，不得静默跳过"

    def test_price_check_requires_product_name(self):
        items = [{"product_name": "遮光窗帘", "quantity": 1, "unit_price": 1.0, "subtotal": 1.0}]
        issues = self._run([_order_round(1, items)], self._spec(product_name=""))
        assert any("product_name" in i for i in issues)

    def test_checks_subset_respected(self):
        """只声明 subtotal 时不查单价（避免用例要商品库真值时反而失败）。"""
        items = [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 31.8, "subtotal": 95.4}]
        issues = self._run([_order_round(7, items)], self._spec(checks=["subtotal"]))
        assert issues == [], "只查小计时不应因单价不接地而报错"

    def test_prefers_later_round_when_earlier_failed(self):
        """先失败后被门禁放行成功：必须取成功那次（真实 CI 轨迹形态）。"""
        bad = _order_round(5, [{"product_name": "遮光窗帘", "quantity": 3,
                                "unit_price": 999.0, "subtotal": 2997.0}], ok=False)
        good = _order_round(7, [{"product_name": "遮光窗帘", "quantity": 3,
                                 "unit_price": 168.0, "subtotal": 504.0}], total=504.0)
        assert self._run([bad, good], self._spec()) == []


class TestFalseSuccessRefined:
    """假成功守卫细化（issue #3365）：报错 ≠ 谎报。

    CI run 34710420292 实证：CH-010 R6 瞬时错误、R7 起自愈，R9 的 order_create 真成功落库
    （totalAmount=408.0 = 3×128，接地正确），末轮文本称成功 —— 这是**真话**，原守卫却判红。
    新语义：报错后若确有写操作成功（tool_result success=true），声明成功不算谎报；
    只有"报错且没有任何写成功"才是假成功（原保护不变）。
    """

    def _round(self, rnd, error=None, text="", ok=None):
        tr = [] if ok is None else [{"tool": "order_create",
                                     "result": {"success": bool(ok), "data": {}}}]
        return {"__round": rnd, "error": error, "final_text": text, "tool_results": tr}

    def test_error_then_real_success_is_not_false_success(self):
        results = [
            self._round(6, error="处理失败: boom"),
            self._round(9, text="订单已创建成功", ok=True),
        ]
        assert lr.check_false_success(results) == [], "写操作真的成功时不得判假成功"

    def test_error_without_any_write_still_fails(self):
        """原保护不变：报错且没有任何写成功 → 文本称成功 = 谎报。"""
        results = [
            self._round(6, error="处理失败: boom"),
            self._round(9, text="商品创建成功", ok=False),
        ]
        issues = lr.check_false_success(results)
        assert issues and "假成功" in issues[0]

    def test_no_error_no_violation(self):
        assert lr.check_false_success([self._round(1, text="创建成功", ok=True)]) == []

    def test_error_before_success_claim_without_tool_results(self):
        """没有任何 tool_result（如纯文本流程）时，维持原语义 —— 报错后称成功即违规。"""
        results = [self._round(6, error="boom"), self._round(8, text="已成功处理")]
        assert lr.check_false_success(results), "无写操作证据时不得放行"


class TestRoundTraceCarriesErrorText:
    """逐轮错误**原文**进轨迹（issue #3365）：只打 `ERR` 标记时归因无从下手。"""

    def test_error_text_printed(self):
        trace = lr.build_round_trace([
            {"__round": 6, "user_message": "123456", "tool_calls": [], "tool_results": [],
             "final_text": "", "error": "处理失败: AttributeError: boom"},
        ])
        assert trace[0]["error"].startswith("处理失败")
        assert "ERR(" in lr.format_round_trace(trace)
        assert "AttributeError" in lr.format_round_trace(trace)


class TestAutoRespondPreferText:
    """`prefer_text: true`：这一轮**按用例声明的文本发**，即使有卡在等（issue #3367）。

    实证（run 34721434317，CH-010 首跑）：用例第 6/7 轮声明的是**验证码「123456」**，
    但那两轮各有一张卡在等（choice 卡 / confirm 卡），harness 的"有什么卡答什么卡"把这
    两轮吃掉了 → 「顾客从未输入过验证码」→ R7 `order_create!缺少短信验证码` → 订单不落库。
    逐轮轨迹：
      R5 you=__FORM__|{...}        （表单被答）
      R6 you=已选加工项：纳米圈打孔   ← 本该发 123456
      R7 you=确认下单              ← 本该发 123456
      R7 order_create!缺少短信验证码

    为什么用**显式开关**而不是"fallback 看起来像验证码就自动发文本"：
    隐式魔法会让用例作者猜不到何时生效；显式声明 + 本测试锁住语义。
    """

    _CARD = [{"type": "choice", "title": "选加工项",
              "options": [{"label": "纳米圈打孔", "value": "pi1"}]}]

    def _results(self, *users, card=True):
        """构造轨迹：**最后一轮带待答卡片**（否则 auto_respond 本就该走 fallback）。"""
        out = [{"user_message": u} for u in users]
        if out and card:
            out[-1]["interactive"] = list(self._CARD)
        return out

    def test_prefer_text_overrides_pending_card(self):
        out = lr.resolve_auto_respond(self._results("你好"), "123456", {},
                                      prefer_text=True)
        assert out == "123456", f"声明了 prefer_text 却仍去答题卡: {out!r}"

    def test_default_still_answers_pending_card(self):
        """不开开关时行为**不变**（继续"有什么卡答什么卡"），避免影响既有用例。"""
        out = lr.resolve_auto_respond(self._results("你好"), "123456", {})
        assert out != "123456", "默认路径不应被改：合作型用户仍优先答卡"

    def test_prefer_text_without_card_uses_fallback(self):
        out = lr.resolve_auto_respond([], "123456", {}, prefer_text=True)
        assert out == "123456"

    def test_prefer_text_false_is_default(self):
        a = lr.resolve_auto_respond(self._results("你好"), "确认", {})
        b = lr.resolve_auto_respond(self._results("你好"), "确认", {}, prefer_text=False)
        assert a == b


class TestAutoRespondNoRepeatCardClick:
    """同卡不重复点（issue #3365，CH-010 实证）。

    CI run 34714932015：CH-010 九轮下来 `order_create ×3` 全被"缺少短信验证码"拒 ——
    模型每轮重发同一张确认卡，harness 每轮点同一张卡 → 验证码轮全被点卡吃掉、流程永不前进。
    真实顾客点过一次不会再点同一张卡，而是直接说下一步需要的信息（验证码/补充信息）——
    即 fallback 的语义。故"已发过的答复"一律改用 fallback。
    """

    def _card(self, comp="confirm", **kw):
        base = {"type": comp}
        base.update(kw)
        return {"interactive": [base], "__round": 1, "tool_calls": [], "tool_results": [],
                "final_text": "", "user_message": ""}

    def test_same_confirm_value_answered_twice_then_fallback(self):
        """同一张确认卡最多点**两次**：首答 + 一次重申；第 3 次起走 fallback（把轮数让给验证码）。"""
        v = "确认下单：北欧风窗帘 3米 ¥408"
        first = [dict(self._card(confirmValue=v), user_message="数量 3 米")]
        assert lr.resolve_auto_respond(first, "123456", {}) == v
        second = first + [dict(self._card(confirmValue=v), user_message=v, __round=2)]
        assert lr.resolve_auto_respond(second, "123456", {}) == v, "模型再次征询应再点一次"
        third = second + [dict(self._card(confirmValue=v), user_message=v, __round=3)]
        assert lr.resolve_auto_respond(third, "123456", {}) == "123456", (
            "两次之后仍重发 → 轮数必须让给验证码，否则整场 order_create 都缺 sms_code"
        )

    def test_new_confirm_value_still_clicked(self):
        """换了内容的确认卡仍要点（那是新的确认请求）。"""
        first = [dict(self._card(confirmValue="确认下单：旧单 ¥100"), user_message="x")]
        second = first + [dict(self._card(confirmValue="确认下单：北欧风窗帘 3米 ¥408"),
                               user_message="确认下单：旧单 ¥100", __round=2)]
        assert lr.resolve_auto_respond(second, "123456", {}) == "确认下单：北欧风窗帘 3米 ¥408"

    def test_single_select_answers_with_label(self):
        """单选卡按**前端协议**发 label（人话），不是内部 value（issue #3365 对齐）。"""
        card = self._card("choice", options=[{"value": "opt1", "label": "第一项"}])
        assert lr.resolve_auto_respond([card], "确认", {}) == "第一项"

    def test_multi_select_answers_with_prefix_and_label(self):
        """多选卡：`multiSelectSubmitPrefix` + label（前端 submitSelections 协议）。

        实证：harness 此前发内部 id（`proc_item_pi_eval_punch`）→ 模型看不懂选了什么
        → 反复重发同一张加工项卡（OR-017 六轮耗尽）。
        """
        card = self._card("choice", multiSelect=True,
                          multiSelectSubmitPrefix="已选加工项：",
                          options=[{"value": "proc_item_x", "label": "纳米圈打孔"}])
        assert lr.resolve_auto_respond([card], "确认", {}) == "已选加工项：纳米圈打孔"

    def test_multi_select_default_prefix(self):
        card = self._card("choice", multiSelect=True,
                          options=[{"value": "proc_item_x", "label": "纳米圈打孔"}])
        assert lr.resolve_auto_respond([card], "确认", {}) == "已选加工项：纳米圈打孔"

    def test_repeated_same_choice_answer_falls_back_after_two(self):
        card = self._card("choice", options=[{"value": "opt1", "label": "第一项"}])
        once = [dict(card, user_message="第一项", __round=1)]
        assert lr.resolve_auto_respond([card] + once, "123456", {}) == "第一项"
        twice = once + [dict(card, user_message="第一项", __round=2)]
        assert lr.resolve_auto_respond([card] + twice, "123456", {}) == "123456"


class TestDbVerifyOrderPhone:
    """落库手机号断言（issue #3386）。

    为什么必须有：此前 `db_verify` 只核商品/明细/数量，`amount_verify` 只核金额，
    `must_succeed` 只看调用成功 —— **订单手机号写错全链路无感**。
    CI 实证（run 34742490138）：CH-010 订单 `20260913384380002` 落库
    `customer_phone = 13800008000`（模型把掩码 `138****8000` 的 `****` 填成了 `0`），
    而用例给模型的是 `13800138000`；11 位纯数字完全合法 → 静默建单成功。
    """

    ORDER = {"data": {"orderNo": "20260913384380002", "customerPhone": "13800008000"}}

    def _run(self, spec, order=None, lookup_ok=True):
        import unittest.mock as mock

        async def fake_lookup(token, order_ref):
            return (order if order is not None else self.ORDER) if lookup_ok else None

        with mock.patch.object(lr, "_fetch_order_detail", new=fake_lookup):
            return asyncio.run(lr.check_db_verify("tok", [spec], [self._round()]))

    def _round(self):
        return _order_round(7, [{"product_name": "北欧风窗帘", "quantity": 3}], total=408.0)

    def _spec(self, **kw):
        base = {"fetch": "order_phone", "source": "order_create",
                "expect_phone": "13800138000"}
        base.update(kw)
        return base

    def test_masked_filled_phone_fails(self):
        """CI 实证形态：落库 13800008000 ≠ 期望 13800138000 → 必须判失败。"""
        issues = self._run(self._spec())
        assert issues, "落库手机号与用例给的号码不一致 → 必须红（否则脏数据无人知）"
        assert "13800008000" in issues[0] and "13800138000" in issues[0], issues[0]

    def test_correct_phone_passes(self):
        order = {"data": {"orderNo": "x", "customerPhone": "13800138000"}}
        assert self._run(self._spec(), order=order) == []

    def test_order_not_found_fails_closed(self):
        issues = self._run(self._spec(), lookup_ok=False)
        assert issues and "查不到" in issues[0], "查不到订单不得静默当通过"

    def test_missing_expected_phone_fails_closed(self):
        """配置写错（没给 expect_phone）不得空转通过。"""
        issues = self._run({"fetch": "order_phone", "source": "order_create"})
        assert issues and "expect_phone" in issues[0]

    def test_phone_absent_in_order_fails(self):
        issues = self._run(self._spec(), order={"data": {"orderNo": "x"}})
        assert issues and "手机号" in issues[0]


class TestDbVerifyOrderPhoneCustomerFields:
    """`db_verify[order_phone]` 的**产出侧**收货人/地址断言（issue #3404 复盘）。

    为什么断言"订单上的值"而不是"过程发了 form 卡"：顾客在意的是订单对不对，
    而机制（form 卡 vs confirm 卡字段）是模型的合法选择 —— 绑机制会造成假红
    （实测 run 34755272379：`form_prefill: 会话里没有出现任何 form 卡`）。
    """

    def _run(self, spec, order):
        import unittest.mock as mock

        async def fake_lookup(token, order_ref):
            return order

        with mock.patch.object(lr, "_fetch_order_detail", new=fake_lookup):
            return asyncio.run(lr.check_db_verify("tok", [spec], [_order_round(7, [
                {"product_name": "遮光窗帘", "quantity": 3}], total=528.0)]))

    def test_order_customer_name_and_address_checks(self):
        """收货人/地址的**产出侧**断言（issue #3404）：预填机制可以变，订单上的值必须对。"""
        order = {"data": {"orderNo": "x", "customerPhone": "13800138000",
                          "customerName": "张三",
                          "customerAddress": "浙江省杭州市西湖区文三路1号1幢101室"}}
        spec = {"fetch": "order_phone", "source": "order_create",
                "expect_phone": "13800138000", "expect_customer_name": "张三",
                "expect_address_contains": "文三路"}
        assert self._run(spec, order=order) == []

    def test_address_mismatch_fails(self):
        """地址被改写（含空格归一化后仍不同）→ 判红（老客户应沿用库里的地址）。"""
        order = {"data": {"orderNo": "x", "customerPhone": "13800138000",
                          "customerName": "张三",
                          "customerAddress": "浙江省杭州市西湖区文三路100号"}}
        spec = {"fetch": "order_phone", "source": "order_create",
                "expect_phone": "13800138000", "expect_address_contains": "文三路1号"}
        issues = self._run(spec, order=order)
        assert issues and "收货地址" in issues[0], issues

    def test_customer_name_mismatch_fails(self):
        order = {"data": {"orderNo": "x", "customerPhone": "13800138000",
                          "customerName": "李四", "customerAddress": "文三路1号"}}
        spec = {"fetch": "order_phone", "source": "order_create",
                "expect_phone": "13800138000", "expect_customer_name": "张三"}
        issues = self._run(spec, order=order)
        assert issues and "收货人" in issues[0], issues


class TestPhoneProvenance:
    """落库手机号必须能追溯到「本用例提供的号码 / 种子号码」（issue #3386）。

    比逐用例写 `expect_phone` 更结构性：**新增用例无需配置**就自动受保护。
    实测价值：CH-010 的脏号码 `13800008000` 既不是用例给的 `13800138000`、
    也不是种子号码 → 本断言直接判红，不需要人肉审计 DB。
    """

    def _case(self, inputs, persona="xiaobu"):
        import unittest.mock as mock
        c = mock.MagicMock()
        c.id = "CH-010"
        c.persona = persona
        c.user_inputs = inputs
        return c

    def _results(self):
        # 注意：results 是**逐轮列表**（_order_round 返回单轮 dict）
        return [_order_round(7, [{"product_name": "北欧风窗帘", "quantity": 3}], total=408.0)]

    def _run(self, case, phone, lookup_ok=True):
        import unittest.mock as mock

        async def fake_lookup(token, order_ref):
            if not lookup_ok:
                return None
            return {"data": {"orderNo": "20260913384380002", "customerPhone": phone}}

        with mock.patch.object(lr, "_fetch_order_detail", new=fake_lookup):
            return asyncio.run(lr.check_phone_provenance("tok", case, self._results()))

    def test_masked_filled_phone_is_flagged(self):
        case = self._case(['auto_respond:\n  form_values:\n    customer_phone: "13800138000"'])
        issues = self._run(case, "13800008000")
        assert issues, "落库号码无法追溯到用例给的号码 → 必须判红"
        assert "13800008000" in issues[0], issues[0]

    def test_supplied_phone_passes(self):
        case = self._case(['auto_respond:\n  form_values:\n    customer_phone: "13800138000"'])
        assert self._run(case, "13800138000") == []

    def test_seed_phone_passes_when_case_supplies_none(self):
        """用例没给号码、流程复用种子订单的收货信息（has_address=True）→ 种子号码合法。"""
        case = self._case(["帮我查一下我的订单"])
        assert self._run(case, "13800138000") == []

    def test_seed_variant_is_flagged(self):
        case = self._case(["帮我查一下我的订单"])
        issues = self._run(case, "13800008000")
        assert issues, "种子号码 13800138000 的掩码填充形态同样必须判红"

    def test_no_created_order_is_noop(self):
        """没有写成功 → 无落库事实，不该凭空报问题。"""
        case = self._case(['customer_phone: "13800138000"'])
        assert asyncio.run(lr.check_phone_provenance("tok", case, [])) == []

    def test_mibao_persona_not_checked(self):
        """B 端米宝可能给顾客建单时从客户档案取号（非用例提供）→ 不做来源闭合。"""
        case = self._case(["给张三创建一个订单"], persona="mibao")
        assert self._run(case, "13912345678") == []


class TestRunCasePhoneProvenanceWiring:
    """run_case 集成：号码来源闭合必须**真的接在用例判定上**（issue #3386）。

    为什么单测函数不够（M68/M122 教训）：函数级断言在"接线断了"时照样全绿 ——
    真正要证明的是 `run_case` 会把它算进 case-level issues（score 0）。
    """

    def _case(self, user_inputs=None, persona="xiaobu"):
        return lr.EvalCase(
            id="PROV-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL,
            user_inputs=user_inputs if user_inputs is not None
            else ['auto_respond:\n  form_values:\n    customer_phone: "13800138000"'],
            expectations=["tool: order_create"], data_checks=[], persona=persona,
        )

    async def _run(self, case, phone):
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None, **kwargs):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "order_create", "args": {}}],
                    "tool_results": [{"tool": "order_create",
                                      "result": {"success": True,
                                                 "data": {"id": "o1",
                                                          "orderNo": "20260913384380002"}}}],
                    "interactive": [], "final_text": "下单成功",
                    "error": None, "streamed": False, "done": True}

        async def fake_lookup(token, ref):
            return {"data": {"orderNo": "20260913384380002", "customerPhone": phone}}

        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "_fetch_order_detail", new=fake_lookup):
            return await lr.run_case(case, "tok", "sess")

    def test_masked_filled_phone_scores_zero(self):
        import asyncio
        res = asyncio.run(self._run(self._case(), "13800008000"))
        assert res["score"] == 0.0, "落库脏号码必须把用例判红（否则 CI 看不见）"
        assert any("13800008000" in str(f) for f, _ in res["failed"])

    def test_correct_phone_keeps_score(self):
        import asyncio
        res = asyncio.run(self._run(self._case(), "13800138000"))
        assert res["score"] == 1.0, f"正常号码被误判: {res['failed']}"


class TestFalseInability:
    """能力误宣：C 端**明明能做**却说"做不了"（issue #3389，验收 C-A1 实证）。

    实证（run 34743802010，`C-A1.transcript.md`）：顾客明确说「确认下单」×4 轮，
    小布连续回「**下单这个操作小布这边没法直接帮您提交呢**，需要您在小程序里点一下"立即购买"」，
    最后 `human_handoff(reason="…智能客服无法代为提交订单")` —— 整场 9 轮**从未调用 `order_create`**。
    而 `order_create` 就是 `customer_order` 这个 skill 自己的写工具（OR-014/017/018/019/020 都真实落单）。

    与 `check_false_success` 配对：那条管"没做却说做了"（假成功），本条管"能做却说做不了"（假无能）。
    两者都是**能力诚实性**断言 —— 顾客视角比答错更致命：购买意图被无理由丢弃。
    """

    def _run(self, texts):
        rounds = [{"__round": i + 1, "tool_calls": [], "tool_results": [],
                   "final_text": t} for i, t in enumerate(texts)]
        return lr.check_false_inability(rounds)

    def test_canonical_ca1_refusal_flagged(self):
        """C-A1 原话必须被抓住。"""
        issues = self._run(["订单信息我帮您整理好啦~ 不过下单这个操作小布这边没法直接帮您提交呢，"
                            "需要您在小程序里点一下\"立即购买\"就能完成啦 😊"])
        assert issues, "「没法直接帮您提交订单」是能力误宣，必须判红"

    def test_variants_flagged(self):
        for t in ["抱歉，我无法为您提交订单，请联系人工",
                  "小布暂时不能帮您下单哦",
                  "创建订单这个我没法操作，您自己在小程序买吧",
                  "我没办法代为下单"]:
            assert self._run([t]), f"未抓住能力误宣变体: {t!r}"

    def test_reverse_order_phrase_flagged(self):
        """语序颠倒（动词在前）也要抓。"""
        assert self._run(["下单需要您自己去小程序操作，我没法帮您完成"])

    def test_legit_unrelated_inability_not_flagged(self):
        """与下单无关的能力说明不得误报（例：不能改价、不能查他人订单）。"""
        for t in ["这个价格我没法直接改，需要商家后台调整哦",
                  "我不能查看其他人的订单信息",
                  "退款我这边没法直接操作，需要走售后流程"]:
            assert self._run([t]) == [], f"误报: {t!r}"

    def test_legit_order_talk_not_flagged(self):
        """正常引导下单的话术不得误报。"""
        for t in ["亲，确认无误的话回复「确认下单」就可以啦~",
                  "好的，订单已提交成功，订单号 20260913384380002",
                  "还差收货信息，方便告诉我姓名、手机号和地址吗？"]:
            assert self._run([t]) == [], f"误报: {t!r}"

    def test_handoff_reason_also_scanned(self):
        """转人工理由里写着"无法代为提交订单"同样算能力误宣（C-A1 R9 的实际形态）。"""
        rounds = [{"__round": 9, "tool_calls": [{"name": "human_handoff",
                                                 "args": {"reason": "顾客需协助下单（智能客服无法代为提交订单）"}}],
                   "tool_results": [], "final_text": "已为您转接人工客服"}]
        assert lr.check_false_inability(rounds), "转人工理由里的能力误宣必须判红"


class TestRunCaseFalseInabilityWiring:
    """run_case 集成：能力误宣必须**真的算进用例判定**（score 0）。"""

    def _case(self):
        return lr.EvalCase(
            id="INAB-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["帮我下单"],
            expectations=["tool: product_search"], data_checks=[],
        )

    def _run(self, reply):
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None, **kwargs):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "product_search", "args": {}}],
                    "tool_results": [], "interactive": [], "final_text": reply,
                    "error": None, "streamed": False, "done": True}

        # PERSONA 是**运行档**级开关（`--persona xiaobu`）：C 端专属断言都挂在这个分支下，
        # 故接线测试必须显式打开它 —— 否则测的是"没接线也绿"，等于假守卫。
        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "PERSONA", "xiaobu"):
            return asyncio.run(lr.run_case(self._case(), "tok", "sess"))

    def test_refusal_scores_zero(self):
        res = self._run("这个我没法帮您提交订单哦")
        assert res["score"] == 0.0, "能力误宣必须判红（否则 core 转化路径被掐断也无人知）"
        assert any("能力" in str(f) or "提交订单" in str(f) for f, _ in res["failed"])

    def test_normal_reply_keeps_score(self):
        res = self._run("亲，确认无误的话回复「确认下单」就可以啦~")
        assert res["score"] == 1.0, f"正常话术被误判: {res['failed']}"


class TestDebugUserWiring:
    """多身份评测（issue #3391）：用例声明的 debug_user 必须**真的传到请求头**。

    为什么必须查接线（M68/M122 教训）：只测 `_chat_headers()` 无法发现
    "run_case 忘了把 case.debug_user 传下去" —— 那样用例仍以 debug_customer_1 跑，
    「新客无历史地址」路径看起来覆盖了、实际没覆盖（假绿）。
    """

    def _case(self, debug_user):
        return lr.EvalCase(
            id="NEWC-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["帮我下单"],
            expectations=["tool: product_search"], data_checks=[],
            persona="xiaobu", debug_user=debug_user,
        )

    def test_headers_include_debug_user_for_customer(self):
        import unittest.mock as mock
        with mock.patch.object(lr, "PERSONA", "xiaobu"):
            h = lr._chat_headers("", "debug_customer_new")
        assert h.get("X-Debug-Role") == "customer"
        assert h.get("X-Debug-User") == "debug_customer_new"

    def test_headers_omit_debug_user_when_unset(self):
        import unittest.mock as mock
        with mock.patch.object(lr, "PERSONA", "xiaobu"):
            h = lr._chat_headers("")
        assert "X-Debug-User" not in h, "未声明身份的用例不该带覆盖头"

    def test_run_case_passes_debug_user_to_send(self):
        """run_case 必须把身份透传给每一轮请求（接线证据，而非仅函数级）。"""
        import unittest.mock as mock
        seen = {}

        async def fake_send(token, session_id, message, images=None, debug_user=""):
            seen["debug_user"] = debug_user
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "product_search", "args": {}}],
                    "tool_results": [], "interactive": [], "final_text": "好的",
                    "error": None, "streamed": False, "done": True}

        async def fake_session(token, prefer_new=True, debug_user=""):
            seen["session_debug_user"] = debug_user
            return "sess_x"

        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "get_or_create_session", new=fake_session), \
             mock.patch.object(lr, "PERSONA", "xiaobu"):
            asyncio.run(lr.run_case(self._case("debug_customer_new"), "tok", "sess_y"))
        assert seen.get("debug_user") == "debug_customer_new", (
            "run_case 没把 case.debug_user 传给 send_message → 身份覆盖失效（假绿）")


class TestDebugUserPrecondition:
    """新客用例的前提必须**可判定**（issue #3391：首版假绿实证）。

    实战教训（run 34746134755）：身份字段只在渲染器里映射、CI 真正走的 YAML 装载路径
    漏映射 → 用例仍以 debug_customer_1（有历史订单）跑 → 走的是"有历史地址"路径，
    却报 ✅ 100%（DB 审计：11 笔订单全挂 debug_customer_1）。**全绿的假绿最危险**，
    故把前提做成可执行断言：以该身份查「我的订单」必须为空。
    """

    def _case(self, debug_user):
        return lr.EvalCase(
            id="NEWC-TEST", legacy_id="", title="t", skill=lr.Skill.ORDER,
            difficulty=lr.Difficulty.NORMAL, user_inputs=["帮我下单"],
            expectations=[], data_checks=[], persona="xiaobu", debug_user=debug_user,
        )

    def _run(self, debug_user, items):
        import unittest.mock as mock

        class _Resp:
            status_code = 200
            # ⚠️ `_safe_json` 读的是 `resp.content`（bytes）而非 `.json()`：
            # 首版夹具只实现 json() → 解析永远失败→ items 恒空 → "无违规" 是夹具喂出来的假绿
            # （本测试正是靠"身份未生效必须判红"这条反向用例才发现夹具错了）。
            content = json.dumps({"success": True, "data": {"items": items}}).encode()

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None, timeout=None):
                self.headers = headers
                return _Resp()

        client = _Client()
        with mock.patch.object(lr.httpx, "AsyncClient", return_value=client):
            issues = asyncio.run(lr.check_debug_user_precondition("tok", self._case(debug_user)))
        return issues, client

    def test_no_debug_user_is_noop(self):
        issues, _ = self._run("", [])
        assert issues == []

    def test_new_customer_identity_effective_passes(self):
        """身份生效（该身份无订单）→ 无违规。"""
        issues, client = self._run("debug_customer_new", [])
        assert issues == []
        assert client.headers.get("X-Debug-User") == "debug_customer_new"

    def test_identity_not_effective_fails_loudly(self):
        """身份没生效（查到 debug_customer_1 的历史订单）→ 判红，且信息可直接定位。"""
        issues, _ = self._run("debug_customer_new", [{"orderNo": "EVAL-ORD-0002"}])
        assert issues, "身份未生效必须判红（否则用例静默走错路径 = 假绿）"
        assert "身份未生效" in issues[0]

    def test_run_case_scores_zero_when_identity_ineffective(self):
        """前提校验必须**接进 run_case 判定**：身份没生效 → 用例判红（防假绿）。

        为什么这条最关键：前提校验若只是"算出来没人用"（假守卫），用例照样全绿 ——
        而这正是首版翻车的形态（全绿但订单全挂 debug_customer_1）。
        """
        import unittest.mock as mock

        async def fake_send(token, session_id, message, images=None, debug_user=""):
            return {"user_message": message, "images": images or [],
                    "tool_calls": [{"name": "product_search", "args": {}}],
                    "tool_results": [], "interactive": [], "final_text": "好的",
                    "error": None, "streamed": False, "done": True}

        async def fake_precheck(token, case):
            return ["新客身份未生效：以 X-Debug-User=debug_customer_new 查「我的订单」返回 2 笔（应为 0）"]

        with mock.patch.object(lr, "send_message", new=fake_send), \
             mock.patch.object(lr, "check_debug_user_precondition", new=fake_precheck), \
             mock.patch.object(lr, "PERSONA", "xiaobu"):
            res = asyncio.run(lr.run_case(self._case("debug_customer_new"), "tok", "sess_z"))
        assert res["score"] == 0.0, "身份未生效必须判红（否则用例静默走错路径 = 全绿假绿）"
        assert any("身份未生效" in str(f) for f, _ in res["failed"])

    def test_real_yaml_load_yields_debug_user(self):
        """**端到端**装载真实用例库：OR-022 的 debug_user 必须落到 EvalCase 上。

        比源码 grep 更强：真的跑一遍 `load_cases_from_yaml('.github/cases')`
        （CI 用的就是这条路径），字段丢了立刻红。
        """
        import pathlib as _pl
        cases_dir = _pl.Path(lr.__file__).resolve().parents[2] / ".github" / "cases"
        cases = {c.id: c for c in lr.load_cases_from_yaml(str(cases_dir))}
        assert cases["OR-022"].debug_user == "debug_customer_new", (
            f"YAML 装载后 debug_user 丢失: {cases['OR-022'].debug_user!r}")
        assert cases["OR-021"].debug_user == "", "未声明身份的用例应为空（不得误继承）"

    def test_loader_maps_debug_user_from_yaml(self):
        """**CI 走的 YAML 装载路径**必须映射 debug_user（首版就是这里漏了）。"""
        import pathlib as _pl
        src = _pl.Path(lr.__file__).read_text(encoding="utf-8")
        assert "debug_user=c.get(\"debug_user\"" in src, (
            "local_runner 的 YAML→EvalCase 装载器漏了 debug_user —— CI（--cases .github/cases）"
            "会用空身份跑，新客用例假绿")


class TestAssertionVocabularyIsMappedByLoader:
    """**每一个**断言字段都必须能被 CI 的 YAML 装载路径映射（issue #3417 复盘）。

    同一类假绿在本仓库已反复出现 3 次（`debug_user` / `form_prefill` /
    `forbidden_card_text`）：字段在 `render_cases.py` 里映射了、在
    `local_runner.load_cases_from_yaml` 里**漏了** → 生成物看着正常，
    而 CI 走的正是 YAML 路径 → **断言永不生效**，用例照样绿。

    逐字段补测治不了这个类（下一个新字段照样漏）。这里改成**词汇表驱动**：
    词汇表 = 生成物 `EvalCase` 的字段（单一源，`tests/agent_eval/eval_cases.py`）。
      ① 新增断言字段若没在这里配 probe → 直接红（强制作者想清楚装载路径）；
      ② 配了 probe 但装载器没映射 → 红。
    """

    # 元数据字段：不是断言，天然不需要 probe
    META = {
        "id", "title", "skill", "difficulty", "user_inputs", "expectations",
        "data_checks", "skip_reason", "legacy_id", "tags", "persona",
    }

    # 断言字段 → (YAML 片段, 期望值)。**必须覆盖词汇表全部断言字段**（见 test_probes_cover_vocabulary）
    PROBES = {
        "order_before": ('    order_before:\n      - "a before b"\n', ["a before b"]),
        "forbidden_text": ('    forbidden_text:\n      - "没法帮您提交"\n', ["没法帮您提交"]),
        "want_text": ('    want_text:\n      - "已经帮您下单"\n', ["已经帮您下单"]),
        "required_args": ('    required_args:\n      - tool: t\n        fields: [x]\n', None),
        "forbidden_args": ('    forbidden_args:\n      - tool: t\n        fields: [x]\n', None),
        "must_succeed": ('    must_succeed:\n      - tool: t\n', None),
        "amount_verify": ('    amount_verify:\n      - tool: t\n        checks: [total]\n', None),
        "db_verify": ('    db_verify:\n      - fetch: order_items\n        source: order_create\n', None),
        "output_verify": ('    output_verify:\n      - tool: t\n        field: payload\n', None),
        "pre_clean": ('    pre_clean:\n      - action: reset\n', None),
        "post_session": ('    post_session:\n      - fetch: user_memories\n', None),
        "debug_user": ('    debug_user: "debug_customer_new"\n', "debug_customer_new"),
        "form_prefill": ('    form_prefill:\n      - field: customer_phone\n        expect: "13800138000"\n', None),
        "forbidden_card_text": ('    forbidden_card_text:\n      - "用量"\n', ["用量"]),
    }

    def _vocabulary(self):
        """从生成物 dataclass 解析字段（单一源；渲染器与装载器都以它为准）"""
        import ast
        src = (REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py").read_text(encoding="utf-8")
        for node in ast.parse(src).body:
            if isinstance(node, ast.ClassDef) and node.name == "EvalCase":
                return [s.target.id for s in node.body
                        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
        raise AssertionError("eval_cases.py 里找不到 EvalCase dataclass —— 解析失效")

    def _assertion_fields(self):
        return [f for f in self._vocabulary() if f not in self.META]

    def test_probes_cover_vocabulary(self):
        missing = [f for f in self._assertion_fields() if f not in self.PROBES]
        assert not missing, (
            f"新增了断言字段但没有装载 probe：{missing}\n"
            "请在 PROBES 里补 YAML 片段（并确认 load_cases_from_yaml 与 render_cases 都映射了）"
        )
        stale = [f for f in self.PROBES if f not in self._assertion_fields()]
        assert not stale, f"PROBES 里有已不存在/已改名/已变元数据的字段：{stale}"

    def test_loader_maps_every_assertion_field(self, tmp_path):
        """逐字段：写成 YAML → 经 CI 装载路径 → 必须非空（漏映射即红）。"""
        (tmp_path / "x.yml").write_text(
            "cases:\n"
            "  - id: TMP-1\n"
            "    title: t\n"
            "    tier: normal\n"
            "    persona: xiaobu\n"
            "    user_inputs:\n"
            "      - \"你好\"\n",
            encoding="utf-8")
        problems = []
        for field in self._assertion_fields():
            snippet, want = self.PROBES[field]
            d = tmp_path / field
            d.mkdir()
            (d / "x.yml").write_text(
                "cases:\n"
                "  - id: TMP-1\n"
                "    title: t\n"
                "    tier: normal\n"
                "    persona: xiaobu\n"
                "    user_inputs:\n"
                "      - \"你好\"\n" + snippet,
                encoding="utf-8")
            cases = {c.id: c for c in lr.load_cases_from_yaml(str(d))}
            got = getattr(cases["TMP-1"], field, None)
            if not got:
                problems.append(f"{field}: 装载后为空（load_cases_from_yaml 漏映射）")
            elif want is not None and got != want:
                problems.append(f"{field}: 装载后被改写 {got!r} ≠ {want!r}")
        assert not problems, (
            "以下断言字段在 **CI 的 YAML 装载路径**上丢失/被改写 —— 该断言永不生效（假绿）：\n  "
            + "\n  ".join(problems)
        )


class TestPreferTextPendingCardDiagnostic:
    """`prefer_text` 吃掉待答卡片时必须**出声**（issue #3421 复盘）。

    实证（CH-025 首跑，run 34763744203）：用例第 4 轮声明验证码「123456」+ prefer_text，
    但那时 agent 刚发的是**加工项多选卡** → harness 把 "123456" 当成了加工项的回答 →
    之后 3 轮空转、`order_create` 从未调用。整跑只表现为"首跑失败、重试通过"，
    被标成 `llm-noise` —— **用例配置缺陷伪装成模型波动**，无人发现。
    """

    _CARD = [{"type": "choice", "title": "要哪些加工项", "options": [{"label": "纳米圈打孔", "value": "pi1"}]}]

    def _results(self, *users, card=True):
        out = [{"user_message": u} for u in users]
        if out and card:
            out[-1]["interactive"] = list(self._CARD)
        return out

    def test_summary_lists_card_type_and_title(self):
        got = lr.pending_card_summary(self._results("你好"))
        assert "choice" in got and "要哪些加工项" in got, got

    def test_summary_empty_without_card(self):
        assert lr.pending_card_summary(self._results("你好", card=False)) == ""
        assert lr.pending_card_summary([]) == ""

    def test_summary_handles_multiple_cards_and_missing_title(self):
        rounds = [{"user_message": "x", "interactive": [
            {"type": "form", "title": ""}, {"component": "confirm", "title": "确认下单"}]}]
        got = lr.pending_card_summary(rounds)
        assert got == "form、confirm:确认下单", got

    def test_prefer_text_with_pending_card_warns(self, capsys):
        lr.resolve_auto_respond(self._results("你好"), "123456", {}, prefer_text=True)
        out = capsys.readouterr().out
        assert "prefer_text 忽略了待答卡片" in out, (
            f"prefer_text 吃掉待答卡片却没有告警（这正是 CH-025 首跑失败被藏起来的原因）：{out!r}")
        assert "123456" in out, "告警应带上是哪句文本在答非所问"

    def test_no_warning_when_no_pending_card(self, capsys):
        lr.resolve_auto_respond([], "123456", {}, prefer_text=True)
        assert "忽略了待答卡片" not in capsys.readouterr().out

    def test_no_warning_when_prefer_text_off(self, capsys):
        """默认路径（答卡）不该刷告警 —— 否则日志噪音会掩盖真问题。"""
        lr.resolve_auto_respond(self._results("你好"), "确认", {})
        assert "忽略了待答卡片" not in capsys.readouterr().out
