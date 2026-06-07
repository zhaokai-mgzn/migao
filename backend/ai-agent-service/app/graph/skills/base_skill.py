"""
Skill 基础执行逻辑

提供通用的 Skill 执行函数，避免各 Skill 节点重复代码。
核心流程：
1. 从 AgentState 构建 ToolContext 并注入 contextvars
2. 创建 LLM + bind_tools
3. 循环执行 Tool Calling 直到 LLM 返回最终回复
4. 从 Tool 结果中提取实体
5. 返回更新后的 state 字段

性能优化策略：
- 策略 1: 收窄 _THINKING_INTENTS 范围，product_inquiry 等不需要工具调用的意图关闭 thinking
- 策略 2: 首轮开 thinking（规划工具调用），迭代 2+ 轮关闭（仅格式化结果），节省 5-8s/轮
- 策略 3: 后续轮可降级到轻量模型（待实现，需评估质量影响）
"""

import asyncio
import json
import re
import traceback
from typing import List, Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
from loguru import logger

from app.config import settings
from app.graph.state import AgentState
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry, set_tool_context, get_tool_context
from app.context.tracker import ConversationTracker
from app.core import (
    CircuitBreakerOpenError,
    LLM_FALLBACK_MESSAGE,
    get_breaker,
)
from app.llm import LLMFactory, select_model, has_images, call_with_retry, cost_tracker


# LLM 熔断器名（百炼调用路径共用）
LLM_BREAKER = "llm_dashscope"


# 全局 ConversationTracker 实例（进程内共享）
_tracker: Optional[ConversationTracker] = None


def get_tracker() -> ConversationTracker:
    """获取全局 ConversationTracker 实例"""
    global _tracker
    if _tracker is None:
        _tracker = ConversationTracker()
    return _tracker


def _strip_think_tags(text: str) -> str:
    """移除 Qwen3 思考模式的 <think>...</think> 标签及其内容"""
    if not text:
        return text
    # 移除 <think>...</think> 块（含跨行）
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    return cleaned if cleaned else text


def _extract_content(response: AIMessage) -> str:
    """从 AIMessage 中提取有效文本内容

    兼容 Qwen3 思考模式：
    1. 优先取 response.content 并移除 <think> 标签
    2. 若 stripped 结果仍含 <think> 标签（仅 thinking 内容），提取内部文本
    3. 再 fallback 到 additional_kwargs 中的 reasoning_content
    4. 仍为空则返回原始 content（保留 think 标签，确保有文字输出）
    """
    content = response.content or ""
    if isinstance(content, list):
        # 多模态返回：提取文本部分
        text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        content = "".join(text_parts)

    stripped = _strip_think_tags(content)

    # _strip_think_tags 在 stripping 结果为空时回退到原文本（含标签）。
    # 二次检测：如果 stripped 仍含标签，说明只有 thinking 内容，需提取其内部文本。
    if stripped:
        if "<think>" in stripped:
            # thinking-only 情况：提取标签内的思考文本，不暴露给用户
            think_match = re.search(r"<think>([\s\S]*?)</think>", stripped, re.DOTALL)
            if think_match:
                fallback = think_match.group(1).strip()
                if fallback:
                    logger.warning(
                        "[_extract_content] Only thinking content found, using thinking text as fallback"
                    )
                    return fallback
            # 提取失败，至少返回带标签的原文总比空好
            return stripped
        return stripped

    # Fallback: 某些 Qwen3 模型将回复放在 additional_kwargs
    extra = getattr(response, "additional_kwargs", {}) or {}
    if extra.get("reasoning_content"):
        logger.warning(
            "[_extract_content] No main content, falling back to reasoning_content from additional_kwargs"
        )
        return extra["reasoning_content"]

    # 终极兜底：返回原始 content（保留 think 标签也不如让用户看到思考过程）
    if content:
        logger.info(
            f"[_extract_content] Returning original content (preserve thinking tags)"
        )
        return content

    return content


# 需要深度思考的意图（仅保留真正需要多步推理的场景）
# - 涉及复杂业务逻辑判断（售后政策、投诉处理）
# - 需要规划多步骤操作（创建工单、管理人员）
# - product_inquiry 不需要：直接回答产品信息，不调工具
# - order_query/logistics_track：仅首轮需要思考（决定调什么工具），后续轮关闭
_THINKING_INTENTS = frozenset({
    "after_sales",
    "after_sales_create",
    "complaint",
    "category_manage",
    "processing_manage",
    "customer_manage",
    "employee_manage",
    "staff_manage",
})


def get_skill_llm(
    intent: str = "",
    tool_count: int = 0,
    text_length: int = 0,
    messages: Optional[List[Any]] = None,
    enable_thinking: Optional[bool] = None,
) -> ChatOpenAI:
    """创建 Skill 专用 LLM 实例（统一走 LLMFactory + Router，支持多模态自动检测）

    - LLM_ENABLE_MODEL_ROUTING=False（默认）：使用 settings.DASHSCOPE_MODEL，行为与原一致
    - LLM_ENABLE_MODEL_ROUTING=True：根据 intent / tool_count / text_length 动态选型
    - 若 messages 中含图片且 启用视觉路由，则返回视觉 LLM（不启用 thinking 模式）
    - 深度思考（enable_thinking）仅对复杂意图开启，简单意图（问候/FAQ/闲聊）关闭以提升响应速度
    - enable_thinking 参数可显式覆盖自动判定（用于迭代 2+ 轮关闭思考）

    Args:
        enable_thinking: 显式指定是否启用思考模式。None 表示根据意图自动判定。
    """
    vision_detected = has_images(messages) if messages else False

    model = select_model(
        intent=intent,
        tool_count=tool_count,
        text_length=text_length,
        has_vision=vision_detected,
    )

    # 根据模型类型选择工厂方法
    # 注意：不能用 "vl" in model 判断，非视觉专用模型也支持视觉理解
    # 正确做法：由 vision_detected（消息含图片）+ DASHSCOPE_VISION_ENABLED（功能开关）决定
    if vision_detected and settings.DASHSCOPE_VISION_ENABLED:
        return LLMFactory.create_vision_llm(model_override=model)

    # 复杂意图开启深度思考，简单意图关闭（首次响应从 7-15s 降到 1-3s）
    # 允许外部显式覆盖（用于迭代 2+ 轮关闭思考）
    if enable_thinking is None:
        enable_thinking = intent in _THINKING_INTENTS
    return LLMFactory.create_skill_llm(
        model_override=model,
        enable_thinking=enable_thinking,
    )


def _extract_usage(response: AIMessage) -> Optional[tuple[int, int]]:
    """从 AIMessage 中提取 (input_tokens, output_tokens)。取不到返回 None。

    兼容 LangChain 不同版本的 usage 位置：
    - response.usage_metadata: {input_tokens, output_tokens, total_tokens}
    - response.response_metadata.token_usage: {prompt_tokens, completion_tokens}
    """
    try:
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
            output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
            if input_tokens or output_tokens:
                return input_tokens, output_tokens

        resp_meta = getattr(response, "response_metadata", None) or {}
        token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
        input_tokens = int(
            token_usage.get("prompt_tokens")
            or token_usage.get("input_tokens")
            or 0
        )
        output_tokens = int(
            token_usage.get("completion_tokens")
            or token_usage.get("output_tokens")
            or 0
        )
        if input_tokens or output_tokens:
            return input_tokens, output_tokens
    except Exception as exc:
        logger.debug(f"[_extract_usage] failed to extract usage: {exc}")
    return None


def _track_llm_cost(
    response: AIMessage,
    model: str,
    tenant_id: Optional[int],
    session_id: str,
) -> None:
    """安全调用 cost_tracker.track_call，任何异常仅 warning 不影响主流程。"""
    try:
        usage = _extract_usage(response)
        if usage is None:
            return
        input_tokens, output_tokens = usage
        cost_tracker.track_call(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tenant_id=tenant_id,
            session_id=session_id or None,
        )
    except Exception as exc:
        logger.warning(f"[base_skill] cost tracking failed: {exc}")


def build_tool_context(state: AgentState) -> ToolContext:
    """从 AgentState 构建 ToolContext"""
    return ToolContext(
        tenant_id=state["tenant_id"],
        user_id=str(state["user_id"]),
        session_id=state.get("session_id", ""),
        role=state.get("role", "customer"),
    )


def create_skill_registry(tool_names: List[str]) -> ToolRegistry:
    """创建仅包含指定 Tool 的 Registry 子集

    从全局单例 ToolRegistry 中引用 Tool 实例（不重复创建），
    避免每次 Skill 执行都实例化全部 21 个 Tool。

    Args:
        tool_names: 需要的 Tool 名称列表

    Returns:
        ToolRegistry: 包含指定 Tool 子集的注册器
    """
    from app.tools.registry import get_tool_registry

    full_registry = get_tool_registry()
    skill_registry = ToolRegistry()

    for name in tool_names:
        tool = full_registry.get_tool(name)
        if tool:
            skill_registry.register(tool)
        else:
            logger.warning(f"[base_skill] Tool '{name}' not found in global registry")

    return skill_registry


def _sanitize_messages_for_text_path(messages):
    """清理历史消息中的 image_url 内容块，避免文本模型收到无法处理的多模态内容。

    has_images() 只查最后一条 HumanMessage（Issue #204），但当用户先发图片消息、
    再发纯文本跟进时，历史中仍存在 image_url。纯文本模型不支持多模态 content 格式
    content list 中的 image_url → DashScope BadRequestError。

    处理策略：
    - 混合内容 (text + image_url): 保留 text，丢弃 image_url
    - 纯 image_url (无 text): 转为占位符 "[图片]"
    - 纯文本: 原样保留
    - 非 HumanMessage: 原样保留
    """
    from langchain_core.messages import HumanMessage

    sanitized = []
    for msg in messages:
        if not isinstance(msg, HumanMessage) or not isinstance(msg.content, list):
            sanitized.append(msg)
            continue

        # 从混合 content list 中提取文本
        text_parts = []
        for item in msg.content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                # image_url / image / 其他非 text 类型 → 丢弃

        if text_parts:
            sanitized.append(HumanMessage(content=" ".join(text_parts)))
        else:
            # 纯图片无文字 → 占位符保留消息存在的事实
            sanitized.append(HumanMessage(content="[图片]"))

    return sanitized


async def execute_skill(
    state: AgentState,
    skill_name: str,
    tool_names: List[str],
    system_prompt: str,
    max_iterations: int = 5,
) -> dict:
    """通用 Skill 执行逻辑

    Args:
        state: 当前图状态
        skill_name: Skill 名称（用于日志和 state 更新）
        tool_names: 该 Skill 可用的 Tool 名称列表
        system_prompt: 该 Skill 的专用 System Prompt
        max_iterations: 最大 Tool Calling 迭代次数

    Returns:
        dict: 需要更新的 state 字段
    """
    raw_messages = state["messages"]
    session_id = state.get("session_id", "")
    is_multimodal = has_images(raw_messages)

    # ── Plan-and-Execute 路径 ──
    from app.graph.plan_executor import execute_plan, should_use_plan_execute, _load_plan

    existing_plan = await _load_plan(session_id) if session_id else None
    # 有 Plan 时确保使用 Plan 所属 skill 的 tools，防止意图路由错误
    if existing_plan and existing_plan.skill_name and existing_plan.skill_name != skill_name:
        from app.graph.skills.skill_registry import get_skill_registry
        cfg = get_skill_registry().get(existing_plan.skill_name)
        if cfg:
            logger.warning(f"[{skill_name}] Plan redirect: {skill_name} → {existing_plan.skill_name}")
            skill_name = existing_plan.skill_name
            tool_names = cfg.tool_names
    if existing_plan is not None or should_use_plan_execute(state, skill_name):
        # 图片消息：先做 Vision 分析，否则 P&E 步骤看不到图片内容
        if is_multimodal and not existing_plan:
            vision_llm = get_skill_llm(intent="", tool_count=0, text_length=0,
                                        messages=raw_messages, enable_thinking=False)
            try:
                vision_response = await vision_llm.ainvoke(raw_messages)
                vision_text = _extract_content(vision_response) or ""
                if vision_text:
                    # 从 Vision 分析中提取结构化商品数据
                    from app.llm import LLMFactory
                    extract_prompt = (
                        f"从以下图片分析结果中提取商品关键信息，返回纯 JSON。\n\n"
                        f"图片分析: {vision_text}\n\n"
                        f"提取字段:\n"
                        f"- name: 商品名称\n"
                        f"- description: 详细描述（包含系列、用途、面料特点等）\n"
                        f"- brand: 品牌\n"
                        f"- specifications: 商品属性字典，key 可以是:\n"
                        f"  材质(material), 克重(weight), 风格(style), 工艺(craft),\n"
                        f"  图案(pattern), 功能(function), 遮光率, 色牢度等\n"
                        f"  根据图片内容提取所有可见属性，如 {{\"材质\":\"涤纶\",\"风格\":\"现代简约\",\"克重\":\"300g/m²\"}}\n"
                        f"- colors: 颜色/色号列表，每个包含 colorName（如'2699-01 象牙白'）\n"
                        f"- pricing_type: 计价方式，布料类 per_meter，配件类 per_piece\n"
                        f"- unit: 计价单位，布料类'米'，配件类'个'/'套'\n\n"
                        f"示例: {{\"name\":\"遮光窗帘\",\"description\":\"...\","
                        f"\"brand\":\"HOME YUUR\","
                        f"\"specifications\":{{\"材质\":\"涤纶\",\"风格\":\"现代简约\"}},"
                        f"\"colors\":[{{\"colorName\":\"2699-01\"}}],"
                        f"\"pricing_type\":\"per_meter\",\"unit\":\"米\"}}"
                    )
                    try:
                        raw = await LLMFactory.invoke_text_safe(
                            [HumanMessage(content=extract_prompt)], enable_thinking=False
                        )
                        extracted = json.loads(raw.strip().lstrip("```json").rstrip("```").strip())
                    except Exception:
                        extracted = {}
                    # 注入图片 URL，后续传给 product_manage
                    img_urls = []
                    for msg in raw_messages:
                        if hasattr(msg, 'content') and isinstance(msg.content, list):
                            for item in msg.content:
                                if isinstance(item, dict) and item.get("type") == "image_url":
                                    url = item.get("image_url", {}).get("url", "")
                                    if url:
                                        img_urls.append(url)
                    extracted["_images"] = img_urls
                    # 将结构化数据注入 state
                    state = dict(state)
                    msgs = list(state.get("messages", []))
                    ctx_msg = (
                        f"[图片分析结果]\n{vision_text}\n\n"
                        f"[结构化数据]\n{json.dumps(extracted, ensure_ascii=False)}\n\n"
                        f"请基于以上信息执行操作。"
                    )
                    msgs.append(SystemMessage(content=ctx_msg))
                    state["messages"] = msgs
                    logger.info(f"[{skill_name}] Vision analysis for P&E | len={len(vision_text)} fields={list(extracted.keys())}")
            except Exception as e:
                logger.warning(f"[{skill_name}] Vision analysis for P&E failed: {e}")

        logger.info(f"[{skill_name}] Trying P&E mode | has_plan={existing_plan is not None}")
        pe_result = await execute_plan(state, skill_name, tool_names, system_prompt)
        if pe_result is not None:
            return pe_result
        logger.info(f"[{skill_name}] P&E fallback to ReAct")

    # 1. 构建并注入 ToolContext
    tool_context = build_tool_context(state)
    set_tool_context(tool_context)

    # 2. 创建 Skill 的 Tool Registry 子集
    skill_registry = create_skill_registry(tool_names)
    langchain_tools = skill_registry.get_langchain_tools()

    # 3. 创建 LLM 并绑定 Tools
    #    计算 text_length 以供路由判定（启用 LLM_ENABLE_MODEL_ROUTING 后生效）
    messages = state["messages"]
    is_multimodal = has_images(messages)

    # 文本路径：清理历史消息中的 image_url 内容块
    # has_images() 只查最后一条 HumanMessage，但历史消息中可能仍有 image_url，
    # 纯文本模型无法处理这类内容 → BadRequestError "Unexpected item type in content"
    if not is_multimodal:
        messages = _sanitize_messages_for_text_path(messages)
    text_length = sum(len(getattr(m, "content", "") or "") for m in messages) + len(system_prompt)
    # 从 intent_result 中提取 intent 名，用于 router 简单意图路由
    intent_result = state.get("intent_result") or {}
    intent_name = ""
    if isinstance(intent_result, dict):
        intent_value = intent_result.get("intent")
        if hasattr(intent_value, "value"):
            intent_name = intent_value.value
        elif intent_value is not None:
            intent_name = str(intent_value)

    llm = get_skill_llm(
        intent=intent_name,
        tool_count=len(langchain_tools),
        text_length=text_length,
        messages=messages,
    )
    # 记录实际使用的模型名，用于成本追踪
    llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

    # 策略 2：创建"无思考"变体，用于迭代 2+ 轮（工具结果格式化不需要深度推理）
    # 仅当首轮开了 thinking 且需要工具调用时才创建，避免浪费
    llm_no_thinking = None
    if not is_multimodal and intent_name in _THINKING_INTENTS and langchain_tools:
        # 懒加载：首轮执行后若需迭代再创建
        pass  # 在循环中按需创建

    # 多模态请求不绑定 Tools（视觉模型不支持 Tool Calling）
    if is_multimodal:
        llm_with_tools = llm
    elif langchain_tools:
        llm_with_tools = llm.bind_tools(langchain_tools)
    else:
        llm_with_tools = llm

    # 4. 构建消息列表：System Prompt + 历史 messages
    # 注入用户身份信息，让 Agent 认识当前对话的人
    user_name = state.get("user_name", "")
    user_role = state.get("role", "")
    if user_name:
        system_prompt = f"当前对话用户: {user_name}（角色: {user_role}）\n\n" + system_prompt

    # 如果消息中包含图片，注入图片理解能力说明
    if is_multimodal:
        system_prompt = (
            "【图片理解能力已启用】您可以识别和分析用户上传的图片内容。\n"
            "当用户上传图片时，请：\n"
            "1. 仔细观察图片内容，识别其中的关键信息（如商品、文字、数据等）\n"
            "2. 根据用户的提问，结合图片内容给出准确回答\n"
            "3. 如果图片中包含可操作的信息（如商品名称、订单号等），可以主动建议使用相关工具处理\n\n"
            + system_prompt
        )

    full_messages: List[Any] = [SystemMessage(content=system_prompt)] + list(messages)

    # 5. Tool Calling 循环
    tracker = get_tracker()
    session_id = state.get("session_id", "")
    final_content = ""
    new_messages: List[Any] = []
    iteration = 0
    interact_called = False  # 跟踪本轮是否调用了 interact

    # 5.a 多模态分支：Vision LLM 仅做图片识别，结果传递给主模型做 Tool Calling
    #     Vision LLM 不支持 Tool Calling，仅负责理解图片内容。
    #     图片理解完成后，清理多模态消息中的 image_url、注入图片分析上下文，
    #     然后回退到主模型 + bind_tools 的标准 Tool Calling 循环。
    vision_analysis = ""  # 提前声明，供下游条件判断使用
    if is_multimodal:
        max_vision_attempts = 2
        for vision_attempt in range(max_vision_attempts):
            try:
                logger.info(
                    f"[{skill_name}][DIAG] Vision LLM call starting | "
                    f"model={llm_model_name} msg_count={len(full_messages)} "
                    f"attempt={vision_attempt + 1}/{max_vision_attempts} "
                    f"tenant={state['tenant_id']} session={session_id}"
                )
                llm_breaker = get_breaker(LLM_BREAKER)

                async def _vision_invoke():
                    return await asyncio.wait_for(
                        llm.ainvoke(full_messages),
                        timeout=60.0,
                    )

                response: AIMessage = await call_with_retry(
                    lambda: llm_breaker.call(_vision_invoke)
                )
                _track_llm_cost(
                    response,
                    model=llm_model_name,
                    tenant_id=state.get("tenant_id"),
                    session_id=session_id,
                )

                vision_analysis = _extract_content(response) or (
                    response.content if isinstance(response.content, str) else str(response.content)
                )
                # Vision LLM 的 AIMessage 不加入对话历史（分析结果通过 vision_context SystemMessage 注入）
                # 避免文本 LLM 看到 Assistant 已"回复"了图片分析，造成语义冲突
                logger.info(
                    f"[{skill_name}] Vision LLM completed | analysis_len={len(vision_analysis)}"
                )

                # 空响应重试（最后一次不再重试）
                if not vision_analysis and vision_attempt < max_vision_attempts - 1:
                    logger.warning(
                        f"[{skill_name}] Vision LLM returned empty content, "
                        f"retrying ({vision_attempt + 1}/{max_vision_attempts}) | "
                        f"tenant={state['tenant_id']} session={session_id}"
                    )
                    continue
                break
            except CircuitBreakerOpenError:
                logger.error(
                    f"[{skill_name}][SLS] Vision LLM circuit_breaker_open | "
                    f"tenant={state['tenant_id']} session={session_id}"
                )
                vision_analysis = ""
                break
            except Exception as e:
                logger.error(f"[{skill_name}] Vision LLM call failed: {e}")
                vision_analysis = ""
                break

        if not vision_analysis:
            # Vision LLM 完全失败：返回友好提示，不进入 Tool Calling
            logger.error(
                f"[{skill_name}] Vision LLM failed, no analysis available | "
                f"tenant={state['tenant_id']} session={session_id}"
            )
            final_content = "抱歉，图片分析暂时无法完成，请用文字描述您的需求，我会帮您处理。"
        else:
            # Vision 成功 → 图片理解结果注入上下文，切换到主模型 + Tool Calling
            vision_context = (
                f"[图片分析结果]\n"
                f"用户上传了图片，以下是图片中识别到的信息：\n"
                f"{vision_analysis}\n"
                f"请严格基于以上分析结果和用户的原始问题，使用可用工具完成操作。"
                f"不要编造图片中没有的信息。"
            )

            # 清理历史消息中的 image_url，替换为纯文本（主模型不支持多模态 content list）
            messages = _sanitize_messages_for_text_path(list(messages))

            # 重建消息列表，注入图片分析上下文
            system_msg = SystemMessage(content=system_prompt)
            full_messages = [system_msg] + messages
            full_messages.append(SystemMessage(content=vision_context))

            # 重新计算 text_length（含 vision_context），确保模型路由准确
            text_length = (
                sum(len(getattr(m, "content", "") or "") for m in messages)
                + len(system_prompt)
                + len(vision_context)
            )

            # 重建文本 LLM 并绑定 Tools
            llm = get_skill_llm(
                intent=intent_name,
                tool_count=len(langchain_tools),
                text_length=text_length,
                messages=messages,
                enable_thinking=True,  # 开启思考：图片理解后的操作需要推理
            )
            llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

            # 创建"无思考"变体（迭代 2+ 轮使用）
            llm_no_thinking = None

            if langchain_tools:
                llm_with_tools = llm.bind_tools(langchain_tools)
            else:
                llm_with_tools = llm

            logger.info(
                f"[{skill_name}] Multimodal→Text fallback | "
                f"text_model={llm_model_name} tools={len(langchain_tools)} "
                f"tenant={state['tenant_id']} session={session_id}"
            )

    # 5.b Tool Calling 循环（纯文本 Skill 或 图片理解后的主模型处理）
    if not is_multimodal or (is_multimodal and vision_analysis):
        # 如果多模态分支已经设置了 final_content（Vision 失败），跳过循环
        if is_multimodal and not vision_analysis:
            pass  # 已在上面设置了 final_content = 错误提示
        else:
            for iteration in range(max_iterations):
                logger.info(
                    f"[{skill_name}] Iteration {iteration + 1}/{max_iterations} | "
                    f"tenant={state['tenant_id']} session={session_id}"
                )

                # 策略 2：首轮开 thinking（规划工具调用），后续轮关闭（仅格式化结果）
                # 节省 5-8s/轮，质量无损（实测：8.0s → 2.7s）
                if iteration > 0 and intent_name in _THINKING_INTENTS:
                    if llm_no_thinking is None:
                        llm_no_thinking = get_skill_llm(
                            intent=intent_name,
                            tool_count=len(langchain_tools),
                            text_length=text_length,
                            messages=messages,
                            enable_thinking=False,  # 显式关闭
                        )
                        if langchain_tools:
                            llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)
                        logger.debug(
                            f"[{skill_name}][DIAG] Created no-thinking LLM for iter {iteration + 1}+"
                        )
                    # 切换到无思考变体
                    current_llm = llm_no_thinking
                else:
                    current_llm = llm_with_tools

                # 调用 LLM（带超时 + 熔断保护）
                try:
                    logger.info(
                        f"[{skill_name}][DIAG] LLM call starting | "
                        f"iteration={iteration + 1} msg_count={len(full_messages) + len(new_messages)} "
                        f"tenant={state['tenant_id']} session={session_id}"
                    )
                    llm_breaker = get_breaker(LLM_BREAKER)

                    async def _llm_invoke():
                        return await asyncio.wait_for(
                            current_llm.ainvoke(full_messages + new_messages),
                            timeout=60.0,
                        )

                    # retry 包在 breaker 外层：对整个含熔断的调用进行可重试判定
                    response: AIMessage = await call_with_retry(
                        lambda: llm_breaker.call(_llm_invoke)
                    )
                    logger.info(
                        f"[{skill_name}][DIAG] LLM call completed | "
                        f"has_tool_calls={bool(response.tool_calls)} "
                        f"content_len={len(response.content or '')} "
                        f"type={type(response).__name__}"
                    )
                    # 成本追踪（失败不阻塞主流程）
                    _track_llm_cost(
                        response,
                        model=llm_model_name,
                        tenant_id=state.get("tenant_id"),
                        session_id=session_id,
                    )
                except CircuitBreakerOpenError:
                    # LLM 熔断器处于 OPEN：返回友好提示，不再冲击百炼
                    logger.error(
                        f"[{skill_name}][SLS] LLM circuit_breaker_open | "
                        f"tenant={state['tenant_id']} session={session_id}"
                    )
                    final_content = LLM_FALLBACK_MESSAGE
                    break
                except asyncio.TimeoutError:
                    logger.error(
                        f"[{skill_name}][SLS] LLM call TIMEOUT after 60s | "
                        f"iteration={iteration + 1} tenant={state['tenant_id']} session={session_id}"
                    )
                    # 检查是否已熔断，熔断后用超友好的提示
                    if get_breaker(LLM_BREAKER).is_open():
                        final_content = LLM_FALLBACK_MESSAGE
                    else:
                        final_content = "抱歉，AI 响应超时，请稍后重试。"
                    break
                except Exception as e:
                    tb = traceback.format_exc()
                    logger.error(
                        f"[{skill_name}][SLS] LLM call FAILED | "
                        f"tenant={state['tenant_id']} session={session_id} "
                        f"error={type(e).__name__}: {e} | traceback={tb[:500]}"
                    )
                    # 连续失败达到阈值后熔断器已进入 OPEN，错误提示更友好
                    if get_breaker(LLM_BREAKER).is_open():
                        final_content = LLM_FALLBACK_MESSAGE
                    else:
                        final_content = "抱歉，AI 响应异常，请稍后重试。"
                    break
                new_messages.append(response)

                # 检查是否有 tool_calls
                if not response.tool_calls:
                    # 没有 tool_calls，LLM 返回了最终回复
                    final_content = _extract_content(response)
                    logger.info(
                        f"[{skill_name}] LLM final reply | "
                        f"content_len={len(final_content)} "
                        f"raw_content_len={len(response.content or '')} "
                        f"has_additional_kwargs={bool(getattr(response, 'additional_kwargs', None))}"
                    )
                    break

                # 有 tool_calls 但 LLM 可能在同一个消息中先输出了文本
                # 提取该文本作为 final_content，确保 interact 等场景下有文本展示
                text_before_tools = _extract_content(response)
                if text_before_tools and not final_content:
                    final_content = text_before_tools
                    logger.info(
                        f"[{skill_name}] Extracted text before tool_calls | len={len(text_before_tools)}"
                    )

                # 执行每个 tool_call
                interact_called = False
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_call_id = tool_call["id"]

                    logger.info(f"[{skill_name}][DIAG] Tool call: {tool_name} | args={tool_args}")

                    # 查找并执行 Tool
                    result_str = ""
                    tool_instance = skill_registry.get_tool(tool_name)
                    if tool_instance:
                        try:
                            logger.info(f"[{skill_name}][DIAG] Tool {tool_name} starting execution")
                            result = await asyncio.wait_for(
                                tool_instance.execute(tool_context, **tool_args),
                                timeout=30.0,  # 工具调用超时 30 秒
                            )
                            logger.info(f"[{skill_name}][DIAG] Tool {tool_name} completed | success={result.success}")
                            result_dict = {
                                "success": result.success,
                                "data": result.data,
                                "error": result.error,
                                "message": result.message,
                            }
                            result_str = json.dumps(result_dict, ensure_ascii=False, default=str)

                            # 从 Tool 结果提取实体
                            if session_id:
                                tracker.extract_entities_from_tool_result(
                                    session_id, tool_name, result_dict
                                )
                        except asyncio.TimeoutError:
                            logger.error(f"[{skill_name}][DIAG] Tool {tool_name} TIMEOUT after 30s | tenant={state['tenant_id']}")
                            result_str = json.dumps({
                                "success": False,
                                "error": "tool_timeout",
                                "message": f"工具 {tool_name} 执行超时",
                                "suggestion": "请简化查询条件后重试，或检查网络连接",
                            }, ensure_ascii=False)
                        except Exception as e:
                            tb = traceback.format_exc()
                            logger.error(f"[{skill_name}][DIAG] Tool {tool_name} FAILED | error={type(e).__name__}: {e} | traceback={tb[:500]}")
                            result_str = json.dumps({
                                "success": False,
                                "error": "tool_execution_failed",
                                "message": f"工具 {tool_name} 执行失败",
                                "suggestion": "请检查参数是否正确，或换用其他方式查询",
                            }, ensure_ascii=False)
                    else:
                        result_str = json.dumps({
                            "success": False,
                            "error": "tool_not_found",
                            "message": f"工具 {tool_name} 不可用",
                            "suggestion": "请用其他可用工具完成操作",
                        }, ensure_ascii=False)

                    # 添加 ToolMessage（包含 tool name，供 SSE 事件使用）
                    new_messages.append(
                        ToolMessage(content=result_str, tool_call_id=tool_call_id, name=tool_name)
                    )

                    # interact 成功后停止迭代，等待用户操作
                    # 防止 LLM 在一个 turn 内发送多个交互组件互相覆盖
                    if tool_name == "interact" and result_dict.get("success"):
                        logger.info(f"[{skill_name}] interact {result.data.get('component', '')} succeeded, breaking to wait for user")
                        interact_called = True
                        break

                # interact 成功后跳出外层迭代循环
                if interact_called:
                    break
            else:
                # 达到最大迭代次数，取最后一条 AI 消息内容
                if new_messages:
                    last_ai = [m for m in new_messages if isinstance(m, AIMessage)]
                    if last_ai:
                        extracted = _extract_content(last_ai[-1])
                        final_content = extracted or "抱歉，处理超时，请稍后重试。"

    # 6. 更新实体
    entities = {}
    if session_id:
        extracted = tracker.get_entities(session_id)
        entities = {
            "order_nos": extracted.order_nos,
            "phone_numbers": extracted.phone_numbers,
            "product_names": extracted.product_names,
            "product_ids": extracted.product_ids,
            "amounts": extracted.amounts,
        }

    # 7. 兜底：如果所有迭代后仍无内容，记录警告
    if not final_content:
        logger.warning(
            f"[{skill_name}] Empty final_content after all iterations | "
            f"tenant={state['tenant_id']} session={session_id} "
            f"iterations={min(iteration + 1, max_iterations) if 'iteration' in dir() else 0} "
            f"new_messages_count={len(new_messages)}"
        )

    # 8. 返回 state 更新
    result: dict[str, Any] = {
        "messages": new_messages,
        "final_answer": final_content,
        "skill_used": skill_name,
        "entities": entities,
    }
    return result
