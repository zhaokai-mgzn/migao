"""NotificationManageTool 单元测试 — 通知管理"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.notification_manage import NotificationManageTool


@pytest.fixture
def tool():
    return NotificationManageTool()


class TestNotificationList:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "n1", "title": "新订单"}]}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True


class TestNotificationUnread:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_unread_count(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"count": 5}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="unread_count")
        assert result.success is True


class TestNotificationMarkRead:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="mark_read", notification_id="n1")
        assert result.success is True


class TestNotificationCreate:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "n-new"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="user-1", title="系统通知", content="欢迎使用")
        assert result.success is True


class TestNotificationPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error
