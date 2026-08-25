"""ProcessingItemManageTool 单元测试 — 加工项/加工分类 CRUD + 价格计算。"""
# case_ids: PP-002, PP-003, PP-004
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.processing_item_manage import ProcessingItemManageTool


@pytest.fixture
def tool():
    return ProcessingItemManageTool()


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


class TestProcessingPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_denied(self, tool, agent_tool_context):
        result = await tool.execute(context=agent_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="remove_item")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestProcessingItemCreate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create_item", category_id="c1", price=5.0)
        assert r1.success is False and "缺少加工项名称" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create_item", name="打孔", price=5.0)
        assert r2.success is False and "缺少分类 ID" in r2.error
        r3 = await tool.execute(context=admin_tool_context, action="create_item", name="打孔", category_id="c1")
        assert r3.success is False and "缺少价格" in r3.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create_item", name="打孔", price=5.0, category_id="c1")
        assert result.success is True
        assert result.data["id"] == "pi-new"
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items"
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["categoryId"] == "c1"
        assert json_data["price"] == 5.0


class TestProcessingItemUpdate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", name="打孔")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", item_id="pi-1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1", name="打孔(更新)", price=6.0)
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1"


class TestProcessingItemDelete:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_item")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_item", item_id="pi-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-items/pi-1"


class TestProcessingToggleStatus:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_item_status", status="active")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="archived")
        assert result.success is False
        assert "无效的状态值" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_active(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="active")
        assert result.success is True
        assert "已启用" in result.message
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1/status"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_inactive(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="inactive")
        assert result.success is True
        assert "已停用" in result.message


class TestProcessingCategories:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_list_categories(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "pc-1"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_categories")
        assert result.success is True
        assert result.data["categories"] == [{"id": "pc-1"}]
        assert mock_client.get.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create_category")
        assert result.success is False
        assert "缺少分类名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pc-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create_category", name="高级加工")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="update_category", name="新名")
        assert r1.success is False and "缺少分类 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="update_category", category_id="pc-1")
        assert r2.success is False and "缺少分类名称" in r2.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_category", category_id="pc-1", name="新名")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-categories/pc-1"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_category")
        assert result.success is False
        assert "缺少分类 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_category", category_id="pc-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-categories/pc-1"


class TestProcessingCalculatePrice:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="calculate_price", quantity=2)
        assert r1.success is False and "缺少加工项 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="calculate_price", processing_item_id="pi-1")
        assert r2.success is False and "缺少数量" in r2.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_priority(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": True, "data": {"totalPrice": 100, "total_price": 90},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "100" in result.message
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items/calculate"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_fallback(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"total_price": 90}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "90" in result.message
