"""
LangGraph StateGraph 构建器（配置驱动版）

从 AgentConfig + SkillRegistry 动态构建 Agent 图，
不再使用 if/else 硬编码 Agent 类型。

图结构（所有 Agent 类型共用）：
  START → intent_router →(条件边)→ Skill 节点 → suggest_node → END

新增 Agent 类型只需：
1. 在 app/agents/agents/ 中添加 AgentConfig 声明
2. 在 app/graph/skills/ 中添加需要的 SkillConfig
3. 注册后即可使用，无需修改本文件
"""

from langgraph.graph import StateGraph, START, END
from loguru import logger

from app.graph.state import AgentState


def build_agent_graph(agent_type: str = "xiaobu"):
    """构建并编译 Agent StateGraph（配置驱动）

    从 AgentConfig 获取 Skill 列表，从 SkillRegistry 获取 Skill 配置
    并自动生成节点函数和路由映射。

    Args:
        agent_type: Agent 类型，如 "mibao", "xiaobu"

    Returns:
        CompiledGraph: 编译后的 LangGraph 图，可直接 ainvoke / astream
    """
    from app.graph.nodes import (
        intent_router_node,
        direct_reply_node,
        route_by_intent,
    )

    # 获取 Agent 配置
    from app.agents.agent_config import get_agent_config
    agent_config = get_agent_config(agent_type)

    # 获取 Skill 注册表
    from app.graph.skills.skill_registry import get_skill_registry
    skill_registry = get_skill_registry()

    logger.info(
        f"[builder] Building graph for agent '{agent_type}' ({agent_config.display_name}) | "
        f"skills={agent_config.skill_names} fallback={agent_config.fallback_skill}"
    )

    graph = StateGraph(AgentState)

    # ── 1. 注册共用辅助节点 ──
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("direct_reply", direct_reply_node)

    # ── 2. 从配置动态注册 Skill 节点 ──
    # 收集所有 Skill 名称（业务 Skill + 兜底 Skill）
    all_skill_names = agent_config.get_all_skill_names()
    skill_node_names = ["direct_reply"]

    # 构建路由映射：route_key → node_id
    skill_route_map = {"direct_reply": "direct_reply"}

    for skill_name in all_skill_names:
        skill_config = skill_registry.get(skill_name)
        if not skill_config:
            logger.warning(
                f"[builder] Skill '{skill_name}' not found in registry, skipping"
            )
            continue

        # 自动生成节点函数（根据 Agent 的 persona 选择对应的 Prompt）
        node_func = skill_registry.create_node_function(
            skill_config, agent_config.persona
        )
        node_id = f"{skill_name}_skill"

        graph.add_node(node_id, node_func)
        skill_node_names.append(node_id)

        # 将 Skill 的 route_keys 映射到 node_id
        for route_key in skill_config.route_keys:
            skill_route_map[route_key] = node_id

    logger.info(
        f"[builder] Registered {len(skill_node_names)} skill nodes | "
        f"route_map keys={list(skill_route_map.keys())}"
    )

    # ── 3. 定义边 ──

    # 入口 → 意图路由
    graph.add_edge(START, "intent_router")

    # 意图路由后的条件边 → 对应 Skill 节点
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        skill_route_map,
    )

    # 所有 Skill 节点 → 结束（后续建议由 LLM 在回复中自然生成）
    for skill_node_name in skill_node_names:
        graph.add_edge(skill_node_name, END)

    return graph.compile()


def build_customer_service_graph():
    """向后兼容的别名，构建小布（C端客服）Agent 图

    Returns:
        CompiledGraph: 编译后的 LangGraph 图
    """
    return build_agent_graph("xiaobu")
