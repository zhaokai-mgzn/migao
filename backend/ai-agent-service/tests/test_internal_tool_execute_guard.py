"""内部 /api/internal/tools/execute 端点安全加固 — 回归测试
# case_ids: DF-008

修复背景：
1. /tools/execute 硬编码 role="admin" 且信任请求体 tenant_id/user_id，
   任何持有 SERVICE_TOKEN 的调用方都能对任意租户执行任意工具（含破坏性写）。
2. verify_service_token 在 SERVICE_TOKEN 未配置时 fail-open（直接放行）。

修复后：
1. /tools/execute 仅允许只读工具（read_only=True），写工具返回 403。
2. verify_service_token 在 SERVICE_TOKEN 未配置时 fail-closed（返回 503）。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.internal import ToolExecuteRequest, execute_tool
from app.utils.auth import verify_service_token
from app.tools.base import BaseTool, ToolResult


class TestServiceTokenFailClosed:
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_empty_service_token_fails_closed(self, mock_settings):
        """SERVICE_TOKEN 未配置时，verify_service_token 必须拒绝而非放行。"""
        mock_settings.SERVICE_TOKEN = ""

        with pytest.raises(HTTPException) as exc_info:
            await verify_service_token("any-token")
        assert exc_info.value.status_code == 503


class _WriteTool(BaseTool):
    name = "order_create"
    description = "写工具（测试）"
    read_only = False
    idempotent = False

    async def execute(self, context, **kwargs):
        return ToolResult(success=True, data={})


class _ReadTool(BaseTool):
    name = "product_search"
    description = "只读工具（测试）"
    read_only = True

    async def execute(self, context, **kwargs):
        return ToolResult(success=True, data={})


def _fake_registry(tool):
    reg = MagicMock()
    reg.has_tool = MagicMock(return_value=True)
    reg.get_tool = MagicMock(return_value=tool)
    reg.execute_tool = AsyncMock(return_value=ToolResult(success=True, data={}))
    return reg


class TestToolExecuteReadOnlyGuard:
    def test_write_tool_rejected(self):
        """写工具（order_create）经内部接口执行应返回 403。"""
        req = ToolExecuteRequest(tool_name="order_create", params={}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry", return_value=_fake_registry(_WriteTool())):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(execute_tool(req, authorized=True))
        assert exc_info.value.status_code == 403

    def test_read_tool_allowed(self):
        """只读工具（product_search）不应被守卫拦截，正常执行返回结果。"""
        req = ToolExecuteRequest(tool_name="product_search", params={"keyword": "窗帘"}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry", return_value=_fake_registry(_ReadTool())):
            result = asyncio.run(execute_tool(req, authorized=True))
        assert result["success"] is True
