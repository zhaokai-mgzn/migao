"""
知识库搜索 Tool 单元测试

测试 KnowledgeSearchTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from app.tools.knowledge_search import KnowledgeSearchTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return KnowledgeSearchTool()


@dataclass
class MockHybridSearchResult:
    """模拟 HybridSearchResult 对象"""
    chunk_id: str
    content: str
    score: float
    vector_score: float
    bm25_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def sample_search_results():
    """模拟 RAG 检索结果"""
    return [
        MockHybridSearchResult(
            chunk_id="chunk_001",
            content="雪尼尔面料是一种环保面料，具有良好的遮光性和垂感。",
            score=0.92,
            vector_score=0.90,
            bm25_score=0.85,
            metadata={"doc_type": "fabric_knowledge", "title": "雪尼尔面料介绍"},
        ),
        MockHybridSearchResult(
            chunk_id="chunk_002",
            content="雪尼尔窗帘清洗建议：可机洗，水温不超过30度，不可漂白。",
            score=0.88,
            vector_score=0.85,
            bm25_score=0.80,
            metadata={"doc_type": "maintenance", "title": "窗帘保养指南"},
        ),
        MockHybridSearchResult(
            chunk_id="chunk_003",
            content="雪尼尔面料不易起球，但需注意避免尖锐物体刮擦。",
            score=0.75,
            vector_score=0.70,
            bm25_score=0.72,
            metadata={"doc_type": "faq", "title": "常见问题"},
        ),
    ]


class TestKnowledgeSearchSuccess:
    """知识库搜索 - 成功场景"""

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", True)
    @patch("app.tools.knowledge_search.search_knowledge", new_callable=AsyncMock)
    async def test_knowledge_search_success(
        self, mock_search, tool, sample_tool_context, sample_search_results
    ):
        """正常检索返回结果"""
        mock_search.return_value = sample_search_results

        result = await tool.execute(
            context=sample_tool_context,
            query="雪尼尔面料会不会起球",
        )

        assert result.success is True
        assert result.data["source_count"] == 3
        assert len(result.data["chunks"]) == 3
        assert result.data["chunks"][0]["chunk_id"] == "chunk_001"
        assert result.data["chunks"][0]["score"] == 0.92
        assert "context" in result.data
        assert "找到" in result.message

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", True)
    @patch("app.tools.knowledge_search.search_knowledge", new_callable=AsyncMock)
    async def test_knowledge_search_with_doc_type(
        self, mock_search, tool, sample_tool_context, sample_search_results
    ):
        """带 doc_type 过滤的检索"""
        mock_search.return_value = [sample_search_results[0]]

        result = await tool.execute(
            context=sample_tool_context,
            query="雪尼尔面料",
            doc_type="fabric_knowledge",
        )

        assert result.success is True
        # 验证 filters 被正确传递
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("filters") == {"doc_type": "fabric_knowledge"} or \
               (call_kwargs[1] if len(call_kwargs) > 1 else {}).get("filters") == {"doc_type": "fabric_knowledge"}

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", True)
    @patch("app.tools.knowledge_search.search_knowledge", new_callable=AsyncMock)
    async def test_knowledge_search_with_top_k(
        self, mock_search, tool, sample_tool_context, sample_search_results
    ):
        """自定义 top_k 参数"""
        mock_search.return_value = sample_search_results[:1]

        result = await tool.execute(
            context=sample_tool_context,
            query="窗帘清洗",
            top_k=1,
        )

        assert result.success is True
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("top_k") == 1


class TestKnowledgeSearchEmpty:
    """知识库搜索 - 空结果场景"""

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", True)
    @patch("app.tools.knowledge_search.search_knowledge", new_callable=AsyncMock)
    async def test_knowledge_search_no_results(
        self, mock_search, tool, sample_tool_context
    ):
        """检索无结果"""
        mock_search.return_value = []

        result = await tool.execute(
            context=sample_tool_context,
            query="火星窗帘安装",
        )

        assert result.success is True
        assert result.data["chunks"] == []
        assert result.data["source_count"] == 0
        assert "没有" in result.message or "暂时" in result.message


class TestKnowledgeSearchRagUnavailable:
    """知识库搜索 - RAG 不可用"""

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", False)
    async def test_knowledge_search_rag_not_available(
        self, tool, sample_tool_context
    ):
        """RAG 模块未加载"""
        result = await tool.execute(
            context=sample_tool_context,
            query="窗帘怎么清洗",
        )

        assert result.success is True
        assert result.data["chunks"] == []
        assert "暂未开启" in result.message or "人工客服" in result.message


class TestKnowledgeSearchValidation:
    """知识库搜索 - 参数验证"""

    async def test_knowledge_search_empty_query(self, tool, sample_tool_context):
        """空查询"""
        result = await tool.execute(
            context=sample_tool_context,
            query="",
        )

        assert result.success is False
        assert "为空" in result.error or "请提供" in result.message

    async def test_knowledge_search_whitespace_query(self, tool, sample_tool_context):
        """仅空白字符查询"""
        result = await tool.execute(
            context=sample_tool_context,
            query="   ",
        )

        assert result.success is False

    async def test_knowledge_search_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色检索被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            query="窗帘怎么清洗",
        )

        assert result.success is False
        assert "权限" in result.error or "权限" in result.message


class TestKnowledgeSearchError:
    """知识库搜索 - 异常处理"""

    @patch("app.tools.knowledge_search._RAG_AVAILABLE", True)
    @patch("app.tools.knowledge_search.search_knowledge", new_callable=AsyncMock)
    async def test_knowledge_search_exception(
        self, mock_search, tool, sample_tool_context
    ):
        """RAG 检索异常"""
        mock_search.side_effect = Exception("Vector store connection failed")

        result = await tool.execute(
            context=sample_tool_context,
            query="窗帘保养",
        )

        assert result.success is False
        assert "失败" in result.message or "重试" in result.message


class TestKnowledgeSearchFormatAndContext:
    """知识库搜索 - _format_chunks 和 _build_context 方法"""

    def test_format_chunks(self, tool, sample_search_results):
        """格式化检索结果"""
        chunks = tool._format_chunks(sample_search_results)

        assert len(chunks) == 3
        assert chunks[0]["index"] == 1
        assert chunks[0]["chunk_id"] == "chunk_001"
        assert chunks[0]["score"] == 0.92
        assert chunks[0]["source"] == "fabric_knowledge"
        assert chunks[2]["index"] == 3

    def test_build_context(self, tool, sample_search_results):
        """构建上下文文本"""
        context = tool._build_context(sample_search_results)

        assert "[资料1]" in context
        assert "[资料2]" in context
        assert "[资料3]" in context
        assert "雪尼尔面料介绍" in context
        assert "窗帘保养指南" in context
        assert "雪尼尔面料是一种环保面料" in context

    def test_build_context_no_title(self, tool):
        """构建上下文 - 无标题时使用 doc_type"""
        results = [
            MockHybridSearchResult(
                chunk_id="chunk_notitle",
                content="测试内容",
                score=0.8,
                vector_score=0.8,
                bm25_score=0.7,
                metadata={"doc_type": "faq"},
            ),
        ]
        context = tool._build_context(results)

        assert "[资料1]" in context
        assert "faq" in context
