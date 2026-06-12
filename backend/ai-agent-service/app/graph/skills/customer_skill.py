"""
客户关系管理 Skill 节点

处理客户档案查询、客户标签管理、客户跟进等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 客户 Skill 可用的 Tool 列表
# customer_manage: 客户CRUD + 标签 + 跟进记录
# order_query: 查该客户的历史订单
# product_search: 查推荐商品
CUSTOMER_TOOLS = ["customer_manage", "order_query", "product_search"]

# 客户 Skill 专用 System Prompt
CUSTOMER_SYSTEM_PROMPT = """你是“米宝”，词元通达商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在客户档案查询与维护、客户标签与跟进记录管理，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 同事询问“某客户信息/档案/电话/历史订单”等时，使用 customer_manage 工具的查询能力
2. 涉及更新客户资料、添加备注、打/移除标签等写操作时，先与同事确认意图再执行
3. 涉及合并客户、删除档案等高风险操作时，必须二次确认并提示影响范围
4. 不编造客户信息（手机号、地址、消费金额等），均通过工具查询
5. 工具调用失败时给出友好提示，建议同事稍后重试或核实参数
6. 当同事询问不在本技能工具范围内的需求（例如订单、商品、通知、报表等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责客户

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


# ────────────── SkillConfig 声明 ──────────────
CUSTOMER_SKILL_CONFIG = SkillConfig(
    name="customer",
    domain="crm",
    display_name="客户关系管理",
    tool_names=CUSTOMER_TOOLS,
    route_keys=["customer"],
    intents=["customer_manage", "customer_query"],
    system_prompts={"mibao": CUSTOMER_SYSTEM_PROMPT},
    default_persona="mibao",
)
