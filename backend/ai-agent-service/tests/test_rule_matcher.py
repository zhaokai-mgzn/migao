# case_ids: MC-010, MC-011, AS-003, AS-004, AS-005, HR-002, DA-004, PR-013, DA-003, PP-002
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

    def test_recent_orders_matches_dashboard(self):
        # DA-003 回归："最近5条订单"是看板语义（dashboard_stats recent_orders），
        # 此前「订单」关键词把它抢到 order_query，agent 用 order_query(list) 而非
        # dashboard_stats(recent_orders)——工具说明明确「最近X条订单优先用本工具」。
        result = self._match("最近5条订单")
        assert result is not None
        assert result.intent == IntentType.DASHBOARD

    def test_recent_orders_with_digits_matches_dashboard(self):
        result = self._match("最近3笔订单")
        assert result is not None
        assert result.intent == IntentType.DASHBOARD

    def test_recent_orders_no_digits_stays_order_query(self):
        # OR-001 回归（#3142 修正）："查看最近的订单"（无数字量词）是查订单列表，
        # 不是看板 recent_orders——#3124 的「最近+订单→DASHBOARD」规则过宽把它误路由，
        # smoke 档 OR-001 回归（7/8，唯一失败）。收紧：仅「最近+数字量词+订单」走看板。
        result = self._match("查看最近的订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_notification_mark_read_matches_notification(self):
        # ST-005 回归：KEYWORD_MAP 缺 NOTIFICATION 关键词，「把新订单通知标为已读」被
        # 「订单」抢到 ORDER_QUERY → agent 按 order 工具集误宣「无法改通知状态」（能力误宣）。
        result = self._match("把新订单通知标为已读")
        assert result is not None
        assert result.intent == IntentType.NOTIFICATION

    def test_notification_query_matches_notification(self):
        result = self._match("有没有未读通知")
        assert result is not None
        assert result.intent == IntentType.NOTIFICATION

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

    def test_quote_keyword_routes_to_quote(self):
        # 算料/报价关键词 → quote 意图
        result = self._match("帮我算一下窗帘要用多少布")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    def test_quote_dimension_regex_routes_to_quote(self):
        # 尺寸数字 + 褶皱 → quote 意图（正则规则）
        result = self._match("3米窗 2倍褶皱 多少钱")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    def test_quote_punch_hole_keyword(self):
        # 打孔帘关键词 → quote 意图
        result = self._match("打孔帘 2.7米高 报价")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    # ── 售后政策类知识咨询（issue #3064 验收 P1-2：双端「退换货政策」未走知识卡片）──
    def test_return_policy_inquiry_routes_to_knowledge_faq(self):
        # 验收实测失败场景：小布/米宝问退换货政策 → 规则判 after_sales → 未调 knowledge_search
        result = self._match("你们退换货政策是怎样的？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_store_return_policy_inquiry_routes_to_knowledge_faq(self):
        result = self._match("我们店的退换货政策是什么")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_aftersales_policy_inquiry_routes_to_knowledge_faq(self):
        result = self._match("售后政策是什么？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_warranty_inquiry_routes_to_knowledge_faq(self):
        result = self._match("窗帘质保多久？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_aftersales_operation_still_routes_to_after_sales(self):
        # 操作类不回归：无政策咨询词 → 仍售后工单
        for msg in ["我要退货", "帮我退款", "看看售后工单", "申请换货"]:
            result = self._match(msg)
            assert result is not None, f"{msg} 应命中"
            assert result.intent == IntentType.AFTER_SALES, f"{msg} 应判售后操作而非知识咨询"
