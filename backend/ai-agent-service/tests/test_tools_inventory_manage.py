"""InventoryManageTool 单元测试 — 库存查询/调整/低库存告警"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.inventory_manage import InventoryManageTool


@pytest.fixture
def tool():
    return InventoryManageTool()


class TestInventoryQuery:
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"skuCode": "SKU001", "stock": 100}]}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-1")
        assert result.success is True

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-x")
        assert result.success is True


class TestInventoryAdjust:
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjust(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        # adjust 先 get 查库存，再 put 调整
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"stock": 100}})
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=50, reason="盘点调整")
        assert result.success is True


class TestLowStockAlert:
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_alert(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": [{"skuCode": "SKU001", "stock": 5}]
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="low_stock_alert")
        assert result.success is True


class TestInventoryInvalid:
    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="invalid")
        assert result.success is False
