# case_ids: MC-010, MC-011
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
        result = self._match("你好呀，今天天气不错，很高兴见到你")
        assert result is None

    def test_regex_order_number(self):
        result = self._match("ORD1234567890123")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.9
        assert result.matched_keywords[0].startswith("regex:")

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
