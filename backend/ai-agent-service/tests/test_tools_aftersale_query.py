"""
AftersaleQueryTool 单元测试 — C端售后查询（列表/详情 + Gap-4 双重隔离）

覆盖契约（DRAFT_JSON L2/L4）：
- 声明：read_only=True + idempotent=True，allowed_roles 含 customer/admin/agent/tenant_admin
- 权限：customer 允许、guest 拒绝；customer 且 user_id 为空 → 拒绝（"缺少用户标识"）
- list：customer 注入 customerId 参数（admin/agent 不过滤）；tenant_id + customer_id 双重过滤（不匹配剔除且 total 递减）
- detail：tenant_id/customer_id 不匹配 → 拒绝（"租户不匹配" / "该工单不属于您"）
- 无效 action → error
"""
# case_ids: AS-001, AS-002, AS-005, DF-009
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.aftersale_query import AftersaleQueryTool
from app.tools.base import ToolContext


@pytest.fixture
def tool():
    return AftersaleQueryTool()


@pytest.fixture
def customer_ctx():
    """customer 角色上下文，user_id=user_001，tenant_id=1"""
    return ToolContext(tenant_id=1, user_id="user_001", session_id="sess_test", role="customer")


@pytest.fixture
def admin_ctx():
    """admin 角色上下文"""
    return ToolContext(tenant_id=1, user_id="admin_001", session_id="sess_test", role="admin")


class TestAftersaleQueryDeclaration:
    """工具元数据声明 — read_only 纯查询，无需确认"""

    def test_metadata(self, tool):
        assert tool.name == "aftersale_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_allowed_roles(self, tool):
        assert set(tool.allowed_roles) == {"customer", "admin", "agent", "tenant_admin"}


class TestAftersaleQueryPermission:
    """角色权限 — 两层权限检查"""

    def test_customer_allowed(self, tool, customer_ctx):
        assert tool.check_permission(customer_ctx) is True

    def test_admin_allowed(self, tool, admin_ctx):
        assert tool.check_permission(admin_ctx) is True

    def test_guest_denied(self, tool):
        guest = ToolContext(tenant_id=1, user_id="guest_001", session_id="s", role="guest")
        assert tool.check_permission(guest) is False

    async def test_guest_execute_rejected(self, tool):
        guest = ToolContext(tenant_id=1, user_id="guest_001", session_id="s", role="guest")
        result = await tool.execute(context=guest, action="list")
        assert result.success is False
        assert "权限" in result.error


class TestAftersaleQueryList:
    """list 查询 — customerId 注入 + status 过滤"""

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_list_happy_path(self, mock_get_client, tool, customer_ctx):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "t1", "ticketNo": "AS-001", "customerId": "user_001", "tenantId": 1, "status": "pending"},
                ],
                "total": 1,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list")

        assert result.success is True
        assert result.data["total"] == 1
        assert len(result.data["items"]) == 1
        assert result.data["items"][0]["ticketNo"] == "AS-001"

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_customer_injects_customer_id_filter(self, mock_get_client, tool, customer_ctx):
        """customer 角色 → 请求 params 必须包含 customerId"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list", status="pending")

        assert result.success is True
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert params.get("customerId") == "user_001"
        assert params.get("status") == "pending"

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_admin_does_not_inject_customer_id(self, mock_get_client, tool, admin_ctx):
        """admin 角色 → 请求 params 不注入 customerId（可看全部工单）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_ctx, action="list")

        assert result.success is True
        params = mock_client.get.call_args.kwargs.get("params", {})
        assert "customerId" not in params

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_customer_empty_user_id_rejected(self, mock_get_client, tool):
        """customer 角色 user_id 为空 → 拒绝且不发起 API 调用"""
        empty_ctx = ToolContext(tenant_id=1, user_id="", session_id="s", role="customer")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=empty_ctx, action="list")

        assert result.success is False
        assert "用户" in result.error
        mock_client.get.assert_not_called()


class TestAftersaleQueryDetail:
    """detail 查询"""

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_detail_happy_path(self, mock_get_client, tool, customer_ctx):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"id": "t1", "ticketNo": "AS-001", "customerId": "user_001", "tenantId": 1, "status": "pending"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="detail", ticket_id="t1")

        assert result.success is True
        assert result.data["ticketNo"] == "AS-001"

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_detail_missing_ticket_id(self, mock_get_client, tool, customer_ctx):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(context=customer_ctx, action="detail")

        assert result.success is False
        assert "工单" in result.error

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_detail_admin_api_failure(self, mock_get_client, tool, customer_ctx):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "工单不存在"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="detail", ticket_id="t1")

        assert result.success is False
        assert "工单不存在" in result.error


class TestAftersaleQueryIsolation:
    """Gap-4：tenant_id + customer_id 双重隔离（防御性过滤）"""

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_list_filters_cross_tenant_items(self, mock_get_client, tool, customer_ctx):
        """跨租户记录被剔除且 total 递减"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "t1", "customerId": "user_001", "tenantId": 1, "status": "pending"},
                    {"id": "t2", "customerId": "user_001", "tenantId": 999, "status": "pending"},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list")

        assert result.success is True
        assert len(result.data["items"]) == 1
        assert result.data["items"][0]["id"] == "t1"
        assert result.data["total"] == 1

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_list_filters_other_customer_items(self, mock_get_client, tool, customer_ctx):
        """他人 customerId 记录被剔除"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "t1", "customerId": "user_001", "tenantId": 1, "status": "pending"},
                    {"id": "t2", "customerId": "user_999", "tenantId": 1, "status": "pending"},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list")

        assert result.success is True
        assert len(result.data["items"]) == 1
        assert result.data["items"][0]["id"] == "t1"
        assert result.data["total"] == 1

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_detail_tenant_mismatch_rejected(self, mock_get_client, tool, customer_ctx):
        """detail 返回跨租户工单 → 拒绝"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"id": "t1", "customerId": "user_001", "tenantId": 999, "status": "pending"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="detail", ticket_id="t1")

        assert result.success is False
        assert "租户" in result.error

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_detail_other_customer_rejected(self, mock_get_client, tool, customer_ctx):
        """detail 返回他人工单 → 拒绝"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"id": "t1", "customerId": "user_999", "tenantId": 1, "status": "pending"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="detail", ticket_id="t1")

        assert result.success is False
        assert "不属于您" in result.message


class TestAftersaleQueryInvalidAction:
    """无效 action"""

    async def test_invalid_action(self, tool, customer_ctx):
        result = await tool.execute(context=customer_ctx, action="create")

        assert result.success is False
        assert "无效操作" in result.error


class TestAftersaleQueryErrorHandling:
    """admin-api 失败 / 执行异常"""

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_list_admin_api_failure(self, mock_get_client, tool, customer_ctx):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list")

        assert result.success is False
        assert "服务不可用" in result.error

    @patch("app.tools.aftersale_query.get_admin_api_client")
    async def test_list_execution_exception_generic_error(self, mock_get_client, tool, customer_ctx):
        """执行抛异常 → tool_execution_failed（不暴露内部错误）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_ctx, action="list")

        assert result.success is False
        assert result.error == "tool_execution_failed"
