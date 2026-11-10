"""出口 ①：口径卡的 **system prompt 片段**（issue #8175 判据 1 / 4 / 5 / 6）。

## 这里是「审核门禁」的最后一个关口

写面（admin-api）允许 `draft` 存在、允许 `retired` 留着；**能不能进 prompt 只由这里判**。
所以本模块**不信任调用方给它的列表**：`select_playbooks` 对每一张卡重判四件事
（`state == 'active'` / `trigger` 可执行 / `counter` 可执行 / 语境界定），任一条不过就丢掉。

判据 1 的红证就是对着这一层做的：往 `render_playbook_block` 的入参里塞一张 `draft`，
它的正文**一个字符都不许**出现在返回值里。

## 为什么 `trigger` 也要出现在 prompt 里（哪怕已经按语境过滤过）

模型拿到的不该是「无条件必须这么做」的硬规则 —— 口径本身**带条件**（「整卷优先」只对
整卷单成立，「除非客户要求零裁」是反例）。把条件渲染出来，模型才能在**语境没被结构化
捕获**的轮次里自己判断；而条件文本是**由结构生成**的（`condition.describe`），
不接受任何自由文本进入 prompt。

## 消毒

`correct` 是人工审核过的一句话，但它是**数据**不是代码：仍然要过
「去控制字符 → XML 转义 → 截断」（与 `user_memories` 注入同口径）。
理由同 `#2815`：注入面一旦不消毒，一个被篡改的库行就能在 system prompt 里伪造出
注入块之外的行。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import settings
from app.playbook import identity, lifecycle
from app.playbook.condition import describe, evaluate, is_executable
from app.playbook.store import STATE_ACTIVE, PlaybookStore

#: 一次注入最多几条（口径是「少而准」的工件；多到几十条说明治理没做）
MAX_PLAYBOOKS = 12
#: 单条正解 / 条件说明的字符上限（控 token + 防「一句话口径」变成一篇文档）
MAX_CORRECT_CHARS = 200
MAX_CONDITION_CHARS = 120
#: 语境里 `user_text` 的上限（够判 `contains`，又不让整段输入进哈希/比较）
MAX_USER_TEXT_CHARS = 2000

PROMPT_HEADER = (
    "【本企业口径】（人工审核通过；与通用经验冲突时以本口径为准；"
    "条件不满足的轮次按通用规则处理）"
)


def _clean(text: Any, max_len: int) -> str:
    """去控制字符 → XML 转义 → 截断（防注入 + 控 token）。"""
    if text is None:
        return ""
    out = "".join(ch for ch in str(text) if ch.isprintable())
    out = (
        out.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return out[:max_len]


def _rank(card: Dict[str, Any]) -> tuple:
    """确定性选举键：衰减分高 → hits 高 → approved_at 新 → id 小。

    排序键整体取负（越小越优先）；`id` 用字符串升序兜底 —— 两个候选在**所有业务维度**上都打平时，
    结果仍然可复现（否则「今天出哪条」会随库的返回顺序漂移）。
    """
    score = lifecycle.decay_score(card)
    approved = lifecycle.as_datetime(card.get("activated_at"))
    approved_ts = approved.timestamp() if approved is not None else 0.0
    return (-score, -int(card.get("hits") or 0), -approved_ts, str(card.get("id") or ""))


def _dedupe_conflicts(playbooks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一冲突组**只保留一条**（读面兜底：脏数据也不许让 prompt 出现互相矛盾的两条）。

    两条卡属于同一组，满足任一即算（并查集合并，所以三种脏形态都覆盖）：

    1. 内容相同：`scope + scope_role + trigger`（**现算**，不信 `conflict_key`）；
    2. 标记相同：库里的 `conflict_key` 相等（哪怕 trigger 不同）；
    3. 传递合并：A~B 同标记、B~C 同内容 ⇒ A/B/C 是一组。

    保留谁由 `_rank` 决定，**丢弃具名可见**（warning 里同时出现保留者与被丢弃者）——
    「少了一条」必须能在日志里查到，而不是看起来什么都没发生。
    """
    if len(playbooks) < 2:
        return list(playbooks or [])

    parent = list(range(len(playbooks)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_content: Dict[str, int] = {}
    by_conflict: Dict[str, int] = {}
    for index, card in enumerate(playbooks):
        content_key = identity.group_key(card)
        if content_key in by_content:
            union(index, by_content[content_key])
        else:
            by_content[content_key] = index
        conflict_key = card.get("conflict_key")
        if conflict_key:
            if conflict_key in by_conflict:
                union(index, by_conflict[conflict_key])
            else:
                by_conflict[conflict_key] = index

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for index, card in enumerate(playbooks):
        grouped.setdefault(find(index), []).append(card)

    kept: List[Dict[str, Any]] = []
    for group in grouped.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        winner = min(group, key=_rank)
        dropped = [str(card.get("id")) for card in group if card is not winner]
        logger.warning(
            f"[playbook] 冲突组只保留一条 | group={identity.group_key(winner)} "
            f"keep={winner.get('id')} dropped={dropped} "
            f"reason=decay/hits/activated_at（确定性选取，避免 prompt 出现矛盾口径）"
        )
        kept.append(winner)
    kept.sort(key=_rank)
    return kept


def select_playbooks(
    playbooks: Optional[List[Dict[str, Any]]],
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """从**任意**入参里筛出「这一刻可以用」的卡（判据 1 / 4 / 6 的唯一裁决点）。

    - `state != 'active'` ⇒ 丢（判据 1：draft / retired 一条都不许露头）
    - `trigger` 不可执行 ⇒ 丢（判据 2：自由文本不进 prompt）
    - 有 `counter` 但不可执行 ⇒ 丢（判据 6：反例不可判 = 反例是注释）
    - 给了 `context` 且反例命中 ⇒ 丢（判据 6：反例真的进判定面）
    """
    if not playbooks:
        return []
    selected: List[Dict[str, Any]] = []
    for pb in playbooks:
        if not isinstance(pb, dict):
            continue
        if pb.get("state") != STATE_ACTIVE:
            continue
        if not is_executable(pb.get("trigger")):
            logger.warning(
                f"[playbook] 跳过不可执行的 trigger | id={pb.get('id')} "
                f"tenant={pb.get('tenant_id')}"
            )
            continue
        counter = pb.get("counter")
        if counter is not None and not is_executable(counter):
            logger.warning(
                f"[playbook] 跳过不可执行的反例（反例不可判 = 注释）| id={pb.get('id')} "
                f"tenant={pb.get('tenant_id')}"
            )
            continue
        if context is not None and counter is not None and evaluate(counter, context):
            # 反例命中 ⇒ 本卡不适用（这正是「反例不是注释」）
            continue
        selected.append(pb)
    # P2 冲突消解：先按冲突组合并（同组只留一条），再套总数上限 ——
    # 顺序反了会用「另一条口径」挤掉本组唯一代表，等于凭空减少一份企业口径。
    selected = _dedupe_conflicts(selected)
    return selected[:MAX_PLAYBOOKS]


def applies_now(playbook: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """这张卡在**这个语境**下该生效吗？（出口③ 的用例执行器与 prompt 共用同一判定）"""
    selected = select_playbooks([playbook], context)
    if not selected:
        return False
    return evaluate(playbook.get("trigger"), context)


def render_playbook_block(
    playbooks: Optional[List[Dict[str, Any]]],
    context: Optional[Dict[str, Any]] = None,
    *,
    selected: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """渲染成一段可直接拼进 system prompt 的 XML 块；无可用卡 ⇒ 空串（调用方原样返回）。

    `selected` 是**已经选好的**卡（调用方刚调过 `select_playbooks` 时传进来，避免重复筛选 +
    重复打「冲突丢弃」日志）。不传就按 `playbooks` 现选 —— 两条路走的是同一份判定。
    """
    chosen = selected if selected is not None else select_playbooks(playbooks, context)
    if not chosen:
        return ""
    lines: List[str] = [PROMPT_HEADER, "<playbooks>"]
    for pb in chosen:
        when = _clean(describe(pb.get("trigger")), MAX_CONDITION_CHARS)
        correct = _clean(pb.get("correct"), MAX_CORRECT_CHARS)
        if not when or not correct:
            continue
        # 来源（判据 4：审核通过 ⇒ 出现在 prompt **且带来源**）。
        # 只有 session_id（不是无来源的推断）：模型引用口径时能指回「哪次会话的第几轮」，
        # 人类复盘时也不用再翻库。`_clean` 会 XML 转义 —— 来源是**数据**，不许在 prompt 里
        # 制造出注入块之外的元素。
        source = pb.get("source") or {}
        session_id = _clean(source.get("session_id"), 64)
        turn = source.get("turn")
        provenance = f' source="{session_id}#{_clean(turn, 8)}"' if session_id else ""
        lines.append(
            f'  <rule id="{_clean(pb.get("id"), 64)}"'
            f' scope="{_clean(pb.get("scope"), 16)}"{provenance}>'
        )
        lines.append(f"    <when>{when}</when>")
        lines.append(f"    <do>{correct}</do>")
        counter = pb.get("counter")
        if counter is not None:
            except_text = _clean(describe(counter), MAX_CONDITION_CHARS)
            if except_text:
                lines.append(f"    <except>{except_text}（命中例外时不套用本口径）</except>")
        lines.append("  </rule>")
    lines.append("</playbooks>")
    if len(lines) <= 3:  # 只有头 + 开闭标签 ⇒ 没有任何可用卡
        return ""
    return "\n".join(lines)


def _last_user_text(state: Dict[str, Any]) -> str:
    """本轮最后一条**用户原话**（没有 ⇒ 空串）。

    为什么要进来：条件语言的 `user_text` 字段一直有中文标签（`condition.py` 的
    `_FIELD_LABELS`）、`casegen` 也按它采样语境，但**运行时语境里从来没有这个键**
    ⇒ 任何以 `user_text` 为条件的卡（含**反例**「除非客户要零裁」）在真实会话里
    永远不成立 —— 字段存在、功能不生效。这正是本单要防的形态，所以在这里补上。
    """
    messages = state.get("messages") or []
    for message in reversed(list(messages)):
        kind = getattr(message, "type", None)
        if kind is None and isinstance(message, dict):
            kind = message.get("type")
        if kind != "human":
            continue
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content[:MAX_USER_TEXT_CHARS]
    return ""


def _context_from_state(state: Dict[str, Any], skill_name: str = "") -> Dict[str, Any]:
    """从会话状态抽「结构化语境」——只放**确定**的事实，缺就缺（不猜）。"""
    context: Dict[str, Any] = {}
    if state.get("agent_type"):
        context["agent_type"] = state.get("agent_type")
    if skill_name:
        context["skill"] = skill_name
    role = state.get("role") or state.get("role_key")
    if role:
        context["role"] = role
    user_text = _last_user_text(state)
    if user_text:
        context["user_text"] = user_text
    return context


async def inject_playbook_prompt(
    system_prompt: str,
    state: Dict[str, Any],
    skill_name: str = "",
) -> str:
    """**B 端**（黄金策 / `mibao`）system prompt 注入出口 ①。

    - 非 B 端（C 端米宝）/ 无租户 ⇒ **原样返回同一个字符串**（C 端零回归）；
    - 任何异常都不抛（fire-and-forget，与 `_inject_user_memories` 同口径）；
    - 注入位置：`_build_system_prompt` 之后、其余跨轮注入之前（口径先于临时提示）。
    """
    if state.get("agent_type") != "mibao":
        return system_prompt
    try:
        tenant_id = int(state.get("tenant_id", 0) or 0)
    except (TypeError, ValueError):
        return system_prompt
    if not tenant_id:
        return system_prompt
    try:
        playbooks = await PlaybookStore().list_active(
            tenant_id, role=state.get("role") or state.get("role_key")
        )
        context = _context_from_state(state, skill_name)
        selected = select_playbooks(playbooks, context)
        block = render_playbook_block(selected, context, selected=selected)
        # 命中计数（P2 衰减/退役的唯一数据面）：只在**触发条件真的命中本轮语境**时 +1。
        # 关闭时一次写入都没有（读路径的行为不因开关改变）；失败只记 warning，不毁本轮对话。
        if settings.PLAYBOOK_HIT_TRACKING_ENABLED:
            matched = [
                str(pb.get("id"))
                for pb in selected
                if pb.get("id") and evaluate(pb.get("trigger"), context)
            ]
            if matched:
                try:
                    await PlaybookStore().record_hits(tenant_id, matched)
                except Exception as hit_error:  # noqa: BLE001 — 计数失败不是本轮对话的故障
                    logger.warning(f"[playbook] 命中计数失败（非致命）: {hit_error}")
        if block:
            logger.info(
                f"[playbook] injected | tenant={tenant_id} "
                f"count={block.count('<rule ')} len={len(block)}"
            )
            return block + "\n" + system_prompt
    except Exception as e:  # noqa: BLE001 — 注入失败不许毁掉本轮对话
        logger.warning(f"[playbook] 注入失败（非致命）: {e}")
    return system_prompt
