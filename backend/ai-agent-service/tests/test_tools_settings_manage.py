"""SettingsManageTool 单元测试 — 系统设置/AI配置/密码修改"""
# case_ids: ST-001, ST-002, ST-003
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.settings_manage import SettingsManageTool


@pytest.fixture
def tool():
    return SettingsManageTool()


class TestSettingsGet:
    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_get(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"companyName": "测试公司"}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="get_settings")
        assert result.success is True


class TestSettingsUpdate:
    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_update(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="update_settings",
            name="新公司名")
        assert result.success is True


class TestAIConfig:
    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_get_ai_config(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"model": "deepseek-v4-pro", "temperature": 0.7}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="get_ai_config")
        assert result.success is True

    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_update_ai_config(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="update_ai_config",
            greeting_template="您好，欢迎咨询", business_hours="9:00-18:00")
        assert result.success is True


class TestChangePassword:
    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_change_password(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="change_password",
            old_password="old123", new_password="new456")
        assert result.success is True


class TestSettingsPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="get_settings")
        assert result.success is False
        assert "权限" in result.error


class TestSettingsChangePasswordValidation:
    """修改密码参数校验"""

    async def test_missing_old_password(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="change_password", new_password="new123")
        assert result.success is False
        assert "缺少旧密码" in result.error

    async def test_missing_new_password(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="change_password", old_password="old123")
        assert result.success is False
        assert "缺少新密码" in result.error

    async def test_new_password_too_short(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="change_password", old_password="old123", new_password="123")
        assert result.success is False
        assert "新密码过短" in result.error


class TestSettingsUpdateValidation:
    """更新设置/AI配置缺字段拒绝"""

    async def test_update_settings_no_fields(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_settings")
        assert result.success is False
        assert "缺少更新参数" in result.error

    async def test_update_ai_config_no_fields(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="update_ai_config")
        assert result.success is False
        assert "缺少更新参数" in result.error


class TestSettingsLoginLogs:
    """登录日志分页查询"""

    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_login_logs(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": 1}, {"id": 2}], "total": 2},
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="login_logs", page=1, size=10)
        assert result.success is True
        assert result.data["total"] == 2
        assert result.data["page"] == 1
        assert result.data["size"] == 10


class TestSettingsInvalidAction:
    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="invalid")
        assert result.success is False
        assert "无效的操作类型" in result.error
