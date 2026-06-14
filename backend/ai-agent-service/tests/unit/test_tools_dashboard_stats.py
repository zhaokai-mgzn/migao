"""
测试 app.tools.dashboard_stats — 数据统计工具（只读）
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.dashboard_stats import DashboardStatsTool


class TestDashboardStatsPermission:
    """权限校验"""

    async def test_customer_role_denied(self, unauthorized_tool_context):
        tool = DashboardStatsTool()
        result = await tool.execute(context=unauthorized_tool_context, action="overview")
        assert result.success is False


class TestDashboardStatsActions:
    """各 action 测试"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_overview_returns_stats(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "todayOrders": 50,
                "todaySales": 1299000,
                "totalCustomers": 2000,
                "activeSessions": 12,
                "monthRevenue": 50000000,
            },
        })
        mock_get_client.return_value = mock_client

        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is True
        assert result.summary is not None and len(result.summary) > 0

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_trend_returns_trend_data(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"list": [{"date": "2024-01-01", "orders": 10, "amount": 1000}]},
        })
        mock_get_client.return_value = mock_client

        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="order_trend", days=7)

        assert result.success is True

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_status_distribution(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"list": [{"status": "completed", "label": "已完成", "count": 30, "color": "#16a34a"}]},
        })
        mock_get_client.return_value = mock_client

        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="order_status")

        assert result.success is True

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_invalid_action_returns_error(self, mock_get_client, admin_tool_context):
        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="invalid_action")
        assert result.success is False


class TestDashboardStatsError:
    """错误处理"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_admin_api_returns_failure(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": "服务不可用"},
        })
        mock_get_client.return_value = mock_client

        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is False

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_network_error(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_get_client.return_value = mock_client

        tool = DashboardStatsTool()
        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is False
