"""具名跨域视图 · `delivery_risk`（生产交付风险）—— issue #6217（族 3 · 包 4 / V2）

判据来源：issue #6217（族 3「按需消费」）。本模块是**视图语义**的唯一判据源：给一份由两条
**既有只读端点**（`/api/admin/processing-orders` + `/api/admin/agent/production/progress`）装配的
快照，产出**确定性的**加工单级视图行（交期 + 工序进度 + 卡点，按交付风险分层排序）+
**逐字段接线状态**。它不取数、不联网、不读挂钟（`as_of` 由调用方传入）。

🔴 **为什么是「跨单聚合」**：生产页是**单任务视图**（一次一张加工单），结构上答不出
「哪些单快到交期还卡着工序」「卡在哪个工序最多」。本视图把**同一批**加工单放在一起做
确定性聚合（`stuck_top` = 按「卡在该工序的加工单数」降序），这正是具名跨域视图存在的理由。

## 三条纪律（逐条落在代码里）

1. **逐字段三态**（族 3 内核纪律，见 `app/briefing/proactive.py::proactive_status`）：
   每个字段是 `wired` / `not_wired` / `incomplete`（+ `reason`），不变式 **`reason is None` ⟺ `wired`**。
   `not_wired` 的两支**必须可分**：① **声明无真值**（既有端点里根本没有这个列 —— 具名说明）；
   ② **声明有真值但装配层没接线**（快照缺数组 / 缺字段）。
   ⚠️ 还有**第三支**：数组已接线但某一行**整行缺键**（`production_progress` 逐单取数时，
   少数单可能没取到）⇒ 该行相关字段落 `incomplete` + `progress_missing` 点名。

2. 🔴 **「未知」与「0」不混**：
   · 加工单**没有交期**（`expected_delivery_date` 为空）⇒ `days_to_deadline` / `overdue` /
     `risk_band` 一律 `null` / `unknown` + `deadline_basis="no_deadline"`，
     **不得**回填 `0`（「0 天后到期」= 今天到期，会把没填交期的单读成最紧急的一批）；
   · 工序进度**没取到**（该行整行缺 `pending_operations`）⇒ `pending_operations=None` +
     `unwired=['pending_operations']`，**不得**填 `[]`（空 = 「没有卡着的工序」，那是真结论）；
   · 有真值时 `0` 照实返回（真 0 道待完工序 / 真 0% 进度）；
   · 「到期日**未知**」与「到期日**已过**」在输出上可分（`risk_band` = `unknown` ≠ `overdue`）。

3. **口径同源（真值判断只有一份，本模块不持有第二份）**：
   `FIELD_SOURCES` 是**单点声明**（字段 → 权威行数组 + 该数组里必须存在的列）；工具层只做
   「按端点原样取行 + 归一化列名」，**不重写任何字段清单**；判据
   `tests/test_briefing_delivery_risk.py::TestSourceOfTruthIsSingle` 机械钉住这两条。

## 快照契约（本视图消费的部分）

```python
{
  "row_fields": {"processing_orders": ["processing_order_no", "status", …],
                 "production_progress": ["pending_operations", "current_operation", …]},
  "row_meta":   {"processing_orders": {"limit": 100, "count": 100, "truncated": false},
                 "production_progress": {"limit": 50, "count": 50, "truncated": true}},
  "processing_orders":  [{"processing_order_no", "order_no", "customer_name", "processor",
                          "expected_delivery_date", "status"}, …],   # **有界** + 租户隔离
  "production_progress": [{"order_no", "expected_delivery_date", "current_operation",
                           "pending_operations", "total_operations", "done_operations"}, …],
}
```

## 有界与租户

`limit`（默认 `MAX_VIEW_ROWS`）是有界的硬前提；**输出被截断时每个「有真值」字段都落
`incomplete`**（有界不许变成静默少报）。租户由调用方传入并原样回显（**不由行数据反推**）——
隔离的关口在装配层（每条查询带租户）。

## 行序

按**交付风险分层**（`overdue` → `critical` → `soon` → `safe` → `unknown`）再按「距今到期天数升序」，
同分层同天数按加工单号升序 ⇒ **同一快照逐字相同输出**（纯函数、与输入行序无关）。
🔴 本视图**改行序**：它的用途就是「哪些单最该先看」，不改序等于把问题原样丢给模型；
分层口径写在 `basis.risk_band` 里可复算。
"""

from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

# 内核读取器与三态词表（声明优先 / 截断显式 / 行数组容错）—— 复用，不复制第二份（族 3 内核纪律）
from app.briefing.proactive import (
    INCOMPLETE,
    NOT_WIRED,
    WIRED,
    _day,
    _declared_fields,
    _num,
    _row_meta,
    _rows,
)

__all__ = [
    "ARRAYS",
    "CRITICAL_DAYS",
    "MAX_VIEW_ROWS",
    "RISK_BANDS",
    "SOON_DAYS",
    "VIEW_ID",
    "field_status",
    "delivery_risk",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "delivery_risk"

#: 本视图消费的两个行数组（装配层自描述以它们为准）
ARRAYS: Tuple[str, ...] = ("processing_orders", "production_progress")

#: 视图输出上限（有界是热路径的硬前提）
MAX_VIEW_ROWS = 50

#: 交付风险分层（按紧急度降序 = 输出行序的**第一**排序键）：
#: `overdue` 已逾期 / `critical` 临近交期 / `soon` 接近交期 / `safe` 宽裕 /
#: `unknown` **交期未知**（未填交期 ⇒ 未知，**不是**「不紧急」）。
RISK_BANDS: Tuple[str, ...] = ("overdue", "critical", "soon", "safe", "unknown")

#: 分层阈值（天，`<=` 命中；口径进 `basis.risk_band` 可复算）
CRITICAL_DAYS = 3
SOON_DAYS = 7

#: 百分比输出精度（进度率）
_OUTPUT_QUANT = Decimal("0.0001")

#: 声明词汇（与内核其余视图的两侧逐字对应）
HAS_TRUTH = "has_truth"
NO_TRUTH = "no_truth"

#: **单点声明**：视图字段 → （权威行数组，该数组里必须存在的列）。工具层不得另写一份。
#: `stuck_operation` / `pending_operations` 的权威数组是 `production_progress`
#: —— 「卡点」只能来自逐单工序进度（加工单列表没有工序列）。
FIELD_SOURCES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "processing_order_no": ("processing_orders", ("processing_order_no",)),
    "order_no": ("processing_orders", ("order_no",)),
    "customer_name": ("processing_orders", ("customer_name",)),
    "processor": ("processing_orders", ("processor",)),
    "status": ("processing_orders", ("status",)),
    "expected_delivery_date": ("processing_orders",
                               ("processing_order_no", "expected_delivery_date")),
    "days_to_deadline": ("production_progress", ("order_no", "expected_delivery_date")),
    "stuck_operation": ("production_progress",
                        ("order_no", "current_operation", "pending_operations")),
    "pending_operations": ("production_progress",
                           ("order_no", "current_operation", "pending_operations")),
    "progress_percent": ("production_progress",
                         ("order_no", "progress_percent", "total_operations",
                          "done_operations")),
    "scheduled_delivery_date": ("processing_orders", ("processing_order_no", "expected_delivery_date")),
    "promised_ship_date": ("processing_orders", ("processing_order_no",)),
}

#: 声明**无真值**的字段 —— 具名说明缺哪个列 / 为什么（issue #6217 判据 1 的「未接线」支）。
#: 🔴 每一条都是**复核过既有端点**之后写下的（不是猜）：
#:  `/api/admin/processing-orders`（`ProcessingOrderResponse`）与
#:  `/api/admin/agent/production/progress` 的真实响应列见 admin-api 侧源码 —— 下列列**一个都不在**。
NO_TRUTH_REASONS: Dict[str, str] = {
    "scheduled_delivery_date": (
        "既有只读端点无此来源：`/api/admin/processing-orders` 的 `ProcessingOrderResponse` 只有"
        "一个 `expectedDeliveryDate`（**没有**第二个「排产交期」列），"
        "`/api/admin/agent/production/progress` 也只有 `expected_delivery_date`"
        "⇒ 排产交期一律「未知」，不得与 `expected_delivery_date` 混为一谈、更不得回填当天"
    ),
    "promised_ship_date": (
        "既有只读端点无此来源：加工单列表只有 `generatedAt` / `issuedAt` / `inProcessingAt` / "
        "`completedAt` 等**实际**时刻列，**没有**「承诺发货日」；订单侧的 `requiredDeliveryDate` "
        "属订单读面（`order:list`），不在本视图的三条取数面内 ⇒ 一律「未知」，不得回填"
    ),
}

#: 字段的中文短标签（披露文案的单点来源：工具层不另写一份，避免两处措辞漂移）
FIELD_LABELS: Dict[str, str] = {
    "processing_order_no": "加工单号", "order_no": "订单号", "customer_name": "客户",
    "processor": "加工人", "status": "加工单状态", "expected_delivery_date": "交期",
    "days_to_deadline": "距交期", "stuck_operation": "卡点工序",
    "pending_operations": "待完工序数", "progress_percent": "工序进度",
    "scheduled_delivery_date": "排产交期", "promised_ship_date": "承诺发货日",
}

#: 字段的人话说明（LLM / 调用方可见；与 `FIELD_SOURCES` 一一对应）
_FIELD_NOTES: Dict[str, str] = {
    "processing_order_no": "加工单号（`/api/admin/processing-orders`）",
    "order_no": "关联订单号（加工单列表经由订单批量取回）",
    "customer_name": "客户名（加工单列表经由订单批量取回）",
    "processor": "加工人（加工单列表）",
    "status": "加工单状态（generated/issued/in_processing/completed/cancelled，端点原样透出）",
    "expected_delivery_date": "交期（加工单列表的 `expectedDeliveryDate`；**null = 未填** ⇒ 未知）",
    "days_to_deadline": "距今到期天数 = 交期 − as_of（**负数 = 已逾期**；无交期 ⇒ 未知）",
    "stuck_operation": "卡点工序 = 逐单进度里**第一个未完成**的工序名（无待完工序 / 没取到进度 ⇒ 未知）",
    "pending_operations": "该单待完（未完成）工序**道数**（端点数组的长度；没取到进度 ⇒ 未知）",
    "progress_percent": "工序进度 = 已完成工序数 ÷ 总工序数 × 100（端点为 0–100 的百分数）",
    "scheduled_delivery_date": "排产交期（**声明无真值**：端点无第二个交期列 ⇒ 一律未知）",
    "promised_ship_date": "承诺发货日（**声明无真值**：端点无该列 ⇒ 一律未知）",
}


# ── 数值读取（确定性：非数值 / 缺字段一律「未知」，不猜 0）─────────────────────


def _out(value: Optional[Decimal]) -> Optional[float]:
    """`Decimal` ⇒ JSON 原生 `float`（定精度），`None` 原样透出。"""
    if value is None:
        return None
    return float(value.quantize(_OUTPUT_QUANT, rounding=ROUND_HALF_UP))


# ── 进度归并（按订单号 —— 两条端点的唯一共用键）───────────────────────────────


def _ref(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _progress_by_order(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _rows(snapshot, "production_progress"):
        key = _ref(row.get("order_no"))
        if key:
            out[key] = row
    return out


def _pending(row: Dict[str, Any]) -> Optional[List[str]]:
    """待完工序（端点数组）⇒ 字符串列表；**键不在 / 形态不认识 ⇒ `None`（未知，不是 `[]`）**。"""
    raw = row.get("pending_operations")
    if not isinstance(raw, (list, tuple)):
        return None
    return [str(name) for name in raw if name not in (None, "")]


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def _base(field: str, source: str) -> Dict[str, Any]:
    return {"missing": [], "gaps": [], "source": source,
            "note": _FIELD_NOTES[field], "label": FIELD_LABELS[field]}


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #6217 判据 1）。

    返回 `{字段: {"status", "reason", "missing", "gaps", "source", "truth", "note", "label"}}`：
    `status` ∈ {`wired`, `not_wired`（声明无真值 / 装配层未接线 / 该行整行缺键）,
    `incomplete`（已接线但**本次不完整**）}；不变式：**`reason is None` ⟺ `status == wired`**。

    纯函数、只读：同一 `snapshot` ⇒ 同一结果（与视图行互不影响）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for field, (array, needed) in FIELD_SOURCES.items():
        source = f"{array}.{'/'.join(needed)}"
        base = _base(field, source)
        if field in NO_TRUTH_REASONS:
            status[field] = {"status": NOT_WIRED, "reason": f"声明无真值：{NO_TRUTH_REASONS[field]}",
                             "truth": NO_TRUTH, **base}
            continue
        declared = _declared_fields(snapshot, array)
        if declared is None:
            status[field] = {"status": NOT_WIRED, "reason": f"快照未提供 {array} 行数组（装配层未接线）",
                             "truth": HAS_TRUTH, **{**base, "missing": [array]}}
            continue
        missing = [name for name in needed if name not in declared]
        if missing:
            status[field] = {"status": NOT_WIRED,
                             "reason": f"快照 {array} 行缺字段 {'、'.join(missing)}"
                                       "（既有端点无此列 / 装配层未接）",
                             "truth": HAS_TRUTH, **{**base, "missing": missing}}
            continue
        gaps = _gaps(field, snapshot, array)
        status[field] = {"status": INCOMPLETE if gaps else WIRED,
                         "reason": "；".join(gaps) if gaps else None,
                         "truth": HAS_TRUTH, **{**base, "gaps": gaps}}
    return status


def _missing_progress_rows(snapshot: Any) -> int:
    """**整行缺键**的加工单数：该单在 `production_progress` 里没有被取到（逐单取数有上限）。"""
    keyed = _progress_by_order(snapshot)
    return sum(1 for row in _rows(snapshot, "processing_orders")
               if _ref(row.get("order_no")) not in keyed)


def _gaps(field: str, snapshot: Any, array: str) -> List[str]:
    """该字段本次**结论不完整**的原因（有界截断 / 逐单进度缺口 —— 都带可归因读数）。"""
    gaps: List[str] = []
    meta = _row_meta(snapshot, array)
    if meta.get("truncated"):
        gaps.append(
            f"{array} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
            f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
        )
    if FIELD_SOURCES[field][0] == "production_progress":
        missing = _missing_progress_rows(snapshot)
        if missing:
            gaps.append(f"{missing} 张加工单没有逐单工序进度（逐单取数有上限 / 该单取数失败）"
                        "⇒ 这些单的卡点与进度**未知**（不是「没有卡着的工序」）")
    if field == "expected_delivery_date":
        blank = _blank_deadlines(snapshot)
        if blank:
            gaps.append(f"{blank} 张加工单没有交期（`expectedDeliveryDate` 为空）"
                        "⇒ 这些单的到期天数与风险分层**未知**（不是「不紧急」）")
    return gaps


def _blank_deadlines(snapshot: Any) -> int:
    """交期为空的加工单数（逐行判 —— 缺值不许被读成「今天到期」）。"""
    return sum(1 for row in _rows(snapshot, "processing_orders")
               if not _ref(row.get("expected_delivery_date")))


# ── 视图行 ──────────────────────────────────────────────────────────────────


def _band(days: Optional[int]) -> str:
    """交付风险分层：**没有交期 ⇒ `unknown`**（未知 ≠ 不紧急）。"""
    if days is None:
        return "unknown"
    if days < 0:
        return "overdue"
    if days <= CRITICAL_DAYS:
        return "critical"
    if days <= SOON_DAYS:
        return "soon"
    return "safe"


def _row(order: Dict[str, Any], progress: Optional[Dict[str, Any]], *,
         as_of: _dt.date) -> Dict[str, Any]:
    """一行 = 一张加工单。逐格「未知」由 `*_basis` + `unwired` 自述。"""
    unwired: List[str] = []
    # 交期：**逐单进度**里的交期优先（它与 `days_to_deadline` 同源），退回加工单列表的交期
    deadline_raw = None
    if progress is not None:
        deadline_raw = progress.get("expected_delivery_date")
    if deadline_raw in (None, ""):
        deadline_raw = order.get("expected_delivery_date")
    deadline = _day(deadline_raw)
    days = None if deadline is None else (deadline - as_of).days
    if deadline is None:
        unwired.append("expected_delivery_date")

    pending: Optional[List[str]] = None
    current: Optional[str] = None
    percent: Optional[Decimal] = None
    if progress is None:
        unwired.extend(["stuck_operation", "pending_operations", "progress_percent"])
    else:
        pending = _pending(progress)
        if pending is None:
            unwired.append("pending_operations")
        raw_current = progress.get("current_operation")
        current = str(raw_current) if raw_current not in (None, "") else None
        if current is None and pending:
            # 端点没给当前工序名，但给了待完工序**有序数组** ⇒ 第一个未完成 = 当前卡点（同一口径）
            current = pending[0]
        if current is None and pending is None:
            # 🔴 「没有卡点」与「读不出卡点」不可合并：
            #   · `pending == []`（端点明确给了空数组）⇒ **确实没有待完工序**（真结论，不进 unwired）；
            #   · `pending is None`（连数组都没取到）⇒ 卡点**未知**（不是「没有卡点」）。
            unwired.append("stuck_operation")
        if progress.get("progress_percent") is not None:
            percent = _num(progress.get("progress_percent"))
            percent = None if percent is None else Decimal(str(percent))
        else:
            total, done = _num(progress.get("total_operations")), _num(progress.get("done_operations"))
            if total and total > 0 and done is not None:
                percent = (Decimal(str(done)) / Decimal(str(total))) * Decimal(100)
            else:
                unwired.append("progress_percent")

    return {
        "processing_order_no": order.get("processing_order_no"),
        "order_no": order.get("order_no"),
        "customer_name": order.get("customer_name"),
        "processor": order.get("processor"),
        "status": order.get("status"),
        "expected_delivery_date": deadline.isoformat() if deadline else None,
        "days_to_deadline": days,
        "risk_band": _band(days),
        "stuck_operation": current,
        "pending_operations": pending,
        "pending_count": None if pending is None else len(pending),
        "progress_percent": _out(percent),
        # 🔴 声明无真值的两格恒为 null（**不得**回填）—— 口径见 NO_TRUTH_REASONS
        "scheduled_delivery_date": None,
        "promised_ship_date": None,
        "unwired": sorted(set(unwired)),
    }


def _stuck_top(rows: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    """**跨单聚合**：卡点工序 → 卡在该工序的加工单数（降序；这就是「卡在哪个工序最多」）。

    口径：只统计 `stuck_operation` **有真值**的行（未知不参与 —— 未知不是「没卡」）。
    """
    counts: Dict[str, int] = {}
    for row in rows:
        name = row["stuck_operation"]
        if name not in (None, ""):
            counts[str(name)] = counts.get(str(name), 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"operation": name, "order_count": count} for name, count in ranked[:limit]]


def delivery_risk(snapshot: Any, *, tenant_id: Any, as_of: _dt.date,
                  limit: int = MAX_VIEW_ROWS) -> Dict[str, Any]:
    """产出具名跨域视图 `delivery_risk` —— 纯函数、确定性、有界。

    Args:
        snapshot: 由两条既有只读端点装配的快照（契约见模块 docstring）
        tenant_id: 调用方所在租户（原样回显；隔离关口在装配层）
        as_of: 扫描基准日（**调用方传入** —— 本模块不读挂钟，确定性由此保证）
        limit: 输出行数上限（≥1；截断时逐字段落 `incomplete`）

    Returns:
        `{"view", "tenant_id", "as_of", "fields", "rows", "stuck_top", "row_meta", "count",
          "rows_total", "truncated", "no_truth_fields", "has_truth_fields", "band_counts",
          "missing_progress", "blank_deadlines", "basis"}`
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 ≥1 的整数，实得 {limit!r}")
    if not isinstance(as_of, _dt.date) or isinstance(as_of, _dt.datetime):
        raise ValueError(f"as_of 必须是 datetime.date，实得 {as_of!r}")

    fields = field_status(snapshot)
    progress = _progress_by_order(snapshot)
    rows = [_row(order, progress.get(_ref(order.get("order_no"))), as_of=as_of)
            for order in _rows(snapshot, "processing_orders")]

    # 行序 = 交付风险降序（同分层按到期天数升序，未知排最后），再按加工单号升序
    rows.sort(key=lambda item: (
        RISK_BANDS.index(item["risk_band"]),
        item["days_to_deadline"] if item["days_to_deadline"] is not None else 10 ** 6,
        str(item["processing_order_no"] or ""),
    ))

    # 🔴 聚合用**全量**行（不是截断后的前 N 行）—— 否则「卡在哪个工序最多」会随 limit 变
    stuck_top = _stuck_top(rows)

    total = len(rows)
    truncated = total > limit
    if truncated:
        rows = rows[:limit]
        # 🔴 有界不许变成静默少报：输出被截断 ⇒ 每个「有真值」字段的结论都不完整（带可归因读数）
        for entry in fields.values():
            if entry["truth"] != HAS_TRUTH:
                continue
            entry["gaps"] = list(entry["gaps"]) + [
                f"视图输出被上限截断（上限 {limit} 行，本次给出 {len(rows)} 行，共 {total} 行）"
                "⇒ 结论不完整"
            ]
            entry["status"] = INCOMPLETE
            entry["reason"] = "；".join(entry["gaps"])

    meta = snapshot.get("row_meta") if isinstance(snapshot, dict) else None
    return {
        "view": VIEW_ID,
        "tenant_id": tenant_id,
        "as_of": as_of.isoformat(),
        "fields": fields,
        "rows": rows,
        "stuck_top": stuck_top,
        "row_meta": dict(meta) if isinstance(meta, dict) else {},
        "count": len(rows),
        "rows_total": total,
        "truncated": truncated,
        "no_truth_fields": sorted(f for f, e in fields.items() if e["truth"] == NO_TRUTH),
        "has_truth_fields": sorted(f for f, e in fields.items() if e["truth"] == HAS_TRUTH),
        "band_counts": {band: sum(1 for r in rows if r["risk_band"] == band) for band in RISK_BANDS},
        "missing_progress": _missing_progress_rows(snapshot),
        "blank_deadlines": _blank_deadlines(snapshot),
        "basis": {
            "arrays": list(ARRAYS),
            "join_key": "order_no —— 加工单列表与逐单工序进度的唯一共用键",
            "row_order": f"交付风险降序 {list(RISK_BANDS)} → 距交期天数升序 → 加工单号升序",
            "risk_band": f"days_to_deadline < 0 ⇒ overdue；<= {CRITICAL_DAYS} ⇒ critical；"
                         f"<= {SOON_DAYS} ⇒ soon；其余 ⇒ safe；无交期 ⇒ unknown（未知）",
            "stuck_top": "卡点工序 → 卡在该工序的加工单数（降序，取前 10）；只统计卡点有真值的行",
            "truth_source": "本模块的 FIELD_SOURCES / NO_TRUTH_REASONS（**单点声明**）",
        },
    }
