"""SettingsManageTool 单元测试 — 系统设置 / AI 配置 / 登录日志**查询**（只读）。

B 端只读化（issue #5247 用户裁定 2026-09-23；settings 域整域收口 = issue #5302）：
settings_manage 的写 action（`update_settings` / `update_ai_config` / `change_password`）
已从工具删除 ⇒ 本次退休写路径用例（**产品裁定，非放宽门禁**）。
写能力下线的判据（枚举 / schema / description / 入口拒绝）在
`tests/test_settings_domain_readonly.py`（新增文件，专治 #5302 的整域漏网）。
"""
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


# [RETIRED #5302] TestSettingsUpdate（1 例） 已退休：更新系统参数（update_settings）已从工具删除
#   （B 端只读化；settings 域整域收口）：写能力不再存在，断言无对象。
#   下线判据见 tests/test_settings_domain_readonly.py::TestSettingsManageIsReadOnly。


class TestAIConfig:
    @patch("app.tools.settings_manage.get_admin_api_client")
    async def test_get_ai_config(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"model": "deepseek-flash", "temperature": 0.7}
        })
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="get_ai_config")
        assert result.success is True


# [RETIRED #5302] TestAIConfig.test_update_ai_config（1 例） 已退休：更新 AI 配置
#   （update_ai_config）已从工具删除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5302] TestChangePassword（1 例） 已退休：修改密码（change_password）已从工具删除
#   （B 端只读化；后台亦无自助改密入口，见 issue #3006/#3098）：写能力不再存在，断言无对象。


# [RETIRED #5302] TestSettingsChangePasswordValidation（3 例） 已退休：改密的参数校验
#   （缺旧密码 / 缺新密码 / 新密码过短）随 change_password 一并退场 —— 参数不再存在于 schema
#   与 execute 签名，校验对象消失（防"留着校验分支"把写路径的可达性重新引回来）。


# [RETIRED #5302] TestSettingsUpdateValidation（2 例） 已退休：更新设置 / 更新 AI 配置的
#   「至少给一个字段」校验随两个写 action 一并退场（同上）。


class TestSettingsPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="get_settings")
        assert result.success is False
        assert "权限" in result.error


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