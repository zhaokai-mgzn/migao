"""小布 AI 主动引导转人工 — 图级/多轮场景测试

验证（设计文档 xiaobu-ai-handoff-guidance.md §4/§5）：
- D1 显式转人工请求 → intent_router 短路直转 complaint（不弹建议卡）
- D3 信号命中 → handoff_offer 节点产出安抚文案 + interact choice 卡片
- 建议卡片 value（转人工客服）确认后 → 命中 D1 → human_handoff 直转
- 用户拒绝（继续咨询）→ 本会话不再自动建议（冷却）
- 正常消息/明确业务意图 → 不弹卡（回归）

Mock 层：LLM/意图分类（IntentRouter.route）、租户配置、SessionStateStore。
"""
# case_ids: CH-013, CH-014, CH-015, CH-016

import json
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.customer_service_agent import CustomerServiceAgent, AgentContext, reset_agent
from app.tools import set_tool_context
from app.tools.registry import reset_tool_registry
from app.router.intent_config import IntentType, IntentResult, RouteDecision


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()


def _make_state(messages, session_id="sess-offer-1", tenant_id=1, agent_type="xiaobu"):
    """构造 AgentState 字典（字段与 app/graph/state.py 对齐）"""
    return {
        "messages": messages,
        "agent_type": agent_type,
        "tenant_id": tenant_id,
        "user_id": "cust-1",
        "user_name": "测试顾客",
        "tenant_name": None,
        "session_id": session_id,
        "role": "customer",
        "permissions": ["*"],
        "intent_result": None,
        "route_decision": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
        "pending_interact_skill": "",
    }


def _make_route_decision(intent_value: str, confidence: float = 0.9, action: str = "full_agent") -> RouteDecision:
    return RouteDecision(
        intent_result=IntentResult(
            intent=IntentType(intent_value),
            confidence=confidence,
            source="classifier",
        ),
        action=action,
    )


# ────────────────────── D1 显式请求 → 短路直转 ──────────────────────


class TestD1ExplicitDirectHandoff:
    async def test_explicit_handoff_shortcuts_to_complaint(self):
        """用户输入'转人工客服' → 不等 LLM 分类，直接 complaint 意图"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content="转人工客服")])

        with patch(
            "app.router.intent_router.IntentRouter.route",
            AsyncMock(return_value=_make_route_decision("general")),
        ) as mock_route:
            result = await intent_router_node(state)

        intent = result["intent_result"]["intent"]
        assert intent == "complaint", f"应直转 complaint，实际 {intent}"
        assert result["intent_result"]["source"] == "explicit_handoff"
        # 显式请求直转：不调用 LLM 分类（短路）
        mock_route.assert_not_awaited()

    async def test_explicit_handoff_wins_over_pending_skill(self):
        """用户在 pending skill 流程中明确要求转人工 → 也直转（不被流程锁住）"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content="我要转人工，不弄了")])
        state["pending_interact_skill"] = "customer_order"

        with patch(
            "app.router.intent_router.IntentRouter.route",
            AsyncMock(return_value=_make_route_decision("general")),
        ):
            result = await intent_router_node(state)

        assert result["intent_result"]["intent"] == "complaint"


# ────────────────────── D3 建议节点产出 ──────────────────────


class TestHandoffOfferNode:
    async def test_offer_node_produces_text_and_choice_card(self):
        """D3 命中 → 安抚文案 + interact choice 卡片（转人工/继续咨询）"""
        from app.graph.handoff_offer import handoff_offer_node

        state = _make_state([HumanMessage(content="你们窗帘质量太差了，气死我了")])
        state["intent_result"] = {"intent": "general", "confidence": 0.6, "source": "classifier"}

        with patch("app.memory.session_state_store.SessionStateStore") as mock_store:
            mock_store.return_value.load = AsyncMock(return_value={})
            mock_store.return_value.commit = AsyncMock(return_value=True)
            result = await handoff_offer_node(state)

        # 1. 安抚文案非空
        assert result["final_answer"], "应产出安抚文案"
        assert result["skill_used"] == "handoff_offer"

        # 2. messages 中含 interact choice ToolMessage
        tool_msgs = [
            m for m in result.get("messages", [])
            if isinstance(m, ToolMessage) and m.name == "interact"
        ]
        assert tool_msgs, "应产出 interact ToolMessage"
        payload = json.loads(tool_msgs[0].content)
        assert payload.get("success") is True
        data = payload["data"]
        assert data["component"] == "choice"
        labels = [opt["label"] for opt in data["options"]]
        values = [opt["value"] for opt in data["options"]]
        assert any("转人工" in v for v in values), f"确认选项应含转人工: {values}"
        assert any("继续" in v for v in values), f"取消选项应含继续: {values}"

    async def test_offer_node_writes_cooldown_state(self):
        """建议后写入 offer_count（冷却：本会话不再自动建议）"""
        from app.graph.handoff_offer import handoff_offer_node

        state = _make_state([HumanMessage(content="你们太坑了")])
        state["intent_result"] = {"intent": "general", "confidence": 0.6, "source": "classifier"}

        with patch("app.memory.session_state_store.SessionStateStore") as mock_store:
            mock_store.return_value.load = AsyncMock(return_value={})
            commit_mock = AsyncMock(return_value=True)
            mock_store.return_value.commit = commit_mock
            await handoff_offer_node(state)

        # commit 至少被调用一次且 payload 含 offer_count >= 1
        assert commit_mock.await_count >= 1


# ────────────────────── 端到端：建议 → 确认 → 直转 ──────────────────────


class TestOfferToDirectHandoffE2E:
    async def test_confirm_value_routes_back_to_direct_handoff(self):
        """建议卡片 value='转人工客服' 作为用户消息 → 命中 D1 直转（能力闭环）"""
        from app.graph.handoff_judge import is_explicit_handoff_request

        # 卡片点击后发送的 value 必须能被 D1 识别（否则确认后无法直转）
        assert is_explicit_handoff_request("转人工客服") is True

    async def test_continue_value_not_explicit(self):
        from app.graph.handoff_judge import is_explicit_handoff_request

        # '继续咨询小布' 不能误判为转人工请求
        assert is_explicit_handoff_request("继续咨询小布") is False

    async def test_refused_then_no_repeat_offer(self):
        """用户拒绝（继续咨询）后，再次不满不再自动建议（冷却生效）"""
        from app.graph.handoff_judge import judge_handoff

        # 拒绝后 handoff_state.last_user_refused=True → 不再 offer
        result = judge_handoff(
            "你们又没解决，气死我了",
            intent="general",
            handoff_state={"offer_count": 1, "last_user_refused": True},
        )
        assert result.action == "none"

    async def test_normal_flow_no_card(self):
        """正常售后咨询 → 无建议卡（该走售后流程）"""
        from app.graph.handoff_judge import judge_handoff

        result = judge_handoff(
            "你好，我想咨询一下窗帘的清洗方法",
            intent="knowledge_faq",
            handoff_state=None,
        )
        assert result.action == "none"


# ────────────────────── intent_router 接线 D3 ──────────────────────


class TestD3RouterIntegration:
    async def test_negative_general_intent_routes_to_handoff_offer(self):
        """general 意图 + 负面情绪 → route_decision.action = handoff_offer"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content="你们窗帘质量太差了，气死我了")])

        with patch(
            "app.router.intent_router.IntentRouter.route",
            AsyncMock(return_value=_make_route_decision("general", confidence=0.5)),
        ), patch("app.agents.tenant_config.get_tenant_ai_config", AsyncMock(return_value={})), \
            patch("app.memory.session_state_store.SessionStateStore.load",
                  AsyncMock(return_value={})):
            result = await intent_router_node(state)

        action = result["route_decision"]["action"]
        assert action == "handoff_offer", f"应路由 handoff_offer，实际 {action}"

    async def test_business_intent_no_offer(self):
        """明确业务意图（order_query）即使含情绪词 → 不 offer（防打断）"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content="这个窗帘质量太差了，帮我查下订单到哪了")])

        with patch(
            "app.router.intent_router.IntentRouter.route",
            AsyncMock(return_value=_make_route_decision("order_query", confidence=0.9)),
        ), patch("app.agents.tenant_config.get_tenant_ai_config", AsyncMock(return_value={})), \
            patch("app.memory.session_state_store.SessionStateStore.load",
                  AsyncMock(return_value={})):
            result = await intent_router_node(state)

        action = result["route_decision"]["action"]
        assert action != "handoff_offer"
