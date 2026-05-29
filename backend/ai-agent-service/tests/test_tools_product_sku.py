"""
商品SKU查询 Tool 单元测试

测试 ProductSkuTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.product_sku import ProductSkuTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return ProductSkuTool()


@pytest.fixture
def sample_sku_response():
    """模拟 admin-api 返回的SKU矩阵数据"""
    return {
        "success": True,
        "data": {
            "colors": [
                {
                    "colorName": "米白色",
                    "colorImage": "https://img.example.com/white.jpg",
                    "skus": [
                        {
                            "id": "sku_001",
                            "skuCode": "CL-001-W-S",
                            "size": "2.0m",
                            "price": 299.0,
                            "stock": 50,
                            "salesCount": 10,
                        },
                        {
                            "id": "sku_002",
                            "skuCode": "CL-001-W-M",
                            "size": "2.5m",
                            "price": 349.0,
                            "stock": 30,
                            "salesCount": 8,
                        },
                    ],
                },
                {
                    "colorName": "深灰色",
                    "colorImage": "https://img.example.com/gray.jpg",
                    "skus": [
                        {
                            "id": "sku_003",
                            "skuCode": "CL-001-G-S",
                            "size": "2.0m",
                            "price": 299.0,
                            "stock": 20,
                            "salesCount": 15,
                        },
                    ],
                },
            ],
        },
    }


class TestProductSkuSuccess:
    """商品SKU查询 - 成功场景"""

    @patch("app.tools.product_sku.get_admin_api_client")
    async def test_query_skus_by_product_id(
        self, mock_get_client, tool, sample_tool_context, sample_sku_response
    ):
        """通过商品ID查询SKU矩阵"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_sku_response)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is True
        assert result.data["color_count"] == 2
        assert result.data["total_sku_count"] == 3
        assert result.data["total_stock"] == 100
        assert len(result.data["colors"]) == 2
        assert result.data["colors"][0]["color_name"] == "米白色"
        assert len(result.data["colors"][0]["skus"]) == 2

    @patch("app.tools.product_sku.get_admin_api_client")
    async def test_query_skus_by_product_name(
        self, mock_get_client, tool, sample_tool_context, sample_sku_response
    ):
        """通过商品名称搜索后查询SKU"""
        mock_client = AsyncMock()
        # 第一次调用：搜索商品
        search_response = {
            "success": True,
            "data": {"items": [{"id": "prod_001", "name": "高遮光雪尼尔窗帘"}]},
        }
        # 第二次调用：查询SKU
        mock_client.get = AsyncMock(side_effect=[search_response, sample_sku_response])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_name="雪尼尔窗帘",
        )

        assert result.success is True
        assert result.data["color_count"] == 2
        assert mock_client.get.call_count == 2


class TestProductSkuValidation:
    """商品SKU查询 - 参数验证"""

    async def test_missing_both_params(self, tool, sample_tool_context):
        """product_id 和 product_name 都没提供"""
        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert "缺少参数" in result.error

    @patch("app.tools.product_sku.get_admin_api_client")
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


class TestProductSkuError:
    """商品SKU查询 - 异常处理"""

    @patch("app.tools.product_sku.get_admin_api_client")
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

    @patch("app.tools.product_sku.get_admin_api_client")
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


class TestProductSkuPermission:
    """商品SKU查询 - 权限检查"""

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "权限" in result.message


class TestProductSkuFormat:
    """商品SKU查询 - 格式化逻辑"""

    def test_format_sku_data_list_input(self, tool):
        """处理直接是列表的输入"""
        data = [
            {
                "colorName": "红色",
                "skus": [
                    {"id": "s1", "size": "L", "price": 100, "stock": 5},
                ],
            },
        ]
        formatted = tool._format_sku_data(data)

        assert formatted["color_count"] == 1
        assert formatted["total_sku_count"] == 1
        assert formatted["total_stock"] == 5

    def test_format_sku_data_empty(self, tool):
        """处理空数据"""
        formatted = tool._format_sku_data({"colors": []})

        assert formatted["color_count"] == 0
        assert formatted["total_sku_count"] == 0
        assert formatted["total_stock"] == 0
