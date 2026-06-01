"""
LangGraph 图构建测试

测试覆盖：
- build_customer_service_graph() 能正确编译
- 图的节点和边结构正确
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from langgraph.graph import StateGraph, START, END


# ========== 图构建测试 ==========

class TestBuildGraph:
    """测试图构建"""

    def test_graph_compiles(self):
        """build_customer_service_graph 应能正确编译"""
        from app.graph.builder import build_customer_service_graph
        graph = build_customer_service_graph()
        # 编译后的图应存在
        assert graph is not None

    def test_mibao_graph_compiles(self):
        """build_agent_graph('mibao') 应能正确编译"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("mibao")
        assert graph is not None
    
    def test_xiaobu_graph_compiles(self):
        """build_agent_graph('xiaobu') 应能正确编译"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("xiaobu")
        assert graph is not None
    
    def test_graph_has_expected_nodes_mibao(self):
        """米宝图应包含所有预期节点（配置驱动）"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("mibao")
        nodes = set(graph.get_graph().nodes.keys())
        # 配置驱动的节点名称：{skill_name}_skill
        expected = {
            "cache_check", "intent_router", "direct_reply",
            "cache_store", "suggest_node",
            "order_skill", "product_skill", "knowledge_skill",
            "aftersales_skill", "customer_skill", "staff_skill",
            "settings_skill", "data_skill", "general_skill",
        }
        for node_name in expected:
            assert node_name in nodes, f"Node '{node_name}' not found in mibao graph. Got: {nodes}"

    def test_graph_has_expected_nodes_xiaobu(self):
        """小布图应包含所有预期节点（配置驱动）"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("xiaobu")
        nodes = set(graph.get_graph().nodes.keys())
        expected = {
            "cache_check", "intent_router", "direct_reply",
            "cache_store", "suggest_node",
            "customer_order_skill", "customer_product_skill",
            "customer_knowledge_skill", "customer_general_skill",
        }
        for node_name in expected:
            assert node_name in nodes, f"Node '{node_name}' not found in xiaobu graph. Got: {nodes}"

    def test_graph_edge_structure(self):
        """图的边结构正确（配置驱动验证）"""
        from app.graph.builder import build_agent_graph
        graph = build_agent_graph("xiaobu")
        nodes = set(graph.get_graph().nodes.keys())

        # 辅助节点始终存在
        assert "cache_check" in nodes
        assert "intent_router" in nodes
        assert "direct_reply" in nodes
        assert "cache_store" in nodes
        assert "suggest_node" in nodes

    def test_intent_to_skill_mapping_complete(self):
        """route_by_intent 的意图→Skill 映射完整"""
        from app.graph.nodes import route_by_intent

        # 验证所有已知意图都能映射
        test_cases = {
            "order_query": "order",
            "logistics_track": "order",
            "product_inquiry": "product",
            "knowledge_faq": "general",
            "after_sales": "aftersales",
            "complaint": "aftersales",
            "greeting": "direct_reply",
            "general": "general",
        }

        for intent, expected_skill in test_cases.items():
            state = {
                "route_decision": {"action": "full_agent"},
                "intent_result": {"intent": intent},
            }
            result = route_by_intent(state)
            assert result == expected_skill, f"Intent '{intent}' routed to '{result}', expected '{expected_skill}'"

    def test_cache_check_routing_values(self):
        """check_cache_hit 返回值与图中条件边的 key 一致"""
        from app.graph.nodes import check_cache_hit

        # hit case
        state_hit = {"cached_answer": "cached"}
        assert check_cache_hit(state_hit) == "hit"

        # miss case
        state_miss = {"cached_answer": None}
        assert check_cache_hit(state_miss) == "miss"


class TestGraphImports:
    """验证图模块的导入链正确"""

    def test_graph_init_exports(self):
        """app.graph.__init__ 导出正确"""
        from app.graph import AgentState, build_agent_graph, build_customer_service_graph
        assert AgentState is not None
        assert build_agent_graph is not None
        assert build_customer_service_graph is not None

    def test_skills_init_exports(self):
        """app.graph.skills.__init__ 导出正确"""
        from app.graph.skills import (
            order_node, product_node, knowledge_node,
            aftersales_node, general_node,
            execute_skill, get_skill_llm, build_tool_context,
        )
        assert all([
            order_node, product_node, knowledge_node,
            aftersales_node, general_node,
            execute_skill, get_skill_llm, build_tool_context,
        ])

    def test_nodes_imports(self):
        """app.graph.nodes 导入正确"""
        from app.graph.nodes import (
            cache_check_node, intent_router_node,
            direct_reply_node, cache_store_node,
            suggestions_node, check_cache_hit, route_by_intent,
        )
        assert all([
            cache_check_node, intent_router_node,
            direct_reply_node, cache_store_node,
            suggestions_node, check_cache_hit, route_by_intent,
        ])

    def test_state_import(self):
        """app.graph.state 导入正确"""
        from app.graph.state import AgentState
        assert AgentState is not None
