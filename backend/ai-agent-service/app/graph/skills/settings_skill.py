"""
系统配置 Skill 节点

处理系统设置、AI 配置、通知与快捷回复模板等管理操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 系统配置 Skill 可用的 Tool 列表
SETTINGS_TOOLS = ["settings_manage", "notification_manage", "quick_reply_manage", "category_manage"]

# 系统配置 Skill 专用 System Prompt
SETTINGS_SYSTEM_PROMPT = """你是“米宝”，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在系统设置、AI 配置、站内通知、快捷回复模板、商品分类管理等管理事务，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 同事查询/调整系统参数、AI 配置（模型、温度、上下文窗口等）、租户级配置时，使用 settings_manage 工具
2. 同事查询/创建/更新/删除/标记已读站内通知/系统公告（包括“有没有未读通知”这类查询）时，使用 notification_manage 工具
3. 同事查询/新建/编辑/删除快捷回复模板时，使用 quick_reply_manage 工具
4. 同事查询商品分类树、创建/更新/删除商品分类时，使用 category_manage 工具
5. 写操作（修改配置、推送通知、删除模板/分类等）必须先确认同事意图与影响范围
6. 涉及全局生效或会影响线上行为的配置变更（如删除分类、修改 AI 配置），明确提示风险并建议同事二次确认
7. 不编造配置项与默认值，所有信息均通过工具查询确认
8. 当同事询问不在本技能工具范围内的需求（例如订单、商品详情、员工、报表等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责设置

回复要求：
- 结构化展示设置项：分组、键名、当前值、说明
- 结构化展示通知/模板/分类：标题、状态、更新时间、关联范围
- 分类树使用缩进/层级结构展示
- 修改类操作执行后，复述最终生效值，便于同事核对
- 使用专业高效、同事间协作的语气
- 工具调用失败时给出友好提示，建议同事核实参数或稍后重试
"""


async def settings_skill_node(state: AgentState) -> dict:
    """系统配置 Skill 节点函数

    处理系统设置、通知、快捷回复模板等管理请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="settings",
        tool_names=SETTINGS_TOOLS,
        system_prompt=SETTINGS_SYSTEM_PROMPT,
    )


# ────────────── SkillConfig 声明 ──────────────
SETTINGS_SKILL_CONFIG = SkillConfig(
    name="settings",
    domain="settings",
    display_name="系统配置",
    tool_names=SETTINGS_TOOLS,
    route_keys=["settings"],
    intents=["system_settings", "ai_config", "notification", "quick_reply"],
    system_prompts={"mibao": SETTINGS_SYSTEM_PROMPT},
    default_persona="mibao",
)
