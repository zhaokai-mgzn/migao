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
from typing import Union

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from app.graph.state import AgentState


# ────────────────────── 多模态内容处理 ──────────────────────


def _extract_text_from_content(content: Union[str, list, None]) -> str:
    """从 HumanMessage/AIMessage 的 content 中提取纯文本

    LangChain 多模态消息的 content 可以是：
    - str: 纯文本消息
    - list: 多模态消息，格式如 [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
    - None: 空消息

    Returns:
        str: 提取的文本内容，多个 text 段用空格拼接
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)
        return " ".join(parts)
    return str(content)


# ────────────────────── Agent 感知辅助函数 ──────────────────────

# 缓存：避免每次请求都重新计算
_agent_intents_cache: dict[str, list[str]] = {}


def reset_agent_intents_cache():
    """重置意图缓存（测试或配置热更新时调用）"""
    global _agent_intents_cache
    _agent_intents_cache = {}


def _get_agent_intents(agent_type: str) -> list[str]:
    """获取指定 Agent 可处理的意图列表（带缓存）

    从 SkillRegistry + AgentConfig 聚合该 Agent 的所有意图。
    分类器收到这个子集后，分类更准确、token 更少。
    """
    if agent_type in _agent_intents_cache:
        return _agent_intents_cache[agent_type]

    try:
        from app.graph.skills.skill_registry import get_skill_registry
        from app.agents.agent_config import get_agent_config

        agent_config = get_agent_config(agent_type)
        registry = get_skill_registry()
        intents = registry.get_intents_for_skills(agent_config.get_all_skill_names())
        # 始终包含公共意图
        intents.extend(["greeting", "farewell", "capabilities", "general"])
        # 去重后排序，但确保 'general' 始终排在最后（兜底语义）
        unique_intents = sorted(set(intents) - {"general"})
        unique_intents.append("general")
        intents = unique_intents
    except (KeyError, ImportError) as e:
        # 配置未就绪时降级为全部意图
        logger.warning(f"[_get_agent_intents] config not ready for {agent_type}: {e}, falling back to all intents")
        from app.router.intent_config import IntentType
        intents = [i.value for i in IntentType]

    _agent_intents_cache[agent_type] = intents
    return intents


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
                user_msg_content = _extract_text_from_content(msg.content)
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
    """执行意图路由

    Agent 感知：传入 agent_type，让分类器只考虑该 Agent 能处理的意图，
    提升分类准确率并降低 token 消耗。
    """
    from app.router.intent_router import IntentRouter

    router = IntentRouter()
    agent_type = state.get("agent_type", "xiaobu")

    # 取最后一条用户消息（多模态消息需提取文本部分）
    user_message = ""
    last_human_msg = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            last_human_msg = msg
            user_message = _extract_text_from_content(msg.content)
            break

    # 构建 chat_history（从 state.messages 中提取，排除最后一条用户消息）
    chat_history: list[dict[str, str]] = []
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            # 跳过最后一条（即当前用户消息），它会作为 message 参数传入
            if msg is last_human_msg:
                continue
            chat_history.append({"role": "user", "content": _extract_text_from_content(msg.content)})
        elif isinstance(msg, AIMessage):
            chat_history.append({"role": "assistant", "content": _extract_text_from_content(msg.content)})

    # Agent 感知：获取该 Agent 可处理的意图子集
    agent_intents = _get_agent_intents(agent_type)

    route_decision = await router.route(
        user_message, chat_history, agent_intents=agent_intents
    )

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


async def direct_reply_node(state: AgentState) -> dict:
    """直接回复，不调用大模型（greeting / farewell / capabilities 等场景）

    优先从 AgentConfig.direct_replies 获取回复文本，
    实现 Agent 级别的回复个性化，不再依赖硬编码映射。
    """
    route_decision = state.get("route_decision") or {}
    intent = (state.get("intent_result") or {}).get("intent", "")
    reply = route_decision.get("direct_reply") or ""
    agent_type = state.get("agent_type", "xiaobu")

    # 优先从 AgentConfig 获取 direct_reply
    try:
        from app.agents.agent_config import get_agent_config
        agent_config = get_agent_config(agent_type)
        config_reply = agent_config.get_direct_reply(intent)
        if config_reply:
            reply = config_reply
    except (KeyError, ImportError):
        pass

    # 兜底：如果 AgentConfig 中没有配置，使用默认值
    if not reply:
        if intent == "greeting":
            reply = "您好！有什么可以帮您的吗？"
        elif intent == "farewell":
            reply = "好的，有需要随时找我~ 😊"
        elif intent == "capabilities":
            reply = "我可以帮您处理各种问题，有什么需要帮忙的吗？"
        else:
            # 非标准意图或配置缺失时的通用兜底，防止返回空消息
            reply = "有什么可以帮您的吗？"

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
                user_msg = _extract_text_from_content(msg.content)
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
    agent_type = state.get("agent_type", "mibao")

    # 找到用户原始消息
    user_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_msg = _extract_text_from_content(msg.content)
            break

    try:
        suggestions = await asyncio.wait_for(
            generator.generate(
                query=user_msg,
                answer=state.get("final_answer", ""),
                intent_type=intent_type,
                agent_type=agent_type,
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
    "order_create": "order",
    "logistics_track": "order",
    "product_inquiry": "product",
    # [RAG 禁用] "knowledge_faq": "knowledge",  # 知识库禁用，fallback 到 general
    "knowledge_faq": "general",
    "after_sales": "aftersales",
    "complaint": "aftersales",
    "greeting": "direct_reply",
    "farewell": "direct_reply",
    "capabilities": "direct_reply",
    "general": "general",
    # 商家后台（米宝）管理类意图
    "customer_manage": "customer",
    "customer_query": "customer",
    "employee_manage": "staff",
    "staff_manage": "staff",
    "role_manage": "staff",
    "permission_manage": "staff",
    "system_settings": "settings",
    "ai_config": "settings",
    "notification": "settings",
    "quick_reply": "settings",
    "dashboard": "data",
    "statistics": "data",
    "data_report": "data",
    "session_manage": "data",
    "after_sales_create": "aftersales",
    # [RAG 禁用] "knowledge_manage": "knowledge",  # 知识库禁用，fallback 到 general
    "knowledge_manage": "general",
    "category_manage": "product",
    "processing_manage": "product",
}


def _last_human_has_image(messages: list) -> bool:
    """检测最后一条 HumanMessage 是否含图片

    LangChain 多模态消息的 content 格式为 list，其中包含 {type: "image_url"} 项。
    用于在路由阶段拦截带图片的请求，避免误入 direct_reply 节点。
    """
    from langchain_core.messages import HumanMessage

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                return any(
                    isinstance(item, dict) and item.get("type") == "image_url"
                    for item in content
                )
            return False
    return False


def route_by_intent(state: AgentState) -> str:
    """根据意图路由到对应 Skill

    返回的路由 key 会被 builder.py 中的 skill_route_map 映射到实际节点名：
    - mibao: order → order_skill, product → product_skill, ...
    - xiaobu: order → customer_order_skill, product → customer_product_skill, ...

    注意：当 last HumanMessage 含图片时，即使 intent 分类为 greeting/capabilities，
    也强制路由到 general skill（vision mode），防止直复节点忽略图片输入。

    会话连续性：当 pending_interact_skill 存在时（上次交互组件等待用户操作），
    优先回到原 skill，除非用户明确表达了不同的高置信度意图。
    """
    pending_skill = state.get("pending_interact_skill", "")
    route = state.get("route_decision") or {}
    action = route.get("action", "full_agent")

    if action == "direct_reply":
        # 多模态输入不走直复节点——直接回复模板没有图片处理能力
        if _last_human_has_image(state.get("messages", [])):
            logger.warning(
                f"[route_by_intent] Multimodal message detected with action=direct_reply; "
                f"redirecting to 'general' for vision processing | tenant={state.get('tenant_id')}"
            )
            return "general"
        # 如果有 pending skill，不执行 direct_reply，继续走 skill 流程
        if pending_skill:
            logger.info(
                f"[route_by_intent] Pending interact skill '{pending_skill}' overrides direct_reply"
            )
            return pending_skill
        return "direct_reply"

    intent = (state.get("intent_result") or {}).get("intent", "general")

    if pending_skill:
        # 会话连续性：用户回应了交互组件
        # 只有在高置信度命中不同意图时才跳出当前 skill
        intended_route = _INTENT_TO_ROUTE.get(intent, "general")
        confidence = (state.get("intent_result") or {}).get("confidence", 0)
        if intended_route != pending_skill and confidence >= 0.9:
            logger.info(
                f"[route_by_intent] High-confidence intent switch: "
                f"{pending_skill} → {intended_route} (intent={intent} confidence={confidence})"
            )
            return intended_route
        logger.info(
            f"[route_by_intent] Session continuity: staying in '{pending_skill}' "
            f"(intent={intent} confidence={confidence})"
        )
        return pending_skill

    return _INTENT_TO_ROUTE.get(intent, "general")
