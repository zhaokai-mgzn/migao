"""
C 端商品可见性单元测试（issue #3932）

小布（C 端顾客）只能看到已上架（on_sale）商品：下架（off_sale）等非上架商品
不得出现在 product_search 结果、product_detail 详情、C 端商品客服提示词中；
B 端（admin 等商户角色）保持现状——能看到自己店铺全状态商品。
"""
# case_ids: PR-001, PR-002, PR-007, PR-009, CH-001, PR-003, PR-019

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.product_search import ProductSearchTool
from app.tools.product_detail import ProductDetailTool
from app.graph.skills.customer_product_skill import CUSTOMER_PRODUCT_SYSTEM_PROMPT


@pytest.fixture
def search_tool():
    return ProductSearchTool()


@pytest.fixture
def detail_tool():
    return ProductDetailTool()


@pytest.fixture
def mixed_status_records():
    """模拟 admin-api 返回的含下架商品列表（tenantId 缺省 → 通过租户校验）"""
    return [
        {
            "id": "prod_on_001",
            "name": "在售雪尼尔窗帘",
            "basePrice": 299.0,
            "stock": 100,
            "status": "on_sale",
        },
        {
            "id": "prod_off_001",
            "name": "已下架遮光帘",
            "basePrice": 199.0,
            "stock": 50,
            "status": "off_sale",
        },
    ]


@pytest.fixture
def off_sale_product_data():
    """模拟 admin-api 返回的下架商品详情"""
    return {
        "id": "prod_off_001",
        "name": "已下架遮光帘",
        "description": "该商品已下架",
        "price": 199.0,
        "basePrice": 199.0,
        "stock": 50,
        "status": "off_sale",
        "categoryId": "cat_001",
        "images": [],
        "skus": [],
        "specifications": {},
    }


@pytest.fixture
def on_sale_product_data():
    """模拟 admin-api 返回的上架商品详情"""
    return {
        "id": "prod_on_001",
        "name": "在售雪尼尔窗帘",
        "description": "高品质雪尼尔面料",
        "price": 299.0,
        "basePrice": 299.0,
        "stock": 100,
        "status": "on_sale",
        "categoryId": "cat_001",
        "images": [],
        "skus": [],
        "specifications": {},
    }


class TestProductSearchCustomerVisibility:
    """product_search：C 端顾客只见已上架商品（issue #3932）"""

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_customer_search_forces_status_on_sale_param(
        self, mock_get_client, search_tool, sample_tool_context, mixed_status_records
    ):
        """C 端：请求参数必须下发后端真实字段 status=on_sale"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": mixed_status_records, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await search_tool.execute(context=sample_tool_context, keyword="窗帘")

        assert result.success is True
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params.get("status") == "on_sale"

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_customer_search_filters_off_sale_records(
        self, mock_get_client, search_tool, sample_tool_context, mixed_status_records
    ):
        """C 端：即使后端返回含 off_sale 记录，结果也只保留 on_sale，total 同步"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": mixed_status_records, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await search_tool.execute(context=sample_tool_context, keyword="窗帘")

        assert result.success is True
        # 本地纵深过滤：只保留 on_sale
        assert [p["id"] for p in result.data["products"]] == ["prod_on_001"]
        # total 取过滤后真实条数（与价格本地过滤同一语义）
        assert result.data["total"] == 1

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_customer_search_filters_record_missing_status(
        self, mock_get_client, search_tool, sample_tool_context
    ):
        """C 端：历史数据缺 status 字段的记录同样不展示（纵深防御）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "prod_legacy", "name": "旧数据商品", "basePrice": 99.0, "stock": 10},
                ],
                "total": 1,
            },
        })
        mock_get_client.return_value = mock_client

        result = await search_tool.execute(context=sample_tool_context, keyword="窗帘")

        assert result.success is True
        assert result.data["products"] == []
        assert result.data["total"] == 0

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_customer_search_all_off_sale_returns_empty(
        self, mock_get_client, search_tool, sample_tool_context, off_sale_product_data
    ):
        """C 端：全为下架商品 → 空结果、total=0（不暴露下架商品存在）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [off_sale_product_data], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await search_tool.execute(context=sample_tool_context, keyword="窗帘")

        assert result.success is True
        assert result.data["products"] == []
        assert result.data["total"] == 0

    @patch("app.tools.product_search.get_admin_api_client")
    async def test_admin_search_keeps_off_sale_records(
        self, mock_get_client, search_tool, admin_tool_context, mixed_status_records
    ):
        """B 端（admin）：原样保留 off_sale 记录、不下发 status 参数（不回归）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": mixed_status_records, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await search_tool.execute(context=admin_tool_context, keyword="窗帘")

        assert result.success is True
        assert len(result.data["products"]) == 2
        assert result.data["total"] == 2
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "status" not in params


class TestProductDetailCustomerVisibility:
    """product_detail：C 端顾客不能查看下架商品详情（issue #3932）"""

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_customer_detail_off_sale_returns_not_found(
        self, mock_get_client, detail_tool, sample_tool_context, off_sale_product_data
    ):
        """C 端：下架商品详情按「不存在」处理，不泄露商品名/ID"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": off_sale_product_data,
        })
        mock_get_client.return_value = mock_client

        result = await detail_tool.execute(
            context=sample_tool_context, product_id="prod_off_001"
        )

        assert result.success is False
        assert result.error == "商品不存在"
        assert "未找到该商品" in result.message
        assert "已下架遮光帘" not in (result.message or "")
        assert "prod_off_001" not in (result.message or "")

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_customer_detail_on_sale_returns_ok(
        self, mock_get_client, detail_tool, sample_tool_context, on_sale_product_data
    ):
        """C 端：上架商品详情正常返回"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": on_sale_product_data,
        })
        mock_get_client.return_value = mock_client

        result = await detail_tool.execute(
            context=sample_tool_context, product_id="prod_on_001"
        )

        assert result.success is True
        assert result.data["id"] == "prod_on_001"
        assert result.data["status"] == "on_sale"

    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_admin_detail_off_sale_returns_ok(
        self, mock_get_client, detail_tool, admin_tool_context, off_sale_product_data
    ):
        """B 端（admin）：下架商品详情正常返回（不回归）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": off_sale_product_data,
        })
        mock_get_client.return_value = mock_client

        result = await detail_tool.execute(
            context=admin_tool_context, product_id="prod_off_001"
        )

        assert result.success is True
        assert result.data["name"] == "已下架遮光帘"


class TestCustomerProductSkillPrompt:
    """customer_product_skill：C 端商品客服提示词必须含「已上架」原则（issue #3932）"""

    def test_system_prompt_contains_on_sale_principle(self):
        assert "已上架" in CUSTOMER_PRODUCT_SYSTEM_PROMPT
        assert "下架" in CUSTOMER_PRODUCT_SYSTEM_PROMPT
