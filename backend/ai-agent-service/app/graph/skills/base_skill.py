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
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Awaitable, List, Any, Optional

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


# LLM 熔断器名
LLM_BREAKER = "llm_minimax"


# 全局 ConversationTracker 实例（进程内共享）
_tracker: Optional[ConversationTracker] = None


def get_tracker() -> ConversationTracker:
    """获取全局 ConversationTracker 实例"""
    global _tracker
    if _tracker is None:
        _tracker = ConversationTracker()
    return _tracker


def _strip_think_tags(text: str) -> str:
    """移除 <think>...</think> 标签及其内容"""
    if not text:
        return text
    # 移除 <think>...</think> 块（含跨行）
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    return cleaned if cleaned else text


def _extract_content(response: AIMessage) -> str:
    """从 AIMessage 中提取有效文本内容

    兼容 MiniMax 思考模式：
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

    # Fallback: 某些模型将回复放在 additional_kwargs 或 response_metadata
    extra = getattr(response, "additional_kwargs", {}) or {}
    resp_meta = getattr(response, "response_metadata", {}) or {}
    reasoning = extra.get("reasoning_content") or resp_meta.get("reasoning_content")
    if reasoning:
        logger.warning(
            "[_extract_content] No main content, falling back to reasoning_content"
        )
        return reasoning

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
# DeepSeek V4 thinking 模式：首轮开启深度思考（规划工具调用 + 图片属性推理），
# 后续轮关闭（策略2 llm_no_thinking 自动接管，仅做结果格式化）。
# 意图列表：订单/商品/售后三大核心业务域的管理操作
_THINKING_INTENTS = frozenset({
    # ── 订单域 ──
    "order_query",        # 订单查询——多条件筛选+关联上下文
    "order_create",       # 订单创建——多SKU+加工项+价格计算
    # ── 商品域 ──
    "product_inquiry",    # 商品创建——图片属性推理+分类+加工项
    # ── 售后域 ──
    "after_sales",        # 售后处理——退款/换货/维修逻辑
    "after_sales_create", # 售后创建——问题归类+解决方案推荐
    "complaint",          # 投诉处理——情绪安抚+升级判断
})


def get_skill_llm(
    intent: str = "",
    tool_count: int = 0,
    text_length: int = 0,
    messages: Optional[List[Any]] = None,
    enable_thinking: Optional[bool] = None,
) -> ChatOpenAI:
    """创建 Skill 专用 LLM 实例（统一走 LLMFactory + Router，支持多模态自动检测）

    - LLM_ENABLE_MODEL_ROUTING=False（默认）：使用 settings.MINIMAX_MODEL，行为与原一致
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
    # 正确做法：由 vision_detected（消息含图片）+ MINIMAX_VISION_ENABLED（功能开关）决定
    if vision_detected and settings.MINIMAX_VISION_ENABLED:
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
    content list 中的 image_url → API BadRequestError。

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


# Prompt 文件缓存（启动时加载一次，避免每次请求读文件）
import os as _os
_ref_dir = _os.path.join(_os.path.dirname(__file__), "references")
_PROMPT_CACHE: dict = {}


def _read_cached(path: str) -> str:
    """读取文件内容，带缓存。文件不存在时返回 ''。"""
    if path in _PROMPT_CACHE:
        return _PROMPT_CACHE[path]
    try:
        with open(path, "r", encoding="utf-8") as f:
            _PROMPT_CACHE[path] = f.read().strip()
    except FileNotFoundError:
        _PROMPT_CACHE[path] = ""
    except Exception as e:
        logger.warning(f"Failed to load prompt file '{path}': {e}")
        _PROMPT_CACHE[path] = ""
    return _PROMPT_CACHE[path]


def _build_system_prompt(skill_name: str, inline_prompt: str = "") -> str:
    """分层组装 System Prompt

    层级（从底到顶）：
      1. base/identity.md     — 公共身份描述（所有 Skill 共享）
      2. base/principles.md   — 公共行为准则（所有 Skill 共享）
      3. prompts/{skill}.md   — 领域规则 + 工具说明（按 Skill）
      4. inline_prompt        — 调用方传入的额外指令（可选，用于覆盖/追加）
      5. EXAMPLES-{skill}.md  — few-shot 示例（按 Skill）

    所有文件均为可选，不存在时静默跳过。
    缓存到 _PROMPT_CACHE 避免每次请求读文件。

    Returns:
        组装好的完整 System Prompt 字符串
    """
    parts = []

    # Layer 1+2: 公共基础（身份 + 原则）
    identity = _read_cached(_os.path.join(_ref_dir, "base", "identity.md"))
    if identity:
        parts.append(identity)

    principles = _read_cached(_os.path.join(_ref_dir, "base", "principles.md"))
    if principles:
        parts.append(principles)

    # Layer 2.5: 共享 Prompt 规则（Certainty Tagging / P&E / Verification）
    prompt_rules = _read_cached(_os.path.join(_ref_dir, "PROMPT-rules.md"))
    if prompt_rules:
        parts.append(prompt_rules)

    # Layer 3: 领域 Prompt
    domain = _read_cached(_os.path.join(_ref_dir, "prompts", f"{skill_name}.md"))
    if domain:
        # 去掉 YAML frontmatter
        if domain.startswith("---"):
            end = domain.find("---", 3)
            if end > 0:
                domain = domain[end + 3:].strip()
        if domain:
            parts.append(domain)

    # Layer 4: 内联 Prompt（调用方传入，如 Vision 能力的动态追加）
    if inline_prompt:
        parts.append(inline_prompt)

    # Layer 5: Few-shot 示例
    examples = _read_cached(_os.path.join(_ref_dir, "EXAMPLES-" + skill_name + ".md"))
    if examples:
        parts.append("\n## Few-shot 参考示例\n\n以下是该领域的正确和错误示例，请严格遵循正确示例的行为模式：\n\n" + examples)

    return "\n\n".join(parts)


def _load_skill_examples(skill_name: str) -> str:
    """向后兼容别名 — 加载 EXAMPLES 文档（已废弃，建议用 _build_system_prompt）"""
    examples = _read_cached(_os.path.join(_ref_dir, "EXAMPLES-" + skill_name + ".md"))
    if examples:
        return "\n## Few-shot 参考示例\n\n以下是该领域的正确和错误示例，请严格遵循正确示例的行为模式：\n\n" + examples
    return ""


def _extract_intent_name(state: AgentState) -> str:
    """从 AgentState 中提取 intent 名称字符串

    兼容 intent_result 中 intent 为 Enum/str/None 等多种类型。
    """
    intent_result = state.get("intent_result") or {}
    if not isinstance(intent_result, dict):
        return ""
    intent_value = intent_result.get("intent")
    if hasattr(intent_value, "value"):
        return intent_value.value
    elif intent_value is not None:
        return str(intent_value)
    return ""


PAGE_SIZE = 10  # 加工项 choice 每页展示数量




async def _execute_tool_safe(tool, tool_args: dict, tool_context, state: dict) -> tuple:
    """统一 Tool 执行入口 — normalize + cache + execute + error handling.

    所有 tool 调用走这里，不经过 LangChain adapter 的 _execute。
    """
    from app.tools.langchain_adapter import LangChainToolAdapter

    # 1. 规范化参数：LLM 可能把 array/object 序列化为 JSON 字符串
    # 兜底：MiniMax 可能把所有参数包在 data 键下
    if "data" in tool_args and isinstance(tool_args.get("data"), dict):
        nested = tool_args["data"]
        if any(k not in tool_args for k in nested):
            logger.info(f"[tool-exec] Flattened nested data for {tool.name}: keys={list(nested.keys())[:8]}")
            tool_args = {**nested, **{k: v for k, v in tool_args.items() if k != "data"}}
    tool_args = LangChainToolAdapter._normalize_args(tool, tool_args)

    session_id = state.get("session_id", "")
    tenant_id = str(state.get("tenant_id", ""))
    tool_name = tool.name
    cache_key = f"{tenant_id}:{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"

    # 2. 缓存检查（带 asyncio.Lock 防止并发竞态）
    if not hasattr(_execute_tool_safe, '_cache'):
        _execute_tool_safe._cache = {}
        _execute_tool_safe._cache_lock = asyncio.Lock()
    async with _execute_tool_safe._cache_lock:
        if cache_key in _execute_tool_safe._cache:
            cached = _execute_tool_safe._cache[cache_key]
            if time.time() - cached["ts"] < 60:
                logger.info(f"[tool-cache] Hit {tool_name}")
                return cached["result"], cached["dict"]

    # 3. 执行 + 超时
    try:
        logger.info(f"[tool-exec] {tool_name} start")
        result = await asyncio.wait_for(
            tool.execute(tool_context, **tool_args),
            timeout=30.0,
        )
        logger.info(f"[tool-exec] {tool_name} done success={result.success}")
    except asyncio.TimeoutError:
        logger.error(f"[tool-exec] {tool_name} TIMEOUT 30s")
        err = json.dumps({"success": False, "error": "timeout", "message": "工具执行超时"}, ensure_ascii=False)
        return err, {"success": False, "error": "timeout"}
    except Exception as e:
        logger.error(f"[tool-exec] {tool_name} ERROR: {e}", exc_info=True)
        err = json.dumps({"success": False, "error": "tool_execution_failed",
                          "message": f"工具 {tool_name} 执行失败，请检查参数格式后重试"},
                         ensure_ascii=False)
        return err, {"success": False, "error": "tool_execution_failed"}

    # 4. 格式化结果
    result_dict = {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "message": result.message,
        "suggestion": getattr(result, "suggestion", None) or "",
    }
    result_str = json.dumps(result_dict, ensure_ascii=False, default=str)

    # 5. 缓存（带锁）
    if result.success:
        async with _execute_tool_safe._cache_lock:
            _execute_tool_safe._cache[cache_key] = {"result": result_str, "dict": result_dict, "ts": time.time()}
            if len(_execute_tool_safe._cache) > 100:
                _execute_tool_safe._cache.pop(next(iter(_execute_tool_safe._cache)))

    return result_str, result_dict


async def _self_correct_retry(
    tool,
    tool_args: dict,
    tool_context,
    skill_name: str,
    result_dict: dict,
    session: str,
    tenant: int,
    state: dict,
) -> tuple[str, dict] | None:
    """自修复重试：工具失败且有 suggestion 时，让 LLM 修正参数后重试。

    这是 Error-Self-Correct Skill 的核心——不依赖 LLM 在多轮对话中
    自己发现和修复，而是在工具层直接做一次自动修正。

    Returns:
        (result_str, result_dict) 如果重试成功；None 如果不需重试或重试失败。
    """
    suggestion = result_dict.get("suggestion", "")
    if not suggestion:
        return None

    error_msg = result_dict.get("message", result_dict.get("error", "执行失败"))
    logger.info(
        f"[{skill_name}][self-correct] Tool {tool.name} failed, attempting auto-correct | "
        f"error={error_msg[:80]} | session={session}"
    )

    # 构建修正提示 — 只给关键信息，不引入全量上下文
    correction_prompt = (
        f"工具 `{tool.name}` 调用失败。\n"
        f"错误：{error_msg}\n"
        f"修复建议：{suggestion}\n\n"
        f"原始参数：{json.dumps(tool_args, ensure_ascii=False)}\n\n"
        f"请根据修复建议，输出修正后的 JSON 参数（只输出 JSON，不要其他文字）。"
    )

    try:
        from app.llm import LLMFactory

        # 用 suggestion_llm 做修正（轻量、低延迟）
        llm = LLMFactory.create_suggestion_llm()
        # 覆盖 temperature 以获得更确定性的输出
        if hasattr(llm, "temperature"):
            llm.temperature = 0.1

        response = await llm.ainvoke([HumanMessage(content=correction_prompt)])
        corrected_text = (response.content if hasattr(response, "content") else str(response)).strip()

        # 提取 JSON
        import re as _re
        json_match = _re.search(r'\{[^{}]*\}', corrected_text, _re.DOTALL)
        if not json_match:
            logger.warning(f"[{skill_name}][self-correct] LLM response not valid JSON: {corrected_text[:100]}")
            return None

        corrected_args = json.loads(json_match.group(0))
        logger.info(
            f"[{skill_name}][self-correct] Corrected args: "
            f"{json.dumps(corrected_args, ensure_ascii=False)[:200]}"
        )

        # 用修正后的参数重新执行
        corrected_result_str, corrected_result_dict = await _execute_tool_safe(
            tool, corrected_args, tool_context, state,
        )

        if corrected_result_dict.get("success"):
            logger.info(f"[{skill_name}][self-correct] ✅ Auto-correct succeeded")
            return corrected_result_str, corrected_result_dict
        else:
            logger.warning(
                f"[{skill_name}][self-correct] ❌ Auto-correct still failed: "
                f"{corrected_result_dict.get('message', corrected_result_dict.get('error', 'unknown'))[:80]}"
            )
            return None

    except Exception as e:
        logger.error(f"[{skill_name}][self-correct] Exception: {type(e).__name__}: {e}")
        return None


async def execute_skill(
    state: AgentState,
    skill_name: str,
    tool_names: List[str],
    system_prompt: str,
    max_iterations: int = 8,
) -> dict:
    """ReAct 循环：LLM 自主推理 → Tool 调用 → 观察结果 → 继续推理。

    移除了 Pipeline/Hook/Guard 体系，把控制权还给 LLM。
    安全规则在 System Prompt + Tool 层，不在代码层。
    """
    raw_messages = state["messages"]
    session_id = state.get("session_id", "")
    tenant_id = int(state.get("tenant_id", 0) or 0)

    # ── 1. 上下文 & 工具准备 ──
    tool_context = build_tool_context(state)
    set_tool_context(tool_context)
    skill_registry = create_skill_registry(tool_names)
    langchain_tools = skill_registry.get_langchain_tools()
    intent_name = _extract_intent_name(state)

    # ── 2. 消息准备 ──
    messages = state["messages"]
    is_multimodal = has_images(messages)
    if not is_multimodal:
        messages = _sanitize_messages_for_text_path(messages)
    text_length = sum(len(getattr(m, "content", "") or "") for m in messages) + len(system_prompt)

    # ── 3. LLM 准备 ──
    llm = get_skill_llm(intent=intent_name, tool_count=len(langchain_tools), text_length=text_length, messages=messages)
    llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

    llm_no_thinking = None
    if langchain_tools:
        from app.llm import LLMFactory
        llm_no_thinking = LLMFactory.create_skill_llm(force_no_think=True)
        llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)

    if is_multimodal:
        llm_with_tools = llm
    elif langchain_tools:
        llm_with_tools = llm.bind_tools(langchain_tools)
    else:
        llm_with_tools = llm

    # ── 4. System Prompt 组装 ──
    user_name_raw = state.get("user_name", "")
    user_role_raw = state.get("role", "")
    if user_name_raw:
        user_name_safe = user_name_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        user_role_safe = user_role_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        system_prompt = (
            "【用户信息】当前对话用户: " + user_name_safe
            + "（角色: " + user_role_safe + "）\n"
            "【用户信息结束】\n\n" + system_prompt
        )
    system_prompt = _build_system_prompt(skill_name, inline_prompt=system_prompt)

    if is_multimodal:
        system_prompt = (
            "【图片理解能力已启用】您可以识别和分析用户上传的图片内容。\n"
            "当用户上传图片时，请：\n"
            "1. 仔细观察图片内容，识别其中的关键信息\n"
            "2. 根据用户的提问，结合图片内容给出准确回答\n"
            "3. 如果图片中包含可操作的信息，可以主动建议使用相关工具处理\n\n"
            + system_prompt
        )

    # ── 5. 跨轮上下文注入 ──
    cached_vision = ""
    if not is_multimodal and session_id:
        try:
            from app.memory.session_memory import SessionMemory as _SM
            cached_vision = await _SM().get_vision_analysis(session_id)
        except Exception as e:
            logger.warning(f"[{skill_name}] get_vision_analysis failed | session={session_id} error={e}")

    collected = {}
    if session_id:
        from app.memory.session_memory import SessionMemory
        collected = await SessionMemory().get_collected_fields(session_id)

    full_messages: List[Any] = []
    msg_list = list(messages)

    if cached_vision and msg_list:
        for i in range(len(msg_list) - 1, -1, -1):
            if isinstance(msg_list[i], HumanMessage):
                msg_list[i] = HumanMessage(content=(
                    f"[系统提示] 你上一轮已经完成了对用户图片的识别分析，结果如下。"
                    f"这是你自己的推理产物，请直接基于它回答用户问题：\n"
                    f"--- 图片分析 ---\n{cached_vision}\n--- 分析结束 ---\n"
                    f"--- 用户消息 ---\n{msg_list[i].content or ''}"
                ))
                break

    if collected and msg_list:
        fields_hint = "；".join(f"{k}={v}" for k, v in collected.items())
        last_msg = msg_list[-1]
        if isinstance(last_msg, HumanMessage):
            msg_list[-1] = HumanMessage(content=(
                f"--- 已收集字段（仅供参考）---\n{fields_hint}\n"
                f"--- 用户消息 ---\n{last_msg.content or ''}"
            ))
    full_messages.extend(msg_list)
    full_messages.insert(0, SystemMessage(content=system_prompt))

    # ── 6. Vision 分支 ──
    new_messages: List[Any] = []
    final_content = ""
    vision_analysis = ""

    if is_multimodal:
        if session_id:
            try:
                await SessionMemory().clear_vision_analysis(session_id)
            except Exception:
                logger.debug(f"[{skill_name}] clear_vision_analysis failed (non-critical) | session={session_id}")

        for vision_attempt in range(2):
            try:
                logger.info(f"[{skill_name}][DIAG] Vision LLM calling | attempt={vision_attempt+1}/2 session={session_id}")
                llm_breaker = get_breaker(LLM_BREAKER)

                async def _vision_invoke():
                    return await asyncio.wait_for(llm.ainvoke(full_messages), timeout=60.0)

                response: AIMessage = await call_with_retry(lambda: llm_breaker.call(_vision_invoke))
                _track_llm_cost(response, model=llm_model_name, tenant_id=state.get("tenant_id"), session_id=session_id)
                vision_analysis = _extract_content(response) or (
                    response.content if isinstance(response.content, str) else str(response.content)
                )
                logger.info(f"[{skill_name}] Vision completed | len={len(vision_analysis)}")
                if not vision_analysis and vision_attempt < 1:
                    logger.warning(f"[{skill_name}] Vision returned empty, retrying | session={session_id}")
                    continue
                break
            except CircuitBreakerOpenError:
                logger.error(f"[{skill_name}][SLS] Vision circuit_breaker_open | session={session_id}")
                vision_analysis = ""
                break
            except Exception as e:
                logger.error(f"[{skill_name}] Vision failed: {e} | session={session_id}")
                vision_analysis = ""
                break

        if not vision_analysis:
            final_content = "抱歉，图片分析暂时无法完成，请用文字描述您的需求，我会帮您处理。"
        else:
            vision_context = (
                f"[图片分析结果]\n用户上传了图片，以下是图片中识别到的信息：\n{vision_analysis}\n"
                f"请严格基于以上分析结果和用户的原始问题，使用可用工具完成操作。不要编造图片中没有的信息。"
            )
            if session_id and vision_analysis:
                try:
                    await SessionMemory().set_vision_analysis(session_id, vision_analysis)
                except Exception as e:
                    logger.error(f"[{skill_name}] set_vision_analysis failed | session={session_id} error={e}")

            messages = _sanitize_messages_for_text_path(list(messages))
            system_msg = SystemMessage(content=system_prompt)
            full_messages = [system_msg] + messages
            full_messages.append(SystemMessage(content=vision_context))

            text_length = sum(len(getattr(m, "content", "") or "") for m in messages) + len(system_prompt) + len(vision_context)
            llm = get_skill_llm(intent=intent_name, tool_count=len(langchain_tools), text_length=text_length, messages=messages, enable_thinking=True)
            llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

            if "processing_item_query" in tool_names:
                langchain_tools = [t for t in langchain_tools if t.name != "processing_item_query"]
                logger.info(f"[{skill_name}] Multimodal: hiding processing_item_query | {len(langchain_tools)} tools remain")

            if langchain_tools:
                llm_with_tools = llm.bind_tools(langchain_tools)
            else:
                llm_with_tools = llm

            llm_no_thinking = None
            if langchain_tools:
                llm_no_thinking = LLMFactory.create_skill_llm(force_no_think=True)
                llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)

    # ── 7. ReAct 循环 ──
    if not is_multimodal or (is_multimodal and vision_analysis):
        # 取消检测
        last_user_msg = ""
        for m in reversed(raw_messages):
            if isinstance(m, HumanMessage):
                last_user_msg = _extract_content(m)
                break
        cancel_keywords = ["算了", "取消", "不创建了", "不买了", "不要了", "不用了"]
        if any(kw in last_user_msg for kw in cancel_keywords):
            logger.info(f"[{skill_name}] Cancel detected | session={session_id}")
            final_content = "好的，已取消。有什么其他需要帮您的吗？"
            new_messages.clear()
            if session_id:
                try:
                    await SessionMemory().clear_pending_skill(session_id)
                except Exception:
                    pass
        else:
            tracker = get_tracker()
            for iteration in range(max_iterations):
                logger.info(f"[{skill_name}] Iteration {iteration+1}/{max_iterations} | session={session_id}")

                # 全轮保持 thinking — LLM 更大胆批量调工具，效率优先
                current_llm = llm_with_tools

                # ── LLM 调用（超时 + 熔断保护）──
                try:
                    logger.info(f"[{skill_name}][DIAG] LLM calling | iter={iteration+1} msgs={len(full_messages)+len(new_messages)} session={session_id}")
                    llm_breaker = get_breaker(LLM_BREAKER)

                    async def _llm_invoke():
                        return await asyncio.wait_for(current_llm.ainvoke(full_messages + new_messages), timeout=60.0)

                    response: AIMessage = await call_with_retry(lambda: llm_breaker.call(_llm_invoke))
                    _track_llm_cost(response, model=llm_model_name, tenant_id=state.get("tenant_id"), session_id=session_id)
                    logger.info(
                        f"[{skill_name}][DIAG] LLM done | iter={iteration+1} "
                        f"has_tools={bool(response.tool_calls)} content_len={len(response.content or '')} "
                        f"session={session_id}"
                    )
                except CircuitBreakerOpenError:
                    logger.error(f"[{skill_name}][SLS] LLM circuit_breaker_open | session={session_id}")
                    final_content = "抱歉，AI 服务暂时不可用，请稍后重试。"
                    break
                except asyncio.TimeoutError:
                    logger.error(f"[{skill_name}][SLS] LLM timeout | iter={iteration+1} session={session_id}")
                    final_content = "抱歉，响应超时，请换个方式描述您的需求。"
                    break
                except Exception as e:
                    logger.error(f"[{skill_name}][SLS] LLM failed | session={session_id} error={type(e).__name__}: {e}")
                    final_content = "抱歉，我遇到了一些问题，请稍后重试。"
                    break

                new_messages.append(response)

                # ── 无 tool_calls → LLM 已完成回复 ──
                if not response.tool_calls:
                    new_text = _extract_content(response)
                    if new_text:
                        final_content = new_text
                    elif not final_content:
                        final_content = "抱歉，我暂时无法生成回复，请换个方式描述您的需求。"
                    break

                # ── 执行 Tool 调用（并发）──
                async def _run_one_tool(tool_call: dict):
                    """执行单个 tool，返回 (tool_call, result_str, result_dict)。"""
                    tool_name = tool_call["name"]
                    args = tool_call.get("args", {})
                    tool = skill_registry.get_tool(tool_name)
                    if tool is None:
                        logger.warning(f"[{skill_name}] Tool not found: {tool_name} | session={session_id}")
                        return tool_call, json.dumps({"success": False, "error": "tool_not_found", "message": f"工具 {tool_name} 不可用"}, ensure_ascii=False), {"success": False}
                    result_str, result_dict = await _execute_tool_safe(tool, args, tool_context, state)
                    if not result_dict.get("success") and result_dict.get("suggestion"):
                        corrected = await _self_correct_retry(tool, args, tool_context, skill_name, result_dict, session_id, tenant_id, state)
                        if corrected:
                            result_str, result_dict = corrected
                    return tool_call, result_str, result_dict

                tool_results = await asyncio.gather(*[_run_one_tool(tc) for tc in response.tool_calls])

                for tool_call, result_str, result_dict in tool_results:
                    tool_name = tool_call["name"]
                    new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"], name=tool_name))
                    try:
                        tracker.extract(tool_name, result_dict)
                    except Exception:
                        pass
                    if tool_name == "interact" and result_dict.get("success"):
                        from app.memory.session_memory import SessionMemory as _SM2
                        try:
                            await _SM2().set_pending_skill(session_id, skill_name)
                        except Exception:
                            pass
            else:
                # 达到 max_iterations — 不暴露 LLM 的半截思考，用友好兜底
                final_content = "抱歉，处理步骤较多，请稍后重试或换个简单的方式描述需求。"

    # ── 8. 实体追踪 ──
    entities = {}
    if session_id:
        extracted = get_tracker().get_entities(session_id)
        entities = {"order_nos": extracted.order_nos, "phone_numbers": extracted.phone_numbers, "product_names": extracted.product_names, "product_ids": extracted.product_ids, "amounts": extracted.amounts}

    # ── 9. 返回值 ──
    result: dict[str, Any] = {"messages": new_messages, "final_answer": final_content, "skill_used": skill_name, "entities": entities}

    # ── 10. 跨轮持久化 ──
    creation_skills = {"product", "order", "aftersales"}
    if skill_name in creation_skills:
        success_markers = ("创建成功", "已创建", "下单成功", "工单已创建", "售后工单")
        cancel_markers = ("已取消", "已取消创建", "好的，已取消", "不创建了", "算了不买了")
        has_succeeded = any(kw in final_content for kw in success_markers)
        has_cancelled = any(kw in final_content for kw in cancel_markers)

        if has_succeeded or has_cancelled:
            try:
                await SessionMemory().set_pending_skill(session_id, None)
                logger.info(f"[{skill_name}] Flow complete, pending_skill cleared | session={session_id}")
            except Exception as e:
                logger.warning(f"[{skill_name}] Failed to clear pending_skill | session={session_id} error={e}")
        else:
            result["pending_interact_skill"] = skill_name
            try:
                await SessionMemory().set_pending_skill(session_id, skill_name)
            except Exception as e:
                logger.warning(f"[{skill_name}] Failed to persist pending_skill | session={session_id} error={e}")

    return result
