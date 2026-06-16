"""EmployeeManageTool 单元测试 — 员工 CRUD"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.employee_manage import EmployeeManageTool


@pytest.fixture
def tool():
    return EmployeeManageTool()


class TestEmployeeList:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "e1", "name": "张三"}]}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is True


class TestEmployeeDetail:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_detail(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"id": "e1", "name": "张三", "phone": "13800138000"}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail", user_id="e1")
        assert result.success is True


class TestEmployeeCreate:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_create(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "e-new"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", name="新员工", phone="13900001111", password="pwd123")
        assert result.success is True


class TestEmployeeDelete:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_delete(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete", user_id="e1")
        assert result.success is True


class TestEmployeeToggleStatus:
    @patch("app.tools.employee_manage.get_admin_api_client")
    async def test_toggle(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_status", user_id="e1", status="disabled")
        assert result.success is True


class TestEmployeePermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error
