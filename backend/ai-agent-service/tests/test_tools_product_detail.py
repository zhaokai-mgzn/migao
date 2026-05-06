"""
商品详情 Tool 单元测试

测试 ProductDetailTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.product_detail import ProductDetailTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return ProductDetailTool()


@pytest.fixture
def sample_product_data():
    """模拟 admin-api 返回的商品详情"""
    return {
        "id": "prod_001",
        "name": "高遮光雪尼尔窗帘",
        "description": "高品质雪尼尔面料，遮光率95%",
        "price": 299.0,
        "basePrice": 299.0,
        "originalPrice": 399.0,
        "stock": 100,
        "status": "active",
        "categoryId": "cat_001",
        "categoryName": "遮光窗帘",
        "images": ["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"],
        "mainImage": "https://img.example.com/1.jpg",
        "skus": [
            {
                "id": "sku_001",
                "skuCode": "CURTAIN-001-WHITE",
                "specifications": {"color": "白色", "size": "2.8m"},
                "price": 299.0,
                "stock": 50,
                "status": "active",
            },
            {
                "id": "sku_002",
                "skuCode": "CURTAIN-001-GRAY",
                "specifications": {"color": "灰色", "size": "2.8m"},
                "price": 299.0,
                "stock": 50,
                "status": "active",
            },
        ],
        "specifications": {"fabric": "雪尼尔", "width": "2.8m"},
        "processingItems": [{"name": "打孔", "price": 10.0}],
        "salesCount": 500,
        "createdAt": "2026-01-01T00:00:00Z",
    }


class TestProductDetailSuccess:
    """商品详情 - 成功场景"""

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_success(
        self, mock_get_client, tool, sample_tool_context, sample_product_data
    ):
        """正常查询商品详情"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": sample_product_data,
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is True
        assert result.data["id"] == "prod_001"
        assert result.data["name"] == "高遮光雪尼尔窗帘"
        assert result.data["price"] == 299.0
        assert result.data["original_price"] == 399.0
        assert len(result.data["skus"]) == 2
        assert result.data["sales_count"] == 500
        assert "高遮光雪尼尔窗帘" in result.message

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_format_skus(
        self, mock_get_client, tool, sample_tool_context, sample_product_data
    ):
        """验证 SKU 格式化"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": sample_product_data,
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        skus = result.data["skus"]
        assert skus[0]["id"] == "sku_001"
        assert skus[0]["sku_code"] == "CURTAIN-001-WHITE"
        assert skus[0]["specifications"]["color"] == "白色"
        assert skus[1]["sku_code"] == "CURTAIN-001-GRAY"


class TestProductDetailNotFound:
    """商品详情 - 商品不存在"""

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_not_found_error_code(
        self, mock_get_client, tool, sample_tool_context
    ):
        """API 返回 NOT_FOUND 错误码"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "商品不存在"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_nonexist",
        )

        assert result.success is False
        assert "不存在" in result.error or "不存在" in result.message

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_empty_data(
        self, mock_get_client, tool, sample_tool_context
    ):
        """API 返回成功但 data 为空"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_empty",
        )

        assert result.success is False
        assert "不存在" in result.error or "不存在" in result.message


class TestProductDetailValidation:
    """商品详情 - 参数验证"""

    async def test_product_detail_empty_id(self, tool, sample_tool_context):
        """空商品 ID"""
        result = await tool.execute(
            context=sample_tool_context,
            product_id="",
        )

        assert result.success is False
        assert "商品 ID" in result.message or "商品 ID" in result.error

    async def test_product_detail_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色查询被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "权限" in result.error or "权限" in result.message


class TestProductDetailError:
    """商品详情 - 异常处理"""

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_network_error(
        self, mock_get_client, tool, sample_tool_context
    ):
        """网络异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "出错" in result.message

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_api_generic_error(
        self, mock_get_client, tool, sample_tool_context
    ):
        """API 返回通用错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "失败" in result.message or "重试" in result.message


class TestProductDetailFormatProduct:
    """商品详情 - _format_product 方法"""

    def test_format_product_complete_data(self, tool, sample_product_data):
        """格式化完整商品数据"""
        product = tool._format_product(sample_product_data)

        assert product["id"] == "prod_001"
        assert product["name"] == "高遮光雪尼尔窗帘"
        assert product["price"] == 299.0
        assert product["original_price"] == 399.0
        assert product["category_name"] == "遮光窗帘"
        assert len(product["skus"]) == 2
        assert product["processing_items"] == [{"name": "打孔", "price": 10.0}]

    def test_format_product_minimal_data(self, tool):
        """格式化最少字段的商品"""
        product = tool._format_product({"id": "prod_min", "name": "最小商品"})

        assert product["id"] == "prod_min"
        assert product["name"] == "最小商品"
        assert product["skus"] == []
        assert product["sales_count"] == 0

    def test_format_skus_empty(self, tool):
        """格式化空 SKU 列表"""
        skus = tool._format_skus([])
        assert skus == []

        skus = tool._format_skus(None)
        assert skus == []
