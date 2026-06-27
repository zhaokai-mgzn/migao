"""
测试 order_create 客户角色权限更新 + SMS verify API 集成 (#733)

业务真值 #1: 客户可以创建订单→必须通过 admin-api SMS verify API 验证身份
业务真值 #2: SMS verify 失败 → 不创建订单 + 返回 error + suggestion
业务真值 #3: SMS verify 成功 → 用 API 返回的 verifiedPhone 创建订单
"""
import pytest
from unittest.mock import patch, AsyncMock, ANY
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
# GAP-1: SMS 验证码 — 客户创建订单前必须通过 admin-api SMS verify API 验证
# 业务真值: 客户创建订单必须通过手机号验证码验证身份→只能创建自己订单
# #733: 调用 admin-api POST /api/auth/sms/verify（非本地 Redis）
# ============================================================

def _make_sms_verify_response(success: bool, verified_phone: str = None, error_msg: str = None):
    """构建 admin-api SMS verify API 响应"""
    if success:
        return {"success": True, "data": {"verifiedPhone": verified_phone or "13800138000"}}
    return {"success": False, "error": {"message": error_msg or "验证码错误或已过期"}}


def _make_order_create_response(success: bool, order_id: str = "order-001"):
    """构建 admin-api 订单创建 API 响应"""
    if success:
        return {
            "success": True,
            "data": {"id": order_id, "orderNo": f"ORD-{order_id}", "status": "pending"},
        }
    return {"success": False, "error": {"message": "创建失败"}}


class TestCustomerOrderCreateSmsVerification:
    """Gap-1 + #733: 客户创建订单 → 必须通过 admin-api SMS verify API"""

    async def test_customer_create_order_without_sms_verify_fails(self, sample_tool_context):
        """客户未提供 sms_code → 创建订单应失败"""
        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is False, (
            f"客户创建订单必须提供短信验证码，当前未拦截: {result.message}"
        )
        assert result.suggestion is not None, "失败时必须提供修复建议"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_create_order_with_invalid_sms_code_fails(self, mock_get_client, sample_tool_context):
        """客户提供错误的SMS验证码 → SMS verify API 返回失败 → 不创建订单"""
        # Mock: SMS verify API 返回失败
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_sms_verify_response(success=False))
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
        assert result.suggestion is not None, "失败时必须提供修复建议"

        # 确认调用了 SMS verify API
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/api/auth/sms/verify" in str(call_args)

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_create_order_with_valid_sms_code_succeeds(self, mock_get_client, sample_tool_context):
        """客户提供正确的SMS验证码 → SMS verify API 返回成功 → 用 verifiedPhone 创建订单"""
        mock_client = AsyncMock()

        # Mock: post 方法根据 path 返回不同响应
        async def mock_post(path, **kwargs):
            if "/api/auth/sms/verify" in str(path):
                return _make_sms_verify_response(success=True, verified_phone="13800138000")
            if "/api/admin/orders" in str(path):
                # #733: 验证 orders API 收到的 phone 是 verifiedPhone（非用户原始输入）
                return _make_order_create_response(success=True, order_id="order-cust-001")
            return {"success": False, "error": {"message": "unknown path"}}

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            sms_code="123456",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is True, f"验证码验证通过后应创建成功: {result.error}"
        assert "order-cust-001" in str(result.data)

        # 验证调用了 SMS verify API 和 orders API
        assert mock_client.post.call_count == 2
        calls = mock_client.post.call_args_list
        # 第一次调用: SMS verify API
        assert "/api/auth/sms/verify" in str(calls[0])
        # 第二次调用: 订单创建 API
        assert "/api/admin/orders" in str(calls[1])

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_sms_verify_api_timeout_returns_error(self, mock_get_client, sample_tool_context):
        """SMS verify API 超时 → 不创建订单 + 返回 error（不 fallback 到无验证创建）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",
            sms_code="123456",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is False, (
            f"SMS verify API 超时应拒绝创建订单，不应 fallback: {result.message}"
        )
        assert result.suggestion is not None, "失败时必须提供修复建议"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_admin_creates_order_without_sms_verify_succeeds(self, mock_get_client, admin_tool_context):
        """admin角色创建订单 → 不需要SMS验证（管理员帮客户下单）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_order_create_response(success=True, order_id="order-admin-001"))
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
        # 确认只调用了 orders API，没有调 SMS verify API
        calls = [str(c) for c in mock_client.post.call_args_list]
        assert not any("/api/auth/sms/verify" in c for c in calls), (
            "admin角色不应调用 SMS verify API"
        )

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_uses_verified_phone_for_order(self, mock_get_client, sample_tool_context):
        """#733: SMS verify 成功 → 订单中的 phone 是 API 返回的 verifiedPhone（非用户原始输入）"""
        mock_client = AsyncMock()

        async def mock_post(path, json_data=None, **kwargs):
            if "/api/auth/sms/verify" in str(path):
                # API 返回不同的 phone（模拟运营商返回标准格式）
                return {"success": True, "data": {"verifiedPhone": "13800138888"}}
            if "/api/admin/orders" in str(path):
                # 验证 orders API 收到的是 verifiedPhone
                assert json_data is not None, "orders API 应有 json_data"
                assert json_data.get("customerPhone") == "13800138888", (
                    f"订单 phone 应为 verifiedPhone '13800138888'，"
                    f"实际: {json_data.get('customerPhone')}"
                )
                return _make_order_create_response(success=True)
            return {"success": False}

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_get_client.return_value = mock_client

        tool = OrderCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            customer_name="测试客户",
            customer_phone="13800138000",  # 用户原始输入
            sms_code="123456",
            items=[{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}],
        )

        assert result.success is True


class TestCustomerOrderCreateSuccess:
    """客户成功创建订单（需要SMS验证码 + SMS verify API）"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_customer_creates_own_order_with_sms(self, mock_get_client, sample_tool_context):
        """客户提供验证码 → SMS verify API 通过 → 创建订单"""
        mock_client = AsyncMock()

        async def mock_post(path, json_data=None, **kwargs):
            if "/api/auth/sms/verify" in str(path):
                return _make_sms_verify_response(success=True)
            if "/api/admin/orders" in str(path):
                return _make_order_create_response(success=True, order_id="order-cust-001")
            return {"success": False}

        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_get_client.return_value = mock_client

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

        # 验证调用了两个 API
        assert mock_client.post.call_count == 2

        # 验证 orders API 传入了正确的 tenant_id / user_id
        orders_call = mock_client.post.call_args_list[1]
        assert orders_call[1]["tenant_id"] == sample_tool_context.tenant_id
        assert orders_call[1]["user_id"] == sample_tool_context.user_id


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
