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
    "interact",        # 交互卡片：写操作 confirm、售后类型/原因 choice
]

# 售后 Skill 专用 System Prompt
AFTERSALES_SYSTEM_PROMPT = """## 售后工单枚举（英文仅内部传值，回复用户必须用中文）

ticket_type: refund=退款/exchange=换货/repair=维修/complaint=投诉/other=其他
priority: normal=普通/urgent=紧急/critical=严重
status: pending=待处理/processing=处理中/resolved=已解决/rejected=已拒绝/closed=已关闭
必填: description(问题描述)
可选: images(凭证), refund_amount(退款金额)

## 售后原则

- 复杂投诉(赔偿/法律)建议转人工
- 从对话历史追踪已收集信息，不重复询问
- 专业高效，有同理心的语气

## 回复语言要求（禁止英文枚举）

- 回复用户时，工单的状态/优先级/类型必须用中文业务术语（待处理/处理中/已解决/已拒绝/已关闭、普通/紧急/严重、退款/换货/维修/投诉/其他）
- 禁止把英文枚举值（pending/normal/refund 等）原样输出给用户
- ✅"当前有 3 条待处理工单，优先级均为普通" ❌"优先级标记都是 normal"""

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
