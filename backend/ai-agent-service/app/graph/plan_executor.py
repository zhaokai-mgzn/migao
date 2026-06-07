"""
Plan-and-Execute 执行器

多步骤写操作（创建商品、创建订单等）走 P&E 模式：
1. LLM 一次性生成结构化 Plan（JSON）
2. 代码按 Plan 逐步执行，每步 LLM 只负责生成展示文本
3. 需要用户输入时保存 Plan 状态，下次消息恢复执行

查询类/简单操作保持 ReAct 模式，不走此路径。
"""

import json
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

PLAN_GENERATION_PROMPT = """你是一个工作流规划器。根据用户的请求，生成一个简洁的执行计划。

可用步骤类型：
- ask: 需要向用户收集信息
- query: 需要先查询数据再展示给用户选择（如查分类列表、加工项列表）
- confirm: 汇总已收集的信息，请用户确认
- execute: 执行最终的写操作

规则：
1. 每步做一件事，不要混合
2. 先收集信息 → 再查询选项 → 确认 → 执行
3. 步骤数不超过 6 步
4. 查询不需要 confirm + execute

输出纯 JSON（无 markdown 标记）：
{
  "goal": "创建遮光窗帘",
  "steps": [
    {"type": "ask", "description": "收集基本信息", "ask_prompt": "请提供价格、库存、货号、售卖方式(散剪/整卷)、规格尺寸(门幅)、计价单位", "fields": ["price", "stock_quantity", "sku_code", "selling_methods", "door_widths", "unit"]},
    {"type": "query", "description": "选择分类", "query_tool": "category_manage", "query_params": {"action": "tree"}, "query_prompt": "请选择一个分类"},
    {"type": "query", "description": "选择加工项", "query_tool": "processing_item_query", "query_params": {"status": "active"}, "query_prompt": "请选择加工项（可多选，回复编号如 1,3）"},
    {"type": "confirm", "description": "确认创建"},
    {"type": "execute", "description": "执行创建", "execute_tool": "product_manage", "execute_action": "create"}
  ]
}

订单创建示例（加工项从选中商品的 product_detail 获取，不是全店查询）：
{
  "goal": "为客户李先生创建窗帘订单",
  "steps": [
    {"type": "ask", "description": "收集订单信息", "ask_prompt": "请提供客户姓名、电话、收货地址、商品名称和数量", "fields": ["customer_name", "customer_phone", "customer_address", "product_name", "quantity"]},
    {"type": "query", "description": "搜索商品确认价格", "query_tool": "product_search", "query_params": {"keyword": ""}, "query_prompt": "请选择要下单的商品"},
    {"type": "query", "description": "查商品详情和加工项", "query_tool": "product_detail", "query_params": {"id": ""}, "query_prompt": "该商品支持的加工项如下，请选择（可多选，不需要回复无）"},
    {"type": "confirm", "description": "确认订单"},
    {"type": "execute", "description": "创建订单", "execute_tool": "order_create", "execute_action": "create"}
  ]
}"""


# ── Plan 持久化 ──


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
        idx = int(nums[0]) - 1  # 用户说的"1"对应 results[0]
        if 0 <= idx < len(results):
            item = results[idx]
            # 根据字段名推断用途
            matched = {}
            if "id" in item:
                matched["id"] = item["id"]
            if "name" in item:
                matched["name"] = item["name"]
            return matched
    # 尝试名称匹配
    for item in results:
        name = item.get("name", "")
        if name and name in user_msg:
            return {"id": item.get("id"), "name": name}
    return None


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
                        plan.context["images"] = urls
                        logger.info(f"[pe] Vision images pre-filled: {len(urls)} urls")
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

    # 4. 如果是延续之前的 Plan（非第一步），从用户回复中提取信息
    if plan.current_step > 0:
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
                    # 根据查询工具映射到正确的 context 字段
                    qt = prev.query_tool
                    item_id = matched.get("id", "")
                    if qt == "category_manage":
                        plan.context["category_id"] = item_id
                        plan.context["category_name"] = matched.get("name", "")
                    elif qt == "processing_item_query":
                        ids = plan.context.get("processing_item_ids", [])
                        if isinstance(ids, list):
                            ids.append(item_id)
                            plan.context["processing_item_ids"] = ids
                    logger.info(f"[pe] Query choice matched: tool={qt} id={item_id}")
        elif prev.type == "confirm":
            # 仅明确取消词才终止，其余都视为确认（用户可能在确认时补充信息）
            cancel_words = ["取消", "不要了", "算了", "不用了", "不做"]
            if any(w in last_user_msg for w in cancel_words):
                await _clear_plan(session_id)
                return {"final_answer": "好的，已取消。", "messages": [AIMessage(content="好的，已取消。")], "skill_used": skill_name}
            plan.context["_user_confirmed"] = True

    # 4. 执行当前步骤
    new_messages = []
    final_answer = ""
    awaiting_user = False

    if current.type == "ask":
        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"需收集的字段: {json.dumps(current.fields, ensure_ascii=False)}\n"
            f"提示: {current.ask_prompt}\n"
            f"用户说: {last_user_msg}\n"
            f"对话上下文已包含的信息: {json.dumps(plan.context, ensure_ascii=False)}\n\n"
            f"规则:\n"
            f"1. 仔细分析对话上下文——图片识别结果、用户回复中可能已包含部分字段的值\n"
            f"2. 能从上下文推断的字段直接确认使用，不要重复问\n"
            f"3. 根据商品类型自动推断：\n"
            f"   - 窗帘/布料类: selling_methods 默认 ['bulk_cut','full_roll'], door_widths 默认 ['2.8m','3.2m'], unit 默认 '米'\n"
            f"   - 配件/辅料类: unit 默认 '个' 或 '套', selling_methods 默认 ['per_piece']\n"
            f"4. 只提问真正缺失且无法推断的字段\n"
            f"5. 如果所有信息已齐全，直接告诉用户信息已完整可以确认创建\n\n"
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
            except Exception as e:
                query_data = json.dumps({"error": str(e)}, ensure_ascii=False)
        else:
            query_data = json.dumps({"error": f"工具不可用: {current.query_tool}"}, ensure_ascii=False)

        # LLM 格式化展示
        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"用户说: {last_user_msg}\n"
            f"展示提示: {current.query_prompt}\n"
            f"已收集信息: {json.dumps(plan.context, ensure_ascii=False)}\n\n"
            f"查询结果:\n{query_data}\n\n"
            f"要求:\n"
            f"1. 用编号列表展示，格式为 '1. 名称 - 价格/描述'\n"
            f"2. 每个选项独占一行，编号从 1 开始连续\n"
            f"3. 请用户回复编号选择。不要调用工具。"
        )
        final_answer = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=prompt),
        ])
        new_messages.append(AIMessage(content=final_answer))
        awaiting_user = True

    elif current.type == "confirm":
        prompt = (
            f"多步骤操作目标: {plan.goal}\n"
            f"用户说: {last_user_msg}\n"
            f"完整信息:\n{json.dumps(plan.context, ensure_ascii=False, indent=2)}\n\n"
            f"结合用户刚才的回复，整理成清单展示，结尾明确请求确认（如'确认创建？回复 确认 或 取消'）。不要调用工具。"
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
                             "processing_item_ids", "product_id", "status", "unit", "cost_price",
                             "brand", "images", "specifications", "colors",
                             "selling_methods", "door_widths", "sku_code", "pricing_type"}
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
