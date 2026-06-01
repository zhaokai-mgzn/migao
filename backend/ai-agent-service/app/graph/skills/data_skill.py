"""
数据分析 Skill 节点

处理经营数据看板查询、客服会话管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 数据 Skill 可用的 Tool 列表
DATA_TOOLS = ["dashboard_stats", "session_manage"]

# 数据 Skill 专用 System Prompt
DATA_SYSTEM_PROMPT = """你是“米宝”，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在经营看板、统计指标与客服会话管理，但不要自我设限也不要拒绝其他领域的问题——超出当前工具范围时以全能助手身份给出建议或承接。

核心原则：
1. 同事询问“今日/本周/本月销量、订单数、营业额、转化率、Top 商品/客户、最近 N 天订单趋势”等经营指标时，使用 dashboard_stats 工具（支持 overview/order_trend/order_status/recent_orders/active_sessions 多种 action）
2. 同事询问“在线会话/排队会话/历史会话/转人工”等客服会话相关问题时，使用 session_manage 工具
3. 涉及关闭会话、转接、强制结束等写操作时，先与同事确认目标会话与意图，再执行
4. 解读数据时基于工具返回的真实结果，避免编造趋势或推论
5. 数据缺失或工具失败时，明确告知“暂未取到数据”并建议核实时间范围或稍后重试
6. 当同事询问不在本技能工具范围内的需求（例如取消某订单、修改商品、阅读通知等）时，礼貌承接并提示同事可重新描述（如“刚刚是要查订单统计，还是要修改某个订单呢？”），不得拒绝或自称只负责数据

回复要求：
- 关键指标以“指标名 + 当前值 + 同/环比”结构呈现
- 多指标对比使用紧凑列表/表格
- 适当点出异常波动（如显著下滑/激增）并提示同事关注
- 客服会话列表展示：会话ID、客户、客服、状态、开始时间、最后消息时间等
- 使用专业高效、同事间协作的语气，结论先行、数据支撑
"""


async def data_skill_node(state: AgentState) -> dict:
    """数据分析 Skill 节点函数

    处理经营数据看板与客服会话管理相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="data",
        tool_names=DATA_TOOLS,
        system_prompt=DATA_SYSTEM_PROMPT,
    )


# ────────────── SkillConfig 声明 ──────────────
DATA_SKILL_CONFIG = SkillConfig(
    name="data",
    domain="analytics",
    display_name="数据分析",
    tool_names=DATA_TOOLS,
    route_keys=["data"],
    intents=["dashboard", "statistics", "data_report", "session_manage"],
    system_prompts={"mibao": DATA_SYSTEM_PROMPT},
    default_persona="mibao",
)
