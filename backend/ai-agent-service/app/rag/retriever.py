"""
AI 智能客服系统 - 混合检索器

融合向量检索和 BM25 关键词检索：
1. 并行执行向量检索和 BM25 检索
2. 使用 RRF (Reciprocal Rank Fusion) 融合排序
3. 返回 Top-K 结果

RRF 公式：score = sum(1 / (k + rank_i))，其中 k=60
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from loguru import logger

from app.rag.vector_store import VectorStore, get_vector_store
from app.rag.bm25_retriever import BM25Retriever, get_bm25_retriever
from app.config import settings


@dataclass
class HybridSearchResult:
    """混合检索结果"""
    chunk_id: str
    content: str
    score: float                      # RRF 融合分数
    vector_score: Optional[float] = None   # 向量检索分数
    bm25_score: Optional[float] = None     # BM25 分数
    vector_rank: Optional[int] = None      # 向量检索排名
    bm25_rank: Optional[int] = None        # BM25 排名
    metadata: Dict[str, Any] = field(default_factory=dict)


class HybridRetriever:
    """混合检索器：向量 + BM25 + RRF 融合
    
    结合向量检索的语义理解能力和 BM25 的精确关键词匹配能力，
    通过 RRF (Reciprocal Rank Fusion) 算法融合两种检索结果，
    提升整体检索效果。
    
    RRF 优势：
    - 不需要对两种检索的分数进行归一化
    - 对排名位置敏感，对绝对分数不敏感
    - 在多个检索结果中找到共识
    """
    
    # RRF 常数，通常取 60
    RRF_K = 60
    
    # 默认权重
    DEFAULT_VECTOR_WEIGHT = 1.0
    DEFAULT_BM25_WEIGHT = 1.0
    
    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        bm25_retriever: Optional[BM25Retriever] = None,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
        rrf_k: int = RRF_K,
    ):
        """
        初始化混合检索器
        
        Args:
            vector_store: VectorStore 实例
            bm25_retriever: BM25Retriever 实例
            vector_weight: 向量检索结果权重
            bm25_weight: BM25 检索结果权重
            rrf_k: RRF 常数
        """
        self.vector_store = vector_store
        self.bm25_retriever = bm25_retriever
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.rrf_k = rrf_k
    
    async def _ensure_components(self):
        """确保检索组件已初始化"""
        if self.vector_store is None:
            self.vector_store = await get_vector_store()
        
        if self.bm25_retriever is None:
            self.bm25_retriever = await get_bm25_retriever()
    
    async def search(
        self,
        query: str,
        tenant_id: int,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        use_vector: bool = True,
        use_bm25: bool = True,
    ) -> List[HybridSearchResult]:
        """
        混合检索
        
        Args:
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回结果数
            filters: 过滤条件
            use_vector: 是否使用向量检索
            use_bm25: 是否使用 BM25 检索
            
        Returns:
            按 RRF 分数排序的检索结果列表
        """
        if not query or not query.strip():
            logger.warning("Empty query provided to hybrid search")
            return []
        
        # 防御性类型转换：确保 top_k 为整数
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 5
        
        await self._ensure_components()
        
        # 准备并行检索任务
        tasks = []
        task_types = []
        
        # 使用配置的 RETRIEVAL_TOP_K 作为初始检索候选数
        retrieval_top_k = max(top_k * 2, settings.RETRIEVAL_TOP_K)
        
        if use_vector and self.vector_store:
            tasks.append(self._vector_search(query, tenant_id, retrieval_top_k, filters))
            task_types.append("vector")
        
        if use_bm25 and self.bm25_retriever:
            tasks.append(self._bm25_search(query, tenant_id, retrieval_top_k, filters))
            task_types.append("bm25")
        
        if not tasks:
            logger.warning("No search methods enabled")
            return []
        
        # 并行执行检索
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Parallel search failed: {e}")
            results = []
        
        # 解析结果
        vector_results = []
        bm25_results = []
        
        for i, (task_type, result) in enumerate(zip(task_types, results)):
            if isinstance(result, Exception):
                logger.error(f"{task_type} search failed: {result}")
            elif task_type == "vector":
                vector_results = result
            elif task_type == "bm25":
                bm25_results = result
        
        logger.info(
            f"Hybrid search: vector={len(vector_results)}, bm25={len(bm25_results)}"
        )
        
        # 使用 RRF 融合结果
        fused_results = self._reciprocal_rank_fusion(
            vector_results,
            bm25_results,
        )
        
        # 返回 Top-K
        return fused_results[:top_k]
    
    async def _vector_search(
        self,
        query: str,
        tenant_id: int,
        top_k: int,
        filters: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """执行向量检索"""
        try:
            results = await self.vector_store.search(
                query=query,
                tenant_id=tenant_id,
                top_k=top_k,
                filters=filters,
            )
            return [
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
    
    async def _bm25_search(
        self,
        query: str,
        tenant_id: int,
        top_k: int,
        filters: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """执行 BM25 检索"""
        try:
            results = await self.bm25_retriever.search(
                query=query,
                tenant_id=tenant_id,
                top_k=top_k,
                filters=filters,
            )
            return [
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []
    
    def _reciprocal_rank_fusion(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
    ) -> List[HybridSearchResult]:
        """
        使用 RRF (Reciprocal Rank Fusion) 融合两种检索结果
        
        RRF 公式：score = sum(weight_i / (k + rank_i))
        
        Args:
            vector_results: 向量检索结果列表
            bm25_results: BM25 检索结果列表
            
        Returns:
            融合后的结果列表（按分数降序）
        """
        # 构建 chunk_id -> 结果信息的映射
        result_map: Dict[str, Dict[str, Any]] = {}
        
        # 处理向量检索结果
        for rank, result in enumerate(vector_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id not in result_map:
                result_map[chunk_id] = {
                    "content": result["content"],
                    "metadata": result.get("metadata", {}),
                    "vector_score": result.get("score"),
                    "vector_rank": rank,
                    "bm25_score": None,
                    "bm25_rank": None,
                    "rrf_score": 0.0,
                }
            
            # 计算 RRF 分数贡献
            rrf_contribution = self.vector_weight / (self.rrf_k + rank)
            result_map[chunk_id]["rrf_score"] += rrf_contribution
        
        # 处理 BM25 检索结果
        for rank, result in enumerate(bm25_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id in result_map:
                # 已存在，更新 BM25 信息
                result_map[chunk_id]["bm25_score"] = result.get("score")
                result_map[chunk_id]["bm25_rank"] = rank
            else:
                # 新结果
                result_map[chunk_id] = {
                    "content": result["content"],
                    "metadata": result.get("metadata", {}),
                    "vector_score": None,
                    "vector_rank": None,
                    "bm25_score": result.get("score"),
                    "bm25_rank": rank,
                    "rrf_score": 0.0,
                }
            
            # 计算 RRF 分数贡献
            rrf_contribution = self.bm25_weight / (self.rrf_k + rank)
            result_map[chunk_id]["rrf_score"] += rrf_contribution
        
        # 转换为 HybridSearchResult 列表并排序
        fused_results = []
        for chunk_id, info in result_map.items():
            fused_results.append(HybridSearchResult(
                chunk_id=chunk_id,
                content=info["content"],
                score=info["rrf_score"],
                vector_score=info["vector_score"],
                bm25_score=info["bm25_score"],
                vector_rank=info["vector_rank"],
                bm25_rank=info["bm25_rank"],
                metadata=info["metadata"],
            ))
        
        # 按 RRF 分数降序排序
        fused_results.sort(key=lambda x: x.score, reverse=True)
        
        return fused_results
    
    async def search_with_fallback(
        self,
        query: str,
        tenant_id: int,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[HybridSearchResult]:
        """
        带降级处理的混合检索
        
        如果向量检索失败，只使用 BM25；
        如果 BM25 失败，只使用向量检索；
        如果都失败，返回空结果。
        
        Args:
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回结果数
            filters: 过滤条件
            
        Returns:
            检索结果列表
        """
        await self._ensure_components()
        
        # 检查各组件可用性
        vector_available = (
            self.vector_store and 
            self.vector_store._available
        )
        bm25_available = (
            self.bm25_retriever is not None and
            self.bm25_retriever._available
        )
        
        if not vector_available and not bm25_available:
            logger.error("No search methods available")
            return []
        
        # 执行检索
        results = await self.search(
            query=query,
            tenant_id=tenant_id,
            top_k=top_k,
            filters=filters,
            use_vector=vector_available,
            use_bm25=bm25_available,
        )
        
        # 如果混合检索没有结果，尝试单独使用可用的方法
        if not results:
            if vector_available:
                logger.info("Trying vector search only")
                vector_results = await self._vector_search(
                    query, tenant_id, top_k, filters
                )
                return [
                    HybridSearchResult(
                        chunk_id=r["chunk_id"],
                        content=r["content"],
                        score=r["score"],
                        vector_score=r["score"],
                        vector_rank=i + 1,
                        metadata=r.get("metadata", {}),
                    )
                    for i, r in enumerate(vector_results)
                ]
            
            if bm25_available:
                logger.info("Trying BM25 search only")
                bm25_results = await self._bm25_search(
                    query, tenant_id, top_k, filters
                )
                return [
                    HybridSearchResult(
                        chunk_id=r["chunk_id"],
                        content=r["content"],
                        score=r["score"],
                        bm25_score=r["score"],
                        bm25_rank=i + 1,
                        metadata=r.get("metadata", {}),
                    )
                    for i, r in enumerate(bm25_results)
                ]
        
        return results


# 全局 HybridRetriever 实例
_hybrid_retriever: Optional[HybridRetriever] = None


async def get_hybrid_retriever() -> HybridRetriever:
    """获取 HybridRetriever 实例（单例模式）"""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = HybridRetriever()
    return _hybrid_retriever


def reset_hybrid_retriever():
    """重置 HybridRetriever 实例（用于测试）"""
    global _hybrid_retriever
    _hybrid_retriever = None


# 便捷函数
async def hybrid_search(
    query: str,
    tenant_id: int,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
) -> List[HybridSearchResult]:
    """
    便捷的混合检索函数
    
    Args:
        query: 查询文本
        tenant_id: 租户 ID
        top_k: 返回结果数
        filters: 过滤条件
        
    Returns:
        混合检索结果列表
    """
    retriever = await get_hybrid_retriever()
    return await retriever.search_with_fallback(query, tenant_id, top_k, filters)
