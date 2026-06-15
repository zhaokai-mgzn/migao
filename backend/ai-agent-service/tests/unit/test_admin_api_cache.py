"""
测试 app.core.admin_api_cache — admin-api 调用缓存层
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.admin_api_cache import (
    AdminApiCache,
    _hash_params,
    get_admin_api_cache,
    TTL_PRODUCT_SEARCH,
    TTL_CATEGORY_TREE,
)


class TestHashParams:
    """_hash_params 参数哈希"""

    def test_empty_params_returns_empty(self):
        assert _hash_params(None) == "empty"
        assert _hash_params({}) == "empty"

    def test_same_params_same_hash(self):
        h1 = _hash_params({"keyword": "test", "page": 1})
        h2 = _hash_params({"keyword": "test", "page": 1})
        assert h1 == h2

    def test_different_params_different_hash(self):
        h1 = _hash_params({"keyword": "a"})
        h2 = _hash_params({"keyword": "b"})
        assert h1 != h2

    def test_order_independent(self):
        h1 = _hash_params({"a": 1, "b": 2})
        h2 = _hash_params({"b": 2, "a": 1})
        assert h1 == h2


class TestKeyGeneration:
    """缓存 key 生成"""

    def test_product_search_key_includes_tenant(self):
        key = AdminApiCache.make_product_search_key(42, {"keyword": "test"})
        assert "product_search" in key
        assert ":42:" in key

    def test_product_search_key_different_tenants(self):
        k1 = AdminApiCache.make_product_search_key(1, {"kw": "a"})
        k2 = AdminApiCache.make_product_search_key(2, {"kw": "a"})
        assert k1 != k2

    def test_category_tree_key_includes_tenant(self):
        key = AdminApiCache.make_category_tree_key(99)
        assert "category_tree" in key
        assert ":99" in key


class TestAdminApiCacheRedisUnavailable:
    """Redis 不可用时的降级行为"""

    @patch("app.core.admin_api_cache.redis_module", autospec=True)
    async def test_get_product_search_returns_none_when_pool_is_none(self, mock_redis_module):
        mock_redis_module.redis_pool = None
        cache = AdminApiCache()
        result = await cache.get_product_search(1, {"kw": "test"})
        assert result is None

    @patch("app.core.admin_api_cache.redis_module", autospec=True)
    async def test_set_product_search_returns_false_when_pool_is_none(self, mock_redis_module):
        mock_redis_module.redis_pool = None
        cache = AdminApiCache()
        result = await cache.set_product_search(1, {"kw": "test"}, {"items": []})
        assert result is False

    @patch("app.core.admin_api_cache.redis_module", autospec=True)
    async def test_get_category_tree_returns_none_when_pool_is_none(self, mock_redis_module):
        mock_redis_module.redis_pool = None
        cache = AdminApiCache()
        result = await cache.get_category_tree(1)
        assert result is None

    @patch("app.core.admin_api_cache.redis_module", autospec=True)
    async def test_set_category_tree_returns_false_when_pool_is_none(self, mock_redis_module):
        mock_redis_module.redis_pool = None
        cache = AdminApiCache()
        result = await cache.set_category_tree(1, {"tree": []})
        assert result is False


class TestAdminApiCacheWithRedis:
    """Redis 可用时的正常行为"""

    @pytest.fixture
    def mock_client(self):
        client = AsyncMock()
        return client

    @pytest.fixture
    def cache(self, mock_client):
        pool = MagicMock()
        with patch(
            "app.core.admin_api_cache.redis_module.redis_pool", pool
        ), patch(
            "app.core.admin_api_cache.redis_async.Redis",
            return_value=mock_client,
        ):
            yield AdminApiCache()

    async def test_get_product_search_hit(self, cache, mock_client):
        mock_client.get = AsyncMock(return_value=json.dumps({"items": [{"id": 1}]}))
        result = await cache.get_product_search(1, {"kw": "test"})
        assert result == {"items": [{"id": 1}]}

    async def test_get_product_search_miss(self, cache, mock_client):
        mock_client.get = AsyncMock(return_value=None)
        result = await cache.get_product_search(1, {"kw": "test"})
        assert result is None

    async def test_set_product_search_success(self, cache, mock_client):
        mock_client.set = AsyncMock(return_value=True)
        result = await cache.set_product_search(1, {"kw": "test"}, {"items": []})
        assert result is True
        mock_client.set.assert_called_once()

    async def test_set_product_search_uses_correct_ttl(self, cache, mock_client):
        mock_client.set = AsyncMock(return_value=True)
        await cache.set_product_search(1, {"kw": "test"}, {"items": []})
        call_kwargs = mock_client.set.call_args
        assert call_kwargs[1]["ex"] == TTL_PRODUCT_SEARCH

    async def test_set_category_tree_uses_correct_ttl(self, cache, mock_client):
        mock_client.set = AsyncMock(return_value=True)
        await cache.set_category_tree(1, {"tree": [{"id": 1}]})
        call_kwargs = mock_client.set.call_args
        assert call_kwargs[1]["ex"] == TTL_CATEGORY_TREE

    async def test_get_error_swallowed(self, cache, mock_client):
        mock_client.get = AsyncMock(side_effect=ConnectionError("redis down"))
        result = await cache.get_product_search(1, {"kw": "test"})
        assert result is None  # error swallowed, not thrown

    async def test_set_error_swallowed(self, cache, mock_client):
        mock_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
        result = await cache.set_product_search(1, {"kw": "test"}, {"items": []})
        assert result is False  # error swallowed


class TestSingleton:
    """单例 get_admin_api_cache"""

    def test_returns_same_instance(self):
        c1 = get_admin_api_cache()
        c2 = get_admin_api_cache()
        assert c1 is c2
