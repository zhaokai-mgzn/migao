"""
澄清轮次护栏 — 防低学历用户被无限澄清追问（issue #2796）

背景（docs/design/agent-clarification-capability-research.md §5/§6）：
澄清是"付费行动"，用户耐心预算约 1 轮。若用户连续答非所问/意图持续模糊，
AI 反复「您想做什么？A/B/C」追问会令用户放弃——达到上限后必须转
「给具体可执行示例 + 转人工出口」的兜底，而非继续追问。

纯函数设计（可单测、无 IO）：
- judge_clarify: 澄清轮次是否已达上限
- tick_clarify: 更新澄清轮计数（澄清轮 +1；用户给出实质意图的轮清零）
- judge_speculative_search: 「意图不明却臆断检索」判据（issue #9280 / CH-003）
- CLARIFY_FORCE_EXAMPLE_TEXT: 面向低学历的兜底话术常量
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Sequence

from loguru import logger

# ── 常量 ──

# 同一会话内"连续澄清"轮次上限（达到后不再追问，改给示例兜底）。
# 参照 Rao & Daumé（SIGIR 2019）"用户约 1 次提问耐心"+ 容错 1 轮。
MAX_CLARIFY_ROUNDS = 2

# SessionStateStore 中澄清状态键
CLARIFY_STATE_KEY = "clarify"

# 兜底话术（面向初中/高中文化用户：短句、给例子、给出口）
# ⚠️ 「出口」**不得**再写「说『转人工』让客服专员帮您」——用户裁定 2026-09-19：
# 转人工能力已退场（见 app/tools/registry.py 注册行注释），这句会把用户指向一个
# 不存在的入口。替代出口 = 继续用例子引导（例子本身就是出口：说清一件事即可）。
CLARIFY_FORCE_EXAMPLE_TEXT = (
    "没关系，我们换个方式～ 您可以试着直接说一句，比如：\n"
    "① 「查一下昨天那个订单」\n"
    "② 「搜一下遮光窗帘」\n"
    "③ 「帮我算下 3 米窗户要多少布」\n"
    "如果还不太确定，也可以直接把想问的原话发我，我来帮您理一理～"
)


# ── 纯函数 ──

def judge_clarify(clarify_count: int, max_rounds: int = MAX_CLARIFY_ROUNDS) -> bool:
    """澄清轮次是否已达上限（应转兜底）。

    Args:
        clarify_count: 当前连续澄清轮数（0 起）
        max_rounds: 上限（默认 2）

    Returns:
        True=已达上限，应强制给示例兜底；False=可继续澄清
    """
    return clarify_count >= max_rounds


def tick_clarify(
    state: Dict[str, Any],
    was_clarify_round: bool,
    max_rounds: int = MAX_CLARIFY_ROUNDS,
) -> Dict[str, Any]:
    """按本轮是否澄清轮更新澄清计数状态。

    规则：
    - was_clarify_round=True（本轮仍是模糊澄清）→ count+1（封顶 max_rounds）
    - was_clarify_round=False（用户给出实质意图/澄清卡被点选）→ 清零
    - 达到上限后状态标记 force_example=True，供调用方直接兜底

    Args:
        state: 读出的会话 clarify 状态（可为 {}）
        was_clarify_round: 本轮是否仍处于澄清轮（低置信重写 general 等）
        max_rounds: 上限

    Returns:
        更新后的 clarify 状态 dict（可直接写回 SessionStateStore）
    """
    cur = int((state or {}).get("count") or 0)
    if not was_clarify_round:
        return {"count": 0, "force_example": False}
    new_count = min(cur + 1, max_rounds)
    return {
        "count": new_count,
        "force_example": new_count >= max_rounds,
    }


def should_force_example(state: Dict[str, Any]) -> bool:
    """读取状态判断是否应强制示例兜底（不继续澄清追问）。"""
    if not state:
        return False
    return bool(state.get("force_example"))


# ── 「意图不明 ⇒ 不得臆断检索」（issue #9280 / CH-003）────────────────────────
#
# 缺陷（run 46086496186 的 xiaobu 腿逐字）：顾客只说了「帮我看看」，模型**猜出两个
# 顾客从未提过的关键词**（「遮光窗帘」「奶油风」）并直接 product_search / product_detail。
# C 端兜底 prompt 逐字写着「意图不明 → 用 choice 候选卡 … **不要默认直接搜相似**」
# 「不确定的细节不要臆断」—— 模型不守（同族：算料前提 / 下单接地都是「prompt 铁律
# 落成代码闸门」），故把这条铁律也落成**确定性判据**。
#
# 为什么 b 端（mibao）不受影响：B 端的模糊轮由 `app/graph/nodes.py::_vague_guess_route`
# 的猜测卡承接（`agent_type != "mibao"` 直接返回 None），且检索词来自**商家自己**的输入；
# 本判据的调用点按 `_is_customer_role` 限定 C 端，B 端语义一字未动。

#: 意图不明时**不得**调用的检索类工具：它们的共同前提是「顾客已经说出要查什么」。
SPECULATIVE_SEARCH_TOOLS = frozenset(
    {"product_search", "product_detail", "customer_order_query"})

#: L1 命中这些意图 = 这句话没有实质诉求（「说清了要什么」的反面）。
_VAGUE_L1_INTENTS = frozenset({"general", "greeting", "farewell", "capabilities"})

#: 顾客给了**具体数字**（订单号 / 手机号 / 尺寸 / 金额）= 已经说清了要查什么。
_DIGITS_RE = re.compile(r"\d{4,}")

#: 检索参数里**可能来自顾客原话**的字段（`product_id` / `action` 不是用户语言，不参与接地）。
_GROUNDABLE_ARG_KEYS = ("keyword", "query", "name", "product_name", "category", "order_no")

#: 检索词的切分（「奶油风 遮光窗帘」里只要有一个词是顾客说过的，就算接地）。
_TERM_SPLIT_RE = re.compile(r"[\s,，/、]+")


def _text_is_substantive(text: str) -> bool:
    """这一句顾客话是否给出了实质意图（三条**事实**信号，任一成立即可）。

    判据全部**复用既有实现**、不新造词表：
    ① 商品品类词 —— `#3365` 的 `extract_product_keyword`（窗帘/窗纱/面料/布艺/遮光帘）；
    ② 具体数字 —— 订单号 / 手机号 / 尺寸 / 金额；
    ③ L1 规则命中非兜底意图 —— `RuleMatcher`（退款/物流/算料…都在这条线上）。
    """
    if not text:
        return False
    from app.graph.skills.base_skill import extract_product_keyword

    if extract_product_keyword(text):
        return True
    if _DIGITS_RE.search(text):
        return True
    from app.router.rule_matcher import RuleMatcher

    hit = RuleMatcher().match(text)
    intent = getattr(hit, "intent", None) if hit else None
    return intent is not None and intent.value not in _VAGUE_L1_INTENTS


def _has_grounded_term(args: Dict[str, Any], user_text: str) -> bool:
    """本次检索的词是不是顾客**自己说过的**（整词，或切分后任一 ≥2 字的词命中）。"""
    for key in _GROUNDABLE_ARG_KEYS:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        whole = value.strip()
        terms = [whole] + [t for t in _TERM_SPLIT_RE.split(whole) if len(t) >= 2]
        if any(t in user_text for t in terms):
            return True
    return False


def judge_speculative_search(
    tool_name: str,
    args: Dict[str, Any] | None,
    user_texts: Sequence[str] | None,
    executed_tools: Iterable[str] = (),
) -> str:
    """「意图不明 + 模型想直接检索」判据：返回拦截话术（**空串 = 放行**）。

    放行（任一成立；每一条都对应一种**不该拦**的正常路径）：
      · 不是检索类工具（只读目录 / 写工具都不在本判据射程内）；
      · 顾客说过实质诉求（`_text_is_substantive`）—— 明确输入必须允许检索；
      · 本次检索的词是顾客自己说过的（`_has_grounded_term`）—— 照着原话搜不算臆断；
      · `product_detail` 且本回合已跑过 `product_search` —— 商品 id 来自真实结果，不是猜的。
    其余 ⇒ 臆断式检索：返回给模型的纠正话术（**发候选卡或追问**，不要默认搜）。
    """
    if tool_name not in SPECULATIVE_SEARCH_TOOLS:
        return ""
    texts = [str(t) for t in (user_texts or []) if str(t or "").strip()]
    executed = set(executed_tools or ())
    if tool_name == "product_detail" and "product_search" in executed:
        return ""
    if any(_text_is_substantive(t) for t in texts):
        return ""
    haystack = "".join(texts)
    if _has_grounded_term(args or {}, haystack):
        return ""

    filled = "、".join(
        f"{k}={str((args or {}).get(k))[:40]}" for k in _GROUNDABLE_ARG_KEYS
        if (args or {}).get(k)
    ) or "（无关键词）"
    return (
        "顾客这句话里**没有任何可直接检索的实质信息**，而你填的检索条件"
        f"（{filled}）是**你自己猜的** —— 顾客从没提过这些词。"
        "意图不明时**不要默认直接搜**（更不要先搜再补一张卡）："
        "① 用 `interact(component=choice)` 发一张候选卡"
        "（选项用顾客嘴里的说法，如「找窗帘 / 查订单 / 售后咨询」）；"
        "② 或者直接用一句口语追问顾客想看哪个方向。"
        "等顾客说出**商品名 / 品类 / 订单号**之后再检索。"
        "（本次调用已被拦下，未执行。）"
    )


# ── 异步守卫（含 SessionStateStore 读写，供 intent_router_node 调用）──

async def apply_clarify_guard(
    session_id: str,
    *,
    is_clarify_round: bool,
    route_decision: Any,
) -> Any:
    """澄清轮护栏入口：更新计数并决定是否改写路由为兜底话术。

    语义：
    - is_clarify_round=True（本轮被路由为低置信澄清/general 兜底）：
      读 clarify 状态 → 若已达上限（force_example）→ 返回改写后的
      RouteDecision（action=direct_reply，话术=CLARIFY_FORCE_EXAMPLE_TEXT）；
      否则 tick +1 并写回 → 返回原 route_decision（继续澄清）。
    - is_clarify_round=False（用户给出实质意图/澄清卡被点选）：
      tick 清零并写回 → 返回原 route_decision。

    存储失败按无状态降级（不阻断主流程，仅记录日志）。

    Args:
        session_id: 会话 ID
        is_clarify_round: 本轮是否仍处于澄清轮（low-confidence 重写 general）
        route_decision: 路由决策对象（有 action/direct_reply 属性）

    Returns:
        可能被改写（强制兜底）的 route_decision；无状态/失败时原样返回。
    """
    if not session_id:
        return route_decision

    try:
        from app.memory.session_state_store import SessionStateStore

        store = SessionStateStore()
        full_state = await store.load(session_id) or {}
        clarify_state = full_state.get(CLARIFY_STATE_KEY) or {}

        # 已达上限且本轮仍是澄清 → 强制兜底（不再追问）
        if is_clarify_round and should_force_example(clarify_state):
            logger.info(
                f"[clarify-guard] clarify round limit reached, force example "
                f"| session={session_id}"
            )
            # 保持上限状态（不清零，直到用户给出实质意图）
            return _rewrite_to_example(route_decision)

        # 更新计数并写回
        new_clarify = tick_clarify(clarify_state, was_clarify_round=is_clarify_round)
        full_state[CLARIFY_STATE_KEY] = new_clarify
        await store.commit(session_id, full_state)
        # 到达上限的"本轮"仍正常澄清（用户还有机会回答）；
        # 状态标记 force_example，下一轮仍澄清时由上方 should_force_example 分支兜底。
        return route_decision
    except Exception as e:
        logger.warning(f"[clarify-guard] guard failed (non-fatal): {e}")
        return route_decision


def _rewrite_to_example(route_decision: Any) -> Any:
    """把路由改写为 direct_reply 兜底话术（不改变原对象，返回新对象）。

    RouteDecision 是 dataclass：优先 dataclasses.replace（保持其它字段），
    非 dataclass（测试替身等）回退到同属性复制；结构异常时原样返回。

    改写结果附带 guard_forced=True 标记：route_by_intent 遇到该标记时，
    即使存在 pending_interact_skill（澄清卡/表单流程），也必须走兜底话术，
    不能再被 pending_skill 覆盖回 general skill（真实验收 #2801 发现）。
    """
    import dataclasses

    if dataclasses.is_dataclass(route_decision):
        new = dataclasses.replace(
            route_decision,
            action="direct_reply",
            direct_reply=CLARIFY_FORCE_EXAMPLE_TEXT,
            tool_hint=None,
        )
        new.guard_forced = True
        return new
    try:
        new = type(route_decision)()
        new.intent_result = route_decision.intent_result
        new.action = "direct_reply"
        new.direct_reply = CLARIFY_FORCE_EXAMPLE_TEXT
        new.tool_hint = None
        new.guard_forced = True
        return new
    except Exception:
        # 结构异常时兜底：原样返回（守卫宁可失效也不阻断）
        return route_decision
