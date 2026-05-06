"""
LangGraph StateGraph 构建器

将所有节点（缓存检查、意图路由、Skill 节点、缓存写入、建议生成）
和条件边组装成完整的 Agent 图。

支持两种 Agent 类型：
- mibao（米宝，工作助手）：order_skill, product_skill, knowledge_skill, aftersales_skill, general_agent
- xiaobu（小布，C端客服）：customer_order_skill, customer_product_skill, customer_knowledge_skill, customer_general_skill

图结构：
  START → cache_check →(hit)→ suggestions → END
                       →(miss)→ intent_router →(条件边)→ Skill 节点 → cache_store → suggestions → END
"""

from langgraph.graph import StateGraph, START, END

from app.graph.state import AgentState


def build_agent_graph(agent_type: str = "xiaobu"):
    """构建并编译 Agent StateGraph

    Args:
        agent_type: Agent 类型，"mibao" 或 "xiaobu"

    Returns:
        CompiledGraph: 编译后的 LangGraph 图，可直接 ainvoke / astream
    """
    graph = StateGraph(AgentState)

    # 导入辅助节点和路由函数
    from app.graph.nodes import (
        cache_check_node,
        intent_router_node,
        direct_reply_node,
        cache_store_node,
        suggestions_node,
        check_cache_hit,
        route_by_intent,
    )

    # ── 注册共用辅助节点 ──
    graph.add_node("cache_check", cache_check_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("direct_reply", direct_reply_node)
    graph.add_node("cache_store", cache_store_node)
    graph.add_node("suggestions", suggestions_node)

    # ── 根据 agent_type 注册不同的 Skill 节点和路由映射 ──
    if agent_type == "mibao":
        from app.graph.skills import (
            order_node,
            product_node,
            knowledge_node,
            aftersales_node,
            general_node,
        )

        graph.add_node("order_skill", order_node)
        graph.add_node("product_skill", product_node)
        graph.add_node("knowledge_skill", knowledge_node)
        graph.add_node("aftersales_skill", aftersales_node)
        graph.add_node("general_agent", general_node)

        skill_route_map = {
            "direct_reply": "direct_reply",
            "order": "order_skill",
            "product": "product_skill",
            "knowledge": "knowledge_skill",
            "aftersales": "aftersales_skill",
            "general": "general_agent",
        }
        skill_node_names = [
            "direct_reply",
            "order_skill",
            "product_skill",
            "knowledge_skill",
            "aftersales_skill",
            "general_agent",
        ]
    else:
        # xiaobu（默认）
        from app.graph.skills import (
            customer_order_skill_node,
            customer_product_skill_node,
            customer_knowledge_skill_node,
            customer_general_skill_node,
        )

        graph.add_node("customer_order_skill", customer_order_skill_node)
        graph.add_node("customer_product_skill", customer_product_skill_node)
        graph.add_node("customer_knowledge_skill", customer_knowledge_skill_node)
        graph.add_node("customer_general_skill", customer_general_skill_node)

        skill_route_map = {
            "direct_reply": "direct_reply",
            "order": "customer_order_skill",
            "product": "customer_product_skill",
            "knowledge": "customer_knowledge_skill",
            "aftersales": "customer_general_skill",
            "general": "customer_general_skill",
        }
        skill_node_names = [
            "direct_reply",
            "customer_order_skill",
            "customer_product_skill",
            "customer_knowledge_skill",
            "customer_general_skill",
        ]

    # ── 定义边 ──

    # 入口 → 语义缓存检查
    graph.add_edge(START, "cache_check")

    # 缓存检查后的条件路由
    graph.add_conditional_edges(
        "cache_check",
        check_cache_hit,
        {
            "hit": "suggestions",   # 缓存命中，直接生成建议后结束
            "miss": "intent_router",  # 未命中，进入意图路由
        },
    )

    # 意图路由后的条件边 → 对应 Skill 节点
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        skill_route_map,
    )

    # 所有 Skill 节点 → 缓存写入
    for skill_node_name in skill_node_names:
        graph.add_edge(skill_node_name, "cache_store")

    # 缓存写入 → 建议生成 → 结束
    graph.add_edge("cache_store", "suggestions")
    graph.add_edge("suggestions", END)

    return graph.compile()


def build_customer_service_graph():
    """向后兼容的别名，构建小布（C端客服）Agent 图

    Returns:
        CompiledGraph: 编译后的 LangGraph 图
    """
    return build_agent_graph("xiaobu")
