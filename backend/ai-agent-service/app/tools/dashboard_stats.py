"""
AI 智能客服系统 - 数据看板 Tool

获取Dashboard统计数据，支持概览统计、订单趋势、状态分布、最近订单、活跃会话、商品销量排行。
"""

import datetime as _dt
import math
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {
    "overview",
    "order_trend",
    # issue #8120（黄金策分析 P1 · 对比）：环比对比在**工具内**确定性计算
    # （本期 = 最近 days 天 / 上期 = 紧邻其前 days 天），模型只转述、不做算术。
    "trend_compare",
    "order_status",
    "recent_orders",
    "active_sessions",
    "product_ranking",
    # issue #5247（B 端只读模块覆盖：看板补全）：三个**只读**待办/发货计数端点此前没有任何
    # 工具绑定（DashboardController 类级 `dashboard:view`，与既有 action 同码）。
    "pending_tasks",
    "pending_shipment_count",
    "processing_shipment_count",
}


# issue #8120：环比对比的窗口口径（action=trend_compare 的参数契约 days ∈ [1, 30]）。
# 读源复核：admin-api `DashboardController#getOrderTrend` 的 days **没有**上限校验
# （`@RequestParam(defaultValue = "7") int days`），本工具的 30 天/期、60 天窗口是**参数契约**
# 上的上限 ⇒ 超出即截断并显式披露（`window_capped` + 实际窗口），不悄悄退化。
MAX_PERIOD_DAYS = 30
MAX_WINDOW_DAYS = 2 * MAX_PERIOD_DAYS


def _finite_number(value: Any) -> Optional[float]:
    """服务端数值原样返回（int 保持 int）；bool / 非数值 / NaN / ±Inf ⇒ None（结构异常）。

    `OrderTrendPointResponse` 逐日给 `date` / `orders`（int）/ `amount`（long），JSON 里恒为数字
    ⇒ 拿到字符串或非有限值只可能是上游异常，**不得**当 0 参与算术（会把"没查到"算成"下降"）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def _parse_trend_points(response: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """把 order-trend 响应解析成**按日期升序**的 `[{date, orders, amount}]`。

    结构异常（缺序列 / 元素不是对象 / date 不可解析 / 数值非有限）⇒ None，由调用方转成失败。
    """
    payload = response.get("data")
    if isinstance(payload, dict):
        raw = payload.get("list", payload.get("trend", payload.get("points")))
    else:
        raw = payload
    if not isinstance(raw, list) or not raw:
        return None
    points: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        date_value = item.get("date")
        if not isinstance(date_value, str) or not date_value.strip():
            return None
        try:
            day = _dt.date.fromisoformat(date_value.strip())
        except ValueError:
            return None
        orders = _finite_number(item.get("orders"))
        amount = _finite_number(item.get("amount"))
        if orders is None or amount is None:
            return None
        points.append({"date": day.isoformat(), "orders": orders, "amount": amount})
    points.sort(key=lambda point: point["date"])
    return points


def _split_trend_periods(
    points: List[Dict[str, Any]], period_days: int
) -> tuple:
    """切成（本期, 上期）：本期 = 最近 period_days 天，上期 = 紧邻其前的等长段。

    序列不足 2×period_days 时上期只取**仅存**的那几天（调用方用 `partial` 披露）。
    """
    current = points[-period_days:]
    rest = points[: len(points) - len(current)]
    previous = rest[-period_days:]
    return current, previous


def _compare_points(
    current: List[Dict[str, Any]], previous: List[Dict[str, Any]], key: str
) -> Dict[str, Any]:
    """同一口径（orders / amount）的本期 vs 上期算术；上期为 0 ⇒ `delta_pct = None`。

    只做算术，不做业务解释（归因 / 建议不在本工具职责内，issue #8120）。
    """
    current_total = sum(point[key] for point in current)
    previous_total = sum(point[key] for point in previous)
    delta = current_total - previous_total
    previous_is_zero = previous_total == 0
    return {
        "current_total": current_total,
        "previous_total": previous_total,
        "delta": delta,
        # 上期为 0 时**没有**百分比可言 ⇒ null（绝不返回 Infinity/NaN）
        "delta_pct": None if previous_is_zero else round(delta / previous_total * 100, 2),
        "current_daily_avg": round(current_total / len(current), 2) if current else None,
        "previous_daily_avg": round(previous_total / len(previous), 2) if previous else None,
        "previous_is_zero": previous_is_zero,
    }


def _period_span(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "start": points[0]["date"] if points else None,
        "end": points[-1]["date"] if points else None,
        "days": len(points),
    }


class DashboardStatsTool(BaseTool):
    """数据看板 Tool

    获取Dashboard统计数据，支持概览统计、订单趋势、状态分布、最近订单、活跃会话、商品销量排行。

    使用场景：
    - 查看今日经营概览（订单数、客户数、工单等）
    - 查看订单趋势图数据
    - 查看订单状态分布（饼图数据）
    - 查看最近订单列表
    - 查看当前活跃的客服会话
    - 查看商品销量排行（哪个商品卖得最好）
    """

    name = "dashboard_stats"
    description = (
        "【触发】用户说'今天生意''经营看板''数据概览''订单趋势''状态分布''最近X条订单''活跃会话'"
        "'哪个卖得好''卖得最好''销量排行''看看数据'时，优先用本工具而非 order_query。"
        "【参数】action 必填：overview(今日概览) / order_trend(趋势,需 days) / "
        "trend_compare(环比对比:本期 vs 紧邻上期,需 days) / order_status(状态分布) / "
        "recent_orders(最近,需 limit) / active_sessions(活跃,需 limit) / "
        "product_ranking(商品销量排行,period=day 近7天|month 近30天,需 limit) / "
        "pending_tasks(待办任务) / pending_shipment_count(待发货单数) / "
        "processing_shipment_count(加工中待发货单数)；days 默认 7、limit 默认 5。"
        "【反例】查某个具体订单/订单列表用 order_query；查客服会话详情用 session_manage；"
        "查加工单用 processing_order_query。"
        "【标注】READONLY — 经营分析专用，不查具体记录、不改动任何数据"
    )
    # 权限码（admin-api 目录）：DashboardController 类级 `@RequirePermission("dashboard:view")`。
    # 目录里 6 个商户角色都持此码 ⇒ 不再按角色名硬编码（#4106 F4）。
    required_permissions = ["dashboard:view"]

    read_only = True   # 只读看板（BaseTool 默认值，显式声明以便权限面自检）

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型："
                    "overview（今日经营统计概览，含订单数/客户数/工单等指标） / "
                    "order_trend（订单趋势折线数据，需配合 days，适用于“最近 N 天订单趋势”场景） / "
                    "trend_compare（环比对比：工具内把 2×days 天序列切成“本期/上期”并算出 delta 与 delta_pct；"
                    "问“这周比上周怎么样/这个月比上个月呢”时用它，禁止自己口算） / "
                    "order_status（订单状态分布饼图数据） / "
                    "recent_orders（最近订单列表，需配合 limit） / "
                    "active_sessions（当前活跃客服会话列表，需配合 limit） / "
                    "product_ranking（商品销量排行，需配合 period 与 limit，适用于“哪个商品卖得最好”场景） / "
                    "pending_tasks（待办任务清单） / "
                    "pending_shipment_count（待发货单数） / "
                    "processing_shipment_count（加工中待发货单数）"
                ),
                "enum": ["overview", "order_trend", "trend_compare", "order_status", "recent_orders", "active_sessions", "product_ranking", "pending_tasks", "pending_shipment_count", "processing_shipment_count"],
            },
            "days": {
                "type": "integer",
                "description": (
                    "查询天数范围，在 action=order_trend 时生效；action=trend_compare 时表示“每期天数”"
                    "（1..30，默认 7，超出 30 会被截断并在返回里带 window_capped=true）。"
                    "例如 7 表示最近 7 天、8 表示最近 8 天、14 表示最近 14 天、30 表示最近 30 天。"
                    "默认 7 天。用户说“最近 7 天”就传 days=7，“最近一周”也传 days=7，"
                    "“最近半个月/15天”传 days=15，“最近一个月/30天”传 days=30。"
                    "不要反问用户具体起止日期。"
                ),
                "default": 7,
                "minimum": 1,
                "maximum": 365,
            },
            "limit": {
                "type": "integer",
                "description": "返回条数限制，在 action=recent_orders / active_sessions / product_ranking 时生效，默认 5。",
                "default": 5,
            },
            "period": {
                "type": "string",
                "description": (
                    "排行周期，仅在 action=product_ranking 时生效：day（近 7 天）/ month（近 30 天，本月）。"
                    "用户说“这个月/本月/近一个月”传 month；“最近一周/这几天”传 day。默认 day。"
                ),
                "enum": ["day", "month"],
                "default": "day",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        days: int = 7,
        limit: int = 5,
        period: str = "day",
        **kwargs,
    ) -> ToolResult:
        """执行数据看板查询"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看数据看板",
                suggestion="请联系管理员获取查看数据看板权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        # 强制转换参数为 int
        days = int(days) if days else 7
        limit = int(limit) if limit else 5
        # period 仅 product_ranking 使用，白名单防注入
        period = period if period in ("day", "month") else "day"

        try:
            if action == "overview":
                return await self._overview(context)
            elif action == "order_trend":
                return await self._order_trend(context, days)
            elif action == "trend_compare":
                return await self._trend_compare(context, days)
            elif action == "order_status":
                return await self._order_status(context)
            elif action == "recent_orders":
                return await self._recent_orders(context, limit)
            elif action == "active_sessions":
                return await self._active_sessions(context, limit)
            elif action == "product_ranking":
                return await self._product_ranking(context, period, limit)
            elif action == "pending_tasks":
                return await self._pending_tasks(context)
            elif action == "pending_shipment_count":
                return await self._pending_shipment_count(context)
            elif action == "processing_shipment_count":
                return await self._processing_shipment_count(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[dashboard-stats] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="数据看板查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _overview(self, context: ToolContext) -> ToolResult:
        """获取统计概览"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/stats",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="统计概览查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        if isinstance(data, list):
            data = {"list": data}  # 兼容 admin-api 返回 list（order-trend/order-status/recent-orders/product-ranking 实测为 list）
        logger.info(f"[dashboard-stats] Overview fetched | tenant={context.tenant_id}")

        # 构建摘要：提取今日订单数和销售额
        today_orders = data.get("todayOrderCount", data.get("totalOrders", "?"))
        today_amount = data.get("todaySalesAmount", data.get("totalAmount", "?"))
        return ToolResult(
            success=True,
            data=data,
            message="今日经营概览数据已获取",
            summary=f"今日订单{today_orders}单, 销售额{today_amount}元",
        )

    async def _order_trend(self, context: ToolContext, days: int) -> ToolResult:
        """获取订单趋势"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/order-trend",
            params={"days": days},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        # 防御：admin-api 可能返回 list 而非 dict
        if not isinstance(response, dict):
            logger.warning(f"[dashboard-stats] _order_trend unexpected response type: {type(response).__name__}")
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="订单趋势查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        # 兼容 admin-api 返回 data 为 list 的形态（生产 /api/admin/dashboard/order-trend
        # 返回 data: [...list...]）：包成 dict 满足 ToolResult.data 校验，同时让摘要统计
        # 与前端消费结构一致（此前 dict API data.get 对 list 崩溃 → order_trend 恒失败，
        # DA-002 根因）
        if isinstance(data, list):
            data = {"list": data}
        logger.info(f"[dashboard-stats] Order trend fetched, days={days} | tenant={context.tenant_id}")

        # 构建摘要：统计趋势数据点数量
        trend_points = len(data.get("list", data.get("trend", data.get("points", []))))
        return ToolResult(
            success=True,
            data=data,
            message=f"近 {days} 天订单趋势数据已获取",
            summary=f"近{days}天订单趋势: {trend_points}个数据点",
        )

    async def _trend_compare(self, context: ToolContext, days: int) -> ToolResult:
        """环比对比（issue #8120）：本期 vs 紧邻上期，**全部算术在工具内完成**。

        取 `2×days` 天 order_trend 序列，按日期升序切成「本期 = 最近 days 天 /
        上期 = 其前 days 天」，返回两段的合计 / 日均 / delta / delta_pct 与逐日切片。
        窗口口径：days 超过 `MAX_PERIOD_DAYS` ⇒ 截断并显式披露（`window_capped` +
        `requested_days` / 实际 `days` / `window_days`），不悄悄退化。
        """
        requested_days = days
        period_days = max(1, min(days, MAX_PERIOD_DAYS))
        window_days = min(2 * period_days, MAX_WINDOW_DAYS)
        window_capped = period_days != requested_days or 2 * requested_days > MAX_WINDOW_DAYS

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/order-trend",
            params={"days": window_days},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        # 防御：admin-api 可能返回 list 而非 dict（与本文件既有 action 同约定）
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="订单趋势查询失败，无法给出环比对比",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        points = _parse_trend_points(response)
        if points is None:
            logger.warning(
                f"[dashboard-stats] trend_compare unexpected payload | tenant={context.tenant_id}"
            )
            return admin_api_failure(response,
                error="unexpected_trend_payload",
                message="订单趋势数据格式异常，本次不提供环比对比",
                suggestion="请稍后重试；本次不返回估算值（数据不可用时不猜涨跌）",
            )

        current_points, previous_points = _split_trend_periods(points, period_days)
        orders_compare = _compare_points(current_points, previous_points, "orders")
        amount_compare = _compare_points(current_points, previous_points, "amount")
        partial = len(current_points) < period_days or len(previous_points) < period_days

        data: Dict[str, Any] = {
            "action": "trend_compare",
            "requested_days": requested_days,
            "days": period_days,
            "window_days": window_days,
            "window_capped": window_capped,
            "partial": partial,
            "current_period": _period_span(current_points),
            "previous_period": _period_span(previous_points),
            "current_daily": current_points,
            "previous_daily": previous_points,
            "amount": amount_compare,
            **orders_compare,
        }

        message = f"近 {period_days} 天订单环比已计算（上期 = 其前 {period_days} 天）"
        if window_capped:
            message += (
                f"；请求 {requested_days} 天/期超出上限，已截断为 {period_days} 天/期"
                f"（窗口 {window_days} 天）"
            )
        if partial:
            message += "；服务端序列不足两期，上期天数少于本期"
        summary = (
            f"本期{period_days}天订单{orders_compare['current_total']}单 / "
            f"上期{orders_compare['previous_total']}单"
        )
        if orders_compare["delta_pct"] is None:
            summary += "（上期为 0，无百分比）"
        else:
            summary += f"，环比{orders_compare['delta_pct']:+.2f}%"
        logger.info(
            f"[dashboard-stats] trend_compare fetched, days={period_days}, "
            f"window={window_days} | tenant={context.tenant_id}"
        )
        return ToolResult(success=True, data=data, message=message, summary=summary)

    async def _order_status(self, context: ToolContext) -> ToolResult:
        """获取订单状态分布"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/order-status",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="订单状态分布查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        if isinstance(data, list):
            data = {"list": data}  # 兼容 admin-api 返回 list（order-trend/order-status/recent-orders/product-ranking 实测为 list）
        logger.info(f"[dashboard-stats] Order status distribution fetched | tenant={context.tenant_id}")

        # 构建摘要：汇总各状态的数量
        status_items = data.get("distribution") or data.get("items") or data.get("list") or []
        if isinstance(status_items, dict):
            top_statuses = [f"{k}:{v}" for k, v in list(status_items.items())[:5]]
            status_text = "、".join(top_statuses) if top_statuses else "无数据"
        elif isinstance(status_items, list):
            status_text = f"{len(status_items)}种状态"
        else:
            status_text = "已获取"
        return ToolResult(
            success=True,
            data=data,
            message="订单状态分布数据已获取",
            summary=f"订单状态分布: {status_text}",
        )

    async def _recent_orders(self, context: ToolContext, limit: int) -> ToolResult:
        """获取最近订单"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/recent-orders",
            params={"limit": limit},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="最近订单查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        if isinstance(data, list):
            data = {"list": data}  # 兼容 admin-api 返回 list（order-trend/order-status/recent-orders/product-ranking 实测为 list）
        logger.info(f"[dashboard-stats] Recent orders fetched, limit={limit} | tenant={context.tenant_id}")

        # 构建摘要：统计订单数量
        orders_list = data.get("list", data.get("records", data.get("items", [])))
        order_count = len(orders_list) if isinstance(orders_list, list) else 0
        return ToolResult(
            success=True,
            data=data,
            message=f"最近 {limit} 条订单已获取",
            summary=f"最近{order_count}条订单",
        )

    async def _active_sessions(self, context: ToolContext, limit: int) -> ToolResult:
        """获取活跃会话"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/active-sessions",
            params={"limit": limit},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="活跃会话查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        if isinstance(data, list):
            data = {"list": data}  # 兼容 admin-api 返回 list（order-trend/order-status/recent-orders/product-ranking 实测为 list）
        logger.info(f"[dashboard-stats] Active sessions fetched, limit={limit} | tenant={context.tenant_id}")

        # 构建摘要：统计会话数量
        sessions_list = data.get("list", data.get("sessions", data.get("items", [])))
        session_count = len(sessions_list) if isinstance(sessions_list, list) else 0
        return ToolResult(
            success=True,
            data=data,
            message=f"当前活跃会话数据已获取",
            summary=f"当前{session_count}个活跃会话",
        )

    async def _product_ranking(self, context: ToolContext, period: str, limit: int) -> ToolResult:
        """获取商品销量排行（哪个商品卖得最好）

        转发 admin-api GET /api/admin/dashboard/product-ranking（按 productId 聚合销量/金额），
        period=day 近 7 天 / month 近 30 天。返回 ProductRanking[]（rank/productName/salesQty/...）。
        """
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/product-ranking",
            params={"period": period, "limit": limit},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="商品销量排行查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        logger.info(
            f"[dashboard-stats] Product ranking fetched, period={period}, limit={limit} "
            f"| tenant={context.tenant_id}"
        )

        # 统一 data 结构为 dict（ToolResult.data 契约要求 dict）：
        # admin-api 返回 ProductRanking[]（list）→ 包成 {"items": [...]}；
        # 兼容已有 {"list"/"items"} 包裹形式。
        if isinstance(data, list):
            wrapped: Dict[str, Any] = {"items": data}
        else:
            wrapped = data if isinstance(data, dict) else {"items": []}

        # 构建摘要：榜首商品 + 排行条数
        ranking_list = wrapped.get("items", wrapped.get("list", []))
        top_name = ""
        if isinstance(ranking_list, list) and ranking_list:
            first = ranking_list[0]
            top_name = first.get("productName") or first.get("product_name") or ""
        period_label = "本月" if period == "month" else "近7天"
        summary = f"{period_label}销量排行: {len(ranking_list) if isinstance(ranking_list, list) else 0}个商品"
        if top_name:
            summary += f"，榜首「{top_name}」"
        return ToolResult(
            success=True,
            data=wrapped,
            message="商品销量排行数据已获取",
            summary=summary,
        )

    async def _pending_tasks(self, context: ToolContext) -> ToolResult:
        """待办任务（GET /api/admin/dashboard/pending-tasks，dashboard:view）"""
        client = get_admin_api_client()
        # ⚠️ 端点路径必须**字面量写在调用点**（静态归属门禁 + 权限守卫的端点对账都靠静态可渲染）
        response = await client.get(
            "/api/admin/dashboard/pending-tasks",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        return self._dashboard_map_result(response, "待办任务", "pending_tasks")

    async def _pending_shipment_count(self, context: ToolContext) -> ToolResult:
        """待发货单数（GET /api/admin/dashboard/pending-shipment-count，dashboard:view）"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/pending-shipment-count",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        return self._dashboard_map_result(response, "待发货单数", "pending_shipment_count")

    async def _processing_shipment_count(self, context: ToolContext) -> ToolResult:
        """加工中待发货单数（GET /api/admin/dashboard/processing-shipment-count，dashboard:view）"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/dashboard/processing-shipment-count",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        return self._dashboard_map_result(response, "加工中待发货单数", "processing_shipment_count")

    def _dashboard_map_result(self, response, label: str, action: str) -> ToolResult:
        """三处「计数/待办」只读端点的共用**结果形态**（错误处理只写一份，路径各自字面量）。"""
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"{label}查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )
        data = response.get("data", {})
        # 计数端点（pending-shipment-count / processing-shipment-count）的 `data` 是**裸标量**
        # （`DashboardController` 返回 `ApiResponse<Long>`）⇒ 包成 dict 满足 `ToolResult.data`
        # 的 dict 契约。不包 ⇒ pydantic ValidationError ⇒ 这两个 action **恒失败**
        # （issue #6044 缺陷 B，2026-10-02 B 端真实评测实测）。
        # 复用同文件既有约定：list ⇒ `{"list": …}`（order_trend 等）、dict 原样
        # （product_ranking 的 `{"items": …}` 同理）。
        if not isinstance(data, dict):
            data = {"count": data}
        logger.info(f"[dashboard-stats] {action} fetched")
        return ToolResult(
            success=True,
            data=data,
            message=f"{label}已获取",
            summary=f"{label}: {data.get('count', '?')}",
        )
