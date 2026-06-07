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
    {"type": "ask", "description": "收集基本信息", "ask_prompt": "请提供商品名称和价格", "fields": ["name", "price"]},
    {"type": "query", "description": "选择分类", "query_tool": "category_manage", "query_params": {"action": "tree"}, "query_prompt": "请选择一个分类"},
    {"type": "query", "description": "选择加工项", "query_tool": "processing_item_query", "query_params": {"status": "active"}, "query_prompt": "请选择加工项（可多选，回复编号如 1,3）"},
    {"type": "confirm", "description": "确认创建"},
    {"type": "execute", "description": "执行创建", "execute_tool": "product_manage", "execute_action": "create"}
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

    try:
        content = await LLMFactory.invoke_text_safe(messages, enable_thinking=True)
        content = content.strip()
        # 清理 markdown 包裹
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        plan_dict = json.loads(content)
        plan = Plan.from_json(plan_dict)
        logger.info(f"[pe] Plan generated | goal='{plan.goal}' steps={len(plan.steps)}")
        return plan
    except Exception as e:
        logger.error(f"[pe] Plan generation failed: {e}")
        return None


# ── 信息提取 ──


def _validate_tool(tool_name: str, allowed_tools: List[str], step_desc: str) -> bool:
    """校验工具是否在允许列表中，防止 LLM prompt injection 越权"""
    if tool_name and tool_name not in allowed_tools:
        logger.warning(f"[pe] Tool '{tool_name}' not in allowed {allowed_tools} for step '{step_desc}' — rejected")
        return False
    return True


async def _extract_fields(user_message: str, fields: List[str], existing: Dict) -> Dict:
    """从用户自然语言回复中提取字段值"""
    if not fields:
        return {}
    llm = LLMFactory.create_skill_llm(enable_thinking=False)
    prompt = (
        f"从用户回复中提取以下字段的值。没提到的字段不要编造。\n\n"
        f"用户回复: {user_message}\n"
        f"需要提取的字段: {', '.join(fields)}\n"
        f"已有信息: {json.dumps(existing, ensure_ascii=False)}\n\n"
        f"返回纯 JSON，如 {{\"字段名\": \"值\"}}。"
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()
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

        plan.skill_name = skill_name
        await _save_plan(session_id, plan)

    # 2. 获取当前步骤
    current = plan.current()
    if current is None:
        await _clear_plan(session_id)
        return {"final_answer": "操作已完成。", "messages": [], "skill_used": skill_name}

    logger.info(f"[pe] Step {plan.current_step + 1}/{len(plan.steps)} type={current.type} goal='{plan.goal}'")

    # 3. 如果是延续之前的 Plan（非第一步），从用户回复中提取信息
    if plan.current_step > 0:
        prev = plan.steps[plan.current_step - 1]
        if prev.type == "ask" and prev.fields:
            extracted = await _extract_fields(last_user_msg, prev.fields, plan.context)
            plan.context.update(extracted)
        elif prev.type == "query":
            plan.context["_user_choice"] = last_user_msg
        elif prev.type == "confirm":
            yes_words = ["确认", "是的", "可以", "好的", "行", "对", "ok", "yes", "确定", "没问题"]
            plan.context["_user_confirmed"] = any(w in last_user_msg.lower() for w in yes_words)
            if not plan.context["_user_confirmed"]:
                # 用户取消 → 清除 Plan
                await _clear_plan(session_id)
                return {"final_answer": "好的，已取消。", "messages": [AIMessage(content="好的，已取消。")], "skill_used": skill_name}

    # 4. 执行当前步骤
    new_messages = []
    final_answer = ""
    awaiting_user = False

    if current.type == "ask":
        prompt = (
            f"你需要向用户收集信息。\n"
            f"已收集: {json.dumps(plan.context, ensure_ascii=False)}\n"
            f"还需收集: {json.dumps(current.fields, ensure_ascii=False)}\n"
            f"提示: {current.ask_prompt}\n\n"
            f"直接向用户提问，简洁友好。不要调用工具。"
        )
        final_answer = await LLMFactory.invoke_text_safe([
            SystemMessage(content=system_prompt),
            *messages[-4:],
            HumanMessage(content=prompt),
        ])
        new_messages.append(AIMessage(content=final_answer))
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
            except Exception as e:
                query_data = json.dumps({"error": str(e)}, ensure_ascii=False)
        else:
            query_data = json.dumps({"error": f"工具不可用: {current.query_tool}"}, ensure_ascii=False)

        # LLM 格式化展示
        prompt = (
            f"查询结果如下。请用文字展示给用户，用编号列表方便用户回复。\n"
            f"展示提示: {current.query_prompt}\n"
            f"已收集信息: {json.dumps(plan.context, ensure_ascii=False)}\n\n"
            f"查询结果:\n{query_data}\n\n"
            f"直接展示并请用户选择，不要调用工具。"
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
            f"请用户确认以下信息后执行操作。\n"
            f"完整信息:\n{json.dumps(plan.context, ensure_ascii=False, indent=2)}\n\n"
            f"整理成清单展示，结尾明确请求确认（如'确认创建？回复 确认 或 取消'）。不要调用工具。"
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

        # 只传递白名单字段，防止 context 参数注入
        _SAFE_PARAMS = {"name", "price", "description", "category_id", "stock_quantity",
                         "processing_item_ids", "product_id", "status", "unit", "cost_price"}
        exec_params = {"action": current.execute_action}
        for k in _SAFE_PARAMS:
            if k in plan.context:
                exec_params[k] = plan.context[k]

        if tool:
            try:
                result = await tool.execute(ctx, **exec_params)
                exec_result = result.message if result.success else f"失败: {result.message}"
            except Exception as e:
                exec_result = f"异常: {e}"
        else:
            exec_result = f"工具不可用: {current.execute_tool}"

        prompt = (
            f"操作已执行。请用友好的语气告知用户结果。\n"
            f"操作: {current.execute_tool}.{current.execute_action}\n"
            f"结果: {exec_result}\n\n"
            f"直接回复用户，不要调用工具。"
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
