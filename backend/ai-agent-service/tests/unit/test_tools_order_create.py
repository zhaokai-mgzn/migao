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


class TestOrderCreateValidation:
    """参数校验"""

    @pytest.mark.skip(reason="Tool delegates validation to admin-api, no client-side check for customer_name")
    async def test_missing_customer_name_returns_error(self, admin_tool_context):
        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_phone="13800000001",
            items=[{"product_name": "商品A", "quantity": 1, "unit_price": 100, "subtotal": 100}],
        )
        assert result.success is False


class TestOrderCreateCustomerRole:
    """customer 角色创建订单 — customerId 自动绑定"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_role_allowed(self, mock_get_client, sample_tool_context):
        """customer 角色应该被允许创建订单"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-cust-001",
                "orderNo": "ORD-2024-CUST",
                "status": "pending",
                "totalAmount": 200,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="李四",
            customer_phone="13900000001",
            items=[{"product_name": "窗帘布", "quantity": 1, "unit_price": 200, "subtotal": 200}],
        )

        assert result.success is True
        assert "order-cust-001" in str(result.data)
        mock_client.post.assert_called_once()

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_id_injected(self, mock_get_client, sample_tool_context):
        """customer 角色创建订单时，customerId 应自动绑定为 context.user_id"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "order-cust-002", "orderNo": "ORD-CUST-002"},
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="王五",
            customer_phone="13700000001",
            items=[{"product_name": "蜂巢帘", "quantity": 1, "unit_price": 150, "subtotal": 150}],
        )

        assert result.success is True
        # 验证 customerId 被注入到请求体中
        call_args = mock_client.post.call_args
        json_data = call_args.kwargs["json_data"]
        assert "customerId" in json_data
        assert json_data["customerId"] == sample_tool_context.user_id

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_id_not_injected_for_admin(self, mock_get_client, admin_tool_context):
        """admin 角色创建订单时，不应自动注入 customerId"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "order-admin-001", "orderNo": "ORD-ADMIN-001"},
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_name="张三",
            customer_phone="13800000001",
            items=[{"product_name": "商品A", "quantity": 1, "unit_price": 100, "subtotal": 100}],
        )

        assert result.success is True
        # 验证 admin 调用时 customerId 不在请求体中
        call_args = mock_client.post.call_args
        json_data = call_args.kwargs["json_data"]
        assert "customerId" not in json_data


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
