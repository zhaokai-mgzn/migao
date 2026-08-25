"""RoleManageTool 单元测试 — 角色/权限 CRUD。"""
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


class TestRoleCreate:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create", code="op")
        assert r1.success is False and "缺少角色名称" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create", name="运营")
        assert r2.success is False and "缺少角色编码" in r2.error
        mock_client.post.assert_not_called()

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_create_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "r-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", name="运营", code="operator", permission_ids=["p1"])
        assert result.success is True
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["permissionIds"] == ["p1"]
        assert mock_client.post.call_args[0][0] == "/api/admin/roles"


class TestRoleUpdate:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", name="新名")
        assert result.success is False
        assert "缺少角色 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_update_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update", role_id="r1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_update_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", role_id="r1", name="新名", permission_ids=["p1", "p2"])
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/roles/r1"
        assert mock_client.put.call_args[1]["json_data"] == {"name": "新名", "permissionIds": ["p1", "p2"]}


class TestRoleDelete:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "缺少角色 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete", role_id="r1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/roles/r1"


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
