"""QuickReplyManageTool 单元测试 — 快捷回复 CRUD"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.quick_reply_manage import QuickReplyManageTool


@pytest.fixture
def tool():
    return QuickReplyManageTool()


class TestQuickReplyList:
    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_list_replies(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "r1", "title": "欢迎语", "content": "您好！"}]}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")

        assert result.success is True

    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_list_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")

        assert result.success is True


class TestQuickReplyCreate:
    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_create(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "new-r1", "title": "新回复"}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            title="新回复",
            content="您好，有什么可以帮您？",
            category="greeting",
        )

        assert result.success is True

    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_create_with_category(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "r2", "categoryId": "cat-1"}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            title="售后回复",
            content="您的售后工单已创建",
            category="cat-1",
        )

        assert result.success is True


class TestQuickReplyUpdate:
    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_update(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={
            "success": True, "data": {"id": "r1", "title": "已更新"}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            reply_id="r1",
            title="已更新",
        )

        assert result.success is True


class TestQuickReplyDelete:
    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_delete(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="delete",
            reply_id="r1",
        )

        assert result.success is True


class TestQuickReplyPermission:
    @patch("app.tools.quick_reply_manage.get_admin_api_client")
    async def test_customer_no_write(self, mock_get_client, tool, sample_tool_context):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(
            context=sample_tool_context,
            action="create",
            title="x",
            content="y",
        )

        assert result.success is False
        assert "权限" in result.error or "权限" in result.message
