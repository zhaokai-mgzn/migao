"""
库存汇总查询 Tool 单元测试

测试 ProductInventoryTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.product_inventory import ProductInventoryTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return ProductInventoryTool()


@pytest.fixture
def sample_inventory_response():
    """模拟 admin-api 返回的库存汇总数据"""
    return {
        "success": True,
        "data": {
            "totalStock": 150,
            "totalSalesCount": 85,
            "totalSalesAmount": 25800.50,
            "skuDetails": [
                {
                    "id": "sku_001",
                    "skuCode": "CL-001-W-S",
                    "colorName": "米白色",
                    "sizeName": "2.0m",
                    "stock": 50,
                    "salesCount": 30,
                    "salesAmount": 8970.0,
                },
                {
                    "id": "sku_002",
                    "skuCode": "CL-001-W-M",
                    "colorName": "米白色",
                    "sizeName": "2.5m",
                    "stock": 30,
                    "salesCount": 25,
                    "salesAmount": 8725.0,
                },
                {
                    "id": "sku_003",
                    "skuCode": "CL-001-G-S",
                    "colorName": "深灰色",
                    "sizeName": "2.0m",
                    "stock": 70,
                    "salesCount": 30,
                    "salesAmount": 8105.50,
                },
            ],
        },
    }


class TestProductInventorySuccess:
    """库存汇总查询 - 成功场景"""

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_query_inventory_by_product_id(
        self, mock_get_client, tool, sample_tool_context, sample_inventory_response
    ):
        """通过商品ID查询库存汇总"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_inventory_response)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is True
        assert result.data["total_stock"] == 150
        assert result.data["total_sales_count"] == 85
        assert result.data["total_sales_amount"] == 25800.50
        assert result.data["sku_count"] == 3
        assert len(result.data["sku_details"]) == 3

        # 验证请求路径
        mock_client.get.assert_called_once_with(
            "/api/admin/products/prod_001/inventory-summary",
            tenant_id=sample_tool_context.tenant_id,
            user_id=sample_tool_context.user_id,
        )

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_query_inventory_by_product_name(
        self, mock_get_client, tool, sample_tool_context, sample_inventory_response
    ):
        """通过商品名称搜索后查询库存"""
        mock_client = AsyncMock()
        search_response = {
            "success": True,
            "data": {"items": [{"id": "prod_001", "name": "雪尼尔窗帘"}]},
        }
        mock_client.get = AsyncMock(side_effect=[search_response, sample_inventory_response])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_name="雪尼尔",
        )

        assert result.success is True
        assert result.data["total_stock"] == 150
        assert mock_client.get.call_count == 2

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_query_inventory_message_format(
        self, mock_get_client, tool, sample_tool_context, sample_inventory_response
    ):
        """验证返回消息格式"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_inventory_response)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert "总库存 150 件" in result.message
        assert "总销量 85 件" in result.message
        assert "¥25800.50" in result.message


class TestProductInventoryValidation:
    """库存汇总查询 - 参数验证"""

    async def test_missing_both_params(self, tool, sample_tool_context):
        """product_id 和 product_name 都没提供"""
        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert "缺少参数" in result.error

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_product_name_not_found(
        self, mock_get_client, tool, sample_tool_context
    ):
        """通过名称搜索但未找到商品"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_name="不存在的商品",
        )

        assert result.success is False
        assert "未找到" in result.message


class TestProductInventoryError:
    """库存汇总查询 - 异常处理"""

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_api_error_response(
        self, mock_get_client, tool, sample_tool_context
    ):
        """admin-api 返回错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "商品不存在"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="invalid_id",
        )

        assert result.success is False
        assert "失败" in result.message

    @patch("app.tools.product_inventory.get_admin_api_client")
    async def test_network_exception(
        self, mock_get_client, tool, sample_tool_context
    ):
        """网络异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "出错" in result.message


class TestProductInventoryPermission:
    """库存汇总查询 - 权限检查"""

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "权限" in result.message
