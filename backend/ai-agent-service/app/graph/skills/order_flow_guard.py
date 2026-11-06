"""订单流程锁 / 归属 / 撤销 + 跨轮流程观的**单一真值源**（从 `base_skill.py` 搬出，issue #8725）。

## 单一职责

回答一个问题：**「这一轮该在哪个 skill 里、能不能把会话锁过去/放出来」**：

| 函数 | 职责 |
|---|---|
| `_flow_owner_skill` / `_route_cross_skill_target` | 本轮该归谁来办（跨 skill 转办的**唯一**判据点） |
| `_relock_order_skill` / `_release_order_lock_on_withdrawal` | 会话锁的**加**与**放**（撤销意图时解锁） |
| `_order_flow_started` / `_flow_state_in_progress` / `_order_flow_in_progress` | 「在办流程」的三种读法 |
| `_is_ordering_withdrawal` / `_has_ordering_intent` | 撤销 / 下单意图判据（词表 + 窗口） |

## 依赖方向（单向）

```text
base_skill.py ──(re-export)──▶ order_flow_guard.py ──(顶层 import)──▶ capability_denial.py
```

## ⚠️ patch 缝：`logger` **调用期**从 base_skill 取

既有守卫用 `patch("app.graph.skills.base_skill.logger")` / `patch.object(base_skill, "logger")`
给这个模块全局打桩。模块顶层 `from loguru import logger` 会把绑定**冻在加载那一刻** ⇒ patch **静默失效**
（本仓最忌讳的「判据自己选择沉默」；实证见 `tests/unit/test_execute_skill_split.py` 的同类说明）。
故这里沿用 `execution/*.py` 的既成写法：**函数入口处**重新绑定，恢复拆分前的**同一解析时机**。
接缝清单由测试**机械提取**（`tests/unit/test_execute_skill_split.py`），将来新增 patch 点自动覆盖。

## 搬运纪律

函数体是原 `base_skill.py` 对应行的**逐字副本**（`ast` 边界切片），唯一机械改动 = 上述 2 行前导。
"""
import json

from langchain_core.messages import ToolMessage

from app.graph.skills.capability_denial import (
    ORDER_WRITE_TOOL, _ORDER_ACTION_WORDS, _normalize_clause,
)


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


# ── 「顾客显式撤回下单」= 比会话锁**更高优先级**的用户信号（issue #7758）────────────
# 生产实证 sess_cf885dc3ef40435a：会话被误锁在 order，顾客「我不是要下单，我要更新商品」
# 因**子串**命中 `_ORDER_INTENT_HINTS`（含「下单」）被判成"仍在推进下单" ⇒ 守卫继续上膛、
# 会话锁没有任何出口 ⇒ 连续 3 轮追问下单规格。
# 为什么不直接把 `_has_ordering_intent` 改成"认否定"：它的宽松是**有意**的（#3477 ——
# 状态优先于措辞，防顾客改口成「好的，就按这个来」就丢守卫）；撤回是**反方向**的信号，
# 该在调用点覆盖（路由 + 在办判据 + 轮末持久化三处），而不是把意图判据改钝。
# 锚点 = **下单动作词** + 少数明确的结算类动词；刻意**不含** `_ORDER_INTENT_HINTS` 里的
# 含糊项（「就这个」「买它」「拍下」）—— 撤回会**清锁**，误判的代价比漏判大
# （「不就是这个价吗」这种反问不该被当成撤回）。
_ORDER_WITHDRAWAL_ANCHORS = tuple(dict.fromkeys(
    _ORDER_ACTION_WORDS + ("结算", "结账", "付款", "购买")))
_ORDER_WITHDRAWAL_NEGATIONS = ("不", "没", "别", "非", "勿")
# 否定词与动作词之间允许的字数：「我**不是要**下单」= 4 字。刻意窄 —— 放宽会把
# 「不要错过下单优惠」这类**正向**措辞吃掉；撤回判据宁可漏一点，也不能误吞正向推进。
_ORDER_WITHDRAWAL_WINDOW = 4


def _is_ordering_withdrawal(message: str) -> bool:
    """这一轮消息是否在**显式撤回**下单（「我不是要下单」「先不落单了」「别结算了」）。

    判据 = **否定词 × 下单动作锚点**（与 `_has_ordering_intent` 同一族锚点，方向相反）：
    前者问"有没有下单措辞"，这里问"那句措辞是不是被否掉的"。结构性判据（否定词距离窗口），
    不是整句白名单。
    """
    text = _normalize_clause(str(message or ""))
    if not text:
        return False
    for anchor in _ORDER_WITHDRAWAL_ANCHORS:
        start = 0
        while True:
            idx = text.find(anchor, start)
            if idx < 0:
                break
            window = text[max(0, idx - _ORDER_WITHDRAWAL_WINDOW):idx]
            if any(neg in window for neg in _ORDER_WITHDRAWAL_NEGATIONS):
                return True
            start = idx + len(anchor)
    return False


async def _release_order_lock_on_withdrawal(session_id: str | None,
                                            state: dict | None = None) -> bool:
    """用户显式撤回下单 ⇒ **解除跨轮下单锁**（issue #7758）。

    为什么必须显式解除：`finalize_turn` 的跨轮持久化段每轮都把 `pending_skill` 写回当前 skill
    ⇒ 一旦会话被误锁到 `order`，**没有任何轮次**会把它放开（生产实证 sess_cf885dc3ef40435a：
    顾客亲口说「我不是要下单」后仍在订单流里连续追问下单规格）。

    只在 `state["ordering_withdrawn"]` 为真时动作（由 `route_by_intent` 在
    「**pending 落在下单域** × 本轮显式撤回」时置位）⇒ 别的流程的锁不归本函数管。

    Returns: 是否真的清过锁（未置位 / 写失败 ⇒ False；调用点忽略返回值，语义不变）。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if not session_id or not (state or {}).get("ordering_withdrawn"):
        return False
    try:
        from app.memory.session_memory import SessionMemory
        await SessionMemory().set_pending_skill(session_id, None)
        logger.info(f"[下单流程] 用户显式撤回下单 → 清除跨轮下单锁 | session={session_id}")
        return True
    except Exception as e:
        logger.warning(
            f"[下单流程] 清除下单锁失败（非致命）| session={session_id} error={e}")
        return False


def _flow_owner_skill(state: dict | None = None,
                      tool_name: str = ORDER_WRITE_TOOL) -> str:
    """**声明了**该写工具的 skill 名 —— 判据取自注册表声明（`SkillConfig.tool_names`）+ 当前 persona 可达集。

    为什么必须 derive（#3571 族第 6 次复发，OR-014 实证）：`_relock_order_skill` 曾写死
    `"customer_order"` —— 那是**只存在于元元（C 端）图**里的节点名。黄金策（B 端）图只有
    `order/product/…`（`MIBAO_CONFIG.skill_names`）⇒ B 端会话回锁后会指向一个
    **图中不存在的节点**（`route_by_intent` 把 pending 名原样返回，条件边映射缺失）——
    即"恢复了能力"的那一步自己先把会话打坏。
    这里不引入任何 skill 名字面量：谁声明了 `order_create` 由注册表回答，persona 可达集由
    `AgentConfig.skill_names` 回答 —— "回锁目标必须真的在该 persona 的图里"由
    `tests/test_or014_flow_owner_guard.py::TestFlowOwnerIsFactDerived` 与
    `tests/unit_ci_workflows/test_denial_guard_or014_invariants.py` 机械守护。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    try:
        from app.graph.skills.skill_registry import get_skill_registry
        owners = [c.name for c in get_skill_registry().get_all()
                  if tool_name in (getattr(c, "tool_names", None) or [])]
        if not owners:
            return ""
        persona = str((state or {}).get("agent_type") or "")
        from app.agents.agent_config import find_agent_for_role, get_agent_config
        if not persona:
            # 缺 agent_type 的调用点（如既有测试构造的 state）：按**角色声明事实**定 persona
            # （`AgentConfig.allowed_roles` 是声明式事实，不是名字表）。
            persona = find_agent_for_role(str((state or {}).get("role") or "")) or ""
        cfg = get_agent_config(persona) if persona else None
        reachable = set(cfg.get_all_skill_names()) if cfg else set()
        for name in owners:
            if name in reachable:
                return name
        if cfg is not None:
            # persona **已知**：只能回锁该 persona 图里真的存在的节点。一个候选都不可达 ⇒
            # fail-safe 返回 ""（不回锁）。issue #5247 实测暴露：B 端只读化后 `order_create`
            # 的唯一归属是 C 端 `customer_order`，若仍走下面的"唯一候选"兜底，**黄金策**（已知 persona）
            # 会拿到一个**不在自己图里**的节点名（`route_by_intent` 原样返回 pending 名 ⇒ 条件边
            # 映射缺失，会话被打坏）。兜底只对"persona 完全解析不出"的情形保留。
            return ""
        # 认不出 persona 时只在**唯一候选**下回锁，避免猜错图（猜错 = 指向图中不存在的节点）
        return owners[0] if len(owners) == 1 else ""
    except Exception as e:
        logger.warning(f"[base_skill] 解析下单流程归属 skill 失败（非致命）: {e}")
        return ""


async def _relock_order_skill(session_id: str | None, state: dict | None = None,
                              migrate_card_owner: bool = False,
                              tool_name: str = ORDER_WRITE_TOOL) -> str:
    """顾客在办下单但当前轮在别的 skill → 把会话**锁回下单流程**（issue #3477）。

    为什么必要（C-A1 run 34791767013 实证）：会话被 choice 卡锁在 `customer_product`，
    顾客「确认下单」后元元说"没权限"并转人工 —— 该 skill 没有 `order_create`，
    而守卫（能力误宣/转人工）此前只认 customer_order/customer_aftersales。
    把 `pending_interact_skill` 锁回**声明了该写工具的那个 skill** 后，**下一轮**路由会走下单
    流程，订单才能真的落下（这是恢复路径，不是口头承诺）。目标由 `_flow_owner_skill` 从
    注册表事实 derive（不再写死 C 端节点名）。

    `tool_name`（issue #4124）：本轮回锁要让**哪个**工具在下一轮可达（默认下单写工具 ⇒
    既有调用点语义不变）。域闸门拒域外目标（`cross_skill_target`）时，回锁目标必须是
    **被拒的那个工具**的归属流程 —— 谁拥有它由注册表事实回答；否则"回锁了但目标仍不可达"，
    等于把 #3976 的空头承诺换个位置重演。

    Returns: 实际回锁到的 skill 名；**未回锁/解析不出/写失败 ⇒ `""`**（既有调用点忽略返回值，
    语义不变；`_route_cross_skill_target` 据此判断"能不能对模型宣称已切流程"）。

    `migrate_card_owner=True`：把**在办确认卡的归属标记**随流程一起迁移（#3571 族，OR-014 实证）。
    为什么必须：下一轮的"答卡轮豁免"要求 `last_card_skill == pending_interact_skill` ——
    卡是在**漂错的那个 skill**里发的，只回锁流程而不迁移卡归属，用户点这张卡时又会被判成
    "别的 skill 的卡" → L1 域逃逸再次把会话甩回 product → 乒乓（等于没修）。
    只迁移 **confirm 卡**（写流程的确认卡）；choice/form 卡（如商品上下架选择器）语义上属于
    发卡 skill 自己的流程，不跟着订单流程走。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if not session_id:
        return ""
    owner = _flow_owner_skill(state, tool_name)
    if not owner:
        logger.warning(
            f"[base_skill] 未能从注册表解析 {tool_name} 的归属 skill → 跳过回锁（非致命）")
        return ""
    try:
        from app.memory.session_memory import SessionMemory
        await SessionMemory().set_pending_skill(session_id, owner)
    except Exception as e:
        logger.warning(f"[base_skill] 锁回归属流程失败（非致命）: {e}")
        return ""
    if not migrate_card_owner:
        return owner
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        card = full.get("last_card") or {}
        if (str(card.get("component") or "") == "confirm"
                and str(full.get("last_card_skill") or "") != owner):
            full["last_card_skill"] = owner
            full["last_confirm_skill"] = owner
            await store.commit(session_id, full)
            logger.info(
                f"[base_skill] 在办确认卡的归属随流程迁移 → {owner} | session={session_id}")
    except Exception as e:
        logger.warning(f"[base_skill] 迁移在办卡归属失败（非致命）: {e}")
    return owner


async def _route_cross_skill_target(session_id: str | None, state: dict | None,
                                    tool_name: str, skill_name: str = "") -> str:
    """消化域闸门判决 `cross_skill_target`：回锁归属流程 + 返回**可执行**的下一步（issue #4124）。

    病灶（#4123 的 artifact 原文）：`product` 流程（12 个工具）内
    `validate_input(order_manage)` 被判 `cross_skill_target` 后，skills 层**零消费**
    （`grep -rn "cross_skill_target" app/graph/skills/` 只命中一处注释）⇒ 模型只拿到劝导语
    「请把会话切到具备该工具的流程后再执行」，而它**没有切换原语** ⇒ 整条链路被放弃
    （AS-003 期望的 `after_sales_manage` 从未被调用）。这里把判决接上**已有的恢复原语**：
    归属从注册表事实 derive（`_flow_owner_skill`，不写死 skill 名）→ `_relock_order_skill`
    回锁（含在办确认卡归属迁移 —— AS-003 正是"已发过确认卡"的形态）→ 一次说清
    「本会话已切到哪 / 下一轮什么可用 / **本轮**该做什么」。

    指引**刻意不承诺本轮执行**：本轮 `bind_tools` 已定，目标工具本轮不可调用
    （写成"本轮可用"就是 #3976 的空头承诺）。
    也**刻意不把 `human_handoff` 写成下一步**：本工具集里它常常可达（`order`/`aftersales`/
    `general` 都声明了它），但"可达 ≠ 该处方" —— 把可恢复的流程改成转人工是更坏的失败形态；
    模型仍可自行判断（写闸门被拦时的话术里也照旧给出转人工出口）。

    Returns: 给模型的指引全文；下列 fail-safe 分支**不改任何状态、返回 `""`**（调用方退回
    既有 suggestion）：无 session / 目标为空 / persona 不可达 / 归属解析不出 /
    归属 == 当前流程（回锁到原地 = 没切 ⇒ 不得对模型宣称"已切到"）。
    为什么必须 fail-safe（`_flow_owner_skill` docstring 的教训）：回锁目标必须真的在该
    persona 的图里 —— 指错图/指原地，"恢复了能力"的那一步自己先把会话打坏（比不修更糟）。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if not session_id or not tool_name:
        return ""
    owner = _flow_owner_skill(state, tool_name)
    if not owner or owner == skill_name:
        logger.warning(
            f"[base_skill] cross_skill_target 无法回锁（不改会话状态）: target={tool_name} "
            f"owner={owner or '<解析不出>'} current={skill_name or '<未知>'} | session={session_id}")
        return ""
    if not await _relock_order_skill(session_id, state, migrate_card_owner=True,
                                     tool_name=tool_name):
        return ""
    logger.warning(
        f"[base_skill] cross_skill_target 已回锁归属流程: {skill_name or '<未知>'} → {owner} "
        f"(target={tool_name}) | session={session_id}")
    return (
        f"`{tool_name}` 不属于**本轮**流程可执行的工具（域闸门判定：跨流程目标），校验未执行。"
        f"**本会话已切到归属流程 `{owner}`：下一轮 `{tool_name}` 即可执行**。"
        f"本轮请**不要再调用** `{tool_name}`，也**不要再发同一张确认卡**"
        f"（本轮工具集已定，点了同样执行不了）；请向用户说明情况，"
        f"并请他再说一次「确认」（或复述要继续办理的事）——下一轮即可办结。"
    )


async def _load_session_facts(session_id: str | None) -> dict:
    """读本会话的**跨轮事实**（未持久化/异常时返回空 dict，不抛）。"""
    if not session_id:
        return {}
    try:
        from app.memory.session_state_store import SessionStateStore
        return await SessionStateStore().load(session_id) or {}
    except Exception:
        return {}


async def _order_flow_started(session_id: str | None, state: dict | None = None) -> bool:
    """下单流程是否已有**真实进展**：本会话成功查过商品详情（`grounded_product_detail`）。

    为什么用这个标记：它是"流程真的开始了"的权威痕迹（查商品是下单链路的必经步骤），
    且不依赖 `state["messages"]` 是否带回上一轮 ToolMessage（跨轮可靠）。
    """
    return bool((await _load_session_facts(session_id)).get("grounded_product_detail"))


def _flow_state_in_progress(state: dict | None = None) -> bool:
    """会话是否**锁定在某个在办业务流程**中（跨轮 pending 锁 / 未完结交互卡）。

    纯**状态事实**（与 skill 名、措辞都无关）：卡片发出即锁、写操作成功即清。
    供"顾客在办下单"与"在办流程中无信号转人工"两处复用（单一事实源）。
    """
    st = state or {}
    return bool(st.get("pending_interact_skill")) or \
        _has_inflight_interactive_card(st.get("messages", []))


async def _order_flow_in_progress(session_id: str | None, state: dict | None = None,
                                  last_user_msg: str = "") -> bool:
    """顾客是否**处于在办下单流程**（状态/事实驱动，与 skill 名和措辞无关）。

    四条独立事实，命中任一即算在办：
      ① 已校验过**下单写参数**（`pending_validated_input.target_tool == order_create`）
         —— 最强证据（顾客已经走到写前一步）；
      ② 本会话成功查过商品详情（`grounded_product_detail`）**且流程仍锁定中**
         （pending 锁 / 未完结交互卡）—— #3477 的形态（choice 卡把会话锁在 customer_product）；
      ③ 本会话查过商品详情 **且** 本轮消息仍在下单 —— 保留原判据作措辞兜底。

    ④ **显式撤回**（`_is_ordering_withdrawal`）优先于 ①②③ —— 顾客亲口撤回就直接为假
       （issue #7758：反方向信号不能由状态压住，否则误锁的会话永远出不来）。

    为什么 ② 必需（issue #3477 C-A1 run 34791767013 实证）：顾客已说「确认下单」，
    但旧判据只看**本轮消息里的关键词**（`_ORDER_INTENT_HINTS`）—— 顾客改说「好的，就按这个来」
    就判为"不在办" → 守卫整段失效、顾客被推给人工。**状态在，就不允许由措辞决定守卫是否生效。**
    """
    # 撤回优先（issue #7758）：顾客**显式撤回**下单 ⇒ 在办判据直接为假。
    # 撤回是反方向的用户信号，压过 ①② 的状态事实（正向改述仍由状态兜底，见 #3477）。

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if _is_ordering_withdrawal(last_user_msg):
        logger.info(
            f"[下单流程] 用户显式撤回下单 → 在办判据为假（不再 relock）"
            f" | session={session_id}")
        return False

    # 廉价前置（性能）：既无在办迹象（无跨轮锁/在办卡）、本轮也没有下单动作 → 直接 False，
    # **不查会话存储**。这条判据会在每个 tool 调用前评估，真实链路里每轮有多个 tool 调用，
    # 无条件 `SessionStateStore.load` 会白白多出 N 次存储往返。
    # 覆盖性说明：① 的 `pending_validated_input` 总是伴随跨轮 pending 锁（写流程锁在
    # `execute_skill` 收尾写入）→ 走 ② 的 `_flow_state_in_progress(state)` 分支仍会命中；
    # ②/③ 本就要求"已接地商品"，而无在办迹象时它也不会成立。
    if not (_flow_state_in_progress(state) or _has_ordering_intent(last_user_msg)):
        return False
    facts = await _load_session_facts(session_id)
    _pvi = facts.get("pending_validated_input") or {}
    if str((_pvi or {}).get("target_tool") or "") == ORDER_WRITE_TOOL:
        return True
    if not facts.get("grounded_product_detail"):
        return False
    return _flow_state_in_progress(state) or _has_ordering_intent(last_user_msg)
