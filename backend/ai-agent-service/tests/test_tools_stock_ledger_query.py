"""
库存台账查询 Tool 测试 —— 只读契约 + 权限面 + **端点归属 + 过滤参数映射**（issue #5247）

同名单测（`.github/growth_gate.py` 要求每个 tool 模块有 `tests/test_tools_<name>.py`）。

断言盯的是**会变的真值**：`read_only` 改 False、权限码写错、去掉权限早返回、端点换成别的路径、
过滤参数名映射错（`sku_id` → `skuId`）—— 逐一都会让这里变红。
"""
# case_ids: PR-005
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.stock_ledger_query import StockLedgerQueryTool
from app.tools.base import ToolContext

ENDPOINT = "/api/admin/stock-ledger"
PERMISSION = "product:list"

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])


def _client(payload=None):
    client = AsyncMock()
    client.get = AsyncMock(return_value=payload or {"success": True, "data": {"items": []}})
    return client


class TestDeclaration:

    def test_is_declared_read_only(self):
        tool = StockLedgerQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_required_permission_equals_endpoint_code(self):
        assert StockLedgerQueryTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        assert StockLedgerQueryTool().name == "stock_ledger_query"

    def test_no_required_params(self):
        """全部过滤项可选：必填参数会让模型有机会编造入参"""
        assert StockLedgerQueryTool().parameters["required"] == []


class TestPermissionGate:

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await StockLedgerQueryTool().execute(context=DENIED)
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_allowed_hits_the_declared_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await StockLedgerQueryTool().execute(context=ALLOWED)

        assert result.success is True
        assert client.get.call_args_list[0].args[0] == ENDPOINT
        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFilterForwarding:
    """过滤参数必须**映射成后端的驼峰名**，写错 ⇒ 后端静默忽略（查全量 = 答非所问）"""

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_sku_filter_maps_to_camel_case(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        await StockLedgerQueryTool().execute(context=ALLOWED, sku_id="sku-1")

        assert client.get.call_args_list[0].kwargs.get("params", {}).get("skuId") == "sku-1"

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_no_filter_sends_empty_params(self, mock_get_client):
        """不带过滤 ⇒ 不得凭空塞参数（会被后端当成过滤条件）"""
        client = _client()
        mock_get_client.return_value = client

        await StockLedgerQueryTool().execute(context=ALLOWED)

        params = client.get.call_args_list[0].kwargs.get("params", {})
        assert all(k not in params for k in ("skuId", "productId", "refNo"))


class TestFailureSurface:

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        client = _client({"success": False, "error": {"message": "台账不可用"}})
        mock_get_client.return_value = client

        result = await StockLedgerQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert "台账不可用" in (result.message or "")

    @patch("app.tools.stock_ledger_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await StockLedgerQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert result.error == "tool_execution_failed"