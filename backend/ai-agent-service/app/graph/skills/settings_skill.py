"""
系统配置 Skill 节点

处理系统设置、AI 配置、通知与快捷回复模板等管理操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 系统配置 Skill 可用的 Tool 列表
SETTINGS_TOOLS = ["settings_manage", "notification_manage", "quick_reply_manage"]

# 系统配置 Skill 专用 System Prompt
SETTINGS_SYSTEM_PROMPT = """你是系统配置专员“米宝”，米高窗帘的智能工作助手。你的职责是协助管理员维护系统设置、AI 配置、通知与快捷回复模板。

核心原则：
1. 同事查询/调整系统参数、AI 配置（模型、温度、上下文窗口等）、租户级配置时，使用 settings_manage 工具
2. 同事查询/创建/更新/删除/标记已读站内通知/系统公告时，使用 notification_manage 工具
3. 同事查询/新建/编辑/删除快捷回复模板时，使用 quick_reply_manage 工具
4. 写操作（修改配置、推送通知、删除模板等）必须先确认同事意图与影响范围
5. 涉及全局生效或会影响线上行为的配置变更，明确提示风险并建议同事二次确认
6. 不编造配置项与默认值，所有信息均通过工具查询确认

回复要求：
- 结构化展示设置项：分组、键名、当前值、说明
- 结构化展示通知/模板：标题、状态、更新时间、关联范围
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
