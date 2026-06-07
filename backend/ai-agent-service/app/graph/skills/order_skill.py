"""
订单 Skill 节点

处理订单查询、物流追踪、订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 订单 Skill 可用的 Tool 列表
ORDER_TOOLS = ["order_query", "order_manage", "order_create", "logistics_track", "product_search", "product_detail"]

# 订单 Skill 专用 System Prompt
ORDER_SYSTEM_PROMPT = """你是"米宝"，米高智能商家管理后台的 AI 管理助手，专注订单/物流领域。

## 工具使用

| 场景 | 工具 |
|------|------|
| 查订单/统计/跟进 | order_query |
| 创建订单 | order_create |
| 修改/取消订单 | order_manage |
| 查物流 | logistics_track |

## 原则

1. 数据标注来源：[工具返回]/[用户提供]/[推断]。不编造订单状态或物流信息
2. 简单写操作（取消订单、修改状态）先文字确认再执行
3. 复杂创建流程（新建订单）系统会自动引导，你只需配合回答
4. 工具失败时友好提示，建议稍后重试

## 回复风格

- 简洁高效，结构化展示订单信息（订单号、状态、金额、物流）
- 创建订单前列出完整信息供确认
- 专业高效，同事间协作语气
"""


async def order_node(state: AgentState) -> dict:
    """订单 Skill 节点函数

    处理订单查询、物流追踪、订单管理相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="order",
        tool_names=ORDER_TOOLS,
        system_prompt=ORDER_SYSTEM_PROMPT,
    )


# ────────────── SkillConfig 声明 ──────────────
ORDER_SKILL_CONFIG = SkillConfig(
    name="order",
    domain="order",
    display_name="订单管理",
    tool_names=ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "order_create", "logistics_track"],
    system_prompts={"mibao": ORDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
