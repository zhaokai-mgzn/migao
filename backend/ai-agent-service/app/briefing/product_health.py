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
    "NOT_ON_SALE",
    "filtered_skus",
    "field_status",
    "product_health",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "product_health"

#: 视图输出上限（有界是热路径的硬前提；截断必须显式 —— 见模块 docstring）
MAX_VIEW_ROWS = 200

#: 「SKU 到期连一行都没进视图」的第四态（issue #6347 Part B）。
#:
#: 🔴 它与 `not_wired`（系统没接）/ `incomplete`（接了但不完整）**并列、不可合并**：这里那个空是
#: **服务端过滤造成的、可行动的空** —— 事实（有几个 SKU / 几个商品 / 商品现在是什么状态）都在，
#: 出路也在（把商品上架，或在状态非法时先改回 `off_sale`/`draft` 再上架）。混成「没有数据」，
#: 用户就被引向**徒劳返工**（重录商品规格），真因一字未提。不变式 `reason is None ⟺ wired`
#: **不给本态开例外**（它的 `reason` 就是那句人话）。
NOT_ON_SALE = "not_on_sale"

#: 商品状态机**内**的合法值（唯一权威 = `ProductService.PRODUCT_STATUSES`，由测试逐字钉住）。
#: 不在其中的状态（如 `active` / `on_shelf`）是「状态机死行」：上架动作会被拒 ⇒ 出路只有先改回
#: 这两个可自救的状态再上架（Part A 已让这条流转可走）。**本模块不做第二份状态机判定** —— 这个
#: 集合只用来把**出路**说对：说错出路比不说更坏。
_RECOVERABLE_STATUSES = frozenset({"draft", "under_review", "on_sale", "off_sale"})

#: 装配层**读不到**该商品行时的占位（已删除 / 越租户）—— 与「读到了、值非法」**必须分开说**
#: （前者不许给「改回 off_sale/draft」的指引：我们并不知道它现在是什么）。
_UNKNOWN_STATUS = "unknown"

#: 给 LLM 的披露里**禁止**出现的归因错误表述（本单用户原话；由判据逐条钉住，见
#: `tests/test_briefing_product_health.py::TestFilteredSkusAreNotMisattributed`）。
FORBIDDEN_ATTRIBUTIONS = (
    "SKU 记录数 = 0",
    "SKU 记录数为 0",
    "SKU 层是空的",
    "SKU 层为空",
    "建议检查商品规格",
    "没有 SKU",
    "没有任何 SKU",
)

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

#: 「行来自 `skus` 数组」的字段（服务端过滤事实只推翻这些字段的结论）—— 从 `FIELD_SOURCES` 现取
_SKU_SOURCED_FIELDS: Tuple[str, ...] = tuple(
    name for name, (array, _) in FIELD_SOURCES.items() if array == "skus"
)

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


# ── 服务端过滤事实（issue #6347 Part B：「有 SKU 但商品不在售」必须自己说出来）─────


def _int_field(value: Any) -> Optional[int]:
    """非负整数计数；读不出 / 为负 ⇒ `None`（未知）。"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _status_buckets(raw: Any) -> Dict[str, int]:
    """`filtered_by_status` → `{商品状态: SKU 行数}`（只认非负整数计数；其余**不猜**、丢弃）。"""
    if not isinstance(raw, dict):
        return {}
    buckets: Dict[str, int] = {}
    for name, count in raw.items():
        parsed = _int_field(count)
        if parsed is not None:
            buckets[str(name)] = parsed
    return buckets


def _product_ids(raw: Any) -> List[str]:
    return [str(item) for item in raw if isinstance(item, (str, int))] if isinstance(raw, list) else []


def filtered_skus(snapshot: Any) -> Dict[str, Any]:
    """`skus` 数组的**服务端过滤事实**（issue #6347 Part B）—— 装配层经 `row_meta.skus` 透出。

    返回 `{"available", "rows_before_filter", "filtered_count", "filtered_by_status",
    "filtered_product_ids", "message"}`：`available=False` ⇒ **老快照**（该键面世前）⇒
    调用方必须退回旧口径（把空当「未接线/无数据」），**不得**凭空断言「被过滤了」。

    🔴 为什么这是一个**独立于三态**的事实：三态判的是「这个字段接没接、全不全」，
    而过滤判的是「接上了、也全，但服务端**按商品在售口径**把行排除了」。两者可以同时为真，
    混在一起就会把**可行动**的空说成**不可行动**的空（本单的用户就是被这么引去重录规格的）。
    """
    meta = _row_meta(snapshot, "skus")
    before = _int_field(meta.get("rows_before_filter"))
    if before is None:
        return {"available": False, "rows_before_filter": None, "filtered_count": None,
                "filtered_by_status": {}, "filtered_product_ids": [], "message": None}
    count = _int_field(meta.get("count"))
    # `count` 缺席 ⇒ 用**实际行数**（引擎与装配层都别猜：两处口径分叉时以能亲眼看见的那个为准）
    count = len(_rows(snapshot, "skus")) if count is None else count
    buckets = _status_buckets(meta.get("filtered_by_status"))
    ids = _product_ids(meta.get("filtered_product_ids"))
    filtered = max(before - count, 0)
    info: Dict[str, Any] = {
        "available": True,
        "rows_before_filter": before,
        "filtered_count": filtered,
        "filtered_by_status": buckets,
        "filtered_product_ids": ids,
        "message": None,
    }
    if not filtered:
        return info
    info["message"] = _filtered_reason(before, filtered, _prod_count(ids, filtered), buckets)
    return info


def _prod_count(ids: List[str], filtered: int) -> Optional[int]:
    """被排除的**商品数**（只在读数自洽时给出：id 去重后 0 < 数 ≤ 被排除的 SKU 数）。

    不自洽（老快照没给 id / id 数与行数矛盾）⇒ `None`：宁可只说 SKU 数，也不说一个错的商品数。
    """
    unique = len(set(ids))
    return unique if 0 < unique <= filtered else None


def _filtered_reason(before: int, filtered: int, products: Optional[int],
                     buckets: Dict[str, int]) -> str:
    """说清**原因**（不是没建 SKU，而是因未上架未纳入）+ **出路**（issue #6347 用户口径 1/2/3）。"""
    scale = f"{filtered} 个 SKU" + (f"（{products} 个商品）" if products else "")
    statuses = "、".join(f"{name} {count} 个" for name, count in sorted(buckets.items()))
    message = (
        f"商品健康度快照里 skus 过滤前有 {before} 行、按商品在售口径过滤后剩 {before - filtered} 行 —— "
        f"有 {scale} 因**商品未上架**（不在售）未纳入本次视图，"
        f"被过滤商品的状态分布：{statuses or '未知'}。"
        "🔴 卡点在**商品状态**，不在 SKU 有没有建过：把商品上架（状态置 on_sale）后，"
        "它们的 SKU 即纳入本视图。"
    )
    odd = {name: count for name, count in buckets.items() if name not in _RECOVERABLE_STATUSES}
    if not odd:
        return message
    detail = "、".join(f"{name} {count} 个" for name, count in sorted(odd.items()))
    message += f"⚠️ 额外：其中有商品的状态是 {detail} —— 这些值不在商品状态机内"
    if set(odd) - {_UNKNOWN_STATUS}:
        # 状态**读到了**且不在状态机内（如 `active` / `on_shelf`）⇒ 出路明确且**可执行**
        # （Part A 已把这条恢复边做通：只许先改回 off_sale / draft，不许直接上架）。
        message += (
            "（合法值 draft / under_review / on_sale / off_sale），**上架动作会被拒**"
            "（「状态流转无效…允许的目标状态: 无」）⇒ 需先把这些商品改回 off_sale（已下架）或 "
            "draft（草稿），再执行上架；改状态后它们的 SKU 同样纳入本视图。"
        )
    if _UNKNOWN_STATUS in odd:
        # 🔴 状态**读不到**（商品已删 / 越租户）⇒ **不猜**：不说「改回某个值」这种可能不对的指引，
        # 只说清「先去商品列表核实它现在的状态」（说错出路比不说更坏）。
        message += (
            "；其中 `unknown` = 装配层读不到该商品行（可能已删除或不属于本租户）⇒ "
            "无法推断出路，请先在商品列表核实这些商品当前的状态。"
        )
    return message


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #5369 判据 1）。

    返回 `{field: {"status", "reason", "missing", "gaps", "source", "note"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（未接入）, `incomplete`（本次不完整）,
    `not_on_sale`（**已接入且完整，但该数组被服务端按在售口径过滤空了** —— issue #6347 Part B）}；
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

        # 🔴 服务端过滤（issue #6347 Part B）：数组**接到了、字段也齐**，但这一轮一行都没进来，
        # 且过滤事实（filtered_skus）证明**过滤前是有行的** ⇒ 本字段的空**不是**「没数据」。
        # 判在 `line = 过滤后 0 行` 这一支（部分保留时字段照旧可用，但仍如实披露）。
        info = filtered_skus(snapshot)
        if field in _SKU_SOURCED_FIELDS and info["available"] and info["message"]:
            if not _rows(snapshot, array):
                status[field] = {
                    "status": NOT_ON_SALE,
                    "reason": info["message"],
                    "missing": [],
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
          "truncated", "unknown_cost_rows", "unattributed_returns", "not_on_sale", "basis"}`；
        `not_on_sale` = 服务端过滤事实（issue #6347 Part B，见 `filtered_skus`）—— 行为与
        「表里没有 SKU」**不可合并**：有它就必须说清「有 N 个 SKU（M 个商品）因未上架未纳入」+ 出路。
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
        # 服务端过滤事实（issue #6347 Part B）：**独立于三态**，工具层据它把原因与出路说给模型
        "not_on_sale": filtered_skus(snapshot),
        "basis": {
            "stock_authority": STOCK_AUTHORITY,
            "sales_authority": STOCK_AUTHORITY,
            "cost_authority": STOCK_AUTHORITY,
            "low_stock": f"stock {LOW_STOCK_OPERATOR} {LOW_STOCK_THRESHOLD}",
            "return_rate": "退货工单数 ÷ 订单行数（同期窗口，装配层同源）",
        },
    }