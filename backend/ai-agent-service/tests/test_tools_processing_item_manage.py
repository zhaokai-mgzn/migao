"""ProcessingItemManageTool 单元测试 — 加工项/加工分类管理"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.processing_item_manage import ProcessingItemManageTool


@pytest.fixture
def tool():
    return ProcessingItemManageTool()


class TestProcessingItemCreate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create_item",
            name="打孔加工", price=5.0, category_id="cat-1")
        assert result.success is True


class TestProcessingItemUpdate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="update_item",
            item_id="pi-1", name="打孔加工(更新)")
        assert result.success is True


class TestProcessingItemCategories:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_list_categories(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": [{"id": "pc-1", "name": "基础加工"}]
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list_categories")
        assert result.success is True

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pc-new"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create_category", name="高级加工")
        assert result.success is True


class TestProcessingItemDelete:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_item", item_id="pi-1")
        assert result.success is True


class TestProcessingItemPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error
