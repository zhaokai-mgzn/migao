"""
小布 AI 主动引导转人工 — 判定模块（Guided Handoff Judge）

纯规则信号判定，不依赖 LLM（确定性、可单测），设计见
docs/design/xiaobu-ai-handoff-guidance.md §3。

三类触发（D1/D2 由调用方 intent_router_node 处理，本模块提供判定函数）：
- D1 用户显式请求转人工（"转人工/找人工…"）→ 直转（is_explicit_handoff_request）
- D3 AI 主动建议（judge_handoff）：
    S1 单轮负面情绪表达（仅 general 兜底意图，不打断明确业务流）
    S2 多轮未解决：最近 3 条用户消息 ≥2 条命中负面表达（售后/兜底反复）
    S3 能力外/超范围请求（赔偿/法律/起诉…）
  建议受冷却约束：每会话 offer_count >= 上限 或 用户已拒绝 → 不再 offer。

意图过滤（防打断业务流，核心）：
- 明确业务意图（下单/算料/查单/售后创建/greeting 等）→ 一律不 offer
- 仅 general（兜底）/ after_sales（售后沟通）允许 offer；
  after_sales 单轮负面不 offer（该走售后流程），多轮未解决（S2）才 offer。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# ────────────────────── D1 显式请求词 ──────────────────────
# 用户明确要求转人工的强信号。刻意不含裸"人工客服"（"人工客服几点上班"
# 是咨询不是请求），避免误直转。
_EXPLICIT_HANDOFF_WORDS = (
    "转人工", "转接人工", "找人工", "找真人", "真人客服",
    "我要人工", "人工帮我", "人工处理",
)

# ────────────────────── D3 信号词 ──────────────────────
# S1/S2 负面情绪表达（子串匹配）。不含"投诉/举报/不满/差评"——
# 这些已被 L1 rule_matcher 命中 complaint 意图走既有直转/投诉流程，
# 不该再走"建议转人工"卡片。
_NEGATIVE_EMOTION_WORDS = (
    "太差", "很差", "差劲", "气死", "很失望", "失望透顶",
    "再也不买", "不买了", "垃圾", "骗人", "敷衍", "没人管",
    "没人处理", "没人理", "态度差", "什么破", "太坑", "坑人",
    "烂透了", "不想再说", "说了很多次", "一直没解决", "反复说",
)

# S3 能力外/超范围请求：赔偿、法律维权等（AI 无权/无法处理，应转人工）
_OUT_OF_SCOPE_WORDS = (
    "赔偿", "赔钱", "起诉", "法院", "律师", "法律途径",
    "12315", "消协", "工商投诉", "媒体曝光",
)

# 允许 offer 的意图白名单：其余意图（下单/报价/售后创建等明确业务流）
# 一律不弹建议卡，防止打断正常业务推进。
#
# `complaint` 于 2026-09-11 纳入（CH-014 抖动治理，CI 实证 run 34622425044）：
# 旧注释的理由是「投诉/举报/不满/差评已被 L1 rule_matcher 命中 complaint 走既有直转/
# 投诉流程」—— 那是**B 端**语义（米宝收到投诉直接转人工）。C 端实测（小布）该轮
# 既没有直转、也没有弹卡，只有一句安抚文本，于是 CH-014 的 `interact` 期望
# 取决于分类器把「你们太坑了」分到 general / after_sales / complaint 中的哪一个
# → 同一用例两次 run 结果相反。判据统一为**消息里有没有可执行诉求**（见
# _ACTIONABLE_REQUEST_WORDS），与 after_sales 完全一致。
_OFFER_ALLOWED_INTENTS = {"general", "after_sales", "complaint"}

# ────────────────────── 可执行业务诉求（S1 例外判据） ──────────────────────
# 用途：`after_sales` 意图下判断「这条消息是不是有正事要办」。
# 设计本意（docs/design/xiaobu-ai-handoff-guidance.md §3.3）防的是**打断有正事
# 要办的业务流**，原文例子是"质量太差**我要退货**" —— 关键是「我要退货」这个
# 动作，而不是意图标签本身。故判据落在"消息里有没有可执行诉求"上。
#
# 为什么必须改（实测不可复现）：旧规则 S1 仅对 `general` 生效 → 同一用例
# （CH-013/CH-014）的成败取决于 LLM 把「你们太坑了，再也不买了」分成
# general 还是 after_sales（run 34612040268 ✅ / run 34613307565 ❌，
# 同代码同输入）→ 变成分类器抽奖，不符合企业级评测要求。
_ACTIONABLE_REQUEST_WORDS = (
    # 售后动作
    "退货", "退钱", "退款", "换货", "换新", "维修", "补发", "重新发", "返修",
    # 下单/交易动作
    "下单", "购买", "我要买", "帮我买", "算料", "报价", "多少钱",
    # 查单/物流动作
    "查订单", "我的订单", "订单号", "查物流", "物流", "快递", "发货",
    # 票据
    "开发票", "发票",
)

# 每会话自动建议次数上限（冷却：达上限后不再弹卡）
DEFAULT_HANDOFF_MAX_OFFERS = 1

# S2 判定窗口：最近 N 条用户消息
_S2_WINDOW = 3
_S2_MIN_NEGATIVE = 2


@dataclass
class HandoffJudgeResult:
    """judge_handoff 判定结果"""
    action: str          # "offer" | "none"
    signal: str = ""     # "S1" / "S2" / "S3"
    reason: str = ""


def is_explicit_handoff_request(message: Optional[str]) -> bool:
    """判断用户消息是否为显式转人工请求（D1，直转语义）。

    供 intent_router_node 在商家 autoHandoffKeywords 检查之后调用：
    命中 → complaint 意图直转（不经建议卡片）。
    """
    if not message:
        return False
    text = str(message).strip()
    if not text:
        return False
    return any(kw in text for kw in _EXPLICIT_HANDOFF_WORDS)


def _hit_negative(text: str) -> bool:
    return any(kw in text for kw in _NEGATIVE_EMOTION_WORDS)


def _hit_out_of_scope(text: str) -> bool:
    return any(kw in text for kw in _OUT_OF_SCOPE_WORDS)


def _hit_actionable_request(text: str) -> bool:
    """消息是否含**可执行业务诉求**（有正事要办）。

    用于 S1 在 `after_sales` 意图下的例外判定：有诉求 → 继续走业务流不打断；
    纯情绪发泄 → 建议转人工（用户此刻最需要的是人，不是流程）。
    """
    return any(kw in text for kw in _ACTIONABLE_REQUEST_WORDS)


def _cooldown_blocked(handoff_state: Optional[dict]) -> bool:
    """冷却检查：已建议满次数或用户已拒绝 → 不再自动建议。"""
    if not handoff_state:
        return False
    offer_count = handoff_state.get("offer_count") or 0
    if offer_count >= DEFAULT_HANDOFF_MAX_OFFERS:
        return True
    if handoff_state.get("last_user_refused"):
        return True
    return False


def has_escalation_signal(message: Optional[str]) -> bool:
    """消息是否带「应当转人工」的信号（显式请求 / 负面情绪 / 能力外诉求）。

    供**代码层兜底**复用，避免各处重复拼词表判断（本模块是这些词表的单一事实源）：
    - D1 显式请求：`is_explicit_handoff_request`
    - S1/S2 负面情绪词表：`_hit_negative`
    - S3 能力外/超范围：`_hit_out_of_scope`

    用途：C 端在办流程中**误转人工**时，代码需要判断「这次转人工是不是用户真的要的」——
    三个信号全无 → 是模型自行放弃流程，应当阻止（见 base_skill 的 human_handoff 兜底）。
    """
    text = str(message or "").strip()
    if not text:
        return False
    return (
        is_explicit_handoff_request(text)
        or _hit_negative(text)
        or _hit_out_of_scope(text)
    )


def judge_handoff(
    message: str,
    intent: str = "",
    recent_user_messages: Optional[List[str]] = None,
    handoff_state: Optional[dict] = None,
) -> HandoffJudgeResult:
    """判定本轮是否需要主动建议转人工（D3）。

    Args:
        message: 当前用户消息文本
        intent: 当轮意图（"general"/"after_sales"/"order_create"...）
        recent_user_messages: 本条之前的最近用户消息（S2 多轮信号用）
        handoff_state: 会话 handoff 状态（{"offer_count": int, "last_user_refused": bool}）

    Returns:
        HandoffJudgeResult(action="offer"|"none", signal, reason)
    """
    if not message or not str(message).strip():
        return HandoffJudgeResult(action="none", reason="空消息")

    text = str(message).strip()

    # 0. 冷却：达上限 / 用户已拒绝 → 不再建议（防骚扰，最高优先级）
    if _cooldown_blocked(handoff_state):
        return HandoffJudgeResult(
            action="none",
            reason=f"冷却中: offer_count={handoff_state.get('offer_count')} "
                   f"refused={handoff_state.get('last_user_refused')}",
        )

    # 1. D1 显式转人工请求由调用方直转；judge 内兜底不 offer（防双路径冲突）
    if is_explicit_handoff_request(text):
        return HandoffJudgeResult(action="none", reason="D1 显式请求走直转")

    # 2. 意图白名单：仅 general / after_sales 可 offer，防打断业务流
    if intent not in _OFFER_ALLOWED_INTENTS:
        return HandoffJudgeResult(
            action="none",
            reason=f"意图 {intent or '(空)'} 不在 offer 白名单",
        )

    # 3. S3 能力外/超范围（赔偿/法律/维权）→ offer
    if _hit_out_of_scope(text):
        return HandoffJudgeResult(
            action="offer", signal="S3",
            reason="能力外/超范围请求（赔偿/法律等）",
        )

    # 4. S1 单轮负面情绪
    #    - general（兜底/未知意图）：负面即 offer。
    #    - after_sales：仅当消息**没有可执行业务诉求**时 offer。
    #      设计本意是「不打断有正事要办的售后流程」（如"质量太差我要退货"），
    #      而不是「售后意图一律不 offer」—— 后者会让纯情绪发泄的处置取决于
    #      分类器把消息分到 general 还是 after_sales，用例成败成为抽奖
    #      （CH-013/CH-014 实测两次 run 结果相反，见 _ACTIONABLE_REQUEST_WORDS 注释）。
    if _hit_negative(text):
        if intent == "general":
            return HandoffJudgeResult(
                action="offer", signal="S1", reason="单轮负面情绪表达(general)"
            )
        if intent in ("after_sales", "complaint") and not _hit_actionable_request(text):
            return HandoffJudgeResult(
                action="offer", signal="S1",
                reason=f"单轮负面情绪表达({intent} 且无可执行业务诉求，不打断业务流)",
            )

    # 5. S2 多轮未解决：最近窗口内 ≥2 条负面表达（本条中性也可触发）
    if recent_user_messages:
        recent = [str(m) for m in recent_user_messages[-_S2_WINDOW:] if m]
        negative_hits = sum(1 for m in recent if _hit_negative(m))
        if negative_hits >= _S2_MIN_NEGATIVE:
            return HandoffJudgeResult(
                action="offer", signal="S2",
                reason=f"多轮未解决: 近{_S2_WINDOW}条中 {negative_hits} 条负面表达",
            )

    return HandoffJudgeResult(action="none", reason="无信号")
