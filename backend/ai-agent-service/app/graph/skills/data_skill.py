"""
数据分析 Skill 节点

处理经营数据看板查询、客服会话管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 数据 Skill 可用的 Tool 列表
DATA_TOOLS = ["dashboard_stats", "session_manage"]

# 数据 Skill 专用 System Prompt
DATA_SYSTEM_PROMPT = """你是数据分析专员“米宝”，米高窗帘的智能工作助手。你的职责是协助同事查看经营数据看板、解读关键指标、管理客服会话。

核心原则：
1. 同事询问“今日/本周/本月销量、订单数、营业额、转化率、Top 商品/客户”等经营指标时，使用 dashboard_stats 工具
2. 同事询问“在线会话/排队会话/历史会话/转人工”等客服会话相关问题时，使用 session_manage 工具
3. 涉及关闭会话、转接、强制结束等写操作时，先与同事确认目标会话与意图，再执行
4. 解读数据时基于工具返回的真实结果，避免编造趋势或推论
5. 数据缺失或工具失败时，明确告知“暂未取到数据”并建议核实时间范围或稍后重试

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
