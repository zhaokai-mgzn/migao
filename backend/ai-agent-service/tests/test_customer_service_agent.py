"""
Tests for app/agents/customer_service_agent.py
Covers: AgentResponse, AgentContext, BaseAgent, get_agent, reset_agent,
         _extract_msg_content, backward compat aliases
"""
import pytest
from unittest.mock import MagicMock, patch

from app.agents.customer_service_agent import (
    AgentResponse,
    AgentContext,
    _extract_msg_content,
    get_agent,
    reset_agent,
    CustomerServiceAgent,
    WorkAssistantAgent,
    BaseAgent,
)
from app.tools import ToolContext


class TestAgentResponse:
    def test_default_values(self):
        resp = AgentResponse(content="hello")
        assert resp.content == "hello"
        assert resp.type == "text"
        assert resp.tool_calls is None
        assert resp.metadata is None

    def test_tool_call_response(self):
        resp = AgentResponse(content="", type="tool_call",
            tool_calls=[{"tool": "search", "tool_input": {"q": "test"}}])
        assert resp.type == "tool_call"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["tool"] == "search"

    def test_error_response_with_metadata(self):
        resp = AgentResponse(content="error", type="error",
            metadata={"error": "ConnectionError"})
        assert resp.type == "error"
        assert resp.metadata["error"] == "ConnectionError"


class TestAgentContext:
    def test_default_values(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1")
        assert ctx.role == "customer"
        assert ctx.identity_type == "wechat_mini"
        assert ctx.user_name is None

    def test_custom_values(self):
        ctx = AgentContext(user_id="u2", tenant_id=200, session_id="s2",
            role="admin", identity_type="web", user_name="TestUser")
        assert ctx.role == "admin"
        assert ctx.identity_type == "web"
        assert ctx.user_name == "TestUser"

    def test_to_dict(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1", user_name="Alice")
        d = ctx.to_dict()
        assert d["user_id"] == "u1"
        assert d["tenant_id"] == 100
        assert d["role"] == "customer"
        assert d["user_name"] == "Alice"
        assert "identity_type" in d

    def test_to_tool_context(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1", role="customer")
        tc = ctx.to_tool_context()
        assert isinstance(tc, ToolContext)
        assert tc.tenant_id == 100
        assert tc.user_id == "u1"


class TestExtractMsgContent:
    def test_plain_text(self):
        msg = MagicMock()
        msg.content = "hello world"
        assert _extract_msg_content(msg) == "hello world"

    def test_strips_think_tags(self):
        msg = MagicMock()
        msg.content = "<think>reasoning</think>actual response"
        assert _extract_msg_content(msg) == "actual response"

    def test_multiline_think_tag(self):
        msg = MagicMock()
        msg.content = "<think>\nline1\nline2\n</think>visible"
        assert _extract_msg_content(msg) == "visible"

    def test_no_think_tag(self):
        msg = MagicMock()
        msg.content = "normal response"
        assert _extract_msg_content(msg) == "normal response"

    def test_multimodal_content_list(self):
        msg = MagicMock()
        msg.content = [
            {"type": "text", "text": "part1"},
            {"type": "image_url", "image_url": {"url": "http://x.com/1.jpg"}},
            {"type": "text", "text": "part2"},
        ]
        assert _extract_msg_content(msg) == "part1part2"

    def test_empty_think_only(self):
        msg = MagicMock()
        msg.content = "<think>reasoning</think>"
        assert _extract_msg_content(msg) == ""


class TestConvertHistory:
    @pytest.fixture
    def agent(self):
        reset_agent()
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            cfg = MagicMock()
            cfg.get_direct_reply = MagicMock(return_value=None)
            cfg.greeting = "test"
            mock_cfg.return_value = cfg
            return BaseAgent(agent_type="xiaobu")

    def test_empty_history(self, agent):
        assert agent._convert_history(None) == []

    def test_empty_list(self, agent):
        assert agent._convert_history([]) == []

    def test_user_message(self, agent):
        from langchain_core.messages import HumanMessage
        result = agent._convert_history([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)
        assert result[0].content == "hello"

    def test_assistant_message(self, agent):
        from langchain_core.messages import AIMessage
        result = agent._convert_history([{"role": "assistant", "content": "hi"}])
        assert len(result) == 1
        assert isinstance(result[0], AIMessage)

    def test_mixed_history(self, agent):
        result = agent._convert_history([
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ])
        assert len(result) == 3

    def test_multimodal_message(self, agent):
        result = agent._convert_history([{
            "role": "user", "content": "img", "content_type": "mixed",
            "images": ["http://x.com/1.jpg"]}])
        assert len(result) == 1
        assert isinstance(result[0].content, list)

    def test_unknown_role_skipped(self, agent):
        assert agent._convert_history([{"role": "system", "content": "x"}]) == []


class TestGetGreeting:
    @pytest.fixture
    def agent(self):
        reset_agent()
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            cfg = MagicMock()
            cfg.get_direct_reply = MagicMock(return_value="Hello from config")
            cfg.greeting = "default greeting"
            mock_cfg.return_value = cfg
            return BaseAgent(agent_type="xiaobu")

    @pytest.mark.asyncio
    async def test_returns_direct_reply_greeting(self, agent):
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        assert await agent.get_greeting(ctx) == "Hello from config"

    @pytest.mark.asyncio
    async def test_falls_back_to_agent_config_greeting(self, agent):
        agent._agent_config.get_direct_reply.return_value = None
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        assert await agent.get_greeting(ctx) == "default greeting"


class TestGetAgent:
    def setup_method(self):
        reset_agent()

    def teardown_method(self):
        reset_agent()

    def test_get_agent_returns_instance(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = get_agent(agent_type="xiaobu")
            assert agent is not None
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "xiaobu"

    def test_same_instance_for_same_type(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            a2 = get_agent(agent_type="xiaobu")
            assert a1 is a2

    def test_different_types_separate(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            a2 = get_agent(agent_type="mibao")
            assert a1 is not a2

    def test_reset_clears_cache(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            reset_agent()
            a2 = get_agent(agent_type="xiaobu")
            assert a1 is not a2


class TestBackwardCompatAliases:
    def test_customer_service_agent(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = CustomerServiceAgent()
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "xiaobu"

    def test_work_assistant_agent(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = WorkAssistantAgent()
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "mibao"
