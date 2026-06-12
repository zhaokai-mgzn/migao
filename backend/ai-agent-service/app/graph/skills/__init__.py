"""
Skill 节点模块

导出所有 Skill 配置与注册表，供 LangGraph StateGraph 使用。
节点函数由 skill_registry.create_node_function() 动态生成。

米宝（工作助手）Skill：order, product, knowledge, aftersales, customer, staff, settings, data, general
小布（C端客服）Skill：customer_order, customer_product, customer_knowledge, customer_general
"""

# 配置与注册
from app.graph.skills.skill_config import SkillConfig, create_skill_config
from app.graph.skills.skill_registry import (
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)

# 公共工具
from app.graph.skills.base_skill import execute_skill, get_skill_llm, build_tool_context

__all__ = [
    "SkillConfig",
    "create_skill_config",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    "execute_skill",
    "get_skill_llm",
    "build_tool_context",
]
