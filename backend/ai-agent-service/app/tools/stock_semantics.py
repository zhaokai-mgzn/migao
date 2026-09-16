"""「低库存」权威口径 —— AI 工具层单点来源（issue #3783）

**业务口径 = 100**（`LOW_STOCK_THRESHOLD`），与后台同源
（#1396：Dashboard 卡片 / DailyBriefing / admin-web 商品列表均为 100）。

**上界语义 = 含上界**（`≤`，非 `<`）：admin-api 两条 SQL 都是 `ps.stock <= 阈值`
（`ProductMapper.findLowStockByColor` 与 `ProductService` 处理 `stockBelow` 处），
Dashboard 卡片文案同样是「库存 ≤ 100」。故本模块把**运算符**也单点化 ——
工具文案不得再写成「低于 XX」（严格小于）。

两条工具路径共用本模块，禁止在工具里另写阈值字面量（否则「两套口径」会变成「三套」）：

  · `product_search(stock_status=low_stock)`  → 下发后端 `stockBelow`
  · `inventory_manage(action=low_stock_alert)` → 下发后端 `threshold`

守卫：`tests/test_tools_stock_semantics.py`
（含「工具模块内不得出现裸字面量 10 / 100」的 AST 硬守卫）。
"""

from typing import Any, Dict

LOW_STOCK_THRESHOLD = 100
# 上界含（≤）——见模块 docstring 的 SQL 依据
LOW_STOCK_OPERATOR = "≤"


def low_stock_phrase(threshold: int = LOW_STOCK_THRESHOLD) -> str:
    """低库存口径短语（LLM / 用户可见），如「库存≤100」。"""
    return f"库存{LOW_STOCK_OPERATOR}{threshold}"


def low_stock_alert_threshold_schema() -> Dict[str, Any]:
    """`inventory_manage.threshold` 参数 schema（LLM 可见）。

    描述与 `default` 都由本模块生成 —— 单点来源，不在工具里另写一份。
    """
    return {
        "type": "integer",
        "description": (
            f"库存预警阈值（low_stock_alert 时可选，默认 {LOW_STOCK_THRESHOLD}）。"
            f"低库存口径与 product_search 的 low_stock 完全一致：SKU {low_stock_phrase()}，"
            "上界含（与后台低库存口径一致）——问「低库存」时两条路径给出同一个数值范围"
        ),
        "default": LOW_STOCK_THRESHOLD,
    }
