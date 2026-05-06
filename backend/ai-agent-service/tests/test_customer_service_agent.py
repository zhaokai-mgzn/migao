"""
CustomerServiceAgent 单元测试

测试 C 端智能客服 Agent 的核心逻辑（LangGraph 版本）
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.agents.customer_service_agent import (
    CustomerServiceAgent,
    AgentContext,
    AgentResponse,
    get_agent,
    reset_agent,
)


# ========== 测试辅助 fixtures ==========

@pytest.fixture
def agent_context():
    """标准 Agent 上下文"""
    return AgentContext(
        user_id="user_001",
        tenant_id=1,
        session_id="sess_001",
        role="customer",
        identity_type="wechat_mini",
    )


@pytest.fixture
def chat_history():
    """多轮对话历史"""
    return [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好！有什么可以帮您的吗？"},
    ]


# ========== AgentContext 测试 ==========

class TestAgentContext:
    """测试 AgentContext 数据类"""

    def test_context_to_dict(self, agent_context):
        """test_context_to_dict: 转为字典"""
        d = agent_context.to_dict()
        assert d["user_id"] == "user_001"
        assert d["tenant_id"] == 1
        assert d["session_id"] == "sess_001"
        assert d["role"] == "customer"
        assert d["identity_type"] == "wechat_mini"

    def test_context_to_tool_context(self, agent_context):
        """test_context_to_tool_context: 转为 ToolContext"""
        tc = agent_context.to_tool_context()
        assert tc.tenant_id == 1
        assert tc.user_id == "user_001"
        assert tc.session_id == "sess_001"
        assert tc.role == "customer"

    def test_context_default_values(self):
        """test_context_defaults: 默认值"""
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        assert ctx.role == "customer"
        assert ctx.identity_type == "wechat_mini"


# ========== AgentResponse 测试 ==========

class TestAgentResponse:
    """测试 AgentResponse 数据类"""

    def test_response_text(self):
        """test_response_text: 文本响应"""
        resp = AgentResponse(content="你好")
        assert resp.content == "你好"
        assert resp.type == "text"
        assert resp.tool_calls is None

    def test_response_error(self):
        """test_response_error: 错误响应"""
        resp = AgentResponse(
            content="出错了",
            type="error",
            metadata={"error": "timeout"},
        )
        assert resp.type == "error"
        assert resp.metadata["error"] == "timeout"

    def test_response_tool_call(self):
        """test_response_tool_call: 工具调用响应"""
        resp = AgentResponse(
            content="",
            type="tool_call",
            tool_calls=[{"tool": "order_query", "tool_input": {"order_id": "123"}}],
        )
        assert resp.type == "tool_call"
        assert len(resp.tool_calls) == 1


# ========== CustomerServiceAgent 初始化测试 ==========

class TestAgentInit:
    """测试 Agent 初始化（LangGraph 版本）"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_agent_default_registry(self, mock_create_registry, mock_build_graph):
        """test_agent_default_registry: 默认 registry"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        assert agent.tool_registry is mock_registry
        assert agent.graph is mock_build_graph.return_value

    @patch("app.graph.builder.build_agent_graph")
    def test_agent_custom_registry(self, mock_build_graph):
        """test_agent_custom_registry: 自定义 registry"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent(tool_registry=mock_registry)
        assert agent.tool_registry is mock_registry

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_convert_history(self, mock_create_registry, mock_build_graph):
        """test_convert_history: 转换对话历史"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        history = agent._convert_history([
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
            {"role": "unknown", "content": "ignore"},
        ])
        assert len(history) == 2  # unknown role 被忽略

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_convert_history_none(self, mock_create_registry, mock_build_graph):
        """test_convert_history_none: None 历史"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        history = agent._convert_history(None)
        assert history == []

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_convert_history_empty(self, mock_create_registry, mock_build_graph):
        """test_convert_history_empty: 空列表"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        history = agent._convert_history([])
        assert history == []

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_build_initial_state(self, mock_create_registry, mock_build_graph):
        """test_build_initial_state: 构建初始状态"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        state = agent._build_initial_state([], ctx)
        assert state["tenant_id"] == 1
        assert state["user_id"] == "u1"
        assert state["session_id"] == "s1"
        assert state["role"] == "customer"
        assert state["final_answer"] == ""
        assert state["suggestions"] == []
        assert state["cached_answer"] is None


# ========== achat 测试 ==========

class TestAChat:
    """测试非流式对话（LangGraph 版本）"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    @patch("app.agents.customer_service_agent.set_tool_context")
    async def test_achat_normal(
        self, mock_set_ctx, mock_create_registry, mock_build_graph,
        agent_context,
    ):
        """test_achat_normal: 正常对话"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "final_answer": "您好，有什么可以帮您的？",
        })
        mock_build_graph.return_value = mock_graph

        agent = CustomerServiceAgent()
        response = await agent.achat("你好", agent_context)

        assert response.content == "您好，有什么可以帮您的？"
        assert response.type == "text"

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    @patch("app.agents.customer_service_agent.set_tool_context")
    async def test_achat_with_history(
        self, mock_set_ctx, mock_create_registry, mock_build_graph,
        agent_context, chat_history,
    ):
        """test_achat_with_history: 带历史的对话"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={"final_answer": "好的"})
        mock_build_graph.return_value = mock_graph

        agent = CustomerServiceAgent()
        response = await agent.achat("查询订单", agent_context, chat_history)

        assert response.content == "好的"
        # 验证 ainvoke 被调用
        mock_graph.ainvoke.assert_called_once()
        # 验证传入的 state 包含历史消息 + 当前消息
        call_args = mock_graph.ainvoke.call_args[0][0]
        assert len(call_args["messages"]) == 3  # 2 history + 1 current

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    @patch("app.agents.customer_service_agent.set_tool_context")
    async def test_achat_exception_returns_error(
        self, mock_set_ctx, mock_create_registry, mock_build_graph,
        agent_context,
    ):
        """test_achat_exception: 异常时返回错误响应"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))
        mock_build_graph.return_value = mock_graph

        agent = CustomerServiceAgent()
        response = await agent.achat("你好", agent_context)

        assert response.type == "error"
        assert "抱歉" in response.content
        assert response.metadata["error"] == "LLM timeout"


# ========== get_greeting 测试 ==========

class TestGetGreeting:
    """测试欢迎语"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    async def test_get_greeting_xiaobu(self, mock_create_registry, mock_build_graph, agent_context):
        """test_get_greeting_xiaobu: 小布欢迎语包含'小布'和'智能客服'"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        greeting = await agent.get_greeting(agent_context)
        assert "小布" in greeting
        assert "客服" in greeting


# ========== 单例模式测试 ==========

class TestAgentSingleton:
    """测试 Agent 单例模式"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_singleton(self, mock_create_registry, mock_build_graph):
        """test_singleton: 单例模式"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        reset_agent()
        a1 = get_agent()
        a2 = get_agent()
        assert a1 is a2
        reset_agent()

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_reset_agent(self, mock_create_registry, mock_build_graph):
        """test_reset: 重置后重新创建"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_registry.return_value = mock_registry
        mock_build_graph.return_value = MagicMock()

        reset_agent()
        a1 = get_agent()
        reset_agent()
        a2 = get_agent()
        assert a1 is not a2
        reset_agent()
