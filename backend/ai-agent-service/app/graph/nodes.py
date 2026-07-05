"""
辅助节点函数

包含 StateGraph 中除 Skill 节点以外的辅助节点：
- intent_router_node: 意图路由
- direct_reply_node: 直接回复（greeting 等）
- suggestions_node: 后续问题建议
- cache_check_node: 语义缓存检查
- cache_store_node: 缓存写入
- check_cache_hit: 缓存命中判断
- route_by_intent: 意图→Skill 路由
- _get_last_human_text: 提取最后一条用户消息文本
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


async def intent_router_node(state: AgentState) -> dict:
    """执行意图路由

    P&E Plan 存在时跳过意图分类，直接返回合成结果（意图重写），
    节省 LLM 调用且防止短文本（如"1"、"确认"）被误分类。
    """
    pending_skill = state.get("pending_interact_skill", "")
    session_id = state.get("session_id", "")
    if pending_skill:
        # 意图重写：P&E 进行中，直接用 plan 的 skill 覆盖意图
        # 映射 pending_skill → 对应的 intent，让 route_by_intent 正确路由
        _SKILL_TO_INTENT = {
            "product": "product_inquiry",
            "order": "order_query",
            "aftersales": "after_sales",
            "customer": "customer_query",
            "staff": "employee_manage",
            "settings": "system_settings",
            "data": "dashboard",
            "general": "general",
        }
        synthetic_intent = _SKILL_TO_INTENT.get(pending_skill, "general")
        logger.info(
            f"[intent_router] Intent rewrite: pending_skill={pending_skill} → intent={synthetic_intent}"
            f" | session={session_id}"
        )
        return {
            "intent_result": {
                "intent": synthetic_intent,
                "confidence": 0.99,
                "source": "plan_rewrite",
            },
            "route_decision": {"action": "full_agent"},
        }

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

    session_id = state.get("session_id", "")
    logger.info(
        f"[intent_router] LLM classified | intent={route_decision.intent_result.intent.value}"
        f" confidence={route_decision.intent_result.confidence:.2f}"
        f" action={route_decision.action}"
        f" | session={session_id}"
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


async def suggestions_node(state: AgentState) -> dict:
    """生成后续问题建议（Stage + 用户画像 + 实体感知）"""
    # 优化: P&E 等待用户输入时跳过建议（ask/confirm 步骤已有引导文案）
    pending_skill = state.get("pending_interact_skill", "")
    if pending_skill:
        return {"suggestions": []}

    from app.suggestions.follow_up import FollowUpSuggestionGenerator

    generator = FollowUpSuggestionGenerator()
    intent_type = (state.get("intent_result") or {}).get("intent", "general")
    agent_type = state.get("agent_type", "mibao")

    # 推断对话阶段
    stage = _infer_stage(state, intent_type)

    # 提取用户画像信息
    user_role = state.get("role", "")
    user_name = state.get("user_name", "") or ""

    # 提取本轮实体（从 recent_entities list，fallback 到 entities dict）
    entities = state.get("recent_entities", [])
    if not entities:
        # fallback: 从 entities dict 构建实体列表
        # 注意展开 list 值（如 {"order_nos": ["ORD001","ORD002"]} → 每个元素一个实体）
        entities_dict = state.get("entities", {})
        if entities_dict:
            for k, v_list in entities_dict.items():
                if not v_list:
                    continue
                items = v_list if isinstance(v_list, list) else [v_list]
                for item in items:
                    entities.append({
                        "type": k,
                        "value": str(item),
                        "label": str(item)[:30],
                    })

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
                chat_history=state.get("messages", []),
                stage=stage,
                session_id=state.get("session_id", ""),
                tenant_id=state.get("tenant_id", 0),
                user_id=state.get("user_id", 0),
                user_role=user_role,
                user_name=user_name,
                entities=entities if entities else None,
            ),
            timeout=15.0,
        )
        # 更新 state 中的 stage
        return {"suggestions": suggestions, "stage": stage}
    except asyncio.TimeoutError:
        logger.debug("Suggestions generation timed out, using empty list")
        return {"suggestions": [], "stage": stage}
    except Exception as e:
        logger.warning(f"Suggestions generation failed: {e}")
        return {"suggestions": [], "stage": stage}


def _infer_stage(state: AgentState, intent_type: str = "") -> str:
    """根据本轮对话状态推断对话阶段

    用于建议生成时感知对话进展，输出更贴合上下文的后续问题。
    """
    # P&E 等待用户输入 → confirming
    if state.get("pending_interact_skill"):
        return "confirming"

    # 直接回复意图（问候/再见/能力说明）
    # 注意: action 在 route_decision 中，不在 intent_result 中
    route_decision = state.get("route_decision") or {}
    action = route_decision.get("action", "")
    if action == "direct_reply":
        if intent_type == "greeting":
            return "initial"
        if intent_type == "farewell":
            return "completed"
        return "initial"

    # AI 已给出实质性回复 → querying（用户已获得信息，可深入）
    final_answer = state.get("final_answer", "")
    if len(final_answer) > 30:
        return "querying"

    # 其他情况保持当前 stage 或默认为 initial
    return state.get("stage", "initial")


# ────────────────────── 条件边路由函数（同步）──────────────────────


# 特殊意图 → direct_reply（不属于任何 skill，直接回复）
_DIRECT_REPLY_INTENTS = {"greeting", "farewell", "capabilities"}

# RAG 禁用期间知识库意图 fallback 到 general（仅 mibao，其 knowledge skill 已禁用）
_KNOWLEDGE_FALLBACK = {"knowledge_faq": "general", "knowledge_manage": "general"}


def _get_intent_to_route(agent_type: str = "") -> dict[str, str]:
    """意图→路由key映射。从 skill_registry 动态构建,避免硬编码不同步。"""
    from app.graph.skills.skill_registry import get_skill_registry
    intent_map = get_skill_registry().get_intent_to_route_map()
    for intent in _DIRECT_REPLY_INTENTS:
        intent_map[intent] = "direct_reply"
    intent_map["general"] = "general"
    # knowledge fallback 仅对 mibao 生效（其 knowledge skill 已禁用）；
    # xiaobu 的 customer_knowledge_skill 保留知识库路由
    if agent_type == "mibao":
        intent_map.update(_KNOWLEDGE_FALLBACK)
    return intent_map


# 懒加载缓存（按 agent_type 分桶，因为不同 agent 的 fallback 不同）
_INTENT_TO_ROUTE: dict[str, dict[str, str]] = {}


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


def _get_last_human_text(messages: list) -> str | None:
    """获取最后一条 HumanMessage 的纯文本内容"""
    from langchain_core.messages import HumanMessage

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return " ".join(texts) if texts else None
    return None


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
    session_id = state.get("session_id", "")
    route = state.get("route_decision") or {}
    action = route.get("action", "full_agent")

    if action == "direct_reply":
        # 多模态输入不走直复节点——直接回复模板没有图片处理能力
        if _last_human_has_image(state.get("messages", [])):
            logger.warning(
                f"[route_by_intent] Multimodal message detected with action=direct_reply; "
                f"redirecting to 'general' for vision processing | tenant={state.get('tenant_id')} session={session_id}"
            )
            return "general"
        # 如果有 pending skill，不执行 direct_reply，继续走 skill 流程
        if pending_skill:
            logger.info(
                f"[route_by_intent] Pending interact skill '{pending_skill}' overrides direct_reply"
                f" | session={session_id}"
            )
            return pending_skill
        logger.info(f"[route_by_intent] Direct reply, no pending skill | session={session_id}")
        return "direct_reply"

    intent = (state.get("intent_result") or {}).get("intent", "general")

    if pending_skill:
        # 会话连续性：用户回应了交互组件（form/choice/confirm）
        # 铁律：pending skill 存在时必须回到原 skill，不允许任何意图覆盖
        # 原因：用户点击交互组件发送的值（如 UUID、简短确认文本）可能被意图分类器误判，
        # 导致对话跳到无关 skill 而中断创建/管理流程
        #
        # 例外（escape hatch）：用户输入长度 > 10 字符且不为纯数字/UUID，
        # 视为明确的话题切换意图，允许路由到新 skill
        last_msg = _get_last_human_text(state.get("messages", []))
        is_short_interact = (
            not last_msg
            or len(last_msg) <= 10
            or last_msg.replace("-", "").replace("_", "").isalnum()  # UUID/纯数字
        )
        if is_short_interact:
            logger.info(
                f"[route_by_intent] Session continuity: staying in '{pending_skill}' "
                f"(intent={intent}, msg_len={len(last_msg or '')}) | session={session_id}"
            )
            return pending_skill
        else:
            logger.info(
                f"[route_by_intent] Escape hatch: user message length={len(last_msg)} "
                f"suggests topic switch, routing to intent '{intent}' | session={session_id}"
            )
            # 清除 pending_skill 避免后续轮次继续锁死
            state["pending_interact_skill"] = ""

    logger.info(
        f"[route_by_intent] Routing to '{intent}' "
        f"(pending_skill={pending_skill or 'none'}, action={action}) | session={session_id}"
    )

    global _INTENT_TO_ROUTE
    agent_type = state.get("agent_type", "")
    if agent_type not in _INTENT_TO_ROUTE:
        _INTENT_TO_ROUTE[agent_type] = _get_intent_to_route(agent_type)
    return _INTENT_TO_ROUTE[agent_type].get(intent, "general")
