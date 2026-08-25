"""NotificationManageTool 单元测试 — 通知查询/标记已读/删除/创建。"""
# case_ids: ST-004, ST-005
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.notification_manage import NotificationManageTool


@pytest.fixture
def tool():
    return NotificationManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def agent_tool_context():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess", role="agent")


class TestNotificationPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_allowed(self, tool, agent_tool_context):
        with patch("app.tools.notification_manage.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
            mock_get_client.return_value = mock_client
            result = await tool.execute(context=agent_tool_context, action="list")
            assert result.success is True

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="broadcast")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestNotificationList:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_passthrough_with_mapping(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "n1"}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="list", page="2", size="5", status="unread", channel="system")
        assert result.success is True
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        # 状态映射 unread→sent；渠道映射 system→internal
        assert params["status"] == "sent"
        assert params["channel"] == "internal"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list", status="archived")
        assert result.success is False
        assert "无效的通知状态" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_invalid_channel(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list", channel="carrier_pigeon")
        assert result.success is False
        assert "无效的通知渠道" in result.error
        mock_client.get.assert_not_called()


class TestNotificationUnreadCount:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_unread_count(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"count": 5}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="unread_count")
        assert result.success is True
        assert result.data["unread_count"] == 5
        assert mock_client.get.call_args[0][0] == "/api/admin/notifications/unread-count"


class TestNotificationMarkRead:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="mark_read")
        assert result.success is False
        assert "缺少通知 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="mark_read", notification_id="n1")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/notifications/n1/read"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_read_all(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="read_all")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/notifications/read-all"


class TestNotificationDelete:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "缺少通知 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete", notification_id="n1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/notifications/n1"


class TestNotificationCreate:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create", title="t", content="c")
        assert r1.success is False and "缺少接收人 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create", recipient_id="u1", content="c")
        assert r2.success is False and "缺少通知标题" in r2.error
        r3 = await tool.execute(context=admin_tool_context, action="create", recipient_id="u1", title="t")
        assert r3.success is False and "缺少通知内容" in r3.error
        mock_client.post.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_invalid_channel(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="u1", title="t", content="c",
            channel="carrier_pigeon")
        assert result.success is False
        assert "无效的通知渠道" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_channel_mapping(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "n-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="u1", title="t", content="c",
            channel="system")
        assert result.success is True
        assert result.data["id"] == "n-new"
        assert mock_client.post.call_args[0][0] == "/api/admin/notifications"
        assert mock_client.post.call_args[1]["json_data"]["channel"] == "internal"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_exception_generic(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="u1", title="t", content="c")
        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert "boom" not in (result.message or "")
