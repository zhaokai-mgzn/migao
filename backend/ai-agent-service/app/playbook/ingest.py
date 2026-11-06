"""口径卡蒸馏的**落库面**（issue #8175 P1）：候选 → `draft` 卡 → 人工审核。

## 这一层补的是 P1a 之后断掉的那一截

`scripts/distill_agent_sessions.py`（P1a，PR #8199）已经把「从 B 端 `mibao` 会话里挑出
纠正 / 口径 / 例外」做完，但产物是**一份 JSON**（`trigger_text` / `category` / `confidence`），
**不是** `playbooks` 行：字段对不上、状态没有、来源没落、冲突没处理。
⇒ 候选到审核队列之间原本断了一截 —— 人得把每条候选手工抄进 `POST /api/admin/playbooks`。

本模块补的就是这一截，三件事，一件不多：

1. **形状转换**：`trigger_text` → 条件语言 `trigger`、`correct` = 原句、
   `source = {session_id, turn}`、`state = draft`；
2. **落库闸门**：`redact`（PII / 报价**整条拒绝**）+ `condition.validate`（自由文本不许入库）
   + 租户校验（候选跨租户 ⇒ 丢弃）；
3. **冲突不覆盖**：同 key（scope + trigger）不同值 ⇒ **两条并存**并各打 `conflict_key`；
   同 key 同值 ⇒ 幂等跳过。**任何分支都不写 `correct_text`**。

## 为什么 `state` 只能是 draft

审核门禁在读面（`app/playbook/prompt.py` 只放 `active`），写面这里再重申一次：
本模块的 INSERT **硬编码** `'draft'`，没有任何参数能改它 ——
「自动落库」与「自动生效」必须是两件事（判据 2 的正控就是冲着这条来的）。

## 关键词从哪来（为什么会**抽不出**关键词）

条件语言不收自由文本，`trigger` 必须落到一个**可判**的字段上。离线会话里唯一确定的结构化语境
是 `user_text`（读面 `_context_from_state` 从本轮最后一条用户消息取它）。
关键词 = 去掉触发词与虚词后**最长的中文连续片段**（≤8 字，且必须先出现在原句里）；
抽不出来 ⇒ **不产卡**（fail-closed：一张永远不触发的卡比没有卡更糟 ——
它占着审核队列、看起来像能力，却永远不会生效）。

## 「例外」为什么不自动变反例

P1a 的 `例外` 类候选是**独立一句**（「除非客户要零裁」）。把它塞进上一条卡的 `counter`
会得到「trigger 与 counter 都用 `user_text`」的结构 ⇒ 出口③ 的语境采样要求
「触发成立**且**反例命中」，同一个字段无法同时取两个值 ⇒ 生成器会直接拒（见
`app/playbook/casegen.py::_require_counter_context`）。宁可不给反例，也不生成一张
**出口③永远生成不出用例**的卡。重启条件见 PR body（需要 intent / 场景维度进条件语境）。
"""

import json
import re
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from app.playbook import condition, identity, redact

SCHEMA_VERSION = 1

STATE_DRAFT = "draft"
#: 口径卡一期只做全企业范围（`role` 属 P2）
SCOPE_TENANT = "tenant"

#: P1a 产物里可以变成卡的类别（`例外` 需要父卡，P1 不自动配对，见模块 docstring）
CARD_CATEGORIES = ("纠正", "口径")

#: 落库闸门的跳过原因（固定集合 ⇒ 统计可逐字节复算）
SKIP_REASONS = (
    "not_a_card_category",
    "missing_source",
    "tenant_mismatch",
    "invalid_trigger",
    "pii_or_price",
    "no_keyword",
    "duplicate",
    "invalid_candidate",
)

#: 触发词（P1a 的规则词）与虚词：算关键词前先从原句里摘掉
_TRIGGER_WORDS = (
    "不对",
    "不是这样",
    "不是",
    "错了",
    "应该是",
    "我们按",
    "我们家",
    "记住",
    "以后都",
    "统一按",
    "一律",
    "除非",
    "特殊情况",
)
_STOP_WORDS = (
    "我们",
    "你们",
    "他们",
    "客户",
    "这个",
    "那个",
    "一下",
    "应该",
    "以后",
    "现在",
    "需要",
    "可以",
    "一个",
    "都",
    "要",
    "就",
    "的",
    "了",
    "是",
    "按",
    "用",
    "走",
    "算",
    "来",
    "做",
    "给",
    "把",
    "和",
    "跟",
    "对",
    "这",
    "那",
    "个",
    "吗",
    "呢",
    "吧",
    "啊",
    "下",
    "上",
    "里",
    "外",
    "时",
    "候",
)
#: 引号里的词优先级最高（人已经把「这条口径叫什么」说清楚了）
_QUOTED = re.compile(r"[「『“\"]([^」』”\"]{2,12})[」』”\"]")
_CJK_RUN = re.compile(r"[\u4e00-\u9fa5]{2,}")

#: 关键词长度上限（太长就变成一句话，`contains` 永远不命中）
MAX_KEYWORD_CHARS = 8
#: 正解长度上限（与读面 `MAX_CORRECT_CHARS` 同口径：入库就截断，别等渲染时才发现）
MAX_CORRECT_CHARS = 200

_INSERT_SQL = """
INSERT INTO playbooks (
    id, tenant_id, scope, scope_role, trigger_json, correct_text, counter_json,
    source_session_id, source_turn, hits, state, conflict_key
) VALUES (
    :id, :tenant_id, :scope, :scope_role, :trigger_json, :correct_text, NULL,
    :source_session_id, :source_turn, 0, 'draft', :conflict_key
)
"""

#: 只写**冲突标记**这一个列：口径正文一次都不许被「后来者」覆盖
_MARK_CONFLICT_SQL = """
UPDATE playbooks
SET conflict_key = :conflict_key, updated_at = NOW()
WHERE id = :id AND tenant_id = :tenant_id AND conflict_key IS DISTINCT FROM :conflict_key
"""

_SELECT_EXISTING_SQL = """
SELECT id, trigger_json, correct_text, state
FROM playbooks
WHERE tenant_id = :tenant_id AND state IN ('draft', 'active')
"""

#: 会话 → 员工（P2 晋升的数据面）：`sessions.customer_id` → `users.id`。
#: **排除 C 端身份**（`role IN ('customer','agent')`）—— 少这个过滤，C 端顾客会被算成
#: 「第 N 个员工」，晋升就是假的。查不到就查不到（fail-closed），绝不猜。
_SELECT_EMPLOYEE_SQL = """
SELECT s.id AS session_id, s.customer_id AS employee_id
FROM sessions s
JOIN users u ON u.id = s.customer_id AND u.tenant_id = s.tenant_id
WHERE s.tenant_id = :tenant_id
  AND s.id IN :session_ids
  AND COALESCE(s.deleted, 0) = 0
  AND u.deleted = 0
  AND u.role IS NOT NULL
  AND u.role NOT IN ('customer', 'agent')
"""

#: 复现证据：一个员工对同一个 `(key, value)` 只记一条（唯一索引兜底 ⇒ 重跑幂等）
_INSERT_REPRODUCTION_SQL = """
INSERT INTO playbook_reproductions (
    tenant_id, playbook_key, value_key, employee_id, session_id, created_at
) VALUES (
    :tenant_id, :playbook_key, :value_key, :employee_id, :session_id, NOW()
)
ON CONFLICT (tenant_id, playbook_key, value_key, employee_id) DO NOTHING
"""


# ── 关键词 ──────────────────────────────────────────────────────────────────


def _strip_tokens(text: str) -> str:
    """摘掉触发词与虚词（长词优先，避免「不对」被「不」拆坏）。"""
    out = text
    for token in sorted(_TRIGGER_WORDS + _STOP_WORDS, key=len, reverse=True):
        out = out.replace(token, " ")
    return out


def extract_keyword(text: str) -> str:
    """原句 → 可做 `contains` 的关键词（空串 = 抽不出，调用方据此**不产卡**）。"""
    if not isinstance(text, str) or not text.strip():
        return ""
    quoted = _QUOTED.search(text)
    if quoted:
        return quoted.group(1)[:MAX_KEYWORD_CHARS]
    runs = _CJK_RUN.findall(_strip_tokens(text))
    if not runs:
        return ""
    keyword = max(runs, key=len)[:MAX_KEYWORD_CHARS]
    # 兜底自证：关键词必须真的出现在原句里（否则做出来的条件永远不命中）
    return keyword if keyword and keyword in text else ""


def build_trigger(keyword: str) -> Dict[str, Any]:
    """关键词 → 条件语言（`user_text contains`）。"""
    return {"field": "user_text", "op": "contains", "value": keyword}


def _canonical(value: Any) -> str:
    return identity.canonical(value)


def playbook_key(trigger: Any, scope: str = SCOPE_TENANT, scope_role: Optional[str] = None) -> str:
    """同一条口径的**身份**（唯一实现 = `app/playbook/identity.py`）。`correct` 是「值」，不参与。"""
    return identity.playbook_key(trigger, scope, scope_role)


def value_key(
    trigger: Any, correct: Any, scope: str = SCOPE_TENANT, scope_role: Optional[str] = None
) -> str:
    """同一身份下的**同一个说法**：晋升计数按 `(key, value)` 分组（不同说法不合并计数）。"""
    return identity.value_key(trigger, correct, scope, scope_role)


def card_id(tenant_id: int, session_id: str, turn: Any, key: str) -> str:
    """确定性主键：同一输入连跑两次得到同一个 id ⇒ 重跑不会造出第二条一样的卡。"""
    raw = f"{tenant_id}|{session_id}|{turn}|{key}"
    return "pb_" + sha1(raw.encode("utf-8")).hexdigest()[:24]


# ── 候选 → 卡 ───────────────────────────────────────────────────────────────


def _clean_text(text: str) -> str:
    """去控制字符 + 折叠空白（消毒在渲染面另有一次，这里是入库前的最小收敛）。"""
    printable = "".join(ch for ch in str(text) if ch.isprintable())
    return re.sub(r"\s+", " ", printable).strip()[:MAX_CORRECT_CHARS]


def candidate_to_card(candidate: Any, tenant_id: int) -> Tuple[Optional[Dict[str, Any]], str]:
    """单条 P1a 候选 → 待插入的 `draft` 行（或 `(None, 跳过原因)`）。"""
    if not isinstance(candidate, dict):
        return None, "invalid_candidate"
    if candidate.get("category") not in CARD_CATEGORIES:
        # `例外` 需要父卡做反例，P1 不自动配对（见模块 docstring）
        return None, "not_a_card_category"
    session_id = str(candidate.get("session_id") or "").strip()
    turn = candidate.get("turn")
    if not session_id or turn is None:
        return None, "missing_source"
    try:
        candidate_tenant = int(candidate.get("tenant_id"))
    except (TypeError, ValueError):
        return None, "invalid_candidate"
    if candidate_tenant != int(tenant_id):
        # 跨租户口径 = 把别家的经营规则灌进本家 prompt，宁可不落
        return None, "tenant_mismatch"

    correct = _clean_text(candidate.get("trigger_text") or "")
    if not correct:
        return None, "invalid_candidate"
    hit = redact.problems(correct)
    if hit:
        return None, "pii_or_price"

    keyword = extract_keyword(correct)
    if not keyword:
        return None, "no_keyword"
    trigger = build_trigger(keyword)
    if condition.validate(trigger):
        # 双保险：关键词本身可能把条件写成非法形态（例如空串），写面一律不许进
        return None, "invalid_trigger"

    key = playbook_key(trigger)
    return (
        {
            "id": card_id(tenant_id, session_id, turn, key),
            "tenant_id": int(tenant_id),
            "scope": SCOPE_TENANT,
            "scope_role": None,
            "trigger_json": _canonical(trigger),
            "correct_text": correct,
            "counter_json": None,
            "source_session_id": session_id,
            "source_turn": int(turn),
            # 写死 draft：本模块**没有**任何参数能直接落 active
            "state": STATE_DRAFT,
            "conflict_key": None,
            "_key": key,
            "_value_key": value_key(trigger, correct),
        },
        "",
    )


# ── 计划（纯函数：给定候选与既有行，算出要插什么、要标什么）──────────────


def _parse_trigger(raw: Any) -> Optional[Any]:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _existing_by_key(existing: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        trigger = _parse_trigger(row.get("trigger_json"))
        if trigger is None:
            continue
        grouped.setdefault(playbook_key(trigger), []).append(row)
    return grouped


def plan_ingest(
    candidates: Optional[Iterable[Any]],
    existing: Optional[Iterable[Dict[str, Any]]],
    tenant_id: int,
) -> Dict[str, Any]:
    """候选 + 库内既有行 → `{rows, skips, conflict_updates, conflicts}`（无 I/O）。"""
    rows: List[Dict[str, Any]] = []
    skips: List[Dict[str, Any]] = []
    conflict_updates: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    reproductions: List[Dict[str, Any]] = []
    by_existing = _existing_by_key(existing)
    by_batch: Dict[str, List[Dict[str, Any]]] = {}

    for index, candidate in enumerate(candidates or []):
        card, reason = candidate_to_card(candidate, tenant_id)
        source = {
            "index": index,
            "session_id": (candidate or {}).get("session_id") if isinstance(candidate, dict) else None,
            "turn": (candidate or {}).get("turn") if isinstance(candidate, dict) else None,
        }
        if card is None:
            skips.append({**source, "reason": reason})
            continue

        key = card["_key"]
        siblings = list(by_existing.get(key, [])) + list(by_batch.get(key, []))
        if any(str(s.get("correct_text")) == card["correct_text"] for s in siblings):
            # 同 key 同值 ⇒ 幂等跳过（重跑 / 同一口径被两次会话说到）。
            # ⚠️ 卡片不新增，但**复现证据要记**：晋升判的是「几个不同员工说过同一件事」，
            # 不是「落了几张卡」—— P1 的幂等跳过的正是后来者的证据，不记就永远晋升不了。
            skips.append({**source, "reason": "duplicate"})
            reproductions.append(_reproduction_entry(card))
            continue
        if siblings:
            # 同 key **不同**值 ⇒ 两条并存，并各打冲突标记（**不是**覆盖）
            card["conflict_key"] = key
            for sibling in siblings:
                if sibling.get("_batch"):
                    sibling["conflict_key"] = key
                else:
                    conflict_updates.append(
                        {"id": sibling.get("id"), "tenant_id": int(tenant_id), "conflict_key": key}
                    )
            conflicts.append({"key": key, "correct": card["correct_text"]})
        card["_batch"] = True
        by_batch.setdefault(key, []).append(card)
        rows.append(card)
        reproductions.append(_reproduction_entry(card))

    # `_key` / `_batch` 是计划内部字段：出库给 SQL 前要摘掉
    cleaned_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    return {
        "rows": cleaned_rows,
        "skips": skips,
        "conflict_updates": conflict_updates,
        "conflicts": conflicts,
        # 复现证据（会话 → 员工在落库时才解析；这里只带出处与身份）
        "reproductions": reproductions,
        "skip_counts": {reason: sum(1 for s in skips if s["reason"] == reason) for reason in SKIP_REASONS},
    }


def _reproduction_entry(card: Dict[str, Any]) -> Dict[str, Any]:
    """一条卡 → 一条复现证据（员工 id 由 `resolve_employees` 另查）。"""
    return {
        "session_id": card["source_session_id"],
        "turn": card["source_turn"],
        "playbook_key": card["_key"],
        "value_key": card["_value_key"],
    }


# ── 落库 ────────────────────────────────────────────────────────────────────


async def _get_session(db: Any) -> Any:
    if db is not None:
        return db
    from app.utils.database import AsyncSessionLocal

    return AsyncSessionLocal()


async def load_existing(db: Any, tenant_id: int) -> List[Dict[str, Any]]:
    """读本租户**未退役**的卡（draft + active）—— 冲突判定的参照面。"""
    from sqlalchemy import text

    result = await db.execute(text(_SELECT_EXISTING_SQL), {"tenant_id": int(tenant_id)})
    return [dict(row._mapping) for row in result.fetchall()]


async def resolve_employees(
    db: Any, tenant_id: int, session_ids: Iterable[Any]
) -> Dict[str, str]:
    """`{session_id: employee_id}`（查不到 = 不在字典里，调用方据此 fail-closed）。

    这条链路是 P2 晋升的**数据面**：`sessions.customer_id` → `users.id`，排除 C 端身份。
    它只回答「这轮是谁在跟黄金策说话」，不猜身份（`role` 为 NULL 的账号一律不算员工）。
    """
    ids = [str(session_id) for session_id in (session_ids or []) if session_id]
    if not ids:
        return {}
    from sqlalchemy import bindparam, text

    stmt = text(_SELECT_EMPLOYEE_SQL).bindparams(bindparam("session_ids", expanding=True))
    result = await db.execute(stmt, {"tenant_id": int(tenant_id), "session_ids": ids})
    employees: Dict[str, str] = {}
    for row in result.fetchall():
        mapping = getattr(row, "_mapping", None) or row
        item = dict(mapping)
        employee_id = item.get("employee_id")
        if employee_id:
            employees[str(item.get("session_id"))] = str(employee_id)
    return employees


async def apply_reproductions(
    db: Any, tenant_id: int, reproductions: List[Dict[str, Any]]
) -> int:
    """写复现证据（唯一索引兜底幂等：同一员工对同一口径重复出现只记一条）。"""
    from sqlalchemy import text

    written = 0
    for entry in reproductions:
        await db.execute(
            text(_INSERT_REPRODUCTION_SQL),
            {
                "tenant_id": int(tenant_id),
                "playbook_key": entry["playbook_key"],
                "value_key": entry["value_key"],
                "employee_id": entry["employee_id"],
                "session_id": entry["session_id"],
            },
        )
        written += 1
    if written:
        await db.commit()
    return written


async def apply_plan(db: Any, plan: Dict[str, Any]) -> Dict[str, int]:
    """执行计划：先插新卡（全是 draft），再补冲突标记（只写 `conflict_key`）。"""
    from sqlalchemy import text

    inserted = 0
    for row in plan.get("rows") or []:
        await db.execute(text(_INSERT_SQL), row)
        inserted += 1
    marked = 0
    for update in plan.get("conflict_updates") or []:
        await db.execute(text(_MARK_CONFLICT_SQL), update)
        marked += 1
    if inserted or marked:
        await db.commit()
    return {"inserted": inserted, "marked": marked}


async def ingest(db: Any, candidates: Iterable[Any], tenant_id: int, apply: bool = False) -> Dict[str, Any]:
    """候选 → 计划 →（可选）落库。`apply=False` 时**一个字节都不写**。"""
    tenant = int(tenant_id)
    existing = await load_existing(db, tenant)
    plan = plan_ingest(candidates, existing, tenant)
    reproductions = list(plan.get("reproductions") or [])
    # 员工解析在 dry-run 里也做（只读 SELECT）：这样「哪几条晋升证据缺失」在写之前就看得见
    employees = await resolve_employees(
        db, tenant, [entry["session_id"] for entry in reproductions]
    )
    known = [
        {**entry, "employee_id": employees[str(entry["session_id"])]}
        for entry in reproductions
        if str(entry["session_id"]) in employees
    ]
    result = {
        "tenant_id": tenant,
        "planned": len(plan["rows"]),
        "skipped": len(plan["skips"]),
        "conflicts": len(plan["conflicts"]),
        "conflict_updates": len(plan["conflict_updates"]),
        "skip_counts": plan["skip_counts"],
        "applied": bool(apply),
        "inserted": 0,
        "marked": 0,
        # 复现证据：planned = 过了闸门的候选数；recorded = 真写进库的条数
        "reproductions_planned": len(reproductions),
        "reproductions_recorded": 0,
        "unknown_employee": len(reproductions) - len(known),
        "rows": plan["rows"],
    }
    if apply and plan["rows"]:
        written = await apply_plan(db, plan)
        result.update(written)
        logger.info(
            f"[playbook-ingest] tenant={tenant} inserted={written['inserted']} "
            f"marked={written['marked']} skipped={result['skipped']} conflicts={result['conflicts']}"
        )
    if apply and known:
        recorded = await apply_reproductions(db, tenant, known)
        result["reproductions_recorded"] = recorded
        logger.info(
            f"[playbook-ingest] tenant={tenant} reproductions={recorded} "
            f"unknown_employee={result['unknown_employee']}"
        )
    return result


# ── 命令行（默认 dry-run；`--apply` 才写）────────────────────────────────────


def load_candidates(path: str) -> List[Any]:
    """读 P1a 的候选文件（`{"candidates": [...]}` 或裸数组）。坏输入 fail-closed。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise SystemExit(f"读不到候选文件 {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"候选文件不是合法 JSON {path}: {exc}")
    if isinstance(data, dict):
        data = data.get("candidates")
    if not isinstance(data, list):
        raise SystemExit(f"候选文件顶层必须是数组或 {{'candidates': [...]}}: {path}")
    return data


def _default_session_factory() -> Any:
    from app.utils.database import AsyncSessionLocal

    return AsyncSessionLocal()


async def _run(args: Any, session_factory: Any) -> Dict[str, Any]:
    candidates = load_candidates(args.input_path)
    async with session_factory() as db:
        return await ingest(db, candidates, args.tenant_id, apply=args.apply)


def main(argv: Optional[List[str]] = None, session_factory: Any = None) -> int:
    """`python3 -m app.playbook.ingest --in <candidates.json> --tenant-id N [--apply]`。"""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="把 P1a 的会话候选落成 draft 口径卡（默认 dry-run，不写库）。",
    )
    parser.add_argument("--in", dest="input_path", required=True, help="P1a 产出的候选 JSON")
    parser.add_argument("--tenant-id", dest="tenant_id", type=int, required=True, help="落库租户")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真的写库（只落 draft）；不给则只打印计划",
    )
    args = parser.parse_args(argv)
    result = asyncio.run(_run(args, session_factory or _default_session_factory))
    printable = {key: value for key, value in result.items() if key != "rows"}
    if not args.apply:
        printable["rows"] = result["rows"]
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover — 命令行入口
    raise SystemExit(main())
