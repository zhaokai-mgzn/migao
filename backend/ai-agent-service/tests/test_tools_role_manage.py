"""RoleManageTool 单元测试 — 角色/权限管理"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.role_manage import RoleManageTool


@pytest.fixture
def tool():
    return RoleManageTool()


class TestRoleList:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "r1", "name": "管理员"}]}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True

    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_all(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": [{"id": "r1", "name": "管理员"}]
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="all")
        assert result.success is True


class TestRoleCreate:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_create(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "r-new"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", name="运营", code="operator")
        assert result.success is True


class TestRoleDelete:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_delete(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete", role_id="r1")
        assert result.success is True


class TestRolePermissions:
    @patch("app.tools.role_manage.get_admin_api_client")
    async def test_list_permissions(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": [{"code": "product:manage", "name": "商品管理"}]
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list_permissions")
        assert result.success is True


class TestRolePermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error
