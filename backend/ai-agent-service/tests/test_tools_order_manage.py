"""OrderManageTool 单元测试 — Agent BFF PATCH 端点"""
# case_ids: OR-007, OR-010
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.order_manage import OrderManageTool


@pytest.fixture
def tool():
    return OrderManageTool()


class TestOrderUpdateStatus:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_update_status(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_status",
            order_id="order-1", status="confirmed")

        assert result.success is True
        # 验证调用了 PATCH Agent 端点
        call_args = mock_client.patch.call_args
        assert "agent/orders/order-1" in call_args[0][0]


class TestOrderUpdateLogistics:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_update_logistics(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_logistics",
            order_id="order-1", logistics_company="顺丰", tracking_number="SF123")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["logisticsCompany"] == "顺丰"
        assert json_data["trackingNumber"] == "SF123"


class TestOrderCancel:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_cancel(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="cancel",
            order_id="ORD-20250718001", cancel_reason="客户要求")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["action"] == "cancel"
        assert json_data["cancelReason"] == "客户要求"


class TestOrderRefund:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_refund(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="refund",
            order_id="order-1", refund_amount=299.0, refund_reason="质量问题")

        assert result.success is True
        call_args = mock_client.patch.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data["action"] == "refund"
        assert json_data["refundAmount"] == 299.0
        assert json_data["refundReason"] == "质量问题"


class TestOrderInvalid:
    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, action="invalid_op", order_id="x")
        assert result.success is False
        assert "不支持" in result.message


class TestOrderPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context, action="cancel", order_id="x")
        assert result.success is False
        assert "权限" in result.error


class TestOrderManageValidation:
    """各 action 必填参数校验"""

    async def test_update_status_missing_status(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_status", order_id="o1")
        assert result.success is False
        assert "缺少状态参数" in result.error

    async def test_update_logistics_missing_company(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_logistics", order_id="o1", tracking_number="SF1")
        assert result.success is False
        assert "缺少快递公司" in result.error

    async def test_update_logistics_missing_tracking(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_logistics", order_id="o1", logistics_company="顺丰")
        assert result.success is False
        assert "缺少运单号" in result.error

    async def test_missing_order_id(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="")
        assert result.success is False
        assert "缺少订单 ID" in result.error


class TestOrderManageConfirmPayment:
    """确认支付 confirm_payment"""

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_confirm_payment(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="confirm_payment", order_id="o1")
        assert result.success is True
        assert "订单已确认支付" in result.message


class TestOrderManageFailure:
    """API 失败与异常路径"""

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_api_failure(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={"success": False, "error": {"message": "订单不存在"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="bad-id")
        assert result.success is False
        assert "订单不存在" in result.error

    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_execute_exception(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="cancel", order_id="o1")
        assert result.success is False
        assert result.error == "tool_execution_failed"
