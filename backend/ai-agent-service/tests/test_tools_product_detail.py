"""
商品详情 Tool 单元测试

测试 ProductDetailTool.execute() 的各种场景
"""
# case_ids: CH-001, PR-003, PR-004

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
        "status": "on_sale",
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


class TestProductStockAuthority:
    """商品库存的唯一权威 = SKU 级（issue #4038）。

    红证（改前 @ origin/main）：`_format_product` 直读后端 `data["stock"]`。
    该字段是**商品级口径**，实测 DB 里 311/497 个商品与 SKU 汇总不一致 ——
    有 SKU 的 351 个商品里 **299 个商品级恒为 0**，而 SKU 合计可以很大
    （实测商品 `2699系列雪尼尔窗帘面料`：商品级 **0** / SKU 合计 **9599**，
    DB 复现：`select p.stock, (select sum(s.stock) from product_skus s where s.product_id=p.id)
    from products p where p.name like '2699系列%'`）。
    改前：后端给什么就报什么；无 SKU 的商品恒报 0（agent 会据此对用户说「没货」）。
    """

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_stock_follows_sku_authority_not_product_level(
        self, mock_get_client, tool, sample_tool_context
    ):
        """后端商品级 `stock=0`（误导），SKU 合计 9599 ⇒ 工具必须报 9599。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "prod_2699",
                "name": "2699系列雪尼尔窗帘面料",
                "price": 299.0,
                "stock": 0,  # 商品级（非权威）——实测该商品两列正是 0 vs 9599
                "status": "on_sale",
                "skus": [
                    {"id": "sku_a", "skuCode": "2699-01", "stock": 9000},
                    {"id": "sku_b", "skuCode": "2699-02", "stock": 599},
                ],
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, product_id="prod_2699")

        assert result.success is True
        assert result.data["stock"] == 9599, "商品库存数字必须来自 SKU 权威，而不是商品级 stock"
        assert result.data["stock_source"] == "sku_sum"

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_no_sku_product_reports_unknown_not_zero(
        self, mock_get_client, tool, sample_tool_context
    ):
        """无 SKU 记录 ⇒ `stock=None`（无法确认），且文案不得说成「库存 0 / 没货」。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "prod_nosku",
                "name": "未维护规格的帘",
                "price": 199.0,
                "stock": 0,
                "status": "on_sale",
                "skus": [],
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, product_id="prod_nosku")

        assert result.success is True
        assert result.data["stock"] is None, "无 SKU 记录不得谎报 0（会被读成「没货」）"
        assert result.data["stock_source"] == "no_sku"
        assert "尚未维护 SKU" in result.message, "必须把「无法确认库存」的原因告诉 LLM"


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
        # issue #4371：商品不再持有加工项 ⇒ product_detail 输出无 processing_items 键
        assert "processing_items" not in product

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
