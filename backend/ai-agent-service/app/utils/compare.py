"""环比 / 归因共用的数值口径（issue #8157 从 `dashboard_stats` 抽出）。

为什么单独成模块：`trend_compare`（看板环比）与 `sales_attribution`（商品归因）必须给出
**同一份**算术 —— `finite_number`（结构异常识别，bool / 字符串 / NaN / ±Inf ⇒ None）与
`delta_pct`（上期为 0 ⇒ None，**绝不** Infinity/NaN）。两处各写一份必然漂移
（同 #3570「不复制第二份解析器」的教训）。

口径边界：本模块只做算术，不做业务解释（归因结论 / 建议不在任何工具职责内）。
"""

import math
from typing import Any, Optional

#: 每期天数上限（`trend_compare` 与 `sales_attribution` 同一份参数契约：`days > 30` 一律截断并披露）。
MAX_PERIOD_DAYS = 30
MAX_WINDOW_DAYS = 2 * MAX_PERIOD_DAYS


def finite_number(value: Any) -> Optional[float]:
    """服务端数值原样返回（int 保持 int）；bool / 非数值 / NaN / ±Inf ⇒ None（结构异常）。

    上游 JSON 里的数值字段只可能是数字 ⇒ 拿到字符串或非有限值只可能是异常，
    **不得**当 0 参与算术（会把「没查到」算成「下降」）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def delta_pct(delta: float, previous_total: float) -> Optional[float]:
    """变化百分比：上期为 0 ⇒ None（没有百分比可言，**绝不** Infinity/NaN）。"""
    if previous_total == 0:
        return None
    return round(delta / previous_total * 100, 2)
