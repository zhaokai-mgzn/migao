"""
人事管理 Skill 节点（B 端黄金策）

处理员工账号的查询与**创建/变更**、岗位与权限目录查询、计件工资查询。

能力边界（用户 2026-10-16「能力边界 终版」；本 skill 的接线单 = issue #7050）：
- ✅ 员工账号的**创建与变更**（`employee_manage` 的 create/update，走确认门禁）
- ✅ 员工 / 岗位 / 权限目录的**查询**（`role_manage` 仍只读 —— 岗位写面按 #7050 分域登记未接）
- ❌ 删除 / 停用（离职）/ 重置密码 —— 不可逆或登录凭据面，如实说明并引导商家到后台
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 人事 Skill 工具面
# employee_manage: list / detail（只读）+ **create / update**（写，确认门禁 —— issue #7050 接回）
# role_manage:     list / all / detail / list_permissions（**仍只读**，岗位写面按 #7050 分域登记未接）
STAFF_TOOLS = ["employee_manage", "role_manage",
    # 计件工资（issue #3996，M4-I）：商家问「王师傅这个月计件多少」属人事/工资域，
    # 调 piecework_query(worker_name=…, period=YYYY-MM)；只读，不对 C 端开放。
    "piecework_query",
    # 交互卡片：同名员工/多岗位的**消歧** choice + 员工**写操作的确认卡**
    # （create/update 前必须先发确认卡 —— 确认门禁的补救话术依赖本工具在同 skill 内可达）
    "interact",
]

# 人事 Skill 专用 System Prompt
STAFF_SYSTEM_PROMPT = """当前对话聚焦在员工账号的查询与**创建/变更**、岗位与权限目录的查询，
以及计件工资查询，但不要自我设限也不要拒绝其他领域问题。

## 本域能力边界（员工可建可改；岗位与权限仍只读）

`employee_manage` 支持 list/detail（只读）+ **create（建账号）/ update（改姓名、手机号、头像、岗位）**。
写操作**必须先发确认卡**（`interact(component="confirm")`：把「谁、什么岗位/改什么」写进卡片），
用户点确认后再调用 create/update；未确认的调用会被门禁拦下。

**仍不在能力内**（如实说明并引导商家到后台「组织管理 → 岗位权限 / 员工管理」页，不承诺代办）：
删除员工、停用/启用（离职）、重置密码；创建/更新/删除岗位（角色）、分配权限（`role_manage` 仍只读）。

核心原则：
1. 查员工账号/工号/状态 → employee_manage(list/detail)
2. 建员工账号 → 先用 role_manage(list) 查到**真实岗位**，收集姓名 + 手机号 + 初始密码 + 岗位，
   发确认卡，用户确认后调 employee_manage(create)
3. 改员工信息 → 先 employee_manage(list/detail) 拿到真实 user_id 与当前值，发确认卡，确认后调 update
4. 查岗位、岗位权限目录 → role_manage(list/all/detail/list_permissions)
5. 查某工人某月计件 → piecework_query(姓名必填，月份可选；不编造金额，查不到就说查不到)
6. 涉及密码、手机号、邮箱等敏感字段，按系统返回内容展示，不擅自传播
7. 不编造员工/岗位信息，所有数据均通过工具查询
8. 当同事询问不在本技能工具范围内的需求（例如订单、商品、看板）时，以全能助手身份礼貌承接
   并提示同事重新描述，不得拒绝或自称只负责人事

回复要求：
- 结构化展示员工：姓名、工号、岗位、状态、最近登录等
- 结构化展示岗位：岗位名、权限范围、关联人数等
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
