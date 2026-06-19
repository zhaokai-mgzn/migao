"""
Tests for aftersale_query tool — C-end customer queries own aftersale tickets.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.tools.base import ToolContext, ToolResult
from app.tools.aftersale_query import AftersaleQueryTool


class TestAftersaleQuery:
    """Customer aftersale query tool tests."""

    @pytest.fixture
    def tool(self):
        return AftersaleQueryTool()

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

    # ── list action ──

    @pytest.mark.asyncio
    async def test_list_injects_customer_id(self, tool, customer_context):
        """Verify customerId is injected in query params for list action."""
        mock_response = {
            "success": True,
            "data": {
                "items": [
                    {"id": "t1", "ticketType": "refund", "status": "pending"}
                ],
                "total": 1,
            },
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, action="list")

        assert result.success is True
        assert result.data["total"] == 1

        # Verify customerId was injected in the params
        call_args = mock_call.call_args
        assert call_args is not None
        # The method signature is (method, path, params, json_data, context)
        params = call_args.kwargs.get("params", {})
        assert params.get("customerId") == "cust_123"

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, tool, customer_context):
        """Verify status filter is passed through."""
        mock_response = {
            "success": True,
            "data": {"items": [], "total": 0},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, action="list", status="pending")

        assert result.success is True
        params = mock_call.call_args.kwargs.get("params", {})
        assert params.get("status") == "pending"
        assert params.get("customerId") == "cust_123"

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, tool, customer_context):
        """Verify pagination params are passed correctly."""
        mock_response = {
            "success": True,
            "data": {"items": [], "total": 0},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, action="list", page=2, size=5)

        assert result.success is True
        params = mock_call.call_args.kwargs.get("params", {})
        assert params.get("page") == 2
        assert params.get("size") == 5

    # ── detail action ──

    @pytest.mark.asyncio
    async def test_detail_with_valid_ticket_id(self, tool, customer_context):
        """Verify detail action fetches specific ticket."""
        mock_response = {
            "success": True,
            "data": {"id": "ticket_001", "ticketType": "refund", "status": "processing"},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)) as mock_call:
            result = await tool.execute(customer_context, action="detail", ticket_id="ticket_001")

        assert result.success is True
        assert result.data["id"] == "ticket_001"

        # Verify the API path includes the ticket_id
        call_args = mock_call.call_args
        path = call_args.kwargs.get("path", "")
        assert "ticket_001" in path

    @pytest.mark.asyncio
    async def test_detail_missing_ticket_id_returns_error(self, tool, customer_context):
        """Verify detail action without ticket_id returns error."""
        result = await tool.execute(customer_context, action="detail")

        assert result.success is False
        assert "ticket_id" in result.error.lower() or "工单" in result.message

    # ── permission ──

    @pytest.mark.asyncio
    async def test_permission_denied_for_admin(self, tool, admin_context):
        """Verify admin role is denied (aftersale_query is customer-only)."""
        result = await tool.execute(admin_context, action="list")

        assert result.success is False
        assert "权限" in result.message or "permission" in result.error.lower()

    # ── invalid action ──

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, tool, customer_context):
        """Verify invalid action returns error."""
        result = await tool.execute(customer_context, action="delete")

        assert result.success is False
        assert "无效" in result.message or "不支持" in result.message

    # ── API error propagation ──

    @pytest.mark.asyncio
    async def test_api_error_propagated(self, tool, customer_context):
        """Verify API error response is returned as failure."""
        mock_response = {
            "success": False,
            "error": {"message": "工单不存在"},
        }

        with patch.object(tool, "_call_admin_api", new=AsyncMock(return_value=mock_response)):
            result = await tool.execute(customer_context, action="detail", ticket_id="nonexistent")

        assert result.success is False
        assert "工单不存在" in result.message
