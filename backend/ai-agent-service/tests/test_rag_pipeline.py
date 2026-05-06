"""
RAGPipeline 单元测试

测试 RAG 文档处理管道：文档处理、混合检索、删除等
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.rag.pipeline import RAGPipeline, reset_rag_pipeline
from app.rag.chunker import FabricChunker
from app.rag.retriever import HybridSearchResult


class TestRAGPipelineInit:
    """测试 RAGPipeline 初始化"""

    def test_pipeline_default_init(self):
        """test_pipeline_default_init: 默认初始化"""
        pipeline = RAGPipeline()
        assert isinstance(pipeline.chunker, FabricChunker)
        assert pipeline.vector_store is None
        assert pipeline.retriever is None

    def test_pipeline_custom_components(self):
        """test_pipeline_custom_components: 自定义组件初始化"""
        mock_chunker = MagicMock(spec=FabricChunker)
        mock_vs = AsyncMock()
        mock_retriever = AsyncMock()
        pipeline = RAGPipeline(
            chunker=mock_chunker,
            vector_store=mock_vs,
            retriever=mock_retriever,
        )
        assert pipeline.chunker is mock_chunker
        assert pipeline.vector_store is mock_vs
        assert pipeline.retriever is mock_retriever


class TestParseFile:
    """测试文件解析"""

    def test_parse_file_txt_content(self):
        """test_parse_file_txt: 解析 txt 二进制内容"""
        content = RAGPipeline.parse_file(
            file_content=b"\xe8\xbf\x99\xe6\x98\xaf\xe6\xb5\x8b\xe8\xaf\x95",  # "这是测试"
            file_name="test.txt",
        )
        assert content == "这是测试"

    def test_parse_file_md_content(self):
        """test_parse_file_md: 解析 md 二进制内容"""
        content = RAGPipeline.parse_file(
            file_content=b"# Title\nHello",
            file_name="doc.md",
        )
        assert "# Title" in content

    def test_parse_file_unknown_ext(self):
        """test_parse_file_unknown_ext: 未知扩展名当纯文本"""
        content = RAGPipeline.parse_file(
            file_content=b"plain text",
            file_name="data.xyz",
        )
        assert content == "plain text"


class TestProcessDocument:
    """测试文档处理流程"""

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_process_document_normal(self, mock_session_local):
        """test_process_document_normal: 正常文档处理"""
        # Mock DB session
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        # Mock vector store
        mock_vs = AsyncMock()
        mock_vs._available = True
        mock_vs.upsert_documents = AsyncMock(return_value=True)

        # Mock retriever
        mock_retriever = AsyncMock()

        pipeline = RAGPipeline(vector_store=mock_vs, retriever=mock_retriever)

        content = "这是一段关于窗帘面料的详细说明文档，介绍了各种面料的特性。" * 10
        doc_id = await pipeline.process_document(
            content=content,
            metadata={"title": "面料说明", "doc_type": "product"},
            tenant_id=1,
            doc_id="doc_test_001",
        )
        assert doc_id == "doc_test_001"
        # 验证 DB 保存被调用
        assert mock_session.execute.called
        assert mock_session.commit.called

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_process_document_auto_doc_id(self, mock_session_local):
        """test_process_document_auto_id: 自动生成 doc_id"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        mock_vs = AsyncMock()
        mock_vs._available = False

        pipeline = RAGPipeline(vector_store=mock_vs, retriever=AsyncMock())
        content = "这是一段关于窗帘面料的详细说明文档内容。" * 10
        doc_id = await pipeline.process_document(
            content=content,
            metadata={"doc_type": "general"},
            tenant_id=1,
        )
        assert doc_id.startswith("doc_")

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_process_document_vector_store_unavailable(self, mock_session_local):
        """test_process_document_vs_unavailable: VectorStore 不可用时仍保存到 DB"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        mock_vs = AsyncMock()
        mock_vs._available = False

        pipeline = RAGPipeline(vector_store=mock_vs, retriever=AsyncMock())
        content = "窗帘保养指南内容说明文档。" * 15
        doc_id = await pipeline.process_document(
            content=content,
            metadata={"doc_type": "guide"},
            tenant_id=1,
            doc_id="doc_no_vs",
        )
        assert doc_id == "doc_no_vs"
        # vector_store.upsert_documents should NOT be called
        mock_vs.upsert_documents.assert_not_called()

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_process_document_empty_chunks(self, mock_session_local):
        """test_process_document_empty_chunks: 分块为空时仍返回 doc_id"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        # 使用 mock chunker 返回空列表
        mock_chunker = MagicMock()
        mock_chunker.chunk_document.return_value = []

        pipeline = RAGPipeline(chunker=mock_chunker, vector_store=AsyncMock(), retriever=AsyncMock())
        doc_id = await pipeline.process_document(
            content="短文本",
            metadata={},
            tenant_id=1,
            doc_id="doc_empty",
        )
        assert doc_id == "doc_empty"


class TestQuery:
    """测试混合检索查询"""

    async def test_query_normal(self):
        """test_query_normal: 正常检索"""
        mock_retriever = AsyncMock()
        mock_retriever.search_with_fallback = AsyncMock(return_value=[
            HybridSearchResult(
                chunk_id="c1", content="窗帘面料", score=0.9, metadata={}
            ),
        ])

        pipeline = RAGPipeline(
            vector_store=AsyncMock(),
            retriever=mock_retriever,
        )
        results = await pipeline.query("窗帘面料", tenant_id=1, top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    async def test_query_no_retriever(self):
        """test_query_no_retriever: retriever 为 None 时返回空"""
        pipeline = RAGPipeline(vector_store=AsyncMock(), retriever=None)
        # Mock _ensure_components to not actually create retriever
        pipeline._ensure_components = AsyncMock()
        pipeline.retriever = None
        results = await pipeline.query("窗帘", tenant_id=1)
        assert results == []

    async def test_query_exception_returns_empty(self):
        """test_query_exception: 异常时返回空列表"""
        mock_retriever = AsyncMock()
        mock_retriever.search_with_fallback = AsyncMock(
            side_effect=Exception("Search error")
        )
        pipeline = RAGPipeline(
            vector_store=AsyncMock(),
            retriever=mock_retriever,
        )
        results = await pipeline.query("窗帘", tenant_id=1)
        assert results == []


class TestDeleteDocument:
    """测试文档删除"""

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_delete_document_normal(self, mock_session_local):
        """test_delete_document_normal: 正常删除"""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        mock_vs = AsyncMock()
        mock_vs._available = True
        mock_vs.delete_document = AsyncMock(return_value=True)

        pipeline = RAGPipeline(vector_store=mock_vs, retriever=AsyncMock())
        success = await pipeline.delete_document("doc_001", tenant_id=1)
        assert success is True
        mock_vs.delete_document.assert_called_once()

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_delete_document_exception(self, mock_session_local):
        """test_delete_document_exception: 删除异常返回 False"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        mock_vs = AsyncMock()
        mock_vs._available = True
        mock_vs.delete_document = AsyncMock(return_value=True)

        pipeline = RAGPipeline(vector_store=mock_vs, retriever=AsyncMock())
        success = await pipeline.delete_document("doc_001", tenant_id=1)
        assert success is False


class TestGetDocumentChunks:
    """测试获取文档分块"""

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_get_document_chunks_normal(self, mock_session_local):
        """test_get_chunks_normal: 正常获取分块"""
        mock_row = MagicMock()
        mock_row.chunk_id = "c1"
        mock_row.content = "内容"
        mock_row.metadata = {"doc_type": "faq"}
        mock_row.chunk_index = 0
        mock_row.created_at = None

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        pipeline = RAGPipeline()
        chunks = await pipeline.get_document_chunks("doc_001", tenant_id=1)
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "c1"

    @patch("app.rag.pipeline.AsyncSessionLocal")
    async def test_get_document_chunks_exception(self, mock_session_local):
        """test_get_chunks_exception: 异常返回空列表"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_local.return_value = mock_session

        pipeline = RAGPipeline()
        chunks = await pipeline.get_document_chunks("doc_001", tenant_id=1)
        assert chunks == []


class TestSingleton:
    """测试单例模式"""

    def test_reset_rag_pipeline(self):
        """test_reset_pipeline: 重置单例"""
        reset_rag_pipeline()
        # 不抛异常即可
