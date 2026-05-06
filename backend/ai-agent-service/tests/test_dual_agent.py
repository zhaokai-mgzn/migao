"""
双 Agent 拆分测试

覆盖：
- Agent 实例化（mibao / xiaobu）
- Agent 类型验证
- Greeting 差异化验证
- get_agent 工厂函数
- Graph Builder 双类型构建
- 向后兼容性
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.agents.customer_service_agent import (
    BaseAgent,
    CustomerServiceAgent,
    WorkAssistantAgent,
    AgentContext,
    AgentResponse,
    get_agent,
    reset_agent,
)


# ========== Fixtures ==========

@pytest.fixture(autouse=True)
def _reset_agent_instances():
    """每个测试前后重置全局 Agent 实例"""
    reset_agent()
    yield
    reset_agent()


@pytest.fixture
def agent_context():
    return AgentContext(
        user_id="user_001",
        tenant_id=1,
        session_id="sess_001",
        role="customer",
        identity_type="wechat_mini",
    )


# ========== Agent 类型验证 ==========

class TestAgentTypes:
    """验证双 Agent 的 _agent_type 属性"""

    def test_customer_service_agent_type(self):
        """CustomerServiceAgent._agent_type == 'xiaobu'"""
        assert CustomerServiceAgent._agent_type == "xiaobu"

    def test_work_assistant_agent_type(self):
        """WorkAssistantAgent._agent_type == 'mibao'"""
        assert WorkAssistantAgent._agent_type == "mibao"

    def test_base_agent_default_type(self):
        """BaseAgent 默认 _agent_type 为 'xiaobu'"""
        assert BaseAgent._agent_type == "xiaobu"


# ========== Agent 实例化测试 ==========

class TestAgentInstantiation:
    """验证双 Agent 实例化"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_xiaobu_instance(self, mock_create_registry, mock_build_graph):
        """CustomerServiceAgent 实例化正确"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        assert isinstance(agent, CustomerServiceAgent)
        assert isinstance(agent, BaseAgent)
        assert agent._agent_type == "xiaobu"
        mock_build_graph.assert_called_once_with("xiaobu")

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_mibao_instance(self, mock_create_registry, mock_build_graph):
        """WorkAssistantAgent 实例化正确"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = WorkAssistantAgent()
        assert isinstance(agent, WorkAssistantAgent)
        assert isinstance(agent, BaseAgent)
        assert agent._agent_type == "mibao"
        mock_build_graph.assert_called_once_with("mibao")


# ========== get_agent 工厂函数测试 ==========

class TestGetAgentFactory:
    """验证 get_agent 工厂函数的双 Agent 路由"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_mibao(self, mock_create_registry, mock_build_graph):
        """get_agent(agent_type='mibao') 返回 WorkAssistantAgent"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="mibao")
        assert isinstance(agent, WorkAssistantAgent)

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_xiaobu(self, mock_create_registry, mock_build_graph):
        """get_agent(agent_type='xiaobu') 返回 CustomerServiceAgent"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="xiaobu")
        assert isinstance(agent, CustomerServiceAgent)

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_default_is_xiaobu(self, mock_create_registry, mock_build_graph):
        """默认 get_agent() 返回 CustomerServiceAgent（向后兼容）"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent()
        assert isinstance(agent, CustomerServiceAgent)

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_with_registry(self, mock_create_registry, mock_build_graph):
        """get_agent 传入 tool_registry 后不调用 create_default_registry"""
        mock_build_graph.return_value = MagicMock()
        custom_registry = MagicMock()

        agent = get_agent(tool_registry=custom_registry, agent_type="mibao")
        assert agent.tool_registry is custom_registry
        mock_create_registry.assert_not_called()

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_mibao_and_xiaobu_are_different_instances(self, mock_create_registry, mock_build_graph):
        """米宝和小布是不同的 Agent 实例"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        mibao = get_agent(agent_type="mibao")
        xiaobu = get_agent(agent_type="xiaobu")
        assert mibao is not xiaobu
        assert isinstance(mibao, WorkAssistantAgent)
        assert isinstance(xiaobu, CustomerServiceAgent)


# ========== Greeting 差异化测试 ==========

class TestGreetings:
    """验证双 Agent 欢迎语差异"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    async def test_mibao_greeting(self, mock_create_registry, mock_build_graph, agent_context):
        """米宝的 greeting 包含'米宝'和'智能工作助手'"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = WorkAssistantAgent()
        greeting = await agent.get_greeting(agent_context)
        assert "米宝" in greeting
        assert "工作助手" in greeting

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    async def test_xiaobu_greeting(self, mock_create_registry, mock_build_graph, agent_context):
        """小布的 greeting 包含'小布'和'智能客服'"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = CustomerServiceAgent()
        greeting = await agent.get_greeting(agent_context)
        assert "小布" in greeting
        assert "客服" in greeting


# ========== SKILL_NODES 差异化测试 ==========

class TestSkillNodes:
    """验证双 Agent 的 SKILL_NODES 配置"""

    def test_xiaobu_skill_nodes(self):
        """小布使用 customer_* 前缀的 Skill 节点"""
        expected = {
            "customer_order_skill", "customer_product_skill",
            "customer_knowledge_skill", "customer_general_skill",
            "direct_reply",
        }
        assert CustomerServiceAgent._SKILL_NODES == expected

    def test_mibao_skill_nodes(self):
        """米宝使用完整的 Skill 节点集合"""
        expected = {
            "order_skill", "product_skill", "knowledge_skill",
            "aftersales_skill", "general_agent", "direct_reply",
        }
        assert WorkAssistantAgent._SKILL_NODES == expected


# ========== Graph Builder 双类型测试 ==========

class TestGraphBuilderDualType:
    """验证 build_agent_graph 支持双类型"""

    def test_build_mibao_graph(self):
        """build_agent_graph('mibao') 成功构建图"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("mibao")
        assert graph is not None

    def test_build_xiaobu_graph(self):
        """build_agent_graph('xiaobu') 成功构建图"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("xiaobu")
        assert graph is not None

    def test_build_customer_service_graph_compat(self):
        """向后兼容：build_customer_service_graph() 成功构建图"""
        from app.graph.builder import build_customer_service_graph
        graph = build_customer_service_graph()
        assert graph is not None


# ========== Import 链测试 ==========

class TestImportChain:
    """验证 import 链正确"""

    def test_agents_module_exports(self):
        """app.agents 模块导出所有双 Agent 相关类"""
        from app.agents import (
            WorkAssistantAgent,
            CustomerServiceAgent,
            BaseAgent,
            AgentContext,
            AgentResponse,
            get_agent,
            reset_agent,
        )
        assert WorkAssistantAgent is not None
        assert CustomerServiceAgent is not None
        assert BaseAgent is not None

    def test_graph_module_exports(self):
        """app.graph 模块导出 build_agent_graph 和向后兼容的 build_customer_service_graph"""
        from app.graph import build_agent_graph, build_customer_service_graph, AgentState
        assert build_agent_graph is not None
        assert build_customer_service_graph is not None
        assert AgentState is not None
