"""
商品搜索 Tool 单元测试

测试 ProductSearchTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.tools.product_search import ProductSearchTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return ProductSearchTool()


@pytest.fixture
def sample_product_records():
    """模拟 admin-api 返回的商品列表"""
    return [
        {
            "id": "prod_001",
            "name": "高遮光雪尼尔窗帘",
            "price": 299.0,
            "basePrice": 299.0,
            "description": "高品质雪尼尔面料，遮光率95%",
            "images": ["https://img.example.com/1.jpg"],
            "mainImage": "https://img.example.com/1.jpg",
            "stock": 100,
            "status": "active",
            "categoryId": "cat_001",
            "specifications": {"fabric": "雪尼尔", "width": "2.8m"},
        },
        {
            "id": "prod_002",
            "name": "简约纯色遮光帘",
            "price": 199.0,
            "basePrice": 199.0,
            "description": "简约风格，多色可选",
            "images": ["https://img.example.com/2.jpg"],
            "mainImage": "https://img.example.com/2.jpg",
            "stock": 50,
            "status": "active",
            "categoryId": "cat_001",
            "specifications": {"fabric": "涤纶", "width": "2.5m"},
        },
    ]


class TestProductSearchSuccess:
    """商品搜索 - 成功场景"""

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_success_with_keyword(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """搜索关键词，正常返回结果"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": sample_product_records,
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="遮光窗帘",
        )

        assert result.success is True
        assert len(result.data["products"]) == 2
        assert result.data["total"] == 2
        assert result.data["page"] == 1
        assert result.data["size"] == 5
        mock_client.get.assert_called_once()

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_with_pagination(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """带分页参数搜索"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": sample_product_records[:1],
                "total": 10,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            page=2,
            size=1,
        )

        assert result.success is True
        assert result.data["page"] == 2
        assert result.data["size"] == 1
        assert result.data["total"] == 10
        assert result.data["total_pages"] == 10

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_with_category(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """带分类 ID 搜索"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": sample_product_records,
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            category_id="cat_001",
        )

        assert result.success is True
        # 验证参数传递了 categoryId
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs.get("params", {}).get("categoryId") == "cat_001" or \
               call_kwargs[1].get("params", {}).get("categoryId") == "cat_001"

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_with_price_range(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """带价格区间搜索"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": sample_product_records[:1],
                "total": 1,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            min_price=200.0,
            max_price=500.0,
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params.get("minPrice") == 200.0
        assert params.get("maxPrice") == 500.0


class TestProductSearchEmpty:
    """商品搜索 - 空结果场景"""

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_empty_results(
        self, mock_get_client, tool, sample_tool_context
    ):
        """搜索无结果"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [],
                "total": 0,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="不存在的商品",
        )

        assert result.success is True
        assert result.data["products"] == []
        assert result.data["total"] == 0
        assert "没有找到" in result.message

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_empty_keyword(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """空关键词搜索（浏览所有商品）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": sample_product_records,
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="",
        )

        assert result.success is True
        assert len(result.data["products"]) == 2


class TestProductSearchPermission:
    """商品搜索 - 权限检查"""

    async def test_product_search_permission_denied(
        self, tool, unauthorized_tool_context
    ):
        """无权限角色搜索被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            keyword="窗帘",
        )

        assert result.success is False
        assert "权限" in result.error or "权限" in result.message


class TestProductSearchError:
    """商品搜索 - 异常处理"""

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_api_error(
        self, mock_get_client, tool, sample_tool_context
    ):
        """admin-api 返回错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "内部服务错误"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
        )

        assert result.success is False
        assert "失败" in result.message

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_network_exception(
        self, mock_get_client, tool, sample_tool_context
    ):
        """网络异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
        )

        assert result.success is False
        assert "出错" in result.message

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_malformed_response(
        self, mock_get_client, tool, sample_tool_context
    ):
        """API 返回格式异常（缺少 data 字段）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            # data 字段为空
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
        )

        # 即使 data 为空，也应该优雅处理
        assert result.success is True
        assert result.data["products"] == []


class TestProductSearchFormatProducts:
    """商品搜索 - _format_products 方法"""

    def test_format_products_normal(self, tool, sample_product_records):
        """格式化正常商品列表"""
        products = tool._format_products(sample_product_records)

        assert len(products) == 2
        assert products[0]["id"] == "prod_001"
        assert products[0]["name"] == "高遮光雪尼尔窗帘"
        assert products[0]["price"] == 299.0
        assert products[0]["main_image"] == "https://img.example.com/1.jpg"

    def test_format_products_empty_list(self, tool):
        """格式化空列表"""
        products = tool._format_products([])
        assert products == []

    def test_format_products_missing_fields(self, tool):
        """格式化缺少字段的商品"""
        records = [{"id": "prod_003", "name": "测试商品"}]
        products = tool._format_products(records)

        assert len(products) == 1
        assert products[0]["id"] == "prod_003"
        assert products[0]["price"] is None
        assert products[0]["main_image"] is None
