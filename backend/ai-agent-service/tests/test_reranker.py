"""
RAG 重排序 (Reranker) 单元测试

测试覆盖：
- DashScopeReranker 初始化
- rerank 降级策略（API 失败时返回原始排序）
- reranker 在 pipeline 中的集成
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.rag.reranker import DashScopeReranker, get_reranker, reset_reranker


# ========== 测试文档数据 ==========

SAMPLE_DOCS = [
    {"content": "窗帘安装步骤：第一步，测量窗户尺寸", "score": 0.8},
    {"content": "雪尼尔面料特点：厚实保暖，遮光性好", "score": 0.75},
    {"content": "退货政策：7天无理由退货", "score": 0.7},
    {"content": "窗帘清洗方法：建议干洗或轻柔水洗", "score": 0.65},
    {"content": "打孔窗帘安装说明：使用专用打孔工具", "score": 0.6},
]


# ========== DashScopeReranker 初始化测试 ==========

class TestDashScopeRerankerInit:
    """重排序器初始化测试"""

    @patch("app.rag.reranker.settings")
    def test_init_with_api_key(self, mock_settings):
        """有 API Key 时正常初始化"""
        mock_settings.RERANK_MODEL = "gte-rerank"
        mock_settings.DASHSCOPE_API_KEY = "test-key"

        reranker = DashScopeReranker()
        assert reranker.model == "gte-rerank"
        assert reranker._available is True

    @patch("app.rag.reranker.DASHSCOPE_API_KEY", "")
    @patch("app.rag.reranker.settings")
    def test_init_without_api_key(self, mock_settings):
        """无 API Key 时 reranker 不可用"""
        mock_settings.RERANK_MODEL = "gte-rerank"

        reranker = DashScopeReranker()
        assert reranker._available is False

    @patch("app.rag.reranker.settings")
    def test_init_custom_model(self, mock_settings):
        """自定义模型名"""
        mock_settings.RERANK_MODEL = "gte-rerank"
        mock_settings.DASHSCOPE_API_KEY = "key"

        reranker = DashScopeReranker(model="custom-rerank")
        assert reranker.model == "custom-rerank"


# ========== rerank 方法测试 ==========

class TestDashScopeRerankerRerank:
    """rerank 方法测试"""

    @pytest.fixture
    def reranker(self):
        with patch("app.rag.reranker.settings") as mock_settings:
            mock_settings.RERANK_MODEL = "gte-rerank"
            mock_settings.DASHSCOPE_API_KEY = "test-key"
            return DashScopeReranker()

    @pytest.mark.asyncio
    async def test_rerank_empty_docs(self, reranker):
        """空文档列表 → 空列表"""
        result = await reranker.rerank("query", [], top_k=3)
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_docs_fewer_than_top_k(self, reranker):
        """文档数 <= top_k → 直接返回原列表"""
        docs = SAMPLE_DOCS[:2]
        result = await reranker.rerank("query", docs, top_k=3)
        assert result == docs

    @pytest.mark.asyncio
    async def test_rerank_unavailable_fallback(self):
        """API Key 为空时降级返回原始排序"""
        with patch("app.rag.reranker.settings") as mock_settings:
            mock_settings.RERANK_MODEL = "gte-rerank"
            mock_settings.DASHSCOPE_API_KEY = ""
            reranker = DashScopeReranker()

        result = await reranker.rerank("安装窗帘", SAMPLE_DOCS, top_k=3)
        assert len(result) == 3
        assert result == SAMPLE_DOCS[:3]

    @pytest.mark.asyncio
    async def test_rerank_api_success(self, reranker):
        """API 成功时按重排序结果返回"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.output = {
            "results": [
                {"index": 4, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.88},
                {"index": 3, "relevance_score": 0.75},
            ]
        }

        with patch("app.rag.reranker.TextReRank") as MockTextReRank:
            MockTextReRank.call = MagicMock(return_value=mock_resp)
            result = await reranker.rerank("安装窗帘", SAMPLE_DOCS, top_k=3)

        assert len(result) == 3
        assert result[0]["rerank_score"] == 0.95
        assert result[0]["content"] == SAMPLE_DOCS[4]["content"]
        assert result[1]["rerank_score"] == 0.88

    @pytest.mark.asyncio
    async def test_rerank_api_failure_fallback(self, reranker):
        """API 返回错误时降级"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.code = "InternalError"
        mock_resp.message = "Server error"

        with patch("app.rag.reranker.TextReRank") as MockTextReRank:
            MockTextReRank.call = MagicMock(return_value=mock_resp)
            result = await reranker.rerank("安装窗帘", SAMPLE_DOCS, top_k=3)

        assert len(result) == 3
        assert result == SAMPLE_DOCS[:3]

    @pytest.mark.asyncio
    async def test_rerank_exception_fallback(self, reranker):
        """API 异常时降级"""
        with patch("app.rag.reranker.TextReRank") as MockTextReRank:
            MockTextReRank.call = MagicMock(side_effect=Exception("Network error"))
            result = await reranker.rerank("安装窗帘", SAMPLE_DOCS, top_k=3)

        assert len(result) == 3
        assert result == SAMPLE_DOCS[:3]

    @pytest.mark.asyncio
    async def test_rerank_empty_api_results_fallback(self, reranker):
        """API 返回空结果时降级"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.output = {"results": []}

        with patch("app.rag.reranker.TextReRank") as MockTextReRank:
            MockTextReRank.call = MagicMock(return_value=mock_resp)
            result = await reranker.rerank("安装窗帘", SAMPLE_DOCS, top_k=3)

        assert len(result) == 3
        assert result == SAMPLE_DOCS[:3]


# ========== 降级策略测试 ==========

class TestFallback:
    """降级策略静态方法测试"""

    def test_fallback_returns_top_k(self):
        """fallback 返回前 top_k 个文档"""
        result = DashScopeReranker._fallback(SAMPLE_DOCS, 3)
        assert len(result) == 3
        assert result == SAMPLE_DOCS[:3]

    def test_fallback_fewer_docs(self):
        """文档数少于 top_k 时返回全部"""
        result = DashScopeReranker._fallback(SAMPLE_DOCS[:2], 5)
        assert len(result) == 2


# ========== 单例管理测试 ==========

class TestRerankerSingleton:
    """单例管理测试"""

    def setup_method(self):
        reset_reranker()

    @pytest.mark.asyncio
    async def test_get_reranker_singleton(self):
        """get_reranker 返回单例"""
        with patch("app.rag.reranker.settings") as mock_settings:
            mock_settings.RERANK_MODEL = "gte-rerank"
            mock_settings.DASHSCOPE_API_KEY = "test-key"

            r1 = await get_reranker()
            r2 = await get_reranker()
            assert r1 is r2

    def test_reset_reranker(self):
        """reset_reranker 清除实例"""
        reset_reranker()
        # 不应抛异常
