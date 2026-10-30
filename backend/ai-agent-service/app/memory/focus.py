"""会话级工作记忆（焦点对象）—— 让「这单」「刚才那个客户」有确定性所指（issue #8173）。

只服务 B 端（`agent_type == "mibao"`）：
- 回写：`remember_from_tool_results()` 从工具结果里识别实体（订单号 / 客户 id / 商品 id），
  更新焦点并记录**来源工具名**，落 `SessionStateStore`（与会话同寿命）。
- 恢复：`normalize_focus()` 归一化读取（`_build_initial_state` 用），最多带 3 条 recent。
- 注入：`inject_focus_prompt()` 在 B 端 system prompt 末尾追加 ≤3 行；空焦点 / C 端 ⇒ 原样返回。
- 指代：`resolve_reference()` 纯函数、**不调 LLM**；类型不匹配或无焦点 ⇒ `None`
  （保持追问，不许猜）。

有意不做（边界）：长期画像 `user_memories`（B 端仍关闭，见 #2815）；LLM 指代消解。
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

FOCUS_KEY = "focus"
MAX_RECENT = 3

ENTITY_ORDER = "order"
ENTITY_CUSTOMER = "customer"
ENTITY_PRODUCT = "product"

_ENTITY_LABELS = {
    ENTITY_ORDER: "订单",
    ENTITY_CUSTOMER: "客户",
    ENTITY_PRODUCT: "商品",
}

# 工具结果里出现可识别实体时写焦点；来源工具名原样记录（判据按它归因）。
_ORDER_TOOLS = frozenset({"order_query"})
_CUSTOMER_TOOLS = frozenset({"customer_manage"})
_PRODUCT_TOOLS = frozenset({"product_detail", "product_search"})

# 同一次 gather 里出现多类实体时的优先级：订单 > 客户 > 商品。
# 理由：「这单」是最强的会话指代，订单结果不该被同批的商品详情顶掉。
_ENTITY_PRIORITY = {ENTITY_ORDER: 0, ENTITY_CUSTOMER: 1, ENTITY_PRODUCT: 2}

_ORDER_REF_TOKENS = ("这单", "这一单", "该订单", "刚才那单")
_CUSTOMER_REF_TOKENS = ("这个客户",)
_PRODUCT_REF_TOKENS = ("这个商品", "该商品")

_FOCUS_HINT = (
    "用户说「这单/该订单」时指上述订单焦点；「这个客户」只在焦点是客户时才指上述客户；"
    "焦点类型不匹配或没有焦点时不得猜测，须向用户确认。"
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_turn(value: Any) -> int:
    """轮次归一化：脏值（非数字）按 0 处理 —— 注入路径不得因持久化脏数据抛错。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _entry(
    entity: str,
    entity_id: str,
    label: str,
    source_tool: str,
    turn: int,
) -> Dict[str, Any]:
    return {
        "entity": entity,
        "id": entity_id,
        "label": label or entity_id,
        "source_tool": source_tool,
        "turn": _safe_turn(turn),
    }


def _normalize_entry(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    entity = _text(raw.get("entity"))
    entity_id = _text(raw.get("id"))
    if entity not in _ENTITY_LABELS or not entity_id:
        return None
    return _entry(
        entity,
        entity_id,
        _text(raw.get("label")),
        _text(raw.get("source_tool")),
        raw.get("turn") or 0,
    )


def _first_order(data: Dict[str, Any], source_tool: str, turn: int) -> Optional[Dict[str, Any]]:
    orders = data.get("orders")
    if isinstance(orders, list):
        for item in orders:
            if isinstance(item, dict):
                order_no = _text(item.get("order_no"))
                if order_no:
                    return _entry(ENTITY_ORDER, order_no, f"#{order_no}", source_tool, turn)
    order_no = _text(data.get("order_no"))
    if order_no:
        return _entry(ENTITY_ORDER, order_no, f"#{order_no}", source_tool, turn)
    return None


def _first_customer(data: Dict[str, Any], source_tool: str, turn: int) -> Optional[Dict[str, Any]]:
    rows = data.get("customers")
    candidates: List[Any] = list(rows) if isinstance(rows, list) else [data]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        customer_id = _text(item.get("id") or item.get("customer_id"))
        if not customer_id:
            continue
        name = _text(item.get("name") or item.get("wechatNickname") or item.get("nickname"))
        return _entry(ENTITY_CUSTOMER, customer_id, name or customer_id, source_tool, turn)
    return None


def _first_product(data: Dict[str, Any], source_tool: str, turn: int) -> Optional[Dict[str, Any]]:
    rows = data.get("products")
    candidates: List[Any] = list(rows) if isinstance(rows, list) else [data]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        product_id = _text(item.get("id") or item.get("product_id"))
        if not product_id:
            continue
        name = _text(item.get("name") or item.get("product_name"))
        return _entry(ENTITY_PRODUCT, product_id, name or product_id, source_tool, turn)
    return None


def extract_focus(
    tool_name: str,
    result_dict: Any,
    turn: int = 0,
) -> Optional[Dict[str, Any]]:
    """从**单个**工具结果里识别焦点实体；识别不到 / 失败结果 ⇒ None。"""
    if not isinstance(result_dict, dict) or not result_dict.get("success"):
        return None
    data = result_dict.get("data")
    if not isinstance(data, dict):
        return None
    name = _text(tool_name)
    if name in _ORDER_TOOLS:
        return _first_order(data, name, turn)
    if name in _CUSTOMER_TOOLS:
        return _first_customer(data, name, turn)
    if name in _PRODUCT_TOOLS:
        return _first_product(data, name, turn)
    return None


def _best_candidate(tool_results: Iterable[Any], turn: int = 0) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_rank = len(_ENTITY_PRIORITY) + 1
    for row in tool_results or []:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            continue
        tool_call, _result_str, result_dict = row
        candidate = extract_focus(_text((tool_call or {}).get("name")), result_dict, turn)
        if not candidate:
            continue
        rank = _ENTITY_PRIORITY.get(candidate["entity"], best_rank)
        if best is None or rank <= best_rank:
            best, best_rank = candidate, rank
    return best


def normalize_focus(raw: Any) -> Dict[str, Any]:
    """把持久化/入参形态归一化成 `{entity,id,label,source_tool,turn,recent[≤3]}`。"""
    if not isinstance(raw, dict):
        return {}
    entry = _normalize_entry(raw)
    if not entry:
        return {}
    recent: List[Dict[str, Any]] = [entry]
    for item in raw.get("recent") or []:
        candidate = _normalize_entry(item)
        if not candidate:
            continue
        if any(
            candidate["entity"] == seen["entity"] and candidate["id"] == seen["id"]
            for seen in recent
        ):
            continue
        recent.append(candidate)
        if len(recent) >= MAX_RECENT:
            break
    result = dict(entry)
    result["recent"] = recent[:MAX_RECENT]
    return result


def update_focus(current: Any, candidate: Any) -> Dict[str, Any]:
    """把新候选并入焦点：新候选成为当前焦点，旧的进 recent（去重、封顶 3 条）。"""
    current_focus = normalize_focus(current)
    new_entry = _normalize_entry(candidate)
    if not new_entry:
        return current_focus
    recent: List[Dict[str, Any]] = [new_entry]
    for seen in (current_focus.get("recent") if current_focus else []) or []:
        if seen["entity"] == new_entry["entity"] and seen["id"] == new_entry["id"]:
            continue
        recent.append(seen)
        if len(recent) >= MAX_RECENT:
            break
    result = dict(new_entry)
    result["recent"] = recent[:MAX_RECENT]
    return result


def format_focus_block(focus: Any) -> str:
    """渲染给模型的焦点块（≤3 行）；无焦点 ⇒ 空串（调用方不注入任何行）。"""
    current = normalize_focus(focus)
    if not current:
        return ""
    label = _ENTITY_LABELS.get(current["entity"], current["entity"])
    source = current["source_tool"] or "未知工具"
    head = f"【会话焦点】当前焦点：{label} {current['label']}（来源 {source}"
    head += f"，第 {current['turn']} 轮）" if current["turn"] > 0 else "）"
    lines = [head]
    others = [
        item for item in current["recent"]
        if not (item["entity"] == current["entity"] and item["id"] == current["id"])
    ]
    if others:
        lines.append(
            "最近涉及："
            + "、".join(
                f"{_ENTITY_LABELS.get(item['entity'], item['entity'])} {item['label']}"
                for item in others[:MAX_RECENT - 1]
            )
        )
    lines.append(_FOCUS_HINT)
    return "\n".join(lines[:3])


def inject_focus_prompt(system_prompt: str, state: Any) -> str:
    """B 端（mibao）system prompt 末尾追加焦点块；C 端 / 空焦点 ⇒ 逐字节原样返回。"""
    if not isinstance(state, dict) or state.get("agent_type") != "mibao":
        return system_prompt
    block = format_focus_block(state.get(FOCUS_KEY))
    if not block:
        return system_prompt
    return f"{system_prompt}\n\n{block}"


def _match_reference(text: Any) -> Tuple[str, str]:
    """返回本轮文本命中的 (实体类型, 指代词)；未命中 ⇒ ("", "")。"""
    content = str(text or "")
    for entity, tokens in (
        (ENTITY_ORDER, _ORDER_REF_TOKENS),
        (ENTITY_CUSTOMER, _CUSTOMER_REF_TOKENS),
        (ENTITY_PRODUCT, _PRODUCT_REF_TOKENS),
    ):
        for token in tokens:
            if token in content:
                return entity, token
    return "", ""


def resolve_reference(text: Any, focus: Any) -> Optional[str]:
    """确定性指代解析（不调 LLM）：命中且**焦点类型匹配**才返回 id，否则 None。

    - 「这单 / 这一单 / 该订单 / 刚才那单」⇒ 焦点是订单才返回其 id；
    - 「这个客户」⇒ 焦点是客户才返回其 id，否则 None（保持追问，不许猜）；
    - 无焦点 ⇒ 一律 None。
    """
    current = normalize_focus(focus)
    if not current:
        return None
    entity, _token = _match_reference(text)
    if entity != current["entity"]:
        return None
    return current["id"]


def reference_hint_line(text: Any, focus: Any) -> str:
    """命中且焦点类型匹配 ⇒ 一行「本轮指代：「这单」= 订单 #7732」；否则空串。

    调用方（`prepare_turn`）只在 `resolve_reference` 命中时追加，空串一行都不加。
    """
    current = normalize_focus(focus)
    if not current:
        return ""
    entity, token = _match_reference(text)
    if entity != current["entity"]:
        return ""
    label = _ENTITY_LABELS.get(entity, entity)
    return f"本轮指代：「{token}」= {label} {current['label']}"


async def remember_from_tool_results(
    session_id: str,
    tool_results: Iterable[Any],
    turn: int = 0,
) -> Optional[Dict[str, Any]]:
    """把本轮工具结果里的实体写进会话焦点（跨轮持久化）；无可识别实体 ⇒ 不写、返回 None。"""
    if not session_id:
        return None
    candidate = _best_candidate(tool_results, turn=turn)
    if candidate is None:
        return None
    from app.memory.session_state_store import SessionStateStore

    store = SessionStateStore()
    full = await store.load(session_id) or {}
    updated = update_focus(full.get(FOCUS_KEY), candidate)
    full[FOCUS_KEY] = updated
    await store.commit(session_id, full)
    return updated
