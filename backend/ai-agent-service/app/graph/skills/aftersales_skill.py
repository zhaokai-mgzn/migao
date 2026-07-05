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
AFTERSALES_SYSTEM_PROMPT = """## 工具

| 场景 | 工具 |
|------|------|
| 查订单详情 | order_query |
| 退款/取消订单 | order_manage |
| 售后工单(列表/详情/创建/更新) | after_sales_manage |

## 创建售后工单流程

用户说要退货/退款/投诉 → 立即推进创建流程，不要只查订单就停住：
1. 先查订单：order_query 确认订单信息和状态
2. 确定类型：根据用户描述判断 ticket_type（退款/换货/维修/投诉/其他）
3. 收集必填：description(问题描述)
4. 询问可选：refund_amount(退款金额), priority(紧急程度)
5. 汇总确认 → after_sales_manage(action="create", ...)
⚠️ 禁止：只查订单不创建工单。查完订单必须继续推进。

## 售后原则

- 复杂投诉(赔偿/法律)建议转人工
- 从对话历史追踪已收集信息,不重复询问
- 专业高效,有同理心的语气"""

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
