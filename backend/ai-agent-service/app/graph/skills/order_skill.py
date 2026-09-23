"""
订单 Skill 节点（B 端米宝，**只读**，issue #5247）

处理订单查询、物流追踪、加工单查询与生产进度/报工明细查询。
🔴 写能力（建单 / 改状态 / 生成加工单 / 加工单状态流转）已按用户裁定 2026-09-23 从 B 端移除：
本 skill 的 `tool_names` 里不得再出现任何 `read_only != True` 的工具（`order_create` /
`order_manage` / `processing_order_generate` / `processing_order_update` / `validate_input`）。
「怎么办建单/改状态」类请求 = 如实说明 B 端已只读 + 引导用户到后台页面自行操作。

⚠️ `route_keys` 与 `intents` **有意保持不变**（两层间接路由：全局 intent→route_key 映射仅由
B 端 skill 构建，C 端小布经 builder 的 `skill_route_map` 重映射）。删 intent 会连带改掉
小布的意图路由 —— 属「C 端零改动」红线之外的动作，故只改工具面与提示词面。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 订单 / 加工单 / 生产只读工具（全部 read_only=True；写工具已解绑，见模块 docstring）
ORDER_TOOLS = [
    "order_query",
    "logistics_track",
    "product_search",
    "product_detail",
    # 生产进度（issue #3996，M4-I）：商家问「这单做到哪道工序/还要多久」→
    # production_progress_query(order_no=…)。只读；缺号先用 order_query 取号。
    "production_progress_query",
    # 加工单过程明细（issue #4201）：商家问「这单下料/裁剪做到哪了、谁报的、合格多少、
    # 返工报废多少」→ production_worklog_query(order_no=…)。只读、仅 B 端。
    "production_worklog_query",
    # 店铺加工项目录（issue #4371：加工项与商品**解耦**）：prompts/order.md 的「加工项」
    # 一节要求「加工费按下单时选的加工项目录核对」，而 product_detail 已不再返回
    # processing_items ⇒ 不绑定本工具就是「提示词承诺了做不到的事」（同型先例 #3365）。
    "processing_item_query",
    "processing_order_query",     # 加工单查询（只读）
    # 加工套件 / 扫码循环（issue #5247 模块覆盖）：GET /api/admin/processing-order-sets*（processing:manage），
    # 复用服务端同一份 setOverview 聚合（不得另造第二份），unit_price=null 保持 null（#4696 口径）。
    "processing_order_set_query",
    # 交互卡片只保留**消歧/选择**（choice）：B 端不再发写确认卡（issue #5247 裁定 2）。
    "interact",
]

# 订单 Skill 专用 System Prompt（展示规则，状态机见 references/prompts/order.md）
ORDER_SYSTEM_PROMPT = """## 🔴 本域已只读（issue #5247 用户裁定 2026-09-23）

**没有任何建单 / 改状态 / 生成加工单 / 加工单状态流转能力**。商家提出这类请求时：
1. 如实说明「米宝在订单域现在只做查询与分析，建单/改单/发货/退款请到后台页面操作」；
2. 给出**具体页面路径**（订单列表 /orders、订单详情页的对应按钮）；
3. **不得**承诺代办、不得说「我这就帮您提交」、不得发写确认卡（choice 消歧卡仍可用）。
问「你能不能创建订单」时如实回答不能，不要含糊。

## 订单展示

表格或列表展示订单(订单号/客户/金额/状态/时间)，用emoji标记状态，末尾引导下一步查询。

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
工具返回为空（该单尚未生产）就如实说「暂无工序/报工记录」。

## 加工单（只读）

商家问「加工单到哪了 / JG-xxx 什么状态 / 这个订单的加工单」→ `processing_order_query`。
概念区分口径**不退场**：加工项 ≠ 加工单，**不得**用加工项查询冒充加工单，**不得**编造加工单号/状态。
生成加工单 / 改加工单状态**不在能力内** → 引导到后台「生产看板」页操作。
"""

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
