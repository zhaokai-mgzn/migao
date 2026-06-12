"""
AI 智能客服系统 - 知识库搜索 Tool

从知识库中检索相关信息，用于回答产品FAQ、尺寸指南等问题。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult

# RAG 模块可能尚未完成（Task #7），使用延迟导入
try:
    from app.rag import search_knowledge, HybridSearchResult
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False
    logger.warning("RAG module not available, knowledge_search will use fallback")


class KnowledgeSearchTool(BaseTool):
    """知识库搜索 Tool
    
    从知识库中检索相关信息，用于回答产品FAQ、尺寸指南、面料知识等问题。
    
    使用场景：
    - 用户询问面料特性（如"雪尼尔面料会不会起球"）
    - 用户询问保养方法（如"窗帘怎么清洗"）
    - 用户询问安装指南（如"打孔窗帘怎么安装"）
    - 用户询问加工费标准（如"打孔加工多少钱"）
    - 用户询问售后政策（如"退换货有什么要求"）
    
    注意：不用于查询订单、商品列表等，这些有专门的 Tool。
    """
    
    name = "knowledge_search"
    description = (
        "从知识库中检索相关信息，用于回答产品FAQ、尺寸指南、面料知识、"
        "保养方法、安装指南、加工费标准、售后政策等专业问题。"
        "当用户询问专业知识时使用，不要用于查询订单或商品列表。"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "查询内容，如'雪尼尔面料怎么清洗'或'打孔加工多少钱'",
            },
            "doc_type": {
                "type": "string",
                "description": "文档类型过滤（可选），用于缩小检索范围",
                "enum": [
                    "product_info",
                    "faq",
                    "processing_guide",
                    "installation",
                    "maintenance",
                    "fabric_knowledge",
                    "policy",
                ],
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量，默认 3",
                "default": 3,
            },
        },
        "required": ["query"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        query: str,
        doc_type: Optional[str] = None,
        top_k: int = 3,
    ) -> ToolResult:
        """执行知识库搜索
        
        Args:
            context: Tool 执行上下文
            query: 查询内容
            doc_type: 文档类型过滤
            top_k: 返回结果数量
            
        Returns:
            ToolResult: 检索结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限搜索知识库",
            )
        
        if not query or not query.strip():
            return ToolResult(
                success=False,
                error="查询内容为空",
                message="请提供查询内容",
            )
        
        # 确保 top_k 为整数（LLM tool calling 可能传入字符串）
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 3
        
        try:
            # 搜索请求日志
            logger.info(f"[knowledge-search] Searching: query='{query}' doc_type={doc_type} | tenant={context.tenant_id}")
            
            # 检查 RAG 是否可用
            if not _RAG_AVAILABLE:
                logger.warning("[knowledge-search] RAG unavailable, using fallback")
                return ToolResult(
                    success=True,
                    data={
                        "chunks": [],
                        "context": "",
                        "source_count": 0,
                    },
                    message="知识库功能暂未开启，建议您联系人工客服获取专业解答。",
                )
            
            # 构建过滤条件
            filters: Dict[str, Any] = {}
            if doc_type:
                filters["doc_type"] = doc_type
            
            # 调用 RAG 混合检索
            results: List[HybridSearchResult] = await search_knowledge(
                query=query,
                tenant_id=context.tenant_id,
                top_k=top_k,
                filters=filters if filters else None,
            )
            
            logger.info(
                f"[knowledge-search] Found {len(results)} results | tenant={context.tenant_id}"
            )
            
            if not results:
                return ToolResult(
                    success=True,
                    data={
                        "chunks": [],
                        "context": "",
                        "source_count": 0,
                    },
                    message="抱歉，暂时没有相关的资料。建议您转人工客服进一步咨询。",
                )
            
            # 格式化检索结果
            chunks = self._format_chunks(results)
            context_text = self._build_context(results)
            
            return ToolResult(
                success=True,
                data={
                    "chunks": chunks,
                    "context": context_text,
                    "source_count": len(chunks),
                },
                message=f"找到 {len(chunks)} 条相关资料",
            )
            
        except Exception as e:
            logger.error(f"[knowledge-search] Search failed | tenant={context.tenant_id} error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="知识库检索失败，请稍后重试",
            )
    
    def _format_chunks(self, results: List[HybridSearchResult]) -> List[Dict[str, Any]]:
        """格式化检索结果
        
        Args:
            results: 混合检索结果列表
            
        Returns:
            List: 格式化后的结果列表
        """
        chunks = []
        for i, result in enumerate(results, 1):
            chunk = {
                "index": i,
                "chunk_id": result.chunk_id,
                "content": result.content,
                "score": result.score,
                "vector_score": result.vector_score,
                "bm25_score": result.bm25_score,
                "metadata": result.metadata,
                "source": result.metadata.get("doc_type", "unknown"),
            }
            chunks.append(chunk)
        
        return chunks
    
    def _build_context(self, results: List[HybridSearchResult]) -> str:
        """构建上下文文本（供 LLM 使用）
        
        Args:
            results: 混合检索结果列表
            
        Returns:
            str: 格式化的上下文文本
        """
        context_parts = []
        
        for i, result in enumerate(results, 1):
            source = result.metadata.get("doc_type", "unknown")
            title = result.metadata.get("title", "")
            
            part = f"[资料{i}]"
            if title:
                part += f"（来源：{title}）"
            elif source:
                part += f"（来源：{source}）"
            part += f"\n{result.content}"
            
            context_parts.append(part)
        
        return "\n\n".join(context_parts)
