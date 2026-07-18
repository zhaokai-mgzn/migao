"""
测试 app.tools.order_create — 创建订单工具
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.order_create import OrderCreateTool
from app.tools.base import ToolResult


class TestOrderCreatePermission:
    """权限校验"""

    async def test_customer_role_denied(self, unauthorized_tool_context):
        tool = OrderCreateTool()
        result = await tool.execute(
            context=unauthorized_tool_context,
            customer_name="测试",
            customer_phone="13800000000",
            items=[{"product_name": "商品A", "quantity": 1, "unit_price": 100}],
        )
        assert result.success is False
        assert "权限" in result.message or "权限" in (result.error or "")


class TestOrderCreateSuccess:
    """成功创建订单"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_create_order_success(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-new",
                "orderNo": "ORD-2024-001",
                "status": "pending",
                "totalAmount": 100,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_name="张三",
            customer_phone="13800000001",
            items=[{"product_name": "蜂巢帘", "quantity": 2, "unit_price": 50, "subtotal": 100}],
        )

        assert result.success is True
        assert "order-new" in str(result.data)
        mock_client.post.assert_called_once()



class TestOrderCreateError:
    """错误处理"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_admin_api_returns_failure(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": "商品不存在"},
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_name="张三",
            customer_phone="13800000001",
            items=[{"product_name": "不存在商品", "quantity": 1, "unit_price": 100}],
        )

        assert result.success is False

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_network_error(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_name="张三",
            customer_phone="13800000001",
            items=[{"product_name": "商品A", "quantity": 1, "unit_price": 100}],
        )

        assert result.success is False
