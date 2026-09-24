"""具名跨域视图 · `customer_profile`（客户画像）—— issue #5456（族 3 · 包 3）

判据来源：issue #5456（族 3「按需消费」，设计文档 §三 族 3）。本模块是**视图语义**的唯一判据源：
给一份**跨域内核快照**（与族 1 主动发现、族 3 包 2 同一形状 —— 同一内核、两种消费形态），产出
确定性的客户级视图行 + **逐字段接线状态**。它不取数、不联网、不读挂钟。

## 三条纪律（逐条落在代码里）

1. **逐字段三态**（复用族 3 内核的纪律，见 `app/briefing/proactive.py::proactive_status`）：
   每个字段是 `wired` / `not_wired` / `incomplete`（+ `reason`），不变式 **`reason is None` ⟺ `wired`**。
   ⇒ 调用方只要看这一条，就知道「空」能不能读成「没问题」。

2. 🔴 **「未知」与「0」不混**（#5369 立的口径）：
   · 声明**无真值**的字段 ⇒ 一律 `null`（**未知**），**不得**回填 `0` / DB 列默认值 / 建档种子常量
     —— 口径照抄 `product_skus.avg_cost` 的「`NULL` = 未知（一律不回填、不猜 0）」；
   · 有真值的字段**照实返回**（值就是 `0` / 空 的照原样保留 —— 那是一个**真结论**，与「未知」是两回事）；
   · 两者在输出上**可分**：每行的值域里「未知」只可能是 `null`，而字段侧另有
     `fields[字段].truth`（`has_truth` / `no_truth`）+ `status` 说明它为什么是 `null`。

3. **口径同源（真值判断只有一份，本模块不持有）**：
   哪些字段有真值是 #5362 的**声明**（`FieldTruthRegistry`）判定的，装配层把它**现取**后随快照运输
   （`field_truth`），本模块**只按运输来的声明分类** ⇒ 因此本文件里**不出现任何被声明字段的名字**
   （自带清单 = 第二份真值判断，正是本单要治的形态）。判据 =
   `tests/test_briefing_customer_profile.py::TestFieldLedgerIsNotOwnedByTheView`
   （含**类级元守卫**：`app/briefing/**` 任一模块自带字段台账 ⇒ 未登记即红，台账只许缩短）。

## 快照契约（本视图消费的部分）

```python
{
  "row_fields": {"customer_profiles": ["<字段名>", …]},   # 装配层自描述：本次真的产出了哪些字段
  "row_meta":   {"customer_profiles": {"limit": 51, "count": 50, "truncated": true}},
  "field_truth": {"customer_profiles": {"<字段名>": {"truth": "has_truth"|"no_truth", "reason": "…"}}},
  "customer_profiles": [{"<字段名>": <值>, …}, …],        # **有界** + 租户隔离（关口在装配层）
}
```

🔴 **声明的运输是「没带就 fail-closed」**：快照没有 `field_truth` ⇒ 本视图**一个字段都不产出**
（`declaration.status = not_wired` + 原因）—— 没有真值判断依据时，「照实返回」与「不猜」都无从谈起。

## 有界与租户

`limit`（默认 `MAX_VIEW_ROWS`）是有界的硬前提；**输出被截断时每个「有真值」字段都落 `incomplete`**
（有界不许变成静默少报）。租户由调用方传入并原样回显（**不由行数据反推**）—— 隔离的关口在装配层
（每条查询带租户），视图不承担取数，也不提供绕过通道。

## 行序

行序 = **装配层 SQL 的口径**（新建倒序 ⇒ 截断取「最该看的那一头」，与客户列表页同序）；
本视图**不改行序**（同一快照 ⇒ 逐字相同输出；字段状态与计数都与行序无关）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 内核读取器与三态词表（声明优先 / 截断显式 / 行数组容错）—— 复用，不复制第二份（族 3 内核纪律）
from app.briefing.proactive import (
    INCOMPLETE,
    NOT_WIRED,
    WIRED,
    _declared_fields,
    _row_meta,
    _rows,
)

__all__ = [
    "ARRAY",
    "HAS_TRUTH",
    "MAX_VIEW_ROWS",
    "NO_TRUTH",
    "TRUTH_KEY",
    "VIEW_ID",
    "customer_profile",
    "declaration_of",
    "declaration_status",
    "field_status",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "customer_profile"

#: 本视图消费的行数组（= 客户档案表名；装配层自描述与真值声明都以它为准）
ARRAY = "customer_profiles"

#: 真值声明的运输键（装配层现取 #5362 注册表后放在快照的这个键下）
TRUTH_KEY = "field_truth"

#: 声明词汇（与 `FieldTruth` 的两侧逐字对应 —— 中文口径见字段的 `reason`）
HAS_TRUTH = "has_truth"
NO_TRUTH = "no_truth"

#: 视图输出上限（有界是热路径的硬前提）。行含客户联系方式等 PII 且列宽 ⇒ 默认取小值；
#: 截断**显式**（`truncated` + 逐字段 `incomplete`），并由工具消息点出真实条数。
MAX_VIEW_ROWS = 50


# ── 声明运输的读取（fail-closed：不认识就不猜）────────────────────────────────


def declaration_of(snapshot: Any) -> Optional[Dict[str, Dict[str, str]]]:
    """运输到快照里的真值声明：`{字段: {"truth": …, "reason": …}}`。

    缺省 / 形态不认识 ⇒ `None`（**fail-closed**）—— 没有依据时不许退化成「都当有真值」
    （那会把 DB 默认值当成真值下发），也不许退化成「都当无真值」（那会把真值抹成 null）。
    """
    if not isinstance(snapshot, dict):
        return None
    block = snapshot.get(TRUTH_KEY)
    entries = block.get(ARRAY) if isinstance(block, dict) else None
    if not isinstance(entries, dict) or not entries:
        return None
    out: Dict[str, Dict[str, str]] = {}
    for field, entry in entries.items():
        if not isinstance(entry, dict) or entry.get("truth") not in (HAS_TRUTH, NO_TRUTH):
            return None
        out[str(field)] = {
            "truth": str(entry["truth"]),
            "reason": str(entry.get("reason") or "").strip(),
        }
    return out


def declaration_status(snapshot: Any) -> Dict[str, Any]:
    """声明本身的状态（+ 原因）—— 不变式同内核：**`reason is None` ⟺ `wired`**。"""
    truth = declaration_of(snapshot)
    if truth is None:
        return {
            "status": NOT_WIRED,
            "reason": (
                f"快照未携带 {TRUTH_KEY}.{ARRAY} 真值声明（装配层现取 #5362 的注册表后运输）"
                "⇒ 没有真值判断依据，本视图不产出任何字段（fail-closed：不猜哪些字段可信）"
            ),
            "fields_total": 0,
            "has_truth_count": 0,
            "no_truth_count": 0,
        }
    return {
        "status": WIRED,
        "reason": None,
        "fields_total": len(truth),
        "has_truth_count": sum(1 for entry in truth.values() if entry["truth"] == HAS_TRUTH),
        "no_truth_count": sum(1 for entry in truth.values() if entry["truth"] == NO_TRUTH),
    }


def _status(status: str, reason: Optional[str], missing: List[str], gaps: List[str],
            truth: str) -> Dict[str, Any]:
    return {"status": status, "reason": reason, "missing": missing, "gaps": gaps, "truth": truth}


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #5456 判据 1）。

    返回 `{字段: {"status", "reason", "missing", "gaps", "truth"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（**声明无真值** ⇒ 本视图不产出该字段，
    或装配层未接线）, `incomplete`（已接线但**本次不完整**）}；
    不变式：**`reason is None` ⟺ `status == wired`**。

    纯函数、只读：同一 `snapshot` ⇒ 同一结果（与视图行互不影响 —— 状态不改判据、不改行）。
    """
    truth = declaration_of(snapshot)
    if truth is None:
        return {}
    declared = _declared_fields(snapshot, ARRAY)
    meta = _row_meta(snapshot, ARRAY)
    rows = _rows(snapshot, ARRAY)

    status: Dict[str, Dict[str, Any]] = {}
    for field in sorted(truth):
        entry = truth[field]
        if entry["truth"] == NO_TRUTH:
            # 🔴 无真值不是「本次缺数据」：它是**声明**的结果（证据化原因来自 #5362 的登记）
            status[field] = _status(NOT_WIRED, f"声明无真值：{entry['reason']}", [], [],
                                    entry["truth"])
            continue
        if declared is None:
            status[field] = _status(NOT_WIRED, f"快照未提供 {ARRAY} 行数组（装配层未接线）",
                                    [ARRAY], [], entry["truth"])
            continue
        if field not in declared:
            status[field] = _status(NOT_WIRED, f"快照 {ARRAY} 行缺字段 {field}（数据层无此来源）",
                                    [field], [], entry["truth"])
            continue
        gaps: List[str] = []
        if meta.get("truncated"):
            gaps.append(
                f"{ARRAY} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
                f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
            )
        absent = sum(1 for row in rows if field not in row)
        if absent:
            gaps.append(f"{absent} 行整行缺 {field} 键（装配 / 序列化漂移）⇒ 结论不完整")
        status[field] = _status(INCOMPLETE if gaps else WIRED,
                                "；".join(gaps) if gaps else None, [], gaps, entry["truth"])
    return status


# ── 视图行 ──────────────────────────────────────────────────────────────────


def _cell(field: str, entry: Dict[str, Any], raw: Dict[str, Any]) -> Any:
    """🔴 「未知」与「真值」的**唯一接缝**：声明无真值 ⇒ `None`（**不得**回填 0 / 默认值）。

    注入式红证（`test_zero_filling_injection_turns_the_unknown_assertion_red`）就是把本函数换成
    「无真值当 0」的版本，同一断言必须变红；反向的「整表一刀切」注入
    （`test_blanket_nulling_injection_turns_the_preservation_assertion_red`）要求有真值的字段**保留**。
    """
    if entry["truth"] == NO_TRUTH:
        return None
    return raw.get(field)


def customer_profile(snapshot: Any, *, tenant_id: Any,
                     limit: int = MAX_VIEW_ROWS) -> Dict[str, Any]:
    """产出 `customer_profile` 视图（按需消费）—— 纯函数、确定性、有界。

    Args:
        snapshot: 跨域内核快照（契约见模块 docstring）
        tenant_id: 调用方所在租户（原样回显；隔离关口在装配层）
        limit: 输出行数上限（≥1；截断时逐字段落 `incomplete`）

    Returns:
        `{"view", "tenant_id", "declaration", "fields", "rows", "row_meta", "count",
          "rows_total", "truncated", "no_truth_fields", "has_truth_fields", "basis"}`
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 ≥1 的整数，实得 {limit!r}")

    truth = declaration_of(snapshot)
    fields = field_status(snapshot)
    rows: List[Dict[str, Any]] = []
    if truth is not None:
        names = sorted(truth)
        for raw in _rows(snapshot, ARRAY):
            rows.append({field: _cell(field, truth[field], raw) for field in names})

    total = len(rows)
    truncated = total > limit
    if truncated:
        rows = rows[:limit]
        # 🔴 有界不许变成静默少报：输出被截断 ⇒ 每个「有真值」字段的结论都不完整（带可归因读数）
        for name, entry in fields.items():
            if entry["truth"] != HAS_TRUTH:
                continue
            entry["gaps"] = list(entry["gaps"]) + [
                f"视图输出被上限截断（上限 {limit} 行，本次给出 {len(rows)} 行，共 {total} 行）"
                "⇒ 结论不完整"
            ]
            entry["status"] = INCOMPLETE
            entry["reason"] = "；".join(entry["gaps"])

    meta = _row_meta(snapshot, ARRAY)
    return {
        "view": VIEW_ID,
        "tenant_id": tenant_id,
        "declaration": declaration_status(snapshot),
        "fields": fields,
        "rows": rows,
        "row_meta": dict(meta),
        "count": len(rows),
        "rows_total": total,
        "truncated": truncated,
        "no_truth_fields": sorted(f for f, e in (truth or {}).items() if e["truth"] == NO_TRUTH),
        "has_truth_fields": sorted(f for f, e in (truth or {}).items() if e["truth"] == HAS_TRUTH),
        "basis": {
            "array": ARRAY,
            "truth_source": (
                f"快照 {TRUTH_KEY}.{ARRAY}（装配层由 #5362 的 FieldTruthRegistry **现取**；"
                "本视图不持有第二份真值判断）"
            ),
            "row_order": "装配层 SQL 口径（新建倒序，截断取最该看的那一头）—— 视图不改行序",
        },
    }