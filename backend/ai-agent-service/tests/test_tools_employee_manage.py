"""EmployeeManageTool 单元测试 — 员工查询（只读）。

B 端只读化（issue #5247）：employee_manage（员工账号） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
"""
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


# [RETIRED #5247] TestCreateContract（3 例） 已退休：建员工（create）已从 B 端移除（B 端只读化）：password 必填契约随之消失，断言无对象。


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

    # ============ 员工权限：employee:list 细粒度控制（B 端只读化后只剩查询面） ============
    # 与后端 AdminUserController 的 @RequirePermission 口径一致：
    # - 查询（list/detail）需 employee:list
    # - 写操作（create/update/delete/reset_password/toggle_status）已随 B 端只读化（issue #5247）
    #   全部移除：写码 employee:create 与其门禁用例见下方 [RETIRED #5247]
    # - admin(*) 全部放行

    @pytest.fixture
    def operator_list_only_context(self):
        return ToolContext(
            tenant_id=1, user_id="op_001", session_id="sess_op", role="operator",
            permissions=["employee:list"],
        )

    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_operator_with_list_only_can_query(self, mock_get_client, tool, operator_list_only_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=operator_list_only_context, action="list")
        assert result.success is True

    # [RETIRED #5247] test_operator_with_list_only_cannot_create 已退休：建员工（create）已从 B 端移除（B 端只读化）：employee:create 细粒度写门禁随写 action 一并消失。

    # [RETIRED #5247] test_operator_with_list_only_cannot_delete 已退休：删员工（delete）已从 B 端移除（B 端只读化）：employee:create 细粒度写门禁随写 action 一并消失。

    # [RETIRED #5247] test_operator_with_create_can_create 已退休：建员工（create）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

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


# [RETIRED #5247] TestEmployeeCreate（2 例） 已退休：建员工（create）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestEmployeeUpdate（4 例） 已退休：改员工（update）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestEmployeeDelete（2 例） 已退休：删员工（delete）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestEmployeeResetPassword（2 例） 已退休：重置密码（reset_password）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestEmployeeToggleStatus（3 例） 已退休：启停员工（toggle_status）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。
