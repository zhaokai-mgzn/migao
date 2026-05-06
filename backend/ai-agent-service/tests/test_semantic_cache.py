"""
语义缓存层 (Semantic Cache) 单元测试

测试覆盖：
- CacheResult 数据结构
- 余弦相似度计算函数
- TTL 策略
- 缓存 store / lookup 基本流程（mock Redis 和 embedding）
"""

import json
import math
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

import app.cache.semantic_cache
sc_module = sys.modules['app.cache.semantic_cache']
from app.cache.semantic_cache import (
    SemanticCache,
    CacheResult,
    _cosine_similarity,
    TTL_BY_INTENT,
    DEFAULT_TTL,
)


# ========== CacheResult 数据结构测试 ==========

class TestCacheResult:
    """CacheResult 数据类测试"""

    def test_cache_result_fields(self):
        """字段赋值正确"""
        now = datetime.now(timezone.utc)
        result = CacheResult(
            answer="测试回答",
            intent_type="order_query",
            confidence=0.98,
            cached_at=now,
        )
        assert result.answer == "测试回答"
        assert result.intent_type == "order_query"
        assert result.confidence == 0.98
        assert result.cached_at == now


# ========== 余弦相似度测试 ==========

class TestCosineSimilarity:
    """余弦相似度计算测试"""

    def test_identical_vectors(self):
        """相同向量 → 1.0"""
        v = [1.0, 2.0, 3.0]
        assert math.isclose(_cosine_similarity(v, v), 1.0, rel_tol=1e-9)

    def test_orthogonal_vectors(self):
        """正交向量 → 0.0"""
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert math.isclose(_cosine_similarity(a, b), 0.0, abs_tol=1e-9)

    def test_opposite_vectors(self):
        """反向向量 → -1.0"""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert math.isclose(_cosine_similarity(a, b), -1.0, rel_tol=1e-9)

    def test_zero_vector(self):
        """零向量 → 0.0"""
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_high_dimension(self):
        """高维向量相似度"""
        a = [1.0] * 1024
        b = [1.0] * 1024
        assert math.isclose(_cosine_similarity(a, b), 1.0, rel_tol=1e-9)


# ========== TTL 策略测试 ==========

class TestTTLStrategy:
    """TTL 策略测试"""

    def test_greeting_ttl(self):
        """问候意图 → 24h TTL"""
        assert TTL_BY_INTENT["greeting"] == 86400

    def test_order_query_ttl(self):
        """订单查询 → 5min TTL（动态数据）"""
        assert TTL_BY_INTENT["order_query"] == 300

    def test_logistics_ttl(self):
        """物流追踪 → 5min TTL"""
        assert TTL_BY_INTENT["logistics_track"] == 300

    def test_knowledge_faq_ttl(self):
        """FAQ → 24h TTL"""
        assert TTL_BY_INTENT["knowledge_faq"] == 86400

    def test_all_intents_have_ttl(self):
        """所有意图类型都有 TTL 配置"""
        expected_intents = [
            "greeting", "knowledge_faq", "product_inquiry",
            "order_query", "logistics_track", "after_sales",
            "complaint", "general",
        ]
        for intent in expected_intents:
            assert intent in TTL_BY_INTENT

    def test_default_ttl(self):
        """默认 TTL = 1h"""
        assert DEFAULT_TTL == 3600


# ========== SemanticCache store/lookup 测试 ==========

class TestSemanticCache:
    """语义缓存 store/lookup 流程测试"""

    @pytest.fixture
    def cache(self):
        return SemanticCache(similarity_threshold=0.95, max_entries=100)

    @pytest.fixture
    def mock_redis_client(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock(return_value=True)
        client.delete = AsyncMock(return_value=1)
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_store_basic(self, cache, mock_redis_client):
        """基本存储流程"""
        embedding = [0.1] * 256

        orig_get_embedding = sc_module.get_embedding
        orig_settings = sc_module.settings
        try:
            sc_module.get_embedding = AsyncMock(return_value=embedding)
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = True
            sc_module.settings = mock_s

            with patch.object(cache, "_get_redis", return_value=mock_redis_client):
                await cache.store(
                    tenant_id="t1",
                    query="订单查询",
                    answer="您的订单已发货",
                    intent_type="order_query",
                )

            # 验证写入 Redis
            mock_redis_client.set.assert_called_once()
            call_args = mock_redis_client.set.call_args
            stored_data = json.loads(call_args[0][1])
            assert len(stored_data) == 1
            assert stored_data[0]["answer"] == "您的订单已发货"
            assert stored_data[0]["intent_type"] == "order_query"
        finally:
            sc_module.get_embedding = orig_get_embedding
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_lookup_cache_miss(self, cache, mock_redis_client):
        """缓存未命中"""
        orig_settings = sc_module.settings
        try:
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = True
            sc_module.settings = mock_s

            with patch.object(cache, "_get_redis", return_value=mock_redis_client):
                result = await cache.lookup("t1", "随便问点什么")
                assert result is None
        finally:
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_lookup_cache_hit(self, cache, mock_redis_client):
        """缓存命中"""
        query_embedding = [1.0, 0.0, 0.0]
        cached_embedding = [1.0, 0.0, 0.0]  # 完全相同

        cache_data = json.dumps([{
            "query_embedding": cached_embedding,
            "query_text": "查订单",
            "answer": "您的订单正在配送中",
            "intent_type": "order_query",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }])
        mock_redis_client.get = AsyncMock(return_value=cache_data)

        orig_get_embedding = sc_module.get_embedding
        orig_settings = sc_module.settings
        try:
            sc_module.get_embedding = AsyncMock(return_value=query_embedding)
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = True
            mock_s.SEMANTIC_CACHE_SIMILARITY_THRESHOLD = 0.95
            sc_module.settings = mock_s

            with patch.object(cache, "_get_redis", return_value=mock_redis_client):
                result = await cache.lookup("t1", "查订单")
                assert result is not None
                assert isinstance(result, CacheResult)
                assert result.answer == "您的订单正在配送中"
                assert result.confidence >= 0.95
        finally:
            sc_module.get_embedding = orig_get_embedding
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_lookup_disabled(self, cache):
        """缓存功能关闭时返回 None"""
        orig_settings = sc_module.settings
        try:
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = False
            sc_module.settings = mock_s
            result = await cache.lookup("t1", "test")
            assert result is None
        finally:
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_store_disabled(self, cache):
        """缓存功能关闭时不写入"""
        orig_settings = sc_module.settings
        try:
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = False
            sc_module.settings = mock_s
            # 不应抛异常
            await cache.store("t1", "q", "a", "general")
        finally:
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_store_with_custom_ttl(self, cache, mock_redis_client):
        """自定义 TTL"""
        embedding = [0.1] * 10

        orig_get_embedding = sc_module.get_embedding
        orig_settings = sc_module.settings
        try:
            sc_module.get_embedding = AsyncMock(return_value=embedding)
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = True
            sc_module.settings = mock_s

            with patch.object(cache, "_get_redis", return_value=mock_redis_client):
                await cache.store("t1", "q", "a", "order_query", ttl=600)

            call_args = mock_redis_client.set.call_args
            assert call_args[1].get("ex") == 600 or call_args.kwargs.get("ex") == 600
        finally:
            sc_module.get_embedding = orig_get_embedding
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_lookup_error_graceful_degradation(self, cache, mock_redis_client):
        """lookup 异常时降级为 None（不阻塞主流程）"""
        mock_redis_client.get = AsyncMock(side_effect=Exception("Redis connection error"))

        orig_settings = sc_module.settings
        try:
            mock_s = MagicMock()
            mock_s.SEMANTIC_CACHE_ENABLED = True
            sc_module.settings = mock_s

            with patch.object(cache, "_get_redis", return_value=mock_redis_client):
                result = await cache.lookup("t1", "test")
                assert result is None
        finally:
            sc_module.settings = orig_settings

    @pytest.mark.asyncio
    async def test_cache_key_format(self, cache):
        """验证 cache key 格式"""
        key = cache._cache_key("tenant_123")
        assert key == "semantic_cache:tenant_123:entries"
