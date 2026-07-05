"""
Tests for BaseAgent state initialization — coverage for issue #947
Verifies recent_entities / user_role / user_name fields in initial state.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import json

from app.agents.customer_service_agent import (
    BaseAgent,
    AgentContext,
    CustomerServiceAgent,
)


class TestBaseAgentState:
    """BaseAgent._build_initial_state 验证"""

    @pytest.fixture
    def mock_context(self):
        return AgentContext(
            user_id="100",
            tenant_id=1,
            session_id="sess_test",
            role="customer",
            identity_type="wechat_mini",
            user_name="TestUser",
        )

    @pytest.fixture
    def agent(self):
        return CustomerServiceAgent()

    async def test_initial_state_has_recent_entities(self, agent, mock_context):
        """#947: _build_initial_state 必须包含 recent_entities 字段"""
        from langchain_core.messages import HumanMessage

        state = await agent._build_initial_state(
            [HumanMessage(content="hello")], mock_context
        )
        assert "recent_entities" in state, (
            "recent_entities 字段缺失，suggestions_node 依赖此字段"
        )
        assert state["recent_entities"] == [], (
            "recent_entities 初始值应为空列表"
        )

    async def test_initial_state_all_required_fields(self, agent, mock_context):
        """验证 _build_initial_state 包含所有必需字段（回归保护）"""
        from langchain_core.messages import HumanMessage

        state = await agent._build_initial_state(
            [HumanMessage(content="hello")], mock_context
        )

        required_fields = [
            "messages", "agent_type", "tenant_id", "user_id", "user_name",
            "session_id", "role", "intent_result", "route_decision",
            "entities", "recent_entities", "intent_chain", "stage",
            "cached_answer", "final_answer", "skill_used", "suggestions",
            "pending_interact_skill",
        ]
        for field in required_fields:
            assert field in state, f"缺少字段: {field}"

    async def test_user_name_passed_to_state(self, agent, mock_context):
        """验证 user_name 正确传入 state"""
        from langchain_core.messages import HumanMessage

        state = await agent._build_initial_state(
            [HumanMessage(content="hello")], mock_context
        )
        assert state["user_name"] == "TestUser"

    async def test_role_passed_to_state(self, agent, mock_context):
        """验证 role 正确传入 state"""
        from langchain_core.messages import HumanMessage

        state = await agent._build_initial_state(
            [HumanMessage(content="hello")], mock_context
        )
        assert state["role"] == "customer"


class TestAgentContext:
    """AgentContext 字段验证（与 state 映射一致性）"""

    def test_context_has_user_name(self):
        ctx = AgentContext(
            user_id="100", tenant_id=1, session_id="s1", user_name="Alice"
        )
        assert ctx.user_name == "Alice"
        d = ctx.to_dict()
        assert d["user_name"] == "Alice"

    def test_context_default_role(self):
        ctx = AgentContext(user_id="100", tenant_id=1, session_id="s1")
        assert ctx.role == "customer"
