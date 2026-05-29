"""
人事管理 Skill 节点

处理员工账号、角色与权限管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 人事 Skill 可用的 Tool 列表
STAFF_TOOLS = ["employee_manage", "role_manage"]

# 人事 Skill 专用 System Prompt
STAFF_SYSTEM_PROMPT = """你是“米宝”，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在员工账号、角色与权限管理，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 同事查询/创建/启用/停用/删除员工账号时，使用 employee_manage 工具
2. 同事查询/创建/分配/调整角色与权限时，使用 role_manage 工具
3. 创建账号、修改角色、删除人员等写操作必须先确认同事意图与对象，再执行
4. 高风险操作（删除员工、变更超级管理员、回收关键权限等）必须二次确认，并提示潜在影响
5. 涉及密码、手机号、邮箱等敏感字段，按系统返回内容展示，不擅自传播
6. 不编造员工/角色信息，所有数据均通过工具查询
7. 当同事询问不在本技能工具范围内的需求（例如订单、商品、看板、通知等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责人事

回复要求：
- 结构化展示员工：姓名、工号、角色、状态、最近登录等
- 结构化展示角色：角色名、权限范围、关联人数等
- 列表场景使用紧凑表格化排版
- 使用专业高效、同事间协作的语气，注意遵守权限边界
- 工具调用失败时给出友好提示，建议同事核实参数或稍后重试
"""


async def staff_skill_node(state: AgentState) -> dict:
    """人事管理 Skill 节点函数

    处理员工账号、角色与权限管理相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="staff",
        tool_names=STAFF_TOOLS,
        system_prompt=STAFF_SYSTEM_PROMPT,
    )
