"""
意图路由引擎 (Intent Router) 单元测试

测试覆盖：
- L1 规则匹配（关键词 + 正则）
- L2 小模型意图分类（mock）
- L3 路由决策逻辑
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.router.intent_config import IntentType, IntentResult, RouteDecision, INTENT_TOOL_MAP
from app.router.rule_matcher import RuleMatcher, KEYWORD_MAP
from app.router.intent_classifier import IntentClassifier
from app.router.intent_router import IntentRouter


# ========== RuleMatcher 测试 ==========

class TestRuleMatcher:
    """L1 规则匹配器测试"""

    @pytest.fixture
    def matcher(self):
        return RuleMatcher()

    # --- 关键词匹配 ---

    def test_keyword_match_order_query(self, matcher):
        """关键词匹配：'我要查订单' → order_query"""
        result = matcher.match("我要查订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.95
        assert result.source == "rule"
        assert any("订单" in kw for kw in result.matched_keywords)

    def test_keyword_match_logistics(self, matcher):
        """关键词匹配：物流相关"""
        result = matcher.match("我的快递到哪了")
        assert result is not None
        assert result.intent == IntentType.LOGISTICS_TRACK
        assert result.confidence == 0.95

    def test_keyword_match_pending_shipment(self, matcher):
        """关键词匹配：'待发货' → ORDER_QUERY（而非物流）"""
        result = matcher.match("我的订单待发货")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_keyword_match_product_inquiry(self, matcher):
        """关键词匹配：商品咨询"""
        result = matcher.match("这个商品多少钱")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_keyword_match_after_sales(self, matcher):
        """关键词匹配：售后"""
        result = matcher.match("我要退货")
        assert result is not None
        assert result.intent == IntentType.AFTER_SALES

    def test_keyword_match_complaint(self, matcher):
        """关键词匹配：投诉"""
        result = matcher.match("我要投诉")
        assert result is not None
        assert result.intent == IntentType.COMPLAINT

    def test_keyword_match_knowledge_faq(self, matcher):
        """关键词匹配：FAQ"""
        result = matcher.match("怎么安装窗帘")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    # --- Greeting 特殊逻辑 ---

    def test_greeting_short_message(self, matcher):
        """短消息问候语：高置信度命中"""
        result = matcher.match("你好")
        assert result is not None
        assert result.intent == IntentType.GREETING
        assert result.confidence == 1.0

    def test_greeting_long_message_ignored(self, matcher):
        """长消息中包含问候词：不作为 greeting 处理"""
        result = matcher.match("你好，我想查一下我的订单状态")
        assert result is not None
        # 应该匹配到订单相关意图而不是 greeting
        assert result.intent != IntentType.GREETING

    def test_greeting_hello_english(self, matcher):
        """英文问候"""
        result = matcher.match("hello")
        assert result is not None
        assert result.intent == IntentType.GREETING

    # --- 正则匹配 ---

    def test_regex_match_order_number(self, matcher):
        """正则匹配：包含订单号格式"""
        result = matcher.match("帮我看看 ORD1234567890 这个订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY
        assert result.source == "rule"

    def test_regex_match_long_number(self, matcher):
        """正则匹配：裸长数字不再匹配订单号（需 ORD 前缀，避免误匹配手机号）"""
        result = matcher.match("20250503123456789012")
        # 裸数字不再匹配 ORDER_QUERY，应返回 None 或匹配其他意图
        if result is not None:
            assert result.intent != IntentType.ORDER_QUERY or result.source != "rule"

    def test_regex_match_ord_prefix_required(self, matcher):
        """正则匹配：订单号必须带 ORD 前缀"""
        # ORD 前缀匹配
        result = matcher.match("ORD1234567890123")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

        # 带分隔符也匹配
        result2 = matcher.match("ORD-1234567890123")
        assert result2 is not None
        assert result2.intent == IntentType.ORDER_QUERY

        # 手机号不匹配（11位数字）
        result3 = matcher.match("13800138000")
        if result3 is not None:
            assert result3.intent != IntentType.ORDER_QUERY

    # --- 未命中 ---

    def test_no_match(self, matcher):
        """无匹配：返回 None"""
        result = matcher.match("今天天气不错")
        assert result is None

    def test_empty_message(self, matcher):
        """空消息：返回 None"""
        assert matcher.match("") is None
        assert matcher.match("   ") is None
        assert matcher.match(None) is None

    # ── P2-7: L1 关键词修复 ──

    def test_confirm_create_product_matches_product_inquiry(self, matcher):
        """'确认创建商品' 应匹配 product_inquiry（新增关键词）"""
        result = matcher.match("确认创建商品")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_confirm_create_order_matches_order_create(self, matcher):
        """'确认创建订单' 应匹配 order_create（新增关键词）"""
        result = matcher.match("确认创建订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_CREATE

    def test_create_product_matches_product_inquiry(self, matcher):
        """'创建商品' 应匹配 product_inquiry（精确短语）"""
        result = matcher.match("创建商品")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_new_product_matches_product_inquiry(self, matcher):
        """'新建商品' 应匹配 product_inquiry（精确短语）"""
        result = matcher.match("新建商品")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_standalone_create_no_longer_matches_product_inquiry(self, matcher):
        """单独的 '创建' 不再匹配 product_inquiry（已从关键词移除）"""
        result = matcher.match("创建")
        # L1 不应匹配为 product_inquiry
        if result is not None:
            assert result.intent != IntentType.PRODUCT_INQUIRY

    def test_standalone_new_no_longer_matches_product_inquiry(self, matcher):
        """单独的 '新建' 不再匹配 product_inquiry（已从关键词移除）"""
        result = matcher.match("新建")
        if result is not None:
            assert result.intent != IntentType.PRODUCT_INQUIRY

    def test_product_keyword_still_matches(self, matcher):
        """'商品' 关键词仍然匹配 product_inquiry（回归保护）"""
        result = matcher.match("商品")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_price_keyword_still_matches(self, matcher):
        """'价格' 关键词仍然匹配 product_inquiry（回归保护）"""
        result = matcher.match("这个商品多少钱")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY


# ========== IntentClassifier 测试 ==========

class TestIntentClassifier:
    """L2 小模型意图分类器测试"""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier()

    def test_parse_response_valid_json(self, classifier):
        """解析正常 JSON 响应"""
        result = classifier._parse_response('{"intent": "order_query", "confidence": 0.92}')
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.92
        assert result.source == "classifier"

    def test_parse_response_markdown_code_block(self, classifier):
        """解析 markdown 代码块包裹的 JSON"""
        result = classifier._parse_response('```json\n{"intent": "logistics_track", "confidence": 0.85}\n```')
        assert result.intent == IntentType.LOGISTICS_TRACK
        assert result.confidence == 0.85

    def test_parse_response_invalid_intent(self, classifier):
        """无效意图类型降级为 general"""
        result = classifier._parse_response('{"intent": "unknown_type", "confidence": 0.8}')
        assert result.intent == IntentType.GENERAL
        assert result.confidence == 0.5

    def test_parse_response_invalid_json(self, classifier):
        """无效 JSON 降级为 general"""
        result = classifier._parse_response("this is not json")
        assert result.intent == IntentType.GENERAL
        assert result.source == "default"

    def test_parse_response_confidence_clamped(self, classifier):
        """置信度钳位 [0, 1]"""
        result = classifier._parse_response('{"intent": "greeting", "confidence": 1.5}')
        assert result.confidence == 1.0

        result = classifier._parse_response('{"intent": "greeting", "confidence": -0.1}')
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_classify_api_failure_fallback(self, classifier):
        """API 调用失败时降级为 general"""
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("API Error"))
        classifier._llm = mock_llm
        result = await classifier.classify("测试消息")
        assert result.intent == IntentType.GENERAL
        assert result.source == "default"


# ========== IntentRouter 测试 ==========

class TestIntentRouter:
    """意图路由引擎测试"""

    @pytest.fixture
    def router(self):
        return IntentRouter()

    # --- 路由决策逻辑 ---

    def test_make_decision_greeting(self, router):
        """Greeting 高置信度 → direct_reply（回复由 direct_reply_node 从 AgentConfig 填充）"""
        intent_result = IntentResult(
            intent=IntentType.GREETING, confidence=1.0, source="rule"
        )
        decision = router._make_decision(intent_result)
        assert decision.action == "direct_reply"
        # 新架构：_make_decision 不再硬编码回复文本，返回 None
        # 由 direct_reply_node 从 AgentConfig.direct_replies 获取
        assert decision.direct_reply is None

    def test_make_decision_greeting_low_confidence(self, router):
        """Greeting 低置信度(< 0.9) → route_with_hint 而非 direct_reply"""
        intent_result = IntentResult(
            intent=IntentType.GREETING, confidence=0.7, source="classifier"
        )
        decision = router._make_decision(intent_result)
        assert decision.action == "route_with_hint"

    def test_make_decision_high_confidence_route_with_hint(self, router):
        """高置信度(>=0.7) → route_with_hint"""
        intent_result = IntentResult(
            intent=IntentType.ORDER_QUERY, confidence=0.95, source="rule"
        )
        decision = router._make_decision(intent_result)
        assert decision.action == "route_with_hint"
        assert decision.tool_hint is not None
        assert "order_query" in decision.tool_hint

    def test_make_decision_low_confidence_full_agent(self, router):
        """低置信度(<0.7) → full_agent"""
        intent_result = IntentResult(
            intent=IntentType.GENERAL, confidence=0.5, source="classifier"
        )
        decision = router._make_decision(intent_result)
        assert decision.action == "full_agent"

    def test_make_decision_complaint_with_hint(self, router):
        """投诉意图高置信度 → route_with_hint + human_handoff"""
        intent_result = IntentResult(
            intent=IntentType.COMPLAINT, confidence=0.9, source="rule"
        )
        decision = router._make_decision(intent_result)
        assert decision.action == "route_with_hint"
        assert "human_handoff" in decision.tool_hint

    # --- 端到端路由 ---

    @pytest.mark.asyncio
    async def test_route_rule_match_takes_priority(self, router):
        """规则匹配优先于分类器"""
        decision = await router.route("我要查订单")
        assert decision.intent_result.source == "rule"
        assert decision.intent_result.intent == IntentType.ORDER_QUERY

    @pytest.mark.asyncio
    async def test_route_greeting_direct_reply(self, router):
        """问候语 → direct_reply action（回复文本由 direct_reply_node 填充）"""
        decision = await router.route("你好")
        assert decision.action == "direct_reply"
        # 新架构：回复文本在 direct_reply_node 中从 AgentConfig 获取
        assert decision.direct_reply is None

    @pytest.mark.asyncio
    async def test_route_falls_to_classifier(self, router):
        """规则未命中时走分类器"""
        with patch.object(
            router.intent_classifier, "classify",
            new_callable=AsyncMock,
            return_value=IntentResult(
                intent=IntentType.PRODUCT_INQUIRY,
                confidence=0.85,
                source="classifier",
            ),
        ):
            decision = await router.route("最近有什么新款窗帘推荐")
            assert decision.intent_result.source == "classifier"
            assert decision.intent_result.intent == IntentType.PRODUCT_INQUIRY


# ========== IntentConfig 数据结构测试 ==========

class TestIntentConfig:
    """意图配置测试"""

    def test_intent_type_values(self):
        """所有意图类型存在"""
        assert len(IntentType) == 29  # 含 order_create

    def test_intent_tool_map_coverage(self):
        """所有意图类型都有 tool 映射"""
        for intent in IntentType:
            assert intent in INTENT_TOOL_MAP

    def test_after_sales_maps_to_after_sales_manage(self):
        """售后意图映射到 after_sales_manage（而非 order_manage）"""
        tools = INTENT_TOOL_MAP[IntentType.AFTER_SALES]
        assert "after_sales_manage" in tools
        assert "order_query" in tools
        assert "order_manage" not in tools

    def test_order_query_excludes_order_manage(self):
        """订单查询意图不再包含 order_manage"""
        tools = INTENT_TOOL_MAP[IntentType.ORDER_QUERY]
        assert "order_query" in tools
        assert "order_manage" not in tools

    def test_intent_result_defaults(self):
        """IntentResult 默认值"""
        result = IntentResult(intent=IntentType.GENERAL, confidence=0.5, source="default")
        assert result.matched_keywords == []

    def test_route_decision_defaults(self):
        """RouteDecision 默认值"""
        intent_result = IntentResult(intent=IntentType.GENERAL, confidence=0.5, source="default")
        decision = RouteDecision(intent_result=intent_result, action="full_agent")
        assert decision.direct_reply is None
        assert decision.tool_hint is None
