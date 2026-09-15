"""
商品搜索 Tool 单元测试

测试 ProductSearchTool.execute() 的各种场景
"""
# case_ids: PR-001, PR-002, PR-007, PR-009

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
            "status": "on_sale",
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
            "status": "on_sale",
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
    async def test_product_search_price_range_is_local_filter_not_backend_param(
        self, mock_get_client, tool, sample_tool_context
    ):
        """价格区间：后端 ProductQueryRequest 无价格字段 → 禁止下发，改本地过滤

        Red（修复前）：下发 params["minPrice"]/["maxPrice"]（后端静默忽略）→ 返回全量 →
        LLM 把全量叙述成「已筛选出 100-200 元」= 幻觉式筛选（工具审计 A1）。
        Green（修复后）：不下发后端不认的键；本地按价格过滤；total = 过滤后真实条数。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "p_low", "name": "低价帘", "basePrice": 80.0, "stock": 5, "status": "on_sale"},
                    {"id": "p_mid", "name": "中价帘", "basePrice": 199.0, "stock": 5, "status": "on_sale"},
                    {"id": "p_high", "name": "高价帘", "basePrice": 299.0, "stock": 5, "status": "on_sale"},
                ],
                "total": 3,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            min_price=100.0,
            max_price=200.0,
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        # 后端 ProductQueryRequest 无 minPrice/maxPrice（Spring 静默忽略）→ 一个都不许下发
        assert "minPrice" not in params
        assert "maxPrice" not in params
        # 本地过滤：只有 199 落在 100-200
        assert [p["id"] for p in result.data["products"]] == ["p_mid"]
        # total 必须是过滤后的真实条数，不能沿用后端全量 total=3
        assert result.data["total"] == 1
        assert "1" in result.message and "价格" in result.message

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_price_filter_no_match_reports_scope(
        self, mock_get_client, tool, sample_tool_context
    ):
        """价格区间本地过滤零命中：必须说明是价格区间没筛到，不能报「没有找到与'窗帘'相关的商品」

        Red（修复前）：过滤未生效 → 返回全量商品（products == [] 断言失败）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "p_low", "name": "低价帘", "basePrice": 80.0, "stock": 5, "status": "on_sale"},
                    {"id": "p_high", "name": "高价帘", "basePrice": 299.0, "stock": 5, "status": "on_sale"},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            min_price=100.0,
            max_price=200.0,
        )

        assert result.success is True
        assert result.data["products"] == []
        assert result.data["total"] == 0
        # 商品是存在的，只是不在价格区间 → 措辞要说清是价格区间没筛到
        assert "价格" in result.message

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_stock_status_maps_to_backend_stock_below(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """库存筛选：后端真实字段是 stockBelow，不是 stockStatus（工具审计 A1）

        Red（修复前）：下发 params["stockStatus"]=low_stock（后端不认 → 返回全量）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": sample_product_records, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            stock_status="low_stock",
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        # 与后台低库存口径一致（#1396：Dashboard/DailyBriefing/admin-web 均为 100）
        assert params.get("stockBelow") == 100
        assert "stockStatus" not in params

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_out_of_stock_maps_to_stock_below_zero(
        self, mock_get_client, tool, sample_tool_context, sample_product_records
    ):
        """缺货筛选：stockBelow=0（后端 stock <= 0）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": sample_product_records, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            stock_status="out_of_stock",
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params.get("stockBelow") == 0

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_rejects_stock_status_backend_cannot_express(
        self, mock_get_client, tool, sample_tool_context
    ):
        """in_stock 后端无法表达（stockBelow 只有 <= 语义）→ 必须明确拒绝，不下发死字段

        Red（修复前）：下发 stockStatus=in_stock → success=True（静默返回全量）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            keyword="窗帘",
            stock_status="in_stock",
        )

        assert result.success is False
        assert mock_client.get.call_count == 0
        assert "low_stock" in result.message or "low_stock" in (result.suggestion or "")


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
