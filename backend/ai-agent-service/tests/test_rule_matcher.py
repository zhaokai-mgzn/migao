# case_ids: MC-010, MC-011, AS-003, AS-004, AS-005, HR-002, DA-004
"""规则匹配器单元测试（app/router/rule_matcher.py）

覆盖：_extract_text / RuleMatcher.match 关键词优先级 / 正则规则 / 未命中。
"""
from app.router.rule_matcher import RuleMatcher, _extract_text
from app.router.intent_config import IntentType


class TestExtractText:
    def test_none_returns_empty(self):
        assert _extract_text(None) == ""

    def test_str_returns_same(self):
        assert _extract_text("查订单") == "查订单"

    def test_list_joins_text_blocks(self):
        content = [
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            {"type": "text", "text": "查订单"},
        ]
        assert _extract_text(content) == "你好 查订单"

    def test_other_type_stringified(self):
        assert _extract_text(42) == "42"


class TestMatch:
    def _match(self, message):
        return RuleMatcher().match(message)

    def test_empty_text_returns_none(self):
        assert self._match("") is None

    def test_none_returns_none(self):
        assert self._match(None) is None

    def test_whitespace_returns_none(self):
        assert self._match("   ") is None

    def test_capabilities_priority(self):
        result = self._match("你能做什么")
        assert result.intent == IntentType.CAPABILITIES
        assert result.confidence == 1.0
        assert result.source == "rule"

    def test_farewell_priority(self):
        result = self._match("再见")
        assert result.intent == IntentType.FAREWELL
        assert result.confidence == 1.0

    def test_order_statistics_priority_over_statistics(self):
        # "订单统计" 同时含"订单"和"统计"，必须优先 order_query 而非 statistics
        result = self._match("订单统计")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.95
        assert result.matched_keywords == ["订单统计"]

    def test_regular_keyword_confidence(self):
        result = self._match("我要投诉")
        assert result.intent == IntentType.COMPLAINT
        assert result.confidence == 0.95
        assert result.source == "rule"
        assert result.matched_keywords == ["投诉"]

    def test_greeting_short_high_confidence(self):
        result = self._match("你好")
        assert result.intent == IntentType.GREETING
        assert result.confidence == 1.0

    def test_long_greeting_skipped(self):
        # 长消息含问候词，不识别为 greeting（无其他关键词 → None）
        assert self._match("你好呀，今天天气不错，很高兴见到你") is None

    def test_regex_order_number(self):
        result = self._match("ORD1234567890123")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.9
        assert result.matched_keywords[0].startswith("regex:")

    # ── 人事域路由（HR-002：创建员工/添加员工必须路由到 staff，不得被商品正则劫持）──
    def test_create_employee_account_routes_to_staff(self):
        result = self._match("创建一个员工账号，姓名张三，手机号13800000000")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    def test_add_employee_routes_to_staff(self):
        result = self._match("添加员工 李四 运营人员")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    def test_new_employee_routes_to_staff(self):
        result = self._match("新建一个员工账号")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    # ── 会话管理触发（看看当前有哪些会话 → session_manage）──
    def test_session_listing_routes_to_session_manage(self):
        result = self._match("看看当前有哪些会话")
        assert result.intent == IntentType.SESSION_MANAGE

    def test_customer_service_sessions_routes_to_session_manage(self):
        result = self._match("看看当前有哪些活跃的客服会话")
        assert result.intent == IntentType.SESSION_MANAGE

    def test_regex_product_creation(self):
        result = self._match("新建一个窗帘")
        assert result.intent == IntentType.PRODUCT_INQUIRY
        assert result.confidence == 0.9
        assert result.matched_keywords[0].startswith("regex:")

    def test_create_order_not_product_inquiry(self):
        # "创建订单" 含"订单"，不应被商品创建正则抢占
        result = self._match("创建订单")
        assert result.intent == IntentType.ORDER_CREATE

    def test_no_match_returns_none(self):
        assert self._match("随便说点什么") is None

    def test_ambiguous_order_and_aftersales_returns_none(self):
        # 跨域消息：订单实体 + 售后动作 → 多意图冲突，L1 不硬猜，交给 L2 带上下文分类
        # （修复生产回归：售后工单创建被"订单"关键词抢占路由）
        assert self._match("给订单20260826708690102创建退款售后工单") is None

    def test_ambiguous_product_and_aftersales_returns_none(self):
        # 售后补信息消息含"商品"实体 + "退款"动作 → 同样不硬猜
        assert self._match("客户手机号13800138000，要退款，商品有瑕疵") is None

    def test_ambiguous_order_entity_and_return_action_returns_none(self):
        # 指代上下文："这个订单…退货…建售后工单"
        assert self._match("这个订单的客户要退货，帮他建个售后工单") is None

    def test_single_aftersales_keyword_still_matches(self):
        # 纯售后意图（单意图）仍走 L1 快速通道
        result = self._match("看看售后工单")
        assert result is not None
        assert result.intent == IntentType.AFTER_SALES

    def test_single_order_keyword_still_matches(self):
        result = self._match("查一下订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_single_intent_multi_keywords_same_intent_still_matches(self):
        # 同意图多关键词（订单 + 待发货）不算冲突
        result = self._match("查一下待发货订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_mixed_regex_and_keyword_prefers_keyword_intent(self):
        # regex 命中不计长度：ORD 单号 + "退款" → 售后意图胜出（售后 skill 持有 order_query）
        result = self._match("ORD1234567890123 要退款")
        assert result is not None
        assert result.intent == IntentType.AFTER_SALES
