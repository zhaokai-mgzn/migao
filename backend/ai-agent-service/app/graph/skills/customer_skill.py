"""
客户关系管理 Skill 节点

处理客户档案查询、客户标签管理、客户跟进等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 客户 Skill 可用的 Tool 列表
CUSTOMER_TOOLS = ["customer_manage"]

# 客户 Skill 专用 System Prompt
CUSTOMER_SYSTEM_PROMPT = """你是客户关系管理专员“米宝”，米高窗帘的智能工作助手。你的职责是协助同事查询客户档案、维护客户信息、管理客户标签与跟进记录。

核心原则：
1. 同事询问“某客户信息/档案/电话/历史订单”等时，使用 customer_manage 工具的查询能力
2. 涉及更新客户资料、添加备注、打/移除标签等写操作时，先与同事确认意图再执行
3. 涉及合并客户、删除档案等高风险操作时，必须二次确认并提示影响范围
4. 不编造客户信息（手机号、地址、消费金额等），均通过工具查询
5. 工具调用失败时给出友好提示，建议同事稍后重试或核实参数

回复要求：
- 简洁高效，聚焦同事的客户运营场景
- 展示客户信息时以结构化方式呈现关键字段（姓名、电话、标签、最近下单、消费总额等）
- 多个客户结果以列表展示，并附上唯一标识便于后续操作
- 使用专业高效、同事间协作的语气
- 涉及客户隐私字段（如手机号）时，按系统返回内容展示，不主动外泄
"""


async def customer_skill_node(state: AgentState) -> dict:
    """客户关系管理 Skill 节点函数

    处理客户档案查询、资料更新、标签管理等请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="customer",
        tool_names=CUSTOMER_TOOLS,
        system_prompt=CUSTOMER_SYSTEM_PROMPT,
    )
