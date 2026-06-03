"""
多模态消息内容处理测试

复现 Bug：用户发送带图片的消息时，HumanMessage.content 为 list（多模态格式），
但 rule_matcher / intent_classifier / graph nodes 等模块假设 content 为 str，
导致 AttributeError: 'list' object has no attribute 'strip'

测试覆盖：
- RuleMatcher.match() 接收 list content 不崩溃
- IntentClassifier.classify() 接收 list message 不崩溃
- intent_router_node 处理多模态 HumanMessage 正确提取文本
- cache_check_node / cache_store_node / suggestions_node 处理 list content 不崩溃
- _extract_text_from_content() helper 函数正确性
"""

import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.router.rule_matcher import RuleMatcher
from app.router.intent_config import IntentType


# ========== 多模态内容格式 ==========

def _make_multimodal_content(text: str, image_urls: list[str] | None = None):
    """构造标准的多模态 HumanMessage content（与 chat.py 中构造逻辑一致）"""
    content = [{"type": "text", "text": text}]
    for url in (image_urls or ["https://oss.example.com/test.jpg"]):
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def _make_state(**overrides):
    """构建测试用 AgentState 字典"""
    state = {
        "messages": [HumanMessage(content="测试消息")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_001",
        "role": "customer",
        "agent_type": "mibao",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


# ========== _extract_text_from_content helper 测试 ==========

class TestExtractTextFromContent:
    """测试从多模态 content 中提取文本的 helper 函数"""

    def test_extract_from_string(self):
        """str content 直接返回"""
        from app.graph.nodes import _extract_text_from_content
        assert _extract_text_from_content("hello world") == "hello world"

    def test_extract_from_multimodal_list(self):
        """list content 提取 text 类型部分"""
        from app.graph.nodes import _extract_text_from_content
        content = _make_multimodal_content("这张图片是什么")
        assert _extract_text_from_content(content) == "这张图片是什么"

    def test_extract_from_multimodal_with_multiple_texts(self):
        """多个 text 部分拼接"""
        from app.graph.nodes import _extract_text_from_content
        content = [
            {"type": "text", "text": "第一段"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            {"type": "text", "text": "第二段"},
        ]
        assert _extract_text_from_content(content) == "第一段 第二段"

    def test_extract_from_empty_list(self):
        """空 list 返回空字符串"""
        from app.graph.nodes import _extract_text_from_content
        assert _extract_text_from_content([]) == ""

    def test_extract_from_none(self):
        """None 返回空字符串"""
        from app.graph.nodes import _extract_text_from_content
        assert _extract_text_from_content(None) == ""

    def test_extract_from_list_with_only_images(self):
        """只有图片没有文本时返回空字符串"""
        from app.graph.nodes import _extract_text_from_content
        content = [{"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}}]
        assert _extract_text_from_content(content) == ""


# ========== RuleMatcher 多模态输入测试 ==========

class TestRuleMatcherMultimodal:
    """RuleMatcher 接收多模态 list content 时不应崩溃"""

    @pytest.fixture
    def matcher(self):
        return RuleMatcher()

    def test_match_with_list_content_does_not_crash(self, matcher):
        """list content 不崩溃（复现 AttributeError）"""
        content = _make_multimodal_content("查订单")
        # 修复前会抛 AttributeError: 'list' object has no attribute 'strip'
        result = matcher.match(content)
        # 应该能正常匹配到 order_query
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_match_with_list_content_no_keywords(self, matcher):
        """list content 无关键词匹配时返回 None"""
        content = _make_multimodal_content("随便说点什么")
        result = matcher.match(content)
        assert result is None

    def test_match_with_empty_list(self, matcher):
        """空 list 返回 None"""
        result = matcher.match([])
        assert result is None

    def test_match_with_list_greeting(self, matcher):
        """list content 中的问候语也能正确匹配"""
        content = _make_multimodal_content("你好")
        result = matcher.match(content)
        assert result is not None
        assert result.intent == IntentType.GREETING


# ========== IntentClassifier 多模态输入测试 ==========

class TestIntentClassifierMultimodal:
    """IntentClassifier 接收 list message 时不应崩溃"""

    @pytest.mark.asyncio
    async def test_classify_with_list_message_does_not_crash(self):
        """list message 传给 classify 不崩溃"""
        from app.router.intent_classifier import IntentClassifier
        classifier = IntentClassifier()

        # Mock LLM 返回正常结果
        mock_response = MagicMock()
        mock_response.content = '{"intent": "product_inquiry", "confidence": 0.85}'
        mock_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        classifier._llm = mock_llm

        content = _make_multimodal_content("这个布料多少钱")
        result = await classifier.classify(content)
        assert result is not None
        # 不应该崩溃，应返回有效结果

    @pytest.mark.asyncio
    async def test_classify_with_list_message_and_history(self):
        """list message + chat_history 不崩溃"""
        from app.router.intent_classifier import IntentClassifier
        classifier = IntentClassifier()

        mock_response = MagicMock()
        mock_response.content = '{"intent": "general", "confidence": 0.6}'
        mock_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        classifier._llm = mock_llm

        content = _make_multimodal_content("帮我看看这个")
        history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好"}]
        result = await classifier.classify(content, chat_history=history)
        assert result is not None


# ========== Graph Nodes 多模态输入测试 ==========

import app.cache.semantic_cache  # noqa - trigger module load
_sc_module = sys.modules['app.cache.semantic_cache']


class TestNodesMultimodal:
    """Graph 节点处理多模态 content 时不应崩溃"""

    @patch("app.router.intent_router.IntentRouter")
    async def test_intent_router_node_with_multimodal(self, MockRouter):
        """intent_router_node 处理多模态消息不崩溃"""
        from app.graph.nodes import intent_router_node

        mock_router = MagicMock()
        mock_decision = MagicMock()
        mock_decision.intent_result.intent.value = "product_inquiry"
        mock_decision.intent_result.confidence = 0.9
        mock_decision.intent_result.source = "classifier"
        mock_decision.action = "full_agent"
        mock_decision.direct_reply = None
        mock_decision.tool_hint = None
        mock_router.route = AsyncMock(return_value=mock_decision)
        MockRouter.return_value = mock_router

        content = _make_multimodal_content("这是什么布料")
        state = _make_state(
            messages=[HumanMessage(content=content)],
        )
        result = await intent_router_node(state)

        # 验证传给 router.route 的 user_message 是 str 而不是 list
        call_args = mock_router.route.call_args
        user_message_arg = call_args[0][0]  # 第一个位置参数
        assert isinstance(user_message_arg, str), \
            f"Expected str, got {type(user_message_arg)}: {user_message_arg}"
        assert user_message_arg == "这是什么布料"

    @patch("app.router.intent_router.IntentRouter")
    async def test_intent_router_node_multimodal_chat_history(self, MockRouter):
        """intent_router_node 处理多模态历史消息不崩溃"""
        from app.graph.nodes import intent_router_node

        mock_router = MagicMock()
        mock_decision = MagicMock()
        mock_decision.intent_result.intent.value = "general"
        mock_decision.intent_result.confidence = 0.7
        mock_decision.intent_result.source = "classifier"
        mock_decision.action = "full_agent"
        mock_decision.direct_reply = None
        mock_decision.tool_hint = None
        mock_router.route = AsyncMock(return_value=mock_decision)
        MockRouter.return_value = mock_router

        # 历史消息中也有多模态内容
        history_content = _make_multimodal_content("看看这个图片")
        state = _make_state(
            messages=[
                HumanMessage(content=history_content),
                AIMessage(content="这是一张窗帘图片"),
                HumanMessage(content=_make_multimodal_content("多少钱")),
            ],
        )
        result = await intent_router_node(state)

        # chat_history 中的 content 也应该是 str
        call_args = mock_router.route.call_args
        chat_history_arg = call_args[0][1]  # 第二个位置参数
        for entry in chat_history_arg:
            assert isinstance(entry["content"], str), \
                f"Chat history content should be str, got {type(entry['content'])}"

    async def test_cache_check_node_with_multimodal(self):
        """cache_check_node 处理多模态消息不崩溃"""
        from app.graph.nodes import cache_check_node

        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value=None)
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True

        content = _make_multimodal_content("查一下这个")
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state(messages=[HumanMessage(content=content)])
            result = await cache_check_node(state)

        # 传给 semantic_cache.lookup 的 query 应该是 str
        if mock_cache.lookup.called:
            call_kwargs = mock_cache.lookup.call_args[1]
            assert isinstance(call_kwargs["query"], str), \
                f"Expected str query, got {type(call_kwargs['query'])}"

    async def test_cache_store_node_with_multimodal(self):
        """cache_store_node 处理多模态消息不崩溃"""
        from app.graph.nodes import cache_store_node

        mock_cache = AsyncMock()
        mock_cache.store = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True

        content = _make_multimodal_content("看看这个")
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state(
                messages=[HumanMessage(content=content)],
                final_answer="这是一个窗帘",
                intent_result={"intent": "product_inquiry"},
            )
            result = await cache_store_node(state)

        assert result == {}
        if mock_cache.store.called:
            call_kwargs = mock_cache.store.call_args[1]
            assert isinstance(call_kwargs["query"], str), \
                f"Expected str query, got {type(call_kwargs['query'])}"

    @patch("app.suggestions.follow_up.FollowUpSuggestionGenerator")
    async def test_suggestions_node_with_multimodal(self, MockGenerator):
        """suggestions_node 处理多模态消息不崩溃"""
        from app.graph.nodes import suggestions_node

        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(return_value=["查看更多", "了解价格"])
        MockGenerator.return_value = mock_gen

        content = _make_multimodal_content("这个多少钱")
        state = _make_state(
            messages=[HumanMessage(content=content)],
            final_answer="这是窗帘",
            intent_result={"intent": "product_inquiry"},
        )
        result = await suggestions_node(state)

        # 传给 generator.generate 的 query 应该是 str
        call_kwargs = mock_gen.generate.call_args[1]
        assert isinstance(call_kwargs["query"], str), \
            f"Expected str query, got {type(call_kwargs['query'])}"
        assert result["suggestions"] == ["查看更多", "了解价格"]
