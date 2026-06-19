"""
Tests for aftersale_create tool — C-end customer creates aftersale tickets.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext, ToolResult
from app.tools.aftersale_create import AftersaleCreateTool


class TestAftersaleCreate:
    """Customer aftersale create tool tests."""

    @pytest.fixture
    def tool(self):
        return AftersaleCreateTool()

    @pytest.fixture
    def customer_context(self):
        return ToolContext(
            tenant_id=1,
            user_id="cust_123",
            session_id="sess_abc",
            role="customer",
        )

    @pytest.fixture
    def admin_context(self):
        return ToolContext(
            tenant_id=1,
            user_id="admin_456",
            session_id="sess_def",
            role="admin",
        )

    @pytest.fixture
    def valid_create_params(self):
        return {
            "order_id": "ORD-2024-001",
            "ticket_type": "refund",
            "reason": "尺寸不符，要求退款",
        }

    # ── successful create ──

    @pytest.mark.asyncio
    async def test_create_injects_customer_id(self, tool, customer_context, valid_create_params):
        """Verify customerId is injected in POST payload."""
        mock_response = {
            "success": True,
            "data": {"id": "ticket_new_001", "ticketType": "refund", "status": "pending"},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, **valid_create_params)

        assert result.success is True
        assert result.data["id"] == "ticket_new_001"

        # Verify customerId was injected in json_data
        call_args = mock_call.call_args
        json_data = call_args.kwargs.get("json_data", {})
        assert json_data.get("customerId") == "cust_123"
        assert json_data.get("orderId") == "ORD-2024-001"
        assert json_data.get("ticketType") == "refund"

    @pytest.mark.asyncio
    async def test_create_with_description(self, tool, customer_context, valid_create_params):
        """Verify optional description is passed through."""
        mock_response = {
            "success": True,
            "data": {"id": "ticket_new_002"},
        }

        params = {**valid_create_params, "description": "窗帘颜色与样品不符"}

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, **params)

        assert result.success is True
        json_data = mock_call.call_args.kwargs.get("json_data", {})
        assert json_data.get("description") == "窗帘颜色与样品不符"

    # ── validation ──

    @pytest.mark.asyncio
    async def test_missing_order_id_returns_error(self, tool, customer_context):
        """Verify missing order_id rejects request."""
        result = await tool.execute(
            customer_context,
            ticket_type="refund",
            reason="测试原因",
        )

        assert result.success is False
        assert "订单" in result.message or "order" in result.message.lower()

    @pytest.mark.asyncio
    async def test_missing_ticket_type_returns_error(self, tool, customer_context):
        """Verify missing ticket_type rejects request."""
        result = await tool.execute(
            customer_context,
            order_id="ORD-001",
            reason="测试原因",
        )

        assert result.success is False
        assert "类型" in result.message or "type" in result.message.lower()

    @pytest.mark.asyncio
    async def test_missing_reason_returns_error(self, tool, customer_context):
        """Verify missing reason rejects request."""
        result = await tool.execute(
            customer_context,
            order_id="ORD-001",
            ticket_type="refund",
        )

        assert result.success is False
        assert "原因" in result.message or "reason" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invalid_ticket_type_rejected(self, tool, customer_context):
        """Verify invalid ticket_type value is rejected."""
        result = await tool.execute(
            customer_context,
            order_id="ORD-001",
            ticket_type="invalid_type",
            reason="测试原因",
        )

        assert result.success is False
        assert "类型" in result.message or "type" in result.error.lower()

    # ── permission ──

    @pytest.mark.asyncio
    async def test_permission_denied_for_admin(self, tool, admin_context, valid_create_params):
        """Verify admin role is denied (aftersale_create is customer-only)."""
        result = await tool.execute(admin_context, **valid_create_params)

        assert result.success is False
        assert "权限" in result.message or "permission" in result.error.lower()

    # ── tool metadata ──

    def test_tool_metadata(self, tool):
        """Verify tool metadata is set correctly."""
        assert tool.name == "aftersale_create"
        assert "customer" in tool.allowed_roles
        assert "admin" not in tool.allowed_roles
        assert tool.read_only is False
        assert tool.destructive is False
        assert tool.idempotent is False

    # ── API error propagation ──

    @pytest.mark.asyncio
    async def test_api_error_propagated(self, tool, customer_context, valid_create_params):
        """Verify API error response is returned as failure."""
        mock_response = {
            "success": False,
            "error": {"message": "订单不存在"},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)):
            result = await tool.execute(customer_context, **valid_create_params)

        assert result.success is False
        assert "订单不存在" in result.message
