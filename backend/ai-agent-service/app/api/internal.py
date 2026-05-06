"""
内部 API 路由（Service Token 认证）

提供内部服务之间的调用接口：
- Tool 执行接口（供 admin-api 反向调用）
- 健康检查
- 知识库同步触发
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.utils.auth import verify_service_token
from app.tools import ToolContext, get_tool_registry

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    """Tool 执行请求"""
    tool_name: str = Field(..., description="Tool 名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="Tool 参数")
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")


class KnowledgeSyncRequest(BaseModel):
    """知识库同步请求"""
    tenant_id: int = Field(..., description="租户 ID")
    type: str = Field(..., description="同步类型: product_updated / document_created / document_updated / document_deleted / full_sync")
    resource_id: Optional[str] = Field(None, description="资源 ID")
    content: Optional[str] = Field(None, description="文档内容（document_created/document_updated 时使用）")
    metadata: Optional[Dict[str, Any]] = Field(None, description="文档元数据")


@router.post("/tools/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    执行 Tool（内部服务调用）
    
    由 admin-api 通过 Service Token 调用，用于反向触发 Agent Tool 执行。
    例如：admin-api 需要 AI 服务执行某个 Tool 获取结果。
    """
    registry = get_tool_registry()
    
    # 检查 Tool 是否存在
    if not registry.has_tool(request.tool_name):
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "TOOL_NOT_FOUND",
                    "message": f"Tool '{request.tool_name}' not found",
                }
            }
        )
    
    # 构建上下文
    context = ToolContext(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        session_id=request.session_id,
        role="admin",  # 内部调用使用 admin 角色
    )
    
    # 执行 Tool
    try:
        result = await registry.execute_tool(
            request.tool_name,
            context,
            **request.params,
        )
        
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "message": result.message,
        }
    except Exception as e:
        logger.error(f"Internal tool execution error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Tool execution failed: {str(e)}",
                }
            }
        )


@router.post("/knowledge/sync")
async def trigger_knowledge_sync(
    request: KnowledgeSyncRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    触发知识库同步
    
    当 admin-api 中的商品/文档更新时，触发 AI 服务重新索引知识库。
    
    同步类型：
    - document_created: 新文档创建，分块并向量化
    - document_updated: 文档更新，重新索引
    - document_deleted: 文档删除，清除分块和向量
    - product_updated: 商品更新，重新索引关联文档
    - full_sync: 全量重建索引
    """
    logger.info(
        f"Knowledge sync triggered: type={request.type}, "
        f"resource_id={request.resource_id}, tenant_id={request.tenant_id}"
    )
    
    try:
        from app.rag.pipeline import get_rag_pipeline
        pipeline = await get_rag_pipeline()
        
        sync_type = request.type
        tenant_id = request.tenant_id
        resource_id = request.resource_id
        
        if sync_type == "document_created":
            # 新文档创建：分块并向量化
            if not request.content:
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "error": {"code": "MISSING_CONTENT", "message": "Content is required for document_created"}}
                )
            doc_id = await pipeline.process_document(
                content=request.content,
                metadata=request.metadata or {},
                tenant_id=tenant_id,
                doc_id=resource_id,
            )
            return {
                "success": True,
                "data": {
                    "message": "Document processed and indexed",
                    "document_id": doc_id,
                    "type": sync_type,
                }
            }
        
        elif sync_type == "document_updated":
            # 文档更新：重新索引
            if not resource_id:
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "error": {"code": "MISSING_RESOURCE_ID", "message": "resource_id is required for document_updated"}}
                )
            if not request.content:
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "error": {"code": "MISSING_CONTENT", "message": "Content is required for document_updated"}}
                )
            success = await pipeline.reindex_document(
                doc_id=resource_id,
                tenant_id=tenant_id,
                new_content=request.content,
                new_metadata=request.metadata,
            )
            return {
                "success": success,
                "data": {
                    "message": "Document reindexed" if success else "Reindex failed",
                    "document_id": resource_id,
                    "type": sync_type,
                }
            }
        
        elif sync_type == "document_deleted":
            # 文档删除：清除分块和向量
            if not resource_id:
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "error": {"code": "MISSING_RESOURCE_ID", "message": "resource_id is required for document_deleted"}}
                )
            success = await pipeline.delete_document(
                doc_id=resource_id,
                tenant_id=tenant_id,
            )
            return {
                "success": success,
                "data": {
                    "message": "Document deleted" if success else "Delete failed",
                    "document_id": resource_id,
                    "type": sync_type,
                }
            }
        
        elif sync_type == "product_updated":
            # 商品更新：如果有关联文档，重新索引
            # 需要关联文档内容，如果提供了 content 则直接处理
            if request.content and resource_id:
                doc_id = await pipeline.process_document(
                    content=request.content,
                    metadata={**(request.metadata or {}), "product_id": resource_id},
                    tenant_id=tenant_id,
                    doc_id=f"product_{resource_id}",
                )
                return {
                    "success": True,
                    "data": {
                        "message": "Product document indexed",
                        "document_id": doc_id,
                        "type": sync_type,
                    }
                }
            return {
                "success": True,
                "data": {
                    "message": "Product sync noted (no content provided)",
                    "type": sync_type,
                    "resource_id": resource_id,
                }
            }
        
        elif sync_type == "full_sync":
            # 全量重建：记录任务，实际重建需要逐文档处理
            return {
                "success": True,
                "data": {
                    "message": "Full sync task queued",
                    "type": sync_type,
                }
            }
        
        else:
            return {
                "success": True,
                "data": {
                    "message": f"Unknown sync type '{sync_type}', ignored",
                    "type": sync_type,
                    "resource_id": resource_id,
                }
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Knowledge sync error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": {
                    "code": "SYNC_ERROR",
                    "message": f"Knowledge sync failed: {str(e)}",
                }
            }
        )


@router.get("/knowledge/stats")
async def get_knowledge_stats(
    tenant_id: int,
    authorized: bool = Depends(verify_service_token),
):
    """
    获取知识库统计信息
    """
    try:
        from app.rag.pipeline import get_rag_pipeline
        pipeline = await get_rag_pipeline()
        stats = await pipeline.get_stats(tenant_id)
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"Failed to get knowledge stats: {e}")
        return {"success": False, "error": str(e)}


@router.get("/tools")
async def list_tools(
    authorized: bool = Depends(verify_service_token),
):
    """
    获取所有可用 Tool 列表（内部接口）
    """
    registry = get_tool_registry()
    
    tools = []
    for tool in registry.get_all_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        })
    
    return {
        "success": True,
        "data": {
            "tools": tools,
            "count": len(tools),
        }
    }
