# 自建 RAG 知识库技术方案 (历史参考)

> **⚠️ 历史参考文档** — v8.0 时期设计，RAG 核心架构仍然适用，但代码示例中的 Hermes Agent 引用已过时。
> **当前 RAG 实现见**: [`docs/wiki/AI-Agent.md`](../wiki/AI-Agent.md) § RAG Pipeline

> 版本：v8.0
> 日期：2026-04-12
> 背景：替代百炼知识库，使用阿里云 DashVector 向量数据库自建 RAG 链路
> 适用场景：布艺行业 AI 客服（窗帘、沙发布、桌布等）

---

## 一、整体架构

### 1.1 RAG 链路概览

```
文档管理流程：
┌──────────────┐    ┌───────────┐    ┌──────────────┐    ┌─────────────┐
│  原始文档     │───>│ 智能分块   │───>│ Embedding    │───>│ DashVector  │
│  (PDF/Word/   │    │ (Fabric   │    │ (text-embed  │    │ 向量索引     │
│   Markdown/   │    │  Chunker) │    │  ding-v3)    │    │             │
│   手动录入)   │    │           │    │              │    │             │
└──────────────┘    └───────────┘    └──────────────┘    └─────────────┘

检索流程（AI 客服对话中）：
┌──────────────┐    ┌───────────┐    ┌──────────────┐    ┌─────────────┐
│  用户问题     │───>│ Query     │───>│ 混合检索     │───>│ 重排序       │
│              │    │ Embedding │    │ (BM25 + 向量) │    │ (Reranker)  │
└──────────────┘    └───────────┘    └──────────────┘    └──────┬──────┘
                                                                │
┌──────────────┐    ┌───────────┐    ┌──────────────┐          │
│  LLM 生成    │<───│ RAG       │<───│ Top-K        │<─────────┘
│  回答        │    │ Prompt    │    │ 文档片段      │
│              │    │ 构造      │    │ + 元数据      │
└──────────────┘    └───────────┘    └──────────────┘
```

### 1.2 技术选型

| 组件 | 选型 | 原因 | 成本 |
|------|------|------|------|
| **向量数据库** | 阿里云 DashVector | 托管服务、按量付费、与百炼生态集成好 | ~¥50/月 |
| **Embedding 模型** | text-embedding-v3（百炼） | 中文效果好、支持多粒度、成本低 | ¥0.002/次 |
| **重排序模型** | bge-reranker-large（本地部署） | 提升 Top-K 精度 10-15% | SAE 0.5C1G |
| **分块策略** | 自定义 FabricChunker | 针对布艺行业文档结构优化 | 代码实现 |
| **BM25 检索** | Elasticsearch（可选）或 PostgreSQL tsvector | 关键词匹配补充 | 已有 RDS PG |

### 1.3 服务依赖关系

```
┌──────────────────────────────────────────────────────────────┐
│                      ai-agent-service                        │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐    │
│  │ Hermes     │  │ RAG 模块   │  │ 知识库管理 API     │    │
│  │ Agent      │──>│ (检索+     │  │ (文档上传/同步/    │    │
│  │ (对话引擎) │  │  Prompt)   │  │  分块/向量化)      │    │
│  └────────────┘  └─────┬──────┘  └────────┬───────────┘    │
│                        │                  │                │
│  ┌─────────────────────┼──────────────────┼────────────┐   │
│  │                     │                  │            │   │
│  ▼                     ▼                  ▼            │   │
│  DashVector      百炼 LLM API       RDS PostgreSQL    │   │
│  (向量检索)       (Embedding +       (文档元数据、     │   │
│                   对话生成)           业务元数据)      │   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Redis (检索缓存、分块缓存)                      │   │
│  └─────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、核心模块设计

### 2.1 文档分块（FabricChunker）

布艺行业文档有其特殊结构：面料属性、加工工艺、安装方法、保养说明等。通用分块策略会破坏语义完整性，需要定制化分块。

**分块原则**：
1. 按语义边界分块，不按固定字符数硬切
2. 保留上下文元信息（商品名、分类、加工工艺）
3. 单块大小 300-800 字，最大不超过 1000 字
4. 相邻块之间有 50-100 字重叠（防止边界信息丢失）

**文档类型与分块策略**：

| 文档类型 | 示例 | 分块策略 | 块大小 |
|---------|------|---------|-------|
| 产品说明 | 遮光窗帘布产品介绍 | 按属性分段（材质、规格、功能、适用场景） | 200-500 字 |
| 加工工艺 | 窗帘打孔/挂钩/折边说明 | 按工艺步骤分块，每步独立 | 150-400 字 |
| FAQ | 常见问题解答 | 一问一答为一块 | 100-300 字 |
| 安装指南 | 窗帘安装步骤 | 按步骤分块，保留前置条件 | 200-600 字 |
| 保养说明 | 清洗、晾晒、收纳方法 | 按保养类型分块 | 150-400 字 |
| 面料知识 | 棉麻、绒布、纱帘特性 | 按面料类型分块 | 300-800 字 |

**FabricChunker 实现**：

```python
# ai-agent-service/rag/chunker.py

from dataclasses import dataclass, field
from typing import List, Optional
import re

@dataclass
class Chunk:
    """文档分块"""
    content: str                    # 分块文本
    metadata: dict                  # 元数据
    chunk_id: str = ""             # 分块 ID（生成）
    embedding: Optional[List[float]] = field(default=None, repr=False)

class FabricChunker:
    """布艺行业文档分块器"""

    # 布艺行业文档结构标记
    SECTION_PATTERNS = [
        r'^#{1,3}\s+(.+)$',           # Markdown 标题
        r'^【(.+)】$',                # 中文方括号标题
        r'^第[一二三四五六七八九十]+[章节部分].+$',  # 章节标记
        r'^\d+\.\s+(.+)$',           # 数字编号标题
        r'^[一二三四五六七八九十]+[、.](.+)$',  # 中文编号
    ]

    # 语义边界关键词
    BOUNDARY_KEYWORDS = [
        '材质', '规格', '功能', '特点', '适用场景', '注意事项',
        '加工', '工艺', '打孔', '挂钩', '折边', '包边',
        '安装', '步骤', '方法',
        '清洗', '保养', '洗涤', '晾晒', '收纳',
        '面料', '成分', '克重', '门幅', '缩水率',
    ]

    def __init__(
        self,
        max_chunk_size: int = 800,
        min_chunk_size: int = 150,
        overlap_size: int = 80,
    ):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap_size = overlap_size

    def chunk(self, document: str, metadata: dict) -> List[Chunk]:
        """
        对文档进行智能分块

        Args:
            document: 文档全文
            metadata: 文档元数据（tenant_id, product_id, category, doc_type 等）

        Returns:
            分块列表
        """
        # 第一步：按结构标记分割
        sections = self._split_by_structure(document)

        # 第二步：按语义边界细化
        semantic_blocks = []
        for section in sections:
            blocks = self._split_by_semantic_boundary(section)
            semantic_blocks.extend(blocks)

        # 第三步：控制块大小
        chunks = []
        for block in semantic_blocks:
            if len(block) > self.max_chunk_size:
                # 大块继续按句子分割
                sub_chunks = self._split_by_sentences(block)
                chunks.extend(sub_chunks)
            elif len(block) >= self.min_chunk_size:
                chunks.append(block)
            else:
                # 小块合并到前一个块
                if chunks:
                    chunks[-1] = chunks[-1] + " " + block
                else:
                    chunks.append(block)

        # 第四步：生成 Chunk 对象
        result = []
        for i, content in enumerate(chunks):
            # 添加重叠内容
            if i > 0 and self.overlap_size > 0:
                prev_tail = chunks[i-1][-self.overlap_size:]
                content = prev_tail + content

            chunk = Chunk(
                content=content.strip(),
                metadata={
                    **metadata,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }
            )
            chunk.chunk_id = self._generate_chunk_id(metadata, i)
            result.append(chunk)

        return result

    def _split_by_structure(self, text: str) -> List[str]:
        """按文档结构标记分割"""
        sections = []
        current_section = []

        for line in text.split('\n'):
            is_heading = any(
                re.match(pattern, line.strip())
                for pattern in self.SECTION_PATTERNS
            )

            if is_heading and current_section:
                section_text = '\n'.join(current_section).strip()
                if section_text:
                    sections.append(section_text)
                current_section = [line]
            else:
                current_section.append(line)

        # 最后一个 section
        if current_section:
            section_text = '\n'.join(current_section).strip()
            if section_text:
                sections.append(section_text)

        return sections if sections else [text]

    def _split_by_semantic_boundary(self, text: str) -> List[str]:
        """按语义边界关键词细化分块"""
        # 查找语义边界关键词的位置
        boundaries = []
        for keyword in self.BOUNDARY_KEYWORDS:
            for match in re.finditer(keyword, text):
                boundaries.append(match.start())

        if not boundaries:
            return [text]

        boundaries.sort()

        # 按边界分割
        blocks = []
        prev_pos = 0
        for pos in boundaries:
            # 往前找最近的换行符作为分割点
            split_pos = text.rfind('\n', prev_pos, pos)
            if split_pos == -1:
                split_pos = pos

            block = text[prev_pos:split_pos].strip()
            if block:
                blocks.append(block)
            prev_pos = split_pos

        # 最后一块
        last_block = text[prev_pos:].strip()
        if last_block:
            blocks.append(last_block)

        return blocks if blocks else [text]

    def _split_by_sentences(self, text: str) -> List[str]:
        """按句子分割大块"""
        sentences = re.split(r'(?<=[。！？\n])', text)
        chunks = []
        current_chunk = []
        current_size = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_size = len(sentence)

            if current_size + sentence_size > self.max_chunk_size and current_chunk:
                chunks.append(''.join(current_chunk))
                current_chunk = [sentence]
                current_size = sentence_size
            else:
                current_chunk.append(sentence)
                current_size += sentence_size

        if current_chunk:
            chunks.append(''.join(current_chunk))

        return chunks

    def _generate_chunk_id(self, metadata: dict, index: int) -> str:
        """生成唯一分块 ID"""
        doc_id = metadata.get("document_id", "unknown")
        return f"chunk_{doc_id}_{index:03d}"
```

### 2.2 Embedding 向量化

使用百炼 `text-embedding-v3` 模型，通过 DashScope SDK 调用。

```python
# ai-agent-service/rag/embedding.py

import asyncio
from typing import List, Optional
from dashscope import TextEmbedding
from tenacity import retry, stop_after_attempt, wait_exponential

class EmbeddingClient:
    """Embedding 客户端"""

    def __init__(self, api_key: str, model: str = "text-embedding-v3"):
        self.api_key = api_key
        self.model = model
        self._dimension = 1024  # text-embedding-v3 默认维度

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def embed(self, text: str) -> List[float]:
        """
        将文本转换为向量

        Args:
            text: 输入文本

        Returns:
            向量（1024 维）
        """
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: TextEmbedding.call(
                model=self.model,
                input=text,
                api_key=self.api_key,
                text_type="document"  # document 或 query
            )
        )

        if response.status_code == 200:
            return response.output["embeddings"][0]["embedding"]
        else:
            raise Exception(
                f"Embedding 调用失败: {response.code} - {response.message}"
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量向量化（最多 25 条/次）

        Args:
            texts: 文本列表

        Returns:
            向量列表
        """
        # DashScope 批量接口限制：最多 25 条
        batch_size = 25
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda b=batch: TextEmbedding.call(
                    model=self.model,
                    input=b,
                    api_key=self.api_key,
                    text_type="document"
                )
            )

            if response.status_code == 200:
                batch_embeddings = [
                    item["embedding"]
                    for item in response.output["embeddings"]
                ]
                all_embeddings.extend(batch_embeddings)
            else:
                raise Exception(
                    f"批量 Embedding 调用失败: {response.code} - {response.message}"
                )

        return all_embeddings
```

### 2.3 DashVector 向量存储

```python
# ai-agent-service/rag/vector_store.py

import dashvector
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class SearchResult:
    """检索结果"""
    chunk_id: str
    content: str
    score: float
    metadata: dict

class DashVectorStore:
    """DashVector 向量存储客户端"""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        dimension: int = 1024,
    ):
        self.api_key = api_key
        self.endpoint = endpoint
        self.dimension = dimension
        self._client = dashvector.Client(
            api_key=api_key,
            endpoint=endpoint
        )

    def create_collection(self, collection_name: str):
        """
        创建向量集合（每个租户一个 collection）

        Args:
            collection_name: 集合名称（建议格式：tenant_{tenant_id}）
        """
        self._client.create_collection(
            name=collection_name,
            dimension=self.dimension,
            metric="cosine",  # cosine / l2 / ip
            fields_schema={
                "content": "string",         # 分块文本
                "tenant_id": "string",       # 租户 ID
                "document_id": "string",     # 文档 ID
                "product_id": "string",      # 关联商品 ID（可选）
                "category": "string",        # 文档分类
                "doc_type": "string",        # 文档类型（FAQ/产品说明/工艺指南）
                "chunk_index": "int",        # 分块序号
                "is_active": "bool",         # 是否有效
            }
        )

    def upsert_chunks(self, collection_name: str, chunks: List) -> bool:
        """
        插入或更新分块

        Args:
            collection_name: 集合名称
            chunks: Chunk 对象列表

        Returns:
            是否成功
        """
        collection = self._client.get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection {collection_name} 不存在")

        # 构造 Docs
        docs = []
        for chunk in chunks:
            doc = dashvector.Doc(
                id=chunk.chunk_id,
                vector=chunk.embedding,
                fields={
                    "content": chunk.content,
                    "tenant_id": chunk.metadata.get("tenant_id"),
                    "document_id": chunk.metadata.get("document_id"),
                    "product_id": chunk.metadata.get("product_id", ""),
                    "category": chunk.metadata.get("category", ""),
                    "doc_type": chunk.metadata.get("doc_type", ""),
                    "chunk_index": chunk.metadata.get("chunk_index", 0),
                    "is_active": True,
                }
            )
            docs.append(doc)

        # 批量插入（最多 100 条/次）
        batch_size = 100
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            result = collection.upsert(batch)
            if not result:
                return False

        return True

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        向量检索

        Args:
            collection_name: 集合名称
            query_vector: 查询向量
            top_k: 返回结果数
            filters: 过滤条件（如 {"tenant_id": "xxx", "category": "curtain"}）

        Returns:
            检索结果列表
        """
        collection = self._client.get_collection(collection_name)
        if not collection:
            return []

        # 构造过滤条件
        filter_expr = None
        if filters:
            filter_parts = []
            for key, value in filters.items():
                filter_parts.append(f"{key} = '{value}'")
            filter_expr = " AND ".join(filter_parts)

        # 检索
        docs = collection.query(
            vector=query_vector,
            topk=top_k,
            filter=filter_expr,
            include_vector=False
        )

        results = []
        for doc in docs:
            results.append(SearchResult(
                chunk_id=doc.id,
                content=doc.fields.get("content", ""),
                score=doc.score,
                metadata={
                    "tenant_id": doc.fields.get("tenant_id"),
                    "document_id": doc.fields.get("document_id"),
                    "product_id": doc.fields.get("product_id"),
                    "category": doc.fields.get("category"),
                    "doc_type": doc.fields.get("doc_type"),
                }
            ))

        return results

    def delete_by_document(self, collection_name: str, document_id: str) -> bool:
        """
        按文档 ID 删除所有分块

        Args:
            collection_name: 集合名称
            document_id: 文档 ID

        Returns:
            是否成功
        """
        collection = self._client.get_collection(collection_name)
        if not collection:
            return False

        # DashVector 不支持按字段过滤删除，需要查询后逐条删除
        docs = collection.query(
            vector=[0.0] * self.dimension,  # 占位向量
            topk=10000,
            filter=f"document_id = '{document_id}'",
            include_vector=False
        )

        if docs:
            doc_ids = [doc.id for doc in docs]
            result = collection.delete(ids=doc_ids)
            return bool(result)

        return True
```

### 2.4 混合检索（BM25 + 向量）

纯向量检索在以下场景效果不佳：
- 精确关键词匹配（如产品型号 "ZG-2024"）
- 专有名词（如面料名 "雪尼尔"、"高精密"）
- 短查询（信息量少，向量相似度不准）

因此采用**混合检索**：BM25 关键词检索 + 向量语义检索，然后加权融合。

```python
# ai-agent-service/rag/retriever.py

from typing import List, Optional, Dict, Any
import asyncio

class HybridRetriever:
    """混合检索器（BM25 + 向量）"""

    def __init__(
        self,
        vector_store,       # DashVectorStore 实例
        embedding_client,   # EmbeddingClient 实例
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        top_k: int = 10,
    ):
        self.vector_store = vector_store
        self.embedding_client = embedding_client
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.top_k = top_k

    async def retrieve(
        self,
        collection_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List:
        """
        混合检索

        Args:
            collection_name: 向量集合名称
            query: 查询文本
            filters: 过滤条件

        Returns:
            检索结果列表（按融合分数排序）
        """
        # 并行执行 BM25 检索和向量检索
        vector_task = self._vector_search(collection_name, query, filters)
        bm25_task = self._bm25_search(collection_name, query, filters)

        vector_results, bm25_results = await asyncio.gather(
            vector_task, bm25_task, return_exceptions=True
        )

        # 处理异常
        if isinstance(vector_results, Exception):
            vector_results = []
        if isinstance(bm25_results, Exception):
            bm25_results = []

        # 融合结果
        fused_results = self._reciprocal_rank_fusion(
            vector_results,
            bm25_results,
            self.vector_weight,
            self.bm25_weight
        )

        return fused_results[:self.top_k]

    async def _vector_search(self, collection_name, query, filters):
        """向量检索"""
        query_embedding = await self.embedding_client.embed(query)
        return self.vector_store.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            top_k=self.top_k * 2,  # 多取一些用于融合
            filters=filters
        )

    async def _bm25_search(self, collection_name, query, filters):
        """
        BM25 关键词检索

        实现方式（二选一）：
        1. PostgreSQL tsvector（已有 RDS，零额外成本）
        2. Elasticsearch（如果已有 ES 集群）

        这里使用 PostgreSQL 方案
        """
        # 调用 PostgreSQL 全文检索
        # 实现见下方 BM25Search 类
        bm25 = BM25Search()
        return await bm25.search(
            collection_name=collection_name,
            query=query,
            filters=filters,
            top_k=self.top_k * 2
        )

    def _reciprocal_rank_fusion(
        self,
        vector_results: List,
        bm25_results: List,
        vector_weight: float,
        bm25_weight: float,
        k: int = 60
    ) -> List:
        """
        倒数排名融合（Reciprocal Rank Fusion）

        公式：score = Σ (weight_i / (k + rank_i))
        """
        # 构建 ID -> 结果的映射
        result_map = {}

        # 向量检索结果
        for rank, result in enumerate(vector_results, 1):
            result_map[result.chunk_id] = {
                "result": result,
                "score": 0.0
            }
            result_map[result.chunk_id]["score"] += vector_weight / (k + rank)

        # BM25 结果
        for rank, result in enumerate(bm25_results, 1):
            if result.chunk_id in result_map:
                result_map[result.chunk_id]["score"] += bm25_weight / (k + rank)
            else:
                result_map[result.chunk_id] = {
                    "result": result,
                    "score": bm25_weight / (k + rank)
                }

        # 按融合分数排序
        sorted_results = sorted(
            result_map.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        return [item["result"] for item in sorted_results]
```

**BM25 检索实现（PostgreSQL tsvector）**：

```python
# ai-agent-service/rag/bm25_search.py

import asyncpg
from typing import List, Optional, Dict, Any

class BM25Search:
    """基于 PostgreSQL tsvector 的 BM25 检索"""

    def __init__(self, dsn: str):
        self.dsn = dsn

    async def search(
        self,
        collection_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
    ) -> List:
        """
        BM25 全文检索

        Args:
            collection_name: 集合名称（对应 rag_chunks 表的 tenant 分区）
            query: 查询文本
            filters: 过滤条件
            top_k: 返回结果数

        Returns:
            检索结果列表
        """
        conn = await asyncpg.connect(self.dsn)

        # 构造查询条件
        where_parts = ["tenant_id = $1"]
        params = [filters.get("tenant_id", "")]
        param_idx = 2

        if filters.get("category"):
            where_parts.append(f"category = ${param_idx}")
            params.append(filters["category"])
            param_idx += 1

        if filters.get("doc_type"):
            where_parts.append(f"doc_type = ${param_idx}")
            params.append(filters["doc_type"])
            param_idx += 1

        where_clause = " AND ".join(where_parts)

        # 全文检索查询
        sql = f"""
            SELECT
                chunk_id,
                content,
                ts_rank(search_vector, plainto_tsquery('chinese', ${param_idx})) as rank_score,
                metadata
            FROM rag_chunks
            WHERE {where_clause}
              AND search_vector @@ plainto_tsquery('chinese', ${param_idx})
            ORDER BY rank_score DESC
            LIMIT ${param_idx + 1}
        """
        params.extend([query, top_k])

        rows = await conn.fetch(sql, *params)
        await conn.close()

        results = []
        for row in rows:
            results.append(SearchResult(
                chunk_id=row["chunk_id"],
                content=row["content"],
                score=row["rank_score"],
                metadata=row["metadata"]
            ))

        return results
```

### 2.5 重排序（Reranker）

混合检索后得到的 Top-K 结果，可以用重排序模型进一步提升精度。

```python
# ai-agent-service/rag/reranker.py

from typing import List
from FlagEmbedding import FlagReranker

class Reranker:
    """重排序模型"""

    def __init__(self, model_path: str = "BAAI/bge-reranker-large"):
        self.reranker = FlagReranker(model_path, use_fp16=True)

    def rerank(
        self,
        query: str,
        passages: List[str],
        top_k: int = 5,
    ) -> List[int]:
        """
        对检索结果重排序

        Args:
            query: 查询文本
            passages: 候选文档片段列表
            top_k: 返回 Top-K

        Returns:
            重排序后的原始索引列表
        """
        # 构造 (query, passage) 对
        pairs = [[query, passage] for passage in passages]

        # 计算相关性分数
        scores = self.reranker.compute_score(pairs, normalize=True)

        # 按分数排序
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # 返回 Top-K 索引
        return [idx for idx, _ in indexed_scores[:top_k]]
```

### 2.6 RAG Prompt 构造

```python
# ai-agent-service/rag/prompt_builder.py

from typing import List

class RAGPromptBuilder:
    """RAG Prompt 构造器"""

    SYSTEM_PROMPT_TEMPLATE = """你是 {company_name} 的 AI 客服助手，专业解答关于窗帘、布艺、面料的咨询。

请根据以下参考资料回答用户的问题。要求：
1. 回答要准确、简洁、专业
2. 优先使用参考资料中的信息，不要编造
3. 如果参考资料中没有相关信息，请如实告知用户
4. 涉及价格时，要说明是估算价，以实际下单为准
5. 涉及加工工艺，要列出具体加工项和对应费用
6. 回答末尾不要添加"希望这个回答对您有帮助"等套话

参考资料：
{context}
"""

    def build(
        self,
        query: str,
        search_results: List,
        company_name: str = "本公司",
    ) -> dict:
        """
        构造 RAG Prompt

        Args:
            query: 用户问题
            search_results: 检索结果列表
            company_name: 公司名称

        Returns:
            Prompt 字典
        """
        # 构造上下文
        context_parts = []
        for i, result in enumerate(search_results, 1):
            context_parts.append(
                f"[资料{i}]（来源：{result.metadata.get('doc_type', '')}，"
                f"分类：{result.metadata.get('category', '')}）\n"
                f"{result.content}"
            )

        context = "\n\n".join(context_parts)

        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            company_name=company_name,
            context=context
        )

        return {
            "system": system_prompt,
            "user": query,
        }
```

---

## 三、数据库设计

### 3.1 知识库文档表

```sql
-- 知识库文档元数据表
CREATE TABLE knowledge_documents (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),

    -- 文档基本信息
    title VARCHAR(255) NOT NULL,
    doc_type VARCHAR(32) NOT NULL,        -- product_info / faq / processing_guide / installation / maintenance / fabric_knowledge
    category VARCHAR(64),                  -- 文档分类（curtain /纱帘 / tablecloth / sofa_fabric）
    file_type VARCHAR(16),                 -- markdown / pdf / word / manual
    file_url VARCHAR(512),                 -- 原始文件 URL（如从文件上传）
    content TEXT,                          -- 文档内容（手动录入或从文件提取）

    -- 关联业务数据
    product_id VARCHAR(64),                -- 关联商品 ID（可选，商品说明类文档）

    -- 向量化状态
    embedding_status VARCHAR(16) DEFAULT 'pending',  -- pending / processing / completed / failed
    chunk_count INTEGER DEFAULT 0,         -- 分块数量
    dashvector_collection VARCHAR(128),    -- DashVector 集合名称

    -- 状态
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(64) REFERENCES agent_employees(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_knowledge_docs_tenant ON knowledge_documents(tenant_id);
CREATE INDEX idx_knowledge_docs_product ON knowledge_documents(product_id);
CREATE INDEX idx_knowledge_docs_status ON knowledge_documents(embedding_status);

-- 分块明细表（用于 BM25 检索和调试）
CREATE TABLE rag_chunks (
    chunk_id VARCHAR(128) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
    document_id VARCHAR(64) NOT NULL REFERENCES knowledge_documents(id),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    chunk_index INTEGER DEFAULT 0,

    -- 全文检索索引
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('chinese', content)
    ) STORED,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- GIN 索引用于全文检索
CREATE INDEX idx_rag_chunks_search ON rag_chunks USING GIN(search_vector);
CREATE INDEX idx_rag_chunks_tenant ON rag_chunks(tenant_id);
CREATE INDEX idx_rag_chunks_document ON rag_chunks(document_id);
```

### 3.2 向量化任务表

```sql
-- 向量化任务表（用于异步任务和重试）
CREATE TABLE embedding_tasks (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
    document_id VARCHAR(64) NOT NULL REFERENCES knowledge_documents(id),
    status VARCHAR(16) DEFAULT 'pending',  -- pending / processing / completed / failed
    total_chunks INTEGER DEFAULT 0,
    processed_chunks INTEGER DEFAULT 0,
    failed_chunks INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_embedding_tasks_tenant ON embedding_tasks(tenant_id);
CREATE INDEX idx_embedding_tasks_status ON embedding_tasks(status);
```

---

## 四、多租户数据隔离设计

本系统的 RAG 架构在设计时就充分考虑了多租户数据隔离需求，从向量数据库、关系型数据库、API 网关到前端展示，全链路实现租户级数据隔离。

### 4.1 隔离策略总览

| 层级 | 隔离机制 | 实现方式 | 安全级别 |
|------|---------|---------|---------|
| **向量数据库层** | Collection 级别隔离 | `tenant_{tenant_id}` 命名约定 | 物理隔离 |
| **数据库层** | 行级安全策略（RLS） | PostgreSQL RLS Policy | 逻辑隔离 |
| **API 网关层** | JWT 租户提取 + 中间件拦截 | 服务端提取 tenant_id，禁止客户端传入 | 访问控制 |
| **应用层** | 租户上下文透传 | 所有查询自动注入 tenant_id 过滤 | 业务隔离 |
| **前端层** | 角色权限 + 数据过滤 | RBAC 菜单控制 + 表格自动过滤 | 展示隔离 |

### 4.2 DashVector Collection 级别隔离

**核心原则**：每个租户拥有独立的 DashVector Collection，向量数据物理隔离。

```python
# rag/vector_store.py

class DashVectorStore:
    """DashVector 向量数据库客户端"""

    def __init__(self, api_key: str, endpoint: str):
        self.client = dashvector.Client(api_key=api_key, endpoint=endpoint)

    def get_collection_name(self, tenant_id: str) -> str:
        """生成租户 Collection 名称"""
        return f"tenant_{tenant_id}"

    def create_tenant_collection(self, tenant_id: str, dimension: int = 1024):
        """为租户创建独立的向量集合"""
        collection_name = self.get_collection_name(tenant_id)

        # 创建集合（如果不存在）
        if collection_name not in [c.name for c in self.client.list_collections()]:
            self.client.create_collection(
                name=collection_name,
                dimension=dimension,
                metric_type='cosine',  # 余弦相似度
                extra_params={
                    'description': f'Knowledge base for tenant {tenant_id}'
                }
            )

    def upsert_chunks(self, tenant_id: str, chunks: list) -> bool:
        """写入向量数据（自动路由到租户 Collection）"""
        collection_name = self.get_collection_name(tenant_id)
        collection = self.client.get_collection(collection_name)

        docs = [
            dashvector.Doc(
                id=chunk.chunk_id,
                vector=chunk.embedding,
                fields={
                    'tenant_id': chunk.metadata['tenant_id'],
                    'document_id': chunk.metadata['document_id'],
                    'doc_type': chunk.metadata.get('doc_type', ''),
                    'category': chunk.metadata.get('category', ''),
                    'product_id': chunk.metadata.get('product_id', ''),
                    'chunk_index': chunk.metadata.get('chunk_index', 0),
                }
            )
            for chunk in chunks
        ]

        result = collection.upsert(docs)
        return result.code == 0

    def search(self, tenant_id: str, query_vector: list, top_k: int = 5,
               filters: dict = None) -> list:
        """向量检索（限定租户 Collection）"""
        collection_name = self.get_collection_name(tenant_id)
        collection = self.client.get_collection(collection_name)

        # 构造过滤条件（确保不会跨租户检索）
        filter_expr = f"tenant_id='{tenant_id}'"
        if filters:
            extra_filters = " AND ".join([
                f"{k}='{v}'" for k, v in filters.items() if k != 'tenant_id'
            ])
            if extra_filters:
                filter_expr += f" AND {extra_filters}"

        result = collection.query(
            vector=query_vector,
            topk=top_k,
            filter=filter_expr
        )

        return result.docs
```

**安全保证**：
- Collection 命名规则 `tenant_{tenant_id}` 确保租户间向量数据完全隔离
- 即使 API Key 泄露，攻击者也只能访问特定租户的 Collection
- 检索时双重 tenant_id 校验（Collection 名称 + 过滤条件）

### 4.3 PostgreSQL 行级安全策略（RLS）

**核心原则**：所有 RAG 相关表启用 RLS，数据库层面强制执行租户隔离。

```sql
-- 启用行级安全
ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE embedding_tasks ENABLE ROW LEVEL SECURITY;

-- 策略：租户只能访问自己的文档
CREATE POLICY tenant_isolation_policy ON knowledge_documents
    USING (tenant_id = current_setting('app.current_tenant_id'));

-- 策略：租户只能访问自己的分块
CREATE POLICY tenant_isolation_policy ON rag_chunks
    USING (tenant_id = current_setting('app.current_tenant_id'));

-- 策略：租户只能访问自己的向量化任务
CREATE POLICY tenant_isolation_policy ON embedding_tasks
    USING (tenant_id = current_setting('app.current_tenant_id'));

-- 插入/更新/删除策略（同样限制租户）
CREATE POLICY tenant_insert_policy ON knowledge_documents
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id'));

CREATE POLICY tenant_update_policy ON knowledge_documents
    USING (tenant_id = current_setting('app.current_tenant_id'))
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id'));

CREATE POLICY tenant_delete_policy ON knowledge_documents
    USING (tenant_id = current_setting('app.current_tenant_id'));
```

**应用层设置租户上下文**：

```python
# database/connection.py

import asyncpg

class TenantAwareConnection:
    """租户感知的数据库连接"""

    @staticmethod
    async def set_tenant_context(conn, tenant_id: str):
        """设置当前连接的租户上下文（供 RLS 策略使用）"""
        await conn.execute(f"SET app.current_tenant_id = '{tenant_id}'")

    @classmethod
    async def get_pool(cls, dsn: str, tenant_id: str):
        """获取租户感知的连接池"""
        pool = await asyncpg.create_pool(dsn=dsn)

        async def init_connection(conn):
            await cls.set_tenant_context(conn, tenant_id)

        await pool.init(init_connection)
        return pool
```

### 4.4 JWT 租户提取与中间件拦截

**核心原则**：tenant_id 从 JWT 服务端提取，绝不信任客户端传入的租户标识。

```python
# middleware/tenant_middleware.py

from fastapi import Request, HTTPException
from jose import jwt, JWTError

class TenantMiddleware:
    """租户中间件：从 JWT 提取 tenant_id 并注入请求上下文"""

    def __init__(self, secret_key: str, public_key_path: str, algorithm: str = "RS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm

    async def __call__(self, request: Request, call_next):
        # 跳过不需要认证的路径
        skip_paths = ['/login', '/health', '/docs', '/openapi.json']
        if request.url.path in skip_paths:
            return await call_next(request)

        # 提取并验证 JWT
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            raise HTTPException(status_code=401, detail="Missing or invalid token")

        token = auth_header.split(' ', 1)[1]

        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        # 提取 tenant_id（必须存在）
        tenant_id = payload.get('tenant_id')
        if not tenant_id:
            raise HTTPException(status_code=401, detail="Missing tenant_id in token")

        # 注入租户上下文到请求对象
        request.state.tenant_id = tenant_id
        request.state.user_id = payload.get('user_id')
        request.state.user_role = payload.get('role', 'support_agent')

        # 设置数据库连接的租户上下文（如果使用连接池中间件）
        request.state.db_tenant_id = tenant_id

        response = await call_next(request)
        return response
```

**路由中使用租户上下文**：

```python
# api/knowledge_routes.py

from fastapi import APIRouter, Depends, Request
from database.connection import TenantAwareConnection

router = APIRouter()

@router.get("/api/admin/knowledge/documents")
async def list_documents(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    doc_type: str = None,
    category: str = None,
    status: str = None,
):
    """获取知识库文档列表（自动按租户过滤）"""
    tenant_id = request.state.tenant_id

    # 构建查询（tenant_id 由中间件注入，不可由客户端篡改）
    query = """
        SELECT id, title, doc_type, category, file_type,
               embedding_status, chunk_count, created_at, updated_at
        FROM knowledge_documents
        WHERE tenant_id = $1
    """
    params = [tenant_id, page_size, (page - 1) * page_size]

    if doc_type:
        query += " AND doc_type = $2"
        params.append(doc_type)

    if category:
        query += f" AND category = ${len(params) + 1}"
        params.append(category)

    if status:
        query += f" AND embedding_status = ${len(params) + 1}"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}"

    # 执行查询并返回...
    # ...
```

### 4.5 多租户安全审计清单

在部署前，请逐项检查：

- [ ] **DashVector Collection 命名**：是否使用 `tenant_{tenant_id}` 格式，且不包含特殊字符
- [ ] **RLS 策略**：是否对 knowledge_documents、rag_chunks、embedding_tasks 三张表都启用了 RLS
- [ ] **JWT 验证**：tenant_id 是否只从服务端 JWT 提取，禁止客户端在 Header/Body 中传入 tenant_id
- [ ] **API 参数清洗**：所有涉及 tenant_id 的查询参数是否被忽略/覆盖为 JWT 中的值
- [ ] **错误信息脱敏**：API 错误响应是否避免泄露其他租户的 ID 或数据
- [ ] **日志脱敏**：应用日志中是否对 tenant_id 进行脱敏处理（如 `tenant_abc***123`）
- [ ] **备份隔离**：数据库备份是否按租户分离，恢复时不会混淆租户数据
- [ ] **监控告警**：是否配置了跨租户访问尝试的监控告警（RLS 策略被触发拒绝）

### 4.6 前端多租户适配

**管理后台无需选择租户**：商家后台是"单租户视角"，用户登录后只看到自己租户的数据。

```typescript
// lib/api-client.ts

class ApiClient {
  private token: string;

  constructor(token: string) {
    this.token = token;
    // tenant_id 不需要前端传入，由服务端从 JWT 提取
  }

  async get(url: string, params?: Record<string, string>) {
    const query = new URLSearchParams(params).toString();
    const response = await fetch(`/api${url}${query ? '?' + query : ''}`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${this.token}`,
        // 不传入 X-Tenant-ID，由服务端自动处理
      },
    });

    if (response.status === 401) {
      // token 过期或无效，跳转登录
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    return response.json();
  }
}
```

---

## 五、API 设计

### 5.1 知识库管理 API

```
# 文档管理
POST   /api/admin/knowledge/documents          # 上传/创建文档
GET    /api/admin/knowledge/documents           # 获取文档列表
GET    /api/admin/knowledge/documents/{id}      # 获取文档详情
PUT    /api/admin/knowledge/documents/{id}      # 更新文档
DELETE /api/admin/knowledge/documents/{id}      # 删除文档

# 分块管理
GET    /api/admin/knowledge/documents/{id}/chunks     # 查看文档分块
PUT    /api/admin/knowledge/documents/{id}/rechunk    # 重新分块

# 向量化
POST   /api/admin/knowledge/documents/{id}/embed      # 触发向量化
GET    /api/admin/knowledge/embedding-tasks/{id}      # 查看向量化任务状态

# 检索测试
POST   /api/admin/knowledge/test-search               # 测试检索（输入问题，返回匹配的文档片段）

# 批量操作
POST   /api/admin/knowledge/batch-sync                # 批量同步知识库（商品上下架时自动触发）
```

### 5.2 请求/响应示例

**创建文档**：

```
POST /api/admin/knowledge/documents
Content-Type: application/json

{
  "title": "遮光窗帘布 - 产品说明",
  "doc_type": "product_info",
  "category": "curtain",
  "content": "遮光窗帘布采用高精密织造工艺...",
  "product_id": "PROD001"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "doc_abc123",
    "title": "遮光窗帘布 - 产品说明",
    "embedding_status": "pending",
    "message": "文档已创建，向量化任务已加入队列"
  }
}
```

**查看分块**：

```
GET /api/admin/knowledge/documents/doc_abc123/chunks
```

**响应**：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_abc123",
    "total_chunks": 5,
    "chunks": [
      {
        "chunk_id": "chunk_doc_abc123_000",
        "content": "遮光窗帘布采用高精密织造工艺，遮光率可达 85%-95%...",
        "chunk_index": 0,
        "metadata": {"category": "curtain", "doc_type": "product_info"}
      },
      {
        "chunk_id": "chunk_doc_abc123_001",
        "content": "加工方式可选：打孔加工（¥5/个）、挂钩加工（¥3/个）、折边加工（¥10/米）...",
        "chunk_index": 1,
        "metadata": {"category": "curtain", "doc_type": "processing_guide"}
      }
    ]
  }
}
```

**测试检索**：

```
POST /api/admin/knowledge/test-search
Content-Type: application/json

{
  "query": "遮光窗帘布 打孔 多少钱",
  "top_k": 5
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "query": "遮光窗帘布 打孔 多少钱",
    "results": [
      {
        "chunk_id": "chunk_doc_abc123_001",
        "content": "加工方式可选：打孔加工（¥5/个）、挂钩加工（¥3/个）...",
        "score": 0.92,
        "source": {
          "document_id": "doc_abc123",
          "title": "遮光窗帘布 - 产品说明",
          "doc_type": "processing_guide"
        }
      }
    ]
  }
}
```

---

## 六、异步任务架构

向量化是耗时操作（一个文档可能有几十块，每块都要调 Embedding API），必须异步处理。

### 6.1 任务流程

```
用户上传文档 → admin-api 创建文档记录 → 写入 embedding_tasks 表（status=pending）
                                                    │
                                                    ▼
                                      ai-agent-service 后台 Worker
                                      （定时轮询或 Redis 消息队列）
                                                    │
                            ┌───────────────────────┼───────────────────────┐
                            ▼                       ▼                       ▼
                      FabricChunker           Embedding 调用          DashVector 写入
                      分块处理                批量向量化（25条/批）    upsert_chunks
                                                    │
                                                    ▼
                                          更新 embedding_tasks 进度
                                          全部完成 → status=completed
                                          部分失败 → status=failed + 错误信息
```

### 6.2 Worker 实现

```python
# ai-agent-service/rag/worker.py

import asyncio
import asyncpg
from datetime import datetime

class EmbeddingWorker:
    """向量化异步 Worker"""

    def __init__(
        self,
        chunker,           # FabricChunker
        embedding_client,  # EmbeddingClient
        vector_store,      # DashVectorStore
        db_pool,           # asyncpg 连接池
        concurrency: int = 3,  # 并发任务数
    ):
        self.chunker = chunker
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.db_pool = db_pool
        self.concurrency = concurrency

    async def start(self):
        """启动 Worker（持续轮询）"""
        while True:
            try:
                await self.process_pending_tasks()
            except Exception as e:
                print(f"Worker 异常: {e}")
            await asyncio.sleep(5)  # 每 5 秒轮询一次

    async def process_pending_tasks(self):
        """处理待处理的向量化任务"""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT et.*, kd.content, kd.title, kd.category, kd.doc_type
                FROM embedding_tasks et
                JOIN knowledge_documents kd ON et.document_id = kd.id
                WHERE et.status = 'pending'
                ORDER BY et.created_at ASC
                LIMIT $1
            """, self.concurrency)

            for row in rows:
                asyncio.create_task(self.process_task(row))

    async def process_task(self, task_row):
        """处理单个向量化任务"""
        task_id = task_row["id"]
        document_id = task_row["document_id"]
        tenant_id = task_row["tenant_id"]
        content = task_row["content"]

        # 更新状态为处理中
        await self.update_task_status(task_id, "processing")

        try:
            # 1. 分块
            metadata = {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "category": task_row["category"],
                "doc_type": task_row["doc_type"],
            }
            chunks = self.chunker.chunk(content, metadata)

            # 更新分块数
            await self.update_task_progress(task_id, total_chunks=len(chunks))

            # 保存分块到数据库（BM25 检索用）
            await self.save_chunks_to_db(chunks)

            # 2. 向量化（批量调用 Embedding API）
            batch_size = 25
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                texts = [chunk.content for chunk in batch]
                embeddings = await self.embedding_client.embed_batch(texts)

                # 填充向量
                for chunk, embedding in zip(batch, embeddings):
                    chunk.embedding = embedding

                # 3. 写入 DashVector
                collection_name = f"tenant_{tenant_id}"
                self.vector_store.upsert_chunks(collection_name, batch)

                # 更新进度
                await self.update_task_progress(
                    task_id,
                    processed_chunks=min(i + batch_size, len(chunks))
                )

            # 全部完成
            await self.update_task_status(task_id, "completed")

            # 更新文档状态
            await self.update_document_embedding_status(
                document_id, "completed", len(chunks)
            )

        except Exception as e:
            await self.update_task_status(task_id, "failed", str(e))
            await self.update_document_embedding_status(document_id, "failed")

    async def save_chunks_to_db(self, chunks):
        """保存分块到 PostgreSQL（用于 BM25 检索）"""
        async with self.db_pool.acquire() as conn:
            for chunk in chunks:
                await conn.execute("""
                    INSERT INTO rag_chunks (chunk_id, tenant_id, document_id, content, metadata, chunk_index)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (chunk_id) DO UPDATE
                    SET content = EXCLUDED.content, metadata = EXCLUDED.metadata
                """, chunk.chunk_id, chunk.metadata["tenant_id"],
                    chunk.metadata["document_id"], chunk.content,
                    chunk.metadata, chunk.metadata["chunk_index"])

    async def update_task_status(self, task_id, status, error_message=None):
        """更新任务状态"""
        async with self.db_pool.acquire() as conn:
            if error_message:
                await conn.execute("""
                    UPDATE embedding_tasks
                    SET status = $1, error_message = $2, updated_at = NOW()
                    WHERE id = $3
                """, status, error_message, task_id)
            else:
                await conn.execute("""
                    UPDATE embedding_tasks
                    SET status = $1, updated_at = NOW()
                    WHERE id = $2
                """, status, task_id)

    async def update_task_progress(self, task_id, total_chunks=None, processed_chunks=None):
        """更新任务进度"""
        async with self.db_pool.acquire() as conn:
            set_parts = ["updated_at = NOW()"]
            params = []
            param_idx = 1

            if total_chunks is not None:
                set_parts.append(f"total_chunks = ${param_idx}")
                params.append(total_chunks)
                param_idx += 1

            if processed_chunks is not None:
                set_parts.append(f"processed_chunks = ${param_idx}")
                params.append(processed_chunks)
                param_idx += 1

            params.append(task_id)
            set_clause = ", ".join(set_parts)

            await conn.execute(f"""
                UPDATE embedding_tasks
                SET {set_clause}
                WHERE id = ${param_idx}
            """, *params)

    async def update_document_embedding_status(self, document_id, status, chunk_count=None):
        """更新文档向量化状态"""
        async with self.db_pool.acquire() as conn:
            if chunk_count is not None:
                await conn.execute("""
                    UPDATE knowledge_documents
                    SET embedding_status = $1, chunk_count = $2, updated_at = NOW()
                    WHERE id = $3
                """, status, chunk_count, document_id)
            else:
                await conn.execute("""
                    UPDATE knowledge_documents
                    SET embedding_status = $1, updated_at = NOW()
                    WHERE id = $2
                """, status, document_id)
```

---

## 七、与 Hermes Agent 集成

### 7.1 knowledge_search Tool 改造

```python
# ai-agent-service/packages/hermes-tools/knowledge_search.py

from hermes import Tool
from rag.retriever import HybridRetriever
from rag.prompt_builder import RAGPromptBuilder

def create_knowledge_search_tool(retriever, prompt_builder):
    """创建知识库查询 Tool"""

    async def execute(params: dict, context: ToolContext) -> dict:
        query = params.get("query", "")
        if not query:
            return {"error": "请提供查询内容"}

        # 获取租户配置
        tenant_id = context.tenant_id
        collection_name = f"tenant_{tenant_id}"

        # 混合检索
        filters = {"tenant_id": tenant_id}

        # 如果用户询问特定商品，加上商品过滤
        product_id = params.get("product_id") or context.get("product_id")
        if product_id:
            filters["product_id"] = product_id

        results = await retriever.retrieve(
            collection_name=collection_name,
            query=query,
            filters=filters,
        )

        if not results:
            return {
                "status": "no_result",
                "message": "抱歉，暂时没有相关资料。",
                "suggestion": "建议转人工客服进一步咨询。"
            }

        # 构造 RAG Prompt 并返回（由 Agent 传给 LLM）
        prompt = prompt_builder.build(
            query=query,
            search_results=results,
            company_name=context.get("company_name", "本公司"),
        )

        return {
            "status": "success",
            "prompt": prompt,
            "source_count": len(results),
            "sources": [
                {
                    "document_id": r.metadata.get("document_id"),
                    "doc_type": r.metadata.get("doc_type"),
                    "score": r.score,
                }
                for r in results[:3]  # 只返回前 3 个来源
            ]
        }

    return Tool(
        name="knowledge_search",
        description="查询面料知识库，获取产品说明、加工工艺、安装指南、保养方法等专业信息",
        parameters={
            "query": {
                "type": "string",
                "required": True,
                "description": "查询内容，如'遮光窗帘布打孔加工多少钱'"
            },
            "product_id": {
                "type": "string",
                "required": False,
                "description": "关联商品 ID（可选，用于缩小检索范围）"
            }
        },
        permissions={
            "require_auth": True,
            "data_scope": "tenant",
        },
        execute=execute
    )
```

### 7.2 Agent 中的使用流程

```
用户: "3 米遮光窗帘布 + 8 个打孔 + 6 米折边，一共多少钱？"

Hermes Agent ReAct 循环：
1. Thought: 用户询问价格，需要查询布料价格和加工费
2. Action: knowledge_search(query="遮光窗帘布 价格")
3. Observation: RAG 返回"遮光窗帘布 ¥128/米，打孔 ¥5/个，折边 ¥10/米"
4. Thought: 已有足够信息计算总价
5. Answer: "遮光窗帘布 3 米 × ¥128 = ¥384，打孔 8 个 × ¥5 = ¥40，折边 6 米 × ¥10 = ¥60，合计 ¥484。注：此为估算价，以实际下单为准。"
```

---

## 八、部署配置

### 8.1 DashVector 实例

```bash
# 阿里云 DashVector 控制台创建实例
# 规格建议：
# - 开发环境：标准版（按量付费）
# - 生产环境：专业版（包年包月）

# 环境变量
DASHVECTOR_API_KEY=sk-xxx
DASHVECTOR_ENDPOINT=https://vrs-cn-hangzhou.data.aliyun.com
DASHVECTOR_DIMENSION=1024
```

### 8.2 Embedding 调用配置

```python
# 环境变量
DASHSCOPE_API_KEY=sk-xxx
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_BATCH_SIZE=25  # DashScope 批量上限
EMBEDDING_RATE_LIMIT=10  # 每秒最大调用数
```

### 8.3 重排序模型部署

```bash
# 方案一：本地部署（SAE Python 应用）
# 依赖：FlagEmbedding
pip install FlagEmbedding

# SAE 资源配置
CPU: 0.5C
Memory: 1G
# 模型首次加载约 30 秒，后续推理 < 50ms/条

# 方案二：百炼 API 调用（无需部署）
# 使用百炼的 Rerank API（如果有）
```

### 8.4 PostgreSQL 全文检索配置

```sql
-- 确保安装了中文全文检索插件
CREATE EXTENSION IF NOT EXISTS zhparser;

-- 创建中文全文检索配置
CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = zhparser);
ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l WITH simple;

-- 在 rag_chunks 表上使用
ALTER TABLE rag_chunks ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('chinese', content)) STORED;
```

---

## 九、成本估算

| 组件 | 规格 | 月成本 | 说明 |
|------|------|--------|------|
| **DashVector** | 标准版（按量） | ~¥50/月 | 向量存储 + 检索，按调用量计费 |
| **Embedding 调用** | text-embedding-v3 | ~¥30/月 | 约 15,000 次调用/月（¥0.002/次） |
| **Reranker** | SAE 0.5C1G | ~¥20/月 | 本地部署 bge-reranker-large |
| **PostgreSQL 全文检索** | 已有 RDS 实例 | ¥0（增量） | 利用现有 RDS，无额外成本 |
| **合计** | | **~¥100/月** | 远低于百炼知识库付费方案 |

---

## 十、优化方向（后续迭代）

### Phase 1（本期实现）
- [x] FabricChunker 自定义分块
- [x] DashVector 向量存储
- [x] 混合检索（BM25 + 向量）
- [x] RAG Prompt 构造
- [x] 异步向量化 Worker

### Phase 2（下一步）
- [ ] 重排序（bge-reranker-large 部署）
- [ ] 检索缓存（相同查询直接返回）
- [ ] 检索效果评估（人工标注测试集）
- [ ] 动态调整 BM25/向量权重

### Phase 3（长期）
- [ ] 多路召回（分类召回 + 向量召回 + 业务规则召回）
- [ ] 用户反馈闭环（标记"有用/无用"自动优化检索策略）
- [ ] 知识库自动更新（商品变更自动触发文档更新）
- [ ] Embedding 模型微调（布艺行业语料 fine-tune）

---

## 十一、与原百炼知识库方案对比

| 维度 | 百炼知识库 | 自建 RAG（本方案） |
|------|-----------|-------------------|
| 检索精度 | 中（通用分块） | 高（行业定制分块 + 混合检索 + 重排序） |
| 多租户隔离 | 平台支持 | 自主控制（collection 级别） |
| 业务关联 | 弱（无法按商品/分类过滤） | 强（元数据过滤、关联查询） |
| 文档同步 | 手动/API 有限 | 完全可控（商品变更自动同步） |
| 工程复杂度 | 低（调 API） | 中（需搭建 RAG pipeline） |
| 成本 | 免费额度内 0 元 | ~¥100/月 |
| 可控性 | 平台黑盒 | 完全可控 |
| 可扩展性 | 受限于平台能力 | 灵活扩展 |

**结论**：对布艺行业场景，自建 RAG 方案在检索精度、业务关联、可控性上全面优于百炼知识库，成本增加约 ¥100/月，工程复杂度适中，强烈建议采用。
