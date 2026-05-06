"""
AI 智能客服系统 - RAG 模块

自建 RAG 知识库实现：
- 向量数据库：阿里云 DashVector
- Embedding 模型：text-embedding-v3（百炼）
- 分块策略：布艺行业定制（FabricChunker）
- 检索策略：混合检索（BM25 + 向量 + RRF 融合）

详见文档：docs/rag-architecture.md
"""

# 分块器
from app.rag.chunker import (
    FabricChunker,
    Chunk,
    chunk_document,
)

# 向量存储
from app.rag.vector_store import (
    VectorStore,
    VectorSearchResult,
    get_vector_store,
    reset_vector_store,
)

# BM25 检索器
from app.rag.bm25_retriever import (
    BM25Retriever,
    BM25SearchResult,
    get_bm25_retriever,
    reset_bm25_retriever,
)

# 混合检索器
from app.rag.retriever import (
    HybridRetriever,
    HybridSearchResult,
    get_hybrid_retriever,
    reset_hybrid_retriever,
    hybrid_search,
)

# 重排序器
from app.rag.reranker import (
    DashScopeReranker,
    get_reranker,
    reset_reranker,
)

# 文档处理管道
from app.rag.pipeline import (
    RAGPipeline,
    get_rag_pipeline,
    reset_rag_pipeline,
    process_document,
    search_knowledge,
)

__all__ = [
    # 分块器
    "FabricChunker",
    "Chunk",
    "chunk_document",
    # 向量存储
    "VectorStore",
    "VectorSearchResult",
    "get_vector_store",
    "reset_vector_store",
    # BM25 检索器
    "BM25Retriever",
    "BM25SearchResult",
    "get_bm25_retriever",
    "reset_bm25_retriever",
    # 混合检索器
    "HybridRetriever",
    "HybridSearchResult",
    "get_hybrid_retriever",
    "reset_hybrid_retriever",
    "hybrid_search",
    # 重排序器
    "DashScopeReranker",
    "get_reranker",
    "reset_reranker",
    # 文档处理管道
    "RAGPipeline",
    "get_rag_pipeline",
    "reset_rag_pipeline",
    "process_document",
    "search_knowledge",
]
