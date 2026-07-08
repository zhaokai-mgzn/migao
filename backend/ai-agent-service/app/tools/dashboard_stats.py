"""
AI 智能客服系统 - 数据看板 Tool

获取Dashboard统计数据，支持概览统计、订单趋势、状态分布、最近订单、活跃会话。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"overview", "order_trend", "order_status", "recent_orders", "active_sessions"}


class DashboardStatsTool(BaseTool):
    """数据看板 Tool

    获取Dashboard统计数据，支持概览统计、订单趋势、状态分布、最近订单、活跃会话。

    使用场景：
    - 查看今日经营概览（订单数、客户数、工单等）
    - 查看订单趋势图数据
    - 查看订单状态分布（饼图数据）
    - 查看最近订单列表
    - 查看当前活跃的客服会话
    """

    name = "dashboard_stats"
    description = (
        "【触发】用户说'今天生意''经营看板''数据概览''订单趋势''状态分布''最近X条订单''活跃会话''看看数据'时，优先用本工具而非 order_query。【何时用】任何看板/趋势/分布/概览类查询。【何时不用】查某个具体订单（用 order_query）、查客服会话详情（用 session_manage）。【前置】action: overview(今日概览)/order_trend(趋势,需days)/order_status(状态分布)/recent_orders(最近,需limit)/active_sessions(活跃,需limit)。days默认7,limit默认5。【标注】READONLY — 经营分析专用，不查具体记录"
    )
    allowed_roles = ["admin", "agent", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型："
                    "overview（今日经营统计概览，含订单数/客户数/工单等指标） / "
                    "order_trend（订单趋势折线数据，需配合 days，适用于“最近 N 天订单趋势”场景） / "
                    "order_status（订单状态分布饼图数据） / "
                    "recent_orders（最近订单列表，需配合 limit） / "
                    "active_sessions（当前活跃客服会话列表，需配合 limit）"
                ),
                "enum": ["overview", "order_trend", "order_status", "recent_orders", "active_sessions"],
            },
            "days": {
                "type": "integer",
                "description": (
                    "查询天数范围，仅在 action=order_trend 时生效。"
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
                "description": "返回条数限制，仅在 action=recent_orders 或 active_sessions 时生效，默认 5。",
                "default": 5,
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
            )

        # 强制转换参数为 int
        days = int(days) if days else 7
        limit = int(limit) if limit else 5

        try:
            if action == "overview":
                return await self._overview(context)
            elif action == "order_trend":
                return await self._order_trend(context, days)
            elif action == "order_status":
                return await self._order_status(context)
            elif action == "recent_orders":
                return await self._recent_orders(context, limit)
            elif action == "active_sessions":
                return await self._active_sessions(context, limit)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[dashboard-stats] Error: action={action}, error={type(e).__name__}: {e}")
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
            return ToolResult(
                success=False,
                error=error_msg,
                message="统计概览查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
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
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单趋势查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        logger.info(f"[dashboard-stats] Order trend fetched, days={days} | tenant={context.tenant_id}")

        # 构建摘要：统计趋势数据点数量
        trend_points = len(data.get("list", data.get("trend", data.get("points", []))))
        return ToolResult(
            success=True,
            data=data,
            message=f"近 {days} 天订单趋势数据已获取",
            summary=f"近{days}天订单趋势: {trend_points}个数据点",
        )

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
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单状态分布查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
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
            return ToolResult(
                success=False,
                error=error_msg,
                message="最近订单查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
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
            return ToolResult(
                success=False,
                error=error_msg,
                message="活跃会话查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
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
