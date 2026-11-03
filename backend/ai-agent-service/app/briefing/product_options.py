"""商品健康度 · 刻度与可选动作（钱 + 「然后呢」规则表）—— issue #8290 从 product_health.py 拆出

判据来源：issue #8276（权衡的刻度：这批货压了多少钱 / 离同行差多少 / 每件多赚多少）·
#8251（可选动作：带代价与可逆性）。依赖 `product_numbers`（读数值与精度）与 `product_judgement`
（分档常量），**不 import 视图模块**（拆分前与视图同住 ⇒ 循环依赖，见 issue #8290）。

## v1 只收**可逆 + 低成本**的动作

清仓 / 下架 / 换供应商这类不可逆动作不进 v1，登记在 issue #8251「不在本单」——
它们需要业务裁定，不是代码能替老板决定的。选项表是**确定性规则表**（不读 LLM）：
同一行永远产出同一组数（不额外排序也能保证确定性）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.briefing.product_judgement import VERDICT_BAD, VERDICT_WATCH
from app.briefing.product_numbers import _dec, _out

#: 选项性质自述（纪律 3：别让调用方把「行业常见做法」读成「对你这家店的建议」）
OPTIONS_BASIS = (
    "行业常见做法，**不是**对具体店铺的建议；每条都需人工判断后再执行"
)

#: 试调价的固定步长（选项表是**确定性规则表** ⇒ 不做参数化，同一行永远同一组数）
PRICE_UP_STEP = Decimal("0.05")

#: 金额自述（纪律 2：别让「给定情景的算术」被读成「预测」）
MONEY_BASIS = (
    "金额 = 给定情景下的**算术**，不是预测：成本未知的行不算钱（未知 ≠ 0）；"
    "调价只算「每件多赚多少」—— 销量会怎么变我们没有**价格弹性**数据，不猜"
)

_COST_LOW = ("low", "低成本：只看数据 / 改文案")

_OPTIONS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
    "return_rate": {
        VERDICT_BAD: [
            {
                "action": "先看这批退货的售后原因分布（色差 / 尺寸 / 物流 / 质量）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "售后工单按原因分组的条数；先知道「主要怪谁」再决定改什么",
            },
            {
                "action": "在商品描述里补「实物色差 / 尺寸以实物为准」提示",
                "cost": "low",
                "cost_note": "改文案，不动物流与价格",
                "reversible": True,
                "verify": "两周后该 SKU 的退货率是否回落（对比本视图的 peer_median）",
            },
        ],
        VERDICT_WATCH: [
            {
                "action": "先看这批退货的售后原因分布（色差 / 尺寸 / 物流 / 质量）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "售后工单按原因分组的条数",
            },
        ],
    },
    "gross_margin": {
        VERDICT_BAD: [
            {
                "action": "先核对成本价是否已维护（成本未知时毛利根本不可算，本行的负数可能是脏数据）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "该 SKU 的 avg_cost 是否有值；有值才是真亏，无值只是「算不出来」",
            },
            {
                "action": "核对近期是否有低于成本价的成交（改价 / 折扣叠加）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "改价记录与订单折扣：看这笔低价是「定价」还是「一次性的让利」",
            },
            {
                "action": "小范围试调价（如 +5%），观察 2 周销量再决定是否扩大",
                "cost": "medium",
                "cost_note": "调价影响转化，需盯销量",
                "reversible": True,
                "verify": "两周内该 SKU 的销量与毛利双向变化；只涨毛利不涨销量的价格要慎用",
                # 唯一能算钱的选项：+5% 每件多赚多少（见 _option_money）
                "money_kind": "price_step",
            },
        ],
        VERDICT_WATCH: [
            {
                "action": "核对成本价是否已维护（成本未知时毛利不可算）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "该 SKU 的 avg_cost 是否有值",
            },
        ],
    },
}


def _money(row: Dict[str, Any], margin_baseline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """权衡的刻度（issue #8276）—— 「这批货压了多少钱 / 离同行差多少 / 每件多赚多少」。

    🔴 三条不许：
    · **成本未知不许当 0**：`stock_value = None` + 自述 `cost_unknown`。把未知写成 0 等于
      说「这批货不占钱」，与事实**正好相反**（注入式红证见 `test_unknown_cost_is_not_zero_capital`）。
    · **不乘销量**：`sales_count` 的周期口径在快照契约里没标注，乘上去就是编
      （红证见 `test_price_step_does_not_multiply_by_sales_count`）。
    · **不给「建议价」**：没有弹性数据，只算「+5% 这个情景下每件多赚多少」。
    """
    stock = _dec(row.get("stock"))
    price = _dec(row.get("price"))
    cost = _dec(row.get("avg_cost"))
    margin = _dec(row.get("gross_margin"))

    if cost is None:
        stock_value, value_basis = None, "cost_unknown"
    elif stock is None:
        stock_value, value_basis = None, "stock_unknown"
    else:
        stock_value, value_basis = stock * cost, "stock × avg_cost"

    peer_median = _dec((margin_baseline or {}).get("peer_median"))
    gap = (peer_median - margin) if (margin is not None and peer_median is not None) else None

    return {
        "stock_value": _out(stock_value),
        "stock_value_basis": value_basis,
        # 正数 = 每件比同行中位**少赚**这么多（方向写反是最难发现的错）
        "margin_gap_per_unit": _out(gap),
        "margin_gap_basis": (
            "peer_median − 本行毛利；正数 = 每件比同行中位少赚"
            if gap is not None
            else "基线样本不足（< 最小样本量）或本行毛利未知 ⇒ 算不出差额"
        ),
        "price_up_5pct_per_unit": _out(price * PRICE_UP_STEP) if price is not None else None,
    }


def _option_money(row: Dict[str, Any], money_kind: str) -> Optional[Dict[str, Any]]:
    """选项层面的钱：**算得出才给**（算不出的不给字段，而不是给 0）。"""
    if money_kind != "price_step":
        return None
    price = _dec(row.get("price"))
    if price is None:
        return None
    return {
        "per_unit": _out(price * PRICE_UP_STEP),
        "premise": "销量不变假设下每件多赚这么多；销量会怎么变没有弹性数据（不猜）",
    }


def _next_options(row: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """按行的 verdict 产出去重后的可选动作；**没问题（good / unknown）⇒ 不产出**。

    纯规则表（不读 LLM）⇒ 同一组 verdict 必然产出同一组选项（确定性由规则表保证，不需要额外排序）。
    """
    options: List[Dict[str, Any]] = []
    seen = set()
    for metric, verdict_field in (
        ("return_rate", "return_rate_verdict"),
        ("gross_margin", "gross_margin_verdict"),
    ):
        verdict = row.get(verdict_field)
        if verdict not in (VERDICT_BAD, VERDICT_WATCH):
            continue
        for option in _OPTIONS.get(metric, {}).get(verdict, []):
            key = (metric, option["action"])
            if key in seen:
                continue
            seen.add(key)
            entry = {**option, "metric": metric, "for_verdict": verdict}
            money_kind = option.get("money_kind")
            impact = _option_money(row, money_kind) if money_kind else None
            if impact is not None:
                entry["money_impact"] = impact
            # 内部标记不外泄（它是规则表的元数据，不是给调用方看的）
            entry.pop("money_kind", None)
            options.append(entry)
    return options or None
