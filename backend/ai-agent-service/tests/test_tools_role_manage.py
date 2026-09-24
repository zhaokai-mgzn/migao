"""RoleManageTool 单元测试 — 角色/权限查询（只读）。

B 端只读化（issue #5247）：role_manage（角色与权限） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
"""
# case_ids: HR-004, HR-005
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.role_manage import RoleManageTool


@pytest.fixture
def tool():
    return RoleManageTool()


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


class TestRolePermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_denied(self, tool, agent_tool_context):
        result = await tool.execute(context=agent_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="grant")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestRoleList:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_list_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "r1", "name": "管理员", "code": "admin"}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="list", page="2", size="5", keyword="管理")
        assert result.success is True
        assert result.data["roles"][0]["id"] == "r1"
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["keyword"] == "管理"
        assert mock_client.get.call_args[0][0] == "/api/admin/roles"

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_list_empty_message(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True
        assert "未找到符合条件的角色" in result.message

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_all_roles(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "r1", "name": "管理员"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="all")
        assert result.success is True
        assert result.data["count"] == 1
        assert mock_client.get.call_args[0][0] == "/api/admin/roles/all"


class TestRoleDetail:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少角色 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"id": "r1", "name": "管理员"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", role_id="r1")
        assert result.success is True
        assert mock_client.get.call_args[0][0] == "/api/admin/roles/r1"


# [RETIRED #5247] TestRoleCreate（2 例） 已退休：建角色（create）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestRoleUpdate（3 例） 已退休：改角色（update）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestRoleDelete（2 例） 已退休：删角色（delete）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


class TestRolePermissions:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_list_permissions(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": [{"code": "product:manage", "name": "商品管理"}],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_permissions")
        assert result.success is True
        assert result.data["count"] == 1
        assert mock_client.get.call_args[0][0] == "/api/admin/permissions"
