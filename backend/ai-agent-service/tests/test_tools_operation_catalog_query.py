"""
工序库 / 工艺路线查询 Tool 测试 —— 只读契约 + **逐 action 的端点归属**（issue #5247）

⚠️ 本工具的权限码是生产域读码 `production:view`（issue #5291：生产域此前**没有读码**，两个读端点与
`ProductionController` 的写面同用 `order:list`/`processing:manage`）：读端点已按 #5246/#5291 的裁决
**拆成方法级 `production:view`** —— 否则持有 `order:list` 的客服/销售/财务能经米宝读到「工艺配置」
页面里看不见的数据（权限泄露），而只持读码的岗位若被要求写码则被假拒绝。
本文件把「工具码 == 端点码」钉在测试层。
"""
# case_ids: PP-002
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.operation_catalog_query import OperationCatalogQueryTool
from app.tools.base import ToolContext

PERMISSION = "production:view"
OPERATIONS = "/api/admin/production/operations-catalog"
ROUTINGS = "/api/admin/production/routings"

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])


def _client():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
    return client


class TestDeclaration:

    def test_is_declared_read_only(self):
        tool = OperationCatalogQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_permission_is_the_menu_node_code(self):
        """权限码 = 侧边栏「工艺配置」节点码（issue #5291 起 = 生产域读码 `production:view`，方向只收窄）"""
        assert OperationCatalogQueryTool.required_permissions == [PERMISSION]

    def test_action_enum_is_read_only_only(self):
        enum = OperationCatalogQueryTool().parameters["properties"]["action"]["enum"]
        assert sorted(enum) == ["operations", "routings"]


class TestPermissionGate:

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await OperationCatalogQueryTool().execute(context=DENIED, action="operations")
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()


class TestEndpointAttribution:

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_operations_hits_catalog_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await OperationCatalogQueryTool().execute(context=ALLOWED, action="operations")

        assert result.success is True
        assert client.get.call_args_list[0].args[0] == OPERATIONS

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_routings_hits_routings_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await OperationCatalogQueryTool().execute(context=ALLOWED, action="routings")

        assert client.get.call_args_list[0].args[0] == ROUTINGS

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await OperationCatalogQueryTool().execute(context=ALLOWED, action="operations")

        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        client = _client()
        client.get = AsyncMock(return_value={"success": False, "error": {"message": "目录不可用"}})
        mock_get_client.return_value = client

        result = await OperationCatalogQueryTool().execute(context=ALLOWED, action="operations")

        assert result.success is False
        assert "目录不可用" in (result.message or "")

    @patch("app.tools.operation_catalog_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await OperationCatalogQueryTool().execute(context=ALLOWED, action="routings")

        assert result.success is False
        assert result.error == "tool_execution_failed"