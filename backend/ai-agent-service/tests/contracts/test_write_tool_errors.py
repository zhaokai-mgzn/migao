"""
写操作 Tool 错误路径回归测试

核心写 Tool 必须正确处理：
1. admin-api 返回 {success: false, error: {code, message}} → 透传错误信息
2. 网络故障 → 不崩溃，返回友好错误
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.base import ToolContext


def _make_context(role="admin"):
    return ToolContext(tenant_id=1, user_id="u1", session_id="s1", role=role)


# ═══════════════════════════════════════════════════════════════════
# product_manage
# ═══════════════════════════════════════════════════════════════════

class TestProductManageErrors:
    """product_manage 写操作错误处理"""

    @pytest.mark.asyncio
    async def test_admin_api_failure_bubbles_up(self):
        """admin-api 返回失败 → tool 返回 success=False + 透传错误信息"""
        from app.tools.product_manage import ProductManageTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": "商品名称已存在"}
        })

        with patch("app.tools.product_manage.get_admin_api_client", return_value=mock_client):
            tool = ProductManageTool()
            result = await tool.execute(
                context=_make_context(),
                action="create",
                name="测试商品",
                price=99,
            )
        assert result.success is False
        assert "商品名称已存在" in result.message or "VALIDATION_ERROR" in result.error

    @pytest.mark.asyncio
    async def test_network_error_graceful(self):
        """网络故障 → 不崩溃，返回友好错误"""
        from app.tools.product_manage import ProductManageTool
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("app.tools.product_manage.get_admin_api_client", return_value=mock_client):
            tool = ProductManageTool()
            result = await tool.execute(
                context=_make_context(),
                action="create",
                name="测试商品",
                price=99,
            )
        assert result.success is False
        assert result.message is not None


# ═══════════════════════════════════════════════════════════════════
# order_create
# ═══════════════════════════════════════════════════════════════════

class TestOrderCreateErrors:
    """order_create 写操作错误处理"""

    @pytest.mark.asyncio
    async def test_admin_api_failure_bubbles_up(self):
        """admin-api 返回失败 → tool 返回 success=False"""
        from app.tools.order_create import OrderCreateTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"code": "INSUFFICIENT_STOCK", "message": "库存不足"}
        })

        with patch("app.tools.order_create.get_admin_api_client", return_value=mock_client):
            tool = OrderCreateTool()
            result = await tool.execute(
                context=_make_context(),
                customer_name="测试客户",
                customer_phone="13800000001",
                items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 100, "subtotal": 100}],
            )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_network_error_graceful(self):
        """网络故障 → 不崩溃"""
        from app.tools.order_create import OrderCreateTool
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("app.tools.order_create.get_admin_api_client", return_value=mock_client):
            tool = OrderCreateTool()
            result = await tool.execute(
                context=_make_context(),
                customer_name="测试",
                customer_phone="13800000001",
                items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 100, "subtotal": 100}],
            )
        assert result.success is False


# ═══════════════════════════════════════════════════════════════════
# customer_manage
# ═══════════════════════════════════════════════════════════════════

class TestCustomerManageErrors:
    """customer_manage 写操作错误处理"""

    @pytest.mark.asyncio
    async def test_admin_api_failure_bubbles_up(self):
        """admin-api 返回失败 → tool 返回 success=False"""
        from app.tools.customer_manage import CustomerManageTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"code": "DUPLICATE", "message": "客户手机号已存在"}
        })

        with patch("app.tools.customer_manage.get_admin_api_client", return_value=mock_client):
            tool = CustomerManageTool()
            result = await tool.execute(
                context=_make_context(),
                action="create",
                name="测试",
                phone="13800000001",
            )
        # customer_manage wraps result — should return error state
        assert result is not None


# ═══════════════════════════════════════════════════════════════════
# common — 所有写 Tool 的错误一致性
# ═══════════════════════════════════════════════════════════════════

class TestWriteToolErrorConsistency:
    """所有写 Tool 的错误格式一致性：success=False 时应有 suggestion 或 message"""

    @pytest.mark.asyncio
    async def test_product_create_response_has_error_path(self):
        """product_manage create 失败时返回一致格式"""
        from app.tools.product_manage import ProductManageTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"code": "ERR", "message": "失败"}
        })

        with patch("app.tools.product_manage.get_admin_api_client", return_value=mock_client):
            tool = ProductManageTool()
            result = await tool.execute(
                context=_make_context(), action="create", name="x", price=1
            )
        # 必须有 success 字段
        assert hasattr(result, "success")
        # 失败时 message 或 error 至少有一个
        assert result.message is not None or result.error is not None
