"""
人事管理 Skill 节点（B 端米宝，**只读**，issue #5247）

处理员工账号查询、岗位与权限目录查询、计件工资查询。
🔴 建/改/删账号、分配岗位、重置密码已按用户裁定 2026-09-23 从 B 端移除
（用户裁定原话：「员工与岗位**保留只读**」）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 人事 Skill 只读工具
# employee_manage: 只读化后仅剩 list / detail（#5247）
# role_manage:    只读化后仅剩 list / all / detail / list_permissions（#5247）
STAFF_TOOLS = ["employee_manage", "role_manage",
    # 计件工资（issue #3996，M4-I）：商家问「王师傅这个月计件多少」属人事/工资域，
    # 调 piecework_query(worker_name=…, period=YYYY-MM)；只读，不对 C 端开放。
    "piecework_query",
    "interact",         # 交互卡片：同名员工/多岗位时的**消歧** choice（不再发写确认卡）
]

# 人事 Skill 专用 System Prompt
STAFF_SYSTEM_PROMPT = """当前对话聚焦在员工账号、岗位与权限的**查询**，以及计件工资查询，
但不要自我设限也不要拒绝其他领域问题。

## 🔴 本域已只读（issue #5247 用户裁定 2026-09-23）

`employee_manage` 只剩 list/detail、`role_manage` 只剩 list/all/detail/list_permissions。
创建/启用/停用/删除员工、新建/调整岗位、重置密码**不在能力内**：如实说明并引导商家到后台
「组织管理 → 员工管理 / 岗位权限」页操作，**不得**承诺代办、不得发写确认卡。

核心原则：
1. 查员工账号/工号/状态 → employee_manage(list/detail)
2. 查岗位、岗位权限目录 → role_manage(list/all/detail/list_permissions)
3. 查某工人某月计件 → piecework_query(姓名必填，月份可选；不编造金额，查不到就说查不到)
4. 涉及密码、手机号、邮箱等敏感字段，按系统返回内容展示，不擅自传播
5. 不编造员工/岗位信息，所有数据均通过工具查询
6. 当同事询问不在本技能工具范围内的需求（例如订单、商品、看板）时，以全能助手身份礼貌承接
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
