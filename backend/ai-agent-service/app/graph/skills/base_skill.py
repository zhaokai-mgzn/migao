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
from app.graph.pending_validated import extract_pending, is_pending_for, PENDING_KEY
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry, set_tool_context, get_tool_context
from app.utils.log_sanitizer import LogSanitizer
from app.memory.user_memory import UserMemoryManager
from app.suggestions.preference_tracker import PreferenceTracker
from app.core import (
    CircuitBreakerOpenError,
    LLM_FALLBACK_MESSAGE,
    get_breaker,
)
from app.llm import LLMFactory, select_model, has_images, call_with_retry, cost_tracker


# ── LLM 熔断器作用域与超时（issue #3270）──
# 历史坑（2026-09-11 实测）：此前所有 skill 共用**一个全局**熔断器名
# `LLM_BREAKER = "llm_minimax"`（遗留名，与实际模型无关）→ 任一 skill 的 LLM
# 连续 3 次超时即把该全局熔断器打成 OPEN → **全部** skill 的 LLM 调用被拒 →
# 用户侧（含 C 端小布）查订单/下单/问答统一返回兜底文案「抱歉，AI 服务暂时不可用」。
#
#     [circuit-breaker:llm_minimax] OPEN → HALF_OPEN | recovery_timeout(30.0s)
#     [circuit-breaker:llm_minimax] HALF_OPEN → OPEN | probe failed: TimeoutError
#     [customer_order][SLS] LLM circuit_breaker_open
#
# 改为**按 skill 隔离**：单 skill 退化不拖垮其他能力（爆炸半径从「整机」收到「单能力」）。
LLM_BREAKER_PREFIX = "llm:"

# LLM 单次调用超时（秒）。60s 对 reasoning 模型 + 多工具 prompt 偏紧，实测
# deepseek-v4-pro 长 prompt 偶发 >60s → 3 次即误熔断。120s 给足余量，同时仍
# 由熔断器兜住真正卡死的下游。
LLM_CALL_TIMEOUT_S = 120.0


def llm_breaker_name(skill_name: str) -> str:
    """按 skill 维度生成 LLM 熔断器名（issue #3270 作用域隔离）。

    同一 skill 多次取名字必须稳定（否则每次新建熔断器 → 熔断失效）。
    """
    return f"{LLM_BREAKER_PREFIX}{skill_name or 'unknown'}"


def _strip_think_tags(text: str) -> str:
    """移除 <think>...</think> 标签及其内容"""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    # 移除 <think>...</think> 块（含跨行）
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    return cleaned if cleaned else text


# 无条件强取消短语：几乎总是指"放弃当前流程"（与第三方行为无关）
_STRONG_CANCEL_PHRASES = ("算了", "不创建了", "取消创建", "取消操作")

# 语境化取消短语：可能是第三方行为（"客户不要了/不买了"是订单取消的原因而非放弃流程），
# 带业务领域语境标记时不算流程取消。
_CONTEXT_CANCEL_PHRASES = ("不要了", "不买了", "不用了")

# "取消"单独出现时歧义大：可能是实体名的一部分（如商品名"回归测试取消Z03"），
# 也可能是业务动作（"帮我取消订单X"应交由领域工具处理）。
# 以下语境的"取消"不作为流程取消指令。
_CANCEL_AMBIGUOUS_MARKERS = (
    "创建", "新建", "添加", "上架", "名称", "货号", "价格", "库存", "商品",
    "订单", "工单", "售后", "退款", "客户", "用户",
)


def _is_cancel_message(text: str) -> bool:
    """判断用户消息是否为明确的"放弃当前流程"取消指令。

    生产回归修复：原实现 `any(kw in msg for kw in cancel_keywords)` 纯子串匹配，
    导致两类误判：
    1. 商品名含"取消"（"帮我创建一个商品，名称回归测试取消Z03"）→ 创建请求被吞；
    2. "帮我取消订单X" → 业务动作被吞，订单实际未取消（未调 order_manage）。

    规则：
    - 无条件强取消（算了/不创建了/取消创建…）→ 直接视为取消；
    - 语境化短语（不要了/不买了/不用了）：带业务领域标记（订单/客户/商品…）→
      是第三方行为描述，不算流程取消（交领域工具）；
    - 含"取消"且带创建/业务领域语境标记 → 不是流程取消；
    - 含"取消"的短消息（≤20 字，确认卡片语境）→ 视为取消；
    - 其它 → 不是取消。
    """
    if not text:
        return False
    text = str(text).strip()
    if any(kw in text for kw in _STRONG_CANCEL_PHRASES):
        return True
    has_domain_marker = any(marker in text for marker in _CANCEL_AMBIGUOUS_MARKERS)
    if any(kw in text for kw in _CONTEXT_CANCEL_PHRASES):
        # "客户不要了"是订单取消原因；"不要了"裸消息是放弃流程
        return not has_domain_marker
    if "取消" not in text:
        return False
    if has_domain_marker:
        return False
    if len(text) > 20:
        return False
    return True


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
    # 防御：非字符串类型强制转换
    if not isinstance(content, str):
        logger.warning(f"[_extract_content] Non-string content detected: type={type(content).__name__}, str={str(content)[:200]}")
        content = str(content)

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
# - product_inquiry 不需要：商品咨询/价格查询是只读检索，直接调 search/detail 即可，无需深度思考
# DeepSeek V4 thinking 模式：首轮开启深度思考（规划工具调用 + 图片属性推理）
# 意图列表：订单/售后/人事/客户/分类等管理写操作（多步推理，需深度思考）
_THINKING_INTENTS = frozenset({
    # ── 订单域 ──
    "order_query",        # 订单查询——多条件筛选+关联上下文（仅首轮思考）
    "order_create",       # 订单创建——多SKU+加工项+价格计算
    # ── 售后域 ──
    "after_sales",        # 售后处理——退款/换货/维修逻辑
    "after_sales_create", # 售后创建——问题归类+解决方案推荐
    "complaint",          # 投诉处理——情绪安抚+升级判断
    # ── 人事/客户/分类管理写操作（Round 25 补：此前无思考，多步写流程易漏参/误判）──
    "role_manage",        # 角色创建——查权限→选权限→确认→create（HR-005 无思考致多意图误判）
    "employee_manage",    # 员工创建——先查重名→校验→确认（HR-002 同类）
    "customer_manage",    # 客户写操作——重名澄清→选→确认（CU-003/004）
    "category_manage",    # 分类管理——建品分类选择多步（PR-008/012/016 同类）
    "processing_manage",  # 加工项管理——创建/调价多步
})

# 多步串行推理意图（_THINKING_INTENTS 的子集）：
# 这些意图的工具结果可能驱动新一轮规划（如「订单查不到 → 换方式重查」），
# 迭代 2+ 轮仍需深度思考，避免提前停止或漏调工具。
# 单步检索意图（order_query 等）仅首轮思考（决定调什么工具），后续轮关闭以节省延迟。
_MULTI_TURN_THINKING_INTENTS = frozenset({
    "order_create",       # 订单创建——多SKU+加工项+价格计算，常需多步
    "after_sales",        # 售后处理——退款/换货/维修逻辑，工具结果驱动下一步
    "after_sales_create", # 售后创建——问题归类+方案推荐，可能多步
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

    - LLM_ENABLE_MODEL_ROUTING=False（默认）：使用 settings.LLM_MODEL，行为与原一致
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
    # 正确做法：由 vision_detected（消息含图片）+ VISION_ENABLED（功能开关）决定
    if vision_detected and settings.VISION_ENABLED:
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


# ── 多轮**写流程** Skill：未完成时必须锁 pending_skill ──
# 为什么要锁：写流程天然多轮（选品→收参→确认→执行），用户的后续轮多是碎片输入
# （「第一笔订单」「数量 3 米」「确认下单」）——不锁就会被重新意图分类跳出本 Skill，
# 上下文断裂、流程每轮从头重来。
#
# ⚠️ 必须同时列出 C 端（小布）Skill 名：小布的 Skill 叫 `customer_*`，与 B 端名
# （product/order/aftersales/...）**名字对不上**。只写 B 端名时 C 端写流程**从不锁**
# （CI 实证 run 34613307565 / CH-012 路由 dump）：
#     R1 intent=after_sales → aftersales   ← 正确进入
#     R2 intent=order_query → order        ← 用户只说「第一笔订单」就被重新分类跳走
#
# ⚠️ 只锁**含「需确认写工具」**的 Skill（destructive / requires_confirmation ——
# 其 validate→confirm→execute 链条天然跨轮）：只读的选品/算料/问答 Skill 不能锁 ——
# 「选品 →（交接）→ 下单」需要能切到 order 域，锁住会把用户困在只读 Skill 里出不来
# （customer_product 无 order_create；CH-010 的 R4「确认下单」正是要切到 customer_order）。
# 也不能用"非 read_only"当判据：会把 human_handoff 这类一次性写操作算进来，
# 于是 customer_general 兜底被误锁，用户困在兜底里（实测踩到）。
# 该边界由 test_graph_skills.TestCustomerSkillPendingLock 双向锁定。
CREATION_SKILL_NAMES = frozenset({
    # B 端
    "product", "order", "aftersales", "staff", "customer",
    # C 端（小布）写流程
    "customer_order", "customer_aftersales",
})


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
        permissions=state.get("permissions") or [],
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

# ────────────────────── Vision 图片意图澄清引导（Phase 1, issue #2777）──────────────────────
# 背景：目标用户可能是初中/高中文化、不熟悉与 AI 沟通（随手发图、带口语短句/不带文字）。
# 图片可能与商户已有信息（商品库/面料/订单/客户）关联，但意图多样（找同款/查订单/建品/售后）。
# 现状缺口的修复方向（G2/G3）：多模态分析不得"识别即用"，先呈现理解，意图模糊时给候选确认。
# 该引导只注入多模态（含图）路径，纯文本路径不注入（见 test_text_path_does_not_inject_clarify_guide）。
VISION_CLARIFY_GUIDE = (
    "【图片意图澄清】收到用户图片时，请先按下面顺序处理，不要拿到图片就调用工具：\n"
    "1. 先在心里形成「我的理解」：图片里是什么（面料/成品/色卡/窗户/订单或售后截图等）、"
    "可能与店铺哪个已有信息相关（商品、面料、订单、客户）。\n"
    "2. 判断用户意图是否明确：用户文字已经清楚说明要做什么（如「创建这个商品」「帮我算料」）→ "
    "按既有流程执行，不要多问。\n"
    "3. 若意图不明确（纯发图、只有口语短句、或图可对应多个对象），"
    "不要猜测后直接执行写操作/下单——先向用户呈现 2-4 个候选意图让用户确认或点选，"
    "例如：找同款/相似商品、识别面料材质、量尺寸算料、查询对应订单、录入成新商品。\n"
    "4. 候选意图用简短大白话列出（每个带简短说明），一次只问一层，不要连环追问；"
    "优先用 interact(component=choice) 下发可点选卡片（若工具可用）。\n"
    "5. 用户确认候选后再进入对应工具流程；全程不得编造图片中不存在的信息。\n"
    "6. 【候选 grounded 到店铺真实商品】当候选与「找同款/这商品多少钱/有没有这个」相关时，"
    "先按图片里的特征（颜色/面料/风格，如「雪尼尔」「米白」）调 product_search 检索店铺真实商品，"
    "把命中商品（名称+价格）作为候选内容引用——"
    "如「您发的这款像店里的『雪尼尔遮光窗帘』¥88/米，您是想：A 看这款详情 B 找类似 C 其他」；"
    "检索无命中时如实说「店里暂时没搜到一模一样的，可以发张更清楚的图，或描述下想要的颜色/面料」，"
    "不要凭空编造商品名或价格。"
)


# ────────────────────── Vision 弱分析守卫（issue #2914）──────────────────────
# 线上会话 sess_c40f60ffcae94f2b 实证：vision 偶发输出只有概括、没有实体的弱分析
# （"受图片分辨率限制…不敢编造色号糊弄您"），且会被 set_vision_analysis 缓存并注入
# 后续轮次（"你识别不出颜色?"拿到缓存的弱文本）→ 一次弱结果毒化整个会话。
_DEGRADED_VISION_HINTS = (
    "分辨率限制",
    "看不清",
    "看不清楚",
    "无法辨认",
    "无法识别",
    "不敢编造",
    "没有十足把握",
)

# 无信息量的语气词/占位碎片（不含视觉实体描述），如 "嗯"/"好的"/"。"
_VISION_NOISE_FRAGMENTS = frozenset({
    "嗯", "啊", "哦", "好的", "好", "行", "可以", "收到",
    "明白了", "明白", "知道了", "知道", "哦哦", "嗯嗯",
    "。", "！", "？", "...", "…", "好的。",
})


def _is_degraded_vision_analysis(text: str) -> bool:
    """判断 vision 分析是否为弱结果（空/无信息碎片/推诿说看不清）。

    注意：不能用『文本过短』判弱 —— DeepSeek vision 风格简洁，纯色/实体回答
    （如「这张图片是红色的。」「红色」「这是窗帘」）是有效分析（issue #2914
    次生回归：原 len<20 判据线上实测误杀简洁正确回答，导致含图消息一直走
    『抱歉，图片分析暂时无法完成』兜底）。判弱仅限：空、无实体碎片、推诿话术。
    """
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    # 单字符无最小信息量（防御：模型只吐一个标点/语气词）
    if len(stripped) < 2:
        return True
    if stripped in _VISION_NOISE_FRAGMENTS:
        return True
    return any(hint in text for hint in _DEGRADED_VISION_HINTS)


def _vision_retry_needed(text: str, attempt: int) -> bool:
    """vision 调用是否应重试：第 0 次拿到空/弱分析时重试一次，第 1 次不再重试。"""
    return (not text or _is_degraded_vision_analysis(text)) and attempt < 1


def _usable_vision_analysis(text: str) -> str:
    """重试后仍弱 → 清空（不缓存、走兜底），防弱结果毒化会话后续轮次。"""
    return "" if _is_degraded_vision_analysis(text) else text


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


async def _auto_resolve_ids(tool, tool_args: dict, state: dict) -> dict:
    """自动解析 _ids 参数：LLM 传加工项名称/序号时自动转为 UUID。

    只处理以 _ids 结尾的 list 参数（如 processing_item_ids、item_ids）。
    不做单值 _id 的解析——那些走 admin-api 的 resolveProductId。
    """
    from app.utils.id_resolver import resolve_processing_item_ids
    from app.utils.http_client import get_admin_api_client

    resolved = dict(tool_args)
    tenant_id = int(state.get("tenant_id", 0) or 0)
    if not tenant_id:
        return resolved

    for key, value in tool_args.items():
        if not key.endswith("_ids") or not isinstance(value, list):
            continue
        if not value:
            continue
        uuid_count = sum(1 for v in value if isinstance(v, str) and len(v) >= 32 and v.count('-') >= 4)
        if uuid_count == len(value):
            continue

        try:
            client = get_admin_api_client()
            resolved_ids = await resolve_processing_item_ids(value, tenant_id, client)
            if resolved_ids:
                resolved[key] = resolved_ids
                logger.info(
                    f"[auto-resolve] {tool.name}.{key}: {len(value)} raw->{len(resolved_ids)} UUIDs "
                    f"| raw={value[:3]} resolved={[r[:8]+'...' for r in resolved_ids[:3]]}"
                )
        except Exception as e:
            logger.warning(f"[auto-resolve] {tool.name}.{key} failed: {e}")

    return resolved


# 明确确认的短词（用户点击 confirm 卡片后回传的 confirmValue 或口头确认）
_CONFIRM_EXACT = {
    "确认", "确定", "好的", "可以", "同意", "确认无误", "是", "行", "没问题",
    "ok", "yes", "confirm", "confirmed", "确认操作", "确定操作",
}
# 强确认词前缀：confirm 卡片回传的 confirmValue 均以确认词开头（如"确认创建商品X"）。
# 刻意不含"可以/行/是"（易与疑问句/其他语境混淆）——它们仅作为整句精确确认生效。
_CONFIRM_PREFIX = ("确认", "确定", "同意", "好的", "没问题", "ok", "yes", "confirm")


def _is_explicit_confirmation(text: str) -> bool:
    """判断用户消息是否为对写操作的明确确认。

    用于破坏性写操作（destructive=True）的代码层兜底：只有当前轮用户消息
    读起来像确认时才允许执行，否则拦截并要求 LLM 先展示确认卡片。
    防的是提示注入（RAG 文档/模型幻觉）诱导 LLM 直接调用不可逆写工具——
    注入内容存在于 SystemMessage/ToolMessage，而非用户消息本身，故此检查有效。

    加固（2026-08-28，flash 主模型适配）：确认词必须位于消息**开头**（或整句
    精确匹配），排除"指令措辞绕过"——如"给订单X确认收款"含"确认"但这是新指令
    而非对确认卡片的确认，flash 等更直接的模型会借此跳过确认卡片直接执行破坏性写。
    """
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lower()
    if tl in _CONFIRM_EXACT:
        return True
    # confirm 卡片回传的 confirmValue（如"确认取消订单123"）或口头确认，以确认词开头且长度受限
    if len(t) <= 24 and tl.startswith(_CONFIRM_PREFIX):
        return True
    return False


def _is_card_confirm_value(message, card_confirm_value) -> bool:
    """用户消息是否**精确等于**最近一次确认卡回传的 confirmValue（= 用户点了确认按钮）。

    为什么必须精确匹配（run 34678939564 + DB 审计实证）：interact 工具描述**强制**
    confirmValue 含上下文（「确认下单：遮光窗帘 米白 散剪 门幅2.8米 3米 ¥474，收货人张三」），
    而 `_is_explicit_confirmation` 对「确认」前缀消息限长 24 字符（防"指令措辞绕过"）
    → 卡片点击回传的长 confirmValue 被误判为"非确认" → 写操作被确认门禁拦截、
    永不落库。报告却因「工具被调用」而判通过（**调了 ≠ 成了**）。

    精确匹配的语义安全性：该值由系统自己生成并展示给用户，用户消息**逐字符等于**它
    只能来自点击确认按钮（卡片协议 onAction(confirmValue)）。新指令/纠偏文本不可能
    恰好等于系统自产的值，故不存在"指令措辞绕过"面（这正是旧启发式的防护目标）。
    """
    if not message or not card_confirm_value:
        return False
    return str(message).strip() == str(card_confirm_value).strip()


def _requires_confirmation(tool, tool_args: dict, last_user_msg: str) -> bool:
    """判断本次 tool 调用是否需要用户明确确认。

    规则：
    - 纯查询工具（read_only=True）→ 永不要求确认
    - 写工具中的只读 action（action ∈ read_only_actions，如 list/detail/tree）→ 免确认
    - destructive 工具 → 必须用户明确确认（除只读 action 外）
    - requires_confirmation 工具（非 destructive 但高风险写操作：财务/通知/会话/库存，
      审计 07 P0-L1 间接提示注入面）→ 同样必须用户明确确认
    - 其余普通写工具 → 维持现状不强制（依赖 Prompt 文本铁律）

    确认判定与 _is_explicit_confirmation 一致：只有当前轮用户消息读起来像确认才放行，
    防注入内容（SystemMessage/ToolMessage 中的指令）诱导 LLM 直接执行写操作。
    """
    # 纯查询工具永不要求确认
    if getattr(tool, "read_only", True):
        return False
    action = str(tool_args.get("action") or tool_args.get("operation") or tool_args.get("op") or "")
    read_only_actions = getattr(tool, "read_only_actions", frozenset()) or frozenset()
    if action and action in read_only_actions:
        return False
    # 写工具需确认：destructive 或显式标记 requires_confirmation（审计 07 P0-L1）
    if not getattr(tool, "destructive", False) and not getattr(tool, "requires_confirmation", False):
        return False
    return not _is_explicit_confirmation(last_user_msg)


def _is_processing_items_card(args: dict) -> bool:
    """choice 卡是否加工项选择卡（排除瑕疵商品等选项带 ¥ 的普通卡）。

    判定：title 含「加工项」**或「加工」**（OR-017 run 34670989760 实证：LLM 的合法
    加工项卡标题是「这款窗帘支持**加工**哦，需要帮您加上吗？」，不含「加工项」三字但
    语义完全是加工项询问 —— 只认「加工项」会把 agent 的正确行为误判为"没问"），
    或任一 option value 以 proc_item 开头。
    与 tests/agent_eval/local_runner.py 的同名函数保持语义一致（断言侧）。
    """
    title = str((args or {}).get("title") or "")
    if not (args or {}).get("options"):
        return bool(title and ("加工项" in title or "加工" in title))
    if "加工项" in title or "加工" in title:
        return True
    return any(str(o.get("value", "")).startswith("proc_item") for o in args.get("options") or [])


def _ensure_processing_items_multiselect(tool_name: str, args: dict) -> dict:
    """加工项 choice 卡漏传 multiSelect 时自动补 true（模式 C 代码兜底，PR-014/015）。

    背景：prompt 已写「加工项选择必须 multiSelect=true」，但 LLM 仍会漏传（🧬不稳定），
    导致加工项选择器退化成单选——用户只能选一个加工项，多选流程断裂。
    设计标准 §3「改 3 次 prompt 修不好 → 代码管」：加工项卡语义上必是多选，
    代码层确定性补齐，不再依赖 LLM 自律。
    """
    if tool_name != "interact":
        return args
    if (args or {}).get("component") != "choice":
        return args
    if (args or {}).get("multiSelect") in (True, "true", "True"):
        return args
    if not _is_processing_items_card(args or {}):
        return args
    new_args = dict(args)
    new_args["multiSelect"] = True
    logger.info("[interact] 自动补齐加工项卡 multiSelect=true（LLM 漏传兜底）")
    return new_args


# ── 模式 C 代码兜底：加工项漏问（OR-017 抖动根因）──
# 业务铁律「商品有加工项 → confirm 前必须先问」目前只写在 prompt/工具描述里，
# 约 1/3 轮次 LLM 会漏掉（CI 实证 run 34622425044 ✅ / 34626024229 ❌ / 34662285260 ❌，
# 同代码同用例）。按项目「改 3 次 prompt 修不好 → 代码管」惯例，做确定性兜底：
# 当 LLM 跳过加工项直接发 confirm 卡时，把该 confirm 卡**改写**为加工项 choice 卡。
# 这与 _ensure_processing_items_multiselect（漏传 multiSelect 自动补）同族。

# 加工项 choice 卡的 option value 前缀（与 _is_processing_items_card 及
# tests/agent_eval/local_runner.py 的断言语义一致）
_PROC_ITEM_VALUE_PREFIX = "proc_item_"

# 用户明确拒绝加工项的短句（命中则跳过兜底 —— 顾客说"不需要"时不得硬弹卡）
_PROC_DECLINE_MARKERS = (
    "不需要加工", "不用加工", "不要加工", "不加工", "不加加工",
    "不需要了", "不用了", "算了", "不加了",
)


def _find_last_product_processing_items(messages) -> List[dict]:
    """从会话历史里找**最近一次** product_detail 的加工项列表。

    OR-017 实测：product_detail 与 confirm 卡经常**跨轮**（R1 查详情、R2 发卡），
    本轮 tool_results 里看不到详情，必须回看会话里的 ToolMessage。
    """
    if not messages:
        return []
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) != "product_detail":
            continue
        try:
            payload = json.loads(msg.content or "{}")
            data = payload.get("data") if isinstance(payload, dict) else None
            items = (data or {}).get("processing_items") or []
            if items:
                return items
        except (ValueError, TypeError, AttributeError):
            continue
    return []


def _last_user_declined_processing(messages) -> bool:
    """最近一条用户消息是否明确拒绝加工项（拒绝过就不再硬弹卡）"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = getattr(msg, "content", "") or ""
            if isinstance(text, list):
                text = " ".join(str(t.get("text", "")) for t in text if isinstance(t, dict))
            return any(k in str(text) for k in _PROC_DECLINE_MARKERS)
    return False


def _has_processing_choice_in_turn(tool_results) -> bool:
    """本轮是否已发过加工项 choice 卡（发过就不再改写）"""
    for _tc, _rs, rd in tool_results:
        if not rd or not rd.get("success"):
            continue
        data = rd.get("data") or {}
        if data.get("component") == "choice" and _is_processing_items_card(data):
            return True
    return False


# 加工项「已问过」的跨轮记账（issue #3365，OR-017 死循环真因）：
# `_plan_processing_items_rewrite` 只看**本轮**问没问过 —— R2 已问过并收到答案，R3 起每轮
# 又把模型的 confirm 卡改写成同一张加工项卡 → confirm 卡永远落不了地 → 顾客反复答同一题。
# 记账按**商品 id**（换商品必须重新问）；拿不到 id 时记 `*` 作兜底。
PROC_ITEMS_ASKED_KEY = "processing_items_asked"
PROC_ITEMS_ASKED_WILDCARD = "*"


def _last_product_id(messages) -> str:
    """最近一次 product_detail 的商品 id（用于按商品记「加工项已问过」）。"""
    if not messages:
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) != "product_detail":
            continue
        try:
            payload = json.loads(msg.content or "{}")
        except (ValueError, TypeError):
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
    return ""


async def _processing_items_already_asked(session_id: str, product_id: str) -> bool:
    """本会话是否已经问过该商品的加工项（含 `*` 兜底记账）。"""
    if not session_id:
        return False
    try:
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(session_id) or {}
        asked = full.get(PROC_ITEMS_ASKED_KEY) or {}
        if not isinstance(asked, dict):
            return False
        return bool(asked.get(PROC_ITEMS_ASKED_WILDCARD)) or bool(asked.get(product_id or ""))
    except Exception:
        return False


async def _mark_processing_items_asked(session_id: str, product_id: str) -> None:
    """记下「该商品的加工项已问过」（跨轮）。异常不抛，不破坏主流程。"""
    if not session_id:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        asked = full.get(PROC_ITEMS_ASKED_KEY) or {}
        if not isinstance(asked, dict):
            asked = {}
        asked[product_id or PROC_ITEMS_ASKED_WILDCARD] = True
        full[PROC_ITEMS_ASKED_KEY] = asked
        await store.commit(session_id, full)
    except Exception as e:
        logger.warning(f"[processing-items] 记账失败（非致命）: {e}")


def _plan_processing_items_rewrite(tool_results, messages) -> Optional[tuple]:
    """检测「有加工项却漏问、直接发 confirm 卡」并返回改写方案。

    Returns:
        (确认卡在 tool_results 中的下标, 新的 choice 卡 data) 或 None
    """
    confirm_idx = -1
    for i, (tc, _rs, rd) in enumerate(tool_results):
        if not rd or not rd.get("success"):
            continue
        data = rd.get("data") or {}
        if tc.get("name") != "interact":
            continue
        if data.get("component") == "confirm" and confirm_idx == -1:
            confirm_idx = i
        elif data.get("component") == "choice" and _is_processing_items_card(data):
            return None  # 本轮已经问过加工项
    if confirm_idx == -1:
        return None
    if _last_user_declined_processing(messages):
        return None  # 顾客明确拒绝过，不硬弹
    items = _find_last_product_processing_items(messages)
    if not items:
        return None  # 没拿到加工项数据，无从改写
    options = []
    for it in items[:_MAX_PROC_OPTIONS]:
        oid = str(it.get("id") or "")
        if not oid:
            continue
        name = str(it.get("name") or "加工项")
        price = it.get("unitPrice")
        unit = it.get("unit") or ""
        options.append({
            "label": f"{name} ¥{price}/{unit}" if price is not None else name,
            "value": f"{_PROC_ITEM_VALUE_PREFIX}{oid}",
            "unitPrice": price,
            "pricingMethod": it.get("pricingMethod"),
        })
    if not options:
        return None
    choice_data = {
        "component": "choice",
        "multiSelect": True,
        "title": "这款商品支持以下加工项，需要哪些呢？（可多选）",
        "options": options,
    }
    return confirm_idx, choice_data


_MAX_PROC_OPTIONS = 6


def _pending_card_before_last_user(messages) -> bool:
    """「上一轮 agent 下发了交互卡、顾客正在回应它」= 真正有在办流程。

    为什么不能只看 `state["pending_interact_skill"]`（首版修复的错，被验收重放抓到）：
    该标记在**任何** CREATION_SKILL 运行后都会被写入（`customer_order` ∈ 创建类 skill），
    于是"查一次订单"也会把流程标记点亮 → 下一句「算了」照样短路成"已取消"
    （验收 C-A2 重放 run 34731714846：R2 仍回「好的，已取消。」）。

    判据落在消息序上：**倒数第二条用户消息之后、最后一条用户消息之前**是否存在
    未答的交互卡（choice/confirm/form）。这正是"顾客在回应一张卡"的形态；
    而"上一轮只是查询/纯文本"则不算在办。
    """
    msgs = list(messages or [])
    humans = [i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)]
    if not humans:
        return False
    last_h = humans[-1]
    prev_h = humans[-2] if len(humans) >= 2 else -1
    for m in msgs[prev_h + 1:last_h]:
        if not isinstance(m, ToolMessage) or getattr(m, "name", None) != "interact":
            continue
        try:
            payload = json.loads(m.content or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        data = payload.get("data") or {}
        if data.get("component") in ("choice", "confirm", "form"):
            return True
    return False


def _confirm_card_seen(messages) -> bool:
    """会话历史里是否**出现过确认卡**（用于把 `confirmation_required` 细分成两种形态）。

    为什么需要（issue #3445）：同样是写单被确认门禁挡回，两种成因的修法完全不同 ——
      · **从没发过确认卡** → 模型跳过确认直接写（该做的是把确认卡补上）；
      · **发过卡但这次回复不是卡值**（顾客回了文本 / harness 没点卡）→ 该修的是点卡链路。
    而 CI 指纹原本只有一句 `confirmation_required`，两种形态长得一模一样，只能人肉翻容器日志
    （fast 档还看不到）。故把细分写进 error 码，让报告自己说话。
    """
    for msg in messages or []:
        if not isinstance(msg, ToolMessage) or getattr(msg, "name", None) != "interact":
            continue
        try:
            payload = json.loads(msg.content or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        if (payload.get("data") or {}).get("component") == "confirm":
            return True
    return False


def _has_inflight_interactive_card(messages) -> bool:
    """会话里是否已下发过交互卡（= 有**在办**的多轮流程）。

    用于阻止「在办流程中途误转人工」：CH-012 实证（run 34673167164）——R1 已下发
    「请选择要申请退货的订单」choice 卡，R3 用户仅回「质量问题」，agent 却调用了
    `human_handoff`（还创建了投诉工单），随后才恢复流程但轮数耗尽、`aftersale_create`
    未发生。有在办卡片 = 用户正在走流程，此时无信号转人工属于**模型自行放弃**。
    """
    for msg in reversed(messages or []):
        if not isinstance(msg, ToolMessage) or getattr(msg, "name", None) != "interact":
            continue
        try:
            payload = json.loads(msg.content or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not payload.get("success"):
            continue
        data = payload.get("data") or {}
        if data.get("component") in ("choice", "confirm", "form"):
            return True
    return False


def _accepted_param_names(tool) -> frozenset | None:
    """工具 execute() 接受的参数名集合；None = 接受任意参数（**kwargs）或无法反射。

    为什么需要（issue #3361，CI 实证 run 34703192730）：
        [tool-exec] order_create ERROR: OrderCreateTool.execute() got an unexpected
        keyword argument 'action'
    LLM 会把**别家工具的字段**顺手带过来（`aftersale_create` / `after_sales_manage`
    都有 `action`，而 `order_create` 没有）→ TypeError → tool_execution_failed →
    模型重试两次才成功（CH-010/OR-014 抖动的真因，单条用例白跑 200-400s）。
    参数被 schema 挡住却仍被传，属"模型层幻觉参数"，代码层拦掉并留警告是唯一稳的解法。
    """
    import inspect as _inspect
    cached = getattr(_accepted_param_names, "_cache", None)
    if cached is None:
        cached = _accepted_param_names._cache = {}
    # 缓存键用"模块+限定名"：仅用类名时，测试里同名替身/同名内部类会互相串味
    # （实测：两个测试各自定义的 class T 共享缓存 → 参数被误丢弃）
    key = f"{type(tool).__module__}.{type(tool).__qualname__}"
    if key in cached:
        return cached[key]
    names = None
    try:
        sig = _inspect.signature(tool.execute)
        accepted = set()
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.kind is _inspect.Parameter.VAR_KEYWORD:
                names = None          # 有 **kwargs → 不做净化
                break
            if param.kind in (_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              _inspect.Parameter.KEYWORD_ONLY):
                accepted.add(name)
        else:
            accepted.discard("context")   # context 由调用方单独传
            names = frozenset(accepted)
    except (TypeError, ValueError):
        names = None
    cached[key] = names
    return names


_PRODUCT_NOUN_RE = None


def extract_sms_code(text: str) -> str:
    """顾客消息**整条就是验证码**时提取它（issue #3365；否则返回空串）。

    为什么必须"整条就是"：手机号 13800138000 里也含 4-6 位数字，裸 `\d{4,6}` 会把
    手机号片段当验证码注入 → 验证必然失败且难排查。用例/真实顾客的验证码轮就是「123456」
    或「验证码 123456」这种形态，故用 `fullmatch`。
    """
    import re as _re
    m = _re.fullmatch(r"\s*(?:短信验证码|验证码)?\s*[:：]?\s*(\d{4,6})\s*", str(text or ""))
    return m.group(1) if m else ""


# ── 写工具「缺参等待期」恢复回路（issue #3365，OR-017 CI 实证）──────────────
# 为什么必须有：写工具因**顾客还没给某个参数**而失败后，模型会原样重发确认卡并重复调用
# 注定失败的工具 —— 顾客点多少次「确认」都拿不到那句"请输入验证码"，生产环境里人也会卡死。
# CI run 34716531345（OR-017）轨迹即此形：R7「确认下单」→ order_create!缺少短信验证码
# → R8「确认」又一张一模一样的 confirm 卡 + 同一条错误 → R9「123456」被这张卡吃掉
# （harness 优先答卡）→ `确认死循环: confirm 卡共出现 3 次未收敛`。
# 修法与 handoff_blocked_inflight 同族：跨轮记账 + 不放行注定失败的调用 + 禁止重发同一张卡。
WRITE_INPUT_ERROR_KEY = "last_write_input_error"

# 工具错误原文 → 缺的参数名。只登记**能从顾客单条消息可靠识别**的参数（保守）。
WRITE_INPUT_ERROR_PARAMS: dict = {
    "缺少短信验证码": "sms_code",
    "验证码格式无效": "sms_code",
    "验证码错误或已过期": "sms_code",
    "缺少商品明细": "items",
}

_INPUT_PARAM_LABELS: dict = {
    "sms_code": "短信验证码（4-6 位数字）",
    "items": "商品明细（名称、数量、单价）",
}


def missing_input_param(error: str) -> str:
    """工具错误原文 → 所缺参数名；不是「缺参」类失败时返回空串。"""
    text = str(error or "")
    if not text:
        return ""
    for key, param in WRITE_INPUT_ERROR_PARAMS.items():
        if key in text:
            return param
    return ""


def user_supplied_param(param: str, user_msg: str) -> bool:
    """顾客这一轮的消息是否**已经补上了**所缺参数。

    只有能可靠判定的参数才返回 True（验证码：整条就是 4-6 位数字）；未知参数一律 False
    → 宁可少拦（多问一句），也不能误判成"已补齐"而放行注定失败的写调用。
    """
    if param == "sms_code":
        return bool(extract_sms_code(user_msg or ""))
    return False


# 只有**能从顾客单条消息可靠判定"已补齐"**的参数才允许进入等待期拦截。
# 反例：`缺少商品明细`（items）无法从一句话判断补齐与否 —— 一旦记账就会把该工具的后续
# 调用永久拦住（顾客说"就是刚才那款窗帘"也判不出来）→ 这类参数宁可不管。
RECOGNIZABLE_INPUT_PARAMS = frozenset({"sms_code"})


# ── 同一张交互卡反复下发（issue #3365，OR-017 CI 实证）──────────────────────
# 实证（run 34718498228，OR-017）：同一张「这款商品支持以下加工项，需要哪些呢？」choice 卡
# 连发 **5 次**（R2-R6），顾客每次都把一模一样的答案回给它（「已选加工项：纳米圈打孔」）——
# 卡没变、答案没变、流程不前进。真人会以为系统坏了；harness 则把它读成"顾客又在答题"。
# 与确认卡同族：**同一张卡（同组件+同标题+同选项）下发第 3 次起拦下**，逼模型基于已有答案往前走。
# 为什么允许 2 次：一次正常下发 + 一次合理重问（顾客没答清/改口）是人机对话的正常形态。
CARD_EMIT_COUNTS_KEY = "card_emit_counts"
CARD_EMIT_LIMIT = 2


def card_fingerprint(args: dict) -> str:
    """交互卡指纹：组件 + 标题 + **选项标签**。

    为什么必须含选项：选项变了就是另一张卡（顾客换了商品/规格后重新确认），
    只按标题去重会把这种正常重发误拦（实测 CH-010 的加工项卡标题会变、OR-014 的选项会变）。
    """
    if not isinstance(args, dict):
        return ""
    comp = str(args.get("component") or "")
    if not comp:
        return ""
    # ── confirm 卡：按**内容**取指纹，不按标题措辞（issue #3397，CI 实证）──
    # 实测（run 34751749165，OR-023）：同一张确认卡被模型换了措辞重发
    # （`请确认订单信息` ×7 / `请确认您的订单信息` ×2）→ 按标题做指纹会当成两张不同的卡，
    # "同一张卡第 3 次起拦下"的守卫漏判 → 顾客被反复要求确认同一件事（确认死循环），
    # 写操作被拖着不落库。改按 **fields 内容**（商品/总价/收货信息…）取指纹后，
    # 「内容相同 = 同一张卡」与人的直觉一致；而**内容真变了**（改数量 3→4、总价变）
    # 就是合法的另一张卡，指纹不同、照常放行。
    if comp == "confirm":
        vals = []
        for f in (args.get("fields") or [])[:12]:
            if isinstance(f, dict):
                vals.append(f"{f.get('label')}={f.get('value')}")
        body = "、".join(vals)[:200]
        cv = str(args.get("confirmValue") or "")[:60]
        return f"confirm|{body}|{cv}" if body or cv else "confirm|"
    title = str(args.get("title") or "").strip()
    labels = []
    for opt in (args.get("options") or [])[:12]:
        if isinstance(opt, dict):
            labels.append(str(opt.get("label") or opt.get("value") or ""))
        else:
            labels.append(str(opt))
    return "|".join([comp, title, "、".join(labels)])[:200]


# ── 以"AI 自己做不到"为理由转人工（issue #3389，验收 C-A1 实证）──────────────
# 实证（run 34743802010）：C-A1 顾客「确认下单」×4 轮后，agent 调了
# `human_handoff(reason="顾客需协助下单（智能客服无法代为提交订单）")` —— 而 `order_create`
# 就是这个 skill 自己的写工具（OR-014/017/018/019/020 都真实落单）。
# 这类"能力误宣"比答错更伤：顾客明明要买，系统却告诉他"我下不了单"，转化路径被自己掐断。
CAPABILITY_DENIAL_PATTERNS = (
    "无法代为提交", "没法代为提交", "无法提交订单", "没法提交订单", "不能提交订单",
    "无法代为下单", "没法代为下单", "无法帮您下单", "没法帮您下单", "无法帮您提交",
    "没法帮您提交", "无法下单", "没法下单", "不能下单", "无法创建订单", "没法创建订单",
    "无法建单", "没法建单", "智能客服无法", "小布无法", "小布没法",
    # **权限类**措辞（issue #3421，C-A1 验收剧本原话）：
    # 实证 run 34763744203 `human_handoff({"reason": "客户请求协助下单（智能客服无下单权限）"})`
    # —— 上面那批是"动宾"式（无法下单/无法代为提交），「**无下单权限**」不在其中 →
    # 明明 `order_create` 就是它自己的写工具，却以"没权限"为由把顾客推给人工。
    "无下单权限", "没有下单权限", "无权限下单", "无提交订单权限", "无权下单",
    "无法帮您完成下单", "没法帮您完成下单", "无法帮您完成订单", "不能帮您下单",
    "人工协助下单", "协助您完成下单",
)


# ── 「顾客正在下单」+「流程已有真实进展」→ 无信号转人工即放弃流程（issue #3421）──
# 为什么需要（C-A1 run 34763744203）：原兜底只在**有在办卡片/pending skill** 时拦，
# 而那一刻顾客已把卡点掉 → 判为"无在办"直接放行，9 轮不下单、转人工收场。
# 顾客的**下单意图本身**就是"在办"信号，但要与"流程真的开始了"（查过商品详情）合取，
# 否则顾客随口一句「下单」也会把合法转人工堵死。
_ORDER_INTENT_HINTS = ("下单", "结算", "提交订单", "拍下", "购买", "要买", "帮我买",
                       "确认订单", "结账", "付款", "就这个", "买它")


def _has_ordering_intent(message: str) -> bool:
    """顾客这一轮是否在**推进下单**（"确认下单"/"数量 3 米"/"就这个"…）。"""
    text = str(message or "")
    return any(h in text for h in _ORDER_INTENT_HINTS)


async def _order_flow_started(session_id: str | None, state: dict | None = None) -> bool:
    """下单流程是否已有**真实进展**：本会话成功查过商品详情（`grounded_product_detail`）。

    为什么用这个标记：它是"流程真的开始了"的权威痕迹（查商品是下单链路的必经步骤），
    且不依赖 `state["messages"]` 是否带回上一轮 ToolMessage（跨轮可靠）。
    """
    if not session_id:
        return False
    try:
        from app.memory.session_state_store import SessionStateStore
        _s = await SessionStateStore().load(session_id) or {}
        return bool(_s.get("grounded_product_detail"))
    except Exception:
        return False


# ── 回复**文本**里的能力自我否定（issue #3443，C-A1 transcript 实证）──────────
# 实证（run 34773014637 的 C-A1）：
#   R6「小布这边是**咨询客服**，没办法直接帮您提交订单哦，不过下单很简单，我教您~」
#   R7「我是咨询客服，**没有权限帮您直接提交订单**哦，下单还是需要您在小程序里操作完成」
#   R9「小布这边确实**没办法直接帮您提交订单**，这是为了保护您的订单和支付安全哦」
#   → 还下发了一张「转人工客服，协助我下单」的卡，顾客亲手选了人工，全程未调 order_create。
# 已有的两道守卫都挡不住它：#3421 管的是**工具参数**（handoff reason），
# `_write_input_recovery_block` 之类管的是**工具调用**；而本条是**最终回复文本**。
#
# 判据与评测侧 `_false_inability_hit`（tests/agent_eval/local_runner.py）**同源**：
# 「agent 主语 + 否定动词」与「下单动作词」必须在**同一句**且距离很近 ——
# 否则「我是小布，您的专属咨询客服」这类正常开场白会被误判。
_AGENT_INABILITY_RE = re.compile(
    r"(?:我|我们|小布|智能客服|客服|这边)[^。！？\n]{0,8}(?:没法|无法|不能|没办法|做不到|没有权限|无权限|没权限)")
_TEXT_ORDER_ACTION_WORDS = ("提交订单", "下单", "创建订单", "建单", "代为提交", "代为下单",
                            "帮您提交", "帮您下单")
_INABILITY_WINDOW = 24


def capability_denial_text_hit(text: str) -> str:
    """回复文本里是否存在"AI 自己做不到 × 下单动作"的能力误宣；返回命中片段或空串。"""
    if not text:
        return ""
    for seg in re.split(r"[。！？\n]", str(text)):
        neg = _AGENT_INABILITY_RE.search(seg)
        if not neg:
            continue
        for verb in _TEXT_ORDER_ACTION_WORDS:
            pos = seg.find(verb)
            if pos < 0:
                continue
            # 动词必须紧邻否定短语（24 字窗口），避免跨半句误判
            if abs(pos - neg.start()) <= _INABILITY_WINDOW or abs(pos - neg.end()) <= _INABILITY_WINDOW:
                return seg.strip()[:60]
    return ""


_TEXT_DENIAL_CORRECTIVE = (
    "你刚才的回复以「自己做不了」为由把顾客推给小程序/人工，但事实相反："
    "`order_create` 就是本流程的写工具，**你可以真实下单**。"
    "请**重新给出回复**：不要再出现「没办法直接帮您提交订单 / 没有权限帮您提交 / "
    "去小程序操作 / 我是咨询客服」这类话术；缺信息就先 `customer_address_query` 查历史地址、"
    "再发 `interact(component=form)` 或用自然语言问；参数齐了走 confirm 卡 → `validate_input` → "
    "`order_create`（含 sms_code）。只有顾客**显式**要求人工、情绪激动或诉求超出能力时才允许引导人工。"
)


def _has_order_write_tool(skill_name: str, registry=None) -> bool:
    """本 skill 当前是否有可用的下单写工具（决定"能力误宣"是否成立）。

    为什么按 skill 判定而不是按 persona：`order_create` 是**小布 customer_order** 的写工具；
    其它 skill（知识/商品/售后）说"我下不了单"可能属实，拦下来反而堵死正确行为。

    ⚠️ `registry` 必须**显式传入**：`skill_registry` 是 `execute_skill` 的**局部变量**，
    模块级函数看不见它 —— 首版写成全局引用会被下面的 `except` 静默吞掉，
    守卫变成永远不触发的 no-op（本仓库反复出现的"假守卫"形态）。故这里不做静默兜底：
    registry 为 None 时显式返回 False，并由调用方传真实 registry。
    """
    if skill_name != "customer_order" or registry is None:
        return False
    try:
        return registry.get_tool("order_create") is not None
    except Exception:
        return False


def confirm_card_fields(args: dict) -> list:
    """从**写调用参数**整理出确认卡字段（只回显、不新增事实）。

    单一源：既供门禁话术的"字段骨架"提示，也供代码兜底**真正发卡**（issue #3445）。
    """
    a = args or {}
    fields = []
    items = a.get("items") or []
    if isinstance(items, list) and items:
        names = [str((it or {}).get("product_name") or (it or {}).get("name") or "")
                 for it in items if isinstance(it, dict)]
        names = [n for n in names if n]
        if names:
            fields.append({"label": "商品", "value": "、".join(names[:3])})
        qtys = [str((it or {}).get("quantity")) for it in items
                if isinstance(it, dict) and (it or {}).get("quantity") is not None]
        if qtys:
            fields.append({"label": "数量", "value": "、".join(qtys[:3])})
    for key, label in (("customer_name", "收货人"), ("customer_phone", "手机号"),
                       ("customer_address", "地址")):
        if a.get(key):
            fields.append({"label": label, "value": str(a.get(key))})
    return fields


def confirm_value_for_fields(fields: list) -> str:
    """与 `interact` 工具**同口径**派生 confirmValue（issue #3406：字段顺序不影响取值）。

    两处必须一致 —— 门禁比对的就是这个值，口径不一致会让"顾客明明点了卡"仍被判未确认。
    """
    facts = []
    for f in (fields or []):
        if isinstance(f, dict):
            facts.append(f"{f.get('label') or ''}={f.get('value') or ''}")
        else:
            facts.append(str(f))
    return ("确认：" + "；".join(sorted(facts))) if facts else ""


def _confirm_card_fields_hint(args: dict) -> str:
    """门禁话术里的"卡片字段骨架"（**只回显模型自己传过的值**）。

    CI 三次实测 `confirmation_required_no_card` —— 模型**从没发过确认卡**就直接写单，
    被拦回后仍反复重试同一个写调用、烧完轮数。它缺的不是"该不该发卡"，而是"卡片里填什么"。
    """
    fields = confirm_card_fields(args)
    if not fields:
        return ""
    return "，建议卡片 fields=" + json.dumps(fields, ensure_ascii=False)


def _capability_denial_reason(args: dict) -> str:
    """转人工的 reason/summary 是否是「AI 自己做不到」的能力误宣；返回命中片段或空串。

    只认明确的**自我能力否定**措辞（顾客显式诉求/情绪/正常业务理由都不在此列），
    避免把"顾客要求人工核价"这类正确转人工拦成故障。
    """
    text = f"{str((args or {}).get('reason') or '')} {str((args or {}).get('summary') or '')}"
    if not text.strip():
        return ""
    for pat in CAPABILITY_DENIAL_PATTERNS:
        if pat in text:
            return text.strip()[:60]
    return ""


# ── 算料必须以"顾客给的窗户尺寸"为前提（issue #3395，DB 实证多收 3 倍钱）──────
# 实证（run 34748745308，OR-022/OR-021）：顾客「我想买遮光窗帘，米白 **3 米**，要纳米圈打孔加工」
# —— 说的是**买 3 米布**。模型把它当成「窗宽 3 米」，再把窗高默认成 2.7 米，于是：
#     P = ceil((3+0.3)×2/2.8) = 3 幅，M = 3×(2.7+0.3) = **9.0 米**
# → `order_create{遮光窗帘×9@168}`，落库 **¥1584**（顾客要的是 ¥528），另一跑还出现 ×9.3。
# 顾客视角完全无法察觉"被多算 3 倍"，属金钱正确性缺陷。
# 判据：会话里**出现过窗户尺寸措辞**才允许算料。为什么这样不卡死：模型缺尺寸时会先问，
# 问过之后会话里自然出现「窗宽/窗高」→ 下一轮放行（自愈）；而顾客直接报"要 3 米"时，
# 会话里永远不会有尺寸措辞 → 一直被拦，逼模型走"按米数下单"而不是"按窗宽算料"。
_DIMENSION_HINTS = ("窗宽", "窗高", "宽度", "高度", "尺寸", "多宽", "多高", "米宽", "米高")


def _conversation_mentions_dimensions(messages) -> bool:
    """会话（用户 + 助手）里是否出现过窗户尺寸措辞。"""
    for m in messages or []:
        try:
            content = str(getattr(m, "content", "") or "")
        except Exception:
            continue
        if any(h in content for h in _DIMENSION_HINTS):
            return True
    return False


async def _curtain_calc_dimension_block(tool_name: str, args: dict, tool_call: dict,
                                        session_id: str, skill_name: str,
                                        state: dict | None = None):
    """无窗户尺寸证据时拦下 `curtain_calc`（返回 3 元组），否则放行（None）。"""
    if tool_name != "curtain_calc":
        return None
    # C 端专属：`curtain_calc` 是小布（顾客自助）的报价能力；B 端米宝有自己的算料链路。
    if not _is_customer_role(state):
        return None
    if _conversation_mentions_dimensions((state or {}).get("messages") or []):
        return None
    w = (args or {}).get("window_width")
    h = (args or {}).get("window_height")
    logger.warning(
        f"[{skill_name}] 拦截无依据算料 curtain_calc "
        f"window_width={w!r} window_height={h!r} | session={session_id}")
    msg = (
        f"你调用了算料工具，但**整个会话里顾客从未提供窗户尺寸**"
        f"（你填的 window_width={w}、window_height={h} 是**你自己假设**的）。"
        f"算料是按「窗宽 + 窗高 + 褶皱倍数」推导用布量（(窗宽+0.3)×褶皱倍数…），"
        f"把顾客说的**购买米数**（「要 3 米」= 买 3 米布）当成窗宽会算出 3 倍布量，"
        f"顾客会被多收 2~3 倍的钱。"
        f"正确做法：顾客直接说「要 X 米」时，X 米就是**购买数量**，"
        f"按数量下单即可（面料单价列 × 数量），**不要**再乘褶皱倍数或走算料；"
        f"只有顾客给了**窗宽/窗高**（或明确说「算料/需要多少布」）时，才先问尺寸再算料。")
    code = "curtain_calc_without_dimensions"
    return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                  ensure_ascii=False),
            {"success": False, "error": code, "message": msg})


def _clear_write_input_error(full: dict) -> dict:
    out = dict(full or {})
    out.pop(WRITE_INPUT_ERROR_KEY, None)
    return out


# ── 写工具不得用「掩码形态」手机号（issue #3386，DB 实证静默脏数据）────────────
# 实证（run 34742490138）：CH-010 订单 `20260913384380002` 落库
# `customer_phone = 13800008000`，而用例给模型的是 `13800138000`。
# `13800008000` = `138` + `0000` + `8000` —— 正是掩码 `138****8000` 的 `****` 被**填成 0**。
# 成因链：graph 层把回复脱敏后才返回（已在本文件 §8.5 移除）→ 落库的 assistant 消息
# 就是 `138****8000` → 模型下一轮读到自己的历史，把星号填成数字 → 11 位纯数字
# **形态完全合法**（`order_create._PHONE_PATTERN = ^1[3-9]\d{9}$` 放行）→ 静默建单成功，
# 顾客收不到短信与配送联系。`validate_input` 只挡得住带 `*` 的形态，挡不住"填 0"。
# 守卫判据（不是裸格式校验，而是**与已知真号比对**）：
#   · 提交值含掩码字符 → 必拦；
#   · 提交值 == 本会话已知真号的掩码变体（`138****8000` / `13800008000` / `138xxxx8000`）
#     且顾客本人本轮没给这个号 → 拦下并回放真实号码；
#   · 会话里没有已知真号 → **不拦**（`13800008000` 本身是合法真号，无权判它是脏数据）。
# 反向约束：顾客明确给了新号码必须放行（改号是合法业务，不能拦成"下单永不成功"）。
KNOWN_RAW_PHONES_KEY = "known_raw_phones"
# 已知收货地址（issue #3397）：预填值必须逐字保真 —— 模型改写会导致**寄错地址**。
KNOWN_ADDRESS_KEY = "known_customer_address"

# 掩码**占位字符**：真手机号绝不含这些字符 → 出现即证明是掩码值（可无条件拦）。
_MASK_PLACEHOLDER_CHARS = "*＊×xX·•#"

# 模型把掩码"填成什么"的可能形态：占位符本身 + **数字 0**（本次事故的真实形态）。
# ⚠️ 与占位字符必须分开：`0` 是合法号码字符，若混进 `_MASK_PLACEHOLDER_CHARS`，
# 任何含 0 的真号都会被判成"掩码形态"（过度拦截，下单永不成功）。
_MASK_FILLER_CHARS = _MASK_PLACEHOLDER_CHARS + "0"

_PHONE_IN_TEXT_RE = None


def _phone_in_text_re():
    """中国大陆手机号（数字边界）—— 惰性编译，避免模块导入期开销。"""
    global _PHONE_IN_TEXT_RE
    if _PHONE_IN_TEXT_RE is None:
        import re as _re
        _PHONE_IN_TEXT_RE = _re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    return _PHONE_IN_TEXT_RE


def raw_phones_in(text) -> set:
    """文本里出现的**完整**手机号（用于收集"本会话已知真号"）。"""
    if not text:
        return set()
    return set(_phone_in_text_re().findall(str(text)))


def mask_variants(raw: str) -> set:
    """某个真号的所有「掩码形态」——占位符既可能保留原样，也可能被模型填成数字/字母。

    `13800138000` → {`138****8000`, `13800008000`, `138xxxx8000`, …}
    最后一项是本次事故的真实落库值，故必须包含"填 0"这一形态。
    """
    raw = str(raw or "")
    if len(raw) != 11 or not raw.isdigit():
        return set()
    return {raw[:3] + (c * 4) + raw[-4:] for c in _MASK_FILLER_CHARS}


def _is_mask_shaped(value: str) -> bool:
    """值里是否含掩码占位字符（含 `*` 的号码绝不可能是真号）。

    ⚠️ 必须同时要求"够像号码"（≥7 位数字）：字段名以 `phone` 结尾不代表值就是号码
    （`{phone_model: "iPhone X"}` 含 `X`），只看占位字符会把无关字段误判成掩码号码。
    """
    text = str(value or "")
    if sum(c.isdigit() for c in text) < 7:
        return False
    return any(c in text for c in _MASK_PLACEHOLDER_CHARS)


def _phone_args(args) -> list:
    """递归收集参数里所有「手机号字段」的 (路径, 值)，深度受限。"""
    out = []

    def _walk(node, path, depth):
        if depth > 3 or not isinstance(node, dict):
            return
        for k, v in node.items():
            key = str(k)
            here = f"{path}.{key}" if path else key
            if isinstance(v, dict):
                _walk(v, here, depth + 1)
            elif isinstance(v, (list, tuple)):
                for i, item in enumerate(v):
                    _walk(item, f"{here}[{i}]", depth + 1)
            elif key.lower().endswith("phone") and isinstance(v, str) and v.strip():
                out.append((here, v.strip()))

    _walk(args or {}, "", 0)
    return out


async def _remember_known_value(session_id: str, key: str, value: str) -> None:
    """把一个**已知真值**（地址等）记进会话状态（只增不减；失败不致命）。"""
    value = str(value or "").strip()
    if not session_id or not value:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        cur = full.get(key) or []
        cur_list = [str(v) for v in cur] if isinstance(cur, (list, tuple, set)) else []
        if value in cur_list:
            return
        full[key] = cur_list + [value]
        await store.commit(session_id, full)
    except Exception as e:
        logger.warning(f"[known-value] 记录 {key} 失败（非致命）: {e}")


async def _known_raw_phones(session_id: str, state: dict | None = None,
                            last_user_msg: str = "") -> set:
    """本会话已知的**真实**手机号：跨轮持久化集合 ∪ 会话里顾客自己说过的号码。

    为什么要两路：顾客提供的号码在本轮消息/历史里（无需持久化），而
    `customer_address_query` 之类读工具返回的号码要靠持久化跨轮带过来。
    """
    known = set()
    try:
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(session_id) or {}
        stored = full.get(KNOWN_RAW_PHONES_KEY) or []
        if isinstance(stored, (list, tuple, set)):
            known |= {str(p) for p in stored if str(p)}
    except Exception:
        pass
    known |= raw_phones_in(last_user_msg)
    for msg in (state or {}).get("messages") or []:
        try:
            role = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
        except Exception:
            role = ""
        if role in ("human", "user"):
            known |= raw_phones_in(getattr(msg, "content", ""))
    return known


async def _remember_raw_phones(session_id: str, phones) -> None:
    """把读到的真号记进会话状态（只增不减；失败不致命）。"""
    fresh = {str(p) for p in (phones or set()) if str(p)}
    if not session_id or not fresh:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        cur = full.get(KNOWN_RAW_PHONES_KEY) or []
        merged = sorted({str(p) for p in cur if str(p)} | fresh)
        if merged == sorted({str(p) for p in cur if str(p)}):
            return
        full[KNOWN_RAW_PHONES_KEY] = merged
        await store.commit(session_id, full)
    except Exception as e:
        logger.warning(f"[phone-guard] 记录真实号码失败（非致命）: {e}")


def _should_code_close_loop(pending: dict | None, target_tool: str,
                            confirmed: bool, executed_tools) -> bool:
    """确认-执行链是否需要**代码侧收口**（issue #3410）。

    为什么抽成纯函数：条件写在 `execute_skill` 内联时**无法被单测观察到**
    （实证：变异 M207"去掉防双单判定"存活 —— 因为成功写会顺手清 pending，
    那条分支走不到）。抽出来后真值表可逐项钉住。

    条件（全部满足才收口）：
      · 存在已校验待执行写（`validate_input` 通过后落库）；
      · 目标工具名非空；
      · 顾客**已明确确认**（确认卡值精确匹配 或 文本明确确认）—— 安全性质：不得绕过确认；
      · 本轮模型**没有执行过**这个工具 —— 防双单（成功写会清 pending，失败写允许代码重试）。
    """
    if not pending or not target_tool or not confirmed:
        return False
    if target_tool in (executed_tools or set()):
        return False
    return True


def _is_customer_role(state: dict | None) -> bool:
    """本轮是否为 **C 端（顾客本人）** 身份。

    为什么必须有（B/C 共用面）：`interact` 工具与全部技能守卫都写在**共享的**
    `base_skill` 里 —— 两端卡片由同一个工具产出，守卫不分端就会互相影响
    （B 端店员代客下单、客服改客户资料的表单与 C 端顾客自助场景语义不同）。
    身份来自 `state["role"]`（= `context.role`：C 端 "customer"，B 端 "admin"/"agent"）。
    """
    return str((state or {}).get("role") or "").strip().lower() == "customer"


def _norm_ws(v) -> str:
    """比对前去掉所有空白（地址/号码里的空格差异不算改写）。"""
    return "".join(str(v or "").split())


# ── 收货信息表单预填必须**逐字保真**（issue #3397，实测 run 34750771576）──────────
# 实证：OR-023 老客户下单，库里地址 `浙江省杭州市西湖区文三路 1 号 1 幢 101 室`，
# 模型预填成 `浙江省杭州市西湖区文三路 100 号`（库里/会话里都没有这个地址）——
# 顾客若不逐字核对就提交，订单会寄到错地址；号码被改写（尤其掩码值回流）更严重
# （掩码号会静默写库，issue #3379/#3386 同族）。
# 判据：表单预填的收货字段，若会话里已有**已知真值**且与预填值不一致（忽略空白），
# 且该值**不是顾客本条消息自己给的** → 拦下并回放真值，逼模型逐字复制。
_PREFILL_FIDELITY_FIELDS = {
    "customer_address": (KNOWN_ADDRESS_KEY, "收货地址"),
    "customer_phone": (KNOWN_RAW_PHONES_KEY, "手机号"),
    "receiver_phone": (KNOWN_RAW_PHONES_KEY, "手机号"),
}


# ── 顾客已报购买数量时，禁止用"用量/褶皱倍数"再问一遍（issue #3402，C-A1 实证）──
# 实证（run 34753219595，主路径 C-A1）：
#   R4 用户「数量 3 米」→ Agent 发 `choice: 请选择窗帘用量 → 3米（¥528）| 6米（¥1056，推荐）`
# —— 顾客说的 3 米就是买 3 米布；Agent 当成窗宽按褶皱倍数算成 6 米，**还标为"推荐"**（2 倍钱）。
# 这张多余卡还每轮吃掉一次交互 → C-A1 的 repeat_until 用完仍未落单（order_create 未调用）。
# 同一个认知错误的**第三个出口**（工具层 #3395、入参层 #3394 已修），故在**产出层（卡片）**拦。
# 判据（保守，只在"确凿的多收钱形态"上触发）：
#   ① 顾客消息里报过**购买数量**（「数量 3 米」「买 2.5 米布」…，且不是"窗宽/窗高"语义）；
#   ② 卡片选项里出现该数量的 **≥2 倍**（2×/3×…，容差 1%）；
#   ③ 卡片标题或选项文字用了「用量 / 褶皱倍数 / 倍数」这类框架。
# 顾客自己要求加倍（「褶皱饱满一点」「用量加倍」）→ 放行。
_QUANTITY_FRAME_WORDS = ("用量", "褶皱倍数", "褶皱", "倍数", "用布量")
_QUANTITY_INTENT = r"(?:数量|买|要|购|来|下单|做)\s*([0-9]+(?:\.[0-9]+)?)\s*米"
_QUANTITY_PLAIN = r"([0-9]+(?:\.[0-9]+)?)\s*米(?:布)?"
_DIMENSION_SEMANTIC = ("窗宽", "窗高", "宽", "高", "门幅", "尺寸")


def _stated_purchase_quantities(messages) -> set:
    """顾客消息里明确报过的**购买数量**（米）。带尺寸语义的表述不算。"""
    import re as _re
    out: set = set()
    for m in messages or []:
        try:
            role = str(getattr(m, "type", "") or getattr(m, "role", ""))
            text = str(getattr(m, "content", "") or "")
        except Exception:
            continue
        if role not in ("human", "user") or not text:
            continue
        for pat in (_QUANTITY_INTENT,):
            for g in _re.findall(pat, text):
                try:
                    out.add(float(g))
                except (TypeError, ValueError):
                    pass
        # 无意图词但有「米布」：也算购买数量（"3 米布"）
        if "米布" in text:
            for g in _re.findall(_QUANTITY_PLAIN, text):
                try:
                    out.add(float(g))
                except (TypeError, ValueError):
                    pass
    return out


async def _quantity_choice_block(tool_name: str, args: dict, tool_call: dict,
                                 session_id: str, skill_name: str,
                                 state: dict | None = None):
    """用"用量/褶皱倍数"框架给出顾客所报数量的 ≥2 倍选项 → 拦下（3 元组），否则 None。"""
    import re as _re
    if tool_name != "interact":
        return None
    # C 端专属守卫：判据是「**顾客**说『买 3 米』被当成窗宽」这条顾客语义
    # （B 端店员代客下单时给出"用量/褶皱"选项可能是合法业务动作）→ 只对 customer 生效。
    if not _is_customer_role(state):
        return None
    opts = (args or {}).get("options")
    if not isinstance(opts, list) or not opts:
        return None
    msgs = (state or {}).get("messages") or []
    stated = _stated_purchase_quantities(msgs)
    if not stated:
        return None
    title = str((args or {}).get("title") or "")
    texts = [title] + [
        f"{o.get('label') or ''} {o.get('value') or ''}" if isinstance(o, dict) else str(o)
        for o in opts
    ]
    joined = " ".join(texts)
    if not any(w in joined for w in _QUANTITY_FRAME_WORDS):
        return None
    # 顾客自己要求过加倍/褶皱饱满 → 放行
    for m in msgs:
        t = str(getattr(m, "content", "") or "")
        if any(k in t for k in ("加倍", "褶皱饱满", "要多一点", "用布量多点")):
            return None
    for text in texts:
        for g in _re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*米", text):
            try:
                v = float(g)
            except (TypeError, ValueError):
                continue
            for q in stated:
                if q <= 0:
                    continue
                for k in (2, 3, 4):
                    if abs(v - q * k) <= max(0.05, q * 0.01):
                        logger.warning(
                            f"[{skill_name}] 拦截「用量/褶皱」倍数选项 tool=interact "
                            f"stated={q} option={v} | session={session_id}")
                        code = "quantity_choice_pleat_multiple"
                        msg = (
                            f"顾客已经明确说了购买数量 **{q:g} 米**（这就是订单数量），"
                            f"你却在卡里给出 `{v:g} 米` 这个 **{k} 倍**选项并要求他选用量 —— "
                            f"顾客会以为要买 {v:g} 米（金额翻 {k} 倍），"
                            f"而且反复问已经回答过的事会让流程原地打转"
                            f"（实测 C-A1 因此耗尽轮数、订单没落成，issue #3402）。"
                            f"正确做法：**直接用 {q:g} 米继续**（面料单价 × {q:g} 米 = 金额），"
                            f"进入确认卡（`validate_input` → `interact(confirm)`）与短信验证码，"
                            f"不要再让他选用量/褶皱倍数。只有**顾客主动要求**加褶皱/加倍用量时才谈倍数。")
                        return (tool_call,
                                json.dumps({"success": False, "error": code, "message": msg},
                                           ensure_ascii=False),
                                {"success": False, "error": code, "message": msg})
    return None


async def _form_prefill_fidelity_block(tool_name: str, args: dict, tool_call: dict,
                                       session_id: str, skill_name: str,
                                       last_user_msg: str = "", state: dict | None = None):
    """form 预填值与已知真值不一致时拦下（返回 3 元组），否则放行（None）。"""
    if tool_name != "interact":
        return None
    # C 端专属：守的是"顾客的收货信息预填"。B 端客服/商家改客户资料的表格
    # 同名 key（customer_phone/customer_address）语义不同 → 只对 customer 生效。
    if not _is_customer_role(state):
        return None
    if str((args or {}).get("component") or "") != "form":
        return None
    fields = (args or {}).get("formFields") or []
    if not isinstance(fields, list) or not fields:
        return None
    known: dict = {}
    if session_id:
        try:
            from app.memory.session_state_store import SessionStateStore
            full = await SessionStateStore().load(session_id) or {}
            for key, (store_key, _label) in _PREFILL_FIDELITY_FIELDS.items():
                vals = full.get(store_key) or []
                if isinstance(vals, (list, tuple, set)):
                    known[key] = [str(v) for v in vals if str(v)]
        except Exception:
            pass
    if not known:
        return None
    from app.utils.pii_mask import mask_pii as _mask
    last_user_norm = _norm_ws(last_user_msg)
    for f in fields:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key") or "")
        if key not in _PREFILL_FIDELITY_FIELDS:
            continue
        val = str(f.get("value") or "")
        if not val.strip():
            continue
        truth_list = [v for v in (known.get(key) or []) if v]
        if not truth_list:
            continue
        got_norm = _norm_ws(val)
        if any(got_norm == _norm_ws(t) for t in truth_list):
            continue
        # 顾客本条消息自己给了这个值（合法新地址/新号码）→ 放行
        if got_norm and got_norm in last_user_norm:
            continue
        truth = truth_list[0]
        label = _PREFILL_FIDELITY_FIELDS[key][1]
        logger.warning(
            f"[{skill_name}] 拦截收货信息预填被改写 field={key} got={val[:24]!r} "
            f"truth={truth[:24]!r} | session={session_id}")
        msg = (
            f"`interact(form)` 里 `{label}` 的预填值 `{val}` 与会话中**已知的真实值**"
            f"`{truth}` 不一致 —— 预填值必须**逐字复制工具返回值**，不能自己改写"
            f"（地址被改写顾客会寄错地方；号码被改写/掩码化会静默写错订单）。"
            f"请用真值 `{label}={truth}` 重新下发这张表单；"
            f"若顾客刚刚给了新的{label}（本条消息里提到），则用顾客给的那个值。")
        code = "form_prefill_altered"
        return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                      ensure_ascii=False),
                {"success": False, "error": code, "message": msg})
    return None


async def _masked_phone_write_block(tool_name: str, args: dict, tool_call: dict,
                                    session_id: str, skill_name: str,
                                    last_user_msg: str = "", state: dict | None = None):
    """写工具参数里是「掩码形态」手机号时拦下（返回 3 元组），否则放行（None）。"""
    pairs = _phone_args(args or {})
    if not pairs:
        return None
    known = await _known_raw_phones(session_id, state, last_user_msg) if session_id else \
        raw_phones_in(last_user_msg)
    # 顾客本人本轮明确给出的号码 = 权威来源（哪怕它长得像掩码变体也不拦）
    user_said = raw_phones_in(last_user_msg)
    for path, value in pairs:
        if _is_mask_shaped(value):
            raw = ""
            for k in known:
                if k[:3] == value[:3] and k[-4:] == value[-4:]:
                    raw = k
                    break
            return _masked_phone_block_result(
                tool_name, path, value, raw, session_id, skill_name,
                because="含掩码字符", tool_call=tool_call)
        if value in user_said:
            continue
        for k in known:
            if value in mask_variants(k):
                return _masked_phone_block_result(
                    tool_name, path, value, k, session_id, skill_name,
                    because=f"是本会话真实号码（{k}）的掩码填充形态",
                    tool_call=tool_call)
    return None


def _masked_phone_block_result(tool_name: str, path: str, value: str, known_raw: str,
                               session_id: str, skill_name: str, because: str,
                               tool_call: dict | None = None):
    """构造拦截返回值（3 元组：tool_call, result_str, result_dict）。"""
    import json as _json
    if known_raw:
        tail = (f"顾客的真实号码是 **{known_raw}** —— 请直接用这个完整号码重新调用 "
                f"`{tool_name}`；**不要**把 `****` 填成数字。")
    else:
        tail = (f"请先回到会话里取顾客**完整的 11 位**号码（或直接问顾客），"
                f"再用真实号码调用 `{tool_name}`。")
    msg = (f"`{tool_name}` 的参数 `{path}` 填的是**掩码形态**的手机号 `{value}`"
           f"（{because}）：掩码值不能用来建单/建工单 —— 号码错了顾客收不到短信与配送联系，"
           f"而且 11 位纯数字的掩码填充值**看起来完全合法**，会静默落库成脏数据。{tail}")
    logger.warning(
        f"[{skill_name}] 拦截掩码形态手机号 tool={tool_name} arg={path} value={value!r} "
        f"known={known_raw!r} | session={session_id}")
    code = "write_blocked_masked_phone"
    return (tool_call, _json.dumps({"success": False, "error": code, "message": msg},
                                   ensure_ascii=False),
            {"success": False, "error": code, "message": msg})


async def _write_input_recovery_block(tool_name: str, args: dict, tool_call: dict,
                                      session_id: str, skill_name: str,
                                      last_user_msg: str):
    """「缺参等待期」拦截：返回 (tool_call, result_str, result_dict) 表示拦下，None 表示放行。

    只在**同一个写工具**或**逐字重发同一张确认卡**时拦 —— 其余工具（查询/交互/换商品）
    一律放行，绝不因为一次缺参失败就把整个会话锁死。
    """
    if not session_id:
        return None
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
    except Exception:
        return None
    flag = full.get(WRITE_INPUT_ERROR_KEY)
    if not isinstance(flag, dict):
        return None
    param = flag.get("param") or missing_input_param(flag.get("error", ""))
    if not param:
        return None
    if user_supplied_param(param, last_user_msg):
        # 顾客已补上 → 清账放行（写工具本体还要走确认门禁）
        try:
            await store.commit(session_id, _clear_write_input_error(full))
            logger.info(f"[{skill_name}] 缺参已补齐 → 清除欠参标记 param={param} | session={session_id}")
        except Exception as e:
            logger.warning(f"[{skill_name}] 欠参标记清除失败（非致命）: {e}")
        return None

    label = _INPUT_PARAM_LABELS.get(param, param)
    failed_tool = str(flag.get("tool") or "")
    reason = ""

    if tool_name == failed_tool:
        reason = (f"顾客**还没有提供**{label}：重复调用 {tool_name} 结果必然相同，"
                  f"本轮**禁止再次调用 {tool_name}**。")
    elif tool_name == "interact":
        _comp = str((args or {}).get("component") or "")
        if (_comp == "confirm"
                and str((args or {}).get("confirmValue") or "") != ""
                and str((args or {}).get("confirmValue")) == str(full.get("last_confirm_value") or "")):
            reason = (f"顾客已经确认过这张卡了，而 {failed_tool or '写工具'} 缺的是{label}："
                      f"重发**同一张确认卡**只会让顾客反复点确认（死循环），本轮禁止重发该卡。")
        else:
            # 欠参期间**任何卡片**都不发（issue #3367）：实测 CH-010 首跑里两张**不同的**卡
            # （choice/confirm）各自把"顾客要发的验证码"这一轮吃掉 → order_create 缺码失败。
            # 卡片会抢走顾客本来要打的那句话；此时唯一有用的动作是**用文本索要**。
            reason = (f"顾客还没提供{label}（{failed_tool or '写工具'} 因此无法执行）："
                      f"本轮**不要下发任何卡片**（卡会抢走顾客正要发的内容），"
                      f"直接用文本索要{label}。")

    if not reason:
        return None

    msg = (reason
           + f" 请**直接用自然语言**向顾客说明卡在哪里，并索要{label}"
           + (f"（工具原话：{flag.get('message')}）" if flag.get("message") else "。")
           + " 顾客提供后再继续原流程（不要重新走一遍商品/地址收集）。")
    logger.warning(
        f"[{skill_name}] 拦截缺参等待期的重复动作 tool={tool_name} "
        f"param={param} | session={session_id} last_msg={last_user_msg[:20]!r}"
    )
    code = "write_blocked_waiting_customer_input"
    return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                  ensure_ascii=False),
            {"success": False, "error": code})


async def _card_loop_block(tool_name: str, args: dict, tool_call: dict,
                          session_id: str, skill_name: str):
    """同一张交互卡下发第 3 次起拦下（返回 3 元组），否则放行（None）。"""
    if tool_name != "interact" or not session_id:
        return None
    fp = card_fingerprint(args)
    if not fp:
        return None
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
    except Exception:
        return None
    counts = full.get(CARD_EMIT_COUNTS_KEY) or {}
    if not isinstance(counts, dict):
        return None
    if int(counts.get(fp) or 0) < CARD_EMIT_LIMIT:
        return None
    comp = str((args or {}).get("component") or "")
    title = str((args or {}).get("title") or "")[:40]
    logger.warning(
        f"[{skill_name}] 拦截重复下发同一张卡 component={comp} title={title!r} "
        f"count={counts.get(fp)} | session={session_id}"
    )
    msg = (f"这张{comp}卡（「{title}」）此前已经下发给顾客并收到过回答，内容没有任何变化："
           "重复下发只会让顾客反复答同一题、流程原地打转。"
           "**本轮不要重发这张卡**：请基于顾客已经给出的信息继续下一步"
           "（信息齐了就调用对应的写工具；缺信息就用自然语言直接问那一项）。"
           "若顾客**明确要求**再看一次加工项/选项，用文本把选项列给他，不要再发卡。")
    code = "card_blocked_repeat_emission"
    return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                  ensure_ascii=False),
            {"success": False, "error": code})


async def _inject_write_input_recovery(system_prompt: str, state: dict,
                                       last_user_msg: str) -> str:
    """把「顾客欠一个参数」注入下一轮系统提示（issue #3365）。

    只在真正待补时注入；顾客本轮已补上则顺手清账并返回原提示。
    fire-and-forget：任何异常都不抛，不破坏主流程。
    """
    if not state.get("session_id"):
        return system_prompt
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(state["session_id"]) or {}
        flag = full.get(WRITE_INPUT_ERROR_KEY)
        if not isinstance(flag, dict):
            return system_prompt
        param = flag.get("param") or missing_input_param(flag.get("error", ""))
        if not param:
            return system_prompt
        if user_supplied_param(param, last_user_msg):
            await store.commit(state["session_id"], _clear_write_input_error(full))
            return system_prompt
        label = _INPUT_PARAM_LABELS.get(param, param)
        failed_tool = str(flag.get("tool") or "写工具")
        logger.info(
            f"[write-input-recovery] 注入索要指令 param={param} tool={failed_tool} "
            f"| session={state['session_id']}"
        )
        return (
            "【上一轮写操作失败：顾客还没提供必要信息】\n"
            f"- {failed_tool} 因缺少{label}而**没有执行**。\n"
            f"- 本轮必须用自然语言向顾客说明并**索要{label}**"
            + (f"（原话：{flag.get('message')}）" if flag.get("message") else "。") + "\n"
            f"- **禁止**再次调用 {failed_tool}（参数不全会再次失败）；"
            "- **禁止**重发上一轮的确认卡/选择卡（重发只会让顾客反复点确认，形成死循环）。\n"
            "- 顾客提供该信息后再继续原流程，不要重新收集已有的商品与地址。\n\n"
            + system_prompt
        )
    except Exception as e:
        logger.warning(f"[write-input-recovery] 注入失败（非致命）: {e}")
        return system_prompt


def extract_product_keyword(text: str) -> str:
    """从顾客消息里抽取**可用于 product_search 的商品关键词**（issue #3365）。

    规则（保守）：取「2-10 字中文/数字 + 商品类名词（窗帘/窗纱/面料/布艺/遮光帘）」的最长命中；
    没有类名词时退化为「订单里常见的指代」之外的短名词 —— 抽不到就返回空串（由调用方决定不作为）。

    为什么需要：接地自动驾驶要替模型补上 product_search，关键词必须来自**顾客原话**
    （不能编），否则会搜错商品、把错误数据当"接地真值"。
    """
    import re as _re
    if not text:
        return ""
    m = _re.search(r"[\u4e00-\u9fa5A-Za-z0-9]{1,10}(?:窗帘|窗纱|面料|布艺|遮光帘)", str(text))
    if not m:
        return ""
    kw = m.group(0)
    # 去掉动词前缀（「我想买夏日清风窗帘」→「夏日清风窗帘」）：否则搜的是整句
    kw = _re.sub(
        r"^(?:帮我|给我|我想买|我想|我要|搜索|搜一下|搜下|查一下|查下|搜|查|看看|看|推荐|要|买|来|找)+",
        "", kw)
    return kw


def _sanitize_tool_args(tool, tool_args: dict) -> dict:
    """丢弃工具 execute() 不接受的关键字参数（保留 context/正常参数）。"""
    accepted = _accepted_param_names(tool)
    if accepted is None or not isinstance(tool_args, dict):
        return tool_args
    unknown = [k for k in tool_args if k not in accepted]
    if not unknown:
        return tool_args
    logger.warning(
        f"[tool-arg-sanitize] {getattr(tool, 'name', '?')} 丢弃不受支持参数 "
        f"{unknown}（模型幻觉参数；保留 {sorted(set(tool_args) - set(unknown))}）"
    )
    return {k: v for k, v in tool_args.items() if k in accepted}


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
    # 幻觉参数净化（见 _sanitize_tool_args 注释：order_create 收到 action → TypeError → 抖动）
    tool_args = _sanitize_tool_args(tool, tool_args)

    # 1.5. 自动解析 _ids 参数：LLM 传加工项名称/序号时自动转 UUID
    tool_args = await _auto_resolve_ids(tool, tool_args, state)

    session_id = state.get("session_id", "")
    tenant_id = str(state.get("tenant_id", ""))
    tool_name = tool.name
    cache_key = f"{tenant_id}:{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"

    # 2. 缓存检查（带 asyncio.Lock 防止并发竞态）
    # ⚠️ 仅缓存只读工具：写操作（read_only=False）绝不允许缓存，
    # 否则 60s 内重复的非幂等写（如重复下单/售后）会被静默吞掉。
    if not hasattr(_execute_tool_safe, '_cache'):
        _execute_tool_safe._cache = {}
        _execute_tool_safe._cache_lock = asyncio.Lock()
    if tool.read_only:
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
        logger.error(
            "[tool-exec] {} TIMEOUT 30s | args={}",
            tool_name,
            json.dumps(LogSanitizer.sanitize_tree(tool_args), ensure_ascii=False, default=str)[:300],
        )
        err = json.dumps({"success": False, "error": "timeout", "message": "工具执行超时"}, ensure_ascii=False)
        return err, {"success": False, "error": "timeout"}
    except Exception as e:
        # 生产回归（sess_fba38395ed094a9d）：此前用 f-string 把 args JSON 拼进消息文本，
        # loguru 因 exc_info=True 触发 message.format()，JSON 里的未配对花括号（如截断的
        # {"component":...）二次抛错（ValueError: unmatched '{'），穿透 except 掩盖真实
        # TypeError，agent 流崩溃且 assistant 消息不落库。
        # 修复：参数化占位符传参 —— args 作为 format 参数不会被再次解析。
        logger.error(
            "[tool-exec] {} ERROR: {} | args={}",
            tool_name,
            e,
            json.dumps(LogSanitizer.sanitize_tree(tool_args), ensure_ascii=False, default=str)[:500],
            exc_info=True,
        )
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

    # 5. 缓存（带锁）— 仅只读工具
    if result.success and tool.read_only:
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


async def _inject_user_memories(system_prompt: str, state: AgentState) -> str:
    """C 端长期记忆注入（issue #2815：仅 xiaobu；mibao 不注入）。

    - 读取 user_memories 中 importance>=0.5 的 top 记忆（agent_type='xiaobu'）
    - format_for_prompt 已做 XML 转义/截断消毒（审计 07 P1-L9：接线必须先消毒）
    - 注入位置：identity_prefix 之后、_build_system_prompt 之前
    - 任何异常不抛（fire-and-forget 语义，不破坏主流程）
    """
    if state.get("agent_type") != "xiaobu":
        return system_prompt
    try:
        tenant_id = int(state.get("tenant_id", 0) or 0)
        user_id = state.get("user_id", "")
        if not tenant_id or not user_id:
            return system_prompt
        mem_text = await UserMemoryManager().format_for_prompt(
            tenant_id, user_id, agent_type="xiaobu"
        )
        if mem_text:
            logger.info(
                f"[memory-inject] Injected user memories | "
                f"tenant={tenant_id} user={user_id} len={len(mem_text)}"
            )
            return mem_text + "\n" + system_prompt
    except Exception as e:
        logger.warning(f"[memory-inject] Failed | error={e}")
    return system_prompt


def _xml_escape_pref(text: str) -> str:
    """偏好注入文本消毒：去控制字符 + XML 转义（审计 07 P1-L9 注入安全原则）。"""
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def _inject_user_preferences(system_prompt: str, state: AgentState) -> str:
    """建议个性化偏好注入（issue #2997：flag 门控，默认关闭；仅 xiaobu）。

    - 开关 SUGGESTION_PREFERENCE_ENABLED=False（默认）→ 直接返回原 prompt（零行为变化）
    - 开启后读取 user_suggestion_prefs 的 TOP 偏好意图（PreferenceTracker.get_top_intents），
      生成 <user_preferences> 消毒块前置注入，供 LLM 自然生成个性化「猜你想问」
    - 标签来自静态 INTENT_LABELS 词表，仍经 _xml_escape_pref 消毒（对齐审计 07 P1-L9）
    - 注入位置与 _inject_user_memories 相同；任何异常不抛（fire-and-forget 语义）
    """
    if not settings.SUGGESTION_PREFERENCE_ENABLED:
        return system_prompt
    if state.get("agent_type") != "xiaobu":
        return system_prompt
    try:
        tenant_id = int(state.get("tenant_id", 0) or 0)
        user_id = state.get("user_id", "")
        if not tenant_id or not user_id:
            return system_prompt
        top = await PreferenceTracker().get_top_intents(tenant_id, user_id, limit=5)
        if not top:
            return system_prompt
        lines = []
        for item in top[:5]:
            label = _xml_escape_pref(
                str(item.get("label") or item.get("intent_type") or "")
            )
            try:
                count = int(item.get("click_count") or 0)
            except (ValueError, TypeError):
                count = 0
            lines.append(f"- {label}（{count} 次）")
        pref_text = (
            "<user_preferences>\n"
            "用户最近常点击的咨询主题（按频次排序，生成「猜你想问」建议时优先覆盖）：\n"
            + "\n".join(lines)
            + "\n</user_preferences>"
        )
        if len(pref_text) > 800:
            pref_text = pref_text[:800] + "..."
        logger.info(
            f"[preference-inject] Injected | "
            f"tenant={tenant_id} user={user_id} intents={len(top)}"
        )
        return pref_text + "\n\n" + system_prompt
    except Exception as e:
        logger.warning(f"[preference-inject] Failed | error={e}")
    return system_prompt


# 需要**短信验证码**才能执行的写工具（C 端）。验证码轮**不构成确认**（确认门禁不可绕过），
# 但码本身要被**记住** —— 顾客不该因为"先给了码"而白给一轮（验收 C-A1 R7 实证）。
SMS_GATED_WRITE_TOOLS = frozenset({"order_create"})
LAST_SMS_CODE_KEY = "last_sms_code"


async def _remember_sms_code(session_id: str, user_msg: str) -> str:
    """验证码轮：把码记进会话状态，供后续写工具回填。异常不抛，不破坏主流程。"""
    code = extract_sms_code(user_msg or "")
    if not code or not session_id:
        return ""
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        if str(full.get(LAST_SMS_CODE_KEY) or "") != code:
            full[LAST_SMS_CODE_KEY] = code
            await store.commit(session_id, full)
            logger.info(f"[sms-code] 记住验证码（供写工具回填）| session={session_id}")
    except Exception as e:
        logger.warning(f"[sms-code] 记码失败（非致命）: {e}")
    return code


async def _stored_sms_code(session_id: str) -> str:
    """读回记住的验证码（无则空串）。"""
    if not session_id:
        return ""
    try:
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(session_id) or {}
        return str(full.get(LAST_SMS_CODE_KEY) or "")
    except Exception:
        return ""


async def _inject_pending_validated(system_prompt: str, state: AgentState, last_user_msg: str) -> str:
    """确认-执行链「已校验待执行」注入（issue #3031，仅 mibao/xiaobu 通用）。

    - 读 SessionStateStore 的 pending_validated_input（validate_input 通过后落库）
    - 仅当当前轮用户消息读起来像确认（_is_explicit_confirmation，或**确认卡 confirmValue
      精确匹配**）时才注入，避免把「待执行」误注入到用户提出新需求/纠偏的轮次
    - 注入 format_execution_hint 提示，让 LLM 直接调写工具，不再重走 validate+interact
    - 卡片确认命中时，把确认记录到 pending.target_tool（跨轮放行链：本轮或下一轮
      实际调用写工具时不再被确认门禁拦 —— CI 实证 run 34682324499：confirmValue 在
      上一轮匹配、本轮消息是验证码，写工具仍被拦）
    - fire-and-forget：任何异常不抛，不破坏主流程
    """
    if not state.get("session_id"):
        return system_prompt
    try:
        from app.memory.session_state_store import SessionStateStore
        from app.graph.pending_validated import format_execution_hint
        store = SessionStateStore()
        full = await store.load(state["session_id"]) or {}
        pending = full.get(PENDING_KEY)

        # 确认轮判定：口头短确认（24 字内）或确认卡 confirmValue 精确匹配（长值）
        is_card_confirm = _is_card_confirm_value(
            last_user_msg or "", full.get("last_confirm_value"))
        # ⚠️ 验证码轮**不算**确认轮（安全性质：确认门禁不得被绕过 —— 见
        # TestTextConfirmationRecordedAcrossTurns::test_sms_code_turn_does_not_record）。
        # 首版曾把验证码轮当确认以"少一轮"，但那等于让顾客**没确认订单明细就能下单**。
        # 正确修法见下：**记住验证码**（供后续写入回填），门禁照旧。
        if (not _is_explicit_confirmation(last_user_msg or "")
                and not is_card_confirm):
            return system_prompt

        # 确认记录（跨轮放行链）：用户在**确认轮**明确确认了「已校验待执行」的写操作时，
        # 就把放行标记落进会话状态 —— **无论本轮模型有没有真的发起写调用**。
        # 两种确认形态都算：
        #   ① 点了确认卡（confirmValue 精确匹配，系统自产值逐字回传）
        #   ② 文本明确确认（_is_explicit_confirmation，与门禁同一判据，如「确认」）
        # 为什么必须覆盖 ②（CI 实证 run 34689293179，OR-017）：
        #   R3 顾客回「确认」→ 模型只调 validate_input 并下发确认卡（**没写**）；
        #   R4 顾客回手机验证码「123456」→ last_confirm_value（'确认下单'）不匹配、
        #   本轮文本也不像确认 → 门禁以「未确认」拦下 order_create → 订单永不落库，
        #   而用例因老断言只看工具名而判通过（假绿）。修法不是放宽门禁，而是把
        #   「用户确认过」在确认轮就记住：安全性质不变（仍需用户明确确认 + 存在已校验的
        #   待执行目标工具，且写成功后清除）。
        if pending and pending.get("target_tool") and (
                is_card_confirm or _is_explicit_confirmation(last_user_msg or "")):
            _f = dict(full)
            _f["confirmed_write_tool"] = pending["target_tool"]
            await store.commit(state["session_id"], _f)
            logger.info(
                f"[pending-validated] 确认已记录 → confirmed_write_tool="
                f"{pending['target_tool']}（形态={'卡片点击' if is_card_confirm else '文本确认'}）"
                f" | session={state['session_id']}"
            )

        if not pending:
            return system_prompt
        hint = format_execution_hint(pending)
        logger.info(
            f"[pending-validated] Injecting execution hint for {pending.get('target_tool')}."
            f"{pending.get('target_action')} | session={state['session_id']}"
        )
        return hint + "\n\n" + system_prompt
    except Exception as e:
        logger.warning(f"[pending-validated] inject failed (non-fatal): {e}")
        return system_prompt


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

    # ── 0. 防御层：输入/输出限制 ──
    MAX_USER_INPUT_LEN = 2000   # 单条用户消息最大字符数
    MAX_CONVERSATION_MSGS = 50  # 对话历史最大消息数
    # 速率限制：同 session 120 秒内最多 180 条消息（1.5条/秒）
    _RATE_WINDOW = 120
    _RATE_LIMIT = 180
    if session_id:
        now = time.time()
        key = f"rate:{session_id}"
        if not hasattr(execute_skill, '_rate_map'):
            execute_skill._rate_map = {}
        rm = execute_skill._rate_map
        if key not in rm:
            rm[key] = []
        rm[key] = [t for t in rm[key] if now - t < _RATE_WINDOW]
        if len(rm[key]) >= _RATE_LIMIT:
            logger.warning(f"[{skill_name}] RATE LIMITED: {len(rm[key])} msgs in {_RATE_WINDOW}s | session={session_id}")
            return {"messages": [], "final_answer": "请求过于频繁，请稍后再试。", "skill_used": skill_name}
        rm[key].append(now)
        if len(rm) > 200:  # 清理过期 session
            rm.pop(next(iter(rm)))

    # 截断超长输入
    if raw_messages and isinstance(raw_messages[-1], HumanMessage):
        content = getattr(raw_messages[-1], "content", "") or ""
        if isinstance(content, str) and len(content) > MAX_USER_INPUT_LEN:
            raw_messages[-1] = HumanMessage(content=content[:MAX_USER_INPUT_LEN] + "...")
            logger.warning(f"[{skill_name}] Input truncated: {len(content)}→{MAX_USER_INPUT_LEN} | session={session_id}")

    # 超过消息数上限时裁剪 + 友善提醒
    if len(raw_messages) > MAX_CONVERSATION_MSGS:
        raw_messages = list(raw_messages[-MAX_CONVERSATION_MSGS:])
        truncation_msg = (
            f"⚠️ 对话已达 {len(state.get('messages',[]))} 轮，历史记录已自动裁剪。"
            f"早期对话内容无法再被引用。建议新建会话以获得最佳体验。"
        )
        raw_messages.insert(0, SystemMessage(content=truncation_msg))
        logger.warning(f"[{skill_name}] History truncated: {len(state.get('messages',[]))}→{MAX_CONVERSATION_MSGS} msgs | session={session_id}")

    # 会话长度提示已移除（2026-09-08 sess_c1fce183dae24f22 复盘）：
    # 旧实现把「当前对话已持续 N 轮」提示拼入最新用户消息，污染确认守卫判定
    # （长度 >24 无法识别为确认 → 长会话写操作确认被反复拦截、死循环）。
    # 不再计算/拼接会话长度提示，用户消息原样保留。

    # ── 1. 上下文 & 工具准备 ──
    from app.memory.session_memory import SessionMemory  # noqa: F811 — 函数内多处使用
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
        # 与首轮 llm 使用同一模型，仅关闭思考（避免路由选型不一致）
        llm_no_thinking = LLMFactory.create_skill_llm(model_override=llm_model_name, force_no_think=True)
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
    identity_prefix = ""
    if user_name_raw:
        user_name_safe = user_name_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        user_role_safe = user_role_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        identity_prefix += (
            "【用户信息】当前对话用户: " + user_name_safe
            + "（角色: " + user_role_safe + "）\n"
            "【用户信息结束】\n"
        )
    # 企业信息注入：对应管理后台「企业基础信息」中的公司名称设置（identity.md 的
    # 企业名是模板措辞，实际企业名以这里为准，多租户下不再张冠李戴）
    tenant_name_raw = state.get("tenant_name", "")
    if tenant_name_raw:
        tenant_name_safe = tenant_name_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        identity_prefix += (
            "【企业信息】你当前服务的企业是「" + tenant_name_safe + "」"
            "（即该企业商家管理后台的 AI 助手）。"
            "企业名称请以此处为准，介绍自己时使用「" + tenant_name_safe + "商家管理后台的 AI 助手」。\n"
            "【企业信息结束】\n"
        )
    if identity_prefix:
        system_prompt = identity_prefix + "\n" + system_prompt
    system_prompt = _build_system_prompt(skill_name, inline_prompt=system_prompt)

    # 4b. C 端长期记忆注入（issue #2815：仅 xiaobu；mibao 不注入）
    system_prompt = await _inject_user_memories(system_prompt, state)

    # 4c. 建议个性化偏好注入（issue #2997：flag 门控默认关闭；仅 xiaobu）
    system_prompt = await _inject_user_preferences(system_prompt, state)

    # 4d. 确认-执行链「已校验待执行」注入（issue #3031：确认轮直接执行写工具）
    # last_user_msg 需在此处可用：从 raw_messages 反向取最后一条 HumanMessage
    _confirm_msg = ""
    for _m in reversed(raw_messages):
        if isinstance(_m, HumanMessage):
            _confirm_msg = _extract_content(_m)
            break
    system_prompt = await _inject_pending_validated(system_prompt, state, _confirm_msg)
    # 4e. 写工具缺参等待期注入（issue #3365，OR-017）：顾客欠验证码等参数时，
    # 明令"索要参数、禁止重复调用、禁止重发同一张确认卡"——模型层不遵从是死循环的真因。
    system_prompt = await _inject_write_input_recovery(system_prompt, state, _confirm_msg)

    if is_multimodal:
        system_prompt = (
            "【图片理解能力已启用】您可以识别和分析用户上传的图片内容。\n"
            "当用户上传图片时，请：\n"
            "1. 仔细观察图片内容，识别其中的关键信息\n"
            "2. 根据用户的提问，结合图片内容给出准确回答\n"
            "3. 如果图片中包含可操作的信息，可以主动建议使用相关工具处理\n\n"
            + VISION_CLARIFY_GUIDE
            + "\n\n"
            + system_prompt
        )

    # ── 5. 跨轮上下文注入 ──
    cached_vision = ""
    if not is_multimodal and session_id:
        try:
            cached_vision = await SessionMemory().get_vision_analysis(session_id)
        except Exception as e:
            logger.warning(f"[{skill_name}] get_vision_analysis failed | session={session_id} error={e}")

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

    full_messages.extend(msg_list)
    # ── 5.5 跨 Skill 上下文注入 + 对话压缩 + 记录当前 skill ──
    ctx_text = ""
    compression_text = ""
    if session_id:
        try:
            from app.memory.context_manager import get_context_manager
            ctx_mgr = get_context_manager()
            await ctx_mgr.load(session_id)  # Redis 恢复
            # T1 主题域切换：先记录切换（异域时旧域实体标 stale），再更新当前 skill
            ctx_mgr.record_domain_switch(session_id, skill_name)
            ctx_mgr.set_last_skill(session_id, skill_name)
            ctx_text = ctx_mgr.build_context(session_id, skill_name)
            # 对话压缩：超过 20 条消息时只保留最近 12 条，其余生成摘要
            if len(msg_list) > 20:
                compression_text = await ctx_mgr.compress_conversation(session_id, msg_list, max_recent=12)
                if compression_text:
                    logger.info(f"[{skill_name}] Compressed conversation: {len(msg_list)}→12 msgs | session={session_id}")
                    msg_list = msg_list[-12:]  # 只保留最近 12 条
            if ctx_text:
                logger.info(f"[{skill_name}] Injected cross-skill context: {len(ctx_text)} chars | session={session_id}")
        except Exception as e:
            logger.warning(f"[{skill_name}] Context manager failed: {e} | session={session_id}")

    full_msg_parts = [system_prompt]
    if compression_text:
        full_msg_parts.append("\n" + compression_text)
    if ctx_text:
        full_msg_parts.append("\n" + ctx_text)
    full_messages.insert(0, SystemMessage(content="\n\n".join(full_msg_parts)))

    # ── 6. Vision 分支 ──
    new_messages: List[Any] = []
    final_content = ""
    _denial_corrected = False      # 文本级能力误宣只纠正一次（issue #3443）
    _no_card_blocked_args = None   # 本轮"没发过确认卡就写单"被拦的参数（issue #3445 代码兜底）
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
                llm_breaker = get_breaker(llm_breaker_name(skill_name))

                async def _vision_invoke():
                    return await asyncio.wait_for(llm.ainvoke(full_messages),
                                                  timeout=LLM_CALL_TIMEOUT_S)

                response: AIMessage = await call_with_retry(lambda: llm_breaker.call(_vision_invoke))
                _track_llm_cost(response, model=llm_model_name, tenant_id=state.get("tenant_id"), session_id=session_id)
                vision_analysis = _extract_content(response) or (
                    response.content if isinstance(response.content, str) else str(response.content)
                )
                logger.info(f"[{skill_name}] Vision completed | len={len(vision_analysis)}")
                # issue #2914：vision 偶发输出只有概括、没有实体的弱分析（如"受图片分辨率限制…"）。
                # 空或弱分析重试一次；重试后仍弱则清空（不缓存、走兜底），防弱结果毒化会话后续轮次。
                if _vision_retry_needed(vision_analysis, vision_attempt):
                    logger.warning(
                        f"[{skill_name}] Vision returned degraded/empty analysis, retrying "
                        f"| attempt={vision_attempt+1}/2 session={session_id}"
                    )
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

        # 重试后仍弱 → 清空，不缓存不注入（防"你识别不出颜色?"拿到缓存的弱文本）
        if vision_analysis:
            vision_analysis = _usable_vision_analysis(vision_analysis)
            if not vision_analysis:
                logger.warning(f"[{skill_name}] Vision degraded after retry, discarding (no cache) | session={session_id}")

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
                # 切片 C：vision 分析全文落上下文槽，跨 skill 召回「图=什么」（G10 收口）
                try:
                    from app.memory.context_manager import get_context_manager
                    ctx_mgr = get_context_manager()
                    ctx_mgr.record_vision_analysis(session_id, vision_analysis)
                except Exception as e:
                    logger.warning(f"[{skill_name}] record_vision_analysis failed | session={session_id} error={e}")

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
                llm_no_thinking = LLMFactory.create_skill_llm(model_override=llm_model_name, force_no_think=True)
                llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)

    # ── 7. ReAct 循环 ──
    if not is_multimodal or (is_multimodal and vision_analysis):
        # 取消检测（生产回归修复：原实现纯关键词子串匹配，
        # "回归测试取消Z03"这类商品名、"帮我取消订单X"这类业务动作都被误判为取消指令）
        last_user_msg = ""
        for m in reversed(raw_messages):
            if isinstance(m, HumanMessage):
                last_user_msg = _extract_content(m)
                break
        # 只有在**确实有在办流程**时才允许"取消"短路（验收发现，issue #3367）。
        # 实证（验收剧本 C-A2，transcripts/ci-34730957920）：
        #   顾客「算了，先看看你们有什么窗帘」→ AI「好的，**已取消**。」且**零工具调用**。
        # 两处危害：① 假状态变更（什么都没在办却说"已取消"，顾客可能以为订单被撤了）；
        #           ② 整句吞掉真实诉求（"看看有什么窗帘"没有触发 product_search）。
        # 判据：pending 流程标记 / pending_interact_skill / 历史里未完结的交互卡 —— 三者皆无
        # 就说明"没有东西可取消"，此时应正常处理顾客这句话（该搜索就搜索）。
        _pending_validated = False
        if session_id:
            try:
                from app.memory.session_state_store import SessionStateStore
                from app.graph.pending_validated import PENDING_KEY
                _full_cancel = await SessionStateStore().load(session_id) or {}
                _pending_validated = bool(_full_cancel.get(PENDING_KEY))
            except Exception:
                _pending_validated = False
        _inflight = _pending_card_before_last_user(state.get("messages", [])) or _pending_validated
        # 验证码轮记账（issue #3379 P2-1）：顾客先给码、下一轮回「确认」是**正常流程**，
        # 不记就会在写工具那一步要求顾客**再发一次码**（验收 C-A1 R7 空转的根因）。
        if session_id and extract_sms_code(last_user_msg):
            await _remember_sms_code(session_id, last_user_msg)

        if _is_cancel_message(last_user_msg) and _inflight:
            logger.info(f"[{skill_name}] Cancel detected | session={session_id} "
                        f"msg={last_user_msg[:24]!r}")
            final_content = "好的，已取消。有什么其他需要帮您的吗？"
            new_messages.clear()
            if session_id:
                try:
                    await SessionMemory().clear_pending_skill(session_id)
                except Exception:
                    pass
        else:
            if _is_cancel_message(last_user_msg) and not _inflight:
                logger.info(
                    f"[{skill_name}] 「取消」类措辞但无在办流程 → 不短路，按正常诉求处理 "
                    f"| session={session_id} msg={last_user_msg[:24]!r}")
            # 本轮**模型自己执行过**的工具名（供 8.4 收口判重：防双单）
            _executed_tools: set = set()
            for iteration in range(max_iterations):
                logger.info(f"[{skill_name}] Iteration {iteration+1}/{max_iterations} | session={session_id}")

                # 首轮保持 thinking（规划工具调用）
                # 迭代 2+ 轮：多步推理意图保留 thinking（工具结果可能驱动新一轮规划），
                # 单步检索意图关闭 thinking 以节省 5-8s/轮（仍保留工具绑定，支持多步工具调用）
                if iteration == 0:
                    current_llm = llm_with_tools
                elif intent_name in _MULTI_TURN_THINKING_INTENTS:
                    current_llm = llm_with_tools
                else:
                    current_llm = llm_no_thinking or llm_with_tools

                # ── LLM 调用（超时 + 熔断保护）──
                try:
                    logger.info(f"[{skill_name}][DIAG] LLM calling | iter={iteration+1} msgs={len(full_messages)+len(new_messages)} session={session_id}")
                    llm_breaker = get_breaker(llm_breaker_name(skill_name))

                    async def _llm_invoke():
                        return await asyncio.wait_for(
                            current_llm.ainvoke(full_messages + new_messages),
                            timeout=LLM_CALL_TIMEOUT_S,
                        )

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
                    # 能力误宣（issue #3443）：文本里"我做不了下单"→ 带纠正提示**重答一次**
                    # （只一次，防死循环）。重答走完整循环，故模型可以继续调工具把单下掉。
                    _denial_hit = capability_denial_text_hit(new_text)
                    if _denial_hit and not _denial_corrected and _has_order_write_tool(skill_name, skill_registry):
                        _denial_corrected = True
                        logger.warning(
                            f"[{skill_name}] 拦截文本级能力误宣并重答 | session={session_id} "
                            f"hit={_denial_hit!r}")
                        new_messages.append(SystemMessage(content=_TEXT_DENIAL_CORRECTIVE))
                        continue
                    if new_text:
                        final_content = new_text
                    elif not final_content:
                        final_content = "抱歉，我暂时无法生成回复，请换个方式描述您的需求。"
                    break

                # ── 执行 Tool 调用（并发）──
                # 本轮「同轮重复写调用」去重槽（issue #3361）：见下方 _run_one_tool 内的说明。
                # 每轮重置：去重范围严格限定在**同一次 LLM 回复**内，绝不跨轮/跨时间窗。
                _turn_write_slots: dict = {}

                async def _run_one_tool(tool_call: dict):
                    """执行单个 tool，返回 (tool_call, result_str, result_dict)。"""
                    # 需要 nonlocal：门禁在下面给 `_no_card_blocked_args` 赋值，而它是
                    # `execute_skill` 的局部变量 —— 不加 `nonlocal` 会创建一个**新局部**，
                    # 收尾的"补发确认卡"永远读不到（首版即此错，被新增用例当场抓住）。
                    nonlocal _no_card_blocked_args
                    tool_name = tool_call["name"]
                    args = tool_call.get("args", {})
                    # 模式 C 代码兜底：加工项 choice 卡漏传 multiSelect → 自动补 true（PR-014/015）
                    args = _ensure_processing_items_multiselect(tool_name, args)
                    # 代码兜底：顾客上一条就是验证码，但模型调 order_create 时没带上
                    # → 自动补齐（issue #3365 实证：CI 里 order_create!缺少短信验证码 ×3，
                    #   顾客明明给了 123456；模型漏参 → 订单不落库 → 用例红且看着像"能力不行"）
                    if tool_name == "order_create" and not (args or {}).get("sms_code"):
                        # 回填链（issue #3379 P2-1）：
                        #   ① 顾客上一条消息整条就是验证码（原有）；
                        #   ② **本会话此前记住的验证码** —— 顾客先给码、再回「确认」时，
                        #      上一轮已经不是码了，若不记就会要求顾客**再发一次**
                        #      （验收 C-A1 实证：验证码轮空转、AI 还说"稍后还需要您手机验证"）。
                        _code = extract_sms_code(last_user_msg) or await _stored_sms_code(session_id)
                        if _code:
                            args = {**args, "sms_code": _code}
                            logger.info(
                                f"[{skill_name}] 代码补齐 order_create.sms_code"
                                f"（{'本轮消息' if extract_sms_code(last_user_msg) else '会话记住的验证码'}）"
                                f"| session={session_id}"
                            )
                    if args is not tool_call.get("args"):
                        tool_call = {**tool_call, "args": args}
                    # ── 缺参等待期拦截（issue #3365，OR-017）──
                    # 顾客欠参数期间：不放行同一个写工具（注定失败）、不放行逐字重发的同一张
                    # 确认卡（死循环）。见 _write_input_recovery_block 的实证说明。
                    _blocked = await _write_input_recovery_block(
                        tool_name, args, tool_call, session_id, skill_name, last_user_msg)
                    if _blocked is not None:
                        return _blocked
                    _blocked2 = await _card_loop_block(
                        tool_name, args, tool_call, session_id, skill_name)
                    if _blocked2 is not None:
                        return _blocked2
                    # ── 掩码形态手机号拦截（issue #3386，DB 实证静默脏数据）──
                    # 在写工具真正执行**之前**：`13800008000` 这种"星号填 0"的形态能通过
                    # 11 位格式校验，一旦放行就是无告警的错号码落库。
                    # 只拦**写**工具：脏数据风险来自"用掩码值建单"，只读查询用掩码值只是
                    # 查不到，拦它反而多一轮往返。判据用 `tool.read_only`（`tool` 就在下面
                    # 解析 —— 放到解析之后，守卫内不再查 registry，避免"注册表拿不到工具
                    # → 静默放行"的假守卫）。
                    tool = skill_registry.get_tool(tool_name)
                    if tool is None:
                        logger.warning(f"[{skill_name}] Tool not found: {tool_name} | session={session_id}")
                        return tool_call, json.dumps({"success": False, "error": "tool_not_found", "message": f"工具 {tool_name} 不可用"}, ensure_ascii=False), {"success": False}
                    # 数量口径产出层守卫（issue #3402）：顾客已报数量时不得给"用量/褶皱倍数"选项
                    _blocked_q = await _quantity_choice_block(
                        tool_name, args, tool_call, session_id, skill_name, state)
                    if _blocked_q is not None:
                        return _blocked_q
                    # 收货信息预填保真守卫（issue #3397）：interact 是只读工具，单独接。
                    _blocked_prefill = await _form_prefill_fidelity_block(
                        tool_name, args, tool_call, session_id, skill_name,
                        last_user_msg, state)
                    if _blocked_prefill is not None:
                        return _blocked_prefill
                    # 算料前提守卫（issue #3395）：只读工具，故在读写分流之前单独接。
                    _blocked_calc = await _curtain_calc_dimension_block(
                        tool_name, args, tool_call, session_id, skill_name, state)
                    if _blocked_calc is not None:
                        return _blocked_calc
                    if not getattr(tool, "read_only", False):
                        _blocked3 = await _masked_phone_write_block(
                            tool_name, args, tool_call, session_id, skill_name,
                            last_user_msg, state)
                        if _blocked3 is not None:
                            return _blocked3
                    # ── 兜底：C 端在办流程中禁止「无信号误转人工」（CH-012 实证）──
                    # R1 已下发选单卡、R3 用户仅回「质量问题」，agent 却 human_handoff
                    # （还创建了投诉工单）→ 流程被放弃、轮数耗尽、aftersale_create 未发生。
                    # 判据与 handoff_judge 同源：显式请求 / 负面情绪 / 能力外诉求 三者皆无
                    # → 不是用户要的转人工，而是模型放弃流程 → 阻止并给出可执行指引。
                    if (tool_name == "human_handoff"
                            and skill_name in ("customer_order", "customer_aftersales")):
                        from app.graph.handoff_judge import has_escalation_signal
                        # 在办判据两条取并集（issue #3361 实证）：
                        #   ① 消息历史里能扫到未完结的交互卡（原实现）；
                        #   ② **跨轮持久化的 pending_interact_skill 非空** —— 这是
                        #      「流程锁定中」的权威标记（卡片发出即写、写操作成功即清），
                        #      不依赖 state["messages"] 是否带回上一轮的 ToolMessage。
                        # 为何 ② 必需（CI run 34689293179，CH-012）：R1 已下发选单卡、
                        # R2 顾客点明订单、R3 顾客只回退货原因「质量问题」，agent 直接
                        # human_handoff（并建了投诉工单）→ 流程被放弃、aftersale_create
                        # 未发生；当时 ① 判为 False（历史里扫不到那张卡）→ 兜底形同虚设。
                        _inflight = bool(state.get("pending_interact_skill")) or \
                            _has_inflight_interactive_card(state.get("messages", []))
                        # 能力误宣（issue #3389）：以"我下不了单/无法代为提交订单"为理由转人工，
                        # 无论有没有在办卡都拦 —— 这是**能力否定**，不是顾客诉求。
                        _denial = _capability_denial_reason(args)
                        if _denial and not has_escalation_signal(last_user_msg):
                            logger.warning(
                                f"[{skill_name}] 拦截能力误宣式转人工 | session={session_id} "
                                f"reason={_denial!r}")
                            _msg = (
                                f"你的转人工理由写的是「{_denial}」—— 但**你能下单**："
                                f"`order_create` 就是本流程的写工具（参数齐了就能真实落单）。"
                                f"「无法代为提交订单」属**能力误宣**：顾客明明要买，"
                                f"却被告知系统做不到，转化路径被自己掐断。"
                                f"正确做法：缺收货信息就先 `customer_address_query` 查历史地址，"
                                f"没有再发 `interact(component=form)` 或用自然语言问姓名/手机号/地址；"
                                f"参数齐了走 confirm 卡 → `validate_input` → `order_create`（含 sms_code）。"
                                f"只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。")
                            return (tool_call,
                                    json.dumps({"success": False,
                                                "error": "handoff_blocked_capability_denial",
                                                "message": _msg}, ensure_ascii=False),
                                    {"success": False, "error": "handoff_blocked_capability_denial"})
                        # 补一条（issue #3421，C-A1 实证）：顾客**正在下单**且流程**已真实启动**
                        # （查过商品详情）时，即使没有待答卡片，无信号转人工也是放弃流程。
                        # 不这么做会漏掉 C-A1 的形态：卡片已被顾客点掉 → `_inflight` 为假 →
                        # 放行转人工 → 9 轮不下单（L1 违规 3 条）。
                        if (not has_escalation_signal(last_user_msg)
                                and not _inflight
                                and _has_ordering_intent(last_user_msg)
                                and await _order_flow_started(session_id, state)):
                            logger.warning(
                                f"[{skill_name}] 拦截「顾客在下单却无信号转人工」 | "
                                f"session={session_id} last_msg={last_user_msg[:30]!r}")
                            _msg2 = (
                                "顾客正在下单（本轮消息仍在推进下单），且本会话已经查过商品详情 —— "
                                "**不要转人工**：`order_create` 就是本流程的写工具，参数齐了就能真实落单。"
                                "缺收货信息就先 `customer_address_query` 查历史地址，没有再发 "
                                "`interact(component=form)` 或直接问；然后走 confirm 卡 → "
                                "`validate_input` → `order_create`（含 sms_code）。"
                                "只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。")
                            return (tool_call,
                                    json.dumps({"success": False,
                                                "error": "handoff_blocked_inflight",
                                                "message": _msg2}, ensure_ascii=False),
                                    {"success": False, "error": "handoff_blocked_inflight"})
                        if not has_escalation_signal(last_user_msg) and _inflight:
                            logger.warning(
                                f"[{skill_name}] 拦截在办流程中的无信号转人工 | session={session_id} "
                                f"last_msg={last_user_msg[:30]!r}"
                            )
                            # 拦截话术必须**可执行**（issue #3361，CI run 34703192730 实证）：
                            # CH-012 R2/R3/R4 每轮都被拦（handoff_blocked_inflight ×3），
                            # 但模型只是**反复重试 human_handoff**、始终不调 aftersale_create
                            # → 流程原地打转、售后单永不创建（复现型红灯）。
                            # 原话术只说"请继续完成当前流程"，没点出**下一步该调哪个工具** ——
                            # 模型读到了"不许转人工"，却不知道"那该干什么"。
                            # 与确认门禁同一手法：把可执行动作（工具名）写进 tool result。
                            _flow_hint = ""
                            for _flow_tool, _hint in (
                                ("aftersale_create",
                                 "顾客是在办**售后**（退货/换货/退款/维修）：请先与顾客确认订单与原因"
                                 "（interact 卡），然后调用 aftersale_create 创建工单"
                                 "（order_id 用已查到的订单号）"),
                                ("order_create",
                                 "顾客是在办**下单**：请继续收齐信息并调用 order_create 完成下单"),
                            ):
                                try:
                                    if skill_registry.get_tool(_flow_tool) is not None:
                                        _flow_hint = _hint
                                        break
                                except Exception:
                                    continue
                            _msg = (
                                "顾客正在办理的业务尚未完成，且本轮消息没有要求转人工、"
                                "没有情绪激动、也不涉及赔偿/法律。**不要再次调用 human_handoff**，"
                                "继续完成当前流程。"
                                + (_flow_hint + "。" if _flow_hint else "请按交互卡与提示继续下一步。")
                                + "若顾客确实要求人工，需其明确说出「转人工/找人工/找客服」"
                                "后再调用本工具。"
                            )
                            return tool_call, json.dumps({
                                "success": False,
                                "error": "handoff_blocked_inflight",
                                "message": _msg,
                            }, ensure_ascii=False), {"success": False, "error": "handoff_blocked_inflight"}

                    # ── 下单接地闸门（issue #3361，OR-014 复现型红灯）──
                    # 实证：C 端「帮我下单，遮光窗帘 3 米，要打孔加工」时模型**一次都没查商品**
                    # （R1 tools=-），凭记忆发确认卡（金额 ¥95.4，而该商品真实单价 ¥168/米）
                    # 并直接下单 → 单价/加工项/金额全不可信，且用例期望的 product_detail 缺失。
                    # prompt 里的「商品详情铁律（confirm 前必须先调 product_detail）」模型不守，
                    # 故加代码闸门：本会话没成功查过商品详情 → 不许下单，并把可执行步骤写进结果。
                    if tool_name == "order_create" and skill_name == "customer_order" and session_id:
                        _grounded = True
                        try:
                            from app.memory.session_state_store import SessionStateStore as _SG
                            _sg = await _SG().load(session_id) or {}
                            _grounded = bool(_sg.get("grounded_product_detail"))
                        except Exception as _ge:
                            logger.debug(f"[{skill_name}] ground gate check failed (non-fatal): {_ge}")
                        if not _grounded:
                            logger.warning(
                                f"[{skill_name}] 下单接地闸门：本会话未查商品详情，拦截 order_create "
                                f"| session={session_id}"
                            )
                            # ── 接地自动驾驶（issue #3365 候选修法 1）──
                            # 实证：闸门拦下后模型**只是反复重试 order_create**（CI run 34707941520
                            # 里被拦 6 次仍不搜索），提示词与拦截话术都劝不动 → 属模型层不遵从。
                            # 代码层直接代跑 product_search → product_detail（**只读**），落接地标记，
                            # 并把查到的真实单价/商品 id 回给模型，让它基于真值重新下单。
                            # 只在"能确定唯一商品"时落地（多命中则把候选交回模型，不猜）。
                            _pilot = None
                            # 关键词来自**会话里对商品的提及**，而不只是本轮消息：
                            # 实证（CI run 34709584877）—— 被拦那一轮用户发的是「确认下单」/表单回传，
                            # 本轮抽不到商品词 → 自动驾驶根本没触发（order_create 仍被拦 5 次）。
                            # 取**最早**一次商品提及（顾客最初要买什么），比最近一次更稳。
                            _kw = extract_product_keyword(last_user_msg)
                            if not _kw:
                                try:
                                    for _m in (state.get("messages") or []):
                                        if not isinstance(_m, HumanMessage):
                                            continue
                                        _kw = extract_product_keyword(_extract_content(_m) or "")
                                        if _kw:
                                            logger.info(
                                                f"[{skill_name}] 接地自动驾驶：从会话历史取得商品关键词"
                                                f"'{_kw}' | session={session_id}"
                                            )
                                            break
                                except Exception:
                                    _kw = ""
                            if _kw:
                                try:
                                    _ps = skill_registry.get_tool("product_search")
                                    _pd = skill_registry.get_tool("product_detail")
                                except Exception:
                                    _ps = _pd = None
                                if _ps is not None and _pd is not None:
                                    try:
                                        _rs, _rd = await _execute_tool_safe(
                                            _ps, {"keyword": _kw}, tool_context, state)
                                        _prods = ((_rd.get("data") or {}).get("products")
                                                  if isinstance(_rd.get("data"), dict) else None) or []
                                        if isinstance(_prods, list) and len(_prods) == 1:
                                            _pid = _prods[0].get("id") or _prods[0].get("productId")
                                            if _pid:
                                                _ds, _dd = await _execute_tool_safe(
                                                    _pd, {"product_id": _pid}, tool_context, state)
                                                if _dd.get("success"):
                                                    _data = _dd.get("data") or {}
                                                    _pilot = {
                                                        "product_id": _pid,
                                                        "name": _data.get("name") or _prods[0].get("name"),
                                                        "price": _data.get("price"),
                                                    }
                                                    from app.memory.session_state_store import (
                                                        SessionStateStore as _SP)
                                                    _sp = await _SP().load(session_id) or {}
                                                    _sp["grounded_product_detail"] = {"product_id": _pid}
                                                    await _SP().commit(session_id, _sp)
                                                    logger.warning(
                                                        f"[{skill_name}] 接地自动驾驶：代跑 "
                                                        f"product_search('{_kw}')→product_detail 完成，"
                                                        f"接地标记已落 | session={session_id}"
                                                    )
                                    except Exception as _pe:
                                        logger.debug(f"[{skill_name}] 接地自动驾驶失败（回落到话术）: {_pe}")
                            if _pilot:
                                return tool_call, json.dumps({
                                    "success": False,
                                    "error": "product_not_grounded",
                                    "message": (
                                        f"下单被拦截，但**已代为查询商品**："
                                        f"{_pilot.get('name')}（product_id={_pilot.get('product_id')}，"
                                        f"单价 ¥{_pilot.get('price')}）。请基于该真实商品与单价"
                                        f"重新组织 items 并调用 order_create；"
                                        f"加工项/规格请用 product_detail 结果中的值，不要凭记忆填。"
                                    ),
                                }, ensure_ascii=False), {"success": False, "error": "product_not_grounded"}
                            return tool_call, json.dumps({
                                "success": False,
                                "error": "product_not_grounded",
                                "message": (
                                    "下单被拦截：本会话还没有**成功查询过商品详情**"
                                    "（价格/规格/加工项都无从确认）。请**立即**按顺序执行，"
                                    "**不要重复调用 order_create**（重复无效，这是硬性前置条件）：\n"
                                    "1) product_search(keyword=顾客提到的商品名) —— 顾客说"
                                    "「遮光窗帘 3 米」就用 keyword=\"遮光窗帘\"；\n"
                                    "2) product_detail(product_id=第 1 步选中的商品)；\n"
                                    "3) 拿到真实单价/加工项/规格后，按顾客确认的信息再下单。\n"
                                    "禁止凭记忆填价格或加工项。"
                                ),
                            }, ensure_ascii=False), {"success": False, "error": "product_not_grounded"}

                    # 写操作（destructive 或 requires_confirmation 高风险写）：必须经用户明确确认
                    # （代码层兜底，防间接提示注入驱动未确认写操作，审计 07 P0-L1）
                    # 豁免：action ∈ tool.read_only_actions 的纯只读调用（list/detail/tree 等）
                    # 卡片确认优先：用户消息**精确等于**最近确认卡的 confirmValue = 用户点了
                    # 确认按钮 → 最强确认信号，直接放行（长 confirmValue 过不了 24 字上限，
                    # 见 _is_card_confirm_value —— 不加这个，mini-app 点确认卡写操作永不落库）。
                    _card_confirmed = False
                    if _requires_confirmation(tool, args, last_user_msg):
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            _store = SessionStateStore()
                            _full = await _store.load(session_id) or {}
                            _card_confirmed = _is_card_confirm_value(
                                last_user_msg, _full.get("last_confirm_value"))
                            if _card_confirmed:
                                # 记录「该写工具已获确认」：确认卡点击后，后续轮补充信息
                                # （如 customer 下单需 sms_code）不再重复要求确认。
                                # CI 实证（run 34682324499 诊断）：confirmValue 点击在上一轮，
                                # 本轮消息是验证码「123456」→ 未记录的话 order_create 被门禁拦。
                                _full["confirmed_write_tool"] = tool_name
                                await _store.commit(session_id, _full)
                                logger.info(
                                    f"[{skill_name}] 确认卡 confirmValue 精确匹配 → 放行写操作 "
                                    f"{tool_name} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] card-confirm check failed (non-fatal): {e}")
                    _write_was_confirmed = False
                    if _card_confirmed is False and _requires_confirmation(tool, args, last_user_msg):
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S3
                            _f3 = await _S3().load(session_id) or {}
                            _write_was_confirmed = _f3.get("confirmed_write_tool") == tool_name
                            if _write_was_confirmed:
                                logger.info(
                                    f"[{skill_name}] 写工具 {tool_name} 前轮已确认 → 放行 | session={session_id}"
                                )
                        except Exception as _e3:
                            logger.warning(f"[{skill_name}] confirmed_write_tool check failed (non-fatal): {_e3}")
                    if _requires_confirmation(tool, args, last_user_msg) and not _card_confirmed and not _write_was_confirmed:
                        logger.warning(
                            f"[{skill_name}] 拦截未确认的写操作 {tool_name} | session={session_id} "
                            f"last_msg={last_user_msg[:30]!r}"
                        )
                        # 诊断：为什么卡片确认没放行（stored 值 vs 本轮消息）
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S2
                            _f2 = await _S2().load(session_id) or {}
                            logger.warning(
                                f"[{skill_name}] card-confirm 诊断: stored={str(_f2.get('last_confirm_value'))[:40]!r} "
                                f"msg={last_user_msg[:40]!r} equal={_is_card_confirm_value(last_user_msg, _f2.get('last_confirm_value'))} "
                                f"| session={session_id}"
                            )
                        except Exception as _e2:
                            logger.warning(f"[{skill_name}] card-confirm 诊断失败: {_e2}")
                        # 话术必须与**本 Skill 的实际能力**匹配（issue #3317）：
                        # 未绑定 interact 的 Skill（B 端 staff/settings/data）若被告知
                        # "请调用 interact（component=confirm）"，那是一条**不可执行指令** ——
                        # 模型拿到"请调用 X"却没有 X，会反复重试或直接放弃。
                        # （不给这些 Skill 补 interact 的理由见 issue #3317：
                        #   用例库里涉及这 6 个工具的 16 条用例无一条断言 interact，
                        #   含 smoke 的 HR-001/HR-004 靠口头确认长期通过 —— 补工具是
                        #   改变 B 端交互形态，收益不明而回归面大。）
                        if skill_registry.get_tool("interact") is not None:
                            # 可执行下一步（issue #3445）：CI 实测 `confirmation_required_no_card ×3`
                            # —— 模型**从没发过确认卡**就直接写单，被拦回后仍反复重试同一个写调用、
                            # 把轮数烧完（R10 时订单仍未落库）。故话术给出**唯一可执行的下一步**：
                            #   ① 明确"再调写工具没用"（防重试）；② 指明必须调 interact(confirm)；
                            #   ③ 回填**已校验参数**（pending_validated_input）与
                            #      **本次被拦调用的字段骨架**（它自己传过的值），让它照抄即可发卡。
                            _pending_hint = ""
                            try:
                                from app.graph.pending_validated import PENDING_KEY as _PK
                                from app.graph.pending_validated import is_pending_for as _is_pending
                                from app.memory.session_state_store import SessionStateStore as _S4
                                _f4 = await _S4().load(session_id) or {}
                                _pend4 = _f4.get(_PK) or {}
                                if _is_pending(_pend4, tool_name) and _pend4.get("params"):
                                    _pending_hint = (
                                        " 已校验的参数（**原样**用作卡片 fields，不要改写）："
                                        + json.dumps(_pend4["params"], ensure_ascii=False,
                                                     default=str)[:400])
                            except Exception as _e4:
                                logger.warning(f"[{skill_name}] pending 参数回填失败（非致命）: {_e4}")
                            msg = (
                                f"工具 {tool_name} 是写操作（可能不可逆或产生数据变更），必须先向用户展示"
                                f"确认卡片并取得明确确认。**不要再次调用 {tool_name}** —— 在顾客点击"
                                f"确认卡之前它会被同样拦下、白烧一轮。本轮唯一的下一步是：调用 "
                                f"interact(component=confirm, fields=[…]) "
                                f"把将要执行的内容展示给顾客，等顾客**点击确认卡**之后再调用 {tool_name}。"
                                + _confirm_card_fields_hint(args)
                                + _pending_hint
                            )
                        else:
                            msg = (
                                f"工具 {tool_name} 是写操作（可能不可逆或产生数据变更），必须先取得用户明确"
                                f"确认。本技能没有确认卡片能力：请用文本**完整复述将要执行的操作与影响**"
                                f"（对象、字段、后果），并请用户回复确认；用户回复确认后再调用本工具。"
                            )
                        # 归因细分（issue #3445）：保留 `confirmation_required` 前缀
                        # （既有断言按子串匹配），后缀说明**是哪一种**：
                        #   · _no_card          → 本会话从没发过确认卡（模型跳过确认直接写）
                        #   · _card_not_clicked → 发过卡，但这次回复不是卡值（顾客回文本/未点卡）
                        _err3 = ("confirmation_required_card_not_clicked"
                                 if _confirm_card_seen(state.get("messages", []))
                                 else "confirmation_required_no_card")
                        if _err3 == "confirmation_required_no_card":
                            # 代码兜底（issue #3445）：本轮模型**从没发过确认卡**就写了单 ——
                            # 拦截话术已给"可执行下一步"，但实测它仍会跳过发卡（3 次复验 2 次命中）。
                            # 收尾时由代码把确认卡 XML 追加到回复文本（发射点在 chat.py 解析
                            # `<interact>` 块），顾客因此始终有点卡的入口。
                            _no_card_blocked_args = dict(args or {})
                        return tool_call, json.dumps(
                            {"success": False, "error": _err3, "message": msg},
                            ensure_ascii=False,
                        ), {"success": False, "error": _err3}
                    # ── 同轮重复写调用合并（issue #3361）──
                    # 模型有时在**同一次回复**里对同一个写工具发多次**完全相同**的调用
                    # （CI 实证 CH-010：一轮里 order_create ×3 → 2 次 tool_execution_failed、
                    # 1 次成功；幸而没变成 2 张订单，纯属运气）。
                    # 写工具刻意不走 60s 读缓存（重复的**非幂等写**不能被静默吞掉，见
                    # _execute_tool_safe 的注释）—— 但"同轮 + 同工具 + 同参数"不是新的写需求，
                    # 而是同一次意图的重复表达：合并为一次执行，其余复用同一结果。
                    # 与缓存的关键区别：作用域只有本轮（下一次回复即失效），参数不同不合并。
                    if not tool.read_only:
                        _dedupe_key = (tool_name, json.dumps(args, sort_keys=True, default=str))
                        _slot = _turn_write_slots.get(_dedupe_key)
                        if _slot is None:
                            _slot = _turn_write_slots[_dedupe_key] = {
                                "lock": asyncio.Lock(), "result": None}
                        async with _slot["lock"]:
                            if _slot["result"] is not None:
                                logger.warning(
                                    f"[{skill_name}] 同轮重复写调用已合并：{tool_name}"
                                    f"（同参数第 2+ 次，复用首次结果）| session={session_id}"
                                )
                                return tool_call, _slot["result"][0], _slot["result"][1]
                            result_str, result_dict = await _execute_tool_safe(
                                tool, args, tool_context, state)
                            _slot["result"] = (result_str, result_dict)
                    else:
                        result_str, result_dict = await _execute_tool_safe(tool, args, tool_context, state)
                    _executed_tools.add(tool_name)
                    if not result_dict.get("success") and result_dict.get("suggestion"):
                        corrected = await _self_correct_retry(tool, args, tool_context, skill_name, result_dict, session_id, tenant_id, state)
                        if corrected:
                            result_str, result_dict = corrected
                    # ── 记住读到的**真实**手机号（issue #3386 写守卫的判据来源）──
                    # 只读工具读回来的号码是权威原文（写工具的入参可能是模型填的掩码变体，
                    # 若从写结果里学号码就等于让脏数据自我合法化，故只看只读工具）。
                    if (session_id and result_dict.get("success")
                            and getattr(tool, "read_only", False)):
                        try:
                            _payload = json.dumps(result_dict.get("data"),
                                                  ensure_ascii=False, default=str)
                            _found = raw_phones_in(_payload)
                            if _found:
                                await _remember_raw_phones(session_id, _found)
                            _addr = (result_dict.get("data") or {}).get("customer_address")
                            if _addr:
                                await _remember_known_value(
                                    session_id, KNOWN_ADDRESS_KEY, str(_addr))
                        except Exception as _e7:
                            logger.warning(f"[{skill_name}] 记录真实号码失败（非致命）: {_e7}")
                    # ── 落地"本会话已查过商品详情"标记（issue #3361 下单接地闸门用）──
                    # 只在成功时写；失败不写（避免"查了但没查到"被当成接地）。
                    # 同一张交互卡的下发计数（issue #3365）：第 3 次起会被 _card_loop_block 拦下。
                    # 必须在这里（而不是外层循环）计数 —— 只有这一层拿得到 `args`（外层只有
                    # result_dict，没有调用参数；首版写在外层，运行时 NameError 被吞成
                    # "计数失败（非致命）"，计数永远为 0 = 拦不住的假守卫）。
                    if tool_name == "interact" and result_dict.get("success") and session_id:
                        _fp_emit = card_fingerprint(args)
                        if _fp_emit:
                            try:
                                from app.memory.session_state_store import SessionStateStore as _S6
                                _s6 = _S6()
                                _f6 = await _s6.load(session_id) or {}
                                _c6 = _f6.get(CARD_EMIT_COUNTS_KEY) or {}
                                if not isinstance(_c6, dict):
                                    _c6 = {}
                                _c6[_fp_emit] = int(_c6.get(_fp_emit) or 0) + 1
                                _f6[CARD_EMIT_COUNTS_KEY] = _c6
                                await _s6.commit(session_id, _f6)
                                logger.info(
                                    f"[{skill_name}] 卡下发计数 {_c6[_fp_emit]} "
                                    f"({_fp_emit[:60]}) | session={session_id}"
                                )
                            except Exception as _e6:
                                logger.warning(f"[{skill_name}] 卡下发计数失败（非致命）: {_e6}")
                    if tool_name == "product_detail" and result_dict.get("success") and session_id:
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            _gs = SessionStateStore()
                            _g = await _gs.load(session_id) or {}
                            _g["grounded_product_detail"] = {
                                "product_id": str((result_dict.get("data") or {}).get("id") or ""),
                            }
                            await _gs.commit(session_id, _g)
                        except Exception as _e:
                            logger.debug(f"[{skill_name}] ground flag persist failed (non-fatal): {_e}")
                    return tool_call, result_str, result_dict

                tool_results = await asyncio.gather(*[_run_one_tool(tc) for tc in response.tool_calls])

                # ── 模式 C 代码兜底：加工项漏问 → confirm 卡改写为加工项 choice 卡（OR-017）──
                # 仅作用于 C 端下单/售后写流程：这些 Skill 的商品详情含加工项数据、
                # 且业务铁律要求 confirm 前必须先问。B 端流程不动。
                if skill_name in ("customer_order", "customer_aftersales"):
                    try:
                        _proc_msgs = new_messages + state.get("messages", [])
                        _proc_pid = _last_product_id(_proc_msgs)
                        # 跨轮已问过（同一商品）→ 不再改写：否则模型的 confirm 卡会被无限
                        # 改写成同一张加工项卡，confirm 永远落不了地（OR-017 实测 4 次）。
                        _proc_asked = await _processing_items_already_asked(session_id, _proc_pid)
                        plan = None if _proc_asked else _plan_processing_items_rewrite(tool_results, _proc_msgs)
                        if plan is not None:
                            idx, choice_data = plan
                            _tc, _rs, rd = tool_results[idx]
                            rd = dict(rd)
                            rd["data"] = choice_data
                            rd["message"] = f"已展示{choice_data['title']}（代码兜底：LLM 漏问加工项，confirm 卡改写为 choice 卡）"
                            result_str_new = json.dumps(rd, ensure_ascii=False, default=str)
                            tool_results[idx] = (_tc, result_str_new, rd)
                            logger.info(
                                f"[{skill_name}] 加工项漏问兜底：confirm 卡改写为加工项 choice 卡 "
                                f"(options={len(choice_data['options'])}) | session={session_id}"
                            )
                        # 记账：本轮任何一张加工项卡发出去过（改写来的或模型自己发的）→ 记「已问过」
                        if any(
                            (rd or {}).get("success")
                            and str((rd or {}).get("data", {}).get("component") or "") == "choice"
                            and _is_processing_items_card((rd or {}).get("data") or {})
                            for _tc, _rs, rd in tool_results
                        ):
                            await _mark_processing_items_asked(session_id, _proc_pid)
                    except Exception as e:
                        logger.warning(f"[{skill_name}] processing-items fallback failed (non-fatal): {e}")

                for tool_call, result_str, result_dict in tool_results:
                    tool_name = tool_call["name"]
                    # 记录 tool 结果到 ContextManager，跨 skill 共享
                    if session_id and result_dict.get("success"):
                        try:
                            from app.memory.context_manager import get_context_manager
                            mgr = get_context_manager()
                            mgr.record_tool_result(session_id, tool_name, result_dict)
                            await mgr.save(session_id)  # Redis 持久化
                        except Exception:
                            pass
                    # ── 确认-执行链状态（issue #3031）──
                    # validate_input 通过 → 持久化「已校验待执行」状态，下一轮确认时
                    # 直接执行写工具，不再从零重走 validate+interact（sess_50ff 三张 confirm 卡根因）。
                    if session_id and tool_name == "validate_input" and result_dict.get("success"):
                        try:
                            pending = extract_pending(tool_call.get("args") or {})
                            if pending:
                                from app.memory.session_state_store import SessionStateStore
                                store = SessionStateStore()
                                full = await store.load(session_id) or {}
                                full[PENDING_KEY] = pending
                                await store.commit(session_id, full)
                                logger.info(
                                    f"[{skill_name}] Pending validated persisted: "
                                    f"{pending['target_tool']}.{pending['target_action']} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] pending_validated persist failed (non-fatal): {e}")
                    # 缺参失败 → 跨轮记账（下一轮注入索要指令 + 拦截重复动作，issue #3365）
                    # 清除只认**同一把工具**成功：product_search 之类只读工具成功不能清账，
                    # 否则欠参标记被顺手抹掉、下一轮又回到"重发卡 + 重复调用"的老路。
                    if session_id and tool_name != "validate_input":
                        _param = "" if result_dict.get("success") else missing_input_param(
                            result_dict.get("error") or "")
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S5
                            _s5 = _S5()
                            _f5 = await _s5.load(session_id) or {}
                            _prev5 = _f5.get(WRITE_INPUT_ERROR_KEY) or {}
                            if _param and _param not in RECOGNIZABLE_INPUT_PARAMS:
                                _param = ""   # 判不出"已补齐"的参数不记账（否则永久锁死该工具）
                            if _param:
                                _f5[WRITE_INPUT_ERROR_KEY] = {
                                    "tool": tool_name,
                                    "param": _param,
                                    "error": str(result_dict.get("error") or ""),
                                    "message": str(result_dict.get("message") or ""),
                                }
                                await _s5.commit(session_id, _f5)
                                logger.info(
                                    f"[{skill_name}] 缺参记账 {tool_name}.{_param} | session={session_id}"
                                )
                            elif result_dict.get("success") and _prev5.get("tool") == tool_name:
                                await _s5.commit(session_id, _clear_write_input_error(_f5))
                                logger.info(
                                    f"[{skill_name}] {tool_name} 成功 → 清除欠参标记 | session={session_id}"
                                )
                        except Exception as _e5:
                            logger.warning(f"[{skill_name}] 缺参记账失败（非致命）: {_e5}")
                    # 写工具执行成功 → 清除对应「已校验待执行」状态与「已确认写工具」标记
                    # （闭环完成；否则后续同类写操作会在无新确认的情况下被放行）。
                    if session_id and result_dict.get("success") and tool_name != "validate_input":
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S4
                            _f4 = await _S4().load(session_id) or {}
                            if _f4.get("confirmed_write_tool") == tool_name:
                                _f4.pop("confirmed_write_tool", None)
                                await _S4().commit(session_id, _f4)
                        except Exception as _e4:
                            logger.warning(f"[{skill_name}] confirmed_write_tool clear failed (non-fatal): {_e4}")
                    # 注意：不能依赖 result_dict["terminal"] —— after_sales_manage(create) 等
                    # B 端写工具不返回 terminal=True（仅 order_create/aftersale_create/human_handoff
                    # 有），依赖 terminal 会导致售后换货的 pending 执行成功后残留。
                    # 正确判定：pending.target_tool 匹配当前工具 + 执行成功 → 清除。
                    if session_id and result_dict.get("success") and tool_name != "validate_input":
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            store = SessionStateStore()
                            full = await store.load(session_id) or {}
                            pending = full.get(PENDING_KEY)
                            if is_pending_for(pending, tool_name):
                                full.pop(PENDING_KEY, None)
                                await store.commit(session_id, full)
                                logger.info(
                                    f"[{skill_name}] Pending validated cleared after {tool_name} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] pending_validated clear failed (non-fatal): {e}")
                    # T2 事务终态：terminal 工具成功后重置当前域上下文（草稿/实体/待确认）
                    if session_id and result_dict.get("success") and result_dict.get("terminal"):
                        try:
                            from app.memory.context_manager import get_context_manager
                            mgr = get_context_manager()
                            mgr.reset_domain(session_id, skill_name)
                            await mgr.save(session_id)
                            logger.info(
                                f"[{skill_name}] Terminal tool {tool_name} — domain context reset | session={session_id}"
                            )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] Terminal reset failed | session={session_id} error={e}")
                    new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"], name=tool_name))
                    if tool_name == "interact" and result_dict.get("success"):
                        try:
                            await SessionMemory().set_pending_skill(session_id, skill_name)
                        except Exception:
                            pass
                        # 记录最近一次确认卡的 confirmValue（会话状态）：下一轮用户点击
                        # 回传的正是这个值 —— 精确匹配它 = 显式确认（见 _is_card_confirm_value）。
                        # 否则长 confirmValue（工具描述强制含上下文）过不了 24 字上限，
                        # 写操作永不落库（run 34678939564 + DB 审计实证假绿）。
                        try:
                            _data = result_dict.get("data") or {}
                            if _data.get("component") == "confirm" and _data.get("confirmValue"):
                                from app.memory.session_state_store import SessionStateStore
                                _store = SessionStateStore()
                                _full = await _store.load(session_id) or {}
                                _full["last_confirm_value"] = str(_data["confirmValue"])
                                await _store.commit(session_id, _full)
                                logger.info(
                                    f"[{skill_name}] last_confirm_value 持久化: "
                                    f"{str(_data['confirmValue'])[:40]} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] last_confirm_value persist failed (non-fatal): {e}")
            else:
                # 达到 max_iterations — 不暴露 LLM 的半截思考，用友好兜底
                final_content = "抱歉，处理步骤较多，请稍后重试或换个简单的方式描述需求。"

    # ── 8.3b 代码兜底**补发确认卡**（issue #3445）──
    # 实测（CI 三次 `confirmation_required_no_card`）：模型**从没发过确认卡**就直接写单，
    # 被门禁拦回后仍会跳过发卡（话术已给唯一可执行的下一步，3 次复验仍有 2 次命中）。
    # 卡片的唯一通用发射点是 `chat.py` 解析回复文本里的 `<interact>` 块 ⇒ 这里把卡补进文本：
    # 顾客因此始终有点卡的入口，而不是"卡在写单被拦、又没有卡可点"。
    # 硬约束（#3414 教训）：**只补卡、不放行写** —— 写仍必须等顾客点卡后由门禁放行；
    # 且仅在"本会话从未出现过确认卡"的形态下补（`card_not_clicked` 说明顾客没点，
    # 那时替他补卡等于替他做决定，不做）。
    if (_no_card_blocked_args and skill_name == "customer_order"
            and final_content and "<interact>" not in final_content):
        _bfields = confirm_card_fields(_no_card_blocked_args)
        if _bfields:
            final_content = final_content + "\n" + build_confirm_interact_xml(
                "请确认订单信息", _bfields,
                confirm_value=confirm_value_for_fields(_bfields))
            logger.info(
                f"[{skill_name}] 代码兜底补发确认卡（模型跳过确认卡）| "
                f"session={session_id} fields={len(_bfields)}")

    # ── 8.4 确认-执行链的**代码侧收口**（issue #3410，C-A1 实证）──
    # 实证（run 34758421478，C-A1 主路径）：顾客点了确认（回传系统自产的确认卡值），
    # 模型回「这就帮您提交~」，随后两轮顾客又说「确认下单」，模型答「都核对好啦」「还差最后一步」
    # —— **整场没有 order_create 调用**，订单永不落库、验收 L1 报「order_create 未调用」；
    # 同一剧本别的轮次却通过（模型碰巧动手）→ 间歇性失败。
    # 既有机制（`_inject_pending_validated`）只做到"注入执行提示"，**动不动手仍由模型决定**。
    # 这里把收口前移到代码：顾客已明确确认 + 存在已校验待执行写 + 本轮模型没调那个工具
    # → **代码直接执行**（同一条执行路径：同样的确认门禁状态、同样的验证码回填链），
    # 并用工具返回的 message 作为给顾客的回复（说真话，而不是"这就帮您提交"）。
    # 只对 C 端生效（分端纪律）：B 端写流程各异，待 B 端有分支级回归证据后再评估。
    if session_id and _is_customer_role(state):
        try:
            from app.memory.session_state_store import SessionStateStore as _S8
            _f8 = await _S8().load(session_id) or {}
            _pending8 = _f8.get(PENDING_KEY)
            _cv8 = _f8.get("last_confirm_value")
            _confirmed8 = (_is_explicit_confirmation(last_user_msg or "")
                           or _is_card_confirm_value(last_user_msg or "", _cv8))
            _target8 = str((_pending8 or {}).get("target_tool") or "")
            if _should_code_close_loop(_pending8, _target8, _confirmed8, _executed_tools):
                _tool8 = skill_registry.get_tool(_target8)
                if _tool8 is not None:
                    _args8 = dict((_pending8.get("params") or {}))
                    # 只在该工具**确实声明了 action** 时才带 action（C 端 order_create 没有）
                    try:
                        _props8 = ((getattr(_tool8, "parameters", None) or {}).get("properties") or {})
                    except Exception:
                        _props8 = {}
                    if "action" in _props8 and _pending8.get("target_action"):
                        _args8.setdefault("action", str(_pending8["target_action"]))
                    # 验证码回填链（与门禁同源）：本轮消息里的码 → 会话记住的码
                    if _target8 in SMS_GATED_WRITE_TOOLS and not _args8.get("sms_code"):
                        _code8 = extract_sms_code(last_user_msg) or await _stored_sms_code(session_id)
                        if _code8:
                            _args8["sms_code"] = _code8
                    _ctx8 = build_tool_context(state)
                    _str8, _res8 = await _execute_tool_safe(_tool8, _args8, _ctx8, state)
                    new_messages.append(ToolMessage(
                        content=_str8, tool_call_id=f"closure_{_target8}", name=_target8))
                    _executed_tools.add(_target8)
                    logger.info(
                        f"[{skill_name}] 确认收口：模型未发起写，代码执行 {_target8} "
                        f"success={bool((_res8 or {}).get('success'))} | session={session_id}")
                    _msg8 = str((_res8 or {}).get("message") or "").strip()
                    if _msg8:
                        final_content = _msg8
                    if (_res8 or {}).get("success") and is_pending_for(_pending8, _target8):
                        _f8.pop(PENDING_KEY, None)
                        await _S8().commit(session_id, _f8)
        except Exception as _e8:
            logger.warning(f"[{skill_name}] 确认收口失败（非致命，交回模型）: {_e8}")

    # ── 8.5 这里**刻意不做** C 端回复脱敏（issue #3386：曾经做过，是错的）──
    # 首版在此处 `mask_pii(final_content)`，理由是"验收剧本里 AI 回显了完整手机号"。
    # 但 `final_answer` 同时是 `_agent_stream_to_sse` 里 `full_response.append(clean)`
    # 的来源 —— 也就是 `save_message` 落库的 assistant 消息、模型**下一轮读到的自己的历史**。
    # 于是：R5 脱敏 `13800138000` → `138****8000` 落库 → R7 模型读到残缺值，
    # 把 `****` 填成 `0` 得到 `13800008000`（11 位纯数字，`order_create` 的格式校验放行）
    # → 订单 `20260913384380002` 落库手机号就是 `13800008000`，**静默脏数据**：
    # 顾客收不到短信与配送联系（DB 实证见 issue #3386）。
    # 正确分界：**记忆/落库保原文，脱敏只做在出站展示层** ——
    # SSE 文本/卡片在 `app/api/chat.py` 的 `_mask_for_customer` / `_mask_card_for_customer`，
    # C 端 `GET /history` 回放在 `app/api/chat.py::get_history`。
    # 另有一层兜底：模型若真把掩码值填回写工具，`_masked_phone_write_block` 会拦下并回放真号。

    # ── 9. 返回值 ──
    result: dict[str, Any] = {"messages": new_messages, "final_answer": final_content, "skill_used": skill_name}

    # ── 10. 跨轮持久化 ──
    # creation_skills 覆盖所有「多轮引导写流程」的域：创建类流程在未完成前必须锁
    # pending_skill，否则用户后续轮补充信息时重新走完整路由被关键词误判跳域
    # （HR-005 角色创建、CU-003 客户打标签：staff/customer 此前缺失 → 引导漂移 + 能力误宣）。
    if skill_name in CREATION_SKILL_NAMES:
        success_markers = ("创建成功", "已创建", "下单成功", "工单已创建", "售后工单",
                          "账号已创建", "角色已创建", "标签已添加", "已更新", "已添加")
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


# ── 确认卡 XML 生成器（issue #3445：代码兜底发卡）──────────────────────────────
# 背景：写调用因 `confirmation_required_no_card` 被门禁拦回时，模型**从没发过确认卡**，
# 被拦回后仍反复重试同一个写调用、烧完轮数（CI 三次实测；话术已改为"唯一可执行的下一步"
# 后**流程能收敛**，但"跳过确认卡"这一行为仍在）。
# 代码兜底要发卡，而卡片的**唯一通用发射点**是 `app/api/chat.py` 里解析**回复文本中的
# `<interact>…</interact>` XML 块**（工具路径最终汇聚到同一协议）。故这里生成该 XML：
# 形状与 `_parse_interact_xml` 的文档字符串一一对应（fields/confirmLabel/cancelLabel/
# confirmValue/cancelValue），由测试对着**真解析器**钉住，避免"生成了但解析不出来"。
def build_confirm_interact_xml(title: str, fields: list, *,
                               confirm_label: str = "确认下单",
                               cancel_label: str = "再改改",
                               confirm_value: str = "",
                               cancel_value: str = "取消") -> str:
    """生成 confirm 卡的 `<interact>` XML 块（只回显传入事实，不新增内容）。

    两条**实测得到的约束**（对着真解析器 `_parse_interact_xml` 测出来的，不是推测）：

    1. **`fields` 为空时直接返回 ""** —— 解析器对"字段缺失"的块返回 None（调用方只会剥离
       XML、不下发残缺 payload）⇒ 空卡片发不出去。返回空串让调用方**显式跳过**追加，
       而不是生成一段注定被丢弃的垃圾。
    2. **不做 XML 实体转义，改用全角替换**（`<`→`＜`、`>`→`＞`、`&`→`＆`）——
       解析器是**正则提取、不做 unescape**，若转成 `&lt;` 就会把 `&lt;` 原样显示给顾客。
       全角替换既保住结构（值里出现 `</value>` 也不会截断），显示也可读。

    `confirmValue` 必须与门禁的卡值口径一致（`interact` 的 confirmValue 已确定性派生，
    见 issue #3406）—— 否则顾客点了卡也过不了确认门禁。
    """
    def _safe(v: object) -> str:
        return (str(v or "").replace("<", "＜").replace(">", "＞").replace("&", "＆"))

    clean_fields = [f for f in (fields or []) if isinstance(f, dict) and f.get("label")]
    if not clean_fields:
        return ""
    flds = "".join(
        f"<field><label>{_safe(f.get('label'))}</label>"
        f"<value>{_safe(f.get('value'))}</value></field>"
        for f in clean_fields)
    return (
        "<interact>"
        "<component>confirm</component>"
        f"<title>{_safe(title)}</title>"
        f"<fields>{flds}</fields>"
        f"<confirmLabel>{_safe(confirm_label)}</confirmLabel>"
        f"<cancelLabel>{_safe(cancel_label)}</cancelLabel>"
        f"<confirmValue>{_safe(confirm_value)}</confirmValue>"
        f"<cancelValue>{_safe(cancel_value)}</cancelValue>"
        "</interact>"
    )
