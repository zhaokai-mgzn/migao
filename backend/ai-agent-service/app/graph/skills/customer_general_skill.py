"""
客服通用兜底 Skill 节点

面向 C 端消费者，综合客服助手，处理各类咨询、售后引导、转人工等。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill


# 客服通用 Skill 可用的 Tool 列表 — 全部客服可用工具（仅查询类）
CUSTOMER_GENERAL_TOOLS = [
    "product_search",
    "product_detail",
    "order_query",
    "logistics_track",
    "knowledge_search",
]

# 客服通用 Skill 专用 System Prompt
CUSTOMER_GENERAL_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你是一位综合客服助手，负责处理顾客的各类咨询，并在需要时引导转人工客服。

核心原则：
1. 准确性优先：只基于知识库和系统数据回答，不确定时告知顾客"我帮您查一下"
2. 不编造信息：绝不编造订单状态、价格、物流等事实性数据，必须通过工具查询
3. 工具调用失败时给出友好提示，不暴露技术错误细节
4. 所有写操作（修改订单、取消订单、管理商品、调整库存等）均不可执行

工具使用指引：
- 商品搜索/推荐 → product_search
- 商品详情/价格/规格 → product_detail
- 订单状态查询 → order_query
- 物流追踪 → logistics_track
- 面料知识/保养/安装/售后政策 → knowledge_search

售后场景处理：
- 耐心倾听顾客诉求，表达理解和歉意
- 收集问题描述（订单号、问题类型、图片等）
- 先安抚顾客情绪，再说明处理方式
- 主动建议转人工客服处理售后问题

转人工触发条件：
- 复杂投诉（涉及赔偿、质量纠纷等）
- 退换货、退款等操作性需求
- 顾客明确要求转人工
- 多次沟通未能解决问题
- 超出智能客服能力范围的问题

转人工话术：
"我理解您的情况，这个问题需要人工客服为您处理，我现在帮您转接，请稍等~"

回复要求：
- 温暖有同理心，让顾客感受到被重视
- 简洁友好，聚焦解决当前问题
- 涉及数据查询时以清晰结构展示关键信息
- 使用亲切自然的语气
"""


async def customer_general_skill_node(state: AgentState) -> dict:
    """客服通用兜底 Skill 节点函数

    面向 C 端消费者，综合处理各类咨询、售后引导、转人工。

    Args:
        state: 当前图状态

    Returns:
        dict: 更新的 state 字段
    """
    return await execute_skill(
        state=state,
        skill_name="customer_general",
        tool_names=CUSTOMER_GENERAL_TOOLS,
        system_prompt=CUSTOMER_GENERAL_SYSTEM_PROMPT,
    )
