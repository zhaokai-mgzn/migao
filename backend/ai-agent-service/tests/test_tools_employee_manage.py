"""EmployeeManageTool 单元测试 — 员工 CRUD、重置密码、启停。"""
# case_ids: HR-001, HR-002, HR-003
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.employee_manage import EmployeeManageTool


@pytest.fixture
def tool():
    return EmployeeManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def agent_tool_context():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess", role="agent")


class TestEmployeePermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_denied(self, tool, agent_tool_context):
        result = await tool.execute(context=agent_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="promote")
        assert result.success is False
        assert "无效的操作类型" in result.error

    # ============ 员工权限全链路：employee:list / employee:create 细粒度控制 ============
    # 与后端 AdminUserController 的 @RequirePermission 口径一致：
    # - 查询（list/detail）需 employee:list
    # - 写操作（create/update/delete/reset_password/toggle_status）需 employee:create
    # - admin(*) 全部放行

    @pytest.fixture
    def operator_list_only_context(self):
        return ToolContext(
            tenant_id=1, user_id="op_001", session_id="sess_op", role="operator",
            permissions=["employee:list"],
        )

    @pytest.fixture
    def operator_write_context(self):
        return ToolContext(
            tenant_id=1, user_id="op_002", session_id="sess_op2", role="operator",
            permissions=["employee:list", "employee:create"],
        )

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_operator_with_list_only_can_query(self, mock_get_client, tool, operator_list_only_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=operator_list_only_context, action="list")
        assert result.success is True

    async def test_operator_with_list_only_cannot_create(self, tool, operator_list_only_context):
        result = await tool.execute(context=operator_list_only_context, action="create", name="张", phone="13800000000")
        assert result.success is False
        assert "权限" in result.error
        assert "管理员工" in result.suggestion

    async def test_operator_with_list_only_cannot_delete(self, tool, operator_list_only_context):
        result = await tool.execute(context=operator_list_only_context, action="delete", user_id="e1")
        assert result.success is False
        assert "权限" in result.error

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_operator_with_create_can_create(self, mock_get_client, tool, operator_write_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "e99"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=operator_write_context, action="create",
            name="张", phone="13800000000", password="Abc@123456", role="operator")
        assert result.success is True

    async def test_operator_without_any_employee_permission_denied(self, tool):
        ctx = ToolContext(
            tenant_id=1, user_id="op_003", session_id="sess_op3", role="operator",
            permissions=["dashboard:view"],
        )
        result = await tool.execute(context=ctx, action="list")
        assert result.success is False
        assert "权限" in result.error


class TestEmployeeList:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_list_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "e1", "name": "张三", "phone": "13800138000", "status": "active", "roles": []}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="list", page="2", size="5", keyword="张", status="active", role="agent")
        assert result.success is True
        assert result.data["users"][0]["id"] == "e1"
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["keyword"] == "张"
        assert params["status"] == "active"
        assert params["role"] == "agent"
        assert mock_client.get.call_args[0][0] == "/api/admin/users"

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_list_empty_message(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        assert "未找到符合条件的员工" in result.message


class TestEmployeeDetail:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少员工 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"id": "e1", "name": "张三"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", user_id="e1")
        assert result.success is True
        assert mock_client.get.call_args[0][0] == "/api/admin/users/e1"


class TestEmployeeCreate:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create", password="p", name="n")
        assert r1.success is False and "缺少手机号" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create", phone="139", name="n")
        assert r2.success is False and "缺少密码" in r2.error
        r3 = await tool.execute(context=admin_tool_context, action="create", phone="139", password="p")
        assert r3.success is False and "缺少姓名" in r3.error
        mock_client.post.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_create_success_with_role_ids(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "e-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", phone="139", password="p", name="n", role_ids=["r1"])
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/users"
        assert mock_client.post.call_args[1]["json_data"]["roleIds"] == ["r1"]


class TestEmployeeUpdate:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", name="n")
        assert result.success is False
        assert "缺少员工 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_update_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", user_id="e1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_update_role_ids_priority_over_role(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", user_id="e1", role_ids=["r1", "r2"], role="agent")
        assert result.success is True
        json_data = mock_client.put.call_args[1]["json_data"]
        assert json_data["roleIds"] == ["r1", "r2"]
        assert "role" not in json_data

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_update_role_fallback(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="update", user_id="e1", role="agent")
        assert result.success is True
        assert mock_client.put.call_args[1]["json_data"]["role"] == "agent"


class TestEmployeeDelete:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "缺少员工 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete", user_id="e1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/users/e1"


class TestEmployeeResetPassword:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_reset_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="reset_password")
        assert result.success is False
        assert "缺少员工 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_reset_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="reset_password", user_id="e1", new_password="newpwd")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/users/e1/reset-password"
        assert mock_client.put.call_args[1]["json_data"] == {"newPassword": "newpwd"}


class TestEmployeeToggleStatus:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_toggle_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_status", status="disabled")
        assert result.success is False
        assert "缺少员工 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", user_id="e1", status="archived")
        assert result.success is False
        assert "无效的状态值" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_toggle_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", user_id="e1", status="disabled")
        assert result.success is True
        assert "已禁用" in result.message
        assert mock_client.put.call_args[0][0] == "/api/admin/users/e1/status"
