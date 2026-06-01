"""
订单 Skill 节点

处理订单查询、物流追踪、订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 订单 Skill 可用的 Tool 列表
ORDER_TOOLS = ["order_query", "order_manage", "logistics_track"]

# 订单 Skill 专用 System Prompt
ORDER_SYSTEM_PROMPT = """你是“米宝”，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在订单查询、物流追踪与订单管理，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 查询订单优先使用 order_query 工具；询问订单统计/跟进状态统计时，使用 order_query 的 statistics / follow_status_stats action
2. 用户问物流/快递/发货/到哪了等相关问题时使用 logistics_track 工具
3. 涉及订单修改/取消等操作时，先确认用户意图再执行 order_manage
4. 不确定时如实告知同事“我需要帮你核实一下”，不编造订单状态或物流信息
5. 工具调用失败时给出友好提示，建议同事稍后重试或联系技术支持
6. 当同事询问不在本技能工具范围内的需求（例如商品、通知、员工、看板等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责订单

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


# ────────────── SkillConfig 声明 ──────────────
ORDER_SKILL_CONFIG = SkillConfig(
    name="order",
    domain="order",
    display_name="订单管理",
    tool_names=ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "logistics_track"],
    system_prompts={"mibao": ORDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
