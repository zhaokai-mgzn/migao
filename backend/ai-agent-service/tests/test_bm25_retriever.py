"""
BM25Retriever 单元测试

测试基于 PostgreSQL 全文搜索的 BM25 检索器
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.rag.bm25_retriever import BM25Retriever, BM25SearchResult, get_bm25_retriever, reset_bm25_retriever


class TestBM25SearchResult:
    """测试 BM25SearchResult 数据类"""

    def test_bm25_search_result_creation(self):
        """test_bm25_result_creation: 正常创建"""
        result = BM25SearchResult(
            chunk_id="chunk_001",
            content="窗帘面料说明",
            score=0.85,
            metadata={"doc_type": "product"},
        )
        assert result.chunk_id == "chunk_001"
        assert result.content == "窗帘面料说明"
        assert result.score == 0.85
        assert result.metadata["doc_type"] == "product"


class TestBuildSearchQuery:
    """测试 SQL 查询构建"""

    def test_build_search_query_basic(self):
        """test_build_query_basic: 基础查询构建"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query("窗帘", tenant_id=1, top_k=10)
        assert "rag_chunks" in sql
        assert "tenant_id = :tenant_id" in sql
        assert "plainto_tsquery" in sql
        assert params["query"] == "窗帘"
        assert params["tenant_id"] == 1
        assert params["top_k"] == 10

    def test_build_search_query_with_doc_type_filter(self):
        """test_build_query_doc_type_filter: 带 doc_type 过滤"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query(
            "面料", tenant_id=1, filters={"doc_type": "faq"}, top_k=5
        )
        assert "metadata->>'doc_type' = :doc_type" in sql
        assert params["doc_type"] == "faq"

    def test_build_search_query_with_category_filter(self):
        """test_build_query_category_filter: 带 category 过滤"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query(
            "面料", tenant_id=1, filters={"category": "curtain"}, top_k=5
        )
        assert "metadata->>'category' = :category" in sql
        assert params["category"] == "curtain"

    def test_build_search_query_with_product_id_filter(self):
        """test_build_query_product_id_filter: 带 product_id 过滤"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query(
            "面料", tenant_id=1, filters={"product_id": "P001"}, top_k=5
        )
        assert "metadata->>'product_id' = :product_id" in sql
        assert params["product_id"] == "P001"

    def test_build_search_query_with_document_id_filter(self):
        """test_build_query_document_id_filter: 带 document_id 过滤"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query(
            "面料", tenant_id=1, filters={"document_id": "doc_001"}, top_k=5
        )
        assert "document_id = :document_id" in sql
        assert params["document_id"] == "doc_001"

    def test_build_search_query_with_multiple_filters(self):
        """test_build_query_multiple_filters: 多条件过滤"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query(
            "面料", tenant_id=1,
            filters={"doc_type": "product", "category": "curtain"},
            top_k=5,
        )
        assert "doc_type" in sql
        assert "category" in sql
        assert params["doc_type"] == "product"
        assert params["category"] == "curtain"

    def test_build_search_query_order_and_limit(self):
        """test_build_query_order_limit: 排序和限制"""
        retriever = BM25Retriever()
        sql, params = retriever._build_search_query("窗帘", tenant_id=1, top_k=3)
        assert "ORDER BY rank_score DESC" in sql
        assert "LIMIT :top_k" in sql
        assert params["top_k"] == 3


class TestBM25Search:
    """测试 BM25 搜索方法"""

    async def test_search_empty_query(self):
        """test_search_empty_query: 空查询返回空结果"""
        retriever = BM25Retriever()
        retriever._available = True
        retriever._availability_checked = True
        result = await retriever.search("", tenant_id=1)
        assert result == []
        result = await retriever.search("   ", tenant_id=1)
        assert result == []

    async def test_search_empty_tenant_id(self):
        """test_search_empty_tenant_id: 空 tenant_id 返回空结果"""
        retriever = BM25Retriever()
        retriever._available = True
        retriever._availability_checked = True
        result = await retriever.search("窗帘", tenant_id=0)
        assert result == []

    async def test_search_when_unavailable(self):
        """test_search_unavailable: BM25 不可用时静默返回空结果"""
        retriever = BM25Retriever()
        retriever._available = False
        retriever._availability_checked = True
        result = await retriever.search("窗帘", tenant_id=1)
        assert result == []

    @patch("app.rag.bm25_retriever.AsyncSessionLocal")
    async def test_search_normal_flow(self, mock_session_local):
        """test_search_normal_flow: 正常搜索流程"""
        # Mock 数据库行
        mock_row = MagicMock()
        mock_row.chunk_id = "chunk_001"
        mock_row.content = "窗帘面料说明"
        mock_row.rank_score = 0.85
        mock_row.metadata = {"doc_type": "product"}
        mock_row.document_id = "doc_001"
        mock_row.chunk_index = 0

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        retriever = BM25Retriever()
        retriever._available = True
        retriever._availability_checked = True
        results = await retriever.search("窗帘", tenant_id=1, top_k=5)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk_001"
        assert results[0].content == "窗帘面料说明"
        assert results[0].score == 0.85
        assert results[0].metadata["document_id"] == "doc_001"

    @patch("app.rag.bm25_retriever.AsyncSessionLocal")
    async def test_search_db_exception_returns_empty(self, mock_session_local):
        """test_search_db_exception: 数据库异常返回空结果"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB connection error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        retriever = BM25Retriever()
        retriever._available = True
        retriever._availability_checked = True
        results = await retriever.search("窗帘", tenant_id=1)
        assert results == []

    async def test_search_with_session_empty_query(self, mock_db_session):
        """test_search_with_session_empty: 空查询返回空"""
        retriever = BM25Retriever()
        result = await retriever.search_with_session(mock_db_session, "", tenant_id=1)
        assert result == []

    async def test_search_with_session_empty_tenant(self, mock_db_session):
        """test_search_with_session_empty_tenant: 空 tenant 返回空"""
        retriever = BM25Retriever()
        result = await retriever.search_with_session(mock_db_session, "窗帘", tenant_id=0)
        assert result == []

    async def test_search_with_session_normal(self, mock_db_session):
        """test_search_with_session_normal: 使用 session 正常搜索"""
        mock_row = MagicMock()
        mock_row.chunk_id = "chunk_002"
        mock_row.content = "产品信息"
        mock_row.rank_score = 0.75
        mock_row.metadata = {}
        mock_row.document_id = "doc_002"
        mock_row.chunk_index = 1

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        retriever = BM25Retriever()
        results = await retriever.search_with_session(
            mock_db_session, "产品", tenant_id=1, top_k=5
        )
        assert len(results) == 1
        assert results[0].chunk_id == "chunk_002"


class TestBM25Availability:
    """测试 BM25 可用性检查"""

    @patch("app.rag.bm25_retriever.AsyncSessionLocal")
    async def test_check_availability_all_ok(self, mock_session_local):
        """test_check_availability_ok: 全部检查通过"""
        mock_session = AsyncMock()
        # 三次 scalar 调用: zhparser, table, column
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        retriever = BM25Retriever()
        available = await retriever.check_availability()
        assert available is True

    @patch("app.rag.bm25_retriever.AsyncSessionLocal")
    async def test_check_availability_exception(self, mock_session_local):
        """test_check_availability_exception: 异常时返回 False"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        retriever = BM25Retriever()
        available = await retriever.check_availability()
        assert available is False


class TestBM25Singleton:
    """测试单例模式"""

    @patch("app.rag.bm25_retriever.BM25Retriever.check_availability", new_callable=AsyncMock, return_value=False)
    async def test_get_bm25_retriever_singleton(self, mock_check):
        """test_singleton: 单例模式"""
        reset_bm25_retriever()
        r1 = await get_bm25_retriever()
        r2 = await get_bm25_retriever()
        assert r1 is r2
        reset_bm25_retriever()

    @patch("app.rag.bm25_retriever.BM25Retriever.check_availability", new_callable=AsyncMock, return_value=False)
    async def test_reset_bm25_retriever(self, mock_check):
        """test_reset: 重置后重新创建"""
        reset_bm25_retriever()
        r1 = await get_bm25_retriever()
        reset_bm25_retriever()
        r2 = await get_bm25_retriever()
        assert r1 is not r2
        reset_bm25_retriever()
