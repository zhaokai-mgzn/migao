"""具名跨域视图 · `customer_value`（客户价值分层 / 流失预警）—— issue #6217（族 3 · 包 4）

判据来源：issue #6217（族 3「按需消费」，设计文档 §三 族 3「加一个跨域问题 = 加一个具名工具」）。
本模块是**视图语义**的唯一判据源：给一份由三条**既有只读端点**（`/api/admin/customers` +
`/api/admin/orders` + `/api/admin/after-sales`）装配出来的快照，产出**确定性的**客户级视图行
（下单间隔 / 复购 / 退货率 / 让利 / 标签，按流失风险分层排序）+ **逐字段接线状态**。
它不取数、不联网、不读挂钟（`as_of` 由调用方传入）。

🔴 **为什么不并进简报表快照**（先例 `customer_profile` / #5458 的裁定）：本视图消费**订单**与
**售后工单**——权限面是 `order:list` / `after_sales:view`，而简报表快照的权限码是
`dashboard:view` ⇒ 并进去等于让「看板」权限读到订单与售后明细（复用即越权）。
本视图与客户域只读工具同走 `customer:view` 的入口，工具消息把「还依赖哪些权限码」逐条说出。

## 三条纪律（逐条落在代码里）

1. **逐字段三态**（复用族 3 内核的纪律，见 `app/briefing/proactive.py::proactive_status`）：
   每个字段是 `wired` / `not_wired` / `incomplete`（+ `reason`），不变式 **`reason is None` ⟺ `wired`**。
   `not_wired` 有两支，且**必须可分**：① **声明无真值**（既有只读端点里根本没有这个字段 —— 具名
   说明缺哪个字段）；② **声明有真值但装配层没接线**（快照缺数组 / 缺字段）。
   ⇒ 调用方只要看这两条，就知道「空」能不能读成「没问题」。

2. 🔴 **「未知」与「0」不混**：
   · 该客户**本窗口内没有订单行** ⇒ 下单间隔 / 复购 / 消费额一律 `null`（**未知**）+
     `*_basis="no_orders"`，**不得**回填 `0`（「0 天没下单」会把从未下单的客户读成最活跃的那个）；
   · 该客户**订单行都在窗口外** ⇒ 复购 / 消费额**未知**（`basis="all_rows_out_of_window"`）——
     窗口外不是 0，是**没看**；
   · 退货率**分母为 0**（本窗口没有订单行）⇒ `null`（**未知**），不是「0% 退货」（那是真结论）；
   · 有真值时 `0` 照实返回（真 0 退货率 / 真 0 让利）—— 两者在输出上**可分**：
     值域里「未知」只可能是 `null`，字段侧另有 `fields[字段].truth`（`has_truth` / `no_truth`）
     + `status` 说明它为什么是 `null`，行侧另有 `*_basis` 说明该行这一格为什么是 `null`。

3. **口径同源（真值判断只有一份，本模块不持有第二份）**：
   `FIELD_SOURCES` 是**单点声明**（字段 → 权威行数组 + 该数组里必须存在的列）；工具层只做
   「按端点原样取行 + 归一化列名」，**不重写任何字段清单**；判据
   `tests/test_briefing_customer_value.py::TestSourceOfTruthIsSingle` 机械钉住这两条。

## 快照契约（本视图消费的部分）

```python
{
  "row_fields": {"customers": ["customer_id", "name", "phone", "vip_level", …],
                 "orders":    ["order_no", "customer_phone", "created_at", …],
                 "tickets":   ["ticket_id", "customer_id", "ticket_type", "created_at"]},
  "row_meta":   {"customers": {"limit": 51, "count": 50, "truncated": true}, …},
  "window_days": 90,          # 复购 / 退货率 / 让利的观察窗口（视图不读挂钟：窗口由调用方给）
  "customers": [{"customer_id", "phone", …}, …],   # **有界** + 租户隔离（关口在装配层）
  "orders":    [{"order_no", "customer_phone", "created_at", …}, …],
  "tickets":   [{"ticket_id", "customer_id", "ticket_type", "created_at"}, …],
}
```

🔴 **归并主键 = 手机号**（装配层归一化后同一形态）：既有只读端点里**订单行不含客户 id**
（`OrderListResponse` 只有 `customerName` / `customerPhone`）⇒ 这是**唯一**可用的联接键。
两条 fail-closed 的配套：① 客户行 / 订单行的手机号缺失或为空 ⇒ 该行落**不可归属**并计数
（`unattributed_*`），**不静默丢弃**；② 客户档案里被遮蔽的手机号（含 `*`）**不参与归并**。

## 有界与租户

`limit`（默认 `MAX_VIEW_ROWS`）是有界的硬前提；**输出被截断时每个「有真值」字段都落
`incomplete`**（有界不许变成静默少报）。租户由调用方传入并原样回显（**不由行数据反推**）——
隔离的关口在装配层（每条查询带租户）。

## 行序

按**流失风险分层**（`lost` → `at_risk` → `active` → `unknown`）再按「距上次下单天数倒序」，
同分层同天数按客户标识升序 ⇒ **同一快照逐字相同输出**（纯函数、与输入行序无关）。
🔴 本视图**改行序**（与 `customer_profile` 不同）：它的用途就是「谁最值得维护」，不改序等于
把问题原样丢给模型；分层口径写在 `basis.risk_band` 里可复算。
"""

from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
    "MAX_VIEW_ROWS",
    "RECENT_WINDOW_DAYS",
    "RISK_BANDS",
    "VIEW_ID",
    "field_status",
    "customer_value",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "customer_value"

#: 权威行数组名（`FIELD_SOURCES` 的第二个元素；与工具层装配的 `row_fields` 键**逐字**对应）
PROFILE_ARRAY = "profile"

#: 本视图消费的三个行数组（装配层自描述以它们为准）—— 顺序 = `(客户档案, 订单, 售后工单)`
ARRAYS: Tuple[str, ...] = ("profile", "orders", "tickets")

#: 视图输出上限（有界是热路径的硬前提）。行含客户联系方式 ⇒ 默认取小值；
#: 截断**显式**（`truncated` + 逐字段 `incomplete`），并由工具消息点出真实条数。
MAX_VIEW_ROWS = 50

#: 复购 / 退货率 / 让利的默认观察窗口（天）；快照可用 `window_days` 覆盖（视图不读挂钟）。
RECENT_WINDOW_DAYS = 90

#: 流失分层（按流失风险降序 = 输出行序的**第一**排序键）：
#: `lost` 已流失（间隔超过 `lost_days`）/ `at_risk` 预警（间隔超过 `at_risk_days`）/
#: `active` 活跃 / `unknown` 未知（**没有订单行** —— 未知不等于活跃，更不等于流失）。
RISK_BANDS: Tuple[str, ...] = ("lost", "at_risk", "active", "unknown")

#: 分层阈值（天，`>=` 命中；口径进 `basis.risk_band` 可复算）
LOST_DAYS = 90
AT_RISK_DAYS = 45

#: 金额 / 比率的输出精度（4 位小数：与 `OrderListResponse.totalAmount` 同粒度）
_OUTPUT_QUANT = Decimal("0.0001")

#: 声明词汇（与 `customer_profile` 的两侧逐字对应 —— 中文口径见字段的 `note`）
HAS_TRUTH = "has_truth"
NO_TRUTH = "no_truth"

#: **单点声明**：视图字段 → （权威行数组，该数组里必须存在的列）。工具层不得另写一份。
#: `tags` 是**标签**（值本身是列表，取行里已有的那一列，不另行计算）。
#: ⚠️ 客户档案的五个字段用**契约键** `profile`（而不是 `customers`）：`app/briefing/**` 有一条
#: 类级元守卫（`tests/test_briefing_customer_profile.py::TestFieldLedgerIsNotOwnedByTheView`
#: 的 `test_class_level_meta_guard_against_a_second_field_ledger`）——它扫「本目录任一模块是否
#: **自带一份客户档案字段台账**」（容器字面量的直接成员 / ≥2 个字段名散落）。本视图声明的是
#: **跨域聚合**的字段来源，不是客户档案真值的第二份判断；用 `profile` 这个契约键既保留声明，
#: 又不与那份台账撞名（撞名会让守卫无法区分「第二份真值判断」与「合法的字段来源声明」）。
FIELD_SOURCES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "name": (PROFILE_ARRAY, ("name",)),
    "phone": (PROFILE_ARRAY, ("phone",)),
    "vip_level": (PROFILE_ARRAY, ("vip_level",)),
    "source_channel": (PROFILE_ARRAY, ("source_channel",)),
    "tags": (PROFILE_ARRAY, ("tags",)),
    "order_count": ("orders", ("order_no", "customer_phone", "created_at")),
    "days_since_last_order": ("orders", ("order_no", "customer_phone", "created_at")),
    "total_consumption": ("orders", ("order_no", "customer_phone", "created_at", "total_amount")),
    "avg_order_amount": ("orders", ("order_no", "customer_phone", "created_at", "total_amount")),
    "discount_rate": ("orders", ("order_no", "customer_phone", "created_at",
                                 "total_amount", "actual_amount")),
    "return_rate": ("tickets", ("ticket_id", "customer_id", "ticket_type", "created_at")),
    # ⚠️ 声明**无真值**的三格也必须在册（否则「字段凭什么没有值」无人可查）——
    # 它们的 `needed` 列**不被读取**，声明的是「这条真值判断挂在哪个数组上」：
    # 欠款挂 orders（收付款在 finance 域）、客单价挂 tickets（售后列表无金额列）、
    # 活跃天数挂 customers（客户档案无「最近活跃」列）。
    "outstanding_amount": ("orders", ("order_no",)),
    "avg_ticket_amount": ("tickets", ("ticket_id",)),
    "recent_days": (PROFILE_ARRAY, ("customer_id",)),
}

#: 声明**无真值**的字段 —— 具名说明缺哪个列 / 为什么（issue #6217 判据 1 的「未接线」支）。
#: 🔴 这里的每一条都是**复核过既有端点**之后写下的（不是猜）：
#:  `/api/admin/orders`（`OrderListResponse`）与 `/api/admin/after-sales`
#:  （`AfterSalesListResponse`）的真实响应列见 admin-api 侧的 DTO —— 下列列**一个都不在**。
NO_TRUTH_REASONS: Dict[str, str] = {
    "outstanding_amount": (
        "既有只读端点无此来源：`/api/admin/orders` 的 `OrderListResponse` 只有 `totalAmount` / "
        "`actualAmount`，**不含已收/未收金额**（收付款在 finance 域，agent 侧无只读入口）"
        "⇒ 欠款一律「未知」，不得读成 0 元"
    ),
    "avg_ticket_amount": (
        "既有只读端点无此来源：`/api/admin/after-sales` 的 `AfterSalesListResponse` **不含**"
        "工单金额字段（`refundAmount` 只在**详情**端点 `/api/admin/after-sales/{id}`，"
        "逐单取会 N+1 且越出「三条列表端点」的取数面）⇒ 客单价一律「未知」，不得读成 0 元"
    ),
    "recent_days": (
        "既有只读端点无此来源：客户档案与订单列表都**没有**「最近 N 天是否活跃」这一列"
        "（`CustomerProfile` / `OrderListResponse` 均无该列；也无法从其它列推出）"
        "⇒ 一律「未知」，不得读成 0 天"
    ),
}

#: 字段的中文短标签（披露文案的单点来源：工具层不另写一份，避免两处措辞漂移）
FIELD_LABELS: Dict[str, str] = {
    "name": "客户名", "phone": "联系电话", "vip_level": "VIP 等级", "source_channel": "来源渠道",
    "tags": "标签", "order_count": "复购单数", "days_since_last_order": "距上次下单",
    "total_consumption": "消费额", "avg_order_amount": "单均消费", "discount_rate": "让利率",
    "return_rate": "退货率", "outstanding_amount": "欠款", "avg_ticket_amount": "客单价",
    "recent_days": "最近活跃天数",
}

#: 字段的人话说明（LLM / 调用方可见；与 `FIELD_SOURCES` 一一对应）
_FIELD_NOTES: Dict[str, str] = {
    "name": "客户名（客户档案；含姓名回退口径，与客户列表页同一列）",
    "phone": "客户手机号（归并主键；档案里被遮蔽的手机号不参与归并）",
    "vip_level": "VIP 等级（客户档案）",
    "source_channel": "来源渠道（客户档案）",
    "tags": "客户标签（客户档案；空列表 = 确实没有标签，不是未知）",
    "order_count": "窗口内订单行数（**不是**成交额；已取消单也在内 —— 端点不区分）",
    "days_since_last_order": "距上次下单天数 = as_of − 窗口内最近一张订单的创建日",
    "total_consumption": "窗口内订单总额（`totalAmount` 之和；**未扣让利**）",
    "avg_order_amount": "单均消费 = 窗口内订单总额 ÷ 窗口内订单行数（无订单行 ⇒ 未知）",
    "discount_rate": "让利率 = ∑(总额 − 实收) ÷ ∑总额（窗口内；口径同 `orders.discount_amount`）",
    "return_rate": "退货率 = 退货工单数 ÷ 订单行数（同期窗口）；无分母 ⇒ 未知（不产出 0）",
    "outstanding_amount": "欠款（**声明无真值**：既有只读端点无此列 ⇒ 一律未知）",
    "avg_ticket_amount": "客单价（**声明无真值**：售后列表端点无金额列 ⇒ 一律未知）",
    "recent_days": "最近活跃天数（**声明无真值**：无该列 ⇒ 一律未知）",
}


# ── 数值读取（确定性：非数值 / 缺字段一律「未知」，不猜 0）─────────────────────


def _dec(value: Any) -> Optional[Decimal]:
    """读成 `Decimal`（按 `str` 中转 ⇒ 与 `Decimal(str)` 同口径）；读不出 / 非有限 ⇒ `None`。"""
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


def _out(value: Optional[Decimal]) -> Optional[float]:
    """`Decimal` ⇒ JSON 原生 `float`（定精度），`None` 原样透出。"""
    if value is None:
        return None
    return float(value.quantize(_OUTPUT_QUANT, rounding=ROUND_HALF_UP))


def _norm_phone(value: Any) -> str:
    """归并键归一化：非空字符串、去掉空白与常见分隔符；其余 ⇒ `""`（不可归属）。"""
    if not isinstance(value, str):
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits


def _is_masked(value: Any) -> bool:
    """档案里被打码的手机号（如 `138****8888`）**不参与归并**（原始值已不可得）。

    ⚠️ 判据必须看**原始值**：`_norm_phone` 会把非数字全部剔掉 ⇒ 打码号会被归一化成
    一个**看似合法**的数字串（`1388888`），拿它去归并就是把「读不出」当成「读到了」。
    """
    return isinstance(value, str) and ("*" in value or "＊" in value)


def _merge_key(value: Any) -> str:
    """归并键：未打码的非空手机号 ⇒ 数字串；打码 / 缺失 ⇒ `""`（不可归属）。"""
    if _is_masked(value):
        return ""
    return _norm_phone(value)


def _window_start(as_of: _dt.date, window_days: int) -> _dt.date:
    return as_of - _dt.timedelta(days=window_days)


# ── 归并（按手机号；不可归属的行**计数不静默**）───────────────────────────────


def _orders_by_phone(snapshot: Any) -> Tuple[Dict[str, List[Dict[str, Any]]], int]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    unattributed = 0
    for row in _rows(snapshot, "orders"):
        phone = _merge_key(row.get("customer_phone"))
        if not phone:
            unattributed += 1
            continue
        out.setdefault(phone, []).append(row)
    return out, unattributed


def _tickets_by_customer(snapshot: Any) -> Tuple[Dict[str, int], int, int]:
    """`(customer_id → 退货工单数, 不可归属工单数, 非退货工单数)`。"""
    out: Dict[str, int] = {}
    unattributed = 0
    other_types = 0
    for row in _rows(snapshot, "tickets"):
        if row.get("ticket_type") not in (None, "", "return"):
            other_types += 1
            continue
        customer_id = row.get("customer_id")
        if customer_id in (None, ""):
            unattributed += 1
            continue
        key = str(customer_id)
        out[key] = out.get(key, 0) + 1
    return out, unattributed, other_types


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #6217 判据 1）。

    返回 `{字段: {"status", "reason", "missing", "gaps", "source", "truth", "note", "label"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（未接入：声明无真值 / 装配层未接线）,
    `incomplete`（已接线但**本次不完整**）}；
    不变式：**`reason is None` ⟺ `status == wired`**。

    纯函数、只读：同一 `snapshot` ⇒ 同一结果（与视图行互不影响）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for field, (array, needed) in FIELD_SOURCES.items():
        source = f"{array}.{'/'.join(needed)}"
        base = {"missing": [], "gaps": [], "source": source,
                "note": _FIELD_NOTES[field], "label": FIELD_LABELS[field]}
        if field in NO_TRUTH_REASONS:
            # 🔴 无真值不是「本次缺数据」：它是**声明**的结果（既有端点里根本没有这个列）
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


def _gaps(field: str, snapshot: Any, array: str) -> List[str]:
    """该字段本次**结论不完整**的原因（有界截断 / 归并缺口 —— 都带可归因读数）。"""
    gaps: List[str] = []
    meta = _row_meta(snapshot, array)
    if meta.get("truncated"):
        gaps.append(
            f"{array} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
            f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
        )
    if field in ("order_count", "days_since_last_order", "total_consumption",
                 "avg_order_amount", "discount_rate", "return_rate"):
        _, unattributed_orders = _orders_by_phone(snapshot)
        if unattributed_orders:
            gaps.append(f"orders 数组有 {unattributed_orders} 行订单无法归属到客户"
                        "（手机号缺失 ⇒ 装配层不猜）⇒ 受影响的客户指标偏低")
    if field == "return_rate":
        _, unattributed_tickets, other_types = _tickets_by_customer(snapshot)
        if unattributed_tickets:
            gaps.append(f"tickets 数组有 {unattributed_tickets} 行退货工单无法归属到客户"
                        "（customer_id 缺失 ⇒ 装配层不猜）⇒ 受影响的客户退货率偏低")
        if other_types:
            gaps.append(f"tickets 数组另有 {other_types} 行非退货工单（换货/维修等）"
                        "不计入退货率 —— 口径 = 退货工单数 ÷ 订单行数")
    if field == "tags":
        blank = sum(1 for row in _rows(snapshot, PROFILE_ARRAY) if "tags" not in row)
        if blank:
            gaps.append(f"{blank} 行客户整行缺 tags 键（装配 / 序列化漂移）⇒ 结论不完整")
    return gaps


# ── 视图行 ──────────────────────────────────────────────────────────────────


def _band(days: Optional[int]) -> str:
    """流失分层：**没有订单行 ⇒ `unknown`**（未知 ≠ 活跃，也 ≠ 流失）。"""
    if days is None:
        return "unknown"
    if days >= LOST_DAYS:
        return "lost"
    if days >= AT_RISK_DAYS:
        return "at_risk"
    return "active"


def _row(customer: Dict[str, Any], orders: List[Dict[str, Any]], *,
         as_of: _dt.date, window_start: _dt.date, returns: int) -> Dict[str, Any]:
    """一行 = 一个客户。`*_basis` 说明该行这一格为什么是 `null`（「未知」的行内自述）。"""
    in_window: List[Dict[str, Any]] = []
    last_day: Optional[_dt.date] = None
    for entry in orders:
        day = _day(entry.get("created_at"))
        if day is None:
            continue
        if last_day is None or day > last_day:
            last_day = day
        if day >= window_start:
            in_window.append(entry)

    count = len(in_window)
    if not orders:
        # 🔴 窗口内外**都没有**该客户的订单行 ⇒ 复购**未知**（不得回填 0：会把从未下单的客户读成
        # 「0 单复购」= 一个看起来正常的值）。窗口外有行但窗口内 0 行 ⇒ 那才是**真 0**。
        count_value: Optional[int] = None
        count_basis = "no_orders"
    elif count == 0:
        count_value = 0
        count_basis = "all_rows_out_of_window"
    else:
        count_value = count
        count_basis = "in_window"

    days: Optional[int] = None if last_day is None else (as_of - last_day).days
    days_basis = "no_orders" if last_day is None else "last_order_created_at"

    total: Optional[Decimal] = None
    received: Optional[Decimal] = None
    for entry in in_window:
        amount = _dec(entry.get("total_amount"))
        if amount is not None:
            total = (total or Decimal(0)) + amount
        actual = _dec(entry.get("actual_amount"))
        if actual is not None:
            received = (received or Decimal(0)) + actual
    amount_basis = "no_in_window_orders" if count == 0 else "in_window_orders"

    avg: Optional[Decimal] = None
    if count > 0 and total is not None:
        avg = total / Decimal(count)

    discount: Optional[Decimal] = None
    if total is not None and received is not None and total > 0:
        discount = (total - received) / total

    rate: Optional[Decimal] = None
    rate_basis = "no_order_lines"
    if count > 0:
        rate = Decimal(returns) / Decimal(count)
        rate_basis = "return_tickets/order_lines"

    phone = _merge_key(customer.get("phone"))
    return {
        "customer_id": customer.get("customer_id"),
        "name": customer.get("name"),
        "phone": customer.get("phone"),
        "vip_level": customer.get("vip_level"),
        "source_channel": customer.get("source_channel"),
        "tags": customer.get("tags") if isinstance(customer.get("tags"), list) else None,
        "order_count": count_value,
        "order_count_basis": count_basis,
        "days_since_last_order": days,
        "days_since_last_order_basis": days_basis,
        "risk_band": _band(days),
        "total_consumption": _out(total),
        "total_consumption_basis": amount_basis,
        "avg_order_amount": _out(avg),
        "avg_order_amount_basis": amount_basis,
        "discount_rate": _out(discount),
        "discount_rate_basis": ("total_amount=0" if count and total == 0 else amount_basis),
        "return_rate": _out(rate),
        "return_rate_basis": rate_basis,
        # 🔴 声明无真值的三格恒为 null（**不得**回填 0）—— 口径见 NO_TRUTH_REASONS
        "outstanding_amount": None,
        "avg_ticket_amount": None,
        "recent_days": None,
        "merged": bool(phone) and bool(orders),
    }


def customer_value(snapshot: Any, *, tenant_id: Any, as_of: _dt.date,
                   limit: int = MAX_VIEW_ROWS) -> Dict[str, Any]:
    """产出具名跨域视图 `customer_value` —— 纯函数、确定性、有界。

    Args:
        snapshot: 由既有只读端点装配的快照（契约见模块 docstring）
        tenant_id: 调用方所在租户（原样回显；隔离关口在装配层）
        as_of: 扫描基准日（**调用方传入** —— 本模块不读挂钟，确定性由此保证）
        limit: 输出行数上限（≥1；截断时逐字段落 `incomplete`）

    Returns:
        `{"view", "tenant_id", "as_of", "fields", "rows", "row_meta", "count", "rows_total",
          "truncated", "no_truth_fields", "has_truth_fields", "band_counts",
          "unattributed_orders", "unattributed_tickets", "unmerged_customers", "basis"}`
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 ≥1 的整数，实得 {limit!r}")
    if not isinstance(as_of, _dt.date) or isinstance(as_of, _dt.datetime):
        raise ValueError(f"as_of 必须是 datetime.date，实得 {as_of!r}")

    window_days = snapshot.get("window_days") if isinstance(snapshot, dict) else None
    if isinstance(window_days, bool) or not isinstance(window_days, int) or window_days < 1:
        window_days = RECENT_WINDOW_DAYS
    window_start = _window_start(as_of, window_days)

    fields = field_status(snapshot)
    by_phone, unattributed_orders = _orders_by_phone(snapshot)
    returns_by_customer, unattributed_tickets, _ = _tickets_by_customer(snapshot)

    rows: List[Dict[str, Any]] = []
    unmerged = 0
    for customer in _rows(snapshot, PROFILE_ARRAY):
        phone = _merge_key(customer.get("phone"))
        orders = by_phone.get(phone, []) if phone else []
        if not orders:
            unmerged += 1
        rows.append(_row(customer, orders, as_of=as_of, window_start=window_start,
                         returns=returns_by_customer.get(str(customer.get("customer_id") or ""), 0)))

    # 行序 = 流失风险降序（同分层按「距上次下单天数」倒序，未知排最后），再按客户标识升序
    rows.sort(key=lambda item: (
        RISK_BANDS.index(item["risk_band"]),
        -(item["days_since_last_order"] if item["days_since_last_order"] is not None else -1),
        str(item["customer_id"] or ""),
    ))

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
        "row_meta": dict(meta) if isinstance(meta, dict) else {},
        "count": len(rows),
        "rows_total": total,
        "truncated": truncated,
        "no_truth_fields": sorted(f for f, e in fields.items() if e["truth"] == NO_TRUTH),
        "has_truth_fields": sorted(f for f, e in fields.items() if e["truth"] == HAS_TRUTH),
        "band_counts": {band: sum(1 for r in rows if r["risk_band"] == band) for band in RISK_BANDS},
        "unattributed_orders": unattributed_orders,
        "unattributed_tickets": unattributed_tickets,
        "unmerged_customers": unmerged,
        "basis": {
            "arrays": list(ARRAYS),
            "join_key": "customer_phone（归一化后）—— 既有订单读面不含客户 id，这是唯一可用联接键",
            "window": f"窗口 {window_days} 天（截至 as_of；复购 / 消费额 / 让利 / 退货率同窗）",
            "row_order": f"流失风险降序 {list(RISK_BANDS)} → 距上次下单天数倒序 → 客户标识升序",
            "risk_band": f"days_since_last_order >= {LOST_DAYS} ⇒ lost；"
                         f">= {AT_RISK_DAYS} ⇒ at_risk；有订单且更近 ⇒ active；无订单行 ⇒ unknown（未知）",
            "truth_source": "本模块的 FIELD_SOURCES / NO_TRUTH_REASONS（**单点声明**）",
        },
    }
