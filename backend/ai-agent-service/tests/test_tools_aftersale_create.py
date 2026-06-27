"""
测试 app.tools.aftersale_create — C端售后创建工具

业务真值 #2: 客户可以创建售后工单→必须关联已有订单号，只能创建自己的工单
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestAftersaleCreatePermission:
    """权限校验 — customer角色可创建售后工单"""

    async def test_customer_role_allowed(self, sample_tool_context):
        """customer角色可以创建售后工单"""
        from app.tools.aftersale_create import AftersaleCreateTool
        tool = AftersaleCreateTool()
        assert tool.check_permission(sample_tool_context) is True

    async def test_guest_role_denied(self, unauthorized_tool_context):
        """guest不能创建售后工单"""
        from app.tools.aftersale_create import AftersaleCreateTool
        tool = AftersaleCreateTool()
        assert tool.check_permission(unauthorized_tool_context) is False


class TestAftersaleCreateSuccess:
    """成功创建售后工单"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_customer_creates_aftersale_with_order_id(self, mock_get_client, sample_tool_context):
        """客户关联已有订单号创建售后工单（需先验证订单所有权 #518）"""
        from app.tools.aftersale_create import AftersaleCreateTool

        mock_client = AsyncMock()
        # Mock: 订单查询（所有权验证）返回属于当前客户的订单
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-123",
                "orderNo": "ORD-001",
                "customerId": sample_tool_context.user_id,  # 属于当前客户
            },
        })
        # Mock: 售后工单创建
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "as-cust-001",
                "ticketNo": "AS-2024-C001",
                "orderId": "order-123",
                "ticketType": "refund",
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="refund",
            reason="商品与描述不符",
        )

        assert result.success is True
        assert "as-cust-001" in str(result.data)

        # 验证先调了订单查询（get）再创建（post）
        assert mock_client.get.called, "必须先查询订单验证所有权"
        mock_client.post.assert_called_once()

        # 验证传入了正确的参数
        call_args = mock_client.post.call_args
        json_data = call_args[1]["json_data"]
        assert json_data["orderId"] == "order-123"
        assert json_data["ticketType"] == "refund"
        assert json_data["source"] == "customer"


class TestAftersaleCreateValidation:
    """参数校验"""

    async def test_missing_order_id_returns_error(self, sample_tool_context):
        """缺少order_id返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="",
            ticket_type="refund",
            reason="商品有问题",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_missing_ticket_type_returns_error(self, sample_tool_context):
        """缺少ticket_type返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            reason="商品有问题",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_missing_reason_returns_error(self, sample_tool_context):
        """缺少reason返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="exchange",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_invalid_ticket_type_rejected(self, sample_tool_context):
        """无效ticket_type被拒绝"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="delete_order",  # 无效类型
            reason="test",
        )

        assert result.success is False


class TestAftersaleCreateFailure:
    """错误处理"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_admin_api_returns_failure_with_suggestion(self, mock_get_client, sample_tool_context):
        """admin-api失败时返回suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"message": "订单不存在"},
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-999",
            ticket_type="refund",
            reason="test",
        )

        assert result.success is False
        assert result.suggestion is not None


# ============================================================
# GAP-2: 售后工单创建 → 必须校验订单属于当前客户
# 业务真值: 售后工单创建时校验创建者=订单所有者
# 当前状态: FAIL — 未验证 order_id 是否属于 customer
# ============================================================

class TestAftersaleCreateOrderOwnership:
    """Gap-2: 创建售后工单前验证订单属于当前客户"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_verify_order_belongs_to_customer_before_create(self, mock_get_client, sample_tool_context):
        """创建售后工单前 → 应先查询订单确认属于当前客户"""
        from app.tools.aftersale_create import AftersaleCreateTool

        # Mock admin-api 对订单查询的响应（order_id 属于 customer user_001）
        mock_client = AsyncMock()
        # 第一次调用: 查询订单详情（验证所有权）
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-123",
                "orderNo": "ORD-001",
                "customerId": sample_tool_context.user_id,  # 属于当前客户
                "customerIdRaw": None,
            },
        })
        # 第二次调用: 创建售后工单
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "as-cust-001", "ticketNo": "AS-001", "status": "pending"},
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="refund",
            reason="商品与描述不符",
        )

        assert result.success is True, (
            f"订单属于当前客户时应成功创建: error={result.error}"
        )

        # 验证先调了订单查询再创建
        assert mock_client.get.called, "必须先查询订单验证所有权"
        # 验证查询了订单详情
        get_call_url = mock_client.get.call_args[0][0] if mock_client.get.call_args else ""
        assert "order" in get_call_url.lower(), f"应先查询订单: {get_call_url}"

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_non_owner_cannot_create_aftersale_for_order(self, mock_get_client, sample_tool_context):
        """订单不属于当前客户时 → 创建售后工单应失败"""
        from app.tools.aftersale_create import AftersaleCreateTool

        # Mock admin-api: 订单属于另一个客户 (user_999)，不是当前客户 (user_001)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "order-456",
                "orderNo": "ORD-456",
                "customerId": "user_999",  # ← 不属于当前客户！
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,  # user_id = "user_001"
            order_id="order-456",
            ticket_type="complaint",
            reason="不是我自己的订单",
        )

        assert result.success is False, (
            f"订单不属于当前客户时应拒绝创建: result={result}"
        )
        assert "不属于" in (result.error or "") + (result.message or ""), (
            f"错误信息应说明订单不属于当前客户: error={result.error}, message={result.message}"
        )


# ============================================================
# GAP-4: 售后查询 → 必须 tenant_id + customer_id 双重隔离
# 业务真值: 售后查询做 tenant_id + customer_id 双重隔离
# 当前状态: FAIL — 只传了 tenant_id/user_id header，未显式过滤
# ============================================================

class TestAftersaleQueryCustomerIsolation:
    """Gap-4: 售后查询必须做 customer_id 隔离"""

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_query_for_customer_includes_customer_id_filter(self, mock_get_client, sample_tool_context):
        """customer角色查询售后工单 → 请求中必须包含 customer_id 过滤参数"""
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [],
                "total": 0,
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=sample_tool_context,  # role=customer, user_id=user_001
            action="list",
            page=1,
            size=5,
        )

        assert result.success is True

        # 验证 admin-api 调用参数中包含 customer_id 过滤
        call_args = mock_client.get.call_args
        params = call_args[1].get("params", {})
        assert "customerId" in params or "customer_id" in params, (
            f"customer查询售后工单必须包含customer_id过滤参数，当前params: {params}"
        )

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_detail_for_customer_verifies_ownership(self, mock_get_client, sample_tool_context):
        """customer查看售后详情 → 返回的数据必须属于当前客户"""
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "ticket-001",
                "ticketNo": "AS-001",
                "customerId": sample_tool_context.user_id,  # 属于当前客户
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=sample_tool_context,
            action="detail",
            ticket_id="ticket-001",
        )

        assert result.success is True
        assert "ticket-001" in str(result.data)

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_query_includes_both_tenant_id_header_and_customer_id_param(self, mock_get_client, sample_tool_context):
        """customer角色查售后工单 → 验证 HTTP 请求同时携带 X-Tenant-Id header 和 customerId query param"""
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=sample_tool_context,
            action="list",
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs.get("tenant_id") == sample_tool_context.tenant_id, (
            f"售后查询请求必须包含X-Tenant-Id header(tenant_id kwarg): {call_kwargs}"
        )
        params = call_kwargs.get("params", {})
        assert str(params.get("customerId")) == str(sample_tool_context.user_id), (
            f"customer角色查询售后工单必须传customerId参数，当前params: {params}"
        )

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_query_response_filters_by_tenant_id(self, mock_get_client, sample_tool_context):
        """API 返回含跨租户工单 → 验证 tenant_id 不匹配的记录被过滤"""
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "t1", "ticketNo": "AS-001", "customerId": sample_tool_context.user_id, "tenantId": 1, "status": "pending"},
                    {"id": "t2", "ticketNo": "AS-002", "customerId": sample_tool_context.user_id, "tenantId": 999, "status": "pending"},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=sample_tool_context,
            action="list",
        )

        assert result.success is True
        items = result.data.get("items", [])
        assert len(items) == 1, f"跨租户工单应被过滤，期望1条，实际{len(items)}条"
        assert items[0]["id"] == "t1"

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_query_detail_filters_by_tenant_id(self, mock_get_client, sample_tool_context):
        """售后工单详情 → 验证 tenant_id 不匹配时拒绝"""
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "ticket-001",
                "ticketNo": "AS-001",
                "customerId": sample_tool_context.user_id,
                "tenantId": 999,
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=sample_tool_context,
            action="detail",
            ticket_id="ticket-001",
        )

        assert result.success is False, f"跨租户工单详情应拒绝访问"
        error_text = (result.error or "") + (result.message or "")
        assert "租户" in error_text or "tenant" in error_text.lower(), (
            f"错误信息应说明租户不匹配: error={result.error}, message={result.message}"
        )

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_aftersale_query_missing_customer_id_rejected(self, mock_get_client, sample_tool_context):
        """customer 角色但 context.user_id 为空 → 验证拒绝执行，不发起 API 调用"""
        from app.tools.base import ToolContext
        from app.tools.aftersale_query import AftersaleQueryTool

        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_get_client.return_value = mock_client

        no_user_context = ToolContext(
            tenant_id=1,
            user_id="",
            session_id="sess_test",
            role="customer",
        )

        tool = AftersaleQueryTool()
        result = await tool.execute(
            context=no_user_context,
            action="list",
        )

        assert result.success is False
        error_text = (result.error or "") + (result.message or "")
        assert "customer" in error_text.lower() or "用户" in error_text
        mock_client.get.assert_not_called()
