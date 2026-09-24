"""
入库单/批次查询 Tool 测试 —— 只读契约 + **逐 action 的端点归属**（issue #5247）

三个只读 action 各自命中一个端点；`detail` 必须把 `id` 拼进路径（拼错就是查不到或查错单）。
"""
# case_ids: PR-005
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.inbound_order_query import InboundOrderQueryTool
from app.tools.base import ToolContext

PERMISSION = "inbound:view"
LIST = "/api/admin/inbound-orders"
BATCHES = "/api/admin/inbound-orders/batches"
DETAIL = "/api/admin/inbound-orders/in-1"

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
        tool = InboundOrderQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_required_permission_equals_endpoint_code(self):
        assert InboundOrderQueryTool.required_permissions == [PERMISSION]

    def test_action_enum_is_read_only_only(self):
        """action 闭集 = 三个只读动作；新增写动作会让这条红（#5247 的护栏）"""
        enum = InboundOrderQueryTool().parameters["properties"]["action"]["enum"]
        assert sorted(enum) == ["batches", "detail", "list"]


class TestPermissionGate:

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await InboundOrderQueryTool().execute(context=DENIED, action="list")
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()


class TestEndpointAttribution:
    """逐 action 断言命中它**声称**的端点"""

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_list_hits_collection_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await InboundOrderQueryTool().execute(context=ALLOWED, action="list")

        assert result.success is True
        assert client.get.call_args_list[0].args[0] == LIST

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_batches_hits_batches_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await InboundOrderQueryTool().execute(context=ALLOWED, action="batches")

        assert client.get.call_args_list[0].args[0] == BATCHES

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_detail_puts_id_into_the_path(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await InboundOrderQueryTool().execute(context=ALLOWED, action="detail", id="in-1")

        assert client.get.call_args_list[0].args[0] == DETAIL

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await InboundOrderQueryTool().execute(context=ALLOWED, action="list")

        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.inbound_order_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await InboundOrderQueryTool().execute(context=ALLOWED, action="list")

        assert result.success is False
        assert result.error == "tool_execution_failed"