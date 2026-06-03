"""
AI 智能客服系统 - 重排序模块

使用百炼 gte-rerank 模型对检索结果进行重排序，提升 RAG 准确率。

流程：
1. 接收混合检索（BM25 + Vector + RRF）的候选文档
2. 调用百炼 rerank API 计算查询与文档的相关性
3. 按相关性分数重新排序，返回 Top-K 最相关文档

降级策略：如果 rerank API 调用失败，返回原始排序的 Top-K 文档。
"""

from typing import List, Dict, Any, Optional
from loguru import logger

from dashscope import TextReRank

from app.config import settings
from app.llm import DASHSCOPE_API_KEY


class DashScopeReranker:
    """基于百炼 gte-rerank 的重排序器
    
    使用 DashScope TextReRank API 对候选文档进行重排序，
    提升检索结果的相关性和准确率。
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        初始化重排序器
        
        Args:
            model: 重排序模型名称，默认使用配置中的 RERANK_MODEL
            api_key: DashScope API Key，默认使用配置中的 DASHSCOPE_API_KEY
        """
        self.model = model or settings.RERANK_MODEL
        self.api_key = api_key or DASHSCOPE_API_KEY
        self._available = bool(self.api_key)
        
        if not self._available:
            logger.warning("[reranker] DashScope API Key not configured, reranker disabled")
        else:
            logger.info(f"[reranker] Initialized with model={self.model}")
    
    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        对候选文档进行重排序
        
        Args:
            query: 用户查询文本
            documents: 候选文档列表，每个文档需包含 'content' 字段
            top_k: 重排序后返回的文档数
            
        Returns:
            按相关性分数降序排列的 top_k 个文档列表，
            每个文档额外包含 'rerank_score' 字段
        """
        if not documents:
            return []
        
        if not self._available:
            logger.warning("[reranker] Reranker not available, returning original order")
            return documents[:top_k]
        
        # 如果文档数 <= top_k，无需重排序
        if len(documents) <= top_k:
            logger.debug(f"[reranker] Only {len(documents)} docs, skip reranking")
            return documents
        
        try:
            # 提取文档内容用于重排序
            doc_contents = [doc.get("content", "") for doc in documents]
            
            logger.info(
                f"[reranker] Reranking {len(documents)} docs for query='{query[:50]}...'"
            )
            
            # 调用百炼 TextReRank API
            resp = TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_contents,
                top_n=top_k,
                api_key=self.api_key,
            )
            
            # 检查响应状态
            if resp.status_code != 200:
                logger.error(
                    f"[reranker] API call failed: status={resp.status_code} "
                    f"code={resp.code} message={resp.message}"
                )
                return self._fallback(documents, top_k)
            
            # 解析结果
            reranked_results = resp.output.get("results", [])
            if not reranked_results:
                logger.warning("[reranker] Empty results from API, using fallback")
                return self._fallback(documents, top_k)
            
            # 根据 rerank 结果重新排序文档
            reranked_docs = []
            for item in reranked_results:
                idx = item.get("index", 0)
                score = item.get("relevance_score", 0.0)
                
                if 0 <= idx < len(documents):
                    doc = documents[idx].copy()
                    doc["rerank_score"] = score
                    reranked_docs.append(doc)
            
            logger.info(
                f"[reranker] Reranking done: {len(documents)} -> {len(reranked_docs)} docs, "
                f"top_score={reranked_docs[0].get('rerank_score', 0):.4f}" if reranked_docs else ""
            )
            
            return reranked_docs
            
        except Exception as e:
            logger.error(f"[reranker] Reranking failed: {type(e).__name__}: {e}")
            return self._fallback(documents, top_k)
    
    @staticmethod
    def _fallback(
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        降级策略：返回原始排序的 top_k 文档
        
        Args:
            documents: 原始文档列表
            top_k: 返回文档数
            
        Returns:
            原始排序的 top_k 文档
        """
        logger.info(f"[reranker] Fallback: returning top {top_k} from original order")
        return documents[:top_k]


# 全局 DashScopeReranker 实例
_reranker: Optional[DashScopeReranker] = None


async def get_reranker() -> DashScopeReranker:
    """获取 DashScopeReranker 实例（单例模式）"""
    global _reranker
    if _reranker is None:
        _reranker = DashScopeReranker()
    return _reranker


def reset_reranker():
    """重置 DashScopeReranker 实例（用于测试）"""
    global _reranker
    _reranker = None
