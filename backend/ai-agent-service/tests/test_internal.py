"""app/api/internal.py 单元测试 — 内部接口（Service Token）。

覆盖：/tools/execute 工具不存在 404 / 写工具 403 / 执行异常 500；
/knowledge/sync 各同步类型的参数校验与 RAG 未部署降级；
/knowledge/stats 与 /tools 列表端点。
"""
# case_ids: API-007, API-008

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.internal import (
    ToolExecuteRequest,
    KnowledgeSyncRequest,
    execute_tool,
    trigger_knowledge_sync,
    get_knowledge_stats,
    list_tools,
)
from app.tools.base import ToolResult


class _ReadTool:
    name = "product_search"
    description = "只读工具"
    read_only = True

    async def execute(self, context, **kwargs):
        return ToolResult(success=True, data={"items": []})


def _registry(tool=None, execute_result=None, execute_side_effect=None):
    reg = MagicMock()
    reg.get_tool = MagicMock(return_value=tool)
    if execute_side_effect is not None:
        reg.execute_tool = AsyncMock(side_effect=execute_side_effect)
    else:
        reg.execute_tool = AsyncMock(return_value=execute_result or ToolResult(success=True, data={}))
    return reg


def _install_rag(get_pipeline):
    """把不存在的 app.rag.pipeline 注入 sys.modules，模拟 RAG 已部署。"""
    rag = types.ModuleType("app.rag")
    pipeline = types.ModuleType("app.rag.pipeline")
    pipeline.get_rag_pipeline = get_pipeline
    return patch.dict(sys.modules, {"app.rag": rag, "app.rag.pipeline": pipeline})


class TestExecuteTool:
    def test_tool_not_found(self):
        req = ToolExecuteRequest(tool_name="nope", params={}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry", return_value=_registry(tool=None)):
            with pytest.raises(HTTPException) as e:
                import asyncio
                asyncio.run(execute_tool(req, authorized=True))
        assert e.value.status_code == 404
        assert e.value.detail["error"]["code"] == "TOOL_NOT_FOUND"

    def test_read_tool_success(self):
        req = ToolExecuteRequest(tool_name="product_search", params={"kw": "x"}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry", return_value=_registry(tool=_ReadTool())):
            import asyncio
            result = asyncio.run(execute_tool(req, authorized=True))
        assert result["success"] is True

    def test_execute_error_500(self):
        req = ToolExecuteRequest(tool_name="product_search", params={}, tenant_id=1, user_id="u1")
        with patch("app.api.internal.get_tool_registry",
                   return_value=_registry(tool=_ReadTool(), execute_side_effect=RuntimeError("boom"))):
            with pytest.raises(HTTPException) as e:
                import asyncio
                asyncio.run(execute_tool(req, authorized=True))
        assert e.value.status_code == 500
        assert e.value.detail["error"]["code"] == "INTERNAL_ERROR"


class TestTriggerKnowledgeSync:
    @pytest.mark.asyncio
    async def test_rag_disabled(self):
        req = KnowledgeSyncRequest(tenant_id=1, type="full_sync")
        result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is False
        assert result["error"]["code"] == "RAG_DISABLED"

    @pytest.mark.asyncio
    async def test_document_created_missing_content(self):
        pipeline = MagicMock()
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="document_created")
            with pytest.raises(HTTPException) as e:
                await trigger_knowledge_sync(req, authorized=True)
        assert e.value.status_code == 400
        assert e.value.detail["error"]["code"] == "MISSING_CONTENT"

    @pytest.mark.asyncio
    async def test_document_created_success(self):
        pipeline = MagicMock()
        pipeline.process_document = AsyncMock(return_value="doc_1")
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="document_created", content="hello")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True
        assert result["data"]["document_id"] == "doc_1"

    @pytest.mark.asyncio
    async def test_document_updated_missing_resource_id(self):
        pipeline = MagicMock()
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="document_updated", content="x")
            with pytest.raises(HTTPException) as e:
                await trigger_knowledge_sync(req, authorized=True)
        assert e.value.detail["error"]["code"] == "MISSING_RESOURCE_ID"

    @pytest.mark.asyncio
    async def test_document_updated_success(self):
        pipeline = MagicMock()
        pipeline.reindex_document = AsyncMock(return_value=True)
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="document_updated", resource_id="r1", content="new")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_document_deleted_success(self):
        pipeline = MagicMock()
        pipeline.delete_document = AsyncMock(return_value=True)
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="document_deleted", resource_id="r1")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_product_updated_with_content(self):
        pipeline = MagicMock()
        pipeline.process_document = AsyncMock(return_value="p_1")
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="product_updated", resource_id="p1", content="desc")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True
        assert result["data"]["document_id"] == "p_1"

    @pytest.mark.asyncio
    async def test_product_updated_without_content(self):
        pipeline = MagicMock()
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="product_updated", resource_id="p1")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True
        assert result["data"]["message"] == "Product sync noted (no content provided)"

    @pytest.mark.asyncio
    async def test_full_sync(self):
        pipeline = MagicMock()
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="full_sync")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True
        assert "Full sync task queued" in result["data"]["message"]

    @pytest.mark.asyncio
    async def test_unknown_type_ignored(self):
        pipeline = MagicMock()
        with _install_rag(AsyncMock(return_value=pipeline)):
            req = KnowledgeSyncRequest(tenant_id=1, type="bogus")
            result = await trigger_knowledge_sync(req, authorized=True)
        assert result["success"] is True
        assert "ignored" in result["data"]["message"]

    @pytest.mark.asyncio
    async def test_sync_error_500(self):
        async def boom():
            raise RuntimeError("db down")
        with _install_rag(boom):
            req = KnowledgeSyncRequest(tenant_id=1, type="full_sync")
            with pytest.raises(HTTPException) as e:
                await trigger_knowledge_sync(req, authorized=True)
        assert e.value.status_code == 500
        assert e.value.detail["error"]["code"] == "SYNC_ERROR"


class TestGetKnowledgeStats:
    @pytest.mark.asyncio
    async def test_rag_disabled(self):
        result = await get_knowledge_stats(tenant_id=1, authorized=True)
        assert result["success"] is False
        assert result["error"]["code"] == "RAG_DISABLED"

    @pytest.mark.asyncio
    async def test_success(self):
        pipeline = MagicMock()
        pipeline.get_stats = AsyncMock(return_value={"docs": 3})
        with _install_rag(AsyncMock(return_value=pipeline)):
            result = await get_knowledge_stats(tenant_id=1, authorized=True)
        assert result["success"] is True
        assert result["data"]["docs"] == 3


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
