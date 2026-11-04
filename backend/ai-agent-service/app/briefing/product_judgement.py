"""商品健康度 · 判断层（同行基线 + 分档 verdict）—— issue #8290 从 product_health.py 拆出

判据来源：issue #8234（同行基线）· #8293 + 缺陷 #8280（方向**登记即契约**）。本模块只依赖
`app.briefing.product_numbers`，**不 import 视图模块**（拆分前它与视图同住 —— 那正是循环依赖，
见 issue #8290）。对外名字仍由门面 `app/briefing/product_health.py` 原样再导出。

## 为什么方向不能由调用方传参（#8280 的机制）

`_verdict` 原本只为退货率写（「越小越好」），毛利复制粘贴调用时**忘了传方向**，于是毛利越低越判「好」，
而**那条单测也一起写反了**，CI 一直是绿的。⇒ 方向必须来自 `METRIC_DIRECTIONS`：调用方连传错的机会都没有；
新指标没登记 ⇒ `KeyError` ⇒ 当场红。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.briefing.product_numbers import _out

#: 判定所需的最小有效样本量：少于它 ⇒ `unknown`（**样本太少不装懂**）
MIN_BASELINE_SAMPLE = 5

VERDICT_GOOD = "good"
VERDICT_WATCH = "watch"
VERDICT_BAD = "bad"
VERDICT_UNKNOWN = "unknown"

#: 基线性质自述（纪律 3：别让调用方把「相对」读成「绝对」）
BASELINE_BASIS = (
    "同行基线 = 同一份快照内全部 SKU 的中位数（peer_median）/ 上四分位（peer_p75，最近秩法）；"
    "这是**相对**判断、**非绝对**标准 —— 全店整体偏高时，相对 good 不代表单店健康"
)


def _median(values: List[Decimal]) -> Optional[Decimal]:
    """中位数（奇数取中位、偶数取中间两数均值）；空集 ⇒ `None`。"""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _p75(values: List[Decimal]) -> Optional[Decimal]:
    """上四分位（最近秩法，NIST 口径）：取第 `ceil(0.75n)` 个（1-based）；空集 ⇒ `None`。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = -((-3 * len(ordered)) // 4)  # ceil(3n/4)，不引入 math
    return ordered[max(0, min(rank - 1, len(ordered) - 1))]


def _peer_baseline(values: List[Optional[float]]) -> Optional[Dict[str, Any]]:
    """`{peer_median, peer_p75, sample_size}`；`None` 值**不进样本**，样本不足 ⇒ `None`。"""
    known = [Decimal(str(value)) for value in values if value is not None]
    if len(known) < MIN_BASELINE_SAMPLE:
        return None
    return {
        "peer_median": _out(_median(known)),
        "peer_p75": _out(_p75(known)),
        "sample_size": len(known),
    }


#: 指标方向 —— **登记即契约**（issue #8293）。
#:
#: 为什么方向不能由调用方传参：缺陷 #8280 就是这么来的 —— `_verdict` 只为退货率写（「越小越好」），
#: 毛利复制粘贴调用时**忘了传方向**，于是毛利越低越判「好」，而**那条单测也一起写反了**，CI 一直是绿的。
#: ⇒ 方向必须来自**这张表**：调用方连传错的机会都没有；新指标没登记 ⇒ `KeyError` ⇒ 当场红。
METRIC_DIRECTIONS: Dict[str, bool] = {
    "return_rate": False,     # 越低越好：退货率高是坏事
    "gross_margin": True,     # 越高越好：毛利高是好事
}


def _verdict(
    metric: str,
    value: Optional[float],
    baseline: Optional[Dict[str, Any]],
    *,
    absolute_bad: bool = False,
) -> str:
    """分档。**方向从 `METRIC_DIRECTIONS` 查**（不由调用方传）。

    默认（退货率这类「越小越好」的量）：`<= peer_median` ⇒ good；`<= peer_p75` ⇒ watch；
    `> peer_p75` ⇒ bad。

    `higher_is_better=True`（毛利这类「越大越好」的量）：`>= peer_median` ⇒ good；否则
    `watch`（`< 0` 由 `absolute_bad` 先兜成 bad）。🔴 少传这个参数会让**毛利越低越被判好**
    —— issue #8280 就是这么来的：`_verdict` 原本只为退货率写，毛利直接复用了它。

    `absolute_bad=True` 时**先判绝对**（`value < 0` ⇒ bad）—— 毛利为负**不因**「全店都亏、
    中位数也是负」而被相对判成 good（注入式红证见
    `test_negative_margin_is_bad_even_when_the_whole_store_loses_money`）。
    值未知或基线不可用（样本不足）⇒ `unknown`（**不装懂**）。
    """
    try:
        higher_is_better = METRIC_DIRECTIONS[metric]
    except KeyError:
        raise KeyError(
            f"指标 `{metric}` 没有登记方向 —— 在 `METRIC_DIRECTIONS`"
            "（backend/ai-agent-service/app/briefing/product_judgement.py）里加一行："
            "越高越好写 True、越低越好写 False。方向不许猜（issue #8293 / 缺陷 #8280）"
        ) from None
    if value is None:
        return VERDICT_UNKNOWN
    if absolute_bad and Decimal(str(value)) < 0:
        return VERDICT_BAD
    if baseline is None:
        return VERDICT_UNKNOWN
    current = Decimal(str(value))
    median = Decimal(str(baseline["peer_median"]))
    if higher_is_better:
        # 越大越好：毛利有绝对判据兜底 bad（< 0），相对判据只需要「低于同行中位 ⇒ 值得看一眼」
        return VERDICT_GOOD if current >= median else VERDICT_WATCH
    if current <= median:
        return VERDICT_GOOD
    if current <= Decimal(str(baseline["peer_p75"])):
        return VERDICT_WATCH
    return VERDICT_BAD


def _baselines(rows: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    """两条基线（退货率 / 毛利率）—— 用**全量**行算，不受输出截断影响。"""
    return {
        "return_rate": _peer_baseline([row.get("return_rate") for row in rows]),
        "gross_margin": _peer_baseline([row.get("gross_margin") for row in rows]),
    }
