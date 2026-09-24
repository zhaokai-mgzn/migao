"""
经营日报查询 Tool 测试 —— 只读契约 + 权限面 + **端点归属**（issue #5247 B 端只读化）

本文件是 `app/tools/briefing_query.py` 的**同名单测**（`.github/growth_gate.py` 对每个
tool 模块要求 `tests/test_tools_<name>.py`）。断言分三面：

1. **声明面**：`read_only is True` / `destructive is False` / `required_permissions`
   逐字等于端点生效码 —— 后者是「Agent 能力 ≡ 页面权限」（issue #5246 守则）在**工具粒度**的锚点，
   权限码写错时这一条会红，而不是等到运行时被 admin-api 403；
2. **权限面**：无权限 ⇒ 拒绝**且不发请求**（`assert_not_called`）；有权限 ⇒ 命中它**声称**的端点；
3. **失败面**：后端 `success=false` 与客户端抛异常都必须落成**可归因**的 `ToolResult`，
   不得让异常穿透到图节点。

⚠️ 这些断言会红吗：把 `read_only` 改 False、把权限码改别的、去掉 `check_permission` 早返回、
把端点换成别的路径、把 `except` 里的返回改成 `raise` —— 逐一都会红（每条断言都盯着一个**会变的**真值）。
"""
# case_ids: DA-008, DA-009, DA-010
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.briefing_query import BriefingQueryTool
from app.tools.base import ToolContext

ENDPOINT = "/api/admin/briefing/today"
PERMISSION = "dashboard:view"

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])
SAMPLE = {"date": "2026-09-24", "orderCount": 3, "revenue": 1280.0}


class TestDeclaration:
    """声明面：只读 + 权限码与端点同码"""

    def test_is_declared_read_only(self):
        tool = BriefingQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False

    def test_required_permission_equals_endpoint_code(self):
        """权限码必须逐字等于 `BriefingController` GET 的生效码（#5246 的同一口径）"""
        assert BriefingQueryTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        """工具名是 skill 绑定与判据的键，改名会静默解绑"""
        assert BriefingQueryTool().name == "briefing_query"

    def test_takes_no_parameters(self):
        """固定取当日简报 ⇒ 无参数（有参数会让模型有机会编造入参）"""
        assert BriefingQueryTool().parameters == {
            "type": "object", "properties": {}, "required": []}


class TestPermissionGate:

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        """无权限 ⇒ 拒绝，且**不得**发出请求（越权与假拒绝都从这条路进来）"""
        result = await BriefingQueryTool().execute(context=DENIED)
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_allowed_hits_the_declared_endpoint(self, mock_get_client):
        """有权限 ⇒ 命中**它声称的那个端点**（端点归属的机械证据）"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is True
        paths = [c.args[0] if c.args else c.kwargs.get("path")
                 for c in client.get.call_args_list]
        assert paths == [ENDPOINT], paths

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        """多租户隔离：租户头必须来自 context，不得硬编码"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": SAMPLE})
        mock_get_client.return_value = client

        await BriefingQueryTool().execute(context=ALLOWED)

        kwargs = client.get.call_args_list[0].kwargs
        assert kwargs.get("tenant_id") == ALLOWED.tenant_id


class TestFailureSurface:

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        """后端 `success=false` ⇒ 失败结果里带**后端原文**，便于用户与排查者定位"""
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "简报尚未生成"}})
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert "简报尚未生成" in (result.message or "")

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        """客户端抛异常 ⇒ 落成 `tool_execution_failed`，不得穿透到图节点"""
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is False
        assert result.error == "tool_execution_failed"