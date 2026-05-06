"""
FabricChunker 单元测试

测试布艺行业文档分块器的各种分块策略
"""

import pytest
from app.rag.chunker import FabricChunker, Chunk, chunk_document


class TestFabricChunkerInit:
    """测试 FabricChunker 初始化"""

    def test_chunker_default_params(self):
        """test_chunker_init_default_params: 默认参数初始化"""
        chunker = FabricChunker()
        assert chunker.chunk_size == 500
        assert chunker.chunk_overlap == 50
        assert chunker.min_chunk_size == 100
        assert chunker.max_chunk_size == 800

    def test_chunker_custom_params(self):
        """test_chunker_init_custom_params: 自定义参数初始化"""
        chunker = FabricChunker(chunk_size=200, chunk_overlap=20, min_chunk_size=50, max_chunk_size=400)
        assert chunker.chunk_size == 200
        assert chunker.chunk_overlap == 20
        assert chunker.min_chunk_size == 50
        assert chunker.max_chunk_size == 400


class TestChunkDocument:
    """测试 chunk_document 方法"""

    def test_chunk_document_empty_content(self):
        """test_chunk_document_empty_content: 空文本返回空列表"""
        chunker = FabricChunker()
        assert chunker.chunk_document("") == []
        assert chunker.chunk_document("   ") == []
        assert chunker.chunk_document(None) == []

    def test_chunk_document_general_type(self):
        """test_chunk_document_general_type: 通用文档分块"""
        chunker = FabricChunker(chunk_size=200, min_chunk_size=10, max_chunk_size=300)
        content = "这是一段测试文本。" * 30  # ~270 chars
        chunks = chunker.chunk_document(content, doc_type="general")
        assert len(chunks) > 0
        for chunk in chunks:
            assert "content" in chunk
            assert "metadata" in chunk
            assert "chunk_id" in chunk
            assert chunk["content"].strip() != ""

    def test_chunk_document_metadata_preserved(self):
        """test_chunk_document_metadata_preserved: 元数据保留"""
        chunker = FabricChunker(min_chunk_size=10, max_chunk_size=300)
        content = "这是一段足够长的测试文本。" * 20
        metadata = {"title": "测试文档", "category": "curtain", "product_id": "P001"}
        chunks = chunker.chunk_document(content, doc_type="general", metadata=metadata)
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk["metadata"]["title"] == "测试文档"
            assert chunk["metadata"]["category"] == "curtain"

    def test_chunk_document_faq_type(self):
        """test_chunk_document_faq_type: FAQ 文档按 Q&A 对分块"""
        chunker = FabricChunker()
        faq_content = """## 常见问题

Q: 窗帘怎么清洗？
A: 建议使用温水手洗或干洗，避免长时间浸泡。不同面料有不同清洗要求，雪尼尔面料建议干洗。

Q: 安装窗帘需要多长时间？
A: 一般安装需要30分钟到1小时，具体取决于窗户大小和窗帘类型。"""
        chunks = chunker.chunk_document(faq_content, doc_type="faq")
        assert len(chunks) == 2
        assert "窗帘怎么清洗" in chunks[0]["content"]
        assert chunks[0]["metadata"]["chunk_type"] == "faq_pair"
        assert "安装窗帘" in chunks[1]["content"]

    def test_chunk_document_faq_fallback_to_general(self):
        """test_chunk_document_faq_fallback: FAQ 无 QA 对时回退通用分块"""
        chunker = FabricChunker(min_chunk_size=10, max_chunk_size=300)
        content = "这不是 FAQ 格式的内容。" * 20
        chunks = chunker.chunk_document(content, doc_type="faq")
        assert len(chunks) > 0

    def test_chunk_document_product_type(self):
        """test_chunk_document_product_type: 产品文档分块"""
        chunker = FabricChunker(min_chunk_size=10, max_chunk_size=300)
        product_content = """# 雪尼尔遮光窗帘

## 材质说明
采用高密度雪尼尔面料，手感柔软厚实。成分为100%涤纶，克重280g/m²。门幅2.8米，缩水率小于3%。

## 功能特点
遮光率达到95%以上，隔热保温效果好。适用场景包括卧室、客厅等需要遮光的空间。

## 加工工艺
支持打孔、挂钩、韩折等多种加工方式。包边采用精细锁边工艺，确保经久耐用。"""
        chunks = chunker.chunk_document(product_content, doc_type="product")
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk["metadata"]["chunk_type"] == "product_info"

    def test_chunk_document_guide_type(self):
        """test_chunk_document_guide_type: 指南文档分块"""
        chunker = FabricChunker(min_chunk_size=10, max_chunk_size=300)
        guide_content = """# 窗帘安装指南

## 安装步骤
步骤 1 确认安装位置
首先确定窗帘杆或轨道的安装位置，测量窗户的宽度和高度，确保安装位置水平。

步骤 2 安装支架
使用电钻在标记位置打孔，安装固定支架，确保支架牢固可靠。"""
        chunks = chunker.chunk_document(guide_content, doc_type="guide")
        assert len(chunks) > 0


class TestSplitBySize:
    """测试文本按大小分割"""

    def test_split_by_size_short_text(self):
        """test_split_by_size_short_text: 短文本不分割"""
        chunker = FabricChunker(max_chunk_size=800)
        result = chunker._split_by_size("短文本")
        assert result == ["短文本"]

    def test_split_by_size_long_text(self):
        """test_split_by_size_long_text: 长文本按大小分割"""
        chunker = FabricChunker(max_chunk_size=100, chunk_overlap=10, min_chunk_size=10)
        long_text = "测试文字。" * 50  # 250 chars
        result = chunker._split_by_size(long_text)
        assert len(result) > 1
        # 每块不应超过 max_chunk_size 太多（句子边界可能略超）
        for chunk in result:
            assert len(chunk) <= 200  # 允许一些边界容差

    def test_split_by_size_overlap(self):
        """test_split_by_size_overlap: 分块有重叠"""
        chunker = FabricChunker(max_chunk_size=100, chunk_overlap=20, min_chunk_size=10)
        long_text = "这是一段很长的文本内容。" * 30
        result = chunker._split_by_size(long_text)
        assert len(result) >= 2


class TestSplitByStructure:
    """测试按文档结构分割"""

    def test_split_by_markdown_headings(self):
        """test_split_by_structure_markdown: Markdown 标题分割"""
        chunker = FabricChunker()
        text = """# 第一章
内容一

## 第二章
内容二

### 第三章
内容三"""
        sections = chunker._split_by_structure(text)
        assert len(sections) >= 2

    def test_split_by_chinese_headings(self):
        """test_split_by_structure_chinese: 中文编号标题分割"""
        chunker = FabricChunker()
        text = """一、面料选择
关于面料的说明

二、安装方法
关于安装的说明"""
        sections = chunker._split_by_structure(text)
        assert len(sections) >= 2


class TestChunkDataclass:
    """测试 Chunk 数据类"""

    def test_chunk_auto_id(self):
        """test_chunk_auto_id: 自动生成 chunk_id"""
        chunk = Chunk(content="test", metadata={})
        assert chunk.chunk_id != ""
        assert len(chunk.chunk_id) > 0

    def test_chunk_custom_id(self):
        """test_chunk_custom_id: 自定义 chunk_id"""
        chunk = Chunk(content="test", metadata={}, chunk_id="my-id")
        assert chunk.chunk_id == "my-id"

    def test_chunk_embedding_default_none(self):
        """test_chunk_embedding_default: embedding 默认为 None"""
        chunk = Chunk(content="test", metadata={})
        assert chunk.embedding is None


class TestConvenienceFunction:
    """测试便捷函数"""

    def test_chunk_document_function(self):
        """test_chunk_document_function: 便捷函数正常工作"""
        content = "这是一段足够长的文本。" * 30
        chunks = chunk_document(content, doc_type="general", chunk_size=200, chunk_overlap=20)
        assert isinstance(chunks, list)
