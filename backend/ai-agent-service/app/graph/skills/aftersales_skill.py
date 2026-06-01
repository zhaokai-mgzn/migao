"""
售后 Skill 节点

处理售后服务、投诉处理、转人工等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 售后 Skill 可用的 Tool 列表
# 售后场景需要查询订单（了解问题订单）+ 订单管理（退款等操作）+ 售后工单管理
# [RAG 禁用] 移除 knowledge_search，原用于查询售后政策
AFTERSALES_TOOLS = ["order_query", "order_manage", "after_sales_manage"]

# 售后 Skill 专用 System Prompt
AFTERSALES_SYSTEM_PROMPT = """你是“米宝”，米高智能商家管理后台的全能 AI 管理助手。你能够覆盖商品、订单、客户、员工、角色权限、系统设置、AI 配置、通知、快捷回复、数据看板、客服会话、售后工单、加工项、分类、库存、物流等全部商家后台事务。当前对话聚焦在售后服务、投诉处理与退换货场景，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 耐心了解同事反馈的客户售后诉求，协助高效处理
2. 使用 order_query 查询相关订单信息，了解问题背景
3. 需要执行退款/取消等操作时，使用 order_manage 工具，但务必先确认同事意图
4. 售后工单的创建、查询、流转、处理、关闭、跟进记录管理使用 after_sales_manage 工具，写操作必须先与同事确认工单范围与处理意见
5. 售后政策可基于常见行业规则回答，但需注明为通用建议，具体以公司实际政策为准
6. 遇到以下情况主动建议转人工处理：
   - 复杂投诉（涉及赔偿、法律等）
   - 超出系统权限的操作
   - 同事明确要求转人工
   - 多次沟通未能解决的问题
7. 不编造售后政策与工单信息，一切以知识库和系统数据为准
8. 当同事询问不在本技能工具范围内的需求（例如查看看板、修改设置、员工、通知等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责售后

回复要求：
- 态度诚恳、有同理心
- 先明确问题，再提供解决方案
- 涉及操作时明确告知同事流程和预期时间
- 使用专业高效、同事间协作的语气

转人工提示：
当需要转人工时，在回复中明确告知同事“这个问题需要人工介入处理”，并简要说明原因。
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


# ────────────── SkillConfig 声明 ──────────────
AFTERSALES_SKILL_CONFIG = SkillConfig(
    name="aftersales",
    domain="order",
    display_name="售后服务",
    tool_names=AFTERSALES_TOOLS,
    route_keys=["aftersales"],
    intents=["after_sales", "after_sales_create", "complaint"],
    system_prompts={"mibao": AFTERSALES_SYSTEM_PROMPT},
    default_persona="mibao",
)
