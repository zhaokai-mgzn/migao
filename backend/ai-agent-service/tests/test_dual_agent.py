"""
双 Agent 架构测试（Skill-centric 配置驱动版）

覆盖：
- Agent 配置注册（mibao / xiaobu）
- Agent 类型验证
- Greeting 差异化验证（从 AgentConfig 获取）
- get_agent 工厂函数
- Graph Builder 双类型构建
- 向后兼容性
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.agents.customer_service_agent import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    get_agent,
    reset_agent,
)
from app.agents.agent_config import get_agent_config, reset_agent_configs
from app.graph.skills.skill_registry import reset_skill_registry


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


# ========== Agent 配置验证 ==========

class TestAgentConfigs:
    """验证 AgentConfig 注册正确"""

    def test_mibao_config_exists(self):
        """mibao AgentConfig 已注册"""
        config = get_agent_config("mibao")
        assert config.name == "mibao"
        assert config.display_name == "米宝"
        assert config.persona == "mibao"

    def test_xiaobu_config_exists(self):
        """xiaobu AgentConfig 已注册"""
        config = get_agent_config("xiaobu")
        assert config.name == "xiaobu"
        assert config.display_name == "小布"
        assert config.persona == "xiaobu"

    def test_mibao_skills(self):
        """米宝使用完整 Skill 集合"""
        config = get_agent_config("mibao")
        assert "order" in config.skill_names
        assert "product" in config.skill_names
        assert "aftersales" in config.skill_names
        assert config.fallback_skill == "general"

    def test_xiaobu_skills(self):
        """小布使用 customer_* 前缀的 Skill"""
        config = get_agent_config("xiaobu")
        assert "customer_order" in config.skill_names
        assert "customer_product" in config.skill_names
        assert config.fallback_skill == "customer_general"

    def test_mibao_roles(self):
        """米宝允许内部角色"""
        config = get_agent_config("mibao")
        assert config.allows_role("admin")
        assert config.allows_role("agent")
        assert not config.allows_role("customer")

    def test_xiaobu_roles(self):
        """小布允许 C 端角色"""
        config = get_agent_config("xiaobu")
        assert config.allows_role("customer")
        assert not config.allows_role("admin")


# ========== get_agent 工厂函数测试 ==========

class TestGetAgentFactory:
    """验证 get_agent 工厂函数"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_mibao(self, mock_create_registry, mock_build_graph):
        """get_agent(agent_type='mibao') 返回 BaseAgent"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="mibao")
        assert isinstance(agent, BaseAgent)
        assert agent._agent_type == "mibao"
        mock_build_graph.assert_called_once_with("mibao")

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_xiaobu(self, mock_create_registry, mock_build_graph):
        """get_agent(agent_type='xiaobu') 返回 BaseAgent"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="xiaobu")
        assert isinstance(agent, BaseAgent)
        assert agent._agent_type == "xiaobu"
        mock_build_graph.assert_called_once_with("xiaobu")

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_default_is_xiaobu(self, mock_create_registry, mock_build_graph):
        """默认 get_agent() 返回小布 Agent（向后兼容）"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent()
        assert agent._agent_type == "xiaobu"

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    def test_get_agent_with_registry(self, mock_create_registry, mock_build_graph):
        """get_agent 传入 tool_registry 后使用该 registry"""
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
        assert mibao._agent_type == "mibao"
        assert xiaobu._agent_type == "xiaobu"


# ========== Greeting 差异化测试 ==========

class TestGreetings:
    """验证双 Agent 欢迎语差异（从 AgentConfig 获取）"""

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    async def test_mibao_greeting(self, mock_create_registry, mock_build_graph, agent_context):
        """米宝的 greeting 包含'米宝'和'工作助手'"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="mibao")
        greeting = await agent.get_greeting(agent_context)
        assert "米宝" in greeting
        assert "工作助手" in greeting

    @patch("app.graph.builder.build_agent_graph")
    @patch("app.agents.customer_service_agent.create_default_registry")
    async def test_xiaobu_greeting(self, mock_create_registry, mock_build_graph, agent_context):
        """小布的 greeting 包含'小布'和'客服'"""
        mock_create_registry.return_value = MagicMock()
        mock_build_graph.return_value = MagicMock()

        agent = get_agent(agent_type="xiaobu")
        greeting = await agent.get_greeting(agent_context)
        assert "小布" in greeting
        assert "客服" in greeting


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
        """app.agents 模块导出所有 Agent 相关类"""
        from app.agents import (
            BaseAgent,
            AgentContext,
            AgentResponse,
            get_agent,
            reset_agent,
            AgentConfig,
            get_agent_config,
            AgentRouter,
        )
        assert BaseAgent is not None
        assert AgentConfig is not None
        assert AgentRouter is not None

    def test_graph_module_exports(self):
        """app.graph 模块导出 build_agent_graph 和向后兼容的 build_customer_service_graph"""
        from app.graph import build_agent_graph, build_customer_service_graph, AgentState
        assert build_agent_graph is not None
        assert build_customer_service_graph is not None
        assert AgentState is not None
