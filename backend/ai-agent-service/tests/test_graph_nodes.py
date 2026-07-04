"""
LangGraph 辅助节点函数测试

测试覆盖：
- cache_check_node: 缓存命中/未命中
- intent_router_node: 各意图类型路由
- direct_reply_node: 直接回复
- cache_store_node: 缓存写入
- suggestions_node: 建议生成（含超时降级）
- check_cache_hit 条件函数
- route_by_intent 条件函数
"""

import asyncio
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.nodes import (
    cache_check_node,
    intent_router_node,
    direct_reply_node,
    cache_store_node,
    suggestions_node,
    check_cache_hit,
    route_by_intent,
    _infer_stage,
)

import app.cache.semantic_cache  # noqa - trigger module load
_sc_module = sys.modules['app.cache.semantic_cache']


# ========== 辅助 fixtures ==========

def _make_state(**overrides):
    """构建测试用 AgentState 字典"""
    state = {
        "messages": [HumanMessage(content="测试消息")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_001",
        "role": "customer",
        "user_name": "",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "recent_entities": [],
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


# ========== cache_check_node 测试 ==========

class TestCacheCheckNode:
    """语义缓存检查节点测试"""

    @patch("app.config.settings")
    async def test_cache_disabled(self, mock_settings):
        """缓存功能关闭时返回 None"""
        mock_settings.SEMANTIC_CACHE_ENABLED = False
        state = _make_state()
        result = await cache_check_node(state)
        assert result["cached_answer"] is None

    async def test_cache_miss(self):
        """缓存未命中"""
        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value=None)
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state()
            result = await cache_check_node(state)
        assert result["cached_answer"] is None

    async def test_cache_hit(self):
        """缓存命中"""
        mock_result = MagicMock()
        mock_result.answer = "缓存回答"
        mock_result.confidence = 0.95
        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value=mock_result)
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state()
            result = await cache_check_node(state)
        assert result["cached_answer"] == "缓存回答"
        assert result["final_answer"] == "缓存回答"
        assert result["skill_used"] == "cache"

    async def test_cache_no_user_message(self):
        """没有用户消息时返回 None"""
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings):
            state = _make_state(messages=[AIMessage(content="AI消息")])
            result = await cache_check_node(state)
        assert result["cached_answer"] is None

    async def test_cache_exception_returns_none(self):
        """缓存查询异常时降级返回 None"""
        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(side_effect=Exception("Redis error"))
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state()
            result = await cache_check_node(state)
        assert result["cached_answer"] is None


# ========== intent_router_node 测试 ==========

class TestIntentRouterNode:
    """意图路由节点测试"""

    @patch("app.router.intent_router.IntentRouter")
    async def test_route_order_query(self, MockRouter):
        """路由到订单查询"""
        mock_router = MagicMock()
        mock_decision = MagicMock()
        mock_decision.intent_result.intent.value = "order_query"
        mock_decision.intent_result.confidence = 0.95
        mock_decision.intent_result.source = "rule"
        mock_decision.action = "full_agent"
        mock_decision.direct_reply = None
        mock_decision.tool_hint = "order_query"
        mock_router.route = AsyncMock(return_value=mock_decision)
        MockRouter.return_value = mock_router

        state = _make_state(messages=[HumanMessage(content="查询我的订单")])
        result = await intent_router_node(state)

        assert result["intent_result"]["intent"] == "order_query"
        assert result["intent_result"]["confidence"] == 0.95
        assert result["route_decision"]["action"] == "full_agent"

    @patch("app.router.intent_router.IntentRouter")
    async def test_route_greeting(self, MockRouter):
        """路由到直接回复（greeting）"""
        mock_router = MagicMock()
        mock_decision = MagicMock()
        mock_decision.intent_result.intent.value = "greeting"
        mock_decision.intent_result.confidence = 0.99
        mock_decision.intent_result.source = "rule"
        mock_decision.action = "direct_reply"
        mock_decision.direct_reply = "您好！"
        mock_decision.tool_hint = None
        mock_router.route = AsyncMock(return_value=mock_decision)
        MockRouter.return_value = mock_router

        state = _make_state(messages=[HumanMessage(content="你好")])
        result = await intent_router_node(state)

        assert result["intent_result"]["intent"] == "greeting"
        assert result["route_decision"]["action"] == "direct_reply"
        assert result["route_decision"]["direct_reply"] == "您好！"


# ========== direct_reply_node 测试 ==========

class TestDirectReplyNode:
    """直接回复节点测试"""

    async def test_direct_reply_with_content(self):
        """有 direct_reply 内容时使用该内容"""
        state = _make_state(
            route_decision={"direct_reply": "欢迎光临！", "action": "direct_reply"}
        )
        result = await direct_reply_node(state)
        assert result["final_answer"] == "欢迎光临！"
        assert result["skill_used"] == "direct_reply"
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "欢迎光临！"

    async def test_direct_reply_fallback(self):
        """无 direct_reply 时使用 AgentConfig 或默认回复"""
        state = _make_state(route_decision={})
        result = await direct_reply_node(state)
        # 兜底应返回非空回复文本
        assert result["final_answer"]
        assert len(result["final_answer"]) > 0
        assert result["skill_used"] == "direct_reply"

    async def test_direct_reply_no_route_decision(self):
        """route_decision 为 None 时使用默认回复"""
        state = _make_state(route_decision=None)
        result = await direct_reply_node(state)
        assert result["final_answer"] is not None
        assert result["skill_used"] == "direct_reply"


# ========== cache_store_node 测试 ==========

class TestCacheStoreNode:
    """缓存写入节点测试"""

    @patch("app.config.settings")
    async def test_cache_store_disabled(self, mock_settings):
        """缓存关闭时不写入"""
        mock_settings.SEMANTIC_CACHE_ENABLED = False
        state = _make_state(final_answer="回答")
        result = await cache_store_node(state)
        assert result == {}

    async def test_cache_store_success(self):
        """缓存写入成功"""
        mock_cache = AsyncMock()
        mock_cache.store = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state(
                final_answer="这是回答",
                intent_result={"intent": "order_query"},
            )
            result = await cache_store_node(state)
        assert result == {}
        mock_cache.store.assert_called_once()

    async def test_cache_store_no_answer(self):
        """无回答时不写入"""
        mock_cache = AsyncMock()
        mock_cache.store = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state(final_answer="")
            result = await cache_store_node(state)
        assert result == {}
        mock_cache.store.assert_not_called()

    async def test_cache_store_exception(self):
        """缓存写入异常时不影响流程"""
        mock_cache = AsyncMock()
        mock_cache.store = AsyncMock(side_effect=Exception("Redis error"))
        mock_settings = MagicMock()
        mock_settings.SEMANTIC_CACHE_ENABLED = True
        with patch("app.config.settings", mock_settings), \
             patch.object(_sc_module, "semantic_cache", mock_cache):
            state = _make_state(final_answer="回答")
            result = await cache_store_node(state)
        assert result == {}


# ========== suggestions_node 测试 ==========

class TestSuggestionsNode:
    """建议生成节点测试"""

    @patch("app.suggestions.follow_up.FollowUpSuggestionGenerator")
    async def test_suggestions_generated(self, MockGenerator):
        """正常生成建议"""
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(return_value=["建议1", "建议2"])
        MockGenerator.return_value = mock_gen

        state = _make_state(
            final_answer="回答",
            intent_result={"intent": "order_query"},
        )
        result = await suggestions_node(state)
        assert result["suggestions"] == ["建议1", "建议2"]

    async def test_suggestions_timeout(self):
        """超时时返回空列表"""
        mock_gen = MagicMock()

        async def slow_generate(**kwargs):
            await asyncio.sleep(5)
            return ["建议"]

        mock_gen.generate = slow_generate

        with patch("app.suggestions.follow_up.FollowUpSuggestionGenerator", return_value=mock_gen), \
             patch("app.graph.nodes.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            state = _make_state(final_answer="回答", intent_result={"intent": "general"})
            result = await suggestions_node(state)
        assert result["suggestions"] == []

    async def test_suggestions_exception(self):
        """异常时返回空列表"""
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.suggestions.follow_up.FollowUpSuggestionGenerator", return_value=mock_gen):
            state = _make_state(final_answer="回答", intent_result={"intent": "general"})
            result = await suggestions_node(state)
        assert result["suggestions"] == []

    # ── #947: 用户画像 + 实体传递给 FollowUpGenerator ──

    @patch("app.suggestions.follow_up.FollowUpSuggestionGenerator")
    async def test_suggestions_passes_user_profile(self, MockGenerator):
        """#947: suggestions_node 传递 user_role, user_name, entities 给 generator"""
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(return_value=["建议1", "建议2"])
        MockGenerator.return_value = mock_gen

        state = _make_state(
            final_answer="这是订单 ORD001 的详情，请查收。",
            intent_result={"intent": "order_query"},
            role="admin",
            user_name="张三",
            recent_entities=[
                {"type": "order_nos", "value": "ORD001", "label": "ORD001"},
            ],
        )
        result = await suggestions_node(state)
        assert result["suggestions"] == ["建议1", "建议2"]

        # 验证 generate() 被调用且传入了用户画像参数
        call_kwargs = mock_gen.generate.call_args.kwargs
        assert call_kwargs["user_role"] == "admin"
        assert call_kwargs["user_name"] == "张三"
        assert call_kwargs["entities"] is not None
        assert len(call_kwargs["entities"]) == 1
        assert call_kwargs["entities"][0]["value"] == "ORD001"

    @patch("app.suggestions.follow_up.FollowUpSuggestionGenerator")
    async def test_suggestions_entities_fallback_from_dict(self, MockGenerator):
        """#947: recent_entities 为空时 fallback 到 entities dict 展开"""
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(return_value=["建议"])
        MockGenerator.return_value = mock_gen

        state = _make_state(
            final_answer="订单查询结果",
            intent_result={"intent": "order_query"},
            recent_entities=[],  # 空
            entities={"order_nos": ["ORD001", "ORD002"], "customer_names": ["张三"]},
        )
        result = await suggestions_node(state)
        assert result["suggestions"] == ["建议"]

        # 验证 entities 被展开为列表格式
        call_kwargs = mock_gen.generate.call_args.kwargs
        assert call_kwargs["entities"] is not None
        entity_values = [e["value"] for e in call_kwargs["entities"]]
        assert "ORD001" in entity_values
        assert "ORD002" in entity_values
        assert "张三" in entity_values

    @patch("app.suggestions.follow_up.FollowUpSuggestionGenerator")
    async def test_suggestions_entities_none_when_no_data(self, MockGenerator):
        """#947: 无实体时 entities 传 None"""
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(return_value=["建议"])
        MockGenerator.return_value = mock_gen

        state = _make_state(
            final_answer="好的",
            intent_result={"intent": "general"},
            recent_entities=[],
            entities={},
        )
        result = await suggestions_node(state)
        assert result["suggestions"] == ["建议"]

        call_kwargs = mock_gen.generate.call_args.kwargs
        assert call_kwargs["entities"] is None


# ========== _infer_stage 测试 ==========

class TestInferStage:
    """#947: _infer_stage 对话阶段推断 — 验证 action 从 route_decision 读取"""

    def test_pending_interact_skill_confirming(self):
        """有 pending_interact_skill 时返回 confirming"""
        state = _make_state(pending_interact_skill="order")
        assert _infer_stage(state) == "confirming"

    def test_direct_reply_greeting_initial(self):
        """action=direct_reply + greeting → initial"""
        state = _make_state(
            route_decision={"action": "direct_reply"},
        )
        assert _infer_stage(state, "greeting") == "initial"

    def test_direct_reply_farewell_completed(self):
        """action=direct_reply + farewell → completed"""
        state = _make_state(
            route_decision={"action": "direct_reply"},
        )
        assert _infer_stage(state, "farewell") == "completed"

    def test_direct_reply_other_initial(self):
        """action=direct_reply + 其他意图 → initial"""
        state = _make_state(
            route_decision={"action": "direct_reply"},
        )
        assert _infer_stage(state, "capabilities") == "initial"

    def test_final_answer_long_querying(self):
        """final_answer > 30 字符 → querying"""
        state = _make_state(
            final_answer="这是关于订单 ORD001 的详细查询结果，包含物流信息和商品详情。" * 2,
        )
        assert _infer_stage(state, "order_query") == "querying"

    def test_final_answer_short_defaults_to_stage(self):
        """final_answer ≤ 30 字符 → 返回 state.stage 或 initial"""
        state = _make_state(
            final_answer="好的",
            stage="querying",
        )
        assert _infer_stage(state, "general") == "querying"

    def test_default_to_initial_when_no_stage(self):
        """无特殊条件 → 回退到 initial"""
        state = _make_state()
        assert _infer_stage(state) == "initial"

    # ── Bug 修复验证：action 必须从 route_decision 读取 ──

    def test_action_from_route_decision_not_intent_result(self):
        """#947 Bug 修复: _infer_stage 从 route_decision 读 action，而非 intent_result"""
        # 模拟旧 bug: intent_result 里有 action=direct_reply，
        # 但 route_decision 里没有（或 action 是 full_agent）
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"action": "direct_reply", "intent": "order_query"},
            final_answer=""  # 无长回复
        )
        # 修复后：读 route_decision.action = "full_agent"，不应返回 initial
        # 旧代码会误读 intent_result.action = "direct_reply" 返回 "initial"
        result = _infer_stage(state, "order_query")
        assert result != "initial", (
            f"BUG 复现: _infer_stage 错误地从 intent_result 读取 action，"
            f"返回了 {result}。应返回 {state.get('stage', 'initial')}"
        )

    def test_no_route_decision_defaults(self):
        """route_decision 为 None 时不崩溃"""
        state = _make_state(route_decision=None)
        result = _infer_stage(state, "general")
        assert result in ("initial", "querying", "confirming", "processing", "completed")


# ========== check_cache_hit 条件函数测试 ==========

class TestCheckCacheHit:
    """缓存命中条件路由测试"""

    def test_hit(self):
        """有 cached_answer 时返回 hit"""
        state = _make_state(cached_answer="缓存回答")
        assert check_cache_hit(state) == "hit"

    def test_miss_none(self):
        """cached_answer 为 None 时返回 miss"""
        state = _make_state(cached_answer=None)
        assert check_cache_hit(state) == "miss"

    def test_miss_empty(self):
        """cached_answer 为空字符串时返回 miss"""
        state = _make_state(cached_answer="")
        assert check_cache_hit(state) == "miss"


# ========== route_by_intent 条件函数测试 ==========

class TestRouteByIntent:
    """意图路由条件函数测试"""

    def test_direct_reply(self):
        """action=direct_reply 路由到 direct_reply"""
        state = _make_state(
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "greeting"},
        )
        assert route_by_intent(state) == "direct_reply"

    def test_order_query(self):
        """order_query 路由到 order"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "order_query"},
        )
        assert route_by_intent(state) == "order"

    def test_logistics_track(self):
        """logistics_track 路由到 order"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "logistics_track"},
        )
        assert route_by_intent(state) == "order"

    def test_product_inquiry(self):
        """product_inquiry 路由到 product"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "product_inquiry"},
        )
        assert route_by_intent(state) == "product"

    def test_knowledge_faq(self):
        """knowledge_faq 路由到 general（mibao 知识库已禁用，fallback 到 general）"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "knowledge_faq"},
            agent_type="mibao",
        )
        assert route_by_intent(state) == "general"

    def test_knowledge_faq_non_mibao(self):
        """knowledge_faq 非 mibao 时走 skill_registry 原始路由（xiaobu 保留知识库）"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "knowledge_faq"},
            agent_type="xiaobu",
        )
        # xiaobu 不应用 _KNOWLEDGE_FALLBACK，走原始路由
        assert route_by_intent(state) != "general"

    def test_knowledge_faq_default_agent_type(self):
        """knowledge_faq 默认 agent_type="" 不应用 fallback"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "knowledge_faq"},
        )
        assert route_by_intent(state) != "general"

    def test_after_sales(self):
        """after_sales 路由到 aftersales"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "after_sales"},
        )
        assert route_by_intent(state) == "aftersales"

    def test_complaint(self):
        """complaint 路由到 aftersales"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "complaint"},
        )
        assert route_by_intent(state) == "aftersales"

    def test_greeting_via_intent(self):
        """greeting 路由到 direct_reply"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "greeting"},
        )
        assert route_by_intent(state) == "direct_reply"

    def test_general(self):
        """general 路由到 general"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "general"},
        )
        assert route_by_intent(state) == "general"

    def test_unknown_intent_defaults_to_general(self):
        """未知意图默认路由到 general"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "unknown_type"},
        )
        assert route_by_intent(state) == "general"

    def test_no_route_decision(self):
        """无 route_decision 时默认 full_agent → general"""
        state = _make_state(route_decision=None, intent_result=None)
        assert route_by_intent(state) == "general"

    def test_direct_reply_with_multimodal_routes_to_general(self):
        """多模态消息 + action=direct_reply 应路由到 general（走 vision mode）而非 direct_reply"""
        # 模拟最后一条 HumanMessage 含 image_url 的多模态消息
        from langchain_core.messages import AIMessage

        multimodal_messages = [
            HumanMessage(content="你好，请介绍一下你自己"),
            AIMessage(content="您好！我是米宝..."),
            HumanMessage(content=[
                {"type": "text", "text": "你能识别图片中的信息吗"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
            ]),
        ]
        state = _make_state(
            messages=multimodal_messages,
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "capabilities"},
        )
        assert route_by_intent(state) == "general"

    def test_direct_reply_without_multimodal_stays_direct_reply(self):
        """纯文本消息 + action=direct_reply 应保持直复路由（回归保护）"""
        state = _make_state(
            messages=[HumanMessage(content="你好")],
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "greeting"},
        )
        assert route_by_intent(state) == "direct_reply"

    # ── P0-1: order_create 路由修复 ──

    def test_order_create_routes_to_order(self):
        """Bug 修复：order_create 意图应路由到 order，而非 general"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "order_create"},
        )
        assert route_by_intent(state) == "order"

    def test_order_create_not_general(self):
        """Bug 修复：order_create 绝对不能路由到 general"""
        state = _make_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "order_create", "confidence": 0.5},
        )
        assert route_by_intent(state) != "general"

    # ── P0-2: 会话连续性（pending_interact_skill）──

    def test_pending_interact_skill_overrides_low_confidence(self):
        """interact 后低置信度分类消息仍回到原 skill"""
        state = _make_state(
            pending_interact_skill="product",
            route_decision={"action": "full_agent"},
            intent_result={"intent": "general", "confidence": 0.3},
        )
        assert route_by_intent(state) == "product"

    def test_pending_interact_skill_stays_for_same_intent(self):
        """interact 后即使分类为同一域，也走 pending skill"""
        state = _make_state(
            pending_interact_skill="product",
            route_decision={"action": "full_agent"},
            intent_result={"intent": "product_inquiry", "confidence": 0.5},
        )
        assert route_by_intent(state) == "product"

    def test_pending_interact_skill_not_overridden_by_high_confidence(self):
        """pending skill 存在时任何意图都不能覆盖，始终回到原 skill"""
        state = _make_state(
            pending_interact_skill="product",
            route_decision={"action": "full_agent"},
            intent_result={"intent": "order_query", "confidence": 0.95},
        )
        # P&E 模式下 pending skill 是绝对锁，高置信度也不能跳走
        assert route_by_intent(state) == "product"

    def test_pending_interact_skill_overrides_direct_reply(self):
        """pending skill 存在时，direct_reply 也应被覆盖"""
        state = _make_state(
            pending_interact_skill="product",
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "greeting", "confidence": 0.99},
        )
        assert route_by_intent(state) == "product"

    def test_no_pending_interact_skill_normal_routing(self):
        """无 pending skill 时正常路由（回归保护）"""
        state = _make_state(
            pending_interact_skill="",
            route_decision={"action": "full_agent"},
            intent_result={"intent": "order_query"},
        )
        assert route_by_intent(state) == "order"

    def test_pending_interact_skill_cleared(self):
        """pending_interact_skill 为空字符串时不影响路由"""
        state = _make_state(
            pending_interact_skill="",
            route_decision={"action": "full_agent"},
            intent_result={"intent": "general"},
        )
        assert route_by_intent(state) == "general"
