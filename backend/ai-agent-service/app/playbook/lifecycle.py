"""口径卡的**生命周期规则**（issue #8175 P2）：衰减 / 规则化退役 / 晋升判定。

## 三件事，一条数据面

| 动作 | 输入 | 输出 | 默认 |
|---|---|---|---|
| **衰减** | `hits` + 最近命中时间 | 一个分数（指数半衰） | 恒算（只读，不改行为） |
| **规则化退役** | 衰减分 + 连续无命中天数 | `active → retired` + **可审计原因** | **关** |
| **晋升** | `(key, value)` 上的**不同员工**复现数 | `draft → active` | **关** |

## 为什么默认关（这是安全口径，不是保守）

P1 立下的边界是「**必须有人审核这一环**」。自动退役/晋升都是**绕过人工**的动作：

- 退役 = 一条口径**立即**从全企业 prompt 里消失（读面不缓存）⇒ 判错就是企业行为被悄悄改掉；
- 晋升 = 一条**没人审核过**的 draft 变成全企业规则 ⇒ 污染面比退役更大。

所以两档都做成**显式开关**（环境变量），并且 `apply` 默认 dry-run：先看清单，再决定写不写。
开关的名字与默认值都写进 PR body 的「待人工裁定」表 —— **业务参数不在代码里散落魔法数**。

## 退役的「连续 N 天 hits 不增长」怎么判

没有历史快照表 ⇒ 用 `last_hit_at`（命中计数最后一次增长的时刻）当锚点：
`now - (last_hit_at or activated_at or created_at) >= N`。命中一次就推迟 N 天，
这正是「不增长」的语义。**命中追踪关闭时无法判定**这条 —— 此时 `retire_sweep` 报
`judged=False`（不是「0 条可退役」的假绿；三态读数口径同仓库其它机制）。

## 晋升的数据面（会话 → 员工）

`playbook_reproductions` 由落库面（`app/playbook/ingest.py`）写：每来一条候选，就沿着
`sessions.customer_id → users.id` 解析出「这轮是谁在跟黄金策说话」，并排除 C 端身份
（`role IN ('customer','agent')`）。同一员工对同一 `(key, value)` 只记一条（唯一索引兜底），
所以 `COUNT(DISTINCT employee_id)` 的语义是「**几个不同员工说过同一件事**」，不是「说过几次」。
**这条链表在 P1 是断的**（`sessions` 没有 agent_type）⇒ 角色过滤就是这里的判别依据，
它的局限写在 PR body 的「数据面现取证明」里，不粉饰。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from app.config import settings
from app.playbook import identity
from app.playbook.condition import is_executable

STATE_ACTIVE = "active"
STATE_DRAFT = "draft"

#: 自动动作的操作者标签（写进 `reviewed_by`；人工动作写员工 id）
SYSTEM_RETIRE_ACTOR = "system:auto-retire"
SYSTEM_PROMOTE_ACTOR = "system:promotion"

#: 退役：CAS（`state='active'` 写进 WHERE）+ 租户列 + 可审计原因
_RETIRE_SQL = """
UPDATE playbooks
SET state = 'retired', retired_at = NOW(), lifecycle_reason = :reason,
    reviewed_by = 'system:auto-retire', updated_at = NOW()
WHERE id = :id AND tenant_id = :tenant_id AND state = 'active'
"""

#: 晋升：CAS（`state='draft'` 写进 WHERE）+ 租户列 + 可审计原因
_PROMOTE_SQL = """
UPDATE playbooks
SET state = 'active', activated_at = NOW(), lifecycle_reason = :reason,
    reviewed_by = 'system:promotion', updated_at = NOW()
WHERE id = :id AND tenant_id = :tenant_id AND state = 'draft'
"""

_LIFECYCLE_COLUMNS = """
    id, tenant_id, scope, scope_role, trigger_json, correct_text, counter_json,
    hits, state, conflict_key, activated_at, created_at, last_hit_at
"""

_ACTIVE_CARDS_SQL = f"""
SELECT {_LIFECYCLE_COLUMNS}
FROM playbooks
WHERE tenant_id = :tenant_id AND state = 'active'
ORDER BY id ASC
LIMIT 1000
"""

_DRAFT_CARDS_SQL = f"""
SELECT {_LIFECYCLE_COLUMNS}
FROM playbooks
WHERE tenant_id = :tenant_id AND state = 'draft'
ORDER BY id ASC
LIMIT 1000
"""

#: 同一 `(key, value)` 上有几个**不同员工**复现过（`COUNT(*)` 会把一个人说两次读成两个人）
_REPRODUCTION_COUNT_SQL = """
SELECT playbook_key, value_key, COUNT(DISTINCT employee_id) AS employees
FROM playbook_reproductions
WHERE tenant_id = :tenant_id
GROUP BY playbook_key, value_key
"""


# ── 时间 / 数值 ─────────────────────────────────────────────────────────────


def as_datetime(value: Any) -> Optional[datetime]:
    """库值 / ISO 串 / datetime → 带时区的 datetime（判不了 ⇒ None，不猜）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# ── 衰减 ────────────────────────────────────────────────────────────────────


def decay_score(card: Dict[str, Any], now: Any = None) -> float:
    """`hits × 0.5^(距上次命中的天数 / 半衰期)`；无命中 ⇒ 0；无时间锚点 ⇒ 不衰减。"""
    hits = _as_int(card.get("hits"))
    if hits <= 0:
        return 0.0
    current = as_datetime(now) or datetime.now(timezone.utc)
    anchor = (
        as_datetime(card.get("last_hit_at"))
        or as_datetime(card.get("activated_at"))
        or as_datetime(card.get("created_at"))
    )
    if anchor is None:
        # 没有时间锚点就「不衰减」：猜一个年龄会把新卡误判成老卡，宁可不判
        return float(hits)
    half_life = float(getattr(settings, "PLAYBOOK_DECAY_HALF_LIFE_DAYS", 90.0) or 0.0)
    if half_life <= 0:
        return float(hits)
    age_days = max(0.0, (current - anchor).total_seconds() / 86400.0)
    return float(hits) * (0.5 ** (age_days / half_life))


# ── 退役判定 ────────────────────────────────────────────────────────────────


def retirement_verdict(card: Dict[str, Any], now: Any = None) -> Dict[str, Any]:
    """一张卡的退役判定（**不写库**）：`{id, eligible, reason, decay, idle_days}`。

    - 开关关闭 ⇒ `reason="disabled"`（明确「没判」，不是「判了不够条件」）；
    - 两个条件**同时**成立才 eligible：连续 N 天无命中 **且** 衰减分 < 阈值。
    """
    current = as_datetime(now) or datetime.now(timezone.utc)
    score = decay_score(card, current)
    verdict: Dict[str, Any] = {
        "id": card.get("id"),
        "eligible": False,
        "reason": "disabled",
        "decay": score,
        "idle_days": None,
    }
    if not bool(getattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", False)):
        return verdict
    if card.get("state") != STATE_ACTIVE:
        verdict["reason"] = "not_active"
        return verdict
    anchor = (
        as_datetime(card.get("last_hit_at"))
        or as_datetime(card.get("activated_at"))
        or as_datetime(card.get("created_at"))
    )
    if anchor is None:
        verdict["reason"] = "no_timestamp"
        return verdict
    idle_days = max(0.0, (current - anchor).total_seconds() / 86400.0)
    verdict["idle_days"] = idle_days
    threshold_days = int(getattr(settings, "PLAYBOOK_RETIRE_AFTER_DAYS", 60) or 0)
    if idle_days < threshold_days:
        verdict["reason"] = "not_idle"
        return verdict
    threshold = float(getattr(settings, "PLAYBOOK_RETIRE_DECAY_THRESHOLD", 0.5) or 0.0)
    if score >= threshold:
        verdict["reason"] = "decay_above_threshold"
        return verdict
    verdict["eligible"] = True
    verdict["reason"] = (
        f"连续 {idle_days:.0f} 天无命中（锚点 {anchor.date().isoformat()}）"
        f"且衰减分 {score:.3f} < 阈值 {threshold}"
    )
    return verdict


def plan_retirements(cards: Optional[Iterable[Dict[str, Any]]], now: Any = None) -> List[Dict[str, Any]]:
    """只返回**够条件**的那几条（顺序按 id，输出可逐字节复算）。"""
    verdicts = [
        retirement_verdict(card, now)
        for card in sorted((c for c in cards or [] if isinstance(c, dict)), key=lambda c: str(c.get("id") or ""))
    ]
    return [verdict for verdict in verdicts if verdict["eligible"]]


def retire_sweep(
    cards: Optional[Iterable[Dict[str, Any]]] = None,
    now: Any = None,
    db: Any = None,
    tenant_id: Optional[int] = None,
) -> Dict[str, Any]:
    """退役扫描（**只判不写**）：默认关；命中追踪关闭 ⇒ `judged=False`（不可判定，不谎报）。"""
    if not bool(getattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", False)):
        return {
            "enabled": False,
            "judged": False,
            "reason": "PLAYBOOK_AUTO_RETIRE_ENABLED=false（默认关，缺省不改变线上行为）",
            "verdicts": [],
        }
    if not bool(getattr(settings, "PLAYBOOK_HIT_TRACKING_ENABLED", False)):
        return {
            "enabled": True,
            "judged": False,
            "reason": "hit_tracking_disabled: 命中计数没开 ⇒「连续 N 天 hits 不增长」不可判定",
            "verdicts": [],
        }
    source = [c for c in cards or [] if isinstance(c, dict)] if cards is not None else []
    verdicts = plan_retirements(source, now)
    return {
        "enabled": True,
        "judged": True,
        "reason": f"评估 {len(source)} 张 active，{len(verdicts)} 张满足退役条件",
        "verdicts": verdicts,
    }


async def apply_retirements(db: Any, tenant_id: int, verdicts: List[Dict[str, Any]]) -> int:
    """逐条 CAS 退役（影响 0 行 = 状态已被别人改过，不静默成功）。"""
    from sqlalchemy import text

    retired = 0
    for verdict in verdicts:
        result = await db.execute(
            text(_RETIRE_SQL),
            {
                "id": verdict["id"],
                "tenant_id": int(tenant_id),
                "reason": verdict["reason"],
            },
        )
        if getattr(result, "rowcount", 0):
            retired += 1
    return retired


# ── 晋升判定 ────────────────────────────────────────────────────────────────


def plan_promotions(
    drafts: Optional[Iterable[Dict[str, Any]]],
    counts: Optional[Dict[Any, int]],
    active_group_keys: Optional[Iterable[str]],
    min_employees: Optional[int] = None,
) -> Dict[str, Any]:
    """draft × 复现计数 × 冲突组 → 可晋升清单 / 被拒清单 / 未达标清单（**不写库**）。

    - 只做 `scope='tenant'`（P2 明确不做 role）；
    - 同组已有 active ⇒ **拒绝**（否则晋升自己就造出两条矛盾卡）；
    - 排序按 id ⇒ 输出可复算。
    """
    minimum = int(
        min_employees
        if min_employees is not None
        else getattr(settings, "PLAYBOOK_PROMOTION_MIN_EMPLOYEES", 3)
    )
    active_keys = set(active_group_keys or ())
    promotions: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    below: List[Dict[str, Any]] = []
    for card in sorted(
        (c for c in drafts or [] if isinstance(c, dict) and c.get("state") == STATE_DRAFT),
        key=lambda c: str(c.get("id") or ""),
    ):
        if card.get("scope") != identity.SCOPE_TENANT:
            blocked.append({"id": card.get("id"), "reason": "scope_not_tenant"})
            continue
        trigger = card.get("trigger")
        if not is_executable(trigger):
            blocked.append({"id": card.get("id"), "reason": "trigger_not_executable"})
            continue
        key = identity.playbook_key(trigger, card.get("scope"), card.get("scope_role"))
        value = identity.value_key(trigger, card.get("correct") or "", card.get("scope"), card.get("scope_role"))
        employees = int((counts or {}).get((key, value), 0))
        entry = {"id": card.get("id"), "employees": employees, "playbook_key": key, "value_key": value}
        if employees < minimum:
            below.append({**entry, "reason": "below_threshold"})
            continue
        if key in active_keys:
            blocked.append({**entry, "reason": "conflict_active"})
            continue
        promotions.append({**entry, "reason": f"{employees} 个不同员工复现（阈值 {minimum}）"})
    return {
        "promotions": promotions,
        "blocked": blocked,
        "below_threshold": below,
        "min_employees": minimum,
    }


def promote_sweep(
    drafts: Optional[Iterable[Dict[str, Any]]],
    counts: Optional[Dict[Any, int]],
    active_group_keys: Optional[Iterable[str]],
    db: Any = None,
    tenant_id: Optional[int] = None,
) -> Dict[str, Any]:
    """晋升扫描（**只判不写**）：默认关；开启前 dry-run 先看清单。"""
    if not bool(getattr(settings, "PLAYBOOK_PROMOTION_ENABLED", False)):
        return {
            "enabled": False,
            "judged": False,
            "reason": "PLAYBOOK_PROMOTION_ENABLED=false（默认关：不绕过人工审核）",
            "promotions": [],
            "blocked": [],
        }
    plan = plan_promotions(drafts, counts, active_group_keys)
    return {"enabled": True, "judged": True, **plan}


async def apply_promotions(db: Any, tenant_id: int, promotions: List[Dict[str, Any]]) -> int:
    """逐条 CAS 晋升（`state='draft'` 写进 WHERE）。"""
    from sqlalchemy import text

    promoted = 0
    for promotion in promotions:
        result = await db.execute(
            text(_PROMOTE_SQL),
            {
                "id": promotion["id"],
                "tenant_id": int(tenant_id),
                "reason": promotion["reason"],
            },
        )
        if getattr(result, "rowcount", 0):
            promoted += 1
    return promoted


# ── 一次性扫描（CLI 承载）───────────────────────────────────────────────────


def _row_card(row: Dict[str, Any]) -> Dict[str, Any]:
    """库行 → 判定用的卡（解析 JSON；解析失败 ⇒ trigger=None ⇒ 各判定 fail-closed）。"""
    import json

    def _parse(raw):
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return None
        return None

    return {
        "id": row.get("id"),
        "tenant_id": row.get("tenant_id"),
        "scope": row.get("scope"),
        "scope_role": row.get("scope_role"),
        "trigger": _parse(row.get("trigger_json")),
        "correct": row.get("correct_text"),
        "hits": row.get("hits"),
        "state": row.get("state"),
        "conflict_key": row.get("conflict_key"),
        "activated_at": row.get("activated_at"),
        "created_at": row.get("created_at"),
        "last_hit_at": row.get("last_hit_at"),
    }


async def _load_cards(db: Any, sql: str, tenant_id: int) -> List[Dict[str, Any]]:
    """同步假会话 / 异步真会话都能跑的最小读法（CLI 与判据共用一条路径）。"""
    from sqlalchemy import text

    result = await _maybe_await(db.execute(text(sql), {"tenant_id": int(tenant_id)}))
    rows = getattr(result, "fetchall", lambda: [])() or []
    cards: List[Dict[str, Any]] = []
    for row in rows:
        mapping = getattr(row, "_mapping", None) or row
        cards.append(dict(mapping))
    return cards


async def run_lifecycle(db: Any, tenant_id: int, apply: bool = False, now: Any = None) -> Dict[str, Any]:
    """读一次租户面 → 分别判退役/晋升 →（可选）写。返回**读数**（零动作也要出声）。"""
    active_cards = [_row_card(row) for row in await _load_cards(db, _ACTIVE_CARDS_SQL, tenant_id)]
    draft_cards = [_row_card(row) for row in await _load_cards(db, _DRAFT_CARDS_SQL, tenant_id)]

    retire = retire_sweep(cards=active_cards, now=now)

    from sqlalchemy import text

    count_result = await _maybe_await(
        db.execute(text(_REPRODUCTION_COUNT_SQL), {"tenant_id": int(tenant_id)})
    )
    counts: Dict[Any, int] = {}
    for row in (getattr(count_result, "fetchall", lambda: [])() or []):
        mapping = getattr(row, "_mapping", None) or row
        item = dict(mapping)
        counts[(item.get("playbook_key"), item.get("value_key"))] = int(item.get("employees") or 0)

    active_keys = {
        identity.playbook_key(
            card.get("trigger"),
            card.get("scope") or identity.SCOPE_TENANT,
            card.get("scope_role"),
        )
        for card in active_cards
        if card.get("trigger") is not None
    }
    promote = promote_sweep(draft_cards, counts, active_keys)

    if apply:
        retired = await apply_retirements(db, tenant_id, retire.get("verdicts") or [])
        promoted = await apply_promotions(db, tenant_id, promote.get("promotions") or [])
        retire["retired"] = retired
        promote["promoted"] = promoted
        if retired or promoted:
            logger.info(
                f"[playbook-lifecycle] applied | tenant={tenant_id} retired={retired} promoted={promoted}"
            )
    return {
        "tenant_id": int(tenant_id),
        "applied": bool(apply),
        "active_cards": len(active_cards),
        "draft_cards": len(draft_cards),
        "retire": retire,
        "promote": promote,
    }


async def _maybe_await(value: Any) -> Any:
    """兼容同步假会话（判据）与异步真会话（CLI）：是 awaitable 就 await。"""
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


def main(argv: Optional[List[str]] = None) -> int:
    """`python -m app.playbook.lifecycle --tenant-id N [--apply]`（默认 dry-run）。

    退出码：`0` = 跑完（含「开关关着 ⇒ 0 动作」的显式读数）；
    `3` = **不可判定**（某档已开启但缺前置数据，如命中追踪关闭）。
    """
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser(description="口径卡生命周期扫描（默认 dry-run，不写库）")
    parser.add_argument("--tenant-id", dest="tenant_id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="真的写库（退役/晋升默认都关）")
    args = parser.parse_args(argv)

    async def _run() -> Dict[str, Any]:
        from app.utils.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await run_lifecycle(db, args.tenant_id, apply=args.apply)

    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["retire"].get("enabled") and not result["retire"].get("judged"):
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover — 命令行入口
    raise SystemExit(main())
