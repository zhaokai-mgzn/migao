"""
辅助节点函数

包含 StateGraph 中除 Skill 节点以外的辅助节点：
- intent_router_node: 意图路由
- direct_reply_node: 直接回复（greeting 等）
- route_by_intent: 意图→Skill 路由
- _get_last_human_text: 提取最后一条用户消息文本
"""

import asyncio
from typing import Union

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from app.graph.handoff_judge import is_explicit_handoff_request
from app.graph.state import AgentState


# ── 业务领域关键词（单一来源）──
# 用于 route_by_intent 的 escape hatch（topic switch）与
# plan_rewrite 路径的澄清轮护栏判定：短消息是否包含实质业务意图。
_SKILL_DOMAIN_KEYWORDS = {
    # 「下单」必须在内（issue #3361）：C 端报价 skill（customer_quote）会下发报价卡并
    # 锁住 pending_interact_skill，而它**没有** order_create 工具。顾客在报价后说
    # 「确认下单/我要下单」时，若这些词不算 order 域信号，escape hatch 不触发 →
    # 会话被锁在报价 skill → 模型照样调 order_create → `tool_not_found` ×2 → 转人工，
    # 订单从未创建（CI run 34686905546 实证：OR-017 R7/R8）。含「下单」即命中
    # L1 规则 ORDER_CREATE（rule_matcher），路由回 customer_order skill 完成下单。
    # 「加工单」（issue #3921，PG-017）：会话锁在订单域时用户提加工单是**域内话题**
    # （加工单=订单履约子进度），不判话题切换逃逸到商品域（商品域会把它当加工项查）。
    "order": {"查订单", "物流", "发货", "订单", "下单", "加工单"},
    # 「退」单独入表（issue #3361）：C 端口语里"我要退上次买的那单"不含"退货"三字，
    # 但语义百分百是售后 —— 漏掉它导致流程被甩去 order 域（见下方「本领域信号优先」注释）。
    "aftersales": {"售后", "退货", "退款", "换货", "投诉", "退"},
    "product": {
        "查商品", "搜商品", "创建商品", "商品管理",
        # 商品**动作**词（#3557 G3/T2）：原表只有管理端**查询**口径，一个动作词都没有
        # → 会话锁在非商品域时「再把它上架」「把遮光窗帘下架」逃不出去 → 被困在
        # order/aftersales（其工具集没有 `product_manage`）→ 模型以「模块越界」口径拒绝。
        # 只收**商品专属动作**：这两个词在下单/报价/售后话术里不出现（对照
        # `_SKILL_DOMAIN_PATTERNS` 的注释——裸名词会坏事，动词不会）。
        # 「价格」「库存」**故意不收**：C 端「这个价格帮我下单」「库存还有吗」高频
        # → 入表会让 customer_quote/customer_order 的会话锁被误逃逸；那两条走
        # `route_by_intent` 的 L1 高置信放行（见 `_rule_intent_domain`）。
        "上架", "下架",
    },
    "customer": {"客户", "会员"},
    "staff": {"员工", "角色", "权限"},
    "settings": {"设置", "配置", "通知", "快捷回复"},
}


# ── 业务领域**句式**信号（正则，issue #3364）──
# 为什么需要：`_SKILL_DOMAIN_KEYWORDS` 是**管理端说法**（查商品/搜商品/创建商品/商品管理），
# C 端口语「有什么遮光窗帘推荐」「看看这款面料」一个都不命中 → escape hatch 不触发 →
# 会话被上一张卡锁在原技能（E2E `test_topic_switch_does_not_leak_order_context` 实测红：
# 查完订单接着问商品，round2 一个商品工具都调不出来）。
# 为什么用**句式**而不是再加"窗帘/面料"裸词：裸词会让下单流程里的「遮光窗帘 3 米，要打孔加工」
# 被判成"切到商品域"，把下单流程甩走（OR-014/OR-017 依赖留在 customer_order）。
# 句式（询问/求推荐）与指令（下单/买）在语义上天然可分，故此处只收询问型。
_SKILL_DOMAIN_PATTERNS = {
    "product": (
        r"(?:推荐|看看|看一下|有什么|有没有|想看看).{0,8}(?:窗帘|窗纱|面料|布艺)",
        r"(?:窗帘|窗纱|面料|布艺).{0,6}(?:推荐|有哪些|有什么|怎么选|哪种好)",
    ),
}


# ── Skill → 意图（短消息快捷路由 / 答卡轮保持本 skill 意图，#3557）──
_SKILL_TO_INTENT = {
    "product": "product_inquiry",
    "customer_product": "product_inquiry",
    "order": "order_query",
    "customer_order": "order_query",
    "aftersales": "after_sales",
    "customer_aftersales": "after_sales",
    "customer": "customer_query",
    "staff": "employee_manage",
    "settings": "system_settings",
    "data": "dashboard",
    "general": "general",
    "customer_general": "general",
    "customer_knowledge": "general",
    "customer_quote": "quote",
}


def _msg_matches_domain_pattern(text: str, domain: str) -> bool:
    """消息是否命中该领域的**句式**信号（正则表，见上）。"""
    import re as _re
    if not text:
        return False
    return any(_re.search(pat, str(text)) for pat in _SKILL_DOMAIN_PATTERNS.get(domain, ()))


def _skill_keyword_domain(skill_name: str) -> str:
    """Skill 名 → 关键词域（C 端 skill 带 `customer_` 前缀：customer_order → order）。

    为什么需要（issue #3361 实证）：`_SKILL_DOMAIN_KEYWORDS` 的键是**领域**
    （order/aftersales/product/…），而 C 端 skill 名是 `customer_order` / `customer_quote`。
    escape hatch 里 `if skill_domain == pending_skill` 于是对 C 端**永不成立** ——
    连当前 skill 自己的领域都被当成"其他领域"，只要用户消息里出现本领域关键词就误判为
    话题切换、释放会话锁，会话被甩给 intent 路由。

    实测后果（CI run 34688038261）：在 `customer_order` 里顾客点确认卡回传
    「确认下单：遮光窗帘3米+打孔加工，合计¥95.4」→ 因含「下单」被判"切到 order 域"
    → pending 清空 → intent 分类为 quote → 路由到 `customer_quote`（该 skill 无
    order_create）→ `Tool not found: order_create` → 订单永不创建、最终转人工。
    """
    name = str(skill_name or "")
    prefix = "customer_"
    return name[len(prefix):] if name.startswith(prefix) else name


def _msg_has_domain_keyword(text: str) -> bool:
    """消息是否包含任何业务领域关键词（用户给出实质意图方向）。"""
    if not text:
        return False
    if any(
        kw in text
        for kws in _SKILL_DOMAIN_KEYWORDS.values()
        for kw in kws
    ):
        return True
    # 句式信号同源（issue #3364）：「有什么窗帘推荐」是实质诉求，不该被当澄清轮
    return any(_msg_matches_domain_pattern(text, d) for d in _SKILL_DOMAIN_PATTERNS)


# ── 确认卡「答卡轮」（#3557 G1）──
# 答卡轮 = 本轮用户输入**逐字等于本会话最近一张确认卡的 confirmValue**
# （`base_skill.py` 的 `_is_card_confirm_value` 同源语义：该值由系统自产并展示，
# 用户不可能"碰巧"逐字相等 → 只可能来自点击卡片）。
_CARD_CONFIRM_INTENT_SOURCE = "card_confirm"


def _is_card_confirm_round(state: dict) -> bool:
    """本轮是否是「点卡确认」轮：输入逐字等于**本 skill 自己那张卡**的 confirmValue。

    为什么**必须**带上 `last_confirm_skill == pending_interact_skill`（issue #3557 vs #3361）：
    - #3557（本判据要治的）：商品上下架卡的 `confirmValue` 里那句「（改为停售，**买家不可下单**）」
      含跨域词「下单」→ L1 规则表判 `order_create` → escape hatch 清锁 → 进 `order` skill
      （无 `product_manage`）→ 零工具调用 + 「订单模块」口径拒绝（run 34808115143，PR-007 50%）。
    - #3361（**不许**踩的契约）：`pending=customer_quote` + 顾客**另起一句**
      「确认下单/我要下单/帮我下单」**必须**切到 `customer_order`（报价 skill 没有
      order_create，不切就"报价后下不了单"）。
    两者的判别式**不是**"答卡轮一律不切域"（那会踩 #3361），而是"**本轮输入是否逐字等于
    本 skill 自己那张卡的 confirmValue**"：#3361 的输入是顾客新写的一句话，
    与报价卡的 confirmValue 不相等 → 照旧放行切换。
    """
    pending = str(state.get("pending_interact_skill") or "")
    card_skill = str(state.get("last_confirm_skill") or "")
    card_value = str(state.get("last_confirm_value") or "")
    if not (pending and card_skill == pending and card_value):
        return False
    msg = (_get_last_human_text(state.get("messages", []) or []) or "").strip()
    return bool(msg) and msg == card_value.strip()


# ── 交互卡「答卡轮」（#3557 G1 家族扩展：choice / form 卡同样在射程内）──
# #3677 的 `_is_card_confirm_round` 只覆盖 **confirm** 卡：`last_confirm_value` /
# `last_confirm_skill` 仅在 `interact` 发 confirm 卡时落库（base_skill 的 interact
# 成功分支）。**choice / form 卡的答卡轮因此完全不在豁免射程内** —— 实测代价
# （run 34841029062，OR-015 R4）：
#   R3 order skill 发 `interact(choice, multiSelect, prefix=已选加工项：)` 加工项卡
#   R4 顾客答卡「已选加工项：纳米圈打孔 · ¥9.5/米」→ 含 L1 商品域关键词「加工项」
#      （rule_matcher.py:41）→ intent=product_inquiry(source=rule)
#      → 下方 L1 高置信域逃逸（#3625 G3/T2）判 product ≠ order → **清掉 order 会话锁**
#      → 落到 product skill（PRODUCT_TOOLS 无 order_create）→ 零工具 + 「我承接的是
#        商品侧的工作」（R5「确认」沿用被污染的锁，同签名）。
# 判据与 #3557 / #3361 一致：**本轮输入是否被"本 skill 自己刚发的那张卡"接受**，
# 而不是"有没有卡"——报价卡后顾客另起一句「确认下单」不在这张卡的取值集合里，
# 照旧放行切换（#3361 不回归）。
def _card_accepts_answer(card: dict, msg: str) -> bool:
    """本轮消息是否是**这张卡**接受的答复（对齐前端点击协议，单一事实源
    `frontend/admin-web/src/components/chat/InteractiveMessage.tsx`）：

    - `confirm` → 逐字等于 `confirmValue`（点击回传的就是这个值）；
    - `choice`  → 逐字等于某个 option 的 `label`/`value`，或逐字等于多选卡的
      `multiSelectSkipLabel`（「不需要加工项」）；多选提交 = `multiSelectSubmitPrefix`
      前缀（「已选加工项：A、B」）；
    - `form`    → `__FORM__|{json}`（`app/api/chat.py` 的表单提交协议）。
    """
    if not msg or not isinstance(card, dict):
        return False
    component = str(card.get("component") or "")
    if component == "confirm":
        value = str(card.get("confirmValue") or "").strip()
        return bool(value) and msg == value
    if component == "choice":
        accepted = set()
        for opt in (card.get("options") or []):
            if isinstance(opt, dict):
                accepted.update(str(opt.get(k) or "").strip() for k in ("label", "value"))
            else:
                accepted.add(str(opt).strip())
        accepted.discard("")
        accepted.add(str(card.get("multiSelectSkipLabel") or "").strip())
        if msg in accepted:
            return True
        if card.get("multiSelect"):
            prefix = str(card.get("multiSelectSubmitPrefix") or "已选加工项：")
            return bool(prefix) and msg.startswith(prefix)
        return False
    if component == "form":
        return msg.startswith("__FORM__|")
    return False


def _is_card_answer_round(state: dict) -> bool:
    """本轮是否是答卡轮（**任意卡型**）：输入被**本 skill 自己刚发的卡**接受。

    `last_card` / `last_card_skill` 由 base_skill 在 `interact` 发卡成功时落库
    （任意 component），`_build_initial_state` 恢复 —— 判据与 confirm 卡版本同源：
    卡是系统自己产出的，用户不可能"碰巧"逐字命中它的取值集合。
    """
    pending = str(state.get("pending_interact_skill") or "")
    card_skill = str(state.get("last_card_skill") or "")
    card = state.get("last_card") or {}
    if not (pending and card_skill == pending and card):
        return False
    msg = (_get_last_human_text(state.get("messages", []) or []) or "").strip()
    return _card_accepts_answer(card, msg)


def _is_own_card_round(state: dict) -> bool:
    """答卡轮总判据：confirm 卡走 `last_confirm_*`（#3677 原判据，不改），
    其余卡型走 `last_card`（choice / form，#3557 家族扩展）。"""
    return _is_card_confirm_round(state) or _is_card_answer_round(state)


# 已知领域：`_SKILL_DOMAIN_KEYWORDS` 的键 + knowledge（无关键词表但有独立 skill）
_KNOWN_DOMAINS = frozenset(_SKILL_DOMAIN_KEYWORDS) | {"knowledge"}


def _route_key_domain(route_key: str) -> str:
    """路由 key → 领域（无法判定时返回 ""）。

    `_get_intent_to_route`（生产，`skill_registry`）给的是**域 key**（`product`/`order`），
    而测试里的映射表与 builder 的 `skill_route_map` 用的是**节点 id**（`product_skill`）。
    两种命名都要能识别，否则 escape hatch 的域比较在测试/生产之间不一致。
    """
    key = str(route_key or "")
    if not key or key in ("general", "direct_reply"):
        return ""
    if key in _KNOWN_DOMAINS:
        return key
    base = key[:-len("_skill")] if key.endswith("_skill") else ""
    if base in _KNOWN_DOMAINS:
        return base
    if base.startswith("customer_"):
        base = base[len("customer_"):]
    return base if base in _KNOWN_DOMAINS else ""


def _rule_intent_domain(intent: str, agent_type: str) -> str:
    """L1 规则命中的 intent 对应的 skill 域（无法路由到具体域时返回 ""）。

    用于 escape hatch：**尊重 L1 已算出的高置信判定**，而不是只认关键词表。
    """
    return _route_key_domain(_intent_to_route_key(intent, agent_type))


def _intent_to_route_key(intent: str, agent_type: str) -> str:
    """intent → 路由 key（懒加载按 agent_type 分桶的映射表）。"""
    global _INTENT_TO_ROUTE
    _key = agent_type or ""
    if _key not in _INTENT_TO_ROUTE:
        _INTENT_TO_ROUTE[_key] = _get_intent_to_route(agent_type)
    return _INTENT_TO_ROUTE[_key].get(intent, "general")


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


# ────────────────────── 跨轮实体提示 ──────────────────────

_ENTITY_LABELS = {
    "product_ids": "商品",
    "order_nos": "订单",
    "customer_ids": "客户",
    "processing_item_ids": "加工项",
}


async def _build_entity_hint(session_id: str) -> str:
    """从 context_manager 读跨轮实体，构建给意图分类器的指代提示。

    让分类器在判断"那个订单/这个商品"时知道具体指代对象，减少误分类。
    最多取每类前 2 个，控制长度。
    """
    if not session_id:
        return ""
    try:
        from app.memory.context_manager import get_context_manager
        ctx_mgr = get_context_manager()
        await ctx_mgr.load(session_id)
        entities = ctx_mgr.get_entities(session_id)
    except Exception as e:
        logger.debug(f"[entity-hint] load failed: {e}")
        return ""
    parts = []
    for etype, items in entities.items():
        if not isinstance(items, list):
            continue
        for item in items[:2]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("order_no") or item.get("no") or ""
            eid = (item.get("no") or item.get("id") or "")[:20]
            parts.append(f"{_ENTITY_LABELS.get(etype, etype)}「{name}」({eid})")
    if not parts:
        return ""
    return "[上下文实体] 之前对话已涉及：" + "、".join(parts)


# ────────────────────── 辅助节点 ──────────────────────


async def intent_router_node(state: AgentState) -> dict:
    """执行意图路由

    pending_skill 存在时：
    - 短消息（≤5 字，如"查啊""确认""1"）：跳过 LLM，直接路由到 pending skill
    - 长消息：仍走 LLM 分类，让 LLM 有机会检测 topic switch
    防止用户被锁死在单一 skill 中无法退出。

    AI 主动引导转人工（xiaobu，见 handoff_judge.py / handoff_offer.py）：
    - D1 用户显式转人工请求（"转人工/找人工…"）→ 短路直转 complaint
      （优先于 pending_skill / LLM 分类，任何流程中用户要求转人工都应直转）
    - D3 结构化信号（负面情绪/多轮未解决/能力外）命中且意图白名单内 →
      route_decision.action="handoff_offer"（建议卡片），由 route_by_intent 路由。
    """
    agent_type = state.get("agent_type", "xiaobu")
    session_id = state.get("session_id", "")
    tenant_id = state.get("tenant_id")

    # ── D1 显式转人工请求 → 短路直转 complaint（不弹建议卡、不调 LLM）──
    if agent_type == "xiaobu":
        last_msg = _get_last_human_text(state.get("messages", [])) or ""
        if is_explicit_handoff_request(last_msg):
            logger.info(
                f"[intent_router] 显式转人工请求 → complaint 直转 "
                f"| tenant={tenant_id} session={session_id}"
            )
            return {
                "intent_result": {
                    "intent": "complaint",
                    "confidence": 0.99,
                    "source": "explicit_handoff",
                },
                "route_decision": {"action": "full_agent"},
            }

    pending_skill = state.get("pending_interact_skill", "")
    if pending_skill:
        # 检查最后一条用户消息长度
        # 注意：必须经 _get_last_human_text 提取纯文本——图片消息的 content 是
        # 多模态 list（text + image_url 块），直接对 raw content 调 .strip() 会抛
        # AttributeError（线上 sess_* 会话真实报错 "'list' object has no attribute 'strip'"）。
        messages = state.get("messages", [])
        last_user_msg = _get_last_human_text(messages) or ""
        msg_len = len(last_user_msg.strip()) if last_user_msg else 0

        # ── 答卡轮豁免（#3557 G1，**必须最先判**）──
        # 点卡确认轮不重判意图：卡值里可能含跨域词（PR-007 的「买家不可下单」含「下单」），
        # 走 L1 规则表会被判成 `order_create` → 路由到 order skill（无 product_manage）
        # → 零工具调用 + 「订单模块」口径拒绝（CI run 34808115143，PR-007 50%）。
        # 放最前面：本轮的实质意图就是"确认刚才那张卡"，无需（也不该）重新分类；
        # 判据与 #3361 的契约不冲突（那个场景的输入不是本 skill 卡的 confirmValue），
        # 见 `_is_card_confirm_round` / `_is_card_answer_round` 的完整说明。
        # 卡型覆盖：confirm（#3677）+ choice / form（run 34841029062 OR-015 R4 实证）。
        if _is_own_card_round(state):
            synthetic_intent = _SKILL_TO_INTENT.get(pending_skill, "general")
            logger.info(
                f"[intent_router] 答卡轮：保持本 skill 意图（不重判）"
                f" | pending_skill={pending_skill} → intent={synthetic_intent}"
                f" | session={session_id}"
            )
            return {
                "intent_result": {
                    "intent": synthetic_intent,
                    "confidence": 0.99,
                    "source": _CARD_CONFIRM_INTENT_SOURCE,
                },
                "route_decision": {"action": "full_agent"},
            }

        # 短消息：沿用 pending_skill 快捷路由（节省 LLM 调用，防止误分类）
        if msg_len <= 5:
            synthetic_intent = _SKILL_TO_INTENT.get(pending_skill, "general")
            logger.info(
                f"[intent_router] Intent rewrite (short msg): pending_skill={pending_skill}"
                f" → intent={synthetic_intent} | msg_len={msg_len} | session={session_id}"
            )

            # ── 澄清轮护栏（issue #2796）：plan_rewrite 路径同样计数 ──
            # 缺陷（真实验收 #2801 发现）：澄清卡下发后 pending_skill 已设置，
            # 后续模糊轮（如"就是那个""你懂的"）走 plan_rewrite 提前 return，
            # 完全绕过下方护栏挂点（其条件含 not pending_skill）→ 兜底永不触发。
            # 修复：仅当 pending_skill 是澄清流程（general / customer_general，
            # 澄清卡由对应兜底 skill 下发）且短消息不含任何业务领域关键词
            # （仍无实质意图）→ 计澄清轮；表单/业务流程（product/order 等的
            # "确认"）属实质交互 → 清零。已达上限 → 强制返回兜底话术。
            if session_id:
                try:
                    from app.graph.clarify_guard import apply_clarify_guard
                    from app.router.intent_config import RouteDecision

                    is_clarify_round = (
                        pending_skill in ("general", "customer_general")
                        and not _msg_has_domain_keyword(last_user_msg)
                    )
                    # 构造护栏兼容的 route_decision（仅需 action/direct_reply 属性）
                    guard_decision = RouteDecision(
                        intent_result=type(
                            "IR",
                            (),
                            {"intent": synthetic_intent, "confidence": 0.99, "source": "plan_rewrite"},
                        )(),
                        action="full_agent",
                    )
                    guarded = await apply_clarify_guard(
                        session_id,
                        is_clarify_round=is_clarify_round,
                        route_decision=guard_decision,
                    )
                    if guarded.action == "direct_reply":
                        logger.info(
                            f"[intent_router] Clarify guard force example (plan_rewrite path)"
                            f" | session={session_id}"
                        )
                        return {
                            "intent_result": {
                                "intent": synthetic_intent,
                                "confidence": 0.99,
                                "source": "plan_rewrite",
                            },
                            "route_decision": {
                                "action": "direct_reply",
                                "direct_reply": guarded.direct_reply,
                                "tool_hint": None,
                                "guard_forced": True,
                            },
                        }
                except Exception as e:
                    logger.warning(
                        f"[intent_router] Clarify guard (plan_rewrite) failed (non-fatal): {e}"
                    )

            # ── L1 规则优先（issue #3476，C-A1 P1 实证）──
            # `_SKILL_TO_INTENT` 的键是**域**名，C 端 pending 值（customer_product 等）
            # 已在上方补齐；但即使补齐，"确认下单"在 customer_product 锁里合成出来的是
            # product_inquiry —— 那会让 escape 命中 order 域关键词却路由回商品技能，
            # 模型依然没有 order_create 可用。短消息里带**领域信号**（交易动词/查单/
            # 退换货…）时必须按 L1 的高置信结果走（"确认下单"→ order_create 0.98）。
            # 放澄清护栏**之后**：护栏判"模糊轮"优先给兜底示例；领域信号轮不算模糊。
            from app.router.rule_matcher import RuleMatcher
            _l1 = RuleMatcher().match(last_user_msg)
            if _l1 and _l1.intent.value not in ("general", "greeting", "farewell",
                                                "capabilities"):
                return {
                    "intent_result": {
                        "intent": _l1.intent.value,
                        "confidence": getattr(_l1, "confidence", 0.99),
                        "source": "rule_short",
                    },
                    "route_decision": {"action": "full_agent"},
                }
            return {
                "intent_result": {
                    "intent": synthetic_intent,
                    "confidence": 0.99,
                    "source": "plan_rewrite",
                },
                "route_decision": {"action": "full_agent"},
            }

        # 长消息：走 LLM 分类，允许 topic switch
        logger.info(
            f"[intent_router] Long msg with pending_skill, running LLM classification"
            f" | pending_skill={pending_skill} msg_len={msg_len} session={session_id}"
        )
        # 继续走下面的 LLM 分类流程

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

    # 商家配置的自动转人工关键词：命中则直接转人工（complaint 意图 → human_handoff）
    # 仅小布（C 端）生效；商家后台「机器人设置」配置 autoHandoffKeywords。
    tenant_id = state.get("tenant_id")
    if agent_type == "xiaobu" and tenant_id and user_message:
        try:
            from app.agents.tenant_config import (
                get_tenant_ai_config,
                is_auto_handoff_trigger,
            )
            ai_config = await get_tenant_ai_config(int(tenant_id))
            if is_auto_handoff_trigger(user_message, ai_config):
                logger.info(
                    f"[intent_router] 命中商家转人工关键词 → complaint "
                    f"| tenant={tenant_id} session={session_id}"
                )
                return {
                    "intent_result": {
                        "intent": "complaint",
                        "confidence": 0.99,
                        "source": "tenant_auto_handoff",
                    },
                    "route_decision": {"action": "full_agent"},
                }
        except Exception as e:
            logger.warning(
                f"[intent_router] 自动转人工关键词检查失败（非致命）: {e}"
            )

    # 注入跨轮实体：让分类器指代消解（"那个订单"→ORD12345），减少误分类。
    # entity_hint 作为独立参数传给 router，仅注入 L2 分类器；
    # L1 规则匹配只看原始用户消息（防止 hint 中的领域词污染关键词匹配）。
    entity_hint = await _build_entity_hint(session_id)

    route_decision = await router.route(
        user_message, chat_history, agent_intents=agent_intents, entity_hint=entity_hint
    )

    session_id = state.get("session_id", "")
    logger.info(
        f"[intent_router] LLM classified | intent={route_decision.intent_result.intent.value}"
        f" confidence={route_decision.intent_result.confidence:.2f}"
        f" action={route_decision.action}"
        f" | session={session_id}"
    )

    # ── 澄清轮次护栏（issue #2796）──
    # 路由到 general（兜底澄清 skill）即澄清轮：连续 ≥N 轮仍无实质意图 →
    # 强制给具体示例兜底话术（防低学历用户被无限追问），而非继续追问。
    # 注意：不以 source=="low_confidence" 为唯一判定——classifier 直接判 general
    # （GENERAL 在低置信重写豁免清单内）同样是"AI 听不明白要澄清"的信号
    # （真实验收 #2801 发现：R1"帮我看看"confidence=0.30 source=classifier 未被计数）。
    if (
        session_id
        and route_decision.action in ("full_agent", "route_with_hint")
        and not pending_skill
    ):
        try:
            from app.graph.clarify_guard import apply_clarify_guard

            is_clarify_round = (
                route_decision.intent_result.intent.value == "general"
            )
            guarded = await apply_clarify_guard(
                session_id,
                is_clarify_round=is_clarify_round,
                route_decision=route_decision,
            )
            if guarded is not route_decision:
                logger.info(
                    f"[intent_router] Clarify guard rewrote to example fallback"
                    f" | session={session_id}"
                )
                route_decision = guarded
        except Exception as e:
            logger.warning(f"[intent_router] clarify guard failed (non-fatal): {e}")

    # ── D3 AI 主动引导转人工（结构化信号，xiaobu C 端）──
    # 商家关键词（上）与显式请求（函数头）已直转；此处只处理"用户未明说但
    # 信号提示该建议转人工"：general/after_sales 意图 + 负面情绪/多轮未解决/
    # 能力外信号 → route 到 handoff_offer（建议卡片，用户确认后才真正转）。
    # pending_skill 存在（用户在表单流程中）时不做 offer，防打断。
    if (
        agent_type == "xiaobu"
        and not pending_skill
        and route_decision.action in ("full_agent", "route_with_hint")
    ):
        try:
            from app.graph.handoff_judge import judge_handoff
            from app.memory.session_state_store import SessionStateStore

            intent_value = route_decision.intent_result.intent.value
            # recent_user_messages：本条之前的最近用户消息（S2 多轮信号）
            recent_user_msgs = [
                m.get("content", "")
                for m in chat_history
                if isinstance(m, dict) and m.get("role") == "user"
            ]
            # 会话冷却状态（读取失败按无状态降级，不弹卡也不影响主流程）
            handoff_state = {}
            try:
                store = SessionStateStore()
                full_state = await store.load(session_id) or {}
                handoff_state = full_state.get("handoff") or {}
            except Exception as e:
                logger.debug(f"[intent_router] handoff state load failed (non-fatal): {e}")

            verdict = judge_handoff(
                user_message,
                intent=intent_value,
                recent_user_messages=recent_user_msgs,
                handoff_state=handoff_state,
            )
            if verdict.action == "offer":
                logger.info(
                    f"[intent_router] D3 handoff offer | signal={verdict.signal} "
                    f"reason={verdict.reason} | tenant={tenant_id} session={session_id}"
                )
                return {
                    "intent_result": {
                        "intent": intent_value,
                        "confidence": route_decision.intent_result.confidence,
                        "source": route_decision.intent_result.source,
                        "signal": verdict.signal,
                    },
                    "route_decision": {
                        "action": "handoff_offer",
                        "direct_reply": None,
                        "tool_hint": None,
                    },
                }
        except Exception as e:
            logger.warning(f"[intent_router] handoff offer judge failed (non-fatal): {e}")

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
            # 澄清护栏强制兜底标记：route_by_intent 遇到时不可被 pending_skill 覆盖
            "guard_forced": bool(getattr(route_decision, "guard_forced", False)),
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


# ────────────────────── 条件边路由函数（同步）──────────────────────


# 特殊意图 → direct_reply（不属于任何 skill，直接回复）
_DIRECT_REPLY_INTENTS = {"greeting", "farewell", "capabilities"}

# RAG 禁用期间知识库意图 fallback 到 general（仅 mibao，其 knowledge skill 已禁用）
_KNOWLEDGE_FALLBACK = {"knowledge_manage": "general"}  # 仅管理意图 fallback（知识管理走 admin-web，不经 agent）


def _get_intent_to_route(agent_type: str = "") -> dict[str, str]:
    """意图→路由key映射。从 skill_registry 动态构建,避免硬编码不同步。

    按 agent_type 对齐 persona：xiaobu 的 C 端专属 skill（如 customer_quote 的
    quote 意图）只有 xiaobu persona，若用默认 mibao persona 构建会被过滤，
    导致 quote 意图 fallback 到 general。故按 agent_type 传对应 persona。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    persona = "xiaobu" if agent_type == "xiaobu" else "mibao"
    intent_map = get_skill_registry().get_intent_to_route_map(persona=persona)
    for intent in _DIRECT_REPLY_INTENTS:
        intent_map[intent] = "direct_reply"
    intent_map["general"] = "general"
    # 米宝已启用 knowledge skill（issue #3059）：knowledge_faq 走知识卡片检索；
    # 仅 knowledge_manage 管理意图 fallback 到 general（知识管理走 admin-web，不经 agent）
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

    # AI 主动引导转人工（D3）：路由到 handoff_offer 节点（建议卡片）
    if action == "handoff_offer":
        logger.info(
            f"[route_by_intent] Routing to handoff_offer (AI guided handoff)"
            f" | tenant={state.get('tenant_id')} session={session_id}"
        )
        return "handoff_offer"

    if action == "direct_reply":
        # 多模态输入不走直复节点——直接回复模板没有图片处理能力
        if _last_human_has_image(state.get("messages", [])):
            logger.warning(
                f"[route_by_intent] Multimodal message detected with action=direct_reply; "
                f"redirecting to 'general' for vision processing | tenant={state.get('tenant_id')} session={session_id}"
            )
            return "general"
        # 如果有 pending skill，不执行 direct_reply，继续走 skill 流程
        # 例外：澄清护栏强制兜底（guard_forced=True）时，兜底话术必须直达
        # 用户，不能被 pending_skill（澄清卡/表单流程）覆盖回 general skill
        # （真实验收 #2801 发现：护栏改写后被 pending 覆盖，兜底永不触达）。
        if pending_skill and not route.get("guard_forced"):
            logger.info(
                f"[route_by_intent] Pending interact skill '{pending_skill}' overrides direct_reply"
                f" | session={session_id}"
            )
            return pending_skill
        logger.info(
            f"[route_by_intent] Direct reply"
            f" (pending_skill={pending_skill or 'none'}, guard_forced={route.get('guard_forced')})"
            f" | session={session_id}"
        )
        return "direct_reply"

    intent = (state.get("intent_result") or {}).get("intent", "general")

    if pending_skill:
        # 会话连续性：pending skill 存在时必须回到原 skill。
        # 原因：用户点击交互组件发送的值（如 UUID、简短确认文本）可能被意图分类器误判。
        #
        # 例外（escape hatch）：用户输入包含明确话题切换信号时允许切换。
        # 注意：不能用字符数判断——中文确认消息（如"好的，确认创建，克重选中"）轻松超过10字。
        # 仅当消息包含其他领域的显式触发词时才允许逃逸。
        last_msg = _get_last_human_text(state.get("messages", [])) or ""
        _pending_domain = _skill_keyword_domain(pending_skill)

        # ── 答卡轮豁免（#3557 G1）：点本 skill 自己那张卡 → 留在本 skill ──
        # 卡值由系统按"必须含上下文"的协议生成，可能含**其他域**的词（PR-007 的
        # 「（改为停售，买家不可下单）」含「下单」；OR-015 R4 的加工项多选卡答卡
        # 「已选加工项：纳米圈打孔 · ¥9.5/米」含「加工项」）→ 下面的 escape hatch 会把它
        # 当成**话题切换**、清掉会话锁 → intent 兜底成 order/product → 进一个**没有该流程
        # 所需工具**的 skill（PRODUCT_TOOLS 无 order_create / ORDER_TOOLS 无 product_manage）
        # → 零工具调用 + 「模块越界」口径拒绝。同源判据也用在 `intent_router_node`
        # （那里会先被 L1 规则表劫持，所以两处都要拦）。
        # 卡型覆盖：confirm（#3677）+ choice / form（本 PR；run 34841029062 OR-015 R4）。
        # 与 #3361 的契约不冲突：那个场景的输入不是本 skill 卡的取值，见 `_card_accepts_answer`。
        if _is_own_card_round(state):
            logger.info(
                f"[route_by_intent] 答卡轮：留在本 skill（不判话题切换）"
                f" | skill={pending_skill} | session={session_id}"
            )
            return pending_skill

        # 使用模块级单一来源关键词表（plan_rewrite 护栏与 escape hatch 共用）
        # 如果用户消息包含非当前 skill 领域的关键词，允许切换
        current_domain_keywords = _SKILL_DOMAIN_KEYWORDS.get(_pending_domain, set())
        # ── 本领域信号优先：消息里带了**当前技能领域**的关键词 → 不切走（issue #3361 实证）──
        # CH-012 复现型红灯的真因：R1 在 customer_aftersales 下发「请选择要退货的订单」卡，
        # R2 顾客回「我要退上次买的那单，订单号 EVAL-ORD-0002」——含「退货」（aftersales 域）
        # 同时含「订单号」（order 域）→ 旧逻辑只看"有没有别的领域词"→ 判为话题切换 →
        # 会话被甩到 customer_order（**没有 aftersale_create**）→ 模型只能尝试转人工 →
        # 被在办兜底拦住 → 三轮原地打转、售后单永不创建。
        # 语义：顾客在退货流程里提订单号，是**流程内的指代**，不是换话题。
        if (any(kw in last_msg for kw in current_domain_keywords)
                or _msg_matches_domain_pattern(last_msg, _pending_domain)):
            logger.info(
                f"[route_by_intent] Escape hatch skipped: 当前领域信号命中 "
                f"(domain={_pending_domain}) | session={session_id}"
            )
            return pending_skill
        # ── L1 高置信判定优先于关键词表（#3557 G3/T2）──
        # 缺陷：`_SKILL_DOMAIN_KEYWORDS["product"]` 是**管理端查询口径**（查商品/搜商品/
        # 创建商品/商品管理），无任何商品**动作**词 → `pending=order` 时「改一下遮光窗帘的
        # 价格」「查一下库存」这类 L1 已高置信判为 `product_inquiry` 的输入照样被困在 order
        # （`order` 的 `ORDER_TOOLS` 没有 `product_manage`）→ 只能以「模块越界」口径拒绝。
        # 修法：L1 规则命中（`source == "rule"`，**确定性、高置信**）判到**可路由的别的域**
        # → 放行逃逸；LLM 分类器结果不放行（防短信/答卡值被分类器误判成别的域时把锁甩走）。
        _rule_domain = ""
        if str((state.get("intent_result") or {}).get("source") or "") == "rule":
            _rule_domain = _rule_intent_domain(intent, state.get("agent_type", ""))
        if _rule_domain and _rule_domain != _pending_domain:
            logger.info(
                f"[route_by_intent] Escape hatch: L1 高置信域切换 "
                f"'{_pending_domain}' → '{_rule_domain}' (intent={intent}) | session={session_id}"
            )
            state["pending_interact_skill"] = ""
            return _intent_to_route_key(intent, state.get("agent_type", ""))

        for skill_domain, keywords in _SKILL_DOMAIN_KEYWORDS.items():
            if skill_domain == _pending_domain:
                continue
            if (any(kw in last_msg for kw in keywords)
                    or _msg_matches_domain_pattern(last_msg, skill_domain)):
                logger.info(
                    f"[route_by_intent] Escape hatch: domain switch detected "
                    f"from '{pending_skill}' to '{skill_domain}' "
                    f"(keyword matched, msg_len={len(last_msg)}) | session={session_id}"
                )
                state["pending_interact_skill"] = ""
                # 不清除 pending_skill in DB，让下一轮还有机会恢复
                break
        else:
            # 无话题切换信号 → 坚守原 skill
            logger.info(
                f"[route_by_intent] Session continuity: staying in '{pending_skill}' "
                f"(intent={intent}, msg_len={len(last_msg)}) | session={session_id}"
            )
            return pending_skill

    logger.info(
        f"[route_by_intent] Routing to '{intent}' "
        f"(pending_skill={pending_skill or 'none'}, action={action}) | session={session_id}"
    )

    return _intent_to_route_key(intent, state.get("agent_type", ""))
