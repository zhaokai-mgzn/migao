"""
售后 Skill 节点

处理售后服务,投诉处理,转人工等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig


# 售后 Skill 可用的 Tool 列表
# 售后场景需要查询订单(了解问题订单)+ 订单管理(退款等操作)+ 售后工单管理
# [RAG 禁用] 移除 knowledge_search,原用于查询售后政策
AFTERSALES_TOOLS = ["order_query", "order_manage", "after_sales_manage",
    "validate_input",  # 写操作前置校验
]

# 售后 Skill 专用 System Prompt
AFTERSALES_SYSTEM_PROMPT = """你是"米宝",专注售后服务,投诉处理与退换货场景。

## 工具

| 场景 | 工具 |
|------|------|
| 查订单详情 | order_query |
| 退款/取消订单 | order_manage |
| 售后工单(列表/详情/创建/更新) | after_sales_manage |

## 创建售后工单流程

1. 先查订单:调 order_query 确认订单状态
2. 收集必填:ticket_type(退款/换货/维修/投诉/其他),description(问题描述)
3. 收集可选:images(凭证图片),priority(normal/urgent/critical),refund_amount(退款金额)
4. 展示汇总 -> 用户确认 -> 调 after_sales_manage(action="create", ...)

## 原则

- 不编造售后信息,一切以系统数据为准
- 写操作必须先确认再执行
- 复杂投诉(赔偿/法律)建议转人工
- 从对话历史追踪已收集信息,不重复询问
- 专业高效,有同理心的语气"""


async def aftersales_node(state: AgentState) -> dict:
    """售后 Skill 节点函数

    处理售后服务,投诉,退换货相关请求。

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
