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
from app.tools.base import (
    NON_RETRYABLE_ERROR_CODES,
    PERMISSION_DENIED_CODE,
    ToolContext,
    ToolResult,
)
from app.tools.registry import (
    set_tool_context, get_tool_context, get_tool_scope,
    audit_write_tool,
)
from app.utils.log_sanitizer import LogSanitizer
import app.utils.error_incident as _err_inc
from app.memory.user_memory import UserMemoryManager
from app.core import (
    CircuitBreakerOpenError,
    LLM_FALLBACK_MESSAGE,
    get_breaker,
)
from app.llm import LLMFactory, select_model, has_images, call_with_retry, cost_tracker
from app.llm.retry_policy import _is_retryable


# ── LLM 熔断器作用域与超时（issue #3270）──
# 历史坑（2026-09-11 实测）：此前所有 skill 共用**一个全局**熔断器名
# `LLM_BREAKER = "llm_minimax"`（遗留名，与实际模型无关）→ 任一 skill 的 LLM
# 连续 3 次超时即把该全局熔断器打成 OPEN → **全部** skill 的 LLM 调用被拒 →
# 用户侧（含 C 端元元）查订单/下单/问答统一返回兜底文案「抱歉，AI 服务暂时不可用」。
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


# ── 异常吞点的**可归因性**（issue #3805，产品侧）──
# 背景（判定跑 34873715194 / SHA 30527b73，B 端 OR-014）：R4/R9/R10/R11 四轮逐字返回
# 同一句兜底、四轮 `tools=-` —— 唯一产生点就是下面 `execute_skill` 的 `except Exception`
# 兜底。异常被吞成一句**无标识**话术，同一会话连吞 4 次（R9–R11 连续 3 轮），
# 而产物里查不到异常类型与原因（根因 undetermined）。
#
# 归因三项（#3809 建立，issue #3810 起与另两个用户可见落点**共用同一实现**）：
#   ① 异常身份：`error=<类型>: <str(exc)>` + traceback（`logger.opt(exception=…)`）——
#      只记 type+str 时，KeyError/AttributeError 这类异常定位不到出错行；
#   ② 上下文：skill / session / 租户 / 轮次 / HTTP request_id；
#   ③ `incident=` 短码：同一 (会话 × 异常类型) ⇒ 同一短码
#      ⇒「连续 N 轮吞同一个异常」的 N 条日志可聚成一个 incident。
# 实现已收敛到 `app/utils/error_incident.py`（单一实现，跨落点同码），此处 re-export
# 保持既有引用面（`base_skill.llm_incident_id` / `safe_exc_message` / `_current_request_id`）。
# 用户可见话术的纪律：C 端/B 端约定兜底话术必须面向低学历用户、**禁英文技术术语与堆栈**，
# 故类型/消息/短码只落日志与审计。
EXC_MSG_MAX = _err_inc.EXC_MSG_MAX
llm_incident_id = _err_inc.llm_incident_id
safe_exc_message = _err_inc.safe_exc_message
_current_request_id = _err_inc.current_request_id



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
    """从 AIMessage 中提取**用户可见**的文本内容 —— 思考内容一律不上屏。

    🔴 单一口径（issue #7510，实证会话 sess_5742c5b5c43a48b1）：本函数的结果会直接进入
    回复气泡并落库（`react_turn` 的 `final_content = new_text`）⇒ **不得**回退到任何形态的
    思考文本：

    1. 取 `response.content` 并移除 `<think>…</think>` 块；
    2. content 为空、或**只有**思考（`<think>` 内部文本 / `reasoning_content` 有值而正文为空）
       ⇒ 返回 `""`，由调用方给固定话术或重答；
    3. 旧实现的两种回退（`<think>` 内文、`reasoning_content`）已删除 —— 它们正是
       「商家看到模型自问自答」的成因：模型把输出预算全花在思考上时正文为空，
       回退把思考原文当答复发出去了。宁可这轮没话说，也不能把思考当回复。
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

    # _strip_think_tags 在剥离后为空时会回退到原文（带标签）⇒ 这里必须再判一次：
    # 仍含 <think> 说明**只有思考**，宁可返回空（调用方的兜底话术接管），也不上屏。
    if stripped and "<think>" in stripped:
        logger.warning(
            "[_extract_content] Only thinking content found, refusing to surface it"
        )
        return ""

    if stripped:
        return stripped

    # 只有 reasoning_content、没有正文 ⇒ 同样不上屏（旧实现从这里把思考原文发出去）
    extra = getattr(response, "additional_kwargs", {}) or {}
    resp_meta = getattr(response, "response_metadata", {}) or {}
    if extra.get("reasoning_content") or resp_meta.get("reasoning_content"):
        logger.warning(
            "[_extract_content] Empty content with reasoning_content present, refusing to surface reasoning"
        )
    return ""


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
#
# ⚠️ **同名不同义**（issue #5331 判据 3 的同族登记）：本集合与上面的 `_THINKING_INTENTS`
# 里 6 个**意图名**（order_query / order_create / category_manage / customer_manage /
# employee_manage / role_manage）与**工具名逐字同形**，但它们是**意图**不是工具引用
# —— 任何「扫工具名引用」的判据都必须把它们当同名不同义处置（否则假红/假绿都从这里来）。
# 另一条同族登记：本文件的 `_named_tools()` 用**子串**匹配工具名 ⇒ `product_manage` 会被
# 角色名 `product_manager` 命中（今天被守卫的四段文本不含该角色名 ⇒ fail-safe 未触发，
# 属**假红**方向、不是假绿）；修法 = 改成 ASCII 词边界匹配，owner = 商品图片守卫面。
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
# ⚠️ 必须同时列出 C 端（元元）Skill 名：元元的 Skill 叫 `customer_*`，与 B 端名
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
    # C 端（元元）写流程
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


# ── 能力可见面（issue #4125，关联 #4123 第二刀）────────────────────────────────
# 病灶：域切分**读写同权** —— `create_skill_registry(cfg.tool_names)` 只放该 skill 声明的工具，
# 于是「查订单」在商品域里也不可执行：模型每轮只见 1~12 个工具，**没有任何东西告诉它
# 其余能力存在、归谁**，被域闸门拒（`cross_skill_target`）后也不知道该去哪儿。
#
# 修法 = **非对称切分**（两处落点共用一份事实）：
#   ① `create_skill_registry`：**写工具**（`read_only=False`）仍按域收紧 —— #4017 的 126 处
#      **写**死角判据不许放松；**只读工具**（`BaseTool.read_only is True`）全域可见/可执行。
#   ② `_build_system_prompt`：静态「能力索引」（域 → 该域可执行的写工具，事实 derive）。
#
# 为什么按 **persona 家族**而不是"全局并只读"：`xiaobu`（C 端顾客）与 `mibao`（B 端商家）的
# 可达集是**硬边界** —— 实测**只被 B 端绑定**的只读工具 5 个（`dashboard_stats` /
# `logistics_track` / `order_query` / `piecework_query` / `processing_item_query`）⇒ 全局并入
# 等于 C 端当场看见 B 端工具（越权面）。家族由 `SkillConfig.system_prompts` 的 key **derive**
# （不写死任何 skill 名 / persona 字面量），且**歧义即 fail-closed 不并**。
#
# 判据：`tests/test_readonly_cross_domain_sharing.py`（执行域/校验域一致 + persona 边界）
#       `tests/test_capability_index_prompt.py`（索引与 `SkillConfig.tool_names` 逐域机械比对）
_CAPABILITY_INDEX_MARKER = "【能力索引】"
_CAPABILITY_INDEX_HEADER = (
    _CAPABILITY_INDEX_MARKER
    + "只读工具（查询/详情/统计类）在**所有流程**内都可直接调用，无需切换流程；"
    "写操作只能在下表所属流程内执行（跨流程写会失败）—— 需要别的流程办理时，"
    "按提示引导用户到对应流程或转人工："
)
#: 裁剪态抬头（issue #8174）：读面按意图裁到 ≤ `TOOL_TRIM_MAX_READ` 后，上面的
#: 「所有流程内都可直接调用」就**成了假真值**（模型会去调本轮没绑定的工具 → Tool not found）。
#: 换成只陈述事实的短句（同时去掉与【能力边界】重复的「去哪儿办」指路，信息不重复）。
_CAPABILITY_INDEX_HEADER_TRIMMED = (
    _CAPABILITY_INDEX_MARKER
    + "本轮只读工具仅限已绑定者（未绑定的只读工具需先切换流程）；"
    "写操作只能在下表所属流程内执行（跨流程写会失败）："
)


# ⚠️ 上面 #4125 的事实四件套（`_all_skill_configs` / `_skill_config` / `_read_only_tool_names` /
# `_family_personas` / `_family_read_only_tool_names`）与 `create_skill_registry` 已**整体搬到**
# `app/graph/skills/tool_selection.py`（issue #8174：本文件受 LOC 棘轮 4356 行约束，裁剪逻辑
# 只能搬出去再加）。下方 import 是**re-export** —— 既有调用点与 `patch(...base_skill.X)` 接缝
# 逐字保持可用（`prepare_turn` 仍按 `_base.create_skill_registry` 取值）。
from app.graph.skills.tool_selection import (  # noqa: E402,F401 — re-export（#8174）
    _all_skill_configs,
    _family_personas,
    _family_read_only_tool_names,
    _read_only_tool_names,
    _skill_config,
    create_skill_registry,
)


def _capability_index(skill_name: str, trimmed: bool = False) -> str:
    """静态能力索引（**给模型看的小地图**，不是给用户说的文本，见 `_CAPABILITY_INDEX_HEADER`）。

    内容 = `域 → 该域可执行的写工具`，一行一个；只读工具不逐条列举（它们已在抬头里表述为
    所有流程可用 —— 逐条列会白烧每轮预算）。**全部从 SkillConfig/注册表事实 derive**，
    不写死任何 skill 名 / 工具名（本仓对"白名单复发"有专门守卫）。

    `trimmed=True`（issue #8174）：本轮的读面被 `tool_selection.plan_read_tools` 裁过 ⇒
    抬头换成**只陈述事实**的版本（#8174 的 prompt 字符数棘轮 + 不许对模型说假真值）。
    """
    cfg = _skill_config(skill_name)
    if cfg is None:
        logger.warning(
            f"[base_skill] 能力索引跳过：skill '{skill_name}' 不在注册表（无从 derive 事实）")
        return ""
    personas = set(cfg.system_prompts or {})
    if not personas:
        return ""
    read_only = _read_only_tool_names()
    lines = []
    for other in sorted(_all_skill_configs(), key=lambda c: c.name):
        if not (personas & set(other.system_prompts or {})):
            continue
        writes = [t for t in (other.tool_names or []) if t not in read_only]
        if writes:
            lines.append("- " + other.name + ": " + " ".join(writes))
    if not lines:
        return ""
    return (_CAPABILITY_INDEX_HEADER_TRIMMED if trimmed
            else _CAPABILITY_INDEX_HEADER) + "\n" + "\n".join(lines)


#: 能力边界段首标记（issue #7291）。与 `_CAPABILITY_INDEX_MARKER` 同族但**不同物**：
#: 索引回答「哪个域有哪些写工具」，边界回答「能办什么 / 不能办什么 / 不能办去哪」。
_CAPABILITY_BOUNDARY_MARKER = "【能力边界】"


def _capability_boundary(skill_name: str) -> str:
    """B 端能力边界段（**只给 mibao**，C 端逐字节不受影响）。

    为什么由代码投影而不是写在 prompt 文件里：边界声明原先手抄在 10 个文件里，
    其中 9 处与工具真值相反（#7291 现取证据）。投影的单一事实源 = 注册表 × mibao 绑定面，
    工具一变文案自动跟随；真值变化由 `tests/test_capability_boundary.py` 的快照判据变红提醒。

    🔴 **必须把 skill_name 传进渲染**（issue #8119）：写能力是**按 skill 绑定**的（order /
    customer / staff / data / knowledge / aftersales / general 零写工具），而原先的投影按
    persona 全局给 —— 于是 order 回合也宣称「✅ 商品改名可直接办理」，本轮却没有
    `product_update` 工具（判据 `test_every_mibao_skill_projects_its_own_scope`）。
    """
    cfg = _skill_config(skill_name)
    if cfg is None or "mibao" not in set(cfg.system_prompts or {}):
        return ""
    from app.agents.capability_boundary import MARKER, render_capability_boundary

    text = render_capability_boundary(skill_name=skill_name)
    # 两处常量漂移会让「段在不在」被判错（测试也抓不到的那类静默失效）⇒ 就地自证。
    assert text.startswith(MARKER) and MARKER == _CAPABILITY_BOUNDARY_MARKER
    return text


# `create_skill_registry` 已搬到 `app/graph/skills/tool_selection.py`（#8174；上方 import 已
# re-export）。`prepare_turn` 仍按 `_base.create_skill_registry` 取值 ⇒ patch 接缝与调用语义不变。


#: 选工具小抄段首标记（issue #8176）。与 `_CAPABILITY_INDEX_MARKER` / `_CAPABILITY_BOUNDARY_MARKER`
#: 同族但**不同物**：索引答「哪个域有哪些写工具」、边界答「能办什么 / 不能办什么」，
#: 小抄答「商家这么说时该点哪把工具、别拿它去做什么」。
_CHEATSHEET_MARKER = "【选工具小抄】"


def _tool_cheatsheet(skill_name: str) -> str:
    """选工具小抄段（**只给 mibao**；C 端提示词逐字节不变，与 Layer 2.7 同一道 persona 门控）。

    真值分工（issue #8176 的口径，不得改）：能力 = 工具注册表；商家叫法 = 本体 objects；
    「不该用 A 做 B」= 工具 `description` 的 `【不要用于】` 段。渲染器在
    `app/graph/skills/cheatsheet.py`，本函数只做 persona 门控与常量漂移自证。
    """
    cfg = _skill_config(skill_name)
    if cfg is None or "mibao" not in set(cfg.system_prompts or {}):
        return ""
    from app.graph.skills.cheatsheet import MARKER, render_cheatsheet

    text = render_cheatsheet(skill_name)
    # 两处常量漂移会让「段在不在」被判错（测试也抓不到的那类静默失效）⇒ 就地自证。
    assert text.startswith(MARKER) and MARKER == _CHEATSHEET_MARKER
    return text


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

# **基础规则层**（必需，相对 `_ref_dir`）：每个 Skill 都注入的公共层 —— 缺失即「整层规则
# 静默消失」（issue #4057 S5）。故这三个文件走 `_read_cached(..., required=True)`：缺失/为空
# 时 **error 级日志 + 抛 `RequiredPromptMissingError`**，不得像可选层那样返回 ""。
# 磁盘存在性由 L0 用例 `tests/unit_ci_workflows/test_ai_agent_prompt_reference_guard.py` 锁
# （删文件 ⇒ CI 红），本处的清单必须与它逐字一致。
_REQUIRED_PROMPT_FILES = (
    "base/identity.md",     # Layer 1 公共身份
    "base/principles.md",   # Layer 2 公共行为准则
    "PROMPT-rules.md",      # Layer 2.5 共享 Prompt 规则（Certainty Tagging / P&E / 确认卡铁律）
)

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


class RequiredPromptMissingError(RuntimeError):
    """必需的基础规则层 Prompt 文件缺失/为空（issue #4057 S5：fail-loud）。"""


def _read_cached(path: str, required: bool = False) -> str:
    """读取文件内容，带缓存。

    `required=False` —— **可选层**（`prompts/<skill>.md`、`EXAMPLES-*.md`）：文件不存在是
    **合法形态**（该层不注入），静默返回 ""。

    `required=True` —— **基础规则层**（`_REQUIRED_PROMPT_FILES`）：缺失/不可读/为空
    **不得**静默返回 ""（那会让整层公共规则消失而没有任何东西变红）⇒ error 级日志 +
    抛 `RequiredPromptMissingError`。
    """
    if path in _PROMPT_CACHE:
        text = _PROMPT_CACHE[path]
    else:
        text = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            _PROMPT_CACHE[path] = text
        except FileNotFoundError:
            if not required:
                _PROMPT_CACHE[path] = ""   # 可选层缺席 = 合法形态
        except Exception as e:
            logger.warning(f"Failed to load prompt file '{path}': {e}")
            if not required:
                _PROMPT_CACHE[path] = ""
    if required and not text:
        logger.error(f"[prompt-ref] REQUIRED 基础规则文件缺失/为空: {path}")
        raise RequiredPromptMissingError(
            f"必需的基础 Prompt 文件缺失或为空：{path} —— 基础规则层不得静默消失"
            f"（issue #4057 S5）")
    return text


def _build_system_prompt(skill_name: str, inline_prompt: str = "",
                         trimmed: bool = False) -> str:
    """分层组装 System Prompt

    层级（从底到顶）：
      1. base/identity.md     — 公共身份描述（所有 Skill 共享）
      2. base/principles.md   — 公共行为准则（所有 Skill 共享）
      2.5 PROMPT-rules.md     — 公共 Prompt 规则（所有 Skill 共享）
      2.6 能力索引            — 域 → 该域可执行的写工具（**事实 derive**，见 #4125）
      3. prompts/{skill}.md   — 领域规则 + 工具说明（按 Skill）
      4. inline_prompt        — 调用方传入的额外指令（可选，用于覆盖/追加）
      5. EXAMPLES-{skill}.md  — few-shot 示例（按 Skill）

    所有文件均为可选，不存在时静默跳过。
    缓存到 _PROMPT_CACHE 避免每次请求读文件。

    ⚠️ 例外（issue #4057 S5）：Layer 1/2/2.5 属**基础规则层**（`_REQUIRED_PROMPT_FILES`），
    缺失/为空时**不静默**（error 日志 + `RequiredPromptMissingError`）—— 它们缺席等于
    每个 Skill 都少一整层公共规则。Layer 3/5（`prompts/<skill>.md`、`EXAMPLES-*.md`）
    仍可缺席（返回 ""）。

    Returns:
        组装好的完整 System Prompt 字符串

    Raises:
        RequiredPromptMissingError: 任一基础规则层文件缺失/不可读/为空。
    """
    parts = []

    # Layer 1+2+2.5: 公共基础（身份 + 原则 + 共享 Prompt 规则）—— **必需层**，缺失即响亮失败
    identity_rel, principles_rel, prompt_rules_rel = _REQUIRED_PROMPT_FILES
    identity = _read_cached(_os.path.join(_ref_dir, identity_rel), required=True)
    if identity:
        parts.append(identity)

    principles = _read_cached(_os.path.join(_ref_dir, principles_rel), required=True)
    if principles:
        parts.append(principles)

    prompt_rules = _read_cached(_os.path.join(_ref_dir, prompt_rules_rel), required=True)
    if prompt_rules:
        parts.append(prompt_rules)

    # Layer 2.6: 能力索引（issue #4125）—— 静态小地图，域 → 该域可执行的写工具。
    # 位置在**公共规则之后、领域 prompt 之前**：它是"全局地形"，供领域规则之上去理解
    # 「本流程能做什么、别的流程归谁」；不放到末尾是为了不被 few-shot 长文淹没。
    # ⚠️ 这是**给模型看**的（system prompt），不是给用户说的 —— 用户可见路径不得复用
    # `_capability_index`（`references/base/principles.md` 第 21 行禁止回复里出现工具名/字段名）；
    # 该边界由 `tests/test_capability_index_prompt.py` 的静态扫描 + 植入负例锁定。
    capability_index = _capability_index(skill_name, trimmed=trimmed)
    if capability_index:
        parts.append(capability_index)

    # Layer 2.7: 能力边界（issue #7291）—— 与 2.6 同族：2.6 是「哪个域有哪些写工具」的地图，
    # 2.7 是「能办什么 / 不能办什么 / 不能办去哪」的口径。**只给 mibao**（见 _capability_boundary）。
    capability_boundary = _capability_boundary(skill_name)
    if capability_boundary:
        parts.append(capability_boundary)

    # Layer 2.8: 选工具小抄（issue #8176）—— 按本轮 skill 的声明面从**工具注册表 + 本体**投影，
    # 替掉原先手抄在 9 处的「场景 → 工具」速查表（#7291 同族：手写的能力声明必与真值漂移）。
    cheatsheet = _tool_cheatsheet(skill_name)
    if cheatsheet:
        parts.append(cheatsheet)

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


def _card_only_confirmation(tool, tool_args: dict) -> bool:
    """本次写调用是否**只认卡值确认**（涉钱面 = 改价，issue #5317 裁定）。

    两条入面口径，**同一个函数**（不另立第二份清单，判据可机械复算）：

      · **声明入面**：工具 schema 声明了 `before_price`（= 走 #5303「改前 → 改后」预览契约的
        改价工具）且本次调用带了价格事实（`price` / `before_price`）；
      · **动作入面**：工具声明 `card_only_actions` 且本次 action 在其中 —— 参数里看不出钱的
        动作（批量 `execute` / `revert` 只带 `batch_id`，价格事实在批次行里）只能由工具声明。

    为什么必须只认卡值：护栏证明的东西必须与它声称证明的一致 —— 文本「确认」只能证明
    "有过一次确认动作"，证明不了"确认卡已发出、卡上有改前价"。放行链因此只剩
    `_is_card_confirm_value`（用户消息**逐字等于**系统自产的卡值 = 真的点了卡）与由**点卡**
    记录下的 `confirmed_write_tool`。
    """
    args = tool_args or {}
    declared = getattr(tool, "card_only_actions", frozenset()) or frozenset()
    action = str(args.get("action") or args.get("operation") or args.get("op") or "")
    if action and action in declared:
        return True
    props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
    if "before_price" not in props:
        return False
    return args.get("price") is not None or args.get("before_price") is not None


def _card_only_confirmation_by_name(tool_name: str, tool_args: dict) -> bool:
    """按**工具名**判涉钱面（取**全局**工具表：待执行/刚被拦的工具可能不在当前 skill 域内）。

    与 `_card_only_confirmation` 只是取件口径差异，**不是第二套判据**。
    """
    try:
        from app.tools.registry import get_tool_registry
        tool = get_tool_registry().get_tool(str(tool_name or ""))
    except Exception:
        tool = None
    return _card_only_confirmation(tool, tool_args)


def _pending_card_only(pending: dict) -> bool:
    """「已校验待执行」的目标工具是否属涉钱面（issue #5317）：文本确认不得记为「已确认」。"""
    return _card_only_confirmation_by_name(
        (pending or {}).get("target_tool"), (pending or {}).get("params") or {})


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
    # 涉钱面（改价）只认卡值（issue #5317）：文本确认**恒不算** ⇒ 放行只剩 react_turn 的
    # `_is_card_confirm_value`（点卡）与由点卡记录下的 `confirmed_write_tool`。
    if _card_only_confirmation(tool, tool_args):
        return True
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
# 业务铁律「店铺有加工项 → confirm 前必须先问」目前只写在 prompt/工具描述里，
# 约 1/3 轮次 LLM 会漏掉（CI 实证 run 34622425044 ✅ / 34626024229 ❌ / 34662285260 ❌，
# 同代码同用例）。按项目「改 3 次 prompt 修不好 → 代码管」惯例，做确定性兜底：
# 当 LLM 跳过加工项直接发 confirm 卡时，把该 confirm 卡**改写**为加工项 choice 卡。
# 这与 _ensure_processing_items_multiselect（漏传 multiSelect 自动补）同族。
# issue #4371（商品↔加工项解耦）：加工项不再挂在商品上 ⇒ 两端（C 端下单/售后、B 端建品）
# 的**唯一事实源统一为 `processing_item_query` 的店铺级目录**，不再读 product_detail 的
# processing_items（该字段已随解耦删除）。

# 加工项 choice 卡的 option value 前缀（与 _is_processing_items_card 及
# tests/agent_eval/local_runner.py 的断言语义一致）
_PROC_ITEM_VALUE_PREFIX = "proc_item_"

# 用户明确拒绝加工项的短句（命中则跳过兜底 —— 顾客说"不需要"/"不用"时不得硬弹卡）。
# 「不用」是 4 个 prompt 承诺的**裸词**（「说"不用"才跳过」，issue #4013 A11），
# 且已包含「不用加工」「不用了」两种更具体写法 ⇒ 后两者不再单列（词表只许收敛）。
_PROC_DECLINE_MARKERS = (
    "不需要加工", "不要加工", "不加工", "不加加工",
    "不需要了", "不用", "算了", "不加了",
)


def _last_user_declined_processing(messages) -> bool:
    """最近一条用户消息是否明确拒绝加工项（拒绝过就不再硬弹卡）"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = getattr(msg, "content", "") or ""
            if isinstance(text, list):
                text = " ".join(str(t.get("text", "")) for t in text if isinstance(t, dict))
            return any(k in str(text) for k in _PROC_DECLINE_MARKERS)
    return False


def _proc_answer_tokens(items: List[dict]) -> set:
    """加工项名 → 顾客可能的说法（全名 + 2 字以上的连续子串）。

    为什么要子串：fixture 里叫「打孔」，顾客口语常说「打孔加工」「纳米圈」——
    只用全名匹配等于不匹配（C-A1 重放 9 里"已答却被当成漏问"的一半原因）。
    """
    toks: set = set()
    for it in items or []:
        name = str((it or {}).get("name") or "").strip()
        if not name:
            continue
        toks.add(name)
        for i in range(len(name)):
            for j in range(i + 2, len(name) + 1):
                toks.add(name[i:j])
    return toks


def _user_already_answered_processing(messages, source_tool: str = "processing_item_query") -> bool:
    """顾客**是否已经就加工项作答**（文本形态：说了加工项名 / 明确不要）。

    实证（C-A1 重放 9，run 34788143133 的 transcript）：
      R2 元元**在文本里**问「需要一起加工吗？」→ R3 顾客答「打孔」→
      R5 代码兜底仍把 confirm 卡改写成加工项 choice 卡 → **同一件事问第二遍**，
      顾客不得不再答一次才轮到「确认下单」（UA 判定因此记"有条件通过"）。
    账上为什么没痕迹：`PROC_ITEMS_ASKED_KEY` 只在**发出加工项卡**时记账 ——
    文本问答形态（问在文字里、答在文字里）不在账上，兜底于是把"已答"误判成"漏问"。

    判据（只看**最近一次 source_tool 结果之后**的用户消息）：
      · 出现加工项词（全名或其 2 字以上子串）→ 已答；
      · 出现拒绝词（不需要加工/算了…）→ 已答（比 `_last_user_declined_processing`
        只看最近一条更强：顾客拒绝后又说「确认下单」也算答过）。
    为什么限定"结果之后"：R1 就说了「要打孔加工」属**需求前置** ——
    那时还没看过可选项与单价，confirm 前仍应摆出来（OR-017 依赖这条）。

    `source_tool`（issue #3320 引入区分；issue #4371 起两端合一）：加工项是**店铺级目录**，
    C 端（下单/售后）与 B 端（建品）的事实源都是本会话真实调用过的
    `processing_item_query` 返回 —— 商品上已不再持有加工项，故默认值改为
    `processing_item_query`（旧默认 `product_detail` 随该字段删除而失效）。
    """
    if not messages:
        return False
    last_detail = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", None) == source_tool:
            last_detail = i
    if last_detail < 0:
        return False
    items = _find_last_query_processing_items(messages)
    tokens = _proc_answer_tokens(items)
    for msg in list(messages)[last_detail + 1:]:
        if not isinstance(msg, HumanMessage):
            continue
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):   # 多模态轮：拼出文本部分
            content = " ".join(str(t.get("text", "")) for t in content if isinstance(t, dict))
        text = str(content)
        if any(k in text for k in _PROC_DECLINE_MARKERS):
            return True
        if tokens and any(tok in text for tok in tokens):
            return True
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
    """检测「店铺有加工项却漏问、直接发 confirm 卡」并返回改写方案。

    事实源 = 本会话真实调用过的 `processing_item_query`（店铺级目录，issue #4371：
    加工项不再挂在商品上，`product_detail` 也不再返回它）。

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
    if _user_already_answered_processing(messages):
        # 顾客已经答过（文本形态：点名加工项 / 更早一轮拒绝过）→ 不得用卡重问一遍
        # （C-A1 重放 9 实证：同一件事问第二遍，顾客要多答一次才轮到确认下单）。
        return None
    items = _find_last_query_processing_items(messages)
    if not items:
        return None  # 没拿到加工项目录，无从改写（**绝不伪造卡**）
    options = []
    for it in items[:_MAX_PROC_OPTIONS]:
        oid = str(it.get("id") or "")
        if not oid:
            continue
        name = str(it.get("name") or "加工项")
        unit = it.get("unit") or ""
        options.append({
            # ⚠️ 标签**不带价格**：加工项已无单价与计价方式（issue #4882）——
            # 旧写法 `f"{name} ¥{price}/{unit}"` 在字段删除后会渲染出「¥None/米」，
            # 卡上就出现了**编造的钱**（R5：禁止新增静默失效形态）。
            "label": f"{name}（{unit}）" if unit else name,
            "value": f"{_PROC_ITEM_VALUE_PREFIX}{oid}",
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


# ── issue #4371（商品↔加工项解耦）：B 端**建品**的加工项漏问兜底已**整体删除** ──
# 原兜底（issue #3320）的适用面是「建品在办 + 有加工项目录 + 未问过 + 正要发 confirm 卡
# ⇒ 把 confirm 卡改写成加工项多选卡」。解耦后**建品不再需要询问/关联加工项**
# （product_manage 已无加工项参数；用户裁定「用户选择完商品以及安装方式后，加工工序已经固定，
# 额外的加工项可以单独从加工项中选择」）⇒ 该改写从"补漏"变成"**过度询问**"：它会把一张
# 本来正确的建品确认卡改成没有下游出口的加工项卡（选了也无处可写）。
# 故整条删除（判据函数 `_plan_b_create_processing_items_rewrite` 与
# `_b_create_processing_items_not_asked` 一并移除，不留死代码）。
# C 端（下单/售后）那条 `_plan_processing_items_rewrite` **保留**：顾客下单时确实要选加工项，
# 事实源改为店铺级目录 `processing_item_query`。
B_CREATE_PENDING_TOOL = "product_manage"
B_CREATE_PENDING_ACTION = "create"


# ── 下单「单价接地」校验（issue OR-014；**已搬到中性模块**，issue #4057 S7）──
# 三个判据函数（`unit_price_grounding_error` / `_match_sku_price` /
# `_library_unit_price_grounded`）及其私有依赖（`_PRICE_TOLERANCE` / `_to_float`）
# 定义在 `app/utils/sku_price.py` —— 工具层（`app/tools/order_create.py`）也要用同一判据，
# 若留在本模块就成了「叶子模块反向 import 上层 skill 私有符号」。此处**再导出**同名符号：
#   · `execution/react_turn.py` 顶层 `from app.graph.skills.base_skill import …,
#     unit_price_grounding_error, …` 依赖它；
#   · `tests/test_order_price_grounding.py` 等既有用例也从这里取。
# ⚠️ 判据/守卫见 `tests/test_utils_sku_price.py`（同一对象、非两份拷贝）。
# ⚠️ patch 接缝：这些名字目前**没有**测试用 `patch.object(base_skill, …)` 打桩；若将来要打桩，
#    注意 `react_turn.py` 是**模块顶层** from-import（绑定冻结）⇒ 打桩不会影响它（见
#    `execution/prepare_turn.py` 顶部注释的解法）。
from app.utils.sku_price import (  # noqa: F401  (re-export: 兼容既有 import 路径)
    _PRICE_TOLERANCE,
    _library_unit_price_grounded,
    _match_sku_price,
    _to_float,
    unit_price_grounding_error,
)


# ── B 端建品「确认-执行」收口的适用判据（issue PR-016，run 34916256903 归因）──
# 实证：B 端建品（product skill）用户 R7 回传确认卡值（confirmValue 精确匹配），
# 模型却调 product_search 宣称「✅ 商品已创建成功！」—— product_manage(action=create)
# **从未执行**（首跑指纹 no_success(product_manage)）；重试轮 R4/R5/R6 三张同事实
# confirm 卡不收敛（评测 check_confirm_loop 判红）。
# 根因：8.4「确认-执行代码收口」只对 C 端生效（`_is_customer_role(state)`），
# B 端建品确认后**没有任何代码兜底** —— 动不动手完全取决于模型自觉。
# 本判据把 8.4 收口扩展为**也覆盖 B 端建品**：pending（validate_input 通过落库）=
# product_manage/create + 用户已明确确认（confirmValue 精确匹配或文本确认）⇒ 可收口。
# 反向守卫（不得把「确认后必执行」写死成「永不确认」）：未确认 / 无 pending /
# 非 create 流程 ⇒ False，模型仍按原流程（可发**不同**的卡说明缺什么）。
# issue #3976（2026-09-17）再扩展：B 端**下单**（order_create/create）同样纳入收口 ——
# 线上实证 sess_202d55d49a254a10：确认卡点击后模型空头承诺「请稍候，我这就提交」、
# order_create 从未执行、订单永不落库。B 端 admin/agent 角色下单无需 sms_code
# （order_create.py 安全规则），收口安全性成立；8.4 的 sms_code 链对 B 端无码
# 场景自然跳过（resolve_sms_code 无已知真值 → 不改入参）。
def _b_create_flow_confirm_eligible(pending: dict | None, confirmed: bool) -> bool:
    """B 端「确认-执行」是否满足代码收口条件（纯函数，可单测）。

    与 `_should_code_close_loop` 的分工：前者管「C 端任意写 + B 端建品/下单」的统一
    收口判据（pending/确认/未执行三条件）；本函数是**收口的适用域**判据 ——
    B 端非 customer 角色下，只有「建品 create（product_manage）或下单 create
    （order_create）在办」这一流程才允许代码代执行。
    """
    if not confirmed:
        return False
    if not isinstance(pending, dict):
        return False
    tool = str(pending.get("target_tool") or "")
    action = str(pending.get("target_action") or "")
    if tool == B_CREATE_PENDING_TOOL and action == B_CREATE_PENDING_ACTION:
        return True
    if tool == ORDER_WRITE_TOOL and action == B_CREATE_PENDING_ACTION:
        return True
    return False


def _find_last_query_processing_items(messages) -> List[dict]:
    """会话历史里**最近一次**成功的 `processing_item_query` 返回的加工项列表。

    加工项的**唯一事实源**（issue #4371：加工项是店铺级目录，商品不再持有它；
    C 端下单/售后与 B 端建品都走这里）。跨轮（R2 查询、R4 才发卡）时本轮
    tool_results 里看不到查询结果，必须回看会话里的 ToolMessage。
    """
    if not messages:
        return []
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) != "processing_item_query":
            continue
        try:
            payload = json.loads(msg.content or "{}")
            if not isinstance(payload, dict) or not payload.get("success"):
                continue
            items = (payload.get("data") or {}).get("items") or []
            if items:
                return items
        except (ValueError, TypeError, AttributeError):
            continue
    return []



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


def _confirm_card_seen(messages, session_state: dict | None = None) -> bool:
    """会话里是否**出现过确认卡**（用于把 `confirmation_required` 细分成两种形态）。

    为什么需要（issue #3445）：同样是写单被确认门禁挡回，两种成因的修法完全不同 ——
      · **从没发过确认卡** → 模型跳过确认直接写（该做的是把确认卡补上）；
      · **发过卡但这次回复不是卡值**（顾客回了文本 / harness 没点卡）→ 该修的是点卡链路。
    而 CI 指纹原本只有一句 `confirmation_required`，两种形态长得一模一样，只能人肉翻容器日志
    （fast 档还看不到）。故把细分写进 error 码，让报告自己说话。

    ⚠️ **`messages` 在真实链路里查不到卡（issue #3750 实证，别再依赖它）**：
    图每轮由 `app/agents/customer_service_agent.py::_convert_history` 从 DB 历史重建，
    **只构造 `HumanMessage`/`AIMessage`**，且 `app/graph/builder.py` 的 `graph.compile()`
    **没有 checkpointer** ⇒ 跨轮 `interact` 的 `ToolMessage` 根本不存在（本轮的那条只进
    `new_messages`）。后果（run 34849029334 / SHA 929732b4 的 OR-026）：R2 明明发出了
    `interact(component=confirm …)`，R3 写调用仍被判 `confirmation_required_no_card`，
    而 `confirmation_required_card_not_clicked` 在最需要它的"发过卡但顾客没点"多轮场景**不可达**。
    故补 `session_state` 这一**真实存在**的证据源：`last_confirm_value` / `last_card`
    由 `interact` 成功路径与 8.3b 补卡路径持久化（本文件 `:3968-3975` / `:4037`）。
    只影响**细分码与补卡判据**，不改任何放行条件。
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
    if isinstance(session_state, dict):
        if str(session_state.get("last_confirm_value") or ""):
            return True
        if str((session_state.get("last_card") or {}).get("component") or "") == "confirm":
            return True
    return False


# ── 确认事实（issue #4037 / F22）：键名与 confirmed_write_tool 同族 ──
CONFIRMED_ORDER_FACTS_KEY = "confirmed_order_facts"

#: 「被确认的**值**」事实（issue #5414）：与 `confirmed_write_tool` **成对**落账、成对清除。
#: 只有本文件的 `record_confirmed_write` / `clear_confirmed_write` 两处能写它 ——
#: 旁路直写会让"名字在、值不在"，护栏就又退回"只证明确认过某个工具"
#: （机械判据：tests/test_price_confirm_value_fact.py::TestMechanicalJudgments）。
CONFIRMED_WRITE_VALUES_KEY = "confirmed_write_values"


def confirmed_order_facts_of(tool_name: str, args: dict) -> str:
    """写调用参数 → 订单金额事实串（口径单点在 `order_create.order_facts_of`）。

    函数级 import：`app.tools.order_create` 反向依赖本模块的接地判据，模块级会成环。
    """
    if str(tool_name or "") != "order_create":
        return ""
    try:
        from app.tools.order_create import order_facts_of
        return order_facts_of(args)
    except Exception as e:  # pragma: no cover - 纯函数不应抛，抛了也不能破坏确认链路
        logger.warning(f"[confirm-facts] 事实提取失败（非致命）: {e}")
        return ""


def record_confirmed_write(state: dict, tool_name: str, args: dict) -> dict:
    """记下"顾客已确认的写操作 + 其中的金额事实"（就地改 `state` 并返回它）。

    **三处确认落点共用本函数**（issue #4037 单一实现，防三份口径漂移）：
      ① 确认卡点击（confirmValue 精确匹配）；
      ② 文本确认（`_inject_pending_validated`）；
      ③ 代码兜底补发的确认卡（8.3b）。
    ③ 尤其重要：那张卡是**代码**替模型补的，顾客点的就是它 —— 事实必须来自
    "本次被拦的写调用参数"（`_no_card_blocked_args`），否则补的卡是"只能点、无从核对"的。

    事实的非空优先级：本次算得出就用本次；算不出（老形态写调用）保留已记的
    —— 不用空值覆盖已有快照（那等于把一道已生效的守护静默关掉）。

    值事实（issue #5414）：同一次落账里记下**被确认的值**（`CARD_ONLY_VALUE_FIELDS` 里在场的
    字段）。与上面的"非空优先级"**刻意相反** —— 值事实是"这次确认的内容是什么"的快照，
    本次算不出就**清掉旧的**：留着旧价等于让这张卡"顺便确认"了另一个价（本单的病灶）。
    """
    _t = str(tool_name or "")
    if not _t:
        return state
    state["confirmed_write_tool"] = _t
    _values = write_value_facts(args or {})
    if _values:
        state[CONFIRMED_WRITE_VALUES_KEY] = _values
    else:
        state.pop(CONFIRMED_WRITE_VALUES_KEY, None)
    _fresh = confirmed_order_facts_of(_t, args or {})
    if _fresh:
        state[CONFIRMED_ORDER_FACTS_KEY] = _fresh
    return state


def clear_confirmed_write(state: dict, tool_name: str) -> dict:
    """写成功后的清除（就地改 `state` 并返回它）：工具名与值事实**一起**清。

    与 `record_confirmed_write` 同族、同一处写该键（机械判据钉住"只有这两处"）——
    分开清会留下"名字没了、值还在"的半截记录。
    """
    if str((state or {}).get("confirmed_write_tool") or "") != str(tool_name or ""):
        return state
    state.pop("confirmed_write_tool", None)
    state.pop(CONFIRMED_WRITE_VALUES_KEY, None)
    return state


def confirmed_write_release(full: dict, tool_name: str, args: dict) -> bool:
    """跨轮放行判据（**全仓唯一实现**，issue #5414）：工具名对 **且** 值逐项核对通过。

    为什么必须唯一：这判据一旦有第二处（只比工具名），护栏就退回"只证明确认过某个工具"
    —— 商家点了价 A 的卡，写失败（记录未清），下一轮改价 B 照样放行。
    fail-closed 方向：记录里没有值事实（旧形态记录 / 非价面记录）+ 本次带了价面值 ⇒ 不放行。
    """
    _f = full or {}
    if str(_f.get("confirmed_write_tool") or "") != str(tool_name or ""):
        return False
    return values_match(_f.get(CONFIRMED_WRITE_VALUES_KEY) or {},
                        write_value_facts(args or {}))


def _confirmed_facts_reject(tool_name: str, args: dict, full: dict) -> Optional[str]:
    """落库前核对「顾客确认的事实」vs「本次要执行的事实」，不一致返回拦截描述。

    只对 `order_create` 生效（F22 实证域：顾客点卡确认金额、随后金额被重写）。
    判据本体在 `order_create.order_confirmation_mismatch`（纯函数，单点）。
    """
    if str(tool_name or "") != "order_create":
        return None
    _prior = str((full or {}).get(CONFIRMED_ORDER_FACTS_KEY) or "")
    if not _prior:
        return None
    try:
        from app.tools.order_create import order_confirmation_mismatch
        return order_confirmation_mismatch(args or {}, _prior) or None
    except Exception as e:
        logger.warning(f"[confirm-facts] 一致性核对失败（非致命）: {e}")
        return None


_PRODUCT_NOUN_RE = None


def extract_sms_code(text: str) -> str:
    """顾客消息**整条就是验证码**时提取它（issue #3365；否则返回空串）。

    为什么必须"整条就是"：手机号 13800138000 里也含 4-6 位数字，裸 `\d{4,6}` 会把
    手机号片段当验证码注入 → 验证必然失败且难排查。用例/真实顾客的验证码轮就是「123456」
    或「验证码 123456」这种形态，故用 `fullmatch`。
    """
    import re as _re
    # 先去掉**所有空白**：顾客会把验证码连空格打出来（「1 2 3 4 5 6」），
    # 不归一化就等于"没给过码"—— 而"没给过码"在新守卫下会被拦下（误伤面在这里）。
    flat = _re.sub(r"\s+", "", str(text or ""))
    m = _re.fullmatch(
        r"(?:短信验证码|验证码|校验码|动态码)?[:：]?(?:是|为)?(\d{4,6})[。.！!～~哦呀哈啊]*",
        flat)
    return m.group(1) if m else ""


def resolve_sms_code(known_code, given_code) -> tuple[str, str]:
    """决定该用哪个验证码 —— **顾客给过的码是唯一真值**（issue #3365 补齐 / #3434 纠正）。

    背景（run 34786827410 全量档实证）：CH-025 与 OR-014 的**首跑失败**指纹都是
    「order_create 因验证码失败，且参数里的验证码与顾客给过/用例声明的都不一致
    —— 疑似模型自造验证码」。短信只发到**顾客手机**上，模型没有别的渠道拿到它：
    它"自己写一个"只会让订单必然被拒（顾客点多少次确认都没用），重试碰巧写对了才通过。

    返回 `(最终使用的码, 归因标签)`：
      · 没有已知真值 → `("", "")` —— **不动**模型入参（让工具按自己的校验拒绝/提示）；
      · 与模型传入的一致 → `(码, "")` —— 不需要改写；
      · 模型漏参 / 传入不一致 → `(真值码, "补齐"|"纠正")`。
    """
    known = str(known_code or "").strip()
    if not known:
        return "", ""
    given = str(given_code or "").strip()
    if given == known:
        return known, ""
    return known, ("补齐" if not given else "纠正")


# ── 确认卡字段 / confirmValue：**单一源在契约模块**（issue #4054）──────────────
# 这两个名字原是本文件的两个模块级函数，`interact` 工具里**另写了一份**同样的派生逻辑
# ⇒ 任一侧改一行（前缀/分隔符/排序口径）就漂移 ⇒ 顾客点了卡也过不了确认门禁
# （`_is_card_confirm_value` 是精确比对），而两侧各自自洽、**没有任何测试会红**。
# 现在派生逻辑只活在 `app/tools/confirm_value.py`，本文件**原样再导出**同名符号 ——
# `app/api/chat.py`、`execution/finalize_turn.py`、既有测试的 import 路径零改动。
# （`_confirm_card_fields_hint` 仍在本文件：它只是话术拼装。）
# merge（F19/F22 × #4054）：P15 往**本文件**的 `confirm_card_fields` 追加的"金额字段"
# 已随搬迁落进契约模块的同名函数（口径不变：末尾追加、金额算不出就不加）——
# 故这里只需再导出，**不得**再写第二份投影（否则两张卡的钱各算各的）。
from app.tools.confirm_value import (  # noqa: F401  (re-export：既有调用方从这里取)
    CARD_ONLY_VALUE_FIELDS,
    confirm_card_fields,
    confirm_value_for_fields,
    price_preview_missing,
    same_value,
    values_match,
    write_value_facts,
)

# `issue #8725`：从 capability_denial.py 再导出（既有 import 面 / patch 接缝面零改动）
from app.graph.skills.capability_denial import (_ORDER_ACTION_WORDS, _ORDER_UNABLE_RE,
    ORDER_WRITE_TOOL, _INABILITY_STEMS, _ABILITY_WORDS, _PERMISSION_NEGATIONS,
    _SCOPE_HANDOFF_MARKERS, _SELF_SCOPE_COMPOUNDS, CAPABILITY_DENIAL_PATTERNS,
    _AGENT_SELF_WORDS, _NON_SELF_SUBJECT_WORDS, _CLAUSE_SPLIT_RE, _PRODUCT_IMAGE_ACTION_WORDS,
    _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE, _PRODUCT_IMAGE_UNABLE_RE, _normalize_clause,
    _negation_positions, _self_scoped_clause, _clause_is_self_line, _scope_misattribution_hit,
    _product_image_denial_hit, capability_denial_text_hit, _STALL_CORRECTIVE,
    _TEXT_DENIAL_CORRECTIVE_MIDORDER, _TEXT_DENIAL_CORRECTIVE, _TEXT_DENIAL_CORRECTIVE_BIZ,
    _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE, _stall_has_progress, _registry_has_tool,
    _LOGISTICS_CHAIN_CORRECTIVE, _logistics_chain_incomplete, _logistics_chain_corrective,
    _order_write_tool_here, _tool_registered_globally, _order_capability_available,
    PRODUCT_IMAGE_WRITE_TOOL, _product_image_capability_available,
    _registry_has_confirm_write_tool, _handoff_guard_applies, _capability_denial_reason,)

# `issue #8725`：从 order_flow_guard.py 再导出（既有 import 面 / patch 接缝面零改动）
from app.graph.skills.order_flow_guard import (_has_inflight_interactive_card,
    _ORDER_INTENT_HINTS, _has_ordering_intent, _ORDER_WITHDRAWAL_ANCHORS,
    _ORDER_WITHDRAWAL_NEGATIONS, _ORDER_WITHDRAWAL_WINDOW, _is_ordering_withdrawal,
    _release_order_lock_on_withdrawal, _flow_owner_skill, _relock_order_skill,
    _route_cross_skill_target, _load_session_facts, _order_flow_started,
    _flow_state_in_progress, _order_flow_in_progress,)

# `issue #8725`：从 phone_masking.py 再导出（既有 import 面 / patch 接缝面零改动）
from app.graph.skills.phone_masking import (KNOWN_RAW_PHONES_KEY, KNOWN_ADDRESS_KEY,
    _MASK_PLACEHOLDER_CHARS, _MASK_FILLER_CHARS, _PHONE_IN_TEXT_RE, _phone_in_text_re,
    raw_phones_in, mask_variants, _is_mask_shaped, _phone_args, _remember_known_value,
    _known_raw_phones, _remember_raw_phones, _should_code_close_loop, _is_customer_role,
    _norm_ws,)

# `issue #8725`：从 injection_blocks.py 再导出（既有 import 面 / patch 接缝面零改动）
from app.graph.skills.injection_blocks import (WRITE_INPUT_ERROR_KEY, _INPUT_PARAM_LABELS,
    user_supplied_param, RECOGNIZABLE_INPUT_PARAMS, _accepted_param_names,
    _clear_write_input_error, CARD_EMIT_COUNTS_KEY, CARD_EMIT_LIMIT, card_fingerprint,
    _PREFILL_FIDELITY_FIELDS, _QUANTITY_FRAME_WORDS, _QUANTITY_INTENT, _QUANTITY_PLAIN,
    _DIMENSION_SEMANTIC, _stated_purchase_quantities, _quantity_choice_block,
    _form_prefill_fidelity_block, _masked_phone_write_block, _masked_phone_block_result,
    _write_input_recovery_block, _card_loop_block, _inject_write_input_recovery,)


def _confirm_card_fields_hint(args: dict) -> str:
    """门禁话术里的"卡片字段骨架"（**只回显模型自己传过的值**）。

    CI 三次实测 `confirmation_required_no_card` —— 模型**从没发过确认卡**就直接写单，
    被拦回后仍反复重试同一个写调用、烧完轮数。它缺的不是"该不该发卡"，而是"卡片里填什么"。

    改价（issue #5303）：骨架里只有"改后价"时**必须补一句下一步** —— 没有 `before_price`
    的改价卡不构成「改前 → 改后」预览（判据同源 `price_preview_missing`），
    而写工具会 fail-closed（`price_preview_required`）⇒ 商家点完卡才被拒、还得再点一次。
    故这里把"先去 product_detail 拿改前价"说成唯一可执行的下一步。
    """
    fields = confirm_card_fields(args)
    if not fields:
        return ""
    hint = "，建议卡片 fields=" + json.dumps(fields, ensure_ascii=False)
    if price_preview_missing(args):
        hint += ("。⚠️ 本次是**改价**：卡上必须同时有「改前价」和「改后价」——"
                 "先调 product_detail 取该商品/该规格的**当前价**，再发 confirm 卡，"
                 "并在调用写工具时带上 before_price=当前价（漏传会被拒）")
    return hint


# ── 8.6 草稿态回复归一（issue #3750）──────────────────────────────────────────
# C 端下单 prompt 有两处铁律（`app/graph/skills/customer_order_skill.py`）：
#   · `:81-82`「在办流程里的任何修改（加工项/地址/数量/颜色/门幅）都只是草稿、订单未创建 →
#     说「记下了，下单时一并提交」；**禁止**「已更新/已修改」」；
#   · `:91`「**验证码**：顾客**确认后**，友好引导…」（= 点确认卡**之后**才轮到验证码）。
# 两条都只写在 prompt 里，实测都被 LLM 违反，后果同族 —— **顾客可见的"承诺与事实不符"**
# （run 34849029334 / SHA 929732b4 的 OR-026 两条失败指纹逐一对应）：
#   · 次败 R2「手机号已更新」，而**截至该轮没有任何写工具成功**
#     （评测全局检查 `check_unbacked_state_claim` 判红）。
#   · 首败 R3/R4 在确认卡**待顾客点击**期间反复回「验证码收到啦 / 请把验证码发我」→
#     协作型顾客按话术供码 → 写调用被确认门禁拦下（**这是正确行为**）→ 顾客的动作
#     永远推不动流程 → agent 再发卡、再提验证码 … 循环到轮数耗尽，
#     `order_create` 全程 2 次调用**无一成功**（issue #3445 家族：被
#     `confirmation_required` 挡回后流程不收敛；指纹 `confirmation_required_no_card`）。
# 处置与既有惯例一致（「改 3 次 prompt 修不好 → 代码管」，同 8.3b 补卡 / 加工项卡改写）：
# 写未成功前，回复只允许「草稿态措辞 + 唯一下一步（点确认卡）」。**只改文本，
# 不放行任何写调用**（`#3414` 教训），确认门禁本身一字不动。
_DRAFT_CLAIM_MARKERS = (
    # 变更态（在办流程里的修改）：prompt `:81` 显式点名「已更新/已修改」
    "已为您更新", "已更新", "已修改", "已改好", "地址已改", "已生效",
    # 完成态（订单类写宣告）：prompt `:82`「"订单已创建"**仅**可在 order_create 成功后说」
    "已成功提交", "已为您提交", "已提交订单", "订单已提交", "订单已创建",
    "已为您下单", "下单成功", "已创建",
)
_DRAFT_STATE_PHRASE = "已记下（下单时一并提交）"
# 与断言侧同源（`tests/agent_eval/local_runner.py:_CODE_REQUEST_HINTS`）：顾客与评测
# harness 一样，靠回复文本里这几个词判断"客服在索要验证码"。
_DRAFT_CODE_ASK_HINTS = ("验证码", "校验码", "短信码", "动态码", "verification code")


def normalize_draft_state_reply(text: str) -> tuple:
    """写未成功前的回复归一：**草稿态措辞 + 唯一下一步**。返回 `(新文本, 命中说明)`。

    纯函数（无 IO），便于单测直接钉住判据。两件事：
      ① 完成/变更态措辞 → 草稿态措辞（`customer_order_skill.py:81-82` 的代码兜底）；
      ② 去掉「索要/复述验证码」的句子 —— 确认卡待点时**唯一**可执行下一步是点卡，
         此时提验证码会把顾客引向一个**推不动流程**的动作（写调用必被门禁拦下，
         见本文件 8.6 头部实证），这正是 #3445 家族"流程不收敛"的成因。

    `<interact>` 卡片块（8.3b 补的卡或模型自己给的卡）先摘出来原样放回，
    避免把卡片字段/confirmValue 误删（卡是顾客唯一的操作入口）。
    """
    raw = str(text or "")
    if not raw:
        return raw, []
    head, sep, card = raw.partition("<interact>")
    notes: list = []
    for marker in _DRAFT_CLAIM_MARKERS:
        if marker in head:
            notes.append(f"完成态措辞「{marker}」→ 草稿态")
            head = head.replace(marker, _DRAFT_STATE_PHRASE)
    kept = []
    for seg in re.split(r"(?<=[。！？!?；;\n])", head):
        if seg and any(h in seg for h in _DRAFT_CODE_ASK_HINTS):
            notes.append("去掉验证码诉求句（确认卡待点，唯一下一步＝点卡）")
            continue
        kept.append(seg)
    head = "".join(kept)
    if not head.strip():
        # 全被删净时不留下空回复（顾客必须拿到**一个**可执行动作）
        head = "亲，订单信息我记下了，麻烦您点一下上方卡片确认，我马上帮您提交～"
    return head + sep + card, notes


# ── 算料必须以"顾客给的窗户尺寸"为前提（issue #3395，DB 实证多收 3 倍钱）──────
# 实证（run 34748745308，OR-022/OR-021）：顾客「我想买遮光窗帘，米白 **3 米**，要打孔加工」
# —— 说的是**买 3 米布**。模型把它当成「窗宽 3 米」，再把窗高默认成 2.7 米，于是：
#     P = ceil((3+0.3)×2/2.8) = 3 幅，M = 3×(2.7+0.3) = **9.0 米**
# → `order_create{遮光窗帘×9@168}`，落库 **¥1584**（顾客要的是 ¥528），另一跑还出现 ×9.3。
# 顾客视角完全无法察觉"被多算 3 倍"，属金钱正确性缺陷。
# 判据：会话里**出现过窗户尺寸措辞**才允许算料。为什么这样不卡死：模型缺尺寸时会先问，
# 问过之后会话里自然出现「窗宽/窗高」→ 下一轮放行（自愈）；而顾客直接报"要 3 米"时，
# 会话里永远不会有尺寸措辞 → 一直被拦，逼模型走"按米数下单"而不是"按窗宽算料"。
_DIMENSION_HINTS = ("窗宽", "窗高", "宽度", "高度", "尺寸", "多宽", "多高", "米宽", "观星台")


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
    # C 端专属：`curtain_calc` 是元元（顾客自助）的报价能力；B 端黄金策有自己的算料链路。
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


# ── B 端权限范围注入（issue #4107 / 父单 #4103 的 F8）──────────────────────────
# 权限码 → 产品能力名：**权威源是 admin-api 的权限目录**（两张 code→name 表：
# `RegistrationService.initializeDefaultRolesAndPermissions` 的 `defaultPermissions`
# = 全量 18 条；`PermissionService.ensureFullPermissionCatalog` = 其中 16 条子集）。
# 这里只是**只读镜像**（名称逐字取自 Java 表，不改写、不润色），漂移由
# `tests/test_permission_scope_injection.py` 的目录守卫机械核对：缺标签 / 标签多余 /
# 名称不一致**都红**（并有"处方码"负例证明它会红）。目录外的码（租户自定义权限）
# **不编名字**，原样回显码本身（详见 `_inject_permission_scope`）。
PERMISSION_LABELS = {
    "dashboard:view": "仪表板查看",
    "product:list": "商品管理",
    "product:create": "新增商品",
    "product:category": "商品分类",
    "processing:manage": "加工管理",
    "processing:view": "加工单查看",
    "processing:update": "加工单操作",
    # 生产执行**写**码（issue #5699 的 I4）：名称逐字取 admin-api `RegistrationService` 的同码条目
    "production:execute": "生产执行",
    # 质检录入**写**码（issue #5652）：名称逐字取 admin-api `RegistrationService` 的同码条目
    "production:inspect": "质检录入",
    # 入库单（V111，issue #5034）：名称逐字取 admin-api RegistrationService 的同码条目
    "inbound:view": "入库单查看",
    "inbound:create": "入库单操作",
    # 🔴 issue #8087（用户 2026-10-29 裁定 C）：`inbound:view` 拆出的三把读码，名称逐字取
    # admin-api RegistrationService/PermissionService 的同码条目（两处目录必须逐值相等）。
    "supplier:view": "供应商查看",
    "purchase:view": "采购单查看",
    "stock:view": "库存单证查看",
    "knowledge:manage": "知识库管理",
    # issue #5246：售后 / 知识库拆出**读**码 —— 镜像必须与 admin-api 权限目录逐码对齐
    # （判据：tests/test_permission_scope_injection.py 的两条「目录 ⊆ 标签」）。
    "after_sales:view": "售后查看",
    "knowledge:view": "知识库查看",
    # issue #5246 第二批：把「写动作挂在读码上」的四个域拆出写码（用户裁定本轮一并收口）
    "order:update": "订单操作",
    "order:create": "新增订单",
    "customer:create": "客户维护",
    # issue #5291：三个域新增**读**码（名称逐字取 admin-api RegistrationService 的同码条目）。
    "product:category:view": "商品分类查看",
    "production:view": "生产查看",
    "system:view": "岗位权限查看",
    "finance:create": "财务操作",
    "agent:session:manage": "会话操作",
    "order:list": "订单列表",
    "order:detail": "订单详情",
    "order:refund": "订单退款",
    "customer:view": "客户管理",
    "finance:view": "财务对账",
    "agent:session": "会话监控",
    # 黄金策唤出码（issue #5642 功能⑤）：名称逐字取 admin-api `RegistrationService.defaultPermissions`
    # 的同码条目（该行名称列 = 「黄金策对话」）。**只读镜像**：不改写、不润色；
    # 缺标签 / 名称不一致由 `tests/test_permission_scope_injection.py` 的目录守卫机械判红。
    "agent:chat": "黄金策对话",
    "employee:list": "员工列表",
    "employee:create": "新增员工",
    "system:manage": "系统管理",
}

#: 注入块最多列出的权限码条数（prompt 预算：超出只给计数，不把 prompt 撑成权限清单）
_MAX_SCOPE_CODES = 20


def _inject_permission_scope(system_prompt: str, state: AgentState) -> str:
    """B 端（黄金策）**权限范围**注入（issue #4107 / 父单 #4103 的 F8）。

    让模型知道「本会话人是谁、当前账号已开通哪些能力」，从而：权限拒绝不重试、
    如实说明缺哪项能力并给开通路径（对应 principles.md 的权限归因规则两半）。

    ⚠️ 注入的是「**已开通能力**」而不是「能力全集」（issue #4147 G6，裁定见 #4150）：
    权限码只覆盖**声明了 `required_permissions` 的工具**，而 `order_query` /
    `product_search` / `knowledge_search` / `notification_manage` 等 B 端工具
    **只按角色开放**（没有码）—— 清单天然不完整，因此**不得**写成「仅限以下，超出即无权」
    这类排他断言、也**不得**叫模型"不要调用工具尝试"：那会让模型把"清单里没有"读成
    "没有这个能力"，对用户本身就有能力造成**假拒绝**。
    模型可以（也应该）先发起调用，**由系统给出权威结论**：真被拒时不再重试，
    如实说明并给开通路径。

    - 仅 B 端（`agent_type == "mibao"`）且权限码非空、非 admin 通配（`"*"`）时注入；
      C 端（xiaobu）/ 空权限 / 通配权限 ⇒ **原样返回同一个对象**（逐字节不变，C 端零回归）
    - 能力名取自 `PERMISSION_LABELS`（admin-api 权限目录的只读镜像）；目录外的码原样回显，
      **绝不补造名字**（自造码会把模型引向不存在的越权能力）
    - 码做换行消毒 + 50 字截断（与 `identity_prefix` 同口径）——否则被篡改的 claim 能在
      prompt 里伪造出注入块之外的行
    - 任何异常不抛（fire-and-forget 语义，与 `_inject_user_memories` 一致）
    """
    try:
        if state.get("agent_type") != "mibao":
            return system_prompt
        raw_perms = state.get("permissions")
        # 形状守卫：只有**码列表**才有范围可言。裸字符串（如 "order:list"）逐字符迭代会注入
        # 一串单字符"码"（比不注入更糟）⇒ 非列表一律按"没有可说的范围"处理。
        if not isinstance(raw_perms, (list, tuple)):
            return system_prompt
        codes = [
            c.replace("\n", " ").replace("\r", " ").strip()[:50]
            for c in raw_perms
            if isinstance(c, str) and c.strip()
        ]
        # admin 通配（`["*"]`）= 无范围可言；注入反而会让模型误以为"只有这些能力"
        if not codes or "*" in codes:
            return system_prompt
        ordered: List[str] = []
        for c in codes:                      # 去重且保序（会话顺序 = 用户习惯顺序）
            if c not in ordered:
                ordered.append(c)
        shown = ordered[:_MAX_SCOPE_CODES]
        caps = "、".join(
            f"{PERMISSION_LABELS[c]}({c})" if c in PERMISSION_LABELS else c
            for c in shown
        )
        if len(ordered) > _MAX_SCOPE_CODES:
            caps += f"…（共 {len(ordered)} 项）"
        role = str(state.get("role") or "").replace("\n", " ").replace("\r", " ").strip()[:50]
        logger.info(
            f"[permission-scope] 注入 B 端权限范围 role={role or '未知'} codes={len(ordered)}"
        )
        return (
            "【权限范围】当前会话人的角色：" + (role or "未知") + "\n"
            "- 当前账号已开通的能力：" + caps + "\n"
            # ⚠️ 措辞纪律（issue #4147 G6；裁定见 #4150）：**不得**写成「仅限以下，超出即无权」，
            # 也**不得**叫模型"不要调用工具尝试"。权限码只覆盖声明了 `required_permissions`
            # 的工具，`order_query` / `product_search` / `knowledge_search` /
            # `notification_manage` 等 B 端工具**只按角色开放、没有码** ⇒ 清单天然不完整；
            # 排他断言/禁止尝试会让模型把"清单里没有"读成"没有这个能力"，对用户本身就有能力
            # 造成假拒绝（真实评测 run 35264687083：模型因此**一次都没调用** employee_manage，
            # HR-009/HR-010 全红）。改为"**先调用，由系统给权威结论**"：真被拒时不再重试、
            # 如实说明并给开通路径（F7 两半都保留）。
            #
            # ⚠️ 终态语义**收窄到同一调用**（issue #4197；改前是"换参数同样不会成功，权限拒绝是
            # 该请求的终态"）：那句对**按 action 分权**的工具是**假真值** —— 本仓库的权限是
            # action 级校验的（`employee_manage`：读要 `employee:list`、写要 `employee:create`；
            # `order_manage` 的 `ACTION_PERMISSIONS` 只有 `refund` 要 `order:refund`，其余只要
            # `order:list`）⇒ **换 action 确实可能成功**。旧措辞把"这一次被拒"说成"整个工具没戏"，
            # 等于教模型过度泛化（一拒全拒）⇒ HR-010（正向对照：持 `employee:create` 时同一请求
            # 必须**真的执行**）恒红的红因在**处方**、不在模型。收窄后：同一调用/同一失败调用
            # 仍是终态（**不得跨轮重复**，与 HR-009 的 `must_fail` + `data_checks`
            # 「同一失败的 create 调用不得跨轮重复」相容 —— 它禁的是自旋，不是换 action 的那一次），
            # 但允许**换一个 action 再试一次**（只一次，仍被拒就停手）。
            "- 调用被系统以权限不足拒绝时：**不要重试**同一调用"
            "（重试同一调用不会成功：权限拒绝是**该调用**的终态，同一失败调用不得跨轮重复）；"
            "同一工具的不同 action 权限可能不同（查询 vs 写入、退款 vs 改单）："
            "被拒后**换 action 可以再试一次**，仍被拒就停手；"
            "随后如实告知用户其账号缺少哪项能力，并指引其联系管理员在「岗位权限」或"
            "「员工管理」开通该权限\n"
            "【权限范围结束】\n\n"
            + system_prompt
        )
    except Exception as e:
        logger.warning(f"[permission-scope] 注入失败（非致命）: {e}")
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


# ── 写工具净化不再静默（issue #3930）────────────────────────────────────────
# 生产实证（sess_2efa2071bb1747d8，2026-09-15）：用户「先把这张色卡图设为主图」，
# agent 把请求路由到 product_update（它没有 images 参数）→ _sanitize_tool_args 静默丢弃
# images → 空字段调用 → 「没有要修改的字段」→ 模型外推「该入口不支持图片」→ 编造性否定出站。
# 修复：写工具丢弃**图片类**未知参数时不再静默 —— 直接失败 + 指引（不执行），误宣链源头切断。
# ⚠️ #5318 改判：指引**不再点名 product_manage**（它自 #5247 起已从 B 端全部 skill 解绑
# ⇒ 点名就是把模型推向必然 tool_not_found 的调用）；改为「如实说明图片写入不在能力内 +
# 引导商家到后台「商品管理」页面」。
# ⚠️ 只对图片类参数生效：非图片类未知参数维持 issue #3361 的静默净化（存量用例依赖，
# 见 test_graph_skills.py 的 test_unexpected_kwarg_dropped）；只读工具永远静默
# （查询类模型爱带多余参数，不能因此失败）。
_IMAGE_DROP_GUIDANCE = {
    "images": "商品主图写入不在黄金策能力内（改图不代做）——请如实说明，并引导商家到"
              "后台「商品管理」页面操作",
    "detail_images": "商品详情图写入不在黄金策能力内（改图不代做）——请如实说明，并引导商家到"
                     "后台「商品管理」页面操作",
    "main_image": "商品主图写入不在黄金策能力内（改图不代做）——请如实说明，并引导商家到"
                  "后台「商品管理」页面操作",
}


def _dropped_args_guidance(tool, tool_args: dict) -> str:
    """写工具被丢弃的**图片类**未知参数 → 失败指引文本（空串 = 不拦截）。"""
    if getattr(tool, "read_only", True):
        return ""
    accepted = _accepted_param_names(tool)
    if accepted is None or not isinstance(tool_args, dict):
        return ""
    hit = [k for k in tool_args if k not in accepted and k in _IMAGE_DROP_GUIDANCE]
    if not hit:
        return ""
    return "参数不受支持: " + "；".join(
        f"{k}: {_IMAGE_DROP_GUIDANCE[k]}" for k in hit)


def tool_timeout_s(tool_name: str) -> float:
    """该工具的执行预算（秒）：全局默认 `TOOL_TIMEOUT_S`，可按工具名覆盖（issue #7707）。

    为什么必须能按工具放宽：生图是**慢工具**（成功路径实测 30~60s），而这里原本写死 30s ⇒
    超时出口 `error="timeout"` 和「模型不接这类请求」在读数上不可区分，归因指向错误的层
    （#7707 的现场：内核读超时 `IMAGE_GEN_TIMEOUT=180s` 根本没被触发）。
    只放宽**具名慢工具**，不抬全局预算（那会把所有卡死工具一起拖长）。
    解析不了的条目忽略（预算配置写错不该让工具全挂）；非正值退回默认（安全护栏不能被配成"立刻超时"）。
    """
    raw = (getattr(settings, "TOOL_TIMEOUT_OVERRIDES", "") or "").strip()
    for item in raw.split(","):
        name, _, value = item.partition("=")
        if name.strip() != tool_name:
            continue
        try:
            seconds = float(value.strip())
        except (TypeError, ValueError):
            logger.warning(f"[tool-exec] TOOL_TIMEOUT_OVERRIDES 里有坏条目，已忽略：{item!r}")
            break
        if seconds > 0:
            return seconds
        break
    return float(getattr(settings, "TOOL_TIMEOUT_S", 30.0) or 30.0)


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
    _raw_args = dict(tool_args)
    tool_args = _sanitize_tool_args(tool, tool_args)

    # 1.1 出口字典**单点构造**（issue #4057 T4）：`ToolResult` 声明的字段全在这一个字面量里，
    # 全部 5 条出口（参数丢弃 / 缓存命中 / 超时 / 异常 / 正常）**共用**它 —— 异常出口只覆盖
    # error/message，不得再各自手写 `{"success": False, "error": …}`（那会让
    # message/summary/suggestion/terminal/data 在某条出口缺席 = 消费点恒 None，而契约守卫
    # `tests/test_contract_wiring.py` 改前只看正常出口那一个字面量 ⇒ 静默违反）。
    # ⚠️ 异常出口**不补 suggestion**：`_self_correct_retry` 以 suggestion 为触发条件，
    #    补它会改变重试行为（属 T1/T3 范围）。
    result_dict = {
        "success": False,
        "data": None,
        "error": None,
        "message": None,
        "summary": "",
        "suggestion": "",
        "terminal": False,
        # admin-api 错误码（issue #4106 F6 带出 / #4109 消费）：`_self_correct_retry`
        # 用它判定「授权类失败不得重试」。异常/超时出口留空 = 可重试（fail-safe 见该函数）。
        "error_code": None,
        "missing_params": [],
    }

    # ── 工具层权限拒绝：码由**共享判据**盖章（issue #4147 G2）────────────────────
    # 病灶：工具层 `check_permission` 的拒绝从不带 `error_code`（41 处手写
    # `ToolResult(success=False, error="权限不足")`）⇒ #4122 的非重试闸门
    # （`error_code in NON_RETRYABLE_ERROR_CODES`）对它**恒不触发**：幂等工具仍被
    # `_self_correct_retry` 拿去做「参数改写重放」（拿同一身份同一权限再调一次永远不可能成功）。
    #
    # 为什么判据在这里、而不去逐个改 41 处：① 其中 3 个文件属其它包持有，
    # 逐点手改必然漏 —— 而漏掉的那一处就是闸门的静默缺口；② 判据是**机械的**
    # （工具级门禁说「不」+ 它交付了失败 ⇒ 这次失败的性质就是权限拒绝），
    # 与工具**怎么措辞**无关 —— 文案有跨端型（「该查询仅限顾客本人使用」）与
    # 权限型（「请联系管理员获取…权限」）两种，拿文案当判据会静默失效（§19.1）。
    # 工具自己的文案**原样保留**（跨端指引比统一文案更有用），这里只补机器可读的码。
    # 门禁之外的拒绝点（action 级 / 归属级）不走这条判据，由 L0 静态锁
    # （tests/test_tool_denial_semantics.py）要求它们自己走 `permission_denied(...)`。
    _gate_check = getattr(tool, "check_permission", None)
    # `is False` 而非 falsy：替身（MagicMock）的属性访问会自动变出 Mock，falsy 判据会把
    # 它们当成"拒绝"（同 `validate_args` 只认 ToolResult 实例的既有取舍）。
    _gate_denied = callable(_gate_check) and _gate_check(tool_context) is False

    # 写工具图片类参数被丢弃 → 不执行，返回失败 + 正确工具指引（issue #3930）：
    # 静默丢弃会制造「空字段调用 → 没有要修改的字段 → 模型外推该入口不支持图片」的误宣链。
    _drop_msg = _dropped_args_guidance(tool, _raw_args)
    if _drop_msg:
        logger.warning(f"[tool-arg-sanitize] {tool.name} 写工具图片类参数被丢弃 → 拒绝执行: {_drop_msg}")
        result_dict["error"] = result_dict["message"] = _drop_msg
        return json.dumps(result_dict, ensure_ascii=False), result_dict

    # 1.5. 自动解析 _ids 参数：LLM 传加工项名称/序号时自动转 UUID
    tool_args = await _auto_resolve_ids(tool, tool_args, state)

    # ── 1.6 入参契约校验（issue #4080 T2）──
    # 工具**自己声明的** `parameters` 必须在这里被真的消费：缺显式 required / 类型不可解析 /
    # 枚举越界 ⇒ **不执行本体**，直接回结构化失败（error + 可执行 suggestion + missing_params），
    # 由 react_turn 的 `_self_correct_retry` 自愈链接手（它第二行就是"没有 suggestion 就短路"）。
    # 为什么放在共享执行入口：判据**不逐工具手写**（R1）—— react_turn 与 finalize_turn 都走这里。
    # fail-open：没有 `parameters` 的鸭子类型替身 `getattr` 取不到 ⇒ 不校验（不静默拦合法调用）；
    # **只认 `ToolResult` 实例**：`MagicMock` 工具（并发/隔离测试里大量使用）的属性访问会自动
    # 变出 Mock 对象，`is not None` 判据会把它们当成"契约失败"而误拦（实测：15 个隔离用例红）。
    _args_contract_check = getattr(tool, "validate_args", None)
    if callable(_args_contract_check):
        _contract_failure = _args_contract_check(tool_args)
        if isinstance(_contract_failure, ToolResult):
            # 填**共用出口字典**（#4057 T4 的单点出口）—— 不另造字典，否则异常出口会缺字段
            result_dict["error"] = _contract_failure.error
            result_dict["message"] = _contract_failure.message
            result_dict["suggestion"] = getattr(_contract_failure, "suggestion", None) or ""
            result_dict["missing_params"] = list(
                getattr(_contract_failure, "missing_params", None) or [])
            return json.dumps(result_dict, ensure_ascii=False), result_dict

    session_id = state.get("session_id", "")
    tenant_id = str(state.get("tenant_id", ""))
    tool_name = tool.name
    # 缓存键必须覆盖**结果依赖的全部事实**（issue #4079 / A5）：`validate_input` 的结论依赖
    # 「当前 skill 执行域」（域内 → success；域外 → `cross_skill_target`）⇒ 键里必须带域。
    # 不带就是**跨域串味**：同租户 60s 内 A 域的成功结论会被 B 域命中（B 域根本执行不了那个
    # 工具）⇒ A5 的死角从缓存里被放回来（"校验通过 → 确认卡 → Tool not found"）。
    # 域外结论本身不进缓存（下面只存 success），所以受影响的正是上面这条危险方向。
    _scope_key = ",".join(sorted(get_tool_scope() or ()))
    cache_key = (
        f"{tenant_id}:{_scope_key}:{tool_name}:"
        f"{json.dumps(tool_args, sort_keys=True, default=str)}"
    )

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
    # 写审计落库（issue #4039）：本函数是黄金策/元元**真实写路径**（直调 tool.execute，
    # 不经 ToolRegistry.execute_tool）⇒ hook 必须挂在这里，否则 audit_logs 恒 0 行。
    # 挂 finally：成功/超时/异常三条出口都留痕（失败也要可追溯）；只读工具不记。
    _audit_write = not tool.read_only
    _audit_t0 = time.time()
    _audit_ok = False
    try:
        logger.info(f"[tool-exec] {tool_name} start")
        result = await asyncio.wait_for(
            tool.execute(tool_context, **tool_args),
            timeout=tool_timeout_s(tool_name),
        )
        _audit_ok = bool(result.success)
        logger.info(f"[tool-exec] {tool_name} done success={result.success}")
    except asyncio.TimeoutError:
        logger.error(
            "[tool-exec] {} TIMEOUT {}s | args={}",
            tool_name,
            tool_timeout_s(tool_name),
            json.dumps(LogSanitizer.sanitize_tree(tool_args), ensure_ascii=False, default=str)[:300],
        )
        result_dict["error"] = "timeout"
        result_dict["message"] = "工具执行超时"
        return json.dumps(result_dict, ensure_ascii=False), result_dict
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
        result_dict["error"] = "tool_execution_failed"
        result_dict["message"] = f"工具 {tool_name} 执行失败，请检查参数格式后重试"
        return json.dumps(result_dict, ensure_ascii=False), result_dict
    finally:
        if _audit_write:
            await audit_write_tool(
                tool_name, tool_context, tool_args, _audit_ok,
                (time.time() - _audit_t0) * 1000,
            )

    # 4. 格式化结果（同一个出口字典，按成功分支填入 `ToolResult` 的真实字段）
    # `ToolResult` **声明的字段必须全部带进 result_dict**（issue #4013 A2：此前漏传
    # terminal/summary ⇒ 消费点 `result_dict.get("terminal")` 恒 None ⇒ reset_domain
    # 永不触发 = 死契约）。判据：tests/test_terminal_tool_and_prompt_contract.py。
    # 工具层权限拒绝的码（issue #4147 G2，判据见上方 `_gate_denied`）：工具自己给了码
    # （admin-api 映射点）就用它的；没给而门禁已判否 ⇒ 补 `PERMISSION_DENIED`。
    # 只在**真的执行过**的那条出口盖章：入参契约失败（缺参/类型/枚举）不在范围内 ——
    # 那是"要模型补参数"的失败，盖章会把补参的引导一并顶掉（真无权限时下一次调用
    # 会拿到带码的拒绝）。
    _error_code = getattr(result, "error_code", None)
    if not _error_code and _gate_denied and not result.success:
        _error_code = PERMISSION_DENIED_CODE
        logger.info(
            f"[tool-exec] {tool_name} 工具级权限门禁拒绝 ⇒ 交付结果补 "
            f"error_code={PERMISSION_DENIED_CODE}（抑制自修复重放）"
        )

    result_dict.update(
        success=result.success,
        data=result.data,
        error=result.error,
        message=result.message,
        summary=getattr(result, "summary", None) or "",
        suggestion=getattr(result, "suggestion", None) or "",
        terminal=bool(getattr(result, "terminal", False)),
        # 授权类失败的判定依据（#4109）：由 `admin_api_failure` 从 admin-api 响应填充。
        error_code=_error_code,
        missing_params=list(getattr(result, "missing_params", None) or []),
    )
    result_str = json.dumps(result_dict, ensure_ascii=False, default=str)

    # 5. 缓存（带锁）— 仅只读工具
    if result.success and tool.read_only:
        async with _execute_tool_safe._cache_lock:
            _execute_tool_safe._cache[cache_key] = {"result": result_str, "dict": result_dict, "ts": time.time()}
            if len(_execute_tool_safe._cache) > 100:
                _execute_tool_safe._cache.pop(next(iter(_execute_tool_safe._cache)))

    return result_str, result_dict


def _failure_text(result_dict: dict, default: str = "执行失败") -> str:
    """工具失败结果的**None 安全**文本取值（issue #4147 G1a）。

    为什么不能用 `result_dict.get("message", result_dict.get("error", "执行失败"))`：
    `.get` 的默认值只在**键缺席**时生效 —— 而 `_execute_tool_safe` 的出口字典**恒定包含**
    `message` 键（`ToolResult.message` 缺省就是 `None`）⇒ 键存在、值为 `None` 时
    该表达式返回 `None`，随后的 `error_msg[:80]` 直接
    `TypeError: 'NoneType' object is not subscriptable`。

    为什么判据必须落在**消费方**（而不是逐个工具去补 message）：任何工具都可能不给
    `message`（`ToolResult` 把它声明为 `Optional`，含糊的失败面很宽），靠"每个工具都规矩"
    = 下一个新工具必踩。这里的口径：**非空字符串才算给了**，否则依次回落到 `error` → 默认文案。
    """
    for key in ("message", "error"):
        value = result_dict.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return default


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

    ⚠️ 仅对**幂等**工具生效（issue #3564）：非幂等写工具（建单/建工单/转人工/发通知）
    失败时自动重放同一调用 = 重复副作用，一律不重试，把失败与 suggestion 交回模型决策。

    Returns:
        (result_str, result_dict) 如果重试成功；None 如果不需重试或重试失败。
    """
    suggestion = result_dict.get("suggestion", "")
    if not suggestion:
        return None

    # None 安全取值（issue #4147 G1a）：`message` 键**存在但值为 None** 时，
    # `.get(..., 默认值)` 不生效 ⇒ 下面的 `error_msg[:80]` 会抛 TypeError，
    # 而这几行在 try **之外** ⇒ 异常穿透、整轮对话被打断（真实身份实测）。
    error_msg = _failure_text(result_dict)

    # ── 授权类失败：禁止自动重试（issue #4109）───────────────────────────────
    # 权限拒绝（PERMISSION_DENIED / FORBIDDEN / 401 系列）拿**同一身份、同一权限**再调一次
    # **永远不可能成功** —— 自动重试只是把同一次拒绝又买了一遍；更糟的是重试入口会调
    # `suggestion_llm` 按「参数怎么补」改写失败，让模型把权限问题当参数问题（与
    # `admin_api_failure` 写给权限拒绝的「不要重试」建议直接打架）⇒ 用户等来的仍是「稍后重试」。
    #
    # 真值来源（单一真值，不另立清单）：`app/tools/base.py::NON_RETRYABLE_ERROR_CODES`
    # —— 与工具层 `admin_api_failure` 用的是同一个常量，也由 retry 侧消费（跨包契约，
    # 名字见 CONTRACT-LEDGER 第十节）。护栏落在**机制层**，不靠每个工具在 suggestion 里
    # 写"请勿重试"自觉（同 #3564 的取舍：靠工具自觉 = 下一个新工具必踩）。
    #
    # fail-safe（**显式声明**，不允许静默滑向任何一极）：`error_code` 缺失/为空 ⇒ 视为
    # **可重试**（= 既有行为不变）。理由：缺码的失败面很宽（超时 / 异常兜底 / 未走
    # `admin_api_failure` 的老路径），一律判成不可重试等于**关掉既有自修复能力**；
    # 而授权拒绝**一定有码**（工具层在授权分支无条件填码），故缺码不会漏判授权拒绝。
    # 该语义由 tests/test_tool_permission_retry_guard.py::TestRetryableFailuresStillRetry 锁住。
    if result_dict.get("error_code") in NON_RETRYABLE_ERROR_CODES:
        logger.warning(
            f"[{skill_name}][self-correct] Tool {tool.name} 授权类失败，"
            f"non-retryable: retry suppressed（自动重试已抑制，失败与 suggestion 交回模型决策）"
            f" | error_code={result_dict.get('error_code')} | error={error_msg[:80]} | session={session}"
        )
        return None

    # ── 非幂等写工具：禁止自动重试（issue #3564）─────────────────────────────
    # 原判据只有「success=False + suggestion」，**不区分工具幂等性** —— 对
    # order_create（建单）/ aftersale_create（建工单）/ human_handoff（转人工）/
    # notification_manage（发通知）这类**非幂等写**，失败时自动重放同一调用就是
    # **重复副作用**（重复建单/重复转人工）；而工具的 suggestion 常常正是
    # "参数怎么补"的引导语，会把重试包装得很合理。真实触发面很宽：工具「第一次已
    # 产生副作用但返回 success=False」（下游超时/响应丢失）时必然重复落库。
    #
    # 真值来源（单一真值，不另立清单）：工具自身的 MCP 风格标注 `BaseTool.idempotent`
    # （app/tools/base.py:86）——它早已是注册表里的既有元数据（get_schema() 就用它拼
    # `NON_IDEMPOTENT` 标签给 LLM 看），本处只是让**机制层**也消费它：护栏落在 retry
    # 侧，不靠每个工具在 suggestion 里写"请勿重试"自觉（靠工具自觉 = 下一个新写工具必踩）。
    # 新写工具"忘了表态"（吃 BaseTool 默认 True）由静态锁拦：
    # tests/test_tool_idempotent_retry_guard.py::TestIdempotencyClassificationLock。
    #
    # fail-safe：取不到标注（非 BaseTool 的替身/新形态工具）一律视为不可重试。
    # 只读查询与显式 idempotent=True 的写工具（product_update/sku_update 等）**照旧重试**
    # —— 既有能力不关闭。
    if not getattr(tool, "idempotent", False):
        logger.warning(
            f"[{skill_name}][self-correct] Tool {tool.name} 非幂等写工具，"
            f"non-idempotent: retry suppressed（自动重试已抑制，失败与 suggestion 交回模型决策）"
            f" | error={error_msg[:80]} | session={session}"
        )
        return None

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
                f"{_failure_text(corrected_result_dict, 'unknown')[:80]}"
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
        # 涉钱面（改价）例外（issue #5317）：文本确认**不得**记为「已确认」——
        # 否则 `react_turn` 的 `_write_was_confirmed` 会拿它放行一次改价，
        # 而那张卡可能从没发出去过（护栏又变成"只证明确认过"）。
        if pending and pending.get("target_tool") and (
                is_card_confirm or (_is_explicit_confirmation(last_user_msg or "")
                                    and not _pending_card_only(pending))):
            _f = dict(full)
            # 与门禁同源记「已确认工具 + 被确认的订单金额事实」（issue #4037 / F22）：
            # 事实取自**已校验待执行的参数**（顾客确认的就是这一份）。
            record_confirmed_write(_f, pending["target_tool"], pending.get("params") or {})
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


#: 点卡轮注入里「目标工具」的**反推表**（只读卡内容，不猜）：卡字段标签 → 写工具。
#: 为什么必须反推：这一轮模型手里只有「一条看起来像文本的用户消息」，
#: 而 `pending_validated_input` 只有走 `validate_input` 的流程才有 ——
#: 改价（`product_update` / `sku_update`）与批量库存（`product_batch_update`）都不经过它
#: ⇒ 没有本表就只能给事实、给不出「该调哪个工具」（issue #6985 实测的两条路径都是这一类）。
_CARD_FIELD_TARGETS = (
    ("改前库存", "product_batch_update"), ("改后库存", "product_batch_update"),
    ("改前价", "product_update"), ("改后价", "product_update"),
)

#: 点卡轮注入模板（`{tool}` 为空时用「发卡时计划调用的那个写工具」这一泛指）。
_CARD_CLICK_SIGNAL_TEMPLATE = (
    "【系统事实 · 顾客刚**点击**了确认卡】顾客本轮消息与系统上一次发出的确认卡 "
    "confirmValue **逐字相同** —— 这是**点卡回传**，不是商家打字输入的文本。\n"
    "该卡确认的写操作现在**已获确认**：本轮应当调用 {tool} 执行（参数按卡上展示的内容填），"
    "**不要**再发一张确认卡、也不要再问一次「是否确认」—— 重发只会让商家再点一次、流程永不收敛。\n"
    "（判据同源：`_is_card_confirm_value` —— 用户消息**逐字等于**系统自产的卡值才算点卡；"
    "其它任何文本都不是点卡。）"
)


def _card_click_target_tool(card: dict | None) -> str:
    """从**确认卡内容**反推这张卡在确认哪个写工具（认不出 ⇒ 空串，不猜）。

    只用卡字段标签（`interact(component=confirm, fields=[…])` 的 label）——
    「改前库存/改后库存」⇒ 批量库存调整 `product_batch_update`；
    「改前价/改后价」⇒ 改价（商品级统一 `product_update`；单规格由卡片来源决定，
    这里给的是**同一张卡的默认写工具**，模型可据卡上「规格」信息改用 `sku_update`）。
    """
    fields = (card or {}).get("fields")
    if not isinstance(fields, list):
        return ""
    labels = " ".join(
        str((f or {}).get("label") or "") if isinstance(f, dict) else str(f or "")
        for f in fields
    )
    for key, tool in _CARD_FIELD_TARGETS:
        if key in labels:
            return tool
    return ""


def _is_card_click_round(last_user_msg: str, session_state: dict | None) -> bool:
    """本轮是否是**点卡轮**（判据与门禁**同源**：`_is_card_confirm_value`，不另立第二份口径）。

    为什么需要这个判定（issue #6985）：模型看不到系统内部的「卡值精确匹配」，
    它只看到一条长得像文本的用户消息；而 4 处涉钱 prompt 又写着绝对措辞
    「商家打字「确认」不算」⇒ 模型自造第二条判据、判「这不是点卡」⇒
    反复重发新卡（`confirmValue` 每轮还在变）⇒ 永远走不到「点卡后再次调用写工具」。
    """
    if not isinstance(session_state, dict):
        return False
    return _is_card_confirm_value(last_user_msg or "",
                                  session_state.get("last_confirm_value"))


async def _inject_card_click_signal(system_prompt: str, state: AgentState,
                                    last_user_msg: str) -> str:
    """点卡轮注入「顾客刚点击了确认卡」的**上下文事实**（issue #6985，修法①）。

    与 `_inject_pending_validated` 的分工：那条管「已校验待执行」的 `validate_input` 流程；
    本条管**不经 `validate_input` 的 A 档写路径**（改价 / 批量改价 / 批量库存），
    它们的「缺的那一步」不是参数，而是**模型不认这是点卡**。

    边界（照实登记）：
      · **只加事实、不放行**：确认门禁、`confirmed_write_release` 的放行链一字未动；
      · **只读**：不写会话状态（不得借注入改放行账）；
      · **只在点卡轮**：判据 = `_is_card_confirm_value`（逐字等于系统自产卡值）⇒
        普通文本「确认」/ 前缀相同 / 无卡 / 无 session 一律**原样返回**；
      · 任何异常不抛（与既有 `_inject_*` 同口径），失败即不注入。
    """
    if not state.get("session_id"):
        return system_prompt
    try:
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(state["session_id"]) or {}
        if not _is_card_click_round(last_user_msg, full):
            return system_prompt
        tool = _card_click_target_tool(full.get("last_card"))
        if not tool:
            # 卡值匹配那轮记下的目标工具（`record_confirmed_write` 同源落账）
            tool = str(full.get("confirmed_write_tool") or "")
        signal = _CARD_CLICK_SIGNAL_TEMPLATE.format(
            tool=tool or "发这张卡时计划调用的那个写工具")
        logger.info(
            f"[card-click] 点卡轮事实注入 | session={state['session_id']} target={tool or '-'}")
        return signal + "\n\n" + system_prompt
    except Exception as e:
        logger.warning(f"[card-click] 注入失败（非致命）: {e}")
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

    实现形态（issue #4049；拆分源头是「关联 #4043」的 S3 条）：本函数是**薄编排壳**。
    原先 1699 行的单函数按职责切成三段，**逐字搬迁**到 `app/graph/skills/execution/`：

      · `prepare_turn`  ：0~6 节 —— 防御层（速率/截断）/ 上下文与工具 / 消息 / LLM /
                          system prompt 组装 / 跨轮注入与压缩 / Vision 分支
      · `react_turn`    ：第 7 节 —— ReAct 循环（写门禁链、工具调用、卡片发射、纠偏）
      · `finalize_turn` ：8.3b~8.6 + 9/10 节 —— 补发确认卡兜底 / 确认-执行链代码侧收口 /
                          草稿态回复归一 / 返回值组装 / 跨轮 `pending_skill` 持久化

    这里只保留**分节注释 + 三次调用 + 返回**；数据流接口（谁传什么、谁交回什么、
    哪些是必须保持同一对象的可变容器、哪些是条件绑定的状态）写在各模块的注释里。
    """
    # ⚠️ **函数内 import，不是模块顶层**：`execution/*` 顶层 `from app.graph.skills.base_skill
    #     import ...` 取本文件里的模块级助手（`_execute_tool_safe` / `_self_correct_retry` /
    #     `_build_system_prompt` / `_inject_*` / 常量…）。若把下面三条提到模块顶层，
    #     加载期立刻成环（`base_skill` → `execution.react_turn` → `base_skill` 半加载 ⇒
    #     ImportError）。理由、图示与「别整理这三行」的原因见
    #     `app/graph/skills/execution/__init__.py`。
    from app.graph.skills.execution.finalize_turn import finalize_turn
    from app.graph.skills.execution.prepare_turn import prepare_turn
    from app.graph.skills.execution.react_turn import react_turn

    # ── 0~6 节：防御层 / 上下文与工具 / 消息 / LLM / system prompt / 跨轮注入与压缩 / Vision ──
    # `execute_skill` 自己作为参数传入：速率限制窗口按拆分前语义**仍挂在
    # `execute_skill._rate_map` 这个函数属性上**（`prepare_turn` 里那三行逐字未改），
    # 换容器 = 限流静默失效/被外部观察路径看不到。
    prep = await prepare_turn(state, skill_name, tool_names, system_prompt, execute_skill)
    # 0 节的速率限制早退：`prepare_turn` 里那一处 `return` 是**逐字保留**的最终结果字典
    # （`{"messages": [], "final_answer": "请求过于频繁…", "skill_used": skill_name}`）
    # ⇒ 以 `final_answer` 为判据原样透传，不改一个字符。
    if "final_answer" in prep:
        return prep

    # ── 7 节：ReAct 循环 ──
    turn = await react_turn(
        state=state,
        skill_name=skill_name,
        max_iterations=max_iterations,
        raw_messages=prep["raw_messages"],
        session_id=prep["session_id"],
        tenant_id=prep["tenant_id"],
        tool_context=prep["tool_context"],
        skill_registry=prep["skill_registry"],
        new_messages=prep["new_messages"],
        is_multimodal=prep["is_multimodal"],
        llm_model_name=prep["llm_model_name"],
        llm_no_thinking=prep["llm_no_thinking"],
        llm_with_tools=prep["llm_with_tools"],
        intent_name=prep["intent_name"],
        full_messages=prep["full_messages"],
        vision_analysis=prep["vision_analysis"],
        final_content=prep["final_content"],
        _denial_corrected=prep["_denial_corrected"],
        _stall_corrected=prep["_stall_corrected"],
        _no_card_blocked_args=prep["_no_card_blocked_args"],
        _no_card_blocked_tool=prep["_no_card_blocked_tool"],
        _no_card_blocked_facts=prep["_no_card_blocked_facts"],
        _write_ok=prep["_write_ok"],
        _relocked_this_round=prep["_relocked_this_round"],
    )
    # ── 8.3b / 8.4 / 8.5 / 8.6 节 + 9 / 10 节 ──
    # 注意 `new_messages`（第 7 节 append 过的**同一个 list**）与 `_executed_tools` 都按
    # **对象本身**继续传递 —— 8.4 的防双单判据、`result["messages"]` 都依赖同一性。
    return await finalize_turn(
        state=state,
        skill_name=skill_name,
        session_id=prep["session_id"],
        skill_registry=prep["skill_registry"],
        new_messages=prep["new_messages"],
        final_content=turn["final_content"],
        _no_card_blocked_args=turn["_no_card_blocked_args"],
        _no_card_blocked_tool=turn["_no_card_blocked_tool"],
        _no_card_blocked_facts=turn["_no_card_blocked_facts"],
        _write_ok=turn["_write_ok"],
        _relocked_this_round=turn["_relocked_this_round"],
        _executed_tools=turn["_executed_tools"],
        PENDING_KEY=turn["PENDING_KEY"],
        last_user_msg=turn["last_user_msg"],
    )


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
