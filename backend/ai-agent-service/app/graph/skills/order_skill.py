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
    # 加工单过程明细（issue #4201）：商家问「这单下料/裁剪做到哪了、谁报的、合格多少、
    # 返工报废多少」→ production_worklog_query(order_no=…)。只读、仅 B 端。
    "production_worklog_query",
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
**转述必须来自工具返回**，工具查不到就如实说查不到，禁止编造进度或交期。

## 过程明细（下料/裁剪做到哪一步、谁报的、合格多少）

商家问「这单**下料**/裁剪做到哪了」「谁报的」「合格多少」「返工/报废多少」「过程明细」时，
调 production_worklog_query(order_no=…)：拿到逐工序的应做/合格/返工/报废数量 + 报工人 +
报工明细后再回答。「下料」= 工序库**裁剪组**（`group_name=裁剪`，如 精裁-布 / 裁剪-纱），
**不是**另一个模型，也**不要**为它另造说法。
**数量口径（唯一一份，与 V49 表注释同源）**：合格 = 正常报工（work_type=normal）的合格数；
返工/报废各取该笔报工数量；**返工/报废不计件、不累加进度**。
**计件金额一律以工具返回为准**（服务端按同一份聚合计算），**禁止自行心算或编造金额**；
工具返回为空（该单尚未生产）就如实说「暂无工序/报工记录」。"""

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
