"""
Plan-and-Execute 执行器

多步骤写操作（创建商品、创建订单等）走 P&E 模式：
1. LLM 一次性生成结构化 Plan（JSON）
2. 代码按 Plan 逐步执行，每步 LLM 只负责生成展示文本
3. 需要用户输入时保存 Plan 状态，下次消息恢复执行

查询类/简单操作保持 ReAct 模式，不走此路径。
"""

import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.llm import LLMFactory
from app.graph.state import AgentState


# ── Plan 数据结构 ──

@dataclass
class PlanStep:
    """Plan 中的一步"""
    type: str  # ask | query | confirm | execute
    description: str = ""
    # ask 步
    ask_prompt: str = ""
    fields: List[str] = field(default_factory=list)
    # query 步
    query_tool: str = ""
    query_params: Dict[str, Any] = field(default_factory=dict)
    query_prompt: str = ""
    # execute 步
    execute_tool: str = ""
    execute_action: str = ""


@dataclass
class Plan:
    """完整 Plan"""
    goal: str
    skill_name: str = ""  # 所属 skill，用于多轮回合路由
    steps: List[PlanStep] = field(default_factory=list)
    current_step: int = 0
    context: Dict[str, Any] = field(default_factory=dict)

    def current(self) -> Optional[PlanStep]:
        if 0 <= self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def advance(self):
        self.current_step += 1

    def is_done(self) -> bool:
        return self.current_step >= len(self.steps)

    def to_json(self) -> str:
        return json.dumps({
            "goal": self.goal,
            "skill_name": self.skill_name,
            "steps": [{"type": s.type, "description": s.description,
                        "ask_prompt": s.ask_prompt, "fields": s.fields,
                        "query_tool": s.query_tool, "query_params": s.query_params,
                        "query_prompt": s.query_prompt,
                        "execute_tool": s.execute_tool, "execute_action": s.execute_action}
                       for s in self.steps],
            "current_step": self.current_step,
            "context": self.context,
        }, ensure_ascii=False)

    @staticmethod
    def from_json(data: dict) -> "Plan":
        steps = []
        for s in data.get("steps", []):
            steps.append(PlanStep(
                type=s.get("type", ""),
                description=s.get("description", ""),
                ask_prompt=s.get("ask_prompt", ""),
                fields=s.get("fields", []),
                query_tool=s.get("query_tool", ""),
                query_params=s.get("query_params", {}),
                query_prompt=s.get("query_prompt", ""),
                execute_tool=s.get("execute_tool", ""),
                execute_action=s.get("execute_action", ""),
            ))
        return Plan(
            goal=data.get("goal", ""),
            skill_name=data.get("skill_name", ""),
            steps=steps,
            current_step=data.get("current_step", 0),
            context=data.get("context", {}),
        )


# ── Prompts ──

PLAN_GENERATION_PROMPT = """你是一个工作流规划器。根据用户的请求，生成简洁的执行计划。

可用步骤：ask(收集信息) | query(查数据展示选项) | confirm(确认) | execute(执行)
规则：单步一事，先收集→再查询→确认→执行，≤6步。

=== 商品创建（含图片上传）===
用户上传了商品图片，Vision 已分析出 name/description/brand/colors/specifications，
只需收集缺失的销售属性。

{
  "goal": "创建2699系列色卡商品",
  "steps": [
    {"type": "ask", "description": "收集销售属性", "ask_prompt": "请提供价格、库存、货号、售卖方式(散剪/整卷)、规格尺寸(门幅)", "fields": ["price", "stock_quantity", "sku_code", "selling_methods", "door_widths"]},
    {"type": "query", "description": "选择分类", "query_tool": "category_manage", "query_params": {"action": "tree"}, "query_prompt": "请选择商品分类"},
    {"type": "query", "description": "选择加工项", "query_tool": "processing_item_query", "query_params": {"status": "active"}, "query_prompt": "请选择加工项（可多选，回复编号如1,3，不需要回复0）"},
    {"type": "confirm", "description": "确认创建"},
    {"type": "execute", "description": "执行创建", "execute_tool": "product_manage", "execute_action": "create"}
  ]
}

=== 订单创建 ===
{
  "goal": "为客户创建订单",
  "steps": [
    {"type": "ask", "description": "收集订单信息", "ask_prompt": "请提供客户姓名、电话、地址、商品名称和数量", "fields": ["customer_name", "customer_phone", "customer_address", "product_name", "quantity"]},
    {"type": "query", "description": "搜索商品", "query_tool": "product_search", "query_params": {"keyword": ""}, "query_prompt": "请选择商品"},
    {"type": "query", "description": "查商品加工项", "query_tool": "product_detail", "query_params": {}, "query_prompt": "该商品支持以下加工项，请选择（不需要回复0）"},
    {"type": "confirm", "description": "确认订单"},
    {"type": "execute", "description": "创建订单", "execute_tool": "order_create", "execute_action": "create"}
  ]
}

=== 售后工单创建 ===
用户需要为某个订单创建售后工单（退款/退货/投诉等）。

{
  "goal": "为订单ORD-xxx创建退款工单",
  "steps": [
    {"type": "ask", "description": "了解售后诉求", "ask_prompt": "请描述售后问题（退款/退货/换货/投诉），并提供订单号或客户信息", "fields": ["issue_type", "reason", "order_no"]},
    {"type": "query", "description": "查询订单详情", "query_tool": "order_query", "query_params": {"action": "detail"}, "query_prompt": "找到以下订单，请确认"},
    {"type": "confirm", "description": "确认创建工单"},
    {"type": "execute", "description": "创建售后工单", "execute_tool": "after_sales_manage", "execute_action": "create"}
  ]
}

=== 售后工单处理 ===
用户要处理已有的售后工单（审批/完结/分配等），不需要 P&E，直接 ReAct。
"""


# ── 智能默认值（根据同类商品推荐属性）──


async def _fetch_smart_defaults(
    category_id: str,
    category_name: str,
    tool_names: List[str],
    ctx,
) -> Dict[str, Any]:
    """查询同类商品，提取常见属性值作为智能推荐

    在用户选择分类后调用，用 product_search 查同类商品，
    分析最常见的 selling_methods / door_widths / unit / price_range 等，
    返回给 ask 步骤作为上下文参考。

    Args:
        category_id: 分类 ID
        category_name: 分类名称
        tool_names: 可用工具列表
        ctx: ToolContext

    Returns:
        {common_attributes, price_range, sample_count, category_name}
    """
    from app.tools.registry import get_tool_registry, set_tool_context

    if "product_search" not in tool_names:
        return {}

    set_tool_context(ctx)
    registry = get_tool_registry()
    tool = registry.get_tool("product_search")
    if not tool:
        return {}

    try:
        result = await tool.execute(ctx, keyword=category_name, size=10)
        if not result.success or not result.data:
            return {}

        products = result.data.get("products") or result.data.get("items") or []
        if len(products) < 2:
            return {}  # 样本太少，不推荐

        # 统计常见属性
        sm_counter: Dict[str, int] = {}
        dw_counter: Dict[str, int] = {}
        unit_counter: Dict[str, int] = {}
        prices: List[float] = []
        specs: Dict[str, Dict[str, int]] = {}  # spec_key → {value: count}
        color_counter: Dict[str, int] = {}
        pricing_counter: Dict[str, int] = {}
        brand_counter: Dict[str, int] = {}
        proc_items: Dict[str, str] = {}  # processing_item_id → name

        for p in products:
            # 售卖方式
            sms = p.get("sellingMethods") or p.get("selling_methods") or []
            if isinstance(sms, list):
                for sm in sms:
                    sm_counter[sm] = sm_counter.get(sm, 0) + 1
            elif isinstance(sms, str) and sms:
                sm_counter[sms] = sm_counter.get(sms, 0) + 1

            # 门幅
            dws = p.get("doorWidths") or p.get("door_widths") or []
            if isinstance(dws, list):
                for dw in dws:
                    dw_counter[dw] = dw_counter.get(dw, 0) + 1
            elif isinstance(dws, str) and dws:
                dw_counter[dws] = dw_counter.get(dws, 0) + 1

            # 单位
            unit = p.get("unit", "")
            if unit:
                unit_counter[unit] = unit_counter.get(unit, 0) + 1

            # 价格
            price = p.get("price")
            if price is not None:
                try:
                    prices.append(float(price))
                except (ValueError, TypeError):
                    pass

            # 规格（克重/工艺/风格/材质/遮光率等全部动态属性）
            product_specs = p.get("specifications") or {}
            if isinstance(product_specs, dict):
                for spec_key, spec_val in product_specs.items():
                    if spec_key not in specs:
                        specs[spec_key] = {}
                    val = str(spec_val)
                    specs[spec_key][val] = specs[spec_key].get(val, 0) + 1

            # 颜色
            colors_list = p.get("colors") or []
            if isinstance(colors_list, list):
                for c in colors_list:
                    name = c.get("colorName") or c.get("name") or str(c)
                    if name:
                        color_counter[name] = color_counter.get(name, 0) + 1

            # 计价方式
            pt = p.get("pricingType") or p.get("pricing_type") or ""
            if pt:
                pricing_counter[pt] = pricing_counter.get(pt, 0) + 1

            # 品牌
            brand = p.get("brand", "")
            if brand:
                brand_counter[brand] = brand_counter.get(brand, 0) + 1

            # 关联加工项
            pi_list = p.get("processingItems") or p.get("processing_items") or []
            if isinstance(pi_list, list):
                for pi in pi_list:
                    pid = pi.get("id") or pi.get("processingItemId") or ""
                    pname = pi.get("name") or pi.get("processingItemName") or ""
                    if pid and pid not in proc_items:
                        proc_items[pid] = pname

        # 取最常见的值（出现 >=30% 的才推荐）
        threshold = max(1, int(len(products) * 0.3))
        defaults: Dict[str, Any] = {"category_name": category_name, "sample_count": len(products)}

        top_sms = sorted(sm_counter.items(), key=lambda x: -x[1])
        if top_sms and top_sms[0][1] >= threshold:
            defaults["common_selling_methods"] = [s for s, _ in top_sms]

        top_dws = sorted(dw_counter.items(), key=lambda x: -x[1])
        if top_dws and top_dws[0][1] >= threshold:
            defaults["common_door_widths"] = [d for d, _ in top_dws]

        top_units = sorted(unit_counter.items(), key=lambda x: -x[1])
        if top_units and top_units[0][1] >= threshold:
            defaults["common_unit"] = top_units[0][0]

        top_pt = sorted(pricing_counter.items(), key=lambda x: -x[1])
        if top_pt and top_pt[0][1] >= threshold:
            defaults["common_pricing_type"] = top_pt[0][0]

        if prices:
            prices.sort()
            defaults["price_range"] = f"{prices[0]:.0f}~{prices[-1]:.0f}元"

        # 规格属性（克重/工艺/风格/材质/遮光率等）— 取每个 key 最常见的值
        if specs:
            common_specs = {}
            for spec_key, value_counts in specs.items():
                top_vals = sorted(value_counts.items(), key=lambda x: -x[1])
                # 至少出现 2 次或 >=30%
                if top_vals[0][1] >= max(2, threshold):
                    common_specs[spec_key] = top_vals[0][0]  # 最常见值
            if common_specs:
                defaults["common_specifications"] = common_specs

        # 颜色
        top_colors = sorted(color_counter.items(), key=lambda x: -x[1])
        if top_colors and top_colors[0][1] >= threshold:
            defaults["common_colors"] = [c for c, _ in top_colors[:8]]

        # 品牌
        top_brands = sorted(brand_counter.items(), key=lambda x: -x[1])
        if top_brands and top_brands[0][1] >= threshold:
            defaults["common_brands"] = [b for b, _ in top_brands]

        # 常用加工项
        if proc_items:
            defaults["common_processing_items"] = [{"id": pid, "name": pname} for pid, pname in proc_items.items()]

        logger.info(
            f"[pe] Smart defaults fetched | category={category_name} "
            f"samples={len(products)} keys={list(defaults.keys())}"
        )
        return defaults

    except Exception as e:
        logger.warning(f"[pe] Smart defaults fetch failed (non-fatal): {e}")
        return {}


async def _fetch_order_smart_defaults(
    product_name: str,
    product_id: str = "",
    tool_names: List[str] = None,
    ctx=None,
) -> Dict[str, Any]:
    """选好商品后查详情，预填价格/加工项/单位"""
    if not tool_names or "product_detail" not in tool_names:
        return {}
    from app.tools.registry import get_tool_registry, set_tool_context
    set_tool_context(ctx)
    registry = get_tool_registry()
    tool = registry.get_tool("product_detail")
    if not tool:
        return {}
    try:
        params = {"product_id": product_id} if product_id else {"keyword": product_name}
        result = await tool.execute(ctx, **params)
        if not result.success or not result.data:
            return {}
        product = result.data.get("product") or result.data
        if not product:
            return {}
        defaults: Dict[str, Any] = {"_source_product": product_name}
        if product.get("price") is not None:
            defaults["unit_price"] = product["price"]
        if product.get("unit"):
            defaults["unit"] = product["unit"]
        if product.get("product_id") or product.get("id"):
            defaults["product_id"] = product.get("product_id") or product.get("id")
        items = product.get("processingItems") or product.get("processing_items") or []
        if items:
            defaults["available_processing_items"] = items
            logger.info(f"[pe] Order smart defaults: {product_name} price={defaults.get('unit_price')} items={len(items)}")
        return defaults
    except Exception as e:
        logger.warning(f"[pe] Order smart defaults failed (non-fatal): {e}")
        return {}


async def _fetch_aftersales_smart_defaults(order_no: str, ctx=None) -> Dict[str, Any]:
    """根据订单号查详情，预填售后工单的客户/金额/商品"""
    from app.tools.registry import get_tool_registry, set_tool_context
    set_tool_context(ctx)
    registry = get_tool_registry()
    tool = registry.get_tool("order_query")
    if not tool:
        return {}
    try:
        result = await tool.execute(ctx, action="detail", order_no=order_no)
        if not result.success or not result.data:
            return {}
        order = result.data.get("order") or result.data
        if not order:
            return {}
        defaults: Dict[str, Any] = {"_source_order": order_no}
        if order.get("customer_name"):
            defaults["customer_name"] = order["customer_name"]
        if order.get("customer_phone") or order.get("phone"):
            defaults["customer_phone"] = order.get("customer_phone") or order.get("phone")
        if order.get("total_amount"):
            defaults["order_amount"] = order["total_amount"]
        items = order.get("items") or order.get("order_items") or []
        if items:
            defaults["order_items"] = [{"name": i.get("product_name", ""), "qty": i.get("quantity", 1)} for i in items[:5]]
        logger.info(f"[pe] Aftersales smart defaults: {order_no} customer={defaults.get('customer_name')}")
        return defaults
    except Exception as e:
        logger.warning(f"[pe] Aftersales smart defaults failed (non-fatal): {e}")
        return {}


async def _save_plan(session_id: str, plan: Plan):
    if not session_id:
        return
    try:
        from app.memory.session_memory import SessionMemory
        await SessionMemory().set_plan_state(session_id, plan.to_json())
        logger.info(f"[pe] Plan saved | session={session_id} step={plan.current_step}/{len(plan.steps)}")
    except Exception as e:
        logger.warning(f"[pe] save_plan failed: {e}")


async def _load_plan(session_id: str) -> Optional[Plan]:
    if not session_id:
        return None
    try:
        from app.memory.session_memory import SessionMemory
        raw = await SessionMemory().get_plan_state(session_id)
        if raw:
            return Plan.from_json(json.loads(raw))
    except Exception as e:
        logger.warning(f"[pe] load_plan failed: {e}")
    return None


async def _clear_plan(session_id: str):
    if not session_id:
        return
    try:
        from app.memory.session_memory import SessionMemory
        await SessionMemory().clear_plan_state(session_id)
    except Exception as e:
        logger.warning(f"[pe] clear_plan failed: {e}")


# ── Plan 生成 ──



async def _generate_plan(user_message: str, chat_history: list, goal_hint: str = "") -> Optional[Plan]:
    """调用 LLM 生成 Plan，失败返回 None"""
    prompt = f"用户请求: {user_message}"
    if goal_hint:
        prompt += f"\n意图提示: {goal_hint}"
    prompt += "\n\n请生成执行计划（纯 JSON）。"

    messages = [SystemMessage(content=PLAN_GENERATION_PROMPT), *chat_history[-4:], HumanMessage(content=prompt)]

    raw = ""
    try:
        raw = await LLMFactory.invoke_text_safe(messages, enable_thinking=False)
        # 从 LLM 回复中提取 JSON 对象（LLM 可能在 JSON 前后加说明文字）
        content = raw.strip()
        # 找到第一个 { 和最后一个 }
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
        # 清理 markdown 包裹
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        plan_dict = json.loads(content)
        plan = Plan.from_json(plan_dict)
        logger.info(f"[pe] Plan generated | goal='{plan.goal}' steps={len(plan.steps)}")
        return plan
    except Exception as e:
        logger.error(f"[pe] Plan generation failed: {e} | raw={raw[:300]}")
        return None


# ── 信息提取 ──


def _validate_tool(tool_name: str, allowed_tools: List[str], step_desc: str) -> bool:
    """校验工具是否在允许列表中，防止 LLM prompt injection 越权"""
    if tool_name and tool_name not in allowed_tools:
        logger.warning(f"[pe] Tool '{tool_name}' not in allowed {allowed_tools} for step '{step_desc}' — rejected")
        return False
    return True


def _match_user_choice(user_msg: str, results: list) -> Optional[dict]:
    """从用户回复匹配查询结果中的选项，返回 {field_name: actual_value}

    用户可能回复编号(1,2)、名称或 ID。
    results 格式: [{"id": "...", "name": "...", ...}, ...]
    根据 query_tool 类型返回对应的字段，如 category_manage → {category_id: ...}
    """
    if not results or not user_msg:
        return None
    # 提取数字
    import re
    nums = re.findall(r'\d+', user_msg)
    if nums:
        # 支持多选："1,3,5" → 匹配所有编号
        ids = []
        names = []
        for n in nums:
            idx = int(n) - 1
            if 0 <= idx < len(results):
                item = results[idx]
                if "id" in item:
                    ids.append(item["id"])
                if "name" in item:
                    names.append(item["name"])
        if ids:
            return {"id": ids[0] if len(ids) == 1 else ids,
                    "name": names[0] if len(names) == 1 else names,
                    "ids": ids, "names": names}
    # 尝试名称匹配
    for item in results:
        name = item.get("name", "")
        if name and name in user_msg:
            return {"id": item.get("id"), "name": name}
    return None


# ── 用户意图检测（修正/回溯/查看进度）──


# 修正意图关键词
_CORRECTION_PATTERNS = [
    # "字段名 + 改/修改/改成/不对/应该是/不是/换成/更正 + 新值"
    # 支持中文和英文 key
    re.compile(
        r"(?:"
        r"(?:价格|售价|单价|price)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成|不是[，,]?\s*是)\s*([\d.]+)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:名称|名字|商品名|name)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成|不是[，,]?\s*是)\s*(.+?)(?:[,，。\s]|$)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:库存|数量|stock)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成)\s*([\d]+)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:货号|编码|sku_code)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成)\s*(.+?)(?:[,，。\s]|$)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:分类|category)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成|换[一个]?)\s*(.+?)(?:[,，。]|$)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:门幅|尺寸|门宽|door_width)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成)\s*(.+?)(?:[,，。\s]|$)"
        r")",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:"
        r"(?:售卖方式|销售方式|selling_method)\s*(?:改成?|修改为?|不对[，,]?\s*应该是?|更正为?|换成)\s*(.+?)(?:[,，。\s]|$)"
        r")",
        re.IGNORECASE,
    ),
    # 通用模式："XX不对" / "XX应该是YY"
    re.compile(
        r"(?:"
        r"(\S{2,8})\s*(?:不对|错了|有误)[，,]?\s*(?:应该是?|改成?|换成?|更正为?)\s*(.+?)(?:[,，。\s]|$)"
        r")",
        re.IGNORECASE,
    ),
]

# 回溯关键词
_BACK_PATTERN = re.compile(r"(?:回到上一步|返回上一步|上一步|返回|后退|back)", re.IGNORECASE)

# 查看进度关键词
_SHOW_PATTERN = re.compile(r"(?:现在有哪些信息|看看进度|当前信息|汇总|现在填了什么|有哪些字段|show|status)", re.IGNORECASE)

# 步骤名 → 关键词映射（用于"重新选分类"这类意图）
_STEP_REDO_PATTERNS = [
    (re.compile(r"重新(?:选|填|选择|填写)\s*(?:分类|category)", re.IGNORECASE), 1),   # 通常分类在第2步
    (re.compile(r"重新(?:选|填|选择|填写)\s*(?:加工项|加工|processing)", re.IGNORECASE), 2),  # 加工项在第3步
    (re.compile(r"重新(?:填|填写|输入)\s*(?:信息|属性|价格|库存|货号)", re.IGNORECASE), 0),  # 回到 ask 步
]


async def _detect_user_intent(user_msg: str, plan) -> dict:
    """分析用户消息意图，支持修正/回溯/查看进度

    纯规则匹配，零 LLM 调用延迟。

    Returns:
        {action, field?, value?, target_step?}
        action: "continue" | "correct" | "back" | "goto" | "show" | "cancel"
    """
    if not user_msg:
        return {"action": "continue"}

    # 1. 检测取消
    cancel_words = ["取消", "不要了", "算了", "不用了", "不做", "不创建了", "放弃"]
    if any(w in user_msg for w in cancel_words):
        return {"action": "cancel"}

    # 2. 检测回溯
    if _BACK_PATTERN.search(user_msg):
        return {"action": "back"}

    # 3. 检测重做某步
    for pattern, target_step in _STEP_REDO_PATTERNS:
        if pattern.search(user_msg):
            return {"action": "goto", "target_step": target_step}

    # 4. 检测查看进度
    if _SHOW_PATTERN.search(user_msg):
        return {"action": "show"}

    # 5. 检测字段修正
    for pattern in _CORRECTION_PATTERNS:
        m = pattern.search(user_msg)
        if m:
            groups = m.groups()
            if len(groups) == 1:
                # 单字段模式，从 pattern 推断字段名
                raw_value = groups[0].strip()
                field_name = _infer_field_from_pattern(pattern, raw_value)
                if field_name:
                    return {"action": "correct", "field": field_name, "value": raw_value}
            elif len(groups) >= 2:
                # 通用模式：group(1)=字段名, group(2)=新值
                cn_field = groups[0].strip()
                raw_value = groups[1].strip() if len(groups) > 1 else ""
                field_name = _FIELD_NAME_MAP.get(cn_field, "")
                if not field_name:
                    # 尝试用字段名本身匹配
                    for cn, en in _FIELD_NAME_MAP.items():
                        if cn_field in cn or cn in cn_field:
                            field_name = en
                            break
                if field_name and raw_value:
                    return {"action": "correct", "field": field_name, "value": raw_value}

    return {"action": "continue"}


def _infer_field_from_pattern(pattern: re.Pattern, value: str) -> str:
    """从正则 pattern 推断对应的英文字段名"""
    import re as _re
    pat_str = pattern.pattern
    if _re.search(r"价格|售价|单价|price", pat_str):
        return "price"
    if _re.search(r"名称|名字|商品名|name", pat_str):
        return "name"
    if _re.search(r"库存|数量|stock", pat_str):
        return "stock_quantity"
    if _re.search(r"货号|编码|sku_code", pat_str):
        return "sku_code"
    if _re.search(r"分类|category", pat_str):
        return "category_name"
    if _re.search(r"门幅|尺寸|门宽|door_width", pat_str):
        return "door_widths"
    if _re.search(r"售卖|销售|selling_method", pat_str):
        return "selling_methods"
    return ""


# 中文字段名 → 英文 key 映射
_FIELD_NAME_MAP = {
    "名称": "name", "商品名称": "name", "名字": "name",
    "价格": "price", "售价": "price", "单价": "price",
    "库存": "stock_quantity", "库存数量": "stock_quantity", "数量": "stock_quantity",
    "描述": "description", "详情": "description", "介绍": "description",
    "分类": "category_id",
    "货号": "sku_code", "商品货号": "sku_code", "编码": "sku_code",
    "售卖方式": "selling_methods", "销售方式": "selling_methods",
    "规格尺寸": "door_widths", "门幅": "door_widths", "尺寸": "door_widths",
    "单位": "unit", "计价单位": "unit",
    # 订单字段
    "客户姓名": "customer_name", "客户": "customer_name", "姓名": "customer_name",
    "电话": "customer_phone", "手机": "customer_phone", "联系电话": "customer_phone",
    "地址": "customer_address", "收货地址": "customer_address",
    "备注": "remark", "订单备注": "remark",
    "商品": "product_name", "商品名称": "product_name",
    "数量": "quantity", "件数": "quantity",
    "总价": "total_amount", "金额": "total_amount",
}


async def _extract_fields(user_message: str, fields: List[str], existing: Dict) -> Dict:
    """从用户自然语言回复中提取字段值"""
    if not fields:
        return {}
    mapping_hints = "\n".join(
        f"  {cn} → {en}" for cn, en in _FIELD_NAME_MAP.items() if en in fields
    )
    prompt = (
        f"从用户回复中提取以下字段的值。中文字段名请按映射表转换为英文 key：\n"
        f"{mapping_hints}\n\n"
        f"用户回复: {user_message}\n"
        f"需要提取的字段: {', '.join(fields)}\n"
        f"已有信息: {json.dumps(existing, ensure_ascii=False)}\n\n"
        f"返回纯 JSON，key 使用英文字段名。没提到的字段不要编造。"
    )
    try:
        content = await LLMFactory.invoke_text_safe([HumanMessage(content=prompt)])
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(content)
    except Exception:
        return {"raw_input": user_message}


# ── 主入口 ──


async def execute_plan(
    state: AgentState,
    skill_name: str,
    tool_names: List[str],
    system_prompt: str,
) -> Optional[dict]:
    """P&E 主入口。返回 None 表示应回退到 ReAct。"""
    messages = state.get("messages", [])
    session_id = state.get("session_id", "")
    intent_result = state.get("intent_result", {})

    # 提取最后一条用户消息
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # 1. 加载或生成 Plan
    plan = await _load_plan(session_id)

    if plan is None:
        intent_name = ""
        if isinstance(intent_result, dict):
            intent_name = intent_result.get("intent", "")
        plan = await _generate_plan(last_user_msg, messages, intent_name)

        if plan is None or len(plan.steps) == 0:
            return None  # 回退 ReAct

        # 单步简单操作不需要 P&E
        if len(plan.steps) == 1 and plan.steps[0].type in ("ask", "query"):
            return None

        # 从 Vision 分析消息中提取图片 URL 预填充 plan.context
        for msg in messages:
            role = getattr(msg, 'type', '') or getattr(msg, 'role', '')
            if role not in ('system', 'assistant', 'ai'):
                continue
            if hasattr(msg, 'content') and isinstance(msg.content, str) and '[图片URL]' in msg.content:
                try:
                    marker = '[图片URL]'
                    marker_end = msg.content.index(marker) + len(marker)
                    json_start = msg.content.index('[', marker_end)
                    json_end = msg.content.index(']', json_start) + 1
                    urls = json.loads(msg.content[json_start:json_end])
                    if urls and "images" not in plan.context:
                        plan.context["images"] = list(dict.fromkeys(urls))  # 去重
                        logger.info(f"[pe] Vision images pre-filled: {len(plan.context['images'])} urls")
                except Exception:
                    pass

        # 从 Vision 分析消息中提取商品属性预填充 context
        for msg in messages:
            if hasattr(msg, 'content') and isinstance(msg.content, str) and '[图片分析结果]' in msg.content:
                vision_fields = await _extract_fields(
                    msg.content,
                    ["name", "description", "brand", "colors", "specifications",
                     "pricing_type", "unit", "selling_methods", "door_widths"],
                    plan.context
                )
                for k, v in vision_fields.items():
                    if v and k not in plan.context and k != "raw_input":
                        plan.context[k] = v
                if vision_fields:
                    logger.info(f"[pe] Vision data pre-filled: {list(vision_fields.keys())}")
                break

        plan.skill_name = skill_name
        await _save_plan(session_id, plan)

    # 2. 获取当前步骤
    current = plan.current()
    if current is None:
        await _clear_plan(session_id)
        return {"final_answer": "操作已完成。", "messages": [], "skill_used": skill_name}

    logger.info(f"[pe] Step {plan.current_step + 1}/{len(plan.steps)} type={current.type} goal='{plan.goal}'")

    # ── 0. 用户意图检测（修正/回溯/查看进度）──
    user_intent = await _detect_user_intent(last_user_msg, plan)

    if user_intent["action"] == "cancel":
        await _clear_plan(session_id)
        return {"final_answer": "好的，已取消。", "messages": [AIMessage(content="好的，已取消。")], "skill_used": skill_name}

    need_re_execute = False  # 标记是否需要重新执行当前步骤（修正后不换步）

    if user_intent["action"] == "back":
        plan.current_step = max(0, plan.current_step - 1)
        current = plan.current()
        logger.info(f"[pe] Backtracked to step {plan.current_step + 1}: {current.type}")
        need_re_execute = True

    elif user_intent["action"] == "goto":
        plan.current_step = max(0, min(user_intent["target_step"], len(plan.steps) - 1))
        current = plan.current()
        logger.info(f"[pe] Goto step {plan.current_step + 1}: {current.type}")
        need_re_execute = True

    elif user_intent["action"] == "correct":
        field = user_intent["field"]
        value = user_intent["value"]
        old = plan.context.get(field, "(未设置)")
        plan.context[field] = value
        logger.info(f"[pe] Field corrected: {field}={old} → {value}")
        # 修正信息后重新执行当前步骤，不推进
        need_re_execute = True

    elif user_intent["action"] == "show":
        # 展示当前收集的所有信息，不推进步骤
        show_lines = ["📋 **当前已收集的信息**："]
        for k, v in plan.context.items():
            if k.startswith("_"):  # 跳过内部字段
                continue
            val_str = str(v)[:80] if v else "(空)"
            show_lines.append(f"  • {k}: {val_str}")
        show_lines.append(f"\n_当前步骤 {plan.current_step + 1}/{len(plan.steps)}: {current.description}_")
        show_lines.append("你可以继续填写，或者对我说\"修改XX为YY\"来更正。")
        final_answer = "\n".join(show_lines)
        await _save_plan(session_id, plan)
        return {"messages": [AIMessage(content=final_answer)], "final_answer": final_answer, "skill_used": skill_name}

    # 如果发生了回溯/跳转/修正，保存 plan 并重新执行
    if need_re_execute:
        await _save_plan(session_id, plan)
        # 重建 context 中的内部标记
        plan.context.pop("_user_choice", None)
        plan.context.pop("_query_results", None)
        plan.context.pop("_user_confirmed", None)

    # ── 1. 从用户回复中提取信息（延续之前的 Plan）──
    if plan.current_step > 0 and not need_re_execute:
        prev = plan.steps[plan.current_step - 1]
        if prev.type == "ask" and prev.fields:
            extracted = await _extract_fields(last_user_msg, prev.fields, plan.context)
            plan.context.update(extracted)
        elif prev.type == "query":
            plan.context["_user_choice"] = last_user_msg
            results = plan.context.get("_query_results", [])
            if results:
                matched = _match_user_choice(last_user_msg, results)
                if matched:
                    qt = prev.query_tool
                    if qt == "category_manage":
                        from app.graph.skills.base_skill import build_tool_context
                        plan.context["category_id"] = matched.get("id", "")
                        plan.context["category_name"] = matched.get("name", "")
                        logger.info(f"[pe] Query choice matched: tool={qt} id={matched.get('id')}")
                        # 根据同类商品提取智能默认值
                        smart = await _fetch_smart_defaults(
                            category_id=plan.context["category_id"],
                            category_name=plan.context["category_name"],
                            tool_names=tool_names,
                            ctx=build_tool_context(state),
                        )
                        if smart:
                            plan.context["_smart_defaults"] = smart
                            logger.info(
                                f"[pe] Smart defaults set for category '{smart.get('category_name')}' "
                                f"({smart.get('sample_count', 0)} samples)"
                            )
                    elif qt == "processing_item_query":
                        ids_list = matched.get("ids", [matched.get("id", "")])
                        plan.context["processing_item_ids"] = [i for i in ids_list if i]
                        logger.info(f"[pe] Query choice matched: tool={qt} count={len(plan.context['processing_item_ids'])}")
        elif prev.type == "confirm":
            plan.context["_user_confirmed"] = True

    # ── 2. 执行当前步骤 ──
    new_messages = []
    final_answer = ""
    awaiting_user = False

    if current.type == "ask":
        # 构建智能默认值提示
        smart_hint = ""
        smart_defaults = plan.context.get("_smart_defaults", {})
        if smart_defaults:
            parts = [f"\n## 同类商品参考（{smart_defaults.get('category_name', '')}分类，{smart_defaults.get('sample_count', 0)}件样本）"]
            if smart_defaults.get("common_selling_methods"):
                parts.append(f"  • 售卖方式: {smart_defaults['common_selling_methods']}")
            if smart_defaults.get("common_door_widths"):
                parts.append(f"  • 门幅/尺寸: {smart_defaults['common_door_widths']}")
            if smart_defaults.get("common_unit"):
                parts.append(f"  • 计价单位: {smart_defaults['common_unit']}")
            if smart_defaults.get("common_pricing_type"):
                parts.append(f"  • 计价方式: {smart_defaults['common_pricing_type']}")
            if smart_defaults.get("price_range"):
                parts.append(f"  • 价格区间: {smart_defaults['price_range']}")
            if smart_defaults.get("common_specifications"):
                spec_str = ", ".join(f"{k}≈{v}" for k, v in smart_defaults["common_specifications"].items())
                parts.append(f"  • 常见规格属性: {spec_str}")
            if smart_defaults.get("common_colors"):
                parts.append(f"  • 常见颜色: {smart_defaults['common_colors'][:5]}")
            if smart_defaults.get("common_brands"):
                parts.append(f"  • 常见品牌: {smart_defaults['common_brands']}")
            if smart_defaults.get("common_processing_items"):
                pi_names = [pi["name"] for pi in smart_defaults["common_processing_items"]]
                parts.append(f"  • 常用加工项: {pi_names[:5]}")
            parts.append("  → 向用户推荐时可直接采用这些常见值，说'同类商品一般用XX'\n")
            smart_hint = "\n".join(parts)

        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"需收集的字段: {json.dumps(current.fields, ensure_ascii=False)}\n"
            f"提示: {current.ask_prompt}\n"
            f"用户说: {last_user_msg}\n"
            f"对话上下文已包含的信息: {json.dumps(plan.context, ensure_ascii=False)}"
            f"{smart_hint}\n"
            f"规则:\n"
            f"1. 仔细分析对话上下文——图片识别结果、用户回复中可能已包含部分字段的值\n"
            f"2. 能从上下文推断的字段直接确认使用，不要重复问\n"
            f"3. 如果上面有\"同类商品参考\"，优先推荐其中最常见的值（如'同类商品一般用XX'），"
            f"让用户可以一键确认，不用手动填写每个选项\n"
            f"4. 如果没有同类商品参考，根据商品名自动推断类型默认值：\n"
            f"   - 窗帘/布料类: selling_methods 默认 ['bulk_cut','full_roll'], door_widths 默认 ['2.8m','3.2m']\n"
            f"   - 配件/辅料类: selling_methods 默认 ['per_piece']\n"
            f"5. 只提问真正缺失且无法推断的字段\n"
            f"6. 如果所有信息已齐全，直接告诉用户信息已完整可以确认创建\n"
            f"7. ⚠️ 如果用户消息中包含对已有信息的修正（如\"价格改成200\"\"名字不对，应该是XX\"），"
            f"先在回复开头确认修正（\"好的，已更新XX为YY\"），然后继续提问其他缺失字段\n\n"
            f"简洁友好地告诉用户你已自动填入了什么，只问缺失的。不要调用工具。"
        )
        final_answer = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=prompt),
        ])
        new_messages.append(AIMessage(content=final_answer))

        # 从对话历史中自动提取可推断的字段值填充 context
        all_known = " ".join(
            m.content if isinstance(m.content, str) else str(m.content)
            for m in messages[-6:]
            if hasattr(m, "content")
        )
        inferred = await _extract_fields(all_known, current.fields, plan.context)
        for k, v in inferred.items():
            if v and k not in plan.context:
                plan.context[k] = v
        if inferred:
            logger.info(f"[pe] Auto-filled from context: {list(inferred.keys())}")
        awaiting_user = True

    elif current.type == "query":
        # 校验工具权限
        if not _validate_tool(current.query_tool, tool_names, current.description):
            await _clear_plan(session_id)
            return {"final_answer": "操作无法完成，请重试。", "messages": [AIMessage(content="操作无法完成，请重试。")], "skill_used": skill_name}

        # 执行查询
        from app.tools.registry import get_tool_registry, set_tool_context
        from app.graph.skills.base_skill import build_tool_context

        registry = get_tool_registry()
        tool = registry.get_tool(current.query_tool)
        ctx = build_tool_context(state)
        set_tool_context(ctx)

        if tool:
            try:
                result = await tool.execute(ctx, **current.query_params)
                query_data = json.dumps(
                    result.data if result.success else {"error": result.message},
                    ensure_ascii=False
                )
                # 存储查询结果，供下一步匹配用户选择
                if result.success and result.data:
                    items = result.data.get("items") or result.data.get("tree") or []
                    if items:
                        plan.context["_query_results"] = items
                        # 代码直接生成编号列表，不依赖 LLM
                        lines = []
                        for i, item in enumerate(items, 1):
                            name = item.get("name", "")
                            desc_parts = []
                            price = item.get("unit_price") or item.get("price") or item.get("basePrice")
                            if price is not None:
                                desc_parts.append(f"{price}元")
                            unit = item.get("unit", "")
                            if unit:
                                desc_parts.append(f"/{unit}")
                            extra = item.get("description") or item.get("category_name", "")
                            line = f"{i}. {name}"
                            if desc_parts:
                                line += f" - {''.join(desc_parts)}"
                            if extra:
                                line += f"（{extra}）"
                            lines.append(line)
                        query_data = "\n".join(lines)
            except Exception as e:
                query_data = f"查询失败: {e}"
        else:
            query_data = f"工具不可用: {current.query_tool}"

        # 代码直接拼接带编号列表，不经过 LLM，避免编号被吃掉
        intro_prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"展示提示: {current.query_prompt}\n"
            f"已收集: {json.dumps(plan.context, ensure_ascii=False)}\n\n"
            f"请用一句话引导用户从下方列表中选择（编号已在列表中，你不需要重复列出）。不要调用工具。"
        )
        llm_intro = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=intro_prompt),
        ])
        # 代码直接拼接编号列表 + 选择引导，LLM 只负责 intro 文案
        final_answer = (
            f"{llm_intro.strip()}\n\n"
            f"{query_data}\n\n"
            f"请回复对应的数字编号进行选择。"
        )
        new_messages.append(AIMessage(content=final_answer))
        awaiting_user = True

    elif current.type == "confirm":
        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"用户说: {last_user_msg}\n"
            f"完整信息:\n{json.dumps(plan.context, ensure_ascii=False, indent=2)}\n\n"
            f"规则:\n"
            f"1. 结合用户刚才的回复，整理成清单展示，结尾明确请求确认（如'确认创建？回复 确认 或 取消'）\n"
            f"2. ⚠️ 如果用户不是在确认而是在修改信息（如\"价格改成200\"\"分类换一个\"），"
            f"先说明\"已更新XX为YY\"，然后重新展示修改后的完整清单，再次请求确认\n"
            f"不要调用工具。"
        )
        final_answer = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=prompt),
        ])
        new_messages.append(AIMessage(content=final_answer))
        awaiting_user = True

    elif current.type == "execute":
        # 校验工具权限，防止 LLM prompt injection 越权
        if not _validate_tool(current.execute_tool, tool_names, current.description):
            await _clear_plan(session_id)
            return {"final_answer": "操作无法完成，请重试。", "messages": [AIMessage(content="操作无法完成，请重试。")], "skill_used": skill_name}

        from app.tools.registry import get_tool_registry, set_tool_context
        from app.graph.skills.base_skill import build_tool_context

        registry = get_tool_registry()
        tool = registry.get_tool(current.execute_tool)
        ctx = build_tool_context(state)
        set_tool_context(ctx)

        # 如果 name 缺失，从对话历史中兜底提取
        if "name" not in plan.context or not plan.context.get("name"):
            # 搜索用户消息和 Vision 分析结果中的商品名称
            all_text = " ".join(
                m.content if isinstance(m.content, str) else str(m.content)
                for m in messages
                if hasattr(m, 'content')
            )
            # 从所有历史文本中提取 name
            name_fields = await _extract_fields(all_text, ["name"], plan.context)
            if name_fields.get("name"):
                plan.context["name"] = name_fields["name"]
                logger.info(f"[pe] Name fallback extracted: {plan.context['name'][:50]}")

        # 只传递白名单字段，防止 context 参数注入
        # 规范化 context 中的字段名和值格式
        _FIELD_ALIASES = {"stock": "stock_quantity", "库存": "stock_quantity",
                           "_images": "images"}
        for alias, target in _FIELD_ALIASES.items():
            if alias in plan.context and target not in plan.context:
                plan.context[target] = plan.context[alias]
        # processing_item_ids: 从 query 步收集的加工项 ID 列表
        if "_query_results" in plan.context and not plan.context.get("processing_item_ids"):
            results = plan.context["_query_results"]
            if results and results[0].get("id"):
                plan.context["processing_item_ids"] = [r["id"] for r in results]
        # 列表字段：字符串拆分为数组
        for list_field in ("selling_methods", "door_widths", "processing_item_ids"):
            val = plan.context.get(list_field)
            if isinstance(val, str):
                import re
                plan.context[list_field] = [p.strip() for p in re.split(r'[,，、\s]+|和|与', val) if p.strip()]

        # 根据工具类型选择安全参数
        # product_manage: 从 colors/selling_methods/door_widths 构造 skus
        if current.execute_tool == "product_manage":
            colors = plan.context.get("colors", [])
            sms = plan.context.get("selling_methods", [])
            dws = plan.context.get("door_widths", [])
            if colors and sms and dws and "skus" not in plan.context:
                sm_list = sms if isinstance(sms, list) else [sms]
                dw_list = dws if isinstance(dws, list) else [dws]
                # 规范化 colors 为 dict 列表，给每个加临时 id
                normalized_colors = []
                for ci, c in enumerate(colors):
                    if isinstance(c, str):
                        normalized_colors.append({"colorName": c, "id": -(ci + 1)})
                    elif isinstance(c, dict):
                        if "id" not in c:
                            c["id"] = -(ci + 1)
                        normalized_colors.append(c)
                colors = normalized_colors
                plan.context["colors"] = colors
                # 构造 SKU：每个 color × sellingMethod × doorWidth
                skus = []
                total_sku_stock = int(plan.context.get("stock_quantity", plan.context.get("stock", 0)) or 0)
                for c in colors:
                    cid = c.get("id", 0) if isinstance(c, dict) else 0
                    for sm in sm_list:
                        for dw in dw_list:
                            skus.append({"colorId": cid, "sellingMethod": sm, "doorWidth": dw,
                                          "price": plan.context.get("price", 0),
                                          "stock": max(1, total_sku_stock // max(1, len(colors) * len(sm_list) * len(dw_list)))})
                plan.context["colors"] = colors  # 更新回去带 id
                plan.context["skus"] = skus
                logger.info(f"[pe] Auto-generated {len(skus)} SKUs")
            if "processing_item_ids" in plan.context and "processing_item_configs" not in plan.context:
                pids = plan.context["processing_item_ids"]
                pid_list = pids if isinstance(pids, list) else [pids]
                # 从查询结果中匹配价格
                results = plan.context.get("_query_results", [])
                price_map = {r.get("id"): r.get("unit_price") for r in results if r.get("id")}
                configs = []
                for pid in pid_list:
                    if pid:
                        cfg = {"processingItemId": pid}
                        price = price_map.get(pid)
                        if price is not None:
                            cfg["customPrice"] = price
                        configs.append(cfg)
                plan.context["processing_item_configs"] = configs
        if current.execute_tool == "order_create":
            if "items" not in plan.context and "product_name" in plan.context:
                qty = int(plan.context.get("quantity", 1))
                plan.context["items"] = [{"product_name": plan.context.get("product_name", ""), "quantity": qty}]
            _SAFE_PARAMS = {"customer_name", "customer_phone", "customer_address",
                             "remark", "items", "product_name", "quantity", "total_amount"}
            _NUMERIC_PARAMS = {"quantity", "total_amount"}
            exec_params = {}
        else:
            _SAFE_PARAMS = {"name", "price", "description", "category_id", "stock_quantity",
                             "processing_item_ids", "processing_item_configs", "product_id", "status",
                             "unit", "cost_price", "brand", "images", "specifications", "colors",
                             "selling_methods", "door_widths", "skus", "sku_code", "pricing_type"}
            _NUMERIC_PARAMS = {"price", "cost_price", "stock_quantity"}
            exec_params = {"action": current.execute_action}
        for k in _SAFE_PARAMS:
            if k in plan.context:
                v = plan.context[k]
                # LLM 提取的值是字符串，需要转为数字
                if k in _NUMERIC_PARAMS and isinstance(v, str):
                    try:
                        v = float(v) if "." in v else int(v)
                    except ValueError:
                        pass
                exec_params[k] = v

        if tool:
            try:
                result = await tool.execute(ctx, **exec_params)
                exec_result = result.message if result.success else f"失败: {result.message}"
            except Exception as e:
                exec_result = f"异常: {e}"
        else:
            exec_result = f"工具不可用: {current.execute_tool}"

        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"操作: {current.execute_tool}.{current.execute_action}\n"
            f"结果: {exec_result}\n\n"
            f"用友好的语气告知用户操作结果。不要调用工具。"
        )
        final_answer = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=prompt),
        ])
        new_messages.append(AIMessage(content=final_answer))
        # execute 完成后清除 Plan
        plan.advance()
        await _clear_plan(session_id)

    # 5. 保存状态
    if awaiting_user:
        # 修正/回溯/查看进度后不推进步骤，重新执行当前步
        if not need_re_execute and user_intent["action"] != "correct":
            plan.advance()
        if plan.is_done():
            await _clear_plan(session_id)
        else:
            await _save_plan(session_id, plan)

    return {
        "messages": new_messages,
        "final_answer": final_answer,
        "skill_used": skill_name,
    }


# ── 判断是否需要 P&E ──


def should_use_plan_execute(state: AgentState, skill_name: str) -> bool:
    """判断当前请求是否应走 P&E 模式"""
    messages = state.get("messages", [])
    last_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                # 多模态消息：提取文本部分
                parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                last_msg = " ".join(parts)
            else:
                last_msg = str(content) if content else ""
            break

    create_kw = ["创建", "新增", "添加", "新建", "上架", "录入"]
    update_kw = ["修改", "更新", "编辑", "调整", "变更"]
    write_kw = create_kw + update_kw

    if not any(kw in last_msg for kw in write_kw):
        return False

    if skill_name == "product":
        return any(kw in last_msg for kw in create_kw + update_kw)
    elif skill_name == "order":
        return any(kw in last_msg for kw in ["创建", "新增", "下单"])
    elif skill_name == "aftersales":
        return any(kw in last_msg for kw in create_kw)

    return False
