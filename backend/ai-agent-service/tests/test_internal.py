"""app/api/internal.py 单元测试 — 内部接口（Service Token）。

覆盖：/tools/execute 工具不存在 404 / 写工具 403 / 执行异常 500；/tools 列表端点。
（知识库同步/stats 端点已随旧 RAG 知识库移除，issue #3051）
"""
# case_ids: API-007

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.internal import (
    ToolExecuteRequest,
    execute_tool,
    list_tools,
)
from app.tools.base import ToolResult


class _ReadTool:
    name = "product_search"
    description = "只读工具"
    read_only = True

    async def execute(self, context, **kwargs):
        return ToolResult(success=True, data={"items": []})


class _WriteTool:
    name = "order_create"
    description = "写工具"
    read_only = False

    async def execute(self, context, **kwargs):
        return ToolResult(success=True, data={})


def _registry(tool, execute_side_effect=None):
    """构造 get_tool_registry 的 MagicMock"""
    reg = MagicMock()
    tool_instance = tool
    if execute_side_effect is not None:
        tool_instance.execute = AsyncMock(side_effect=execute_side_effect)
    reg.get_tool = MagicMock(return_value=tool_instance)
    return reg


class TestExecuteTool:
    def test_tool_not_found_404(self):
        req = ToolExecuteRequest(tool_name="nonexistent", params={}, tenant_id=1, user_id="u1")
        reg = MagicMock()
        reg.get_tool = MagicMock(return_value=None)
        with patch("app.api.internal.get_tool_registry", return_value=reg):
            with pytest.raises(HTTPException) as e:
                asyncio.run(execute_tool(req, authorized=True))
        assert e.value.status_code == 404

    def test_write_tool_403(self):
        req = ToolExecuteRequest(tool_name="order_create", params={}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry",
                   return_value=_registry(tool=_WriteTool())):
            with pytest.raises(HTTPException) as e:
                asyncio.run(execute_tool(req, authorized=True))
        assert e.value.status_code == 403

    def test_execute_error_500(self):
        req = ToolExecuteRequest(tool_name="product_search", params={}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry",
                   return_value=_registry(tool=_ReadTool(), execute_side_effect=RuntimeError("boom"))):
            with pytest.raises(HTTPException) as e:
                asyncio.run(execute_tool(req, authorized=True))
        assert e.value.status_code == 500
        assert e.value.detail["error"]["code"] == "INTERNAL_ERROR"


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_tools(self):
        tool = _ReadTool()
        tool.parameters = {"type": "object", "properties": {}}
        reg = MagicMock()
        reg.get_all_tools = MagicMock(return_value=[tool])
        with patch("app.api.internal.get_tool_registry", return_value=reg):
            result = await list_tools(authorized=True)
        assert result["success"] is True
        assert result["data"]["count"] == 1
        assert result["data"]["tools"][0]["name"] == "product_search"
