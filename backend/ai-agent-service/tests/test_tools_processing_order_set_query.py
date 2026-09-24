"""
加工套件 / 扫码进度查询 Tool 测试 —— 只读契约 + **逐 action 的端点归属**（issue #5247）

⚠️ 权限码是 `processing:manage`：这三个读端点（#5257 新增、#5246 收口）生效码即 `processing:manage`
—— 与侧边栏「生产看板」节点同码。若写成旧的 `processing:view`，持有它的岗位能在页面里看不到
生产看板的情况下经米宝读到套件与扫码进度（权限泄露），故这里逐字钉死。
"""
# case_ids: PG-057
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.processing_order_set_query import ProcessingOrderSetQueryTool
from app.tools.base import ToolContext

PERMISSION = "processing:manage"
LIST = "/api/admin/processing-order-sets"
DETAIL = "/api/admin/processing-order-sets/ps-1"
SCAN = "/api/admin/processing-order-sets/scan-progress"

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
        tool = ProcessingOrderSetQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_permission_is_the_menu_node_code(self):
        assert ProcessingOrderSetQueryTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        assert ProcessingOrderSetQueryTool().name == "processing_order_set_query"

    def test_action_enum_is_read_only_only(self):
        enum = ProcessingOrderSetQueryTool().parameters["properties"]["action"]["enum"]
        assert sorted(enum) == ["detail", "list", "scan_progress"]


class TestPermissionGate:

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await ProcessingOrderSetQueryTool().execute(context=DENIED, action="list")
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()


class TestEndpointAttribution:

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_list_hits_collection_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await ProcessingOrderSetQueryTool().execute(context=ALLOWED, action="list")

        assert result.success is True
        assert client.get.call_args_list[0].args[0] == LIST

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_detail_puts_id_into_the_path(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await ProcessingOrderSetQueryTool().execute(context=ALLOWED, action="detail", id="ps-1")

        assert client.get.call_args_list[0].args[0] == DETAIL

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_scan_progress_hits_scan_endpoint_and_forwards_order_no(self, mock_get_client):
        """扫码进度必须带订单号或加工单号之一，并**映射成后端驼峰名**"""
        client = _client()
        mock_get_client.return_value = client

        await ProcessingOrderSetQueryTool().execute(
            context=ALLOWED, action="scan_progress", order_no="ORD-1")

        assert client.get.call_args_list[0].args[0] == SCAN
        assert client.get.call_args_list[0].kwargs.get("params", {}).get("orderNo") == "ORD-1"

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_scan_progress_without_identifier_asks_instead_of_asking_backend(
            self, mock_get_client):
        """缺标识符 ⇒ **不发 HTTP 请求**，让模型回去向用户要单号（否则后端查询无意义或全量返回）"""
        client = _client()
        mock_get_client.return_value = client

        result = await ProcessingOrderSetQueryTool().execute(
            context=ALLOWED, action="scan_progress")

        assert result.success is False
        client.get.assert_not_called()

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await ProcessingOrderSetQueryTool().execute(context=ALLOWED, action="list")

        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.processing_order_set_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await ProcessingOrderSetQueryTool().execute(context=ALLOWED, action="list")

        assert result.success is False
        assert result.error == "tool_execution_failed"