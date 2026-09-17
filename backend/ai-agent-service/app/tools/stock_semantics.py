"""「低库存」权威口径 + 「商品库存」唯一权威 —— AI 工具层单点来源（#3783 / #4038）

## 一、商品库存的唯一权威 = **SKU 级**（`product_skus.stock`，issue #4038）

仓库既有真值 `.github/templates/product-sku-stock.yml`：
「商品库存 = 所有 SKU 库存求和（`products.stock` 常为 0，以 SKU 汇总为准）」。
DB 实测（2026-09-18，云 dev）印证该真值：

  · `products.stock` 与 SKU 汇总在 **311/497** 个商品上不一致；
  · 有 SKU 的 351 个商品里 **299 个商品级恒为 0**（实测 `2699系列雪尼尔窗帘面料`：
    商品级 0 / SKU 合计 9599）；
  · 扣减（订单流程）、低库存口径、列表排序、详情/列表返回的 `stock` **全部已按 SKU 级**。

⇒ **商品级 `products.stock` 是派生冗余列（非权威）**，任何工具都不得直接采信；
商品库存数字一律经 `product_stock_summary()` 从 SKU 明细派生
（守卫：`tests/test_tools_stock_semantics.py::TestProductStockAuthority`，
含「工具模块内不得直读后端商品级 `data["stock"]`」的硬守卫）。

## 二、「低库存」阈值口径 = 100（含上界 ≤，issue #3783）

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

from typing import Any, Dict, Iterable, Optional

LOW_STOCK_THRESHOLD = 100
# 上界含（≤）——见模块 docstring 的 SQL 依据
LOW_STOCK_OPERATOR = "≤"

# ── 商品库存唯一权威（issue #4038）──────────────────────────────────────────
#: 权威来源 = SKU 级。**故意显式命名**：让「权威是谁」在代码里可被断言，而不是靠注释。
STOCK_AUTHORITY = "sku"
#: 商品库存数字的来源标记（LLM / 调用方可见）
SKU_SUM_SOURCE = "sku_sum"
NO_SKU_SOURCE = "no_sku"


def product_stock_summary(skus: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, Any]:
    """按唯一权威（SKU 级）汇总商品库存 —— 工具层商品库存数字的**唯一入口**。

    Args:
        skus: 商品详情里的 SKU 明细（`data["skus"]`），每项含 `stock`

    Returns:
        `{"stock": int | None, "stock_source": "sku_sum" | "no_sku"}`

        **无 SKU 记录时 `stock=None`（fail-closed）**：宁可说「无法确认」，
        也不谎报 `0` —— `0` 会被 LLM 读成「没货」，而实测有 SKU 的商品里
        299/351 的商品级列恰好恒为 0，正是这个误读的来源。
    """
    if not skus:
        return {"stock": None, "stock_source": NO_SKU_SOURCE}
    total = 0
    for sku in skus:
        try:
            total += int((sku or {}).get("stock") or 0)
        except (TypeError, ValueError):
            # 单个 SKU 的脏值按 0 计，不因一行坏数据把整商品的库存数字变成异常
            continue
    return {"stock": total, "stock_source": SKU_SUM_SOURCE}


def no_sku_stock_note(product_name: str = "") -> str:
    """无 SKU 记录时给 LLM 的统一说明 —— **不得**表述为「库存 0 / 没货 / 缺货」。"""
    label = f"商品【{product_name}】" if product_name else "该商品"
    return (
        f"{label}尚未维护 SKU 规格（颜色/售卖方式/门幅），无法确认可用库存 —— "
        "请先在商品详情维护 SKU 后再查询"
    )


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
