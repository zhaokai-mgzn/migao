"""商品健康度 · 数值读取与输出精度（**无仓内依赖的底座**）—— issue #8290 从 product_health.py 拆出

为什么单独一层：判断 / 刻度 / 归因三块**都**要读数值（`_dec`）、都要定精度输出（`_out`），
而这些 helper 原与三块同住在 `app/briefing/product_health.py` 里 ⇒ 拆任何一块都会把整个视图模块
拉回来（循环依赖，见 issue #8290 的「为什么没在本单拆」）。本模块**不 import 任何仓内模块**，
是这个文件族的底座。

🔴 唯一接缝：**「未知」与「0」不混** —— 非数值 / 非有限 / 缺省一律 `None`（不猜 0）。
注入式红证见 `backend/ai-agent-service/tests/test_briefing_product_health.py` 的
`test_injected_zero_filling_turns_the_same_assertion_red`（把 `_gross_margin` 换成「未知当 0」的版本，
同一条断言必须变红）。⚠️ 那条注入是**经门面**打的（`product_health._gross_margin`）：`_row` 仍在门面里、
按模块全局名查找 ⇒ 门面上的改名对查看行为同样生效（拆分前后一致）。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

#: 金额 / 比率的输出精度（4 位小数：与 `product_skus.avg_cost NUMERIC(12,4)` 同粒度）
_OUTPUT_QUANT = Decimal("0.0001")


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
