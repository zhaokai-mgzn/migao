"""AfterSalesManageTool 单元测试 — 售后工单查询/创建/状态流转。

覆盖 list/detail/create/update_status 的正常路径与参数校验，
以及 destructive 工具只读 action 的确认豁免（DF-008）。
"""
# case_ids: DF-008, AS-001, AS-002, AS-004
import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills.base_skill import _requires_confirmation
from app.tools.after_sales_manage import AfterSalesManageTool, VALID_ACTIONS


@pytest.fixture
def tool():
    return AfterSalesManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    return client


class TestAfterSalesReadOnlyConfirmation:
    """destructive 工具只读 action 的确认豁免（DF-008）"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查售后工单") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "ticket_id": "x"}, "查工单详情") is False

    def test_write_actions_still_require_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "create"}, "创建工单") is True
        assert _requires_confirmation(tool, {"action": "update_status"}, "关闭工单") is True


class TestAfterSalesPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="close")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestAfterSalesList:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_list_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "t1", "status": "pending"}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            page="2",
            size="5",
            status="pending",
            ticket_type="refund",
            keyword="尺寸",
        )

        assert result.success is True
        assert result.data["items"][0]["id"] == "t1"
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["status"] == "pending"
        assert params["ticketType"] == "refund"
        assert params["keyword"] == "尺寸"

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_list_failure(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "服务不可用"


class TestAfterSalesDetail:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少工单 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        payload = {"id": "t1", "ticketNo": "AS-1", "status": "pending"}
        mock_client.get = AsyncMock(return_value={"success": True, "data": payload})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", ticket_id="t1")
        assert result.success is True
        assert result.data == payload
        assert mock_client.get.call_args[0][0] == "/api/admin/after-sales/t1"


class TestAfterSalesCreate:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_create_missing_required_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create", ticket_type="refund", reason="尺寸不符")
        assert r1.success is False and "缺少订单 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create", order_id="o1", reason="尺寸不符")
        assert r2.success is False and "缺少工单类型" in r2.error
        r3 = await tool.execute(context=admin_tool_context, action="create", order_id="o1", ticket_type="refund")
        assert r3.success is False and "缺少原因说明" in r3.error
        mock_client.post.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_create_invalid_ticket_type(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", order_id="o1", ticket_type="destroy", reason="x")
        assert result.success is False
        assert "无效的工单类型" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_create_description_fallback_to_reason(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "t-new", "ticketNo": "AS-1"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", order_id="o1", ticket_type="refund", reason="尺寸不符")
        assert result.success is True
        assert result.data["id"] == "t-new"
        assert mock_client.post.call_args[0][0] == "/api/admin/agent/after-sales"
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["orderId"] == "o1"
        assert json_data["ticketType"] == "refund"
        assert json_data["description"] == "尺寸不符"
        assert json_data["source"] == "agent"

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_create_kwargs_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "t-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            order_id="o1",
            ticket_type="refund",
            reason="尺寸不符",
            images=["https://img/1.png"],
            priority="urgent",
            refund_amount=50.0,
        )
        assert result.success is True
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["images"] == ["https://img/1.png"]
        assert json_data["priority"] == "urgent"
        assert json_data["refundAmount"] == 50.0


class TestAfterSalesUpdateStatus:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_update_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="update_status", status="resolved")
        assert r1.success is False and "缺少工单 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="update_status", ticket_id="t1")
        assert r2.success is False and "缺少状态参数" in r2.error
        mock_client.put.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_update_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="update_status", ticket_id="t1", status="archived")
        assert result.success is False
        assert "无效的工单状态" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_update_success_with_reason(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_status", ticket_id="t1", status="resolved", reason="已处理")
        assert result.success is True
        assert result.data == {"ticket_id": "t1", "status": "resolved"}
        assert mock_client.put.call_args[0][0] == "/api/admin/after-sales/t1/status"
        assert mock_client.put.call_args[1]["json_data"] == {"status": "resolved", "reason": "已处理"}
