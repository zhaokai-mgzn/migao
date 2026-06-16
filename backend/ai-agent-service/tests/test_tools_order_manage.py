"""OrderManageTool 单元测试 — 状态/物流/取消/收款/退款"""
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
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_status",
            order_id="order-1", status="confirmed")

        assert result.success is True


class TestOrderUpdateLogistics:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_update_logistics(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_logistics",
            order_id="order-1", logistics_company="顺丰", tracking_number="SF123")

        assert result.success is True


class TestOrderCancel:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_cancel(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="cancel",
            order_id="order-1", cancel_reason="客户要求")

        assert result.success is True


class TestOrderRefund:
    @patch("app.tools.order_manage.get_admin_api_client")
    async def test_refund(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="refund",
            order_id="order-1", refund_amount=299.0, refund_reason="质量问题")

        assert result.success is True


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
