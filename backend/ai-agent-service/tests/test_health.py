# case_ids: MC-009
"""Readiness 探活单元测试（app/utils/health.py + main.py /ready）

覆盖：Redis+DB 正常 → ready；DB 故障 → not_ready；Redis 池未初始化 → not_ready。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils import health


class TestCheckReadiness:
    async def test_ready_when_db_and_redis_ok(self):
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_async_cm = MagicMock()
        mock_async_cm.__aenter__.return_value = mock_session

        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)

        with patch("app.utils.health.AsyncSessionLocal", return_value=mock_async_cm), \
             patch("app.utils.health.redis_pool", new=object()), \
             patch("app.utils.health.redis.Redis", return_value=mock_client):
            ok = await health.check_readiness()
        assert ok is True
        mock_session.execute.assert_awaited_once()

    async def test_not_ready_when_db_down(self):
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("db down"))
        mock_async_cm = MagicMock()
        mock_async_cm.__aenter__.return_value = mock_session

        with patch("app.utils.health.AsyncSessionLocal", return_value=mock_async_cm), \
             patch("app.utils.health.redis_pool", new=object()), \
             patch("app.utils.health.redis.Redis") as mock_redis:
            ok = await health.check_readiness()
        assert ok is False
        mock_redis.assert_not_called()

    async def test_not_ready_when_redis_pool_uninitialized(self):
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_async_cm = MagicMock()
        mock_async_cm.__aenter__.return_value = mock_session

        with patch("app.utils.health.AsyncSessionLocal", return_value=mock_async_cm), \
             patch("app.utils.health.redis_pool", new=None):
            ok = await health.check_readiness()
        assert ok is False

    async def test_not_ready_when_redis_ping_fails(self):
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_async_cm = MagicMock()
        mock_async_cm.__aenter__.return_value = mock_session

        mock_client = MagicMock()
        mock_client.ping = AsyncMock(side_effect=ConnectionError("redis down"))

        with patch("app.utils.health.AsyncSessionLocal", return_value=mock_async_cm), \
             patch("app.utils.health.redis_pool", new=object()), \
             patch("app.utils.health.redis.Redis", return_value=mock_client):
            ok = await health.check_readiness()
        assert ok is False
