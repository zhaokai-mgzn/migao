"""
AI 智能客服系统 - BM25 关键词检索器

基于 PostgreSQL 全文搜索实现 BM25 检索：
- 使用 to_tsvector('chinese', content) 创建中文全文索引
- 使用 plainto_tsquery 解析查询
- 使用 ts_rank 计算相关性分数
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.database import AsyncSessionLocal


@dataclass
class BM25SearchResult:
    """BM25 检索结果"""
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any]


class BM25Retriever:
    """基于 PostgreSQL 全文搜索的 BM25 检索器
    
    使用 PostgreSQL 的 tsvector 和 ts_rank 实现中文全文检索，
    作为向量检索的补充，在精确关键词匹配场景下效果更好。
    
    依赖：
    - PostgreSQL 需要安装 zhparser 扩展支持中文分词
    - rag_chunks 表需要创建 search_vector 字段和 GIN 索引
    """
    
    def __init__(self):
        """初始化 BM25 检索器"""
        self._available = False  # 默认不可用，需要显式检查
        self._availability_checked = False
    
    def _build_search_query(
        self,
        query: str,
        tenant_id: int,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> tuple:
        """
        构建全文搜索 SQL 查询
        
        Args:
            query: 搜索查询
            tenant_id: 租户 ID
            filters: 过滤条件
            top_k: 返回结果数
            
        Returns:
            (sql_string, params_dict)
        """
        # 基础查询
        sql_parts = [
            "SELECT",
            "    chunk_id,",
            "    content,",
            "    ts_rank(search_vector, plainto_tsquery('chinese', :query)) as rank_score,",
            "    metadata,",
            "    document_id,",
            "    chunk_index",
            "FROM rag_chunks",
            "WHERE tenant_id = :tenant_id",
            "    AND search_vector @@ plainto_tsquery('chinese', :query)",
        ]
        
        params = {
            "query": query,
            "tenant_id": tenant_id,
            "top_k": top_k,
        }
        
        # 添加过滤条件
        if filters:
            if filters.get("doc_type"):
                sql_parts.append("    AND metadata->>'doc_type' = :doc_type")
                params["doc_type"] = filters["doc_type"]
            
            if filters.get("category"):
                sql_parts.append("    AND metadata->>'category' = :category")
                params["category"] = filters["category"]
            
            if filters.get("product_id"):
                sql_parts.append("    AND metadata->>'product_id' = :product_id")
                params["product_id"] = filters["product_id"]
            
            if filters.get("document_id"):
                sql_parts.append("    AND document_id = :document_id")
                params["document_id"] = filters["document_id"]
        
        # 排序和限制
        sql_parts.extend([
            "ORDER BY rank_score DESC",
            "LIMIT :top_k",
        ])
        
        sql = "\n".join(sql_parts)
        return sql, params
    
    async def ensure_availability_checked(self):
        """确保可用性已检查（只检查一次）"""
        if not self._availability_checked:
            self._available = await self.check_availability()
            self._availability_checked = True
            if not self._available:
                logger.warning(
                    "BM25 retriever is not available (search_vector column or zhparser extension missing). "
                    "Falling back to vector-only search."
                )

    async def search(
        self,
        query: str,
        tenant_id: int,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[BM25SearchResult]:
        """
        使用 PostgreSQL ts_rank 进行全文搜索
        
        Args:
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回结果数
            filters: 过滤条件（如 {"doc_type": "faq", "category": "curtain"}）
            
        Returns:
            BM25 检索结果列表
        """
        if not query or not query.strip():
            logger.warning("Empty query provided to BM25 search")
            return []
        
        if not tenant_id:
            logger.warning("Empty tenant_id provided to BM25 search")
            return []
        
        # 检查 BM25 是否可用，不可用则静默返回空结果
        await self.ensure_availability_checked()
        if not self._available:
            return []
        
        try:
            sql, params = self._build_search_query(query, tenant_id, filters, top_k)
            
            async with AsyncSessionLocal() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                
                search_results = []
                for row in rows:
                    metadata = row.metadata if row.metadata else {}
                    # 添加额外元数据
                    metadata.update({
                        "document_id": row.document_id,
                        "chunk_index": row.chunk_index,
                        "tenant_id": tenant_id,
                    })
                    
                    search_results.append(BM25SearchResult(
                        chunk_id=row.chunk_id,
                        content=row.content,
                        score=float(row.rank_score),
                        metadata=metadata,
                    ))
                
                logger.info(f"BM25 search returned {len(search_results)} results")
                return search_results
                
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            # 返回空结果而不是抛出异常，保证系统可用性
            return []
    
    async def search_with_session(
        self,
        session: AsyncSession,
        query: str,
        tenant_id: int,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[BM25SearchResult]:
        """
        使用指定的数据库会话进行全文搜索
        
        用于在事务中执行搜索，与其他数据库操作保持一致性。
        
        Args:
            session: SQLAlchemy 异步会话
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回结果数
            filters: 过滤条件
            
        Returns:
            BM25 检索结果列表
        """
        if not query or not query.strip():
            return []
        
        if not tenant_id:
            return []
        
        try:
            sql, params = self._build_search_query(query, tenant_id, filters, top_k)
            
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            
            search_results = []
            for row in rows:
                metadata = row.metadata if row.metadata else {}
                metadata.update({
                    "document_id": row.document_id,
                    "chunk_index": row.chunk_index,
                    "tenant_id": tenant_id,
                })
                
                search_results.append(BM25SearchResult(
                    chunk_id=row.chunk_id,
                    content=row.content,
                    score=float(row.rank_score),
                    metadata=metadata,
                ))
            
            return search_results
            
        except Exception as e:
            logger.error(f"BM25 search with session failed: {e}")
            return []
    
    async def check_availability(self) -> bool:
        """
        检查 BM25 检索是否可用
        
        检查 PostgreSQL 是否安装了中文全文检索扩展
        """
        try:
            async with AsyncSessionLocal() as session:
                # 检查 zhparser 扩展
                result = await session.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'zhparser')")
                )
                has_zhparser = result.scalar()
                
                if not has_zhparser:
                    logger.warning("PostgreSQL zhparser extension not installed")
                    return False
                
                # 检查 rag_chunks 表是否存在
                result = await session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'rag_chunks'
                        )
                    """)
                )
                has_table = result.scalar()
                
                if not has_table:
                    logger.warning("rag_chunks table not found")
                    return False
                
                # 检查 search_vector 字段是否存在
                result = await session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_name = 'rag_chunks' AND column_name = 'search_vector'
                        )
                    """)
                )
                has_search_vector = result.scalar()
                
                if not has_search_vector:
                    logger.warning("search_vector column not found in rag_chunks")
                    return False
                
                logger.info("BM25 retriever is available")
                return True
                
        except Exception as e:
            logger.error(f"BM25 availability check failed: {e}")
            return False
    
    async def get_stats(self, tenant_id: int) -> Dict[str, Any]:
        """
        获取 BM25 检索统计信息
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            统计信息字典
        """
        try:
            async with AsyncSessionLocal() as session:
                # 获取该租户的分块总数
                result = await session.execute(
                    text("SELECT COUNT(*) FROM rag_chunks WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id}
                )
                total_chunks = result.scalar()
                
                # 获取文档类型分布
                result = await session.execute(
                    text("""
                        SELECT 
                            metadata->>'doc_type' as doc_type,
                            COUNT(*) as count
                        FROM rag_chunks
                        WHERE tenant_id = :tenant_id
                        GROUP BY metadata->>'doc_type'
                    """),
                    {"tenant_id": tenant_id}
                )
                doc_type_dist = {row.doc_type or "unknown": row.count for row in result}
                
                return {
                    "total_chunks": total_chunks,
                    "doc_type_distribution": doc_type_dist,
                    "available": True,
                }
                
        except Exception as e:
            logger.error(f"Failed to get BM25 stats: {e}")
            return {
                "total_chunks": 0,
                "doc_type_distribution": {},
                "available": False,
                "error": str(e),
            }


# 全局 BM25Retriever 实例
_bm25_retriever: Optional[BM25Retriever] = None


async def get_bm25_retriever() -> BM25Retriever:
    """获取 BM25Retriever 实例（单例模式）"""
    global _bm25_retriever
    if _bm25_retriever is None:
        _bm25_retriever = BM25Retriever()
        await _bm25_retriever.ensure_availability_checked()
    return _bm25_retriever


def reset_bm25_retriever():
    """重置 BM25Retriever 实例（用于测试）"""
    global _bm25_retriever
    _bm25_retriever = None
