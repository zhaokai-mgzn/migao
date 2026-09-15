"""
订单 Skill 节点

处理订单查询,物流追踪,订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 订单 Skill 可用的 Tool 列表
# ⚠️ 加工单工具（processing_order_generate/query/update）不在此列（产品决策 2026-09-15，
# issue #3917）：agent 暂不接入加工单工具，须区分「加工项/加工单」概念并引导后台
# （订单详情-加工单块）。intents 保留（下方）⇒「加工单」问题仍路由到订单 skill，
# 由 prompts/order.md 的概念区分口径引导，**不得**用加工项查询/目录代替、不得编造加工单数据。
ORDER_TOOLS = ["order_query", "order_manage", "order_create", "logistics_track", "product_search", "product_detail",
    "validate_input",  # 写操作前置校验
    "interact",        # 交互卡片：多 SKU 规格 choice（prompts/order.md 强制要求）、下单前 confirm、表单 form
]

# 订单 Skill 专用 System Prompt（展示规则，状态机见 references/prompts/order.md）
ORDER_SYSTEM_PROMPT = """## 订单展示

表格或列表展示订单(订单号/客户/金额/状态/时间)，用emoji标记状态，末尾引导下一步操作。"""

ORDER_SKILL_CONFIG = SkillConfig(
    name="order",
    domain="order",
    display_name="订单管理",
    tool_names=ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "order_create", "logistics_track",
             "processing_order_generate", "processing_order_query", "processing_order_update"],
    system_prompts={"mibao": ORDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
