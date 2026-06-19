"""
测试 order_create 客户角色权限更新

业务真值 #1: 客户可以创建订单→必须通过手机号验证身份，只能创建自己订单
"""
import pytest
from unittest.mock import patch, AsyncMock
from app.tools.order_create import OrderCreateTool
from app.tools.base import ToolContext


class TestCustomerOrderCreatePermission:
    """客户角色权限测试"""

    def test_customer_role_allowed(self):
        """customer 角色在 allowed_roles 中"""
        tool = OrderCreateTool()
        assert "customer" in tool.allowed_roles, (
            f"允许的角色应包含 'customer'，当前: {tool.allowed_roles}"
        )

    async def test_customer_can_create_order(self, sample_tool_context):
        """customer角色 check_permission 返回 True"""
        tool = OrderCreateTool()
        assert tool.check_permission(sample_tool_context) is True

    def test_guest_still_denied(self):
        """guest角色仍被拒绝"""
        tool = OrderCreateTool()
        guest_ctx = ToolContext(
            tenant_id=1, user_id="guest_001",
            session_id="sess_test", role="guest"
        )
        assert tool.check_permission(guest_ctx) is False

    def test_admin_still_allowed(self):
        """admin角色仍可使用"""
        tool = OrderCreateTool()
        admin_ctx = ToolContext(
            tenant_id=1, user_id="admin_001",
            session_id="sess_test", role="admin"
        )
        assert tool.check_permission(admin_ctx) is True


class TestCustomerOrderCreateSuccess:
    """客户成功创建订单"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_creates_own_order(self, mock_get_client, sample_tool_context):
        """客户用自己的信息创建订单"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-cust-001",
                "orderNo": "ORD-C-2024-001",
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is True
        assert "order-cust-001" in str(result.data)
        mock_client.post.assert_called_once()

        # 验证传入了 customer 的 user_id / tenant_id
        call_args = mock_client.post.call_args
        assert call_args[1]["tenant_id"] == sample_tool_context.tenant_id
        assert call_args[1]["user_id"] == sample_tool_context.user_id


class TestCustomerOrderCreateValidation:
    """客户创建订单参数校验"""

    async def test_customer_create_missing_items(self, sample_tool_context):
        """客户创建订单缺items时返回错误+suggestion"""
        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试",
            customer_phone="13800138000",
            items=[],
        )
        assert result.success is False
        # 缺参数时应有suggestion
        assert result.suggestion is not None
