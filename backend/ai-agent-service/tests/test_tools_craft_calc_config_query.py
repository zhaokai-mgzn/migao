"""
算料配置（参数）查询 Tool 测试 —— 只读契约 + 端点归属（issue #5247）

只查**参数**（选优顺序、档位常量等），不做算料计算：算料需要窗宽/窗高等输入，属页面侧动作。
"""
# case_ids: OR-035
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.craft_calc_config_query import CraftCalcConfigQueryTool
from app.tools.base import ToolContext

ENDPOINT = "/api/admin/production/craft-calc-config"
PERMISSION = "processing:manage"

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])


def _client():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": {"priorities": []}})
    return client


class TestDeclaration:

    def test_is_declared_read_only(self):
        tool = CraftCalcConfigQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_required_permission_equals_endpoint_code(self):
        assert CraftCalcConfigQueryTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        assert CraftCalcConfigQueryTool().name == "craft_calc_config_query"

    def test_takes_no_parameters(self):
        """固定取配置 ⇒ 无参数（不得让模型编造窗宽/窗高来触发计算）"""
        assert CraftCalcConfigQueryTool().parameters == {
            "type": "object", "properties": {}, "required": []}


class TestPermissionGate:

    @patch("app.tools.craft_calc_config_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await CraftCalcConfigQueryTool().execute(context=DENIED)
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.craft_calc_config_query.get_admin_api_client")
    async def test_allowed_hits_the_declared_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await CraftCalcConfigQueryTool().execute(context=ALLOWED)

        assert result.success is True
        assert client.get.call_args_list[0].args[0] == ENDPOINT
        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.craft_calc_config_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        client = _client()
        client.get = AsyncMock(return_value={"success": False, "error": {"message": "配置缺失"}})
        mock_get_client.return_value = client

        result = await CraftCalcConfigQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert "配置缺失" in (result.message or "")

    @patch("app.tools.craft_calc_config_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await CraftCalcConfigQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert result.error == "tool_execution_failed"