"""DashboardStatsTool 单元测试 — 经营看板 5 类统计查询"""
# case_ids: DA-001, DA-002, DA-003
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.dashboard_stats import DashboardStatsTool
from app.tools.base import ToolContext


@pytest.fixture
def tool():
    return DashboardStatsTool()


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")


class TestDashboardDeclaration:
    """工具元数据声明 — READONLY 纯查询，admin/agent/tenant_admin 可用"""

    def test_metadata(self, tool):
        assert tool.name == "dashboard_stats"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_allowed_roles(self, tool):
        assert set(tool.allowed_roles) == {"admin", "agent", "tenant_admin"}


class TestDashboardPermission:
    """角色权限"""

    def test_admin_allowed(self, tool, admin_tool_context):
        assert tool.check_permission(admin_tool_context) is True

    def test_agent_allowed(self, tool, agent_ctx):
        assert tool.check_permission(agent_ctx) is True

    def test_customer_denied(self, tool, sample_tool_context):
        assert tool.check_permission(sample_tool_context) is False

    async def test_execute_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="overview")
        assert result.success is False
        assert "权限" in result.error


class TestDashboardInvalid:
    """无效 action 拒绝"""

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="invalid_op")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestDashboardOverview:
    """经营概览 overview — DA-001"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_overview_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"todayOrderCount": 12, "todaySalesAmount": 3456.78},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is True
        assert result.data["todayOrderCount"] == 12
        assert "今日订单12单" in result.summary
        assert "销售额3456.78元" in result.summary
        mock_client.get.assert_called_once()
        assert "/api/admin/dashboard/stats" in mock_client.get.call_args[0][0]

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_overview_fallback_total(self, mock_get_client, tool, admin_tool_context):
        """data 缺 todayOrderCount/todaySalesAmount 时回退 totalOrders/totalAmount"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"totalOrders": 5, "totalAmount": 100},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is True
        assert "今日订单5单" in result.summary
        assert "销售额100元" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_overview_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "上游异常"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is False
        assert "上游异常" in result.error

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_overview_list_response_defense(self, mock_get_client, tool, admin_tool_context):
        """admin-api 返回 list 时防御性包装，不崩溃"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=[{"a": 1}])
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is False


class TestDashboardOrderTrend:
    """订单趋势 order_trend — DA-002"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_trend_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"list": [{"date": "07-01"}, {"date": "07-02"}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_trend", days=7)

        assert result.success is True
        assert "近7天订单趋势" in result.summary
        assert "2个数据点" in result.summary
        assert "days" in mock_client.get.call_args.kwargs["params"]

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_trend_default_days(self, mock_get_client, tool, admin_tool_context):
        """days 缺省默认 7"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"trend": []}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_trend")

        assert result.success is True
        assert mock_client.get.call_args.kwargs["params"]["days"] == 7

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_trend_list_response_defense(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=[1, 2, 3])
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_trend")

        assert result.success is False

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_trend_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "失败"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_trend")

        assert result.success is False


class TestDashboardOrderStatus:
    """订单状态分布 order_status"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_status_dict(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"distribution": {"已完成": 5, "生产中": 2}},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_status")

        assert result.success is True
        assert "已完成:5" in result.summary
        assert "生产中:2" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_status_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"status": "已完成"}, {"status": "生产中"}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_status")

        assert result.success is True
        assert "2种状态" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_status_scalar(self, mock_get_client, tool, admin_tool_context):
        """distribution 为非 dict/list 标量时走「已获取」兜底"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"distribution": "已完成"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_status")

        assert result.success is True
        assert "已获取" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_order_status_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "失败"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="order_status")

        assert result.success is False


class TestDashboardRecentOrders:
    """最近订单 recent_orders — DA-003"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_recent_orders_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"list": [{"id": "o1"}, {"id": "o2"}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="recent_orders", limit=5)

        assert result.success is True
        assert "最近2条订单" in result.summary
        assert mock_client.get.call_args.kwargs["params"]["limit"] == 5

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_recent_orders_records(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"records": [{"id": "o1"}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="recent_orders")

        assert result.success is True
        assert "最近1条订单" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_recent_orders_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "失败"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="recent_orders")

        assert result.success is False


class TestDashboardActiveSessions:
    """活跃会话 active_sessions"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_active_sessions_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"sessions": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="active_sessions", limit=5)

        assert result.success is True
        assert "当前3个活跃会话" in result.summary

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_active_sessions_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "失败"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="active_sessions")

        assert result.success is False


class TestDashboardException:
    """execute 异常 → tool_execution_failed 泛化"""

    @patch("app.tools.dashboard_stats.get_admin_api_client")
    async def test_execute_exception(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="overview")

        assert result.success is False
        assert result.error == "tool_execution_failed"
