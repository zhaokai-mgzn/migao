"""
Skill 节点模块

导出所有 Skill 节点函数，供 LangGraph StateGraph 使用。

米宝（工作助手）Skill 节点：
- order_node: 订单服务（查询/物流/管理）
- product_node: 商品咨询（搜索/详情/库存）
- knowledge_node: 知识库检索（面料/保养/安装/政策）
- aftersales_node: 售后服务（投诉/退换/转人工）
- general_node: 通用兗底（全部 Tool）

小布（C端客服）Skill 节点：
- customer_order_skill_node: 订单查询/物流追踪
- customer_product_skill_node: 商品咨询/推荐
- customer_knowledge_skill_node: 知识库FAQ
- customer_general_skill_node: 通用客服兗底
"""

# 米宝（工作助手）Skill 节点
from app.graph.skills.order_skill import order_node
from app.graph.skills.product_skill import product_node
from app.graph.skills.knowledge_skill import knowledge_node
from app.graph.skills.aftersales_skill import aftersales_node
from app.graph.skills.customer_skill import customer_skill_node
from app.graph.skills.staff_skill import staff_skill_node
from app.graph.skills.settings_skill import settings_skill_node
from app.graph.skills.data_skill import data_skill_node
from app.graph.skills.general_agent import general_node

# 小布（C端客服）Skill 节点
from app.graph.skills.customer_order_skill import customer_order_skill_node
from app.graph.skills.customer_product_skill import customer_product_skill_node
from app.graph.skills.customer_knowledge_skill import customer_knowledge_skill_node
from app.graph.skills.customer_general_skill import customer_general_skill_node

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
    # 米宝 Skill
    "order_node",
    "product_node",
    "knowledge_node",
    "aftersales_node",
    "customer_skill_node",
    "staff_skill_node",
    "settings_skill_node",
    "data_skill_node",
    "general_node",
    # 小布 Skill
    "customer_order_skill_node",
    "customer_product_skill_node",
    "customer_knowledge_skill_node",
    "customer_general_skill_node",
    # 配置与注册
    "SkillConfig",
    "create_skill_config",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    # 公共工具
    "execute_skill",
    "get_skill_llm",
    "build_tool_context",
]
