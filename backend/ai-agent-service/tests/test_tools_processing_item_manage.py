"""ProcessingItemManageTool 单元测试 — 加工项/加工分类 CRUD + 价格计算。"""
# case_ids: PP-002, PP-003, PP-004, PP-006
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.processing_item_manage import ProcessingItemManageTool


@pytest.fixture
def tool():
    return ProcessingItemManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def agent_tool_context():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess", role="agent")


class TestProcessingPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_denied(self, tool, agent_tool_context):
        result = await tool.execute(context=agent_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="remove_item")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestProcessingItemCreate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            category_id="c1", price=5.0, pricing_method="per_meter")
        assert r1.success is False and "缺少加工项名称" in r1.error
        r2 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", price=5.0, pricing_method="per_meter")
        assert r2.success is False and "缺少分类 ID" in r2.error
        r3 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", category_id="c1", pricing_method="per_meter")
        assert r3.success is False and "缺少价格" in r3.error
        # issue #3543：pricing_method 是 admin-api @NotBlank 必填项，缺失必须本地拦下
        r4 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", category_id="c1", price=5.0)
        assert r4.success is False and "缺少计价方式" in r4.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        """PP-006 / issue #3543：请求体必须含 pricingMethod + unitPrice，且显式映射 price→unitPrice。

        admin-api `ProcessingItemCreateRequest` 契约（Java DTO 为准）：
        `@NotBlank pricingMethod` + `@NotNull BigDecimal unitPrice` + `@NotBlank categoryId`。
        旧实现只 POST `{name, categoryId, price}` → Bean Validation 422「参数校验失败」
        → B 端「新增加工项」完全不可用（acceptance/2026-09-14/replay-triage §2.3）。
        """
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="测试加工",
            price=8.0, category_id="c1", pricing_method="per_meter")
        assert result.success is True
        assert result.data["id"] == "pi-new"
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items"
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["categoryId"] == "c1"
        assert json_data["name"] == "测试加工"
        assert json_data["pricingMethod"] == "per_meter"
        # 值正确：单价以 unitPrice（非 price）落请求体——显式映射，禁止依赖同名
        assert json_data["unitPrice"] == 8.0
        assert "price" not in json_data

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_rejects_unsupported_pricing_method(self, mock_get_client, tool, admin_tool_context, mock_client):
        """计价方式 canonical 枚举（issue #3543 / #3005）：per_piece（按个）非法必须拒绝并说明。"""
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="测试加工",
            category_id="c1", price=8.0, pricing_method="per_piece")
        assert result.success is False
        assert "计价方式" in result.error
        # 「并说明」：错误信息须给出可选枚举，且点明 per_piece 不支持
        assert "per_meter" in result.message and "per_area" in result.message
        assert "per_piece" in result.message
        mock_client.post.assert_not_called()

    def test_pricing_method_schema_declares_canonical_enum(self, tool):
        """schema 必须声明 pricing_method（与 description 铁律所列参数一致），枚举无 per_piece。"""
        props = tool.parameters["properties"]
        assert "pricing_method" in props, "description 要求 LLM 传 pricing_method，schema 必须声明"
        assert set(props["pricing_method"]["enum"]) == {"per_meter", "per_set", "fixed", "per_area"}
        assert "per_piece" not in props["pricing_method"]["enum"]

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_without_density_field(self, mock_get_client, tool, admin_tool_context, mock_client):
        """PP-006（issue #3005 回滚）：create_item 不再支持 per_meter_quantity 透传"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="打孔", price=8.0,
            category_id="c1", pricing_method="per_meter")
        assert result.success is True
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["unitPrice"] == 8.0
        assert "perMeterQuantity" not in json_data


class TestProcessingItemUpdate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", name="打孔")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", item_id="pi-1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1", name="打孔(更新)", price=6.0)
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1"
        json_data = mock_client.put.call_args[1]["json_data"]
        assert json_data["price"] == 6.0
        assert "perMeterQuantity" not in json_data


class TestProcessingItemDelete:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_item")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_item", item_id="pi-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-items/pi-1"


class TestProcessingToggleStatus:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_item_status", status="active")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="archived")
        assert result.success is False
        assert "无效的状态值" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_active(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="active")
        assert result.success is True
        assert "已启用" in result.message
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1/status"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_inactive(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="inactive")
        assert result.success is True
        assert "已停用" in result.message


class TestProcessingCategories:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_list_categories(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "pc-1"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_categories")
        assert result.success is True
        assert result.data["categories"] == [{"id": "pc-1"}]
        assert mock_client.get.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create_category")
        assert result.success is False
        assert "缺少分类名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pc-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create_category", name="高级加工")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="update_category", name="新名")
        assert r1.success is False and "缺少分类 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="update_category", category_id="pc-1")
        assert r2.success is False and "缺少分类名称" in r2.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_category", category_id="pc-1", name="新名")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-categories/pc-1"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_category")
        assert result.success is False
        assert "缺少分类 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_category", category_id="pc-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-categories/pc-1"


class TestProcessingCalculatePrice:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="calculate_price", quantity=2)
        assert r1.success is False and "缺少加工项 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="calculate_price", processing_item_id="pi-1")
        assert r2.success is False and "缺少数量" in r2.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_priority(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": True, "data": {"totalPrice": 100, "total_price": 90},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "100" in result.message
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items/calculate"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_fallback(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"total_price": 90}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "90" in result.message
