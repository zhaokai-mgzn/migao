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
  "orders":   [{"order_no", "status", "customer_id", "created_at", "shipped_at",
                "sale_amount", "cost_amount"}],              # 低于成本价 / 超 N 天未发货
  "skus":     [{"sku_id", "product_id", "product_name", "stock"}],  # 库存告急（stock ≤ 阈值）
  "returns":  [{"return_no", "customer_id", "product_id", "returned_at", "amount"}],
  "price_changes": [{"change_no", "order_no", "product_id",
                     "original_price", "new_price", "changed_at"}],
}
```

行数组缺省 = 该规则无输入 ⇒ **不命中**。这与「命中 0 条」在输出上等价，但语义不同：
**「没数据」不等于「没问题」** —— 调用方不得把空命中读成「今天一切正常」。

⇒ 那个语义差别由 `proactive_status()` 落成**数据层可分**（逐规则 `wired` / `not_wired` + 原因）：
判据 = 「规则声明的输入」（`RuleSpec.requires`）×「装配层声明的产出」（`row_fields`），
**两侧各只有一份声明**，没有第二份口径；老快照没有 `row_fields` 时按实际行的字段并集兜底
（滚动升级期不至于把已接线的规则读成未接线）。

数据来源：admin-api 聚合层（`DailyBriefingService.aggregateSnapshot`）落库的 `source_snapshot`
—— 与经营日报**同源**，故两个入口口径一致（设计文档 §三 族 3 末「同一内核、两种消费形态」）。
快照内的行级数组（orders / skus / returns）由跨域视图内核（族 3 · 包 1，issue #5358）装配，
本模块只消费。两条**结构性不可达**（如实登记，不是静默失效）：全仓无改价流水表 ⇒ `price_changes`
永不出现；`orders` 表无成本列 ⇒ `orders` 行**没有 `cost_amount`** ⇒ `below_cost_price` 接不通
—— 两条都在未接线清单里（**不是「命中 0 条」**）。
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
    "ProactiveConfig",
    "DEFAULT_CONFIG",
    "RuleSpec",
    "RULES",
    "proactive_status",
    "scan_snapshot",
    "daily_findings",
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


# ── 五条首批规则 ────────────────────────────────────────────────────────────


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
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows(snapshot, "price_changes"):
        original, new = _num(row.get("original_price")), _num(row.get("new_price"))
        if original is None or new is None or original <= 0:
            continue
        # 保留 2 位小数后比较 ⇒ 「恰等阈值」不命中（浮点毛刺不改变边界行为）
        pct = round(abs(new - original) / original * 100, 2)
        if pct <= cfg.price_change_pct:
            continue
        day, ref = _day(row.get("changed_at")), _ref(row, "change_no", "id")
        if day is None or not ref:
            continue
        grouped.setdefault(day.isoformat(), []).append({
            "ref": ref,
            "order_no": row.get("order_no"),
            "product_id": row.get("product_id"),
            "original_price": original,
            "new_price": new,
            "pct": pct,
        })
    result: List[_Hit] = []
    for date, rows in grouped.items():
        rows.sort(key=lambda r: r["ref"])
        result.append(_Hit(date, tuple(rows), len(rows),
                           round(sum(abs(r["new_price"] - r["original_price"]) for r in rows), 2)))
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
        # 🔴 成本价：`orders` 表**无成本列** ⇒ 该规则结构性接不通（未接线清单，不是「命中 0 条」）
        requires=("orders", ("order_no", "sale_amount", "cost_amount")),
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
    ),
    RuleSpec(
        rule_id="price_change_over",
        rule_name="改价幅度超阈值",
        severity="medium",
        expression="abs(new_price - original_price) / original_price * 100 > price_change_pct",
        action_label="去核对改价订单",
        action_url="/orders",
        unit="笔",
        thresholds=lambda cfg: {"price_change_pct": cfg.price_change_pct},
        title=lambda hit, cfg: f"{hit.count} 笔改价幅度超 {cfg.price_change_pct:g}%",
        detect=_detect_price_change,
        # 🔴 全仓无改价流水表 ⇒ `price_changes` 数组永不装配 ⇒ 该规则结构性接不通（同上）
        requires=("price_changes", ("change_no", "original_price", "new_price", "changed_at")),
    ),
)


# ── 装配与扫描 ──────────────────────────────────────────────────────────────


#: 接线状态的取值（逐规则）：`wired` = 该规则的输入已接入本次快照；`not_wired` = 该能力**尚未接入**
#: （⇒ 空命中**不代表**这方面没问题）；已接线但当天无命中仍是 `wired` —— 两类在数据层可分。
WIRED = "wired"
NOT_WIRED = "not_wired"


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


def proactive_status(
    snapshot: Any, rules: Sequence[RuleSpec] = RULES
) -> Dict[str, Dict[str, Any]]:
    """**逐规则**接线状态 + 未接线原因（issue #5358）—— 治「两种空在输出上等价」（#5348）。

    为什么**逐规则**而不是一个整体状态：**部分接线是可能的**（首批 5 条里 3 条能接、2 条结构上
    接不通），整体布尔到了调用方还是分不出「哪一条没接线」——那就又变回「空命中 = 今天没问题」。

    返回 `{rule_id: {"rule_id", "rule_name", "status", "reason", "missing"}}`：
    `status` ∈ {`wired`, `not_wired`}；`not_wired` 必带 `reason` 与 `missing`（缺哪个数组/字段），
    `wired` 的 `reason` 恒为 `None`。纯函数、只读：同一 `(snapshot, rules)` ⇒ 同一结果，
    与命中集合互不影响（接线状态不改判据、不改命中）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for spec in rules:
        key, needed = spec.requires
        available = _declared_fields(snapshot, key)
        if available is None:
            value, missing = NOT_WIRED, [key]
            reason = f"快照未提供 {key} 行数组（装配层未接线）"
        else:
            missing = [name for name in needed if name not in available]
            value = NOT_WIRED if missing else WIRED
            reason = f"快照 {key} 行缺字段 {'、'.join(missing)}（数据层无此来源）" if missing else None
        status[spec.rule_id] = {
            "rule_id": spec.rule_id,
            "rule_name": spec.rule_name,
            "status": value,
            "reason": reason,
            "missing": missing,
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
    """
    day = _resolve_as_of(snapshot, as_of)
    if day is None:
        return []
    today = day.isoformat()
    findings = [
        f for f in scan_snapshot(snapshot, config=config, as_of=day, rules=rules)
        if f["detected_on"] == today
    ]
    return findings[: _resolve_config(snapshot, config).max_findings]
