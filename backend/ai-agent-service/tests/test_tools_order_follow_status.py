"""
订单跟进状态 Tool 单元测试

测试 OrderFollowStatusTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.order_follow_status import OrderFollowStatusTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return OrderFollowStatusTool()


class TestOrderFollowStatusQuery:
    """订单跟进状态 - 查询场景"""

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_query_follow_status_success(
        self, mock_get_client, tool, admin_tool_context
    ):
        """查询订单跟进状态 - 成功"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "followStatus": "following",
                "updatedAt": "2024-01-15T10:30:00",
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="query",
            order_id="order_001",
        )

        assert result.success is True
        assert result.data["follow_status"] == "following"
        assert result.data["follow_status_label"] == "跟进中"
        assert "跟进中" in result.message

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_query_follow_status_pending(
        self, mock_get_client, tool, admin_tool_context
    ):
        """查询订单跟进状态 - 待跟进"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"followStatus": "pending"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="query",
            order_id="order_002",
        )

        assert result.success is True
        assert result.data["follow_status"] == "pending"
        assert "待跟进" in result.message

    async def test_query_missing_order_id(self, tool, admin_tool_context):
        """查询时缺少订单ID"""
        result = await tool.execute(
            context=admin_tool_context,
            action="query",
        )

        assert result.success is False
        assert "订单 ID" in result.message


class TestOrderFollowStatusUpdate:
    """订单跟进状态 - 更新场景"""

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_update_follow_status_success(
        self, mock_get_client, tool, admin_tool_context
    ):
        """更新订单跟进状态 - 成功"""
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={
            "success": True,
            "data": {"followStatus": "completed"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            order_id="order_001",
            new_status="completed",
        )

        assert result.success is True
        assert result.data["follow_status"] == "completed"
        assert "已完成" in result.message

        # 验证请求
        mock_client.put.assert_called_once_with(
            "/api/admin/orders/order_001/follow-status",
            json_data={"followStatus": "completed"},
            tenant_id=admin_tool_context.tenant_id,
            user_id=admin_tool_context.user_id,
        )

    async def test_update_missing_order_id(self, tool, admin_tool_context):
        """更新时缺少订单ID"""
        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            new_status="following",
        )

        assert result.success is False
        assert "订单 ID" in result.message

    async def test_update_missing_new_status(self, tool, admin_tool_context):
        """更新时缺少新状态"""
        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            order_id="order_001",
        )

        assert result.success is False
        assert "new_status" in result.message

    async def test_update_invalid_status(self, tool, admin_tool_context):
        """更新时传入无效状态"""
        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            order_id="order_001",
            new_status="invalid_status",
        )

        assert result.success is False
        assert "无效" in result.error


class TestOrderFollowStatusStats:
    """订单跟进状态 - 统计场景"""

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_get_stats_success(
        self, mock_get_client, tool, admin_tool_context
    ):
        """获取跟进统计 - 成功"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "total": 50,
                "pending": 20,
                "following": 15,
                "completed": 15,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="stats",
        )

        assert result.success is True
        assert result.data["total"] == 50
        assert result.data["pending"] == 20
        assert result.data["following"] == 15
        assert result.data["completed"] == 15
        assert "共 50 单" in result.message

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_get_stats_api_error(
        self, mock_get_client, tool, admin_tool_context
    ):
        """获取统计 - API错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "服务不可用"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="stats",
        )

        assert result.success is False
        assert "失败" in result.message


class TestOrderFollowStatusPermission:
    """订单跟进状态 - 权限检查"""

    async def test_permission_denied_customer(self, tool, sample_tool_context):
        """customer角色没有权限"""
        result = await tool.execute(
            context=sample_tool_context,
            action="query",
            order_id="order_001",
        )

        assert result.success is False
        assert "权限" in result.message

    async def test_permission_denied_guest(self, tool, unauthorized_tool_context):
        """guest角色没有权限"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            action="stats",
        )

        assert result.success is False
        assert "权限" in result.message


class TestOrderFollowStatusError:
    """订单跟进状态 - 异常处理"""

    async def test_invalid_action(self, tool, admin_tool_context):
        """无效操作类型"""
        result = await tool.execute(
            context=admin_tool_context,
            action="invalid_action",
        )

        assert result.success is False
        assert "不支持" in result.message

    @patch("app.tools.order_follow_status.get_admin_api_client")
    async def test_network_exception(
        self, mock_get_client, tool, admin_tool_context
    ):
        """网络异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="query",
            order_id="order_001",
        )

        assert result.success is False
        assert "失败" in result.message
