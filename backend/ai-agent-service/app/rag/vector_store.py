"""
AI 智能客服系统 - DashVector 向量存储封装

封装 DashVector 向量数据库操作：
- 初始化客户端和 collection
- 文档向量化并存储
- 向量相似度检索
- 删除文档向量
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger

from app.config import settings

# 重试配置
MAX_RETRIES = 3
BASE_DELAY = 1.0  # 秒
MAX_DELAY = 30.0  # 秒


@dataclass
class VectorSearchResult:
    """向量检索结果"""
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any]


class VectorStore:
    """DashVector 向量存储封装
    
    使用阿里云 DashVector 作为向量数据库，
    使用 DashScope text-embedding-v3 生成文本向量。
    
    多租户隔离策略：
    - 每个租户使用独立的 Collection（tenant_{tenant_id}）
    - Collection 级别物理隔离
    """
    
    # text-embedding-v3 向量维度
    EMBEDDING_DIMENSION = 1024
    
    # 批量插入限制
    UPSERT_BATCH_SIZE = 100
    EMBEDDING_BATCH_SIZE = 25
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
    ):
        """
        初始化 VectorStore
        
        Args:
            api_key: DashVector API Key
            endpoint: DashVector Endpoint
            embedding_api_key: DashScope API Key（用于 Embedding）
        """
        self.api_key = api_key or settings.DASHVECTOR_API_KEY
        self.endpoint = endpoint or settings.DASHVECTOR_ENDPOINT
        self.embedding_api_key = embedding_api_key or settings.DASHSCOPE_API_KEY
        
        self._client = None
        self._embedding_client = None
        self._available = False
    
    async def init(self):
        """初始化 DashVector 客户端和 Embedding 客户端"""
        try:
            # 导入 dashvector
            import dashvector
            
            # 初始化 DashVector 客户端
            if self.api_key and self.endpoint:
                self._client = dashvector.Client(
                    api_key=self.api_key,
                    endpoint=self.endpoint
                )
                logger.info("DashVector client initialized")
            else:
                logger.warning(f"[vector-store] DashVector not available, degraded mode | api_key_set={bool(self.api_key)} endpoint_set={bool(self.endpoint)}")
                return
            
            # 初始化 Embedding 客户端
            if self.embedding_api_key:
                try:
                    import dashscope
                    dashscope.api_key = self.embedding_api_key
                    self._embedding_client = dashscope.TextEmbedding
                    logger.info("DashScope Embedding client initialized")
                except Exception as e:
                    logger.warning(f"[vector-store] DashScope Embedding init failed, degraded mode | error={type(e).__name__}: {e}")
            else:
                logger.warning("DashScope API Key not configured")
            
            self._available = True
            
        except ImportError as e:
            logger.warning(f"DashVector or DashScope not installed: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize VectorStore: {e}")
    
    async def close(self):
        """关闭客户端连接，释放资源"""
        self._client = None
        self._embedding_client = None
        self._available = False
        logger.info("VectorStore connections closed")
    
    async def _retry_with_backoff(self, func, *args, **kwargs):
        """带指数退避的重试包装器，处理 API 限流和瞬时错误"""
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                # 判断是否为可重试的错误（限流、超时、服务端错误）
                is_retryable = any(kw in error_str for kw in [
                    'throttl', 'rate limit', 'timeout', '429', '500', '502', '503', '504'
                ])
                if not is_retryable or attempt == MAX_RETRIES - 1:
                    raise
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                logger.warning(
                    f"Retryable error (attempt {attempt + 1}/{MAX_RETRIES}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
        raise last_exception
    
    def _get_collection_name(self, tenant_id: int) -> str:
        """获取租户对应的 Collection 名称"""
        return f"tenant_{tenant_id}"
    
    async def _ensure_collection(self, tenant_id: int):
        """确保租户的 Collection 存在"""
        if not self._available or not self._client:
            logger.warning("VectorStore not available, skipping collection check")
            return None
        
        collection_name = self._get_collection_name(tenant_id)
        
        try:
            # 检查 collection 是否存在
            collections = self._client.list_collections()
            collection_names = [c.name for c in collections] if collections else []
            
            if collection_name not in collection_names:
                # 创建 collection
                self._client.create_collection(
                    name=collection_name,
                    dimension=self.EMBEDDING_DIMENSION,
                    metric='cosine',  # 余弦相似度
                    fields_schema={
                        'content': 'string',
                        'tenant_id': 'int',
                        'document_id': 'string',
                        'doc_type': 'string',
                        'category': 'string',
                        'product_id': 'string',
                        'chunk_index': 'int',
                        'chunk_id': 'string',
                    }
                )
                logger.info(f"[vector-store] Collection ready | name={collection_name} (created)")
            else:
                logger.info(f"[vector-store] Collection ready | name={collection_name}")
            
            return self._client.get_collection(collection_name)
            
        except Exception as e:
            logger.error(f"[vector-store] Collection ensure failed | tenant={tenant_id} name={collection_name} error={type(e).__name__}: {e}", exc_info=True)
            return None
    
    async def _get_embeddings(
        self,
        texts: List[str],
        text_type: str = "document",
    ) -> List[List[float]]:
        """
        使用 DashScope text-embedding-v3 生成文本向量
        
        Args:
            texts: 文本列表
            text_type: 文本类型，'document' 用于入库，'query' 用于检索查询
            
        Returns:
            向量列表
        """
        if not self._embedding_client:
            logger.error("Embedding client not available")
            raise RuntimeError("Embedding client not initialized")
        
        model = settings.DASHSCOPE_EMBEDDING_MODEL or 'text-embedding-v3'
        all_embeddings = []
        
        # 批量处理
        for i in range(0, len(texts), self.EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + self.EMBEDDING_BATCH_SIZE]
            
            async def _call_embedding():
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda b=batch: self._embedding_client.call(
                        model=model,
                        input=b,
                        text_type=text_type,
                    )
                )
            
            try:
                response = await self._retry_with_backoff(_call_embedding)
                
                if response.status_code == 200:
                    embeddings = [
                        item['embedding']
                        for item in response.output['embeddings']
                    ]
                    all_embeddings.extend(embeddings)
                else:
                    raise RuntimeError(
                        f"Embedding API error: {response.code} - {response.message}"
                    )
                    
            except Exception as e:
                logger.error(f"Failed to get embeddings for batch {i}: {e}")
                raise
        
        return all_embeddings
    
    async def upsert_documents(
        self,
        chunks: List[Dict[str, Any]],
        tenant_id: int,
        doc_id: str,
    ) -> bool:
        """
        将分块后的文档向量化并存入 DashVector
        
        Args:
            chunks: 分块列表，每个块包含 content 和 metadata
            tenant_id: 租户 ID
            doc_id: 文档 ID
            
        Returns:
            是否成功
        """
        if not self._available:
            logger.warning("VectorStore not available, skipping upsert")
            return False
        
        if not chunks:
            logger.warning("No chunks to upsert")
            return True
        
        try:
            # 确保 collection 存在
            collection = await self._ensure_collection(tenant_id)
            if not collection:
                logger.error(f"Collection not available for tenant {tenant_id}")
                return False
            
            # 获取文本向量（入库使用 document 类型）
            texts = [chunk['content'] for chunk in chunks]
            embeddings = await self._get_embeddings(texts, text_type='document')
            
            # 构造 DashVector Doc
            import dashvector
            
            docs = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                metadata = chunk.get('metadata', {})
                doc = dashvector.Doc(
                    id=chunk.get('chunk_id', f"{doc_id}_{i}"),
                    vector=embedding,
                    fields={
                        'content': chunk['content'],
                        'tenant_id': tenant_id,
                        'document_id': doc_id,
                        'doc_type': metadata.get('doc_type', ''),
                        'category': metadata.get('category', ''),
                        'product_id': metadata.get('product_id', ''),
                        'chunk_index': i,
                        'chunk_id': chunk.get('chunk_id', f"{doc_id}_{i}"),
                    }
                )
                docs.append(doc)
            
            # 批量插入
            for i in range(0, len(docs), self.UPSERT_BATCH_SIZE):
                batch = docs[i:i + self.UPSERT_BATCH_SIZE]
                result = collection.upsert(batch)
                
                if not result:
                    logger.error(f"Failed to upsert batch {i}")
                    return False
            
            logger.info(f"[vector-store] Documents stored | count={len(docs)} collection={self._get_collection_name(tenant_id)}")
            return True
            
        except Exception as e:
            logger.error(f"[vector-store] Upsert failed | tenant={tenant_id} doc_id={doc_id} error={type(e).__name__}: {e}", exc_info=True)
            return False
    
    async def search(
        self,
        query: str,
        tenant_id: int,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[VectorSearchResult]:
        """
        向量相似度检索
        
        Args:
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回结果数
            filters: 过滤条件（如 {"doc_type": "faq", "category": "curtain"}）
            
        Returns:
            检索结果列表
        """
        if not self._available:
            logger.warning("VectorStore not available, returning empty results")
            return []
        
        try:
            # 获取查询向量（检索使用 query 类型）
            logger.debug(f"[vector-store] Similarity search | collection={self._get_collection_name(tenant_id)} top_k={top_k}")
            query_embedding = await self._get_embeddings([query], text_type='query')
            if not query_embedding:
                return []
            
            # 获取 collection
            collection_name = self._get_collection_name(tenant_id)
            collection = self._client.get_collection(collection_name)
            
            if not collection:
                logger.warning(f"Collection {collection_name} not found")
                return []
            
            # 构造过滤条件
            filter_expr = f"tenant_id = '{tenant_id}'"
            if filters:
                for key, value in filters.items():
                    if key != 'tenant_id' and value:
                        filter_expr += f" AND {key} = '{value}'"
            
            # 执行检索（带重试）
            async def _do_query():
                return collection.query(
                    vector=query_embedding[0],
                    topk=top_k,
                    filter=filter_expr,
                    include_vector=False
                )
            
            results = await self._retry_with_backoff(_do_query)
            
            # 解析结果
            search_results = []
            if results:
                for doc in results:
                    search_results.append(VectorSearchResult(
                        chunk_id=doc.id,
                        content=doc.fields.get('content', ''),
                        score=doc.score,
                        metadata={
                            'tenant_id': doc.fields.get('tenant_id'),
                            'document_id': doc.fields.get('document_id'),
                            'doc_type': doc.fields.get('doc_type'),
                            'category': doc.fields.get('category'),
                            'product_id': doc.fields.get('product_id'),
                            'chunk_index': doc.fields.get('chunk_index'),
                            'chunk_id': doc.fields.get('chunk_id'),
                        }
                    ))
            
            logger.info(f"Vector search returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            logger.error(f"[vector-store] Search failed | tenant={tenant_id} error={type(e).__name__}: {e}", exc_info=True)
            return []
    
    async def delete_document(self, tenant_id: int, doc_id: str) -> bool:
        """
        删除指定文档的所有向量
        
        Args:
            tenant_id: 租户 ID
            doc_id: 文档 ID
            
        Returns:
            是否成功
        """
        if not self._available:
            logger.warning("VectorStore not available, skipping delete")
            return False
        
        try:
            collection_name = self._get_collection_name(tenant_id)
            collection = self._client.get_collection(collection_name)
            
            if not collection:
                logger.warning(f"Collection {collection_name} not found")
                return True
            
            # 查询该文档的所有分块
            filter_expr = f"tenant_id = '{tenant_id}' AND document_id = '{doc_id}'"
            results = collection.query(
                vector=[0.0] * self.EMBEDDING_DIMENSION,  # 占位向量
                topk=10000,
                filter=filter_expr,
                include_vector=False
            )
            
            if not results:
                logger.info(f"No vectors found for doc {doc_id}")
                return True
            
            # 删除所有分块
            chunk_ids = [doc.id for doc in results]
            
            # 批量删除
            for i in range(0, len(chunk_ids), self.UPSERT_BATCH_SIZE):
                batch = chunk_ids[i:i + self.UPSERT_BATCH_SIZE]
                collection.delete(batch)
            
            logger.info(f"Deleted {len(chunk_ids)} vectors for doc {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"[vector-store] Delete failed | tenant={tenant_id} doc_id={doc_id} error={type(e).__name__}: {e}", exc_info=True)
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        status = {
            "available": self._available,
            "client_initialized": self._client is not None,
            "embedding_initialized": self._embedding_client is not None,
        }
        
        if self._available and self._client:
            try:
                loop = asyncio.get_event_loop()
                collections = await loop.run_in_executor(
                    None, self._client.list_collections
                )
                status["collection_count"] = len(collections) if collections else 0
            except Exception as e:
                status["error"] = str(e)
                status["available"] = False
        
        return status


# 全局 VectorStore 实例
_vector_store: Optional[VectorStore] = None


async def get_vector_store() -> VectorStore:
    """获取 VectorStore 实例（单例模式）"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
        await _vector_store.init()
    return _vector_store


def reset_vector_store():
    """重置 VectorStore 实例（用于测试）"""
    global _vector_store
    _vector_store = None
