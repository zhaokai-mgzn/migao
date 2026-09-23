"""InventoryManageTool 单元测试 — 库存查询/低库存告警（只读）

B 端只读化（issue #5247）：inventory_manage（库存） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
"""
# case_ids: PR-004, PR-005, PR-006
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


# [RETIRED #5247] TestInventoryAdjust（3 例） 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


class TestInventoryStockAuthority:
    """库存数字的唯一权威 = SKU 级（issue #4038）—— query/adjust 不得直读商品级 stock。

    红证（改前 @ origin/main）：`_query` 用 `data.get("stock", 0)` 直读后端商品级聚合、
    `_adjust_inventory` 用 `product_data.get("stock", 0)` 取当前库存。
    实测 DB 里 311/497 个商品该列与 SKU 汇总不一致（有 SKU 的商品 299/351 恒为 0）。
    """

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_stock_follows_sku_authority(self, mock_get_client, tool, admin_tool_context):
        """后端商品级 `stock=0`（误导），SKU 合计 9599 ⇒ query 必须报 9599。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "name": "2699系列雪尼尔窗帘面料",
                "stock": 0,  # 商品级（非权威）
                "status": "on_sale",
                "skus": [{"stock": 9000}, {"stock": 599}],
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-2699")

        assert result.success is True
        assert result.data["stock"] == 9599
        assert result.data["stock_source"] == "sku_sum"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_no_sku_reports_unknown_not_zero(self, mock_get_client, tool, admin_tool_context):
        """无 SKU 记录 ⇒ `stock=None`（无法确认），不得谎报 0（会被读成「没货」）。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"name": "未维护规格的帘", "stock": 0, "status": "on_sale", "skus": []},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-nosku")

        assert result.success is True
        assert result.data["stock"] is None
        assert result.data["stock_source"] == "no_sku"
        assert "尚未维护 SKU" in result.message


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


class TestInventoryQueryValidation:
    """query 参数校验与租户隔离"""

    async def test_query_missing_product_id(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="query")
        assert result.success is False
        assert "缺少商品 ID" in result.error

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_tenant_mismatch(self, mock_get_client, tool, admin_tool_context):
        """响应 tenant_id 不一致 → 商品不存在（纵深防御）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"tenantId": 999, "stock": 10},
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="p1")
        assert result.success is False
        assert "商品不存在" in result.error

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_not_found(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False, "error": {"code": "NOT_FOUND", "message": "商品不存在"},
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="p1")
        assert result.success is False
        assert "商品不存在" in result.error

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_success_with_stock(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"name": "窗帘", "stock": 88, "status": "on_sale", "skus": [{"stock": 88}]},
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="p1")
        assert result.success is True
        assert result.data["stock"] == 88
        assert result.data["product_name"] == "窗帘"


# [RETIRED #5247] TestInventoryAdjustValidation（4 例） 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：调整入参校验随之消失，断言无对象。


class TestInventoryLowStockAlert:
    """低库存预警 - 颜色+规格维度 + 租户过滤"""

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_low_stock_tenant_filter(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": [
                {"productId": "p1", "productName": "窗帘", "skuCode": "SKU1", "tenantId": 1, "stock": 5},
                {"productId": "p2", "productName": "跨租户", "skuCode": "SKU2", "tenantId": 999, "stock": 3},
            ],
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="low_stock_alert", threshold=100)
        assert result.success is True
        assert result.data["count"] == 1
        assert result.data["items"][0]["sku_code"] == "SKU1"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_low_stock_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="low_stock_alert")
        assert result.success is True
        assert result.data["count"] == 0


class TestInventoryCustomerRestriction:
    """customer 角色仅允许 query"""

    # [RETIRED #5247] test_customer_adjust_denied 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：该权限断言的对象是写 action，写能力已不存在。

    async def test_customer_low_stock_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="low_stock_alert")
        assert result.success is False
        assert "权限不足" in result.error

    async def test_customer_query_denied(self, tool, sample_tool_context):
        """issue #5246：`inventory_manage` 是**B 端独占**工具（它的 `allowed_roles` 曾含 C 端
        角色 `customer`，属已确认的横向越权隐患）⇒ 现强调权限码 `product:list`/`product:create`，
        C 端角色的查询一律拒绝。"""
        result = await tool.execute(context=sample_tool_context, action="query", product_id="p1")
        assert result.success is False
        assert "权限" in result.error
