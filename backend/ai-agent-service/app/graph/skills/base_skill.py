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
        if not _is_explicit_confirmation(last_user_msg or "") and not is_card_confirm:
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
        if _is_cancel_message(last_user_msg):
            logger.info(f"[{skill_name}] Cancel detected | session={session_id}")
            final_content = "好的，已取消。有什么其他需要帮您的吗？"
            new_messages.clear()
            if session_id:
                try:
                    await SessionMemory().clear_pending_skill(session_id)
                except Exception:
                    pass
        else:
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
                    tool_name = tool_call["name"]
                    args = tool_call.get("args", {})
                    # 模式 C 代码兜底：加工项 choice 卡漏传 multiSelect → 自动补 true（PR-014/015）
                    args = _ensure_processing_items_multiselect(tool_name, args)
                    if args is not tool_call.get("args"):
                        tool_call = {**tool_call, "args": args}
                    tool = skill_registry.get_tool(tool_name)
                    if tool is None:
                        logger.warning(f"[{skill_name}] Tool not found: {tool_name} | session={session_id}")
                        return tool_call, json.dumps({"success": False, "error": "tool_not_found", "message": f"工具 {tool_name} 不可用"}, ensure_ascii=False), {"success": False}
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
                            msg = (
                                f"工具 {tool_name} 是写操作（可能不可逆或产生数据变更），必须先向用户展示"
                                f"确认卡片并取得明确确认。请调用 interact（component=confirm）展示操作预览，"
                                f"等用户点击确认后再执行。"
                            )
                        else:
                            msg = (
                                f"工具 {tool_name} 是写操作（可能不可逆或产生数据变更），必须先取得用户明确"
                                f"确认。本技能没有确认卡片能力：请用文本**完整复述将要执行的操作与影响**"
                                f"（对象、字段、后果），并请用户回复确认；用户回复确认后再调用本工具。"
                            )
                        return tool_call, json.dumps(
                            {"success": False, "error": "confirmation_required", "message": msg},
                            ensure_ascii=False,
                        ), {"success": False, "error": "confirmation_required"}
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
                    if not result_dict.get("success") and result_dict.get("suggestion"):
                        corrected = await _self_correct_retry(tool, args, tool_context, skill_name, result_dict, session_id, tenant_id, state)
                        if corrected:
                            result_str, result_dict = corrected
                    return tool_call, result_str, result_dict

                tool_results = await asyncio.gather(*[_run_one_tool(tc) for tc in response.tool_calls])

                # ── 模式 C 代码兜底：加工项漏问 → confirm 卡改写为加工项 choice 卡（OR-017）──
                # 仅作用于 C 端下单/售后写流程：这些 Skill 的商品详情含加工项数据、
                # 且业务铁律要求 confirm 前必须先问。B 端流程不动。
                if skill_name in ("customer_order", "customer_aftersales"):
                    try:
                        plan = _plan_processing_items_rewrite(tool_results, new_messages + state.get("messages", []))
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
