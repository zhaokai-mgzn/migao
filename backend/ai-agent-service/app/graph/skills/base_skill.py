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
    2. 若为空，检查 additional_kwargs 中的 reasoning_content（部分模型使用）
    3. 最终兜底返回空字符串
    """
    content = response.content or ""
    if isinstance(content, list):
        # 多模态返回：提取文本部分
        text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        content = "".join(text_parts)
    content = _strip_think_tags(content)
    if content:
        return content

    # Fallback: 某些 Qwen3 模型将回复放在 additional_kwargs
    extra = getattr(response, "additional_kwargs", {}) or {}
    if extra.get("reasoning_content") and not content:
        logger.warning("[_extract_content] Only reasoning_content found, no main content")
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
    if vision_detected and "vl" in model:
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

    # 5.a 多模态分支：直接调用视觉 LLM，不进入 Tool Calling 循环
    if is_multimodal:
        try:
            logger.info(
                f"[{skill_name}][DIAG] Vision LLM call starting | "
                f"model={llm_model_name} msg_count={len(full_messages)} "
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

            final_content = _extract_content(response) or (
                response.content if isinstance(response.content, str) else str(response.content)
            )
            new_messages.append(response)
            logger.info(
                f"[{skill_name}] Vision request completed | content_len={len(final_content)}"
            )
        except CircuitBreakerOpenError:
            logger.error(
                f"[{skill_name}][SLS] Vision LLM circuit_breaker_open | "
                f"tenant={state['tenant_id']} session={session_id}"
            )
            final_content = LLM_FALLBACK_MESSAGE
        except Exception as e:
            logger.error(f"[{skill_name}] Vision LLM call failed: {e}")
            final_content = "抱歉，图片分析暂时无法完成，请稍后重试。"
    else:
        # 5.b 文本分支：Tool Calling 循环
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

            # 执行每个 tool_call
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
                        result_str = json.dumps(
                            {"success": False, "error": "tool_timeout", "message": f"工具 {tool_name} 执行超时，请稍后重试"},
                            ensure_ascii=False,
                        )
                    except Exception as e:
                        tb = traceback.format_exc()
                        logger.error(f"[{skill_name}][DIAG] Tool {tool_name} FAILED | error={type(e).__name__}: {e} | traceback={tb[:500]}")
                        result_str = json.dumps(
                            {"success": False, "error": "tool_execution_failed", "message": "工具执行失败，请稍后重试"},
                            ensure_ascii=False,
                        )
                else:
                    result_str = json.dumps(
                        {"success": False, "error": "tool_not_found", "message": f"工具 {tool_name} 不可用"},
                        ensure_ascii=False,
                    )

                # 添加 ToolMessage（包含 tool name，供 SSE 事件使用）
                new_messages.append(
                    ToolMessage(content=result_str, tool_call_id=tool_call_id, name=tool_name)
                )
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
    return {
        "messages": new_messages,
        "final_answer": final_content,
        "skill_used": skill_name,
        "entities": entities,
    }
