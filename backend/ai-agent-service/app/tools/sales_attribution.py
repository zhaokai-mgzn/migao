"""AI 智能客服系统 - 商品归因 Tool（B 端黄金策，只读；issue #8157 · P1-3 后半）

商家问「这周为什么比上周少卖 / 哪个商品拖的」时，本工具按商品聚合**本期与紧邻上期
两个等长窗口**的销售额，给出涨跌 Top N —— **全部算术在工具内**，模型只转述。

## 权限面（判据 = `tests/unit_ci_workflows/test_agent_permission_parity.py`）

- `required_permissions = ["order:list"]`：与它读取的**唯一端点**同一码 ——
  `GET /api/admin/orders`（`OrderController#getOrders` 方法级 `@RequirePermission("order:list")`）
  ⇒ 判据 2「工具码 ≡ 端点码」成立，**不需要**任何 `CODE_DIVERGENCE_EXCEPTIONS` 登记；
- 菜单节点 = 「销售订单」（`TOOL_MENU_NODE` 登记同名节点）⇒ 判据 3 的节点码锚定成立；
- 为什么不挂在 `dashboard_stats` 下：那会把 `order:list` 引进一个只声明 `dashboard:view` 的工具
  （判据 2 结构性红），而把两个码都声明则会放宽到「持看板码但不持订单码」的岗位
  （`product_manager` / `knowledge_editor` 实测无 `order:list`）⇒ 它们会「点进去 403」。

## 口径（复用，不另造）

- 窗口切分 / `finite_number` / `delta_pct` 与 `dashboard_stats(action=trend_compare)` **同一份**
  （`app/utils/compare.py`）：每期上限 `MAX_PERIOD_DAYS`、上期为 0 ⇒ `delta_pct = None`；
- 订单语义与 `order_query` 同一份：`GET /api/admin/orders?page&size&startDate&endDate`
  （`endDate` 含当日，`OrderService#resolveListWindow` 的半开区间）；
- 销售额 = 订单行 `amount` 之和（`amount → subtotal → unitPrice×quantity`）；
- 分页上限**显式**（5 页 × 200 条/期）：超限披露 `window.truncated` + `page_cap`，
  **不许**静默丢数据后给出「看起来完整」的排名；
- 结构异常（缺 `items` / 金额非数值 / 品名为空）⇒ 整次失败，**不得**当 0 参与排名。

**只给数字与排名**：不给归因结论、不给建议（那是产品决策）。
"""

import datetime as _dt
from typing import Any, Dict, List, Optional

from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.compare import MAX_PERIOD_DAYS, delta_pct, finite_number
from app.utils.http_client import get_admin_api_client

# 分页上限**显式**（5 页 × 200 条 = 1000 条/期）；超限必须披露，不许静默。
MAX_ATTRIBUTION_PAGE_SIZE = 200
MAX_ATTRIBUTION_PAGES = 5
ATTRIBUTION_PAGE_CAP = MAX_ATTRIBUTION_PAGE_SIZE * MAX_ATTRIBUTION_PAGES
MAX_ATTRIBUTION_TOP = 10


def _today() -> _dt.date:
    """窗口右端 = 本机当天（与 `finance_api` 的 `_dt.date.today()` 同口径）。

    单独成函数是为了让判据能把窗口边界钉成确定值（不打真实时钟）。
    """
    return _dt.date.today()


def _item_amount(item: Dict[str, Any]) -> Optional[float]:
    """订单行的销售额：`amount` → `subtotal` → `unitPrice×quantity`（与 order_query 同口径）。

    三者都读不出 ⇒ None（结构异常）。**不得**当 0：把「读不到」算成「没卖」，
    会让排名凭空多出一条下滑。
    """
    raw = item.get("amount")
    if raw is None:
        raw = item.get("subtotal")
    if raw is not None:
        return finite_number(raw)
    unit_price = finite_number(item.get("unitPrice"))
    quantity = finite_number(item.get("quantity"))
    if unit_price is None or quantity is None:
        return None
    return round(unit_price * quantity, 2)


def _aggregate_window_products(records: List[Any]) -> Optional[Dict[str, Dict[str, Any]]]:
    """把一窗口的订单聚合成 `{product_name: {"amount": 销售额, "orders": 订单数}}`。

    订单数 = **含该商品的不同订单数**（同一单里同商品多行只算一单）。
    结构异常（记录 / 明细不是对象、品名为空、金额读不出来）⇒ None，由调用方转失败
    —— 读不懂的金额**不进**排名（不许当 0）。
    """
    aggregated: Dict[str, Dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return None
        raw_items = record.get("items")
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            return None
        order_key = record.get("orderNo") or record.get("id") or f"#{index}"
        for item in raw_items:
            if not isinstance(item, dict):
                return None
            name = item.get("productName")
            if not isinstance(name, str) or not name.strip():
                return None
            amount = _item_amount(item)
            if amount is None:
                return None
            bucket = aggregated.setdefault(name.strip(), {"amount": 0.0, "orders": set()})
            bucket["amount"] += amount
            bucket["orders"].add(str(order_key))
    return aggregated


def _attribution_entries(
    current: Dict[str, Dict[str, Any]], previous: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """两窗口按商品名对齐成条目（缺的一侧按 0 计），delta / delta_pct 与环比同口径。"""
    empty = {"amount": 0.0, "orders": set()}
    entries: List[Dict[str, Any]] = []
    for name in set(current) | set(previous):
        cur = current.get(name, empty)
        prev = previous.get(name, empty)
        current_amount = round(cur["amount"], 2)
        previous_amount = round(prev["amount"], 2)
        delta = round(current_amount - previous_amount, 2)
        entries.append({
            "product_name": name,
            "current": current_amount,
            "previous": previous_amount,
            "delta": delta,
            "delta_pct": delta_pct(delta, previous_amount),
            "orders": len(cur["orders"]),
        })
    return entries


class SalesAttributionTool(BaseTool):
    """商品归因 Tool（只读）

    使用场景：
    - 商家问「这周为什么比上周少卖了」「哪个商品卖得比上周少 / 拖后腿」
    - 想知道按商品的涨跌 Top N（谁贡献了变化、贡献多少）
    """

    name = "sales_attribution"
    description = (
        "【触发】用户问'这周为什么比上周少''为什么少了''哪个商品卖得比上周差''哪个商品拖的'"
        "'按商品看涨跌''谁贡献了变化'时，用本工具而非自己口算。"
        "【参数】days（每期天数，1..30，默认 7）、top（涨跌榜各返回几条，1..10，默认 5）。"
        "【返回】本期/上期销售额与 delta / delta_pct / previous_is_zero、涨跌 Top N"
        "（product_name / current / previous / delta / delta_pct / orders）、窗口起止日期与截断标记。"
        "**全部算术在工具内**：数字与排名必须逐字转述，禁止自己按订单口算，也禁止编造原因。"
        "【反例】只看单窗口销量排行用 dashboard_stats(product_ranking)；对比两个总量用 "
        "dashboard_stats(trend_compare)；查具体订单用 order_query。"
        "【标注】READONLY — 只给数字与排名，不给归因结论/建议"
    )
    # 权限码（admin-api 目录）：订单列表读面 `order:list`（= 「销售订单」菜单节点码）。
    # 与 `GET /api/admin/orders` 的方法级 `@RequirePermission("order:list")` 同码 ⇒ 判据 2 绿。
    required_permissions = ["order:list"]
    read_only = True   # 只读归因（BaseTool 默认值，显式声明以便权限面自检）

    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": (
                    "每期天数：本期 = 最近 days 天，上期 = 紧邻其前 days 天（1..30，默认 7；"
                    "超出 30 会被截断并在返回里带 window_capped=true）。"
                    "用户说“这周”传 7，“这个月/最近 30 天”传 30。不要反问起止日期。"
                ),
                "default": 7,
                "minimum": 1,
                "maximum": MAX_PERIOD_DAYS,
            },
            "top": {
                "type": "integer",
                "description": "涨跌榜条数：top_up / top_down 各返回至多 top 条（1..10，默认 5）。",
                "default": 5,
                "minimum": 1,
                "maximum": MAX_ATTRIBUTION_TOP,
            },
        },
    }

    async def execute(
        self,
        context: ToolContext,
        days: int = 7,
        top: int = 5,
        **kwargs,
    ) -> ToolResult:
        """执行商品归因"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看商品归因",
                suggestion="请联系管理员获取订单查看权限",
            )

        days = int(days) if days else 7
        top = int(top) if top else 5

        try:
            return await self._attribute(context, days, top)
        except Exception as e:
            logger.error(
                f"[sales-attribution] Error: {type(e).__name__}: {e}", exc_info=True
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="商品归因查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _fetch_window_orders(
        self, context: ToolContext, start: _dt.date, end: _dt.date
    ) -> tuple:
        """取一个**已定窗口**的订单（分页到取满或触到上限）。

        读源复核（issue #8157）：`GET /api/admin/orders` 的日期参数是 `startDate` / `endDate`
        （`YYYY-MM-DD`），且 `OrderService#resolveListWindow` 把 `endDate` 当**含当日**
        （半开区间 `[startDate 00:00, endDate+1 00:00)`，business clock 时区）。

        Returns:
            ``(records, truncated, failure)``：
            - 正常 ⇒ ``(订单列表, 是否被分页上限截断, None)``；
            - 失败 ⇒ ``(None, False, ToolResult)`` —— **不**返回半段数据（半段会伪装成完整排名）。
        """
        client = get_admin_api_client()
        records: List[Any] = []
        total = 0
        page = 1
        while page <= MAX_ATTRIBUTION_PAGES:
            response = await client.get(
                "/api/admin/orders",
                params={
                    "page": page,
                    "size": MAX_ATTRIBUTION_PAGE_SIZE,
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                },
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            if not isinstance(response, dict):
                response = {"data": response} if isinstance(response, list) else {}
            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "查询失败")
                return None, False, admin_api_failure(response,
                    error=error_msg,
                    message=(
                        f"订单查询失败（{start.isoformat()}~{end.isoformat()}），无法给出商品归因"
                    ),
                    suggestion="请稍后重试；本次不返回估算的排名",
                )
            data = response.get("data")
            items = data.get("items") if isinstance(data, dict) else None
            page_total = finite_number(data.get("total")) if isinstance(data, dict) else None
            if not isinstance(items, list) or page_total is None:
                logger.warning(
                    f"[sales-attribution] unexpected order payload | tenant={context.tenant_id}"
                )
                return None, False, ToolResult(
                    success=False,
                    error="unexpected_order_payload",
                    message="订单数据格式异常，本次不提供商品归因",
                    suggestion="请稍后重试；本次不返回估算值（数据不可用时不猜排名）",
                )
            total = int(page_total)
            records.extend(items)
            if len(records) >= total or not items:
                break
            page += 1
        return records, len(records) < total, None

    async def _attribute(self, context: ToolContext, days: int, top: int) -> ToolResult:
        """本期 vs 紧邻上期按商品聚合销售额 + 涨跌 Top N（全部算术在工具内）。"""
        requested_days = days
        period_days = max(1, min(days, MAX_PERIOD_DAYS))
        top_n = max(1, min(top, MAX_ATTRIBUTION_TOP))
        window_capped = period_days != requested_days

        current_end = _today()
        current_start = current_end - _dt.timedelta(days=period_days - 1)
        previous_end = current_start - _dt.timedelta(days=1)
        previous_start = previous_end - _dt.timedelta(days=period_days - 1)

        current_records, current_truncated, failure = await self._fetch_window_orders(
            context, current_start, current_end
        )
        if failure is not None:
            return failure
        previous_records, previous_truncated, failure = await self._fetch_window_orders(
            context, previous_start, previous_end
        )
        if failure is not None:
            return failure

        current_agg = _aggregate_window_products(current_records)
        previous_agg = _aggregate_window_products(previous_records)
        if current_agg is None or previous_agg is None:
            logger.warning(
                f"[sales-attribution] unexpected order items | tenant={context.tenant_id}"
            )
            return ToolResult(
                success=False,
                error="unexpected_order_items",
                message="订单明细格式异常，本次不提供商品归因",
                suggestion="请稍后重试；本次不返回估算值（金额读不出来时不猜排名）",
            )

        entries = _attribution_entries(current_agg, previous_agg)
        current_total = round(sum(entry["current"] for entry in entries), 2)
        previous_total = round(sum(entry["previous"] for entry in entries), 2)
        delta = round(current_total - previous_total, 2)
        previous_is_zero = previous_total == 0
        pct = delta_pct(delta, previous_total)
        truncated = current_truncated or previous_truncated

        top_up = sorted(
            (entry for entry in entries if entry["delta"] > 0),
            key=lambda entry: (-entry["delta"], entry["product_name"]),
        )[:top_n]
        top_down = sorted(
            (entry for entry in entries if entry["delta"] < 0),
            key=lambda entry: (entry["delta"], entry["product_name"]),
        )[:top_n]

        data: Dict[str, Any] = {
            "requested_days": requested_days,
            "days": period_days,
            "window_capped": window_capped,
            "top": top_n,
            "current_total": current_total,
            "previous_total": previous_total,
            "delta": delta,
            "delta_pct": pct,
            "previous_is_zero": previous_is_zero,
            "top_up": top_up,
            "top_down": top_down,
            "window": {
                "current": {
                    "start": current_start.isoformat(),
                    "end": current_end.isoformat(),
                    "days": period_days,
                },
                "previous": {
                    "start": previous_start.isoformat(),
                    "end": previous_end.isoformat(),
                    "days": period_days,
                },
                "truncated": truncated,
                "page_cap": ATTRIBUTION_PAGE_CAP,
            },
        }

        message = f"近 {period_days} 天商品归因已计算（上期 = 其前 {period_days} 天）"
        if window_capped:
            message += f"；请求 {requested_days} 天/期超出上限，已截断为 {period_days} 天/期"
        if truncated:
            message += (
                f"；窗口订单量超过分页上限（每期最多取 {ATTRIBUTION_PAGE_CAP} 条），"
                "排名可能不含全部订单"
            )
        summary = f"本期销售额{current_total}元 / 上期{previous_total}元"
        if pct is None:
            summary += "（上期为 0，无百分比）"
        else:
            summary += f"，环比{pct:+.2f}%"
        if top_up:
            summary += f"；上升最多「{top_up[0]['product_name']}」"
        if top_down:
            summary += f"；下滑最多「{top_down[0]['product_name']}」"
        logger.info(
            f"[sales-attribution] fetched, days={period_days}, top={top_n}, "
            f"truncated={truncated} | tenant={context.tenant_id}"
        )
        return ToolResult(success=True, data=data, message=message, summary=summary)
