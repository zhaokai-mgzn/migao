"""
订单 Skill 节点

处理订单查询、物流追踪、订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 订单 Skill 可用的 Tool 列表
ORDER_TOOLS = ["order_query", "order_manage", "logistics_track"]

# 订单 Skill 专用 System Prompt
ORDER_SYSTEM_PROMPT = """你是订单服务专员“米宝”，米高窗帘的智能工作助手。你的职责是协助同事查询订单、追踪物流、管理订单。

核心原则：
1. 查询订单时优先使用 order_query 工具
2. 用户问物流/快递/发货/到哪了等相关问题时使用 logistics_track 工具
3. 涉及订单修改/取消等操作时，先确认用户意图再执行 order_manage
4. 不确定时如实告知同事"我需要帮你核实一下"，不编造订单状态或物流信息
5. 工具调用失败时给出友好提示，建议同事稍后重试或联系技术支持

回复要求：
- 简洁高效，聚焦解决同事当前问题
- 查询结果以结构化方式展示关键信息（订单号、状态、金额、物流等）
- 使用专业高效、同事间协作的语气
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
