"""具名跨域视图 · `product_health`（商品健康度：销量 + 库存 + 退货率 + 成本毛利）—— issue #5369

判据来源：issue #5369（族 3 · 包 2「按需消费」，设计文档 §三 族 3）。本模块是**视图语义**的唯一
判据源：给一份**内核快照**（与族 1 主动发现**同一份**行级快照 —— 同一内核、两种消费形态），产出
确定性的 SKU 级视图行 + **逐字段接线状态**。它不取数、不联网、不读挂钟。

## 三条纪律（逐条落在代码里）

1. **逐字段三态**（复用 #5358 的纪律，见 `app/briefing/proactive.py::proactive_status`）：
   每个字段是 `wired` / `not_wired` / `incomplete`（+ `reason`），不变式 **`reason is None` ⟺ `wired`**。
   ⇒ 调用方只要看这一条，就知道「空」能不能读成「没问题」。

2. 🔴 **「未知」与「0」不混**：
   · `avg_cost IS NULL`（`schema.sql` 的既有口径：存量不回填、不猜 0）⇒ 该行**成本未知**
     （`gross_margin=None` + `cost_known=False`），**不得**产出 `0` 毛利；
   · 售价 = 成本 ⇒ 毛利**真 0**（有真值时 0 是正确结论）—— 两者在输出上必须可分；
   · 退货率：有分母且 0 退货 ⇒ **真 0**；分母为 0（没有订单行）⇒ **未知**（不倒推 0）；
   · 库存读不出 ⇒ `low_stock=None`（**未知**），不得判成 `False`（那会被读成「没问题」）。

3. **口径同源（不得另写一份聚合）**：
   · 库存 / 销量的权威 = **SKU 级**（`product_skus.stock` / `product_skus.sales_count`，
     `#4038` + `schema.sql`：商品级同名列是**派生冗余列**）⇒ 本视图只取行里的权威列，不做第二份派生；
   · 低库存判定复用**既有业务口径**（`app/tools/stock_semantics.py` 的 `LOW_STOCK_THRESHOLD`，
     含上界 `≤`）—— 与族 1 的 `low_stock` 规则同一份阈值：判据
     `tests/test_briefing_product_health.py::TestSourceOfTruthIsShared::test_low_stock_judgement_equals_family1_rule`
     （同一快照下两侧的告急 SKU 集合必须逐字相同）；
   · 退货率的两端（`return_tickets` / `order_lines`）由装配层成对给出（同一窗口、同一口径），
     本视图**只做除法**，不各自另算一份。

## 退货率口径（本包定义，逐字进判据）

**某商品的退货率 = 该商品归属到的退货工单数 ÷ 该商品的订单行数**（同期窗口，窗口由装配层保证：
`DailyBriefingService.SNAPSHOT_RETURN_WINDOW_DAYS` 两端同源）。分子来自
`after_sales_tickets`（`ticket_type='return'`）按订单归属到商品（多商品订单**不猜** ⇒ `product_id`
为空的退货行会被计成 `incomplete`，而不是静默压低退货率）；分母来自 `order_items` 的**有效订单行数**
（口径同 `OrderItemMapper.selectProductRanking` 的有效状态集）。**不是**「退货件数 ÷ 销量米数」。

## 有界与租户

`limit`（默认 `MAX_VIEW_ROWS`）是有界的硬前提；**输出被截断时每个字段都落 `incomplete`**（有界不许
变成静默少报）。租户由调用方传入并原样回显（**不由行数据反推**）—— 隔离的关口在装配层（每条查询
带租户），视图不承担取数，也不提供绕过通道。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

# 内核读取器（声明优先 / 截断显式 / 行数组容错）—— 复用，不复制第二份（#5369 判据 3）
from app.briefing.proactive import (
    INCOMPLETE,
    NOT_WIRED,
    WIRED,
    _declared_fields,
    _num,
    _row_meta,
    _rows,
)
from app.tools.stock_semantics import LOW_STOCK_OPERATOR, LOW_STOCK_THRESHOLD, STOCK_AUTHORITY

__all__ = [
    "MAX_VIEW_ROWS",
    "VIEW_ID",
    "FIELD_LABELS",
    "FIELD_SOURCES",
    "REQUIRED_ROW_FIELDS",
    "LOW_STOCK_THRESHOLD",
    "field_status",
    "product_health",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "product_health"

#: 视图输出上限（有界是热路径的硬前提；截断必须显式 —— 见模块 docstring）
MAX_VIEW_ROWS = 200

#: 金额 / 比率的输出精度（4 位小数：与 `product_skus.avg_cost NUMERIC(12,4)` 同粒度）
_OUTPUT_QUANT = Decimal("0.0001")

#: 逐字段来源（**单点声明**）：视图字段 → （权威行数组，该数组里必须存在的字段）
FIELD_SOURCES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "sales_count": ("skus", ("sales_count",)),
    "stock": ("skus", ("stock",)),
    "gross_margin": ("skus", ("price", "avg_cost")),
    "return_rate": ("product_return_stats", ("product_id", "return_tickets", "order_lines")),
}

#: 本视图需要的行字段（装配层 `row_fields` 必须声明它们；与 Java 侧契约机械钉住）
REQUIRED_ROW_FIELDS: Dict[str, Tuple[str, ...]] = {
    "skus": ("sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"),
    "returns": ("product_id",),
    "product_return_stats": ("product_id", "return_tickets", "order_lines"),
}

#: 字段的中文短标签（披露文案的单点来源：工具层不另写一份，避免两处措辞漂移）
FIELD_LABELS = {
    "sales_count": "销量",
    "stock": "库存",
    "gross_margin": "成本毛利",
    "return_rate": "退货率",
}

#: 字段的人话说明（LLM / 调用方可见；与 `FIELD_SOURCES` 一一对应）
_FIELD_NOTES = {
    "sales_count": "SKU 累计销量（权威 = product_skus.sales_count）",
    "stock": "SKU 库存（0.1 米粒度；权威 = product_skus.stock）",
    "gross_margin": "毛利 = 售价 − 移动加权成本；成本未知 ⇒ 该行未知（不产出 0）",
    "return_rate": "退货率 = 退货工单数 ÷ 订单行数（同期窗口）；无分母 ⇒ 未知（不产出 0）",
}


# ── 数值读取（确定性：非数值 / 缺字段一律「未知」，不猜 0）─────────────────────


def _dec(value: Any) -> Optional[Decimal]:
    """读成 `Decimal`；非数值 / 非有限 / 缺省 ⇒ `None`（未知）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            return None
    return parsed if parsed.is_finite() else None


def _int_or_none(value: Any) -> Optional[int]:
    """整数计数（条数）：读不出或为负 ⇒ `None`（未知）。"""
    parsed = _dec(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def _out(value: Optional[Decimal]) -> Optional[float]:
    """`Decimal` ⇒ JSON 原生 `float`（定精度），`None` 原样透出。"""
    if value is None:
        return None
    return float(value.quantize(_OUTPUT_QUANT, rounding=ROUND_HALF_UP))


def _gross_margin(price: Optional[Decimal], avg_cost: Optional[Decimal]) -> Optional[Decimal]:
    """毛利 = 售价 − 成本；**任一端未知 ⇒ `None`**（🔴 不得用 0 冒充「成本为零」）。

    这是「未知 vs 0」的唯一接缝：注入式红证（`test_injected_zero_filling_turns_the_same_assertion_red`）
    就是把本函数换成「未知当 0」的版本，同一断言必须变红。
    """
    if price is None or avg_cost is None:
        return None
    return price - avg_cost


def _blank_rows(snapshot: Any, array: str, field: str) -> int:
    """某个行数组里 `field` 缺值的行数（维度缺值 ⇒ 结论不完整，不是「这些行没问题」）。"""
    return sum(1 for row in _rows(snapshot, array) if row.get(field) in (None, ""))


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #5369 判据 1）。

    返回 `{field: {"status", "reason", "missing", "gaps", "source", "note"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（未接入）, `incomplete`（本次不完整）}；
    不变式：**`reason is None` ⟺ `status == wired`**。

    纯函数、只读：同一 `snapshot` ⇒ 同一结果（与视图行互不影响 —— 状态不改判据、不改行）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for field, (array, needed) in FIELD_SOURCES.items():
        declared = _declared_fields(snapshot, array)
        source = f"{array}.{'/'.join(needed)}"
        if declared is None:
            status[field] = {
                "status": NOT_WIRED,
                "reason": f"快照未提供 {array} 行数组（装配层未接线）",
                "missing": [array],
                "gaps": [],
                "source": source,
                "note": _FIELD_NOTES[field],
            }
            continue
        missing = [name for name in needed if name not in declared]
        if missing:
            status[field] = {
                "status": NOT_WIRED,
                "reason": f"快照 {array} 行缺字段 {'、'.join(missing)}（数据层无此来源）",
                "missing": missing,
                "gaps": [],
                "source": source,
                "note": _FIELD_NOTES[field],
            }
            continue

        gaps: List[str] = []
        meta = _row_meta(snapshot, array)
        if meta.get("truncated"):
            gaps.append(
                f"{array} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
                f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
            )
        if field == "return_rate":
            # 分子来自退货行：它的截断 / 归属缺失同样让结论不完整（否则退货率静默偏低）
            if _declared_fields(snapshot, "returns") is None:
                gaps.append("快照未提供 returns 行数组（退货单数来源未接线）⇒ 退货率不完整")
            else:
                returns_meta = _row_meta(snapshot, "returns")
                if returns_meta.get("truncated"):
                    gaps.append(
                        f"returns 数组已被行数上限截断（上限 {returns_meta.get('limit')} 行，"
                        f"本次给出 {returns_meta.get('count')} 行）⇒ 退货单数偏低"
                    )
                unattached = _blank_rows(snapshot, "returns", "product_id")
                if unattached:
                    gaps.append(
                        f"returns 数组有 {unattached} 行退货无法归属到商品（多商品订单，装配层不猜）"
                        "⇒ 受影响的商品退货率偏低"
                    )
        status[field] = {
            "status": INCOMPLETE if gaps else WIRED,
            "reason": "；".join(gaps) if gaps else None,
            "missing": [],
            "gaps": gaps,
            "source": source,
            "note": _FIELD_NOTES[field],
        }
    return status


# ── 视图行（SKU 级 = 唯一权威）───────────────────────────────────────────────


def _row(sku_row: Dict[str, Any], stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """一行 = 一个 SKU（库存 / 销量 / 成本在 SKU 级才是权威 —— `#4038`）。"""
    product_id = sku_row.get("product_id")
    stock = _num(sku_row.get("stock"))
    price, avg_cost = _dec(sku_row.get("price")), _dec(sku_row.get("avg_cost"))
    margin = _gross_margin(price, avg_cost)

    stat = stats.get(str(product_id)) if product_id not in (None, "") else None
    if stat is None:
        tickets = lines = None
        basis = "no_product_stats"
    else:
        tickets, lines = _int_or_none(stat.get("return_tickets")), _int_or_none(stat.get("order_lines"))
        basis = "tickets/order_lines"
    rate: Optional[Decimal] = None
    if tickets is not None and lines is not None:
        if lines > 0:
            rate = Decimal(tickets) / Decimal(lines)
        else:
            # 没有分母 ⇒ 退货率**未知**（`0` 会被读成「没有退货」—— 那是另一件事）
            basis = "no_order_lines"

    return {
        "sku_id": sku_row.get("sku_id") or sku_row.get("id"),
        "product_id": product_id,
        "product_name": sku_row.get("product_name"),
        "stock": stock,
        # 告急 = 既有业务口径（`stock_semantics`，含上界 ≤）—— 未知库存 ⇒ None（不是「不告急」）
        "low_stock": None if stock is None else stock <= LOW_STOCK_THRESHOLD,
        "sales_count": _num(sku_row.get("sales_count")),
        "price": _out(price),
        "avg_cost": _out(avg_cost),
        "gross_margin": _out(margin),
        "cost_known": avg_cost is not None,
        "return_tickets": tickets,
        "order_lines": lines,
        "return_rate": _out(rate),
        "return_rate_basis": basis,
    }


def product_health(
    snapshot: Any, *, tenant_id: Any, limit: int = MAX_VIEW_ROWS
) -> Dict[str, Any]:
    """产出 `product_health` 视图（按需消费）—— 纯函数、确定性、有界。

    Args:
        snapshot: 内核快照（与族 1 同一份；`row_fields` / `row_meta` / 行数组契约见
            `DailyBriefingService.SNAPSHOT_ROW_FIELDS`）
        tenant_id: 调用方所在租户（原样回显；隔离关口在装配层）
        limit: 输出行数上限（≥1；截断时逐字段落 `incomplete`）

    Returns:
        `{"view", "tenant_id", "fields", "rows", "row_meta", "count", "rows_total",
          "truncated", "unknown_cost_rows", "unattributed_returns", "basis"}`
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 ≥1 的整数，实得 {limit!r}")

    fields = field_status(snapshot)
    stats: Dict[str, Dict[str, Any]] = {}
    for row in _rows(snapshot, "product_return_stats"):
        product_id = row.get("product_id")
        if product_id not in (None, ""):
            stats[str(product_id)] = row

    rows = [_row(sku_row, stats) for sku_row in _rows(snapshot, "skus")]
    rows.sort(key=lambda item: (str(item["product_id"] or ""), str(item["sku_id"] or "")))

    total = len(rows)
    truncated = total > limit
    if truncated:
        rows = rows[:limit]
        # 🔴 有界不许变成静默少报：输出被截断 ⇒ 每个字段的结论都不完整（带可归因读数）
        for entry in fields.values():
            entry["gaps"] = list(entry["gaps"]) + [
                f"视图输出被上限截断（上限 {limit} 行，本次给出 {len(rows)} 行，共 {total} 行）"
                "⇒ 结论不完整"
            ]
            entry["status"] = INCOMPLETE
            entry["reason"] = "；".join(entry["gaps"])

    row_meta = snapshot.get("row_meta") if isinstance(snapshot, dict) else None
    return {
        "view": VIEW_ID,
        "tenant_id": tenant_id,
        "fields": fields,
        "rows": rows,
        "row_meta": dict(row_meta) if isinstance(row_meta, dict) else {},
        "count": len(rows),
        "rows_total": total,
        "truncated": truncated,
        "unknown_cost_rows": sum(1 for item in rows if item["cost_known"] is False),
        "unattributed_returns": _blank_rows(snapshot, "returns", "product_id"),
        "basis": {
            "stock_authority": STOCK_AUTHORITY,
            "sales_authority": STOCK_AUTHORITY,
            "cost_authority": STOCK_AUTHORITY,
            "low_stock": f"stock {LOW_STOCK_OPERATOR} {LOW_STOCK_THRESHOLD}",
            "return_rate": "退货工单数 ÷ 订单行数（同期窗口，装配层同源）",
        },
    }