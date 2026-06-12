"""
AI 智能客服系统 - 知识库管理 Tool

管理知识库文档，支持查询文档列表、上传文档、删除文档、触发向量化、查看分块、测试检索、批量同步。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "upload", "delete", "embed", "chunks", "test_search", "batch_sync"}

# 文档类型
VALID_DOC_TYPES = {"faq", "product", "policy", "guide", "other"}

# 同步模式
VALID_SYNC_MODES = {"full", "incremental"}


class KnowledgeManageTool(BaseTool):
    """知识库管理 Tool

    管理知识库文档：查询列表、上传文档、删除文档、触发向量化、查看分块、测试检索、批量同步。

    使用场景：
    - 查询知识库文档列表
    - 上传新的知识库文档（管理元数据）
    - 删除已有文档
    - 触发文档向量化
    - 查看文档分块结果
    - 测试知识库检索效果
    - 批量同步商品数据到知识库
    """

    name = "knowledge_manage"
    description = (
        "知识库管理工具，支持查询知识库文档列表、上传文档元数据、删除文档、触发向量化、"
        "查看文档分块结果、测试检索效果、批量同步商品数据到知识库。"
        "当需要管理AI客服的知识库内容时使用。"
    )

    allowed_roles = ["admin", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：list（查询文档列表）/ upload（上传文档元数据）/ delete（删除文档）/ "
                    "embed（触发向量化）/ chunks（查看分块）/ test_search（测试检索）/ batch_sync（批量同步）"
                ),
                "enum": ["list", "upload", "delete", "embed", "chunks", "test_search", "batch_sync"],
            },
            "document_id": {
                "type": "string",
                "description": "文档 ID（delete/embed/chunks 时必填）",
            },
            "name": {
                "type": "string",
                "description": "文档名称（upload 时必填）",
            },
            "doc_type": {
                "type": "string",
                "description": "文档类型：faq（常见问题）/ product（商品）/ policy（政策）/ guide（指南）/ other（其他）",
                "enum": ["faq", "product", "policy", "guide", "other"],
            },
            "description": {
                "type": "string",
                "description": "文档描述（upload 时可选）",
            },
            "query": {
                "type": "string",
                "description": "检索查询文本（test_search 时必填）",
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量（test_search 时可选，默认 5）",
                "default": 5,
            },
            "sync_mode": {
                "type": "string",
                "description": "同步模式：full（全量）/ incremental（增量）",
                "enum": ["full", "incremental"],
            },
            "product_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "指定同步的商品 ID 列表（batch_sync 时可选，不填则按 sync_mode 同步全部）",
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词（list 时可选）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        document_id: Optional[str] = None,
        name: Optional[str] = None,
        doc_type: Optional[str] = None,
        description: Optional[str] = None,
        query: Optional[str] = None,
        top_k: int = 5,
        sync_mode: Optional[str] = None,
        product_ids: Optional[List[str]] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行知识库管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行知识库管理操作",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "list":
                return await self._list_documents(context, page, size, keyword, doc_type)
            elif action == "upload":
                return await self._upload_document(context, name, doc_type, description)
            elif action == "delete":
                return await self._delete_document(context, document_id)
            elif action == "embed":
                return await self._embed_document(context, document_id)
            elif action == "chunks":
                return await self._get_chunks(context, document_id)
            elif action == "test_search":
                return await self._test_search(context, query, top_k)
            elif action == "batch_sync":
                return await self._batch_sync(context, sync_mode, product_ids)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"Knowledge manage error: action={action}, error={e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="知识库操作失败，请稍后重试",
            )

    async def _list_documents(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
        doc_type: Optional[str],
    ) -> ToolResult:
        """查询知识库文档列表"""
        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        if doc_type:
            params["type"] = doc_type

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/knowledge/documents",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询知识库文档列表失败：{error_msg}",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"Knowledge documents list: page={page}, size={size}, total={total}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 篇知识库文档",
        )

    async def _upload_document(
        self,
        context: ToolContext,
        name: Optional[str],
        doc_type: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """上传文档元数据"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少文档名称",
                message="上传文档时必须提供文档名称（name）",
            )

        if not doc_type:
            return ToolResult(
                success=False,
                error="缺少文档类型",
                message="上传文档时必须提供文档类型（doc_type）",
            )

        if doc_type not in VALID_DOC_TYPES:
            return ToolResult(
                success=False,
                error=f"无效的文档类型: {doc_type}",
                message=f"不支持的文档类型，可选：{', '.join(VALID_DOC_TYPES)}",
            )

        json_data: Dict[str, Any] = {
            "name": name,
            "type": doc_type,
        }
        if description:
            json_data["description"] = description

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/knowledge/documents",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "上传失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"上传文档失败：{error_msg}",
            )

        data = response.get("data", {})
        doc_id = data.get("id", "")

        logger.info(
            f"Knowledge document uploaded: doc_id={doc_id}, name={name}, "
            f"type={doc_type}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"文档「{name}」已上传，文档 ID：{doc_id}",
        )

    async def _delete_document(
        self,
        context: ToolContext,
        document_id: Optional[str],
    ) -> ToolResult:
        """删除文档"""
        if not document_id:
            return ToolResult(
                success=False,
                error="缺少文档 ID",
                message="删除文档时必须提供文档 ID（document_id）",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/knowledge/documents/{document_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除文档失败：{error_msg}",
            )

        logger.info(
            f"Knowledge document deleted: doc_id={document_id}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"document_id": document_id},
            message=f"文档已删除",
        )

    async def _embed_document(
        self,
        context: ToolContext,
        document_id: Optional[str],
    ) -> ToolResult:
        """触发文档向量化"""
        if not document_id:
            return ToolResult(
                success=False,
                error="缺少文档 ID",
                message="触发向量化时必须提供文档 ID（document_id）",
            )

        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/knowledge/documents/{document_id}/embed",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "向量化失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"触发向量化失败：{error_msg}",
            )

        logger.info(
            f"Knowledge document embed triggered: doc_id={document_id}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"document_id": document_id, "status": "embedding"},
            message=f"文档向量化任务已触发，请稍后查看结果",
        )

    async def _get_chunks(
        self,
        context: ToolContext,
        document_id: Optional[str],
    ) -> ToolResult:
        """查看文档分块结果"""
        if not document_id:
            return ToolResult(
                success=False,
                error="缺少文档 ID",
                message="查看分块时必须提供文档 ID（document_id）",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/knowledge/documents/{document_id}/chunks",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查看文档分块失败：{error_msg}",
            )

        data = response.get("data", {})
        chunks = data.get("chunks", [])

        logger.info(
            f"Knowledge document chunks: doc_id={document_id}, "
            f"chunk_count={len(chunks)}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"document_id": document_id, "chunks": chunks, "count": len(chunks)},
            message=f"文档共 {len(chunks)} 个分块",
        )

    async def _test_search(
        self,
        context: ToolContext,
        query: Optional[str],
        top_k: int,
    ) -> ToolResult:
        """测试知识库检索"""
        if not query:
            return ToolResult(
                success=False,
                error="缺少查询文本",
                message="测试检索时必须提供查询文本（query）",
            )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/knowledge/test-search",
            json_data={"query": query, "topK": top_k},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "检索失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"测试检索失败：{error_msg}",
            )

        data = response.get("data", {})
        results = data.get("results", [])

        logger.info(
            f"Knowledge test search: query='{query}', top_k={top_k}, "
            f"results={len(results)}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"query": query, "results": results, "count": len(results)},
            message=f"检索到 {len(results)} 条相关结果",
        )

    async def _batch_sync(
        self,
        context: ToolContext,
        sync_mode: Optional[str],
        product_ids: Optional[List[str]],
    ) -> ToolResult:
        """批量同步商品数据到知识库"""
        if not sync_mode:
            return ToolResult(
                success=False,
                error="缺少同步模式",
                message="批量同步时必须提供同步模式（sync_mode）：full（全量）或 incremental（增量）",
            )

        if sync_mode not in VALID_SYNC_MODES:
            return ToolResult(
                success=False,
                error=f"无效的同步模式: {sync_mode}",
                message=f"不支持的同步模式，可选：{', '.join(VALID_SYNC_MODES)}",
            )

        json_data: Dict[str, Any] = {"syncMode": sync_mode}
        if product_ids:
            json_data["productIds"] = product_ids

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/knowledge/batch-sync",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "同步失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"批量同步失败：{error_msg}",
            )

        data = response.get("data", {})
        synced_count = data.get("syncedCount", 0)

        logger.info(
            f"Knowledge batch sync: mode={sync_mode}, synced={synced_count}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"批量同步已完成，共同步 {synced_count} 条数据",
        )
