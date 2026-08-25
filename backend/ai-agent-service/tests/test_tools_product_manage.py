"""ProductManageTool 单元测试 — 商品创建/更新/上下架。

对应 app/tools/product_manage.py 的 create/update/toggle_status 三条 action，
覆盖正常路径、参数校验、camelCase 字段映射、异常泛化兜底。
"""
# case_ids: PR-007, PR-008
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.product_manage import ProductManageTool


@pytest.fixture
def tool():
    return ProductManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.post = AsyncMock()
    client.patch = AsyncMock()
    client.put = AsyncMock()
    return client


class TestProductPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestProductCreate:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create")
        assert result.success is False
        assert "缺少商品名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_camel_case_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            name="窗帘",
            category_id="cat-1",
            price=100.5,
            stock_quantity=99,
            processing_item_ids=["pi-1"],
            processing_item_configs=[{"processingItemId": "pi-1", "customPrice": 10}],
            selling_methods=["bulk_cut"],
            door_widths=["2.8米"],
            sku_code="SKU-1",
            pricing_type="per_meter",
        )

        assert result.success is True
        assert result.data["product_id"] == "p-1"

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["tenant_id"] == admin_tool_context.tenant_id
        assert call_kwargs["user_id"] == admin_tool_context.user_id
        json_data = call_kwargs["json_data"]
        # 字段必须为 camelCase，且 stock 强制 int
        assert json_data["categoryId"] == "cat-1"
        assert json_data["basePrice"] == 100.5
        assert json_data["stock"] == 99
        assert isinstance(json_data["stock"], int)
        assert json_data["processingItemIds"] == ["pi-1"]
        assert json_data["processingItemConfigs"] == [{"processingItemId": "pi-1", "customPrice": 10}]
        assert json_data["sellingMethods"] == ["bulk_cut"]
        assert json_data["doorWidths"] == ["2.8米"]
        assert json_data["skuCode"] == "SKU-1"
        assert json_data["pricingType"] == "per_meter"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": False, "error": {"message": "商品名重复"}, "suggestion": "换一个名字",
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert result.error == "商品名重复"
        assert "创建商品失败" in result.message
        assert result.suggestion == "换一个名字"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_warnings_appended(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "p-1"},
            "warnings": ["skuCode 已存在，系统自动重新生成"],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is True
        assert "⚠️" in result.message
        assert "skuCode 已存在" in result.message


class TestProductUpdate:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_missing_product_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", name="新名字")
        assert result.success is False
        assert "缺少商品 ID" in result.error
        mock_client.patch.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_no_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", product_id="p-1")
        assert result.success is False
        assert "没有需要更新的字段" in result.error
        mock_client.patch.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.patch = AsyncMock(return_value={"success": False, "error": {"message": "商品不存在"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="update", product_id="p-1", name="新名字")
        assert result.success is False
        assert result.error == "商品不存在"
        assert "更新商品失败" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_only_non_none_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="update",
            product_id="p-1",
            name="新名字",
            price=88.0,
            stock_quantity=5,
        )

        assert result.success is True
        assert result.data["updated_fields"] == ["name", "basePrice", "stock"]

        call_kwargs = mock_client.patch.call_args[1]
        json_data = call_kwargs["json_data"]
        assert json_data == {"name": "新名字", "basePrice": 88.0, "stock": 5}
        assert "categoryId" not in json_data
        assert "description" not in json_data


class TestProductToggleStatus:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_missing_product_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_status", status="on_sale")
        assert result.success is False
        assert "缺少商品 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="sold_out")
        assert result.success is False
        assert "无效的商品状态" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_on_sale(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {"status": "on_sale"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="on_sale")
        assert result.success is True
        assert "已上架" in result.message
        assert mock_client.put.call_args[0][0] == "/api/admin/products/p-1/status"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_off_sale(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True, "data": {"status": "off_sale"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="off_sale")
        assert result.success is True
        assert "已下架" in result.message

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_toggle_failure_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": False, "error": {"message": "商品不存在"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", product_id="p-1", status="on_sale")
        assert result.success is False
        assert result.error == "商品不存在"
        assert "商品状态更新失败" in result.message


class TestProductException:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_execute_exception_generic(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create", name="窗帘")
        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert "boom" not in (result.message or "")
