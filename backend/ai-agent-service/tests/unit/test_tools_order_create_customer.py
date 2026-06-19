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


# ============================================================
# GAP-1: SMS 验证码 — 客户创建订单前必须验证手机号
# 业务真值: 客户创建订单必须通过手机号验证码验证身份→只能创建自己订单
# 当前状态: FAIL — 尚未实现 SMS 验证
# ============================================================

class TestCustomerOrderCreateSmsVerification:
    """Gap-1: 客户创建订单 → 必须通过手机号验证"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_create_order_without_sms_verify_fails(self, mock_get_client, sample_tool_context):
        """客户未通过SMS验证 → 创建订单应失败"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        # 当前预期: 缺少 sms_code 参数或未验证 → 失败
        assert result.success is False, (
            f"客户创建订单必须提供短信验证码，当前未拦截: {result.message}"
        )
        assert result.suggestion is not None, "失败时必须提供修复建议"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_create_order_with_invalid_sms_code_fails(self, mock_get_client, sample_tool_context):
        """客户提供错误的SMS验证码 → 创建订单应失败"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            sms_code="000000",  # 无效验证码
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is False, (
            f"错误验证码应被拒绝: {result.message}"
        )
        assert "验证码" in (result.error or "") or "验证码" in (result.message or ""), (
            f"错误信息应包含'验证码'关键词: error={result.error}, message={result.message}"
        )

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_create_order_with_valid_sms_code_succeeds(self, mock_get_client, sample_tool_context):
        """客户提供正确的SMS验证码 → 创建订单成功"""
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

        # Mock SMS verification as valid
        with patch.object(OrderCreateTool, "_verify_sms_code", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True

            tool = OrderCreateTool()
            result = await tool.execute(
                context=sample_tool_context,
                customer_name="测试客户",
                customer_phone="13800138000",
                sms_code="123456",  # 有效验证码
                items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
            )

            mock_verify.assert_called_once_with(
                phone="13800138000",
                code="123456",
                tenant_id=sample_tool_context.tenant_id,
            )
            assert result.success is True, f"验证码验证通过后应创建成功: {result.error}"
            assert "order-cust-001" in str(result.data)

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_admin_creates_order_without_sms_verify_succeeds(self, mock_get_client, admin_tool_context):
        """admin角色创建订单 → 不需要SMS验证（管理员帮客户下单）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-admin-001",
                "orderNo": "ORD-A-2024-001",
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=admin_tool_context,
            customer_name="客户A",
            customer_phone="13800138001",
            items=[{"product_name": "蜂巢帘", "quantity": 2, "unit_price": 50, "subtotal": 100}],
        )

        assert result.success is True, (
            f"管理员创建订单无需SMS验证，当前异常: {result.error}"
        )


class TestCustomerOrderCreateSuccess:
    """客户成功创建订单（需要SMS验证码）"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_creates_own_order_with_sms(self, mock_get_client, sample_tool_context):
        """客户提供验证码后创建订单"""
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

        with patch.object(OrderCreateTool, "_verify_sms_code", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True

            tool = OrderCreateTool()
            result = await tool.execute(
                context=sample_tool_context,
                customer_name="测试客户",
                customer_phone="13800138000",
                sms_code="123456",
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
            sms_code="123456",
            items=[],
        )
        assert result.success is False
        # 缺参数时应有suggestion
        assert result.suggestion is not None
