"""InventoryManageTool 单元测试 — 库存查询/调整/低库存告警"""
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


class TestInventoryAdjust:
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjust_uses_agent_stock_endpoint(self, mock_get_client, tool, admin_tool_context):
        """生产回归修复：库存调整必须走 agent 专用库存端点并校验读回。

        旧实现 PUT /api/admin/products/{id} 传 stock，admin-api 静默忽略该字段
        但仍返回 success → agent 报"50→80"而 DB 仍是 50（假成功）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"name": "窗帘-欧式", "stock": 100}
        })
        mock_client.patch = AsyncMock(return_value={
            "success": True, "data": {"name": "窗帘-欧式", "stock": 150}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=50, reason="盘点调整")
        assert result.success is True
        # 必须调用 agent 专用库存端点，且透传 adjustment/reason
        path = mock_client.patch.call_args.args[0]
        assert path == "/api/admin/agent/products/prod-1/stock"
        body = mock_client.patch.call_args.kwargs.get("json_data", {})
        assert body.get("adjustment") == 50
        assert body.get("reason") == "盘点调整"
        assert result.data.get("new_stock") == 150

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjust_readback_mismatch_fails_closed(self, mock_get_client, tool, admin_tool_context):
        """端点返回 success 但读回库存与预期不符 → 必须报失败（杜绝假成功）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"name": "窗帘-欧式", "stock": 100}
        })
        mock_client.patch = AsyncMock(return_value={
            "success": True, "data": {"name": "窗帘-欧式", "stock": 100}  # 未被更新
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=50, reason="盘点调整")
        assert result.success is False
        assert "未生效" in (result.message or "")

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjust_endpoint_error_fails_closed(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"stock": 100}
        })
        mock_client.patch = AsyncMock(return_value={"success": False, "error": {"message": "库存不足"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=50, reason="盘点调整")
        assert result.success is False


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
            "success": True, "data": {"name": "窗帘", "stock": 88, "status": "on_sale"},
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="query", product_id="p1")
        assert result.success is True
        assert result.data["stock"] == 88
        assert result.data["product_name"] == "窗帘"


class TestInventoryAdjustValidation:
    """adjust 参数校验与库存不足"""

    async def test_adjust_missing_product_id(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="adjust", adjustment=1, reason="r")
        assert result.success is False
        assert "缺少商品 ID" in result.error

    async def test_adjust_missing_adjustment(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="adjust", product_id="p1", reason="r")
        assert result.success is False
        assert "缺少调整数量" in result.error

    async def test_adjust_missing_reason(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="adjust", product_id="p1", adjustment=1)
        assert result.success is False
        assert "缺少调整原因" in result.error

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjust_insufficient_stock(self, mock_get_client, tool, admin_tool_context):
        """new_stock < 0 → 库存不足"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"name": "窗帘", "stock": 5}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="adjust", product_id="p1", adjustment=-10, reason="出库")
        assert result.success is False
        assert "库存不足" in result.error


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

    async def test_customer_adjust_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="adjust", product_id="p1", adjustment=1, reason="r")
        assert result.success is False
        assert "权限不足" in result.error

    async def test_customer_low_stock_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="low_stock_alert")
        assert result.success is False
        assert "权限不足" in result.error

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_customer_query_allowed(self, mock_get_client, tool, sample_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"name": "窗帘", "stock": 10}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=sample_tool_context, action="query", product_id="p1")
        assert result.success is True
