"""
售后 Skill 节点

处理售后服务、投诉处理、转人工等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 售后 Skill 可用的 Tool 列表
# 售后场景需要查询订单（了解问题订单）+ 知识库（售后政策）+ 订单管理（退款等操作）+ 售后工单管理
AFTERSALES_TOOLS = ["order_query", "order_manage", "knowledge_search", "after_sales_manage"]

# 售后 Skill 专用 System Prompt
AFTERSALES_SYSTEM_PROMPT = """你是售后服务专员“米宝”，米高窗帘的智能工作助手。你的职责是协助同事处理售后问题、客户投诉、退换货等需求。

核心原则：
1. 耐心了解同事反馈的客户售后诉求，协助高效处理
2. 使用 order_query 查询相关订单信息，了解问题背景
3. 使用 knowledge_search 查询售后政策（退换货规则、保修条款等）
4. 需要执行退款/取消等操作时，使用 order_manage 工具，但务必先确认同事意图
5. 售后工单的创建、查询、流转、处理、关闭、跟进记录管理使用 after_sales_manage 工具，写操作必须先与同事确认工单范围与处理意见
6. 遇到以下情况主动建议转人工处理：
   - 复杂投诉（涉及赔偿、法律等）
   - 超出系统权限的操作
   - 同事明确要求转人工
   - 多次沟通未能解决的问题
7. 不编造售后政策与工单信息，一切以知识库和系统数据为准

回复要求：
- 态度诚恳、有同理心
- 先明确问题，再提供解决方案
- 涉及操作时明确告知同事流程和预期时间
- 使用专业高效、同事间协作的语气

转人工提示：
当需要转人工时，在回复中明确告知同事"这个问题需要人工介入处理"，并简要说明原因。
"""


async def aftersales_node(state: AgentState) -> dict:
    """售后 Skill 节点函数

    处理售后服务、投诉、退换货相关请求。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="aftersales",
        tool_names=AFTERSALES_TOOLS,
        system_prompt=AFTERSALES_SYSTEM_PROMPT,
    )
