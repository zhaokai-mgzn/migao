"""图辅助节点单元测试（app/graph/nodes.py）

覆盖：
- _extract_text_from_content：str / None / list / 非文本兜底
- _get_last_human_text / _last_human_has_image：多模态检测
- _infer_stage：pending/问候/告别/长回复 阶段推断
- direct_reply_node：greeting/farewell/capabilities 兜底
- intent_router_node：pending_skill 短消息合成意图快捷路由
- route_by_intent：direct_reply + 多模态重定向 general、escape hatch 切换、会话连续性
"""
# case_ids: CH-002, CH-003
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import (
    _extract_text_from_content,
    _get_last_human_text,
    _infer_stage,
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


class TestInferStage:
    def test_pending_interact_confirming(self):
        state = {"pending_interact_skill": "product"}
        assert _infer_stage(state, "product_inquiry") == "confirming"

    def test_direct_reply_greeting_initial(self):
        state = {"route_decision": {"action": "direct_reply"}}
        assert _infer_stage(state, "greeting") == "initial"

    def test_direct_reply_farewell_completed(self):
        state = {"route_decision": {"action": "direct_reply"}}
        assert _infer_stage(state, "farewell") == "completed"

    def test_long_answer_querying(self):
        state = {"route_decision": {"action": "full_agent"}, "final_answer": "很长的回答" * 10}
        assert _infer_stage(state, "order_query") == "querying"

    def test_default_initial(self):
        state = {"route_decision": {"action": "full_agent"}, "final_answer": "短"}
        assert _infer_stage(state, "order_query") == "initial"


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
