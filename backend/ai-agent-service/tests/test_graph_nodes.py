"""图辅助节点单元测试（app/graph/nodes.py）

覆盖：
- _extract_text_from_content：str / None / list / 非文本兜底
- _get_last_human_text / _last_human_has_image：多模态检测
- direct_reply_node：greeting/farewell/capabilities 兜底
- intent_router_node：pending_skill 短消息合成意图快捷路由
- intent_router_node：plan_rewrite 路径澄清轮护栏（连续模糊意图触发兜底）
- route_by_intent：direct_reply + 多模态重定向 general、escape hatch 切换、会话连续性
"""
# case_ids: CH-002, CH-003, CH-018, CH-022
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import (
    _extract_text_from_content,
    _get_last_human_text,
    _last_human_has_image,
    direct_reply_node,
    intent_router_node,
    route_by_intent,
)


class TestExtractTextFromContent:
    def test_string_passthrough(self):
        assert _extract_text_from_content("你好") == "你好"

    def test_none_returns_empty(self):
        assert _extract_text_from_content(None) == ""

    def test_list_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "x"}},
            {"type": "text", "text": "世界"},
        ]
        assert _extract_text_from_content(content) == "你好 世界"

    def test_non_dict_list_ignored(self):
        content = [{"type": "text", "text": "a"}, "raw", 123]
        assert _extract_text_from_content(content) == "a"

    def test_non_string_fallback(self):
        assert _extract_text_from_content(42) == "42"


class TestGetLastHumanText:
    def test_string_content(self):
        messages = [HumanMessage(content="hello")]
        assert _get_last_human_text(messages) == "hello"

    def test_list_content(self):
        messages = [HumanMessage(content=[{"type": "text", "text": "hi"}])]
        assert _get_last_human_text(messages) == "hi"

    def test_no_human_message(self):
        assert (_get_last_human_text([AIMessage(content="assistant")]) is None)

    def test_image_only_returns_none(self):
        messages = [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])]
        assert (_get_last_human_text(messages) is None)


class TestLastHumanHasImage:
    def test_image_detected(self):
        messages = [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])]
        assert _last_human_has_image(messages) is True

    def test_no_image(self):
        messages = [HumanMessage(content="纯文本")]
        assert _last_human_has_image(messages) is False

    def test_no_human(self):
        assert _last_human_has_image([AIMessage(content="a")]) is False


class TestDirectReplyNode:
    @pytest.mark.asyncio
    async def test_greeting_fallback(self):
        with patch("app.agents.agent_config.get_agent_config", side_effect=ImportError):
            state = {
                "intent_result": {"intent": "greeting"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert result["skill_used"] == "direct_reply"
        assert "帮您" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_farewell_fallback(self):
        with patch("app.agents.agent_config.get_agent_config", side_effect=ImportError):
            state = {
                "intent_result": {"intent": "farewell"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert "随时找我" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_config_reply_preferred(self):
        fake_config = MagicMock()
        fake_config.get_direct_reply.return_value = "自定义问候"
        with patch("app.agents.agent_config.get_agent_config", return_value=fake_config):
            state = {
                "intent_result": {"intent": "greeting"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert result["final_answer"] == "自定义问候"


class TestIntentRouterNode:
    @pytest.mark.asyncio
    async def test_pending_skill_short_msg_rewrites_intent(self):
        state = {
            "pending_interact_skill": "product",
            "session_id": "s1",
            "messages": [HumanMessage(content="确认")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "product_inquiry"
        assert result["intent_result"]["confidence"] == 0.99
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"

    @pytest.mark.asyncio
    async def test_pending_skill_order_maps_to_order_query(self):
        state = {
            "pending_interact_skill": "order",
            "session_id": "s1",
            "messages": [HumanMessage(content="1")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "order_query"

    @pytest.mark.asyncio
    async def test_no_pending_skill_runs_llm(self):
        mock_route_decision = MagicMock()
        mock_route_decision.intent_result.intent.value = "greeting"
        mock_route_decision.intent_result.confidence = 0.9
        mock_route_decision.intent_result.source = "llm"
        mock_route_decision.action = "direct_reply"
        mock_route_decision.direct_reply = "您好"
        mock_route_decision.tool_hint = None

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_route_decision)

        state = {
            "session_id": "s1",
            "agent_type": "xiaobu",
            "messages": [HumanMessage(content="你好")],
        }
        with patch("app.router.intent_router.IntentRouter", return_value=mock_router), \
             patch("app.graph.nodes._get_agent_intents", return_value=["greeting", "general"]), \
             patch("app.graph.nodes._build_entity_hint", new=AsyncMock(return_value="")):
            result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "greeting"
        assert result["route_decision"]["action"] == "direct_reply"

    # ── 澄清轮护栏：plan_rewrite 路径（pending_skill 短消息）也必须接入护栏 ──
    # 真实验收发现（#2801）：连续模糊意图（"帮我看看"→"就是那个"→"你懂的"）
    # 澄清卡下发后 pending_skill 已设置，后续模糊轮走 plan_rewrite 提前 return，
    # 完全绕过护栏挂点 → 兜底话术永不触发。本组测试锁定该缺陷。

    @staticmethod
    def _mock_clarify_store(state_dict):
        """内存版 SessionStateStore（与 test_clarify_guard 同构）。"""
        store = MagicMock()
        store.load = AsyncMock(return_value=dict(state_dict))
        store.commit = AsyncMock(side_effect=lambda sid, st: (state_dict.clear(), state_dict.update(st)))
        return store

    @pytest.mark.asyncio
    async def test_pending_skill_vague_short_msg_reaches_clarify_limit_returns_fallback(self):
        """缺陷锁定：plan_rewrite 短消息（如"就是那个"）连续模糊已达上限 → 应返回兜底话术。"""
        from app.graph.clarify_guard import (
            CLARIFY_STATE_KEY,
            CLARIFY_FORCE_EXAMPLE_TEXT,
            MAX_CLARIFY_ROUNDS,
        )

        store = self._mock_clarify_store(
            {CLARIFY_STATE_KEY: {"count": MAX_CLARIFY_ROUNDS, "force_example": True}}
        )
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="就是那个")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        # 护栏改写为 direct_reply 兜底话术（而非继续 plan_rewrite 弹卡）
        assert result["route_decision"]["action"] == "direct_reply"
        assert result["route_decision"]["direct_reply"] == CLARIFY_FORCE_EXAMPLE_TEXT

    @pytest.mark.asyncio
    async def test_pending_skill_vague_short_msg_increments_clarify_count(self):
        """plan_rewrite 模糊短消息应计澄清轮（count +1 写回），未达上限继续 plan_rewrite。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 1, "force_example": False}})
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="你懂的")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 2

    @pytest.mark.asyncio
    async def test_pending_skill_domain_keyword_resets_clarify(self):
        """plan_rewrite 短消息含领域关键词（如"查订单"）→ 实质意图，清零计数。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store(
            {CLARIFY_STATE_KEY: {"count": 2, "force_example": True}}
        )
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="查订单")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 0

    @pytest.mark.asyncio
    async def test_pending_customer_general_vague_short_msg_counts_clarify(self):
        """C 端澄清卡由 customer_general skill 下发：pending_skill=customer_general
        的模糊短消息也应计澄清轮（真实验收 #2801 发现：只认 general 导致 C 端
        护栏永不计数、兜底不触发）。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 1, "force_example": False}})
        state = {
            "pending_interact_skill": "customer_general",
            "session_id": "s1",
            "messages": [HumanMessage(content="你懂的")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 2

    @pytest.mark.asyncio
    async def test_general_intent_classifier_source_counts_clarify_round(self):
        """主挂点：classifier 直接判 general（非 low_confidence 重写）也计澄清轮。

        真实验收 #2801 发现：R1"帮我看看"confidence=0.30 被 classifier 判 general
        （GENERAL 在低置信重写豁免清单内，source 非 low_confidence），旧判定
        source=="low_confidence" 不成立 → 首轮未计数 → 兜底推迟一轮。
        """
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 0, "force_example": False}})

        mock_route_decision = MagicMock()
        mock_route_decision.intent_result.intent.value = "general"
        mock_route_decision.intent_result.confidence = 0.30
        mock_route_decision.intent_result.source = "classifier"
        mock_route_decision.action = "full_agent"
        mock_route_decision.direct_reply = None
        mock_route_decision.tool_hint = None

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_route_decision)

        state = {
            "session_id": "s1",
            "agent_type": "mibao",
            "messages": [HumanMessage(content="帮我看看")],
        }
        with patch("app.router.intent_router.IntentRouter", return_value=mock_router), \
             patch("app.graph.nodes._get_agent_intents", return_value=["general"]), \
             patch("app.graph.nodes._build_entity_hint", new=AsyncMock(return_value="")), \
             patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 1


class TestRouteByIntent:
    def test_direct_reply_no_pending(self):
        state = {
            "route_decision": {"action": "direct_reply"},
            "messages": [HumanMessage(content="你好")],
        }
        assert route_by_intent(state) == "direct_reply"

    def test_direct_reply_multimodal_redirects_to_general(self):
        state = {
            "route_decision": {"action": "direct_reply"},
            "messages": [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])],
        }
        assert route_by_intent(state) == "general"

    def test_pending_skill_stays_on_same_skill(self):
        state = {
            "pending_interact_skill": "product",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "product_inquiry"},
            "messages": [HumanMessage(content="好的，继续")],
        }
        assert route_by_intent(state) == "product"

    def test_pending_skill_guard_forced_bypasses_pending(self):
        """护栏强制兜底（guard_forced=True）不被 pending_skill 覆盖。

        真实验收 #2801 发现：澄清护栏改写为 direct_reply 兜底话术后，
        route_by_intent 因 pending_skill 存在又覆盖回 general skill →
        兜底永不触达用户。guard_forced 标记必须穿透 pending_skill。
        """
        state = {
            "pending_interact_skill": "general",
            "route_decision": {"action": "direct_reply", "guard_forced": True},
            "intent_result": {"intent": "general"},
            "messages": [HumanMessage(content="你懂的")],
        }
        assert route_by_intent(state) == "direct_reply"

    def test_pending_skill_escape_hatch_switches_domain(self):
        state = {
            "pending_interact_skill": "product",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "order_query"},
            "messages": [HumanMessage(content="帮我查一下订单")],
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"order_query": "order_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "order_skill"

    def test_no_pending_routes_by_intent(self):
        state = {
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "product_inquiry"},
            "messages": [HumanMessage(content="搜窗帘")],
            "agent_type": "",
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"product_inquiry": "product_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "product_skill"
