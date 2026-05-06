"""
辅助节点函数

包含 StateGraph 中除 Skill 节点以外的辅助节点：
- cache_check_node: 语义缓存检查
- intent_router_node: 意图路由
- direct_reply_node: 直接回复（greeting 等）
- cache_store_node: 缓存写入
- suggestions_node: 后续问题建议

以及条件边路由函数：
- check_cache_hit: 缓存命中判断
- route_by_intent: 意图→Skill 路由
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from app.graph.state import AgentState


# ────────────────────── 辅助节点 ──────────────────────


async def cache_check_node(state: AgentState) -> dict:
    """检查语义缓存是否命中"""
    from app.cache.semantic_cache import semantic_cache
    from app.config import settings

    if not settings.SEMANTIC_CACHE_ENABLED:
        return {"cached_answer": None}

    try:
        # 取最后一条用户消息
        user_msg_content = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                user_msg_content = msg.content
                break

        if not user_msg_content:
            return {"cached_answer": None}

        result = await semantic_cache.lookup(
            tenant_id=str(state["tenant_id"]),
            query=user_msg_content,
        )
        if result:
            logger.info(
                f"[cache_check] HIT | tenant={state['tenant_id']} "
                f"confidence={result.confidence:.4f}"
            )
            return {
                "cached_answer": result.answer,
                "final_answer": result.answer,
                "skill_used": "cache",
            }
    except Exception as e:
        logger.warning(f"Cache check failed: {e}")

    return {"cached_answer": None}


async def intent_router_node(state: AgentState) -> dict:
    """执行意图路由"""
    from app.router.intent_router import IntentRouter

    router = IntentRouter()

    # 取最后一条用户消息
    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    # 构建 chat_history（从 state.messages 中提取，排除最后一条用户消息）
    chat_history: list[dict[str, str]] = []
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            # 跳过最后一条（即当前用户消息），它会作为 message 参数传入
            if msg.content == user_message and msg is state["messages"][-1]:
                continue
            chat_history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            chat_history.append({"role": "assistant", "content": msg.content})

    route_decision = await router.route(user_message, chat_history)

    return {
        "intent_result": {
            "intent": route_decision.intent_result.intent.value,
            "confidence": route_decision.intent_result.confidence,
            "source": route_decision.intent_result.source,
        },
        "route_decision": {
            "action": route_decision.action,
            "direct_reply": route_decision.direct_reply,
            "tool_hint": route_decision.tool_hint,
        },
    }


# 按 agent_type 区分的问候语，避免小布返回米宝的问候
_AGENT_GREETINGS: dict[str, str] = {
    "xiaobu": "您好！我是小布，米高窗帘的智能客服。我可以为您介绍商品、查询订单、追踪物流，还能解答窗帘相关的各种问题，请问有什么可以帮您的吗？",
    "mibao": "您好！我是米宝，您的智能工作助手。我可以帮您处理商品管理、订单处理、库存查询等工作事务，有什么需要帮忙的吗？",
}


async def direct_reply_node(state: AgentState) -> dict:
    """直接回复，不调用大模型（greeting 等场景）"""
    route_decision = state.get("route_decision") or {}
    intent = (state.get("intent_result") or {}).get("intent", "")
    reply = route_decision.get("direct_reply") or ""

    # greeting 意图：根据 agent_type 返回对应问候语，而非使用 intent_router 硬编码的回复
    if intent == "greeting" or not reply:
        agent_type = state.get("agent_type", "xiaobu")
        reply = _AGENT_GREETINGS.get(agent_type, reply or "你好！有什么可以帮您的吗？")

    return {
        "messages": [AIMessage(content=reply)],
        "final_answer": reply,
        "skill_used": "direct_reply",
    }


async def cache_store_node(state: AgentState) -> dict:
    """将回答写入语义缓存"""
    from app.cache.semantic_cache import semantic_cache
    from app.config import settings

    if not settings.SEMANTIC_CACHE_ENABLED:
        return {}

    try:
        intent_type = (state.get("intent_result") or {}).get("intent", "general")

        # 找到用户的原始消息（最后一条 HumanMessage）
        user_msg = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                user_msg = msg.content
                break

        if user_msg and state.get("final_answer"):
            await semantic_cache.store(
                tenant_id=str(state["tenant_id"]),
                query=user_msg,
                answer=state["final_answer"],
                intent_type=intent_type,
            )
    except Exception as e:
        logger.warning(f"Cache store failed: {e}")

    return {}


async def suggestions_node(state: AgentState) -> dict:
    """生成后续问题建议"""
    from app.suggestions.follow_up import FollowUpSuggestionGenerator

    generator = FollowUpSuggestionGenerator()
    intent_type = (state.get("intent_result") or {}).get("intent", "general")

    # 找到用户原始消息
    user_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_msg = msg.content
            break

    try:
        suggestions = await asyncio.wait_for(
            generator.generate(
                query=user_msg,
                answer=state.get("final_answer", ""),
                intent_type=intent_type,
            ),
            timeout=15.0,
        )
        return {"suggestions": suggestions}
    except asyncio.TimeoutError:
        logger.debug("Suggestions generation timed out, using empty list")
        return {"suggestions": []}
    except Exception as e:
        logger.warning(f"Suggestions generation failed: {e}")
        return {"suggestions": []}


# ────────────────────── 条件边路由函数（同步）──────────────────────


def check_cache_hit(state: AgentState) -> str:
    """缓存检查后的条件路由"""
    if state.get("cached_answer"):
        return "hit"
    return "miss"


# 意图 → 路由 key 映射（两种 Agent 共用相同的 key，builder 中映射到不同节点名）
_INTENT_TO_ROUTE: dict[str, str] = {
    "order_query": "order",
    "logistics_track": "order",
    "product_inquiry": "product",
    "knowledge_faq": "knowledge",
    "after_sales": "aftersales",
    "complaint": "aftersales",
    "greeting": "direct_reply",
    "farewell": "direct_reply",
    "capabilities": "direct_reply",
    "general": "general",
}


def route_by_intent(state: AgentState) -> str:
    """根据意图路由到对应 Skill

    返回的路由 key 会被 builder.py 中的 skill_route_map 映射到实际节点名：
    - mibao: order → order_skill, product → product_skill, ...
    - xiaobu: order → customer_order_skill, product → customer_product_skill, ...
    """
    route = state.get("route_decision") or {}
    action = route.get("action", "full_agent")

    if action == "direct_reply":
        return "direct_reply"

    intent = (state.get("intent_result") or {}).get("intent", "general")

    return _INTENT_TO_ROUTE.get(intent, "general")
