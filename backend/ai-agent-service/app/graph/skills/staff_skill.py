"""
人事管理 Skill 节点

处理员工账号、角色与权限管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 人事 Skill 可用的 Tool 列表
# interact（#3577，2026-09-14 产品裁定「交互形态统一」）：门禁 `_requires_confirmation`
# 拦截未确认写操作时的补救话术是「请调用 interact(component=confirm) 发确认卡」，而
# references/prompts/staff.md 同样承诺「立即调 interact(component=confirm) 发确认卡片」——
# 不绑则该承诺不可执行（#3317 的 6 处之一）。写操作安全由 admin-api 层承担，
# agent 侧确认卡是交互一致性，不替代 admin-api 校验（不收紧、不移除写工具的门禁标记）。
STAFF_TOOLS = ["employee_manage", "role_manage",
    # 计件工资（issue #3996，M4-I）：商家问「王师傅这个月计件多少」属人事/工资域，
    # 调 piecework_query(worker_name=…, period=YYYY-MM)；只读，不对 C 端开放。
    "piecework_query",
    "validate_input",  # 写操作前置校验
    "interact",         # 交互卡片：写操作 confirm
]

# 人事 Skill 专用 System Prompt
STAFF_SYSTEM_PROMPT = """当前对话聚焦在员工账号、角色与权限管理，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 同事查询/创建/启用/停用/删除员工账号时，使用 employee_manage 工具
2. 同事查询/创建/分配/调整角色与权限时，使用 role_manage 工具
3. 创建账号、修改角色、删除人员等写操作必须先确认同事意图与对象，再执行
4. 高风险操作（删除员工、变更超级管理员、回收关键权限等）必须二次确认，并提示潜在影响
5. 涉及密码、手机号、邮箱等敏感字段，按系统返回内容展示，不擅自传播
6. 不编造员工/角色信息，所有数据均通过工具查询
7. 当同事询问不在本技能工具范围内的需求（例如订单、商品、看板、通知等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责人事
8. 同事问「某工人/师傅这个月计件多少 / 计件明细」时用 piecework_query 查（姓名必填，月份可选，不编造金额；查不到就说查不到）

回复要求：
- 结构化展示员工：姓名、工号、角色、状态、最近登录等
- 结构化展示角色：角色名、权限范围、关联人数等
- 列表场景使用紧凑表格化排版
- 使用专业高效、同事间协作的语气，注意遵守权限边界
- 工具调用失败时给出友好提示，建议同事核实参数或稍后重试
"""

STAFF_SKILL_CONFIG = SkillConfig(
    name="staff",
    domain="hr",
    display_name="人事管理",
    tool_names=STAFF_TOOLS,
    route_keys=["staff"],
    intents=["employee_manage", "staff_manage", "role_manage", "permission_manage"],
    system_prompts={"mibao": STAFF_SYSTEM_PROMPT},
    default_persona="mibao",
)
