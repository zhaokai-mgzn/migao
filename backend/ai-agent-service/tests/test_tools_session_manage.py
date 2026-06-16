"""SessionManageTool 单元测试 — 会话管理（列表/监控/详情/分配/结束）"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.session_manage import SessionManageTool


@pytest.fixture
def tool():
    return SessionManageTool()


class TestSessionList:
    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "s1", "status": "active", "customerName": "张三"}]}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")

        assert result.success is True

    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_list_with_status_filter(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list", status="active")

        assert result.success is True


class TestSessionMonitor:
    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_monitor(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"activeCount": 5, "waitingCount": 2}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="monitor")

        assert result.success is True


class TestSessionDetail:
    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_detail(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"id": "s1", "status": "active", "messages": []}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", session_id="s1")

        assert result.success is True

    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(context=admin_tool_context, action="detail")

        assert result.success is False


class TestSessionWrite:
    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_assign(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="assign",
            session_id="s1",
            employee_id="emp-1",
        )

        assert result.success is True

    @patch("app.tools.session_manage.get_admin_api_client")
    async def test_end(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="end",
            session_id="s1",
        )

        assert result.success is True


class TestSessionInvalidAction:
    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="invalid_op")

        assert result.success is False
        assert "不支持" in result.message
