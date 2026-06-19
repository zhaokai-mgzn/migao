"""Tests for TenantAiConfigCache."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.cache.tenant_ai_config_cache import TenantAiConfigCache


class TestTenantAiConfigCache:
    """TenantAiConfigCache unit tests."""

    def test_cache_instance(self):
        """Cache can be instantiated."""
        cache = TenantAiConfigCache()
        assert cache is not None
        assert cache._memory == {}

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_admin_api(self):
        """First call triggers admin-api fetch."""
        cache = TenantAiConfigCache()
        mock_config = {"botName": "小布", "greetingTemplate": "Hello"}

        with patch.object(cache, "_fetch_from_admin_api", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config
            result = await cache.get_config(1)
            assert result == mock_config
            mock_fetch.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_cache_hit_skips_admin_api(self):
        """Second call within TTL uses memory cache."""
        cache = TenantAiConfigCache()
        mock_config = {"botName": "测试"}

        with patch.object(cache, "_fetch_from_admin_api", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config
            await cache.get_config(1)  # miss → fetch
            await cache.get_config(1)  # hit → no fetch
            assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_admin_api_error_returns_none(self):
        """admin-api failure returns None gracefully."""
        cache = TenantAiConfigCache()

        with patch.object(cache, "_fetch_from_admin_api", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            result = await cache.get_config(1)
            assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_clears_memory_cache(self):
        """invalidate() forces re-fetch on next get."""
        cache = TenantAiConfigCache()
        mock_config = {"botName": "小布"}

        with patch.object(cache, "_fetch_from_admin_api", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_config
            await cache.get_config(1)
            await cache.invalidate(1)
            await cache.get_config(1)  # re-fetch after invalidate
            assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """Different tenants have separate cache entries."""
        cache = TenantAiConfigCache()
        config_a = {"botName": "租户A"}
        config_b = {"botName": "租户B"}

        with patch.object(cache, "_fetch_from_admin_api", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = [config_a, config_b]
            result_a = await cache.get_config(1)
            result_b = await cache.get_config(2)
            assert result_a == config_a
            assert result_b == config_b
