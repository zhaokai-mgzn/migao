"""
订单 Skill 节点

处理订单查询,物流追踪,订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 订单 Skill 可用的 Tool 列表
# 加工单工具（processing_order_generate/query/update）按 issue #4196 恢复接入（用户裁定反转
# #3917 的「暂不接入」决策；#4027 曾因它们不在 IntentType 而把 3 个意图从 intents 移除，
# 本次在 IntentType / _INTENT_DESCRIPTIONS / INTENT_DOMAINS / INTENT_TOOL_MAP 四处一并补齐）。
# ⚠️ 概念区分口径**不退场**（prompts/order.md 的防混淆守则）：加工项 ≠ 加工单，**不得**用
# 加工项查询/目录冒充加工单，**不得**编造加工单号/状态。
ORDER_TOOLS = ["order_query", "order_manage", "order_create", "logistics_track", "product_search", "product_detail",
    # 生产进度（issue #3996，M4-I）：商家问「这单做到哪道工序/还要多久」→
    # production_progress_query(order_no=…)。只读；缺号先用 order_query 取号。
    "production_progress_query",
    "validate_input",  # 写操作前置校验
    "interact",        # 交互卡片：多 SKU 规格 choice（prompts/order.md 强制要求）、下单前 confirm、表单 form
    # 店铺加工项目录（issue #4371：加工项与商品**解耦**）—— prompts/order.md 的「加工项」
    # 一节强制要求「confirm 前必须先调 processing_item_query 拿目录再发 choice 卡」，
    # 而 product_detail 已不再返回 processing_items ⇒ 不绑定本工具就是
    # 「提示词承诺了做不到的事」（模型撞 tool_not_found、加工费漏收；同型先例 #3365）。
    "processing_item_query",
    "processing_order_generate",  # 生成加工单（批量，写操作 confirm）
    "processing_order_query",     # 加工单查询（只读）
    "processing_order_update",    # 加工单状态更新（issue/start/complete/cancel，写操作 confirm）
]

# 订单 Skill 专用 System Prompt（展示规则，状态机见 references/prompts/order.md）
ORDER_SYSTEM_PROMPT = """## 订单展示

表格或列表展示订单(订单号/客户/金额/状态/时间)，用emoji标记状态，末尾引导下一步操作。

## 生产进度（订单做到哪道工序）

商家问「这单做到哪了/生产进度/还要多久/卡在哪道工序/排产了吗」时，调 production_progress_query(order_no=…)：
拿到进度%、当前工序、待完工序、预计交期后再回答。缺订单号先用 order_query 查单取号，不要猜号；
**转述必须来自工具返回**，工具查不到就如实说查不到，禁止编造进度或交期。"""

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
