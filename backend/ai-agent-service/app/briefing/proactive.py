"""主动发现 · 规则引擎（确定性扫描）—— issue #5322（族 1 · 包 1）

判据来源：`docs/agent-feature-design.md` §三 族 1。

本模块是族 1 的**唯一判据源**：给一份数据快照，产出**确定性的**命中集合
（不是「AI 觉得异常」）。三条铁约束逐条落在这里：

1. **触发用规则，不用 LLM 自由发挥** —— 规则具名（`RULES`）、阈值可配（`ProactiveConfig`）、
   判据逐条可复算（`criterion.expression` + `thresholds` + `observed` 原始观测值）；
2. **每条命中必带三件套** —— `criterion`（为什么给你看）/ `impact`（几条 / 多少钱）/ `action`（一键处置入口）；
3. 🔴 **没有处置入口的不发** —— `action` 缺失/为空的候选在装配期被**丢弃**（`_assemble`），
   不靠调用方自觉；它的红证是注入式的（把某规则的入口拿掉 ⇒ 该条必不出现）。

「**日报要窄，对话要宽**」的落点 = `daily_findings()`：只保留**当天**成立的异常
（事件型规则按事件日期分组，状态型规则按扫描基准日成立）；全量视图见 `scan_snapshot()`。

## 数据快照契约（`snapshot`）

```python
{
  "biz_date": "2026-09-22",   # 扫描基准日（「当天」）；缺省时须由调用方传 as_of
  "config":   {...},          # 选填：阈值覆盖（租户级配置的落点），键同 ProactiveConfig
  "row_fields": {...},        # 装配层**自描述**：本次真的给出了哪些行数组、每个数组有哪些字段
  "row_meta": {...},          # 每个行数组的元信息：{"limit": 500, "count": 500, "truncated": true}
  "cost_accounting": true,    # 租户级**事实**（issue #5348）：该租户是否存在 avg_cost IS NOT NULL 的 SKU
  "audit_tool_logging": true, # 租户级**事实**（issue #5388）：窗口内是否存在**任意** agent_tool 审计行
                              #   = 审计上报在本租户上确实在产出（缺省 = **未知**，不当 false）
  "orders":   [{"order_no", "status", "customer_id", "created_at", "shipped_at",
                "sale_amount", "cost_amount"}],              # 低于成本价 / 超 N 天未发货
  "skus":     [{"sku_id", "product_id", "product_name", "stock"}],  # 库存告急（stock ≤ 阈值）
  "returns":  [{"return_no", "customer_id", "product_id", "returned_at", "amount"}],
  "price_changes": [{"change_no", "tool_name", "product_id",                 # 改价（审计日志源）
                     "before_price", "new_price", "changed_at"}],
  "order_discounts": [{"order_no", "total_amount", "discount_amount",        # 让利（订单列源）
                       "created_at"}],
}
```

行数组缺省 = 该规则无输入 ⇒ **不命中**。这与「命中 0 条」在输出上等价，但语义不同：
**「没数据」不等于「没问题」** —— 调用方不得把空命中读成「今天一切正常」。

⇒ 那个语义差别由 `proactive_status()` 落成**数据层可分**（逐规则 `wired` / `not_wired` /
`not_enabled` / `incomplete` + 原因）：
判据 = 「规则声明的输入」（`RuleSpec.requires` / `dimensions` / `judgeable_fields` / `enabled_by`）
×「装配层声明的产出」（`row_fields` / `row_meta` / 租户级事实），
**两侧各只有一份声明**，没有第二份口径；老快照没有自描述时按实际行的字段并集兜底
（滚动升级期不至于把已接线的规则读成未接线）。

🔴 **加有界（热路径必须）会新开一个静默面**：截断的行「看不见」，规则照旧不命中 ⇒ 又被读成「没问题」。
故装配层的 `row_meta.truncated` **必须显式**，且**只有** `wired`（= 已接入**且本次完整**）才允许把空命中
读成「这方面没问题」；`not_wired` / `not_enabled` / `incomplete` 都带 `reason`。

数据来源：admin-api 聚合层（`DailyBriefingService.aggregateSnapshot`）落库的 `source_snapshot`
—— 与经营日报**同源**，故两个入口口径一致（设计文档 §三 族 3 末「同一内核、两种消费形态」）。
快照内的行级数组（orders / skus / returns）由跨域视图内核（族 3 · 包 1，issue #5358）装配，
本模块只消费。

## 改价幅度（issue #5388 裁定 C）：数据源 = **审计日志**，不建改价流水表

`price_changes` 由装配层从 `audit_logs` 装配（`resource_type='agent_tool'` 且
`tool_name ∈ {product_update, sku_update}` —— 🔴 **两者都是改价**：商品级统一定价 / 单 SKU 调价，
只筛一个会**漏一半**），幅度取自审计行里的 `before_price` / `price` 真值。
两条**固有边界**（`RuleSpec.caveats`，始终可取、非 `wired` 时并入 `reason`，不许静默）：

1. 审计是 **fail-open**（3s 硬上限、允许丢行）⇒ 本项**只会漏报、不会误报**；
2. 审计留痕自 **#5303** 起才带 `before_price` ⇒ 无 `before_price` 的记录**不判定**
   （`judgeable_fields` 落成行级「未判定」+ `gaps` 点名），**不是「幅度 0」**。

🔴 **两种「没有改价记录」必须不同**（本单最易做错的一条）：**该租户从没改过价**（正常的空）
与**审计根本没在跑**（故障的空）在输出上长得一样。判据 = 租户级事实 `audit_tool_logging`
（窗口内是否存在**任意** `agent_tool` 审计行 = 审计上报在该租户上确实在产出）：
`true` ⇒ 正常的空（信封还是 `wired`，空命中可读成「这方面没问题」）；
`false` ⇒ `not_enabled` + 可行动的原因（**不许**读成「无异常」）；**缺省 ⇒ 未知**，不宣称「没开」。

## 让利幅度（`discount_over`）：数据源 = `orders.discount_amount`

幅度 = `discount_amount / total_amount`。语义是**经营洞察**（让利过多），
与「有人动了价」（内控）**互补，不是替代**。
它与改价那条的「空」**性质不同**：`orders` 是主库列（不是 fail-open 旁路）⇒ 数组已接入且完整时，
空命中**可信**（本窗口内确实没有让利）；其故障空是**结构性的**（数组没装配 ⇒ `not_wired`）。

🔴 **成本价（issue #5348）**：成本不在 `orders` 表上，而在 `product_skus.avg_cost`（移动加权）。
装配层**逐行解析 SKU**（① `processing_info.skuId` → ② 该商品**唯一** SKU → ③ 不可解析）后给出
`cost_amount = Σ(行数量 × 该行 avg_cost)`；**任一行不可解析、或该行 `avg_cost IS NULL` ⇒ 整单
`cost_amount = None`（整单不可判定）—— 不出部分和**（部分和把未知行当 0，沿用 `avg_cost` 既有口径
「不猜 0」）。两条与之配套的纪律：① **行级三态** —— 成本未知的行**不得**被当成「没低于成本」
（落 `incomplete` + `gaps` 点名，见 `judgeable_fields`）；② **`not_enabled`** —— 成本价字段在
（系统有），但该租户没有任何 `avg_cost IS NOT NULL` 的 SKU（= 没做成本核算）⇒ 与 `not_wired`
**并列、不可合并**：`not_wired` 不可行动（系统没做），`not_enabled` 可行动（用户能去开）。
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.tools.stock_semantics import LOW_STOCK_THRESHOLD

__all__ = [
    "MAX_EVIDENCE_ROWS",
    "UNSHIPPED_STATUSES",
    "WIRED",
    "NOT_WIRED",
    "NOT_ENABLED",
    "INCOMPLETE",
    "ProactiveConfig",
    "DEFAULT_CONFIG",
    "RuleSpec",
    "RULES",
    "proactive_status",
    "scan_snapshot",
    "daily_findings",
    "daily_findings_total",
]

#: 判据里逐条例出的观测值上限（超出以 `observed_total` 给全量计数）——防判据本身膨胀
MAX_EVIDENCE_ROWS = 10

#: 排序权重：紧急度 → 规则注册序（同权重时）；日期倒序在 `_ordered` 里叠加
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

#: 「该发货而未发货」的订单状态（`order_query` 的状态词表：confirmed=已确认(待发货)、producing=生产中）。
#: `pending`（待付款）不算 —— 未付款的订单催发货是噪音；`shipped`/`completed`/`cancelled` 更不算。
#: 另有 `shipped_at` 非空即视为已发货（双判据，状态漂移时不至于漏判）。
UNSHIPPED_STATUSES = frozenset({"confirmed", "producing"})


# ── 输入读取（容错，全部确定性：非数值/缺字段的行一律跳过，不猜）────────────────


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> Optional[_dt.date]:
    """ISO 时间串 ⇒ 日期（按其自带偏移取日期 ⇒ 与运行机器时区无关；这是确定性的前提）。"""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return _dt.date.fromisoformat(text[:10])
        except ValueError:
            return None


def _rows(snapshot: Any, key: str) -> List[Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get(key)
    if not isinstance(raw, (list, tuple)):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _ref(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


# ── 阈值配置（可配 + 边界判据）──────────────────────────────────────────────


@dataclass(frozen=True)
class ProactiveConfig:
    """规则阈值。默认值即产品口径；`from_dict` 供快照/调用方覆盖（租户级配置的落点）。"""

    #: 超 N 天未发货（严格大于 N 天 ⇒ N 天不命中、N+1 天命中）
    unshipped_days: int = 3
    #: 库存告急阈值（**含上界** `stock <= threshold`）—— 默认与 `low_stock_alert` 同源
    low_stock_threshold: int = LOW_STOCK_THRESHOLD
    #: 连续退货：同一客户/商品在窗口内退货 ≥ N 次
    repeat_return_count: int = 3
    #: 连续退货的观察窗口（天，含端点）
    repeat_return_window_days: int = 7
    #: 改价幅度阈值（百分比，保留 2 位小数后比较 ⇒ 恰等阈值不命中）
    price_change_pct: float = 30.0
    #: 让利幅度阈值（百分比；口径 = `discount_amount / total_amount`，issue #5388）
    discount_pct: float = 30.0
    #: 低于成本价的容忍额度（亏损额 **严格大于** 它才命中；0.0 = 只要低于成本就命中）
    below_cost_tolerance: float = 0.0
    #: 日报条数上限（「日报要窄」的机械落点；超出按紧急度截断）
    max_findings: int = 5

    def __post_init__(self) -> None:
        for name, value, low in (
            ("unshipped_days", self.unshipped_days, 1),
            ("low_stock_threshold", self.low_stock_threshold, 0),
            ("repeat_return_count", self.repeat_return_count, 2),
            ("repeat_return_window_days", self.repeat_return_window_days, 1),
            ("max_findings", self.max_findings, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < low:
                raise ValueError(f"{name} 必须是不小于 {low} 的整数，实得 {value!r}")
        for name, value in (
            ("price_change_pct", self.price_change_pct),
            ("discount_pct", self.discount_pct),
            ("below_cost_tolerance", self.below_cost_tolerance),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} 必须是非负数，实得 {value!r}")

    @classmethod
    def from_dict(cls, raw: Any) -> "ProactiveConfig":
        """按已知字段覆盖默认值；未知键忽略（向前兼容），非法值照抛（不静默退化）。"""
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


DEFAULT_CONFIG = ProactiveConfig()


# ── 命中（规则内部表示；装配成条目在 `_assemble`）──────────────────────────────


@dataclass(frozen=True)
class _Hit:
    """一条规则在**某个日期**上的命中：观测值已排序 ⇒ 装配结果逐字可复现。"""

    detected_on: str
    observed: Tuple[Dict[str, Any], ...]
    count: int
    amount: Optional[float]


@dataclass(frozen=True)
class RuleSpec:
    """具名规则。`detect` 是纯函数：同一 (snapshot, as_of, config) ⇒ 同一 `_Hit` 列表。"""

    rule_id: str
    rule_name: str
    severity: str
    #: 可复算判据的表达式（人可读、机器可比对；阈值与观测值分别给在 criterion 里）
    expression: str
    action_label: str
    action_url: str
    #: 影响面的计数单位（单 / 个 SKU / 笔退货 …）
    unit: str
    thresholds: Callable[[ProactiveConfig], Dict[str, Any]]
    title: Callable[[_Hit, ProactiveConfig], str]
    detect: Callable[[Any, _dt.date, ProactiveConfig], List[_Hit]]
    #: 规则的**输入契约**：`(快照行数组键, 必需行字段)`。接线状态的判据源就是它 ——
    #: 规则自己声明「读什么」，装配层声明「给什么」（`row_fields`），两边一比即知接没接上。
    requires: Tuple[str, Tuple[str, ...]]
    #: 用于**分组**的维度字段（缺值的行走不到该维度上）：不登记的话，「客户 × 商品」这种双维度规则
    #: 会被读成两个维度都接上了 —— 实际上缺商品的行只参与客户维度（本次不完整，见 `INCOMPLETE`）。
    dimensions: Tuple[str, ...] = ()
    #: **行级可判定性**（「没数据 ≠ 没问题」的**行级**版本，issue #5348）：`requires` 里这些字段在
    #: **本行**为空 ⇒ 该行落「**未判定**」（既不进命中、也不算「没问题」）。不登记 ⇒ 只按整数组/整字段判定。
    judgeable_fields: Tuple[str, ...] = ()
    #: **租户级前置**（`not_enabled` 的判据源，issue #5348）：`(快照键, 能力名, 开启指引)`。
    #: 快照键取值为布尔，由装配层**从事实推出**（不是人工配置项）：`False` ⇒「系统**有**这个能力，
    #: 是**该租户没开**」⇒ 落 `not_enabled`（带可行动的 `reason`）。键缺省/非布尔 ⇒ **不宣称**
    #: 「没开」（看不见的事实不是 `False`：滚动升级期的老快照按未知处理）。
    enabled_by: Optional[Tuple[str, str, str]] = None
    #: **数据源固有边界**（issue #5388）：与「本次是否完整」无关 —— 它是这个源**永远**带的性质
    #: （如审计是 fail-open ⇒ 只可能漏报）。始终随 status 条目给出（`caveats`），
    #: **非 `wired` 时并入 `reason`** ⇒ 边界不会因为「今天恰好完整」而消失。
    #: 🔴 它**不进** `reason` 的 `wired` 分支（不变式 `reason is None` ⟺ `wired` 不开例外）。
    caveats: Tuple[str, ...] = ()


# ── 六条规则（首批五条 + #5388 的 `price_change_over` 改数据源 / `discount_over` 新增）────


def _detect_below_cost(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows(snapshot, "orders"):
        sale, cost = _num(row.get("sale_amount")), _num(row.get("cost_amount"))
        if sale is None or cost is None:
            continue
        loss = cost - sale
        if loss <= cfg.below_cost_tolerance:
            continue
        day, ref = _day(row.get("created_at")), _ref(row, "order_no", "id")
        if day is None or not ref:
            continue
        grouped.setdefault(day.isoformat(), []).append(
            {"ref": ref, "sale_amount": sale, "cost_amount": cost, "loss": round(loss, 2)}
        )
    return [
        _Hit(date, tuple(sorted(rows, key=lambda r: r["ref"])), len(rows),
             round(sum(r["loss"] for r in rows), 2))
        for date, rows in grouped.items()
    ]


def _detect_unshipped(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    """状态型规则：异常**在扫描基准日仍然成立** ⇒ 命中日期 = 基准日。"""
    observed: List[Dict[str, Any]] = []
    for row in _rows(snapshot, "orders"):
        if row.get("shipped_at") or str(row.get("status") or "") not in UNSHIPPED_STATUSES:
            continue
        day, ref = _day(row.get("created_at")), _ref(row, "order_no", "id")
        if day is None or not ref:
            continue
        days = (as_of - day).days
        if days <= cfg.unshipped_days:
            continue
        observed.append({"ref": ref, "days": days, "amount": _num(row.get("sale_amount"))})
    if not observed:
        return []
    observed.sort(key=lambda r: r["ref"])
    amounts = [r["amount"] for r in observed if r["amount"] is not None]
    return [_Hit(as_of.isoformat(), tuple(observed), len(observed),
                 round(sum(amounts), 2) if amounts else None)]


def _detect_low_stock(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    """状态型规则；口径 = `stock <= threshold`（**含上界**），与 `low_stock_alert` 同源。"""
    observed: List[Dict[str, Any]] = []
    for row in _rows(snapshot, "skus"):
        stock, ref = _num(row.get("stock")), _ref(row, "sku_id", "id")
        if stock is None or not ref or stock > cfg.low_stock_threshold:
            continue
        observed.append({
            "ref": ref,
            "product_id": row.get("product_id"),
            "product_name": row.get("product_name"),
            "stock": stock,
            "threshold": cfg.low_stock_threshold,
        })
    if not observed:
        return []
    observed.sort(key=lambda r: r["ref"])
    return [_Hit(as_of.isoformat(), tuple(observed), len(observed), None)]


def _detect_repeat_returns(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    """事件型规则：同一**客户**或同一**商品**在 W 天窗口内退货 ≥ N 次 ⇒ 按窗口末日命中。"""
    rows: List[Dict[str, Any]] = []
    for row in _rows(snapshot, "returns"):
        day, ref = _day(row.get("returned_at")), _ref(row, "return_no", "id")
        if day is None or not ref:
            continue
        rows.append({"ref": ref, "day": day, "row": row})
    rows.sort(key=lambda r: (r["day"], r["ref"]))

    # 命中主体：key = (命中日期, 主体类型, 主体标识) → 窗口内的退货行
    hits: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for field, subject_type in (("customer_id", "customer"), ("product_id", "product")):
        for row in rows:
            subject = str(row["row"].get(field) or "")
            if not subject:
                continue
            window_start = row["day"] - _dt.timedelta(days=cfg.repeat_return_window_days - 1)
            in_window = [
                other for other in rows
                if window_start <= other["day"] <= row["day"]
                and str(other["row"].get(field) or "") == subject
            ]
            if len(in_window) >= cfg.repeat_return_count:
                hits[(row["day"].isoformat(), subject_type, subject)] = in_window

    grouped: Dict[str, List[Tuple[str, str, str]]] = {}
    for key in hits:
        grouped.setdefault(key[0], []).append(key)

    result: List[_Hit] = []
    for date in sorted(grouped):
        subjects = sorted(grouped[date])
        refs = sorted({r["ref"] for key in subjects for r in hits[key]})
        amounts = [_num(r["row"].get("amount")) for key in subjects for r in hits[key]]
        result.append(_Hit(
            date,
            tuple({
                "subject_type": subject_type,
                "subject_id": subject,
                "count": len(hits[(date, subject_type, subject)]),
                "window_days": cfg.repeat_return_window_days,
                "window_end": date,
            } for _, subject_type, subject in subjects),
            len(refs),
            round(sum(a for a in amounts if a is not None), 2) if all(a is not None for a in amounts) else None,
        ))
    return result


def _detect_price_change(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    """改价幅度（issue #5388）：行来自**审计日志**（`tool_name ∈ {product_update, sku_update}`）。

    🔴 键名逐字 = 落库真值（`before_price` / `new_price`）：缺 `before_price` 的行
    （#5303 之前的改价、或脱敏期落库的历史行）在本层被跳过 —— 但**不是静默的**：
    `judgeable_fields` 把它们登记为「未判定」，`proactive_status` 据此落 `incomplete` + `gaps`。

    行来自**两条腿、一个数组**（#5388 审计腿 + #5411 批量腿，装配层合并）⇒ 本层对 `tool_name`
    **不设限**：谁在这里加「只认审计工具」这类过滤，批量降价就会重新变成发现不了的改价。
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows(snapshot, "price_changes"):
        before, new = _num(row.get("before_price")), _num(row.get("new_price"))
        if before is None or new is None or before <= 0:
            continue
        # 保留 2 位小数后比较 ⇒ 「恰等阈值」不命中（浮点毛刺不改变边界行为）
        pct = round(abs(new - before) / before * 100, 2)
        if pct <= cfg.price_change_pct:
            continue
        day, ref = _day(row.get("changed_at")), _ref(row, "change_no", "id")
        if day is None or not ref:
            continue
        grouped.setdefault(day.isoformat(), []).append({
            "ref": ref,
            "tool_name": row.get("tool_name"),
            "product_id": row.get("product_id"),
            "before_price": before,
            "new_price": new,
            "pct": pct,
        })
    result: List[_Hit] = []
    for date, rows in grouped.items():
        rows.sort(key=lambda r: r["ref"])
        result.append(_Hit(date, tuple(rows), len(rows),
                           round(sum(abs(r["new_price"] - r["before_price"]) for r in rows), 2)))
    return result


def _detect_discount(snapshot: Any, as_of: _dt.date, cfg: ProactiveConfig) -> List[_Hit]:
    """让利幅度（issue #5388）：`discount_amount / total_amount > discount_pct`（`orders` 主库列）。

    语义 = **经营洞察**（这单让利过多），与 `price_change_over`（内控：有人动了价）互补。
    分母未知（`total_amount` 缺/非数）或 ≤ 0 的行**不判定**（不许当成 100%）——
    登记在 `judgeable_fields` 里，由 `proactive_status` 落成「未判定」。
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows(snapshot, "order_discounts"):
        total, discount = _num(row.get("total_amount")), _num(row.get("discount_amount"))
        if total is None or discount is None or total <= 0:
            continue
        pct = round(discount / total * 100, 2)
        if pct <= cfg.discount_pct:
            continue
        day, ref = _day(row.get("created_at")), _ref(row, "order_no", "id")
        if day is None or not ref:
            continue
        grouped.setdefault(day.isoformat(), []).append({
            "ref": ref,
            "total_amount": total,
            "discount_amount": discount,
            "pct": pct,
        })
    result: List[_Hit] = []
    for date, rows in grouped.items():
        rows.sort(key=lambda r: r["ref"])
        result.append(_Hit(date, tuple(rows), len(rows),
                           round(sum(r["discount_amount"] for r in rows), 2)))
    return result


RULES: Tuple[RuleSpec, ...] = (
    RuleSpec(
        rule_id="below_cost_price",
        rule_name="低于成本价的订单",
        severity="high",
        expression="cost_amount - sale_amount > below_cost_tolerance",
        action_label="去核对订单成本价",
        action_url="/orders",
        unit="单",
        thresholds=lambda cfg: {"below_cost_tolerance": cfg.below_cost_tolerance},
        title=lambda hit, cfg: f"{hit.count} 单成交价低于成本，合计亏损 {hit.amount:.2f} 元",
        detect=_detect_below_cost,
        # 🔴 成本价来自 `product_skus.avg_cost`（#5348）—— 装配层逐行解析 SKU 后给出 Σ 行成本；
        # 租户级前置与行级可判定性各只有一份声明（`enabled_by` / `judgeable_fields`）。
        requires=("orders", ("order_no", "sale_amount", "cost_amount")),
        judgeable_fields=("cost_amount",),
        enabled_by=("cost_accounting", "成本核算",
                    "在商品入库时录入单价（系统按移动加权算出成本价）"),
    ),
    RuleSpec(
        rule_id="unshipped_overdue",
        rule_name="超 N 天未发货",
        severity="high",
        expression="days(as_of - created_at) > unshipped_days",
        action_label="去处理待发货订单",
        action_url="/orders?status=待发货",
        unit="单",
        thresholds=lambda cfg: {"unshipped_days": cfg.unshipped_days},
        title=lambda hit, cfg: f"{hit.count} 单已超 {cfg.unshipped_days} 天未发货",
        detect=_detect_unshipped,
        requires=("orders", ("order_no", "status", "created_at", "shipped_at")),
    ),
    RuleSpec(
        rule_id="low_stock",
        rule_name="库存告急",
        severity="medium",
        expression="sku.stock <= low_stock_threshold",
        action_label="去看低库存商品",
        action_url="/products?low_stock=true",
        unit="个 SKU",
        thresholds=lambda cfg: {"low_stock_threshold": cfg.low_stock_threshold},
        title=lambda hit, cfg: f"{hit.count} 个 SKU 库存告急（≤ {cfg.low_stock_threshold}）",
        detect=_detect_low_stock,
        requires=("skus", ("sku_id", "stock")),
    ),
    RuleSpec(
        rule_id="repeat_returns",
        rule_name="连续退货",
        severity="high",
        expression=(
            "count(returns of same customer|product within repeat_return_window_days) "
            ">= repeat_return_count"
        ),
        action_label="去查看退货工单",
        action_url="/after-sales",
        unit="笔退货",
        thresholds=lambda cfg: {
            "repeat_return_count": cfg.repeat_return_count,
            "repeat_return_window_days": cfg.repeat_return_window_days,
        },
        title=lambda hit, cfg: (
            f"{hit.count} 笔退货触发连续退货（同一客户或商品，{cfg.repeat_return_window_days} 天内 ≥ "
            f"{cfg.repeat_return_count} 次）"
        ),
        detect=_detect_repeat_returns,
        requires=("returns", ("return_no", "customer_id", "product_id", "returned_at")),
        # 退货事实按「同一客户」或「同一商品」两个维度分组：缺 product_id 的行（多商品订单的退货）
        # 只参与客户维度 ⇒ 必须显式登记为「本次不完整」，不许读成商品维度也接上了。
        dimensions=("customer_id", "product_id"),
    ),
    RuleSpec(
        rule_id="price_change_over",
        rule_name="改价幅度超阈值",
        severity="medium",
        expression="abs(new_price - before_price) / before_price * 100 > price_change_pct",
        action_label="去核对改价记录",
        action_url="/products",
        unit="笔",
        thresholds=lambda cfg: {"price_change_pct": cfg.price_change_pct},
        title=lambda hit, cfg: f"{hit.count} 笔改价幅度超 {cfg.price_change_pct:g}%",
        detect=_detect_price_change,
        # 🔴 取数面**两条腿**（issue #5388 + #5411），行数组只有**一个**（不另立第二套）：
        # · 审计腿：`resource_type='agent_tool'` + `tool_name ∈ {product_update, sku_update}`
        #   （**两者都是改价**，只筛一个会漏一半）；
        # · 批量腿：`agent_batches.batch_type='product_price'` × `agent_batch_items`
        #   （`old_value`/`new_value`，按 V127 的字段/状态白名单筛）—— 批量执行时审计行里没有价格。
        requires=("price_changes", ("change_no", "before_price", "new_price", "changed_at")),
        # 行级可判定性：缺 before_price（#5303 之前的改价）/ 缺 new_price（脱敏期历史行）⇒ **未判定**
        judgeable_fields=("before_price", "new_price"),
        # 租户级前置 = **审计上报在本租户上确实在产出**（窗口内有任意 agent_tool 审计行）：
        # false ⇒ 「从没改过价」与「审计没在跑」不可分 ⇒ not_enabled（不是「无异常」）。
        enabled_by=("audit_tool_logging", "写工具审计留痕",
                    "让米宝或员工通过 AI 助手至少执行一次写操作（如改价）以产生审计留痕；"
                    "若你确实用过写操作而这里仍为空，说明审计上报没有在跑（该通道 fail-open、可能丢行），"
                    "请联系技术支持排查"),
        caveats=(
            "审计上报是 fail-open（3s 硬上限、允许丢行）⇒ 本项**可能漏报**；审计只记「调用过」，"
            "而 `success=false`（服务端拒绝 / 工具抛错）的调用**不算改价**（价根本没变）"
            "⇒ 本项不会把失败的改价报成改价",
            "审计留痕自 #5303 起才带改价真值：更早的改价没有 before_price ⇒ 那类记录**不判定**（不是幅度 0）",
            "批量改价（product_batch_update）**在射程内**，但取数面与审计腿不同：它走批次明细 "
            "agent_batch_items 的 old_value / new_value（执行批量时参数只有 batch_id，审计行里没有价格可落）"
            "；「从未生效」的条目（pending / failed / skipped）不算改价，**已撤销的批次仍算**（价确实动过）"
            "；审计腿的租户级前置（audit_tool_logging）**只管审计腿** —— 它 false 时批量腿不受影响，"
            "该租户仍可能因批量改价而命中（那种情形下「本次未判定」只对审计腿成立）",
            "覆盖面仍窄于「所有改价」：只覆盖经米宝执行的 product_update / sku_update / "
            "product_batch_update 三条路径；product_manage（能改 basePrice，但改前价不可得 ⇒ 幅度不可判定）"
            "与后台页面直接改价（不经 Agent ⇒ 不写 agent_tool 审计）是本项**显式豁免**的两条路径"
            "（豁免在册 + 理由，见 app/tools/registry.py 的 _UNTRACKED_PRICE_PATHS）",
            "改前价由模型据 product_detail 的当前价填写（#5303 起必填），服务端按值回查（#5317）**不符即拒**"
            " ⇒ 被拒的调用不入本项；幅度取**落库真值**（审计腿 = action_details.priceChange，"
            "批量腿 = agent_batch_items 的 old/new 值）",
        ),
    ),
    RuleSpec(
        rule_id="discount_over",
        rule_name="让利幅度超阈值",
        severity="medium",
        expression="discount_amount / total_amount * 100 > discount_pct",
        action_label="去核对让利订单",
        action_url="/orders",
        unit="单",
        thresholds=lambda cfg: {"discount_pct": cfg.discount_pct},
        title=lambda hit, cfg: f"{hit.count} 单让利超 {cfg.discount_pct:g}%（合计让利 {hit.amount:.2f} 元）",
        detect=_detect_discount,
        # 数据源 = `orders.discount_amount`（主库列，**不是** fail-open 旁路）：数组只装配
        # 窗口内**有让利**的订单（0 让利不可能命中）⇒ 已接入且完整时空命中可信。
        requires=("order_discounts", ("order_no", "total_amount", "discount_amount", "created_at")),
        # 可空/可缺：`discount_amount` 默认 0、`total_amount` 未知时**分母未知** ⇒ 未判定（不是 100%）
        judgeable_fields=("discount_amount", "total_amount"),
        caveats=(
            "折扣取自 orders.discount_amount（建单录入的应收−实收差额，**默认 0**）："
            "从未录入过优惠的老订单，其 0 是默认值 ⇒ 本项对历史订单偏漏报",
            "该数组只含窗口内**有让利**的订单（0 让利不可能命中）⇒ 已接入且完整时，空命中 = 本窗口内确实没有让利",
        ),
    ),
)


# ── 装配与扫描 ──────────────────────────────────────────────────────────────


#: 接线状态的取值（逐规则）：
#: · `wired` = 输入已接入**且本次完整** ⇒ 空命中才等于「这方面没问题」；
#: · `not_wired` = 该能力**尚未接入**（结构性缺数组/字段）；
#: · `not_enabled` = 系统**有**这个能力，但**该租户没开**（issue #5348：如未做成本核算）
#:   ⇒ 空命中**不可**读成「没问题」，但它是**可行动**的（去开启），与 `not_wired`（不可行动）不可合并；
#: · `incomplete` = 接上了但**本次不完整**（行数被上限截断 / 分组维度在部分行上缺值 / 有行未判定）
#:   ⇒ 空命中仍**不可**读成「没问题」（「截断必须显式」—— 有界不许变成静默少报）。
WIRED = "wired"
NOT_WIRED = "not_wired"
NOT_ENABLED = "not_enabled"
INCOMPLETE = "incomplete"


def _declared_fields(snapshot: Any, key: str) -> Optional[set]:
    """装配层声明的行字段集；`None` = 该数组未接入本次快照。

    `row_fields` 是装配层的**自描述**（它真的产出了哪些字段），显式声明**优先**（声明里没有的字段
    就是没有，不靠「某一行碰巧带上」）；没有自描述时（滚动升级期老快照 / 手工快照）退回**实际行的
    字段并集** —— 否则已接线的规则会被读成未接线。
    """
    if not isinstance(snapshot, dict):
        return None
    declared = snapshot.get("row_fields")
    if isinstance(declared, dict):
        fields_ = declared.get(key)
        return {str(name) for name in fields_} if isinstance(fields_, (list, tuple)) else None
    rows = _rows(snapshot, key)
    return {str(name) for row in rows for name in row} if rows else None


def _row_meta(snapshot: Any, key: str) -> Dict[str, Any]:
    """装配层对该行数组的**元信息**（`row_meta`）：行数上限 / 实际行数 / 是否被截断。

    缺省（老快照没有 `row_meta`）按「未截断」处理 —— 那是**未知**，不是「已确认完整」；
    自描述的旧版字段（`row_fields`）同样是尽力而为，故两者都只用于**发现**问题，不用于宣称完整。
    """
    if not isinstance(snapshot, dict):
        return {}
    meta = snapshot.get("row_meta")
    entry = meta.get(key) if isinstance(meta, dict) else None
    return entry if isinstance(entry, dict) else {}


def _tenant_fact(snapshot: Any, key: str) -> Optional[bool]:
    """快照里的**租户级事实**（布尔）：`True` / `False`；缺省或非布尔 ⇒ `None`（**未知**）。

    🔴 未知**不**当作 `False` —— 看不见的事实不是「该租户没开」：老快照（滚动升级期）没有这个键，
    读成 `False` 会把**已开启**的租户误报成「你还没开启」（正是本单要治的
    「不同性质的『没有』不能共用一个说法」）。
    """
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    return value if isinstance(value, bool) else None


def proactive_status(
    snapshot: Any, rules: Sequence[RuleSpec] = RULES
) -> Dict[str, Dict[str, Any]]:
    """**逐规则**接线状态 + 不可用/不完整原因（issue #5358/#5348）—— 治「两种空在输出上等价」（#5348）。

    为什么**逐规则**而不是一个整体状态：**部分接线是可能的**（首批 5 条里 4 条能接、1 条结构上
    接不通），整体布尔到了调用方还是分不出「哪一条没接线」——那就又变回「空命中 = 今天没问题」。

    返回 `{rule_id: {"rule_id", "rule_name", "status", "reason", "missing", "gaps", "caveats"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（系统未实现）, `not_enabled`（系统有、该租户没开）,
    `incomplete`（本次不完整）}；
    不变式：**`reason is None` ⟺ `status == wired`**（`not_enabled` **不开例外**）—— 调用方只要看这一条，
    就知道空命中能不能读成「没问题」。`missing` = 缺的数组/字段；`gaps` = 不完整的具体原因
    （截断 / 维度缺值 / **有行未判定**）；`caveats` = **数据源固有边界**（issue #5388：如审计是
    fail-open ⇒ 只可能漏报）—— 它**恒在**（可为空列表），非 `wired` 时并入 `reason`，
    `wired` 时只以 `caveats` 出现（不变式不给 `wired` 开例外，但边界也不许因此静默）。

    纯函数、只读：同一 `(snapshot, rules)` ⇒ 同一结果，与命中集合互不影响
    （接线状态不改判据、不改命中）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for spec in rules:
        key, needed = spec.requires
        available = _declared_fields(snapshot, key)
        gaps: List[str] = []
        if available is None:
            value, missing = NOT_WIRED, [key]
            reason = f"快照未提供 {key} 行数组（装配层未接线）"
        else:
            missing = [name for name in needed if name not in available]
            if missing:
                value = NOT_WIRED
                reason = f"快照 {key} 行缺字段 {'、'.join(missing)}（数据层无此来源）"
            elif spec.enabled_by and _tenant_fact(snapshot, spec.enabled_by[0]) is False:
                # 🔴 系统**有**这个能力，是**该租户没开**（issue #5348）：与 `not_wired` **并列、不可合并**
                # —— not_wired 不可行动（系统没做），这里可行动（用户能去开），reason 本身就是那句引导。
                fact_key, ability, guidance = spec.enabled_by
                missing = []
                value = NOT_ENABLED
                reason = (
                    f"你还没开启{ability}（快照 {fact_key}=false）⇒ {spec.rule_name}本次未判定；"
                    f"{guidance}后即可开启"
                )
            else:
                # 接上了也可能**本次不完整**：行数被上限截断、分组维度在部分行上缺值、或**有行未判定**。
                # 🔴 不显式登记的话，「有界」（热路径必须）就变成了新的静默少报面。
                meta = _row_meta(snapshot, key)
                if meta.get("truncated"):
                    gaps.append(
                        f"{key} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
                        f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
                    )
                rows = _rows(snapshot, key)
                for name in spec.dimensions:
                    blank = sum(1 for row in rows if row.get(name) in (None, ""))
                    if blank:
                        gaps.append(
                            f"{key} 行有 {blank} 行缺 {name}（那些行只参与其它维度的判定）"
                        )
                for name in spec.judgeable_fields:
                    # 🔴 「没数据 ≠ 没问题」的**行级**版本：字段本行为空的行**未判定** ——
                    # 既不进命中，也**不许**被当成「没命中（= 没问题）」。
                    unknown = sum(1 for row in rows if row.get(name) is None)
                    if unknown:
                        gaps.append(
                            f"{key} 行有 {unknown} 行的 {name} 为空（**未判定**，不得读成「没命中」）"
                        )
                value = INCOMPLETE if gaps else WIRED
                reason = "；".join(gaps) if gaps else None
        status[spec.rule_id] = {
            "rule_id": spec.rule_id,
            "rule_name": spec.rule_name,
            "status": value,
            # 固有边界并入原因（#5388）：非 wired 时调用方只读 reason 也不会漏掉边界；
            # wired 时 reason 保持 None（不变式），边界仍由 `caveats` 给出 ⇒ 两头都不静默。
            "reason": reason if reason is None or not spec.caveats
                      else "；".join([reason, *spec.caveats]),
            "missing": missing,
            "gaps": gaps,
            "caveats": list(spec.caveats),
        }
    return status


def _resolve_config(snapshot: Any, config: Optional[ProactiveConfig]) -> ProactiveConfig:
    if config is not None:
        return config
    return ProactiveConfig.from_dict(snapshot.get("config") if isinstance(snapshot, dict) else None)


def _resolve_as_of(snapshot: Any, as_of: Any) -> Optional[_dt.date]:
    if as_of is not None:
        return _day(as_of)
    return _day(snapshot.get("biz_date") if isinstance(snapshot, dict) else None)


def _assemble(spec: RuleSpec, hit: _Hit, cfg: ProactiveConfig) -> Optional[Dict[str, Any]]:
    """装配一条命中条目（三件套）。🔴 没有处置入口 ⇒ 返回 None（不发）。"""
    if not (spec.action_label and spec.action_url):
        return None
    return {
        "rule_id": spec.rule_id,
        "rule_name": spec.rule_name,
        "severity": spec.severity,
        "detected_on": hit.detected_on,
        "title": spec.title(hit, cfg),
        "criterion": {
            "expression": spec.expression,
            "thresholds": spec.thresholds(cfg),
            "observed": list(hit.observed[:MAX_EVIDENCE_ROWS]),
            "observed_total": len(hit.observed),
        },
        "impact": {
            "count": hit.count,
            "unit": spec.unit,
            "amount": hit.amount,
            "amount_unit": "元",
        },
        "action": {"label": spec.action_label, "url": spec.action_url},
    }


def scan_snapshot(
    snapshot: Any,
    config: Optional[ProactiveConfig] = None,
    as_of: Any = None,
    rules: Sequence[RuleSpec] = RULES,
) -> List[Dict[str, Any]]:
    """确定性扫描：全量命中共（含历史异常），按 日期倒序 → 紧急度 → 规则注册序。

    无扫描基准日（快照无 `biz_date` 且未传 `as_of`）⇒ 返回空集合 —— 「当天」判不出来时**不猜**。
    """
    day = _resolve_as_of(snapshot, as_of)
    if day is None:
        return []
    cfg = _resolve_config(snapshot, config)
    items: List[Tuple[int, int, str, Dict[str, Any]]] = []
    for index, spec in enumerate(rules):
        for hit in spec.detect(snapshot, day, cfg):
            finding = _assemble(spec, hit, cfg)
            if finding is None:
                continue
            items.append((_SEVERITY_RANK.get(spec.severity, 9), index, hit.detected_on, finding))
    # 两次稳定排序：先 (紧急度, 注册序)，再叠 日期倒序 ⇒ 同日内仍按紧急度
    items.sort(key=lambda item: (item[0], item[1]))
    items.sort(key=lambda item: item[2], reverse=True)
    return [item[3] for item in items]


def daily_findings(
    snapshot: Any,
    config: Optional[ProactiveConfig] = None,
    as_of: Any = None,
    rules: Sequence[RuleSpec] = RULES,
) -> List[Dict[str, Any]]:
    """**日报视图**：只保留当天成立的异常，并按紧急度截断到 `max_findings`。

    与 `scan_snapshot` 同源同判据，唯一差别是「窄」：历史异常在全量视图里在、在这里必不在。
    ⚠️ 这个截断是**展示口径**（「日报要窄」），不是「今天只有这么多」—— 真实条数见
    `daily_findings_total()`（同一份当天过滤实现，不另写一份）。
    """
    return _today_findings(snapshot, config, as_of, rules)[
        : _resolve_config(snapshot, config).max_findings
    ]


def daily_findings_total(
    snapshot: Any,
    config: Optional[ProactiveConfig] = None,
    as_of: Any = None,
    rules: Sequence[RuleSpec] = RULES,
) -> int:
    """日报口径下**当天**成立的异常**真实条数**（未按 `max_findings` 截断）。

    「日报要窄」不许变成「静默少报」：条数被上限截断时，调用方必须能说出真实条数
    （工具消息据此点出「日报只列前 N 项，当天共 M 项」）。
    """
    return len(_today_findings(snapshot, config, as_of, rules))


def _today_findings(
    snapshot: Any,
    config: Optional[ProactiveConfig],
    as_of: Any,
    rules: Sequence[RuleSpec],
) -> List[Dict[str, Any]]:
    """当天成立的异常（**唯一实现**：`daily_findings` 与 `daily_findings_total` 共用，不许各写一份）。"""
    day = _resolve_as_of(snapshot, as_of)
    if day is None:
        return []
    today = day.isoformat()
    return [
        f for f in scan_snapshot(snapshot, config=config, as_of=day, rules=rules)
        if f["detected_on"] == today
    ]
