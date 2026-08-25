# case_ids: MC-009
"""应用入口单元测试（app/main.py）

覆盖：create_app / /health / CORS / lifespan / _session_auto_close_loop。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app import main as main_module


class TestCreateApp:
    def test_returns_fastapi_with_metadata(self):
        with patch("app.main.settings") as s:
            s.APP_NAME = "ai-agent-service"
            s.APP_VERSION = "1.0.0"
            s.DEBUG = True
            s.API_PREFIX = "/api"
            s.CORS_ALLOWED_ORIGINS = "http://a.com"
            app = main_module.create_app()
        assert isinstance(app, FastAPI)
        assert app.title == "ai-agent-service"
        assert app.version == "1.0.0"

    def test_cors_splits_and_appends_dev_origins(self):
        with patch("app.main.settings") as s:
            s.APP_NAME = "ai-agent-service"
            s.APP_VERSION = "1.0.0"
            s.DEBUG = True
            s.API_PREFIX = "/api"
            s.CORS_ALLOWED_ORIGINS = "http://a.com, http://b.com"
            app = main_module.create_app()
        cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert len(cors) == 1
        origins = cors[0].kwargs["allow_origins"]
        assert "http://a.com" in origins
        assert "http://b.com" in origins
        assert "http://localhost:5173" in origins
        assert "http://localhost:3000" in origins

    def test_health_endpoint(self):
        with patch("app.main.settings") as s, \
             patch("app.main.init_db", new_callable=AsyncMock), \
             patch("app.main.close_db", new_callable=AsyncMock), \
             patch("app.main.init_redis", new_callable=AsyncMock), \
             patch("app.main.close_redis", new_callable=AsyncMock), \
             patch("app.main._session_auto_close_loop", new_callable=AsyncMock):
            s.APP_NAME = "ai-agent-service"
            s.APP_VERSION = "1.0.0"
            s.DEBUG = True
            s.API_PREFIX = "/api"
            s.CORS_ALLOWED_ORIGINS = "http://a.com"
            app = main_module.create_app()
            with TestClient(app) as client:
                resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "status": "healthy",
            "service": "ai-agent-service",
            "version": "1.0.0",
        }


class TestLifespan:
    @pytest.mark.asyncio
    async def test_non_debug_init_failure_raises(self):
        with patch("app.main.settings") as s:
            s.DEBUG = False
            s.APP_NAME = "x"
            s.APP_VERSION = "1"
            with patch("app.main.init_db", new_callable=AsyncMock, side_effect=RuntimeError("db down")):
                with pytest.raises(RuntimeError):
                    async with main_module.lifespan(None):
                        pass

    @pytest.mark.asyncio
    async def test_debug_init_failure_swallowed(self):
        with patch("app.main.settings") as s, \
             patch("app.main.init_db", new_callable=AsyncMock, side_effect=RuntimeError("db down")), \
             patch("app.main.init_redis", new_callable=AsyncMock), \
             patch("app.main.close_redis", new_callable=AsyncMock), \
             patch("app.main.close_db", new_callable=AsyncMock), \
             patch("app.main._session_auto_close_loop", new_callable=AsyncMock):
            s.DEBUG = True
            s.APP_NAME = "x"
            s.APP_VERSION = "1"
            async with main_module.lifespan(None):
                pass

    @pytest.mark.asyncio
    async def test_shutdown_closes_redis_and_db(self):
        mock_close_redis = AsyncMock()
        mock_close_db = AsyncMock()
        with patch("app.main.settings") as s, \
             patch("app.main.init_db", new_callable=AsyncMock), \
             patch("app.main.init_redis", new_callable=AsyncMock), \
             patch("app.main.close_redis", new=mock_close_redis), \
             patch("app.main.close_db", new=mock_close_db), \
             patch("app.main._session_auto_close_loop", new_callable=AsyncMock):
            s.DEBUG = True
            s.APP_NAME = "x"
            s.APP_VERSION = "1"
            async with main_module.lifespan(None):
                pass
        mock_close_redis.assert_awaited_once()
        mock_close_db.assert_awaited_once()


class TestSessionAutoCloseLoop:
    def _mock_session_memory(self, idle_side_effect=None):
        mock_sm = MagicMock()
        mock_sm.close_idle_sessions = AsyncMock(side_effect=idle_side_effect or [0])
        mock_sm.cleanup_closed_sessions = AsyncMock(return_value=0)
        return mock_sm

    @pytest.mark.asyncio
    async def test_cancelled_error_reraises(self):
        mock_sm = self._mock_session_memory()
        with patch("app.memory.session_memory.SessionMemory", return_value=mock_sm), \
             patch("app.main.asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await main_module._session_auto_close_loop()

    @pytest.mark.asyncio
    async def test_scans_idle_sessions_and_daily_cleanup(self):
        mock_sm = self._mock_session_memory()
        with patch("app.memory.session_memory.SessionMemory", return_value=mock_sm), \
             patch("app.main.asyncio.sleep", new_callable=AsyncMock, side_effect=[None, asyncio.CancelledError()]):
            with pytest.raises(asyncio.CancelledError):
                await main_module._session_auto_close_loop()
        mock_sm.close_idle_sessions.assert_awaited_once_with(idle_minutes=240)
        mock_sm.cleanup_closed_sessions.assert_awaited_once_with(older_than_days=90)

    @pytest.mark.asyncio
    async def test_nonfatal_exception_continues_loop(self):
        mock_sm = self._mock_session_memory(idle_side_effect=RuntimeError("scan error"))
        with patch("app.memory.session_memory.SessionMemory", return_value=mock_sm), \
             patch("app.main.asyncio.sleep", new_callable=AsyncMock, side_effect=[None, asyncio.CancelledError()]):
            with pytest.raises(asyncio.CancelledError):
                await main_module._session_auto_close_loop()
        # 第一次 close_idle_sessions 抛异常被吞（非致命），循环继续到第二次 sleep 后 CancelledError 重抛
        mock_sm.close_idle_sessions.assert_awaited_once_with(idle_minutes=240)
        mock_sm.cleanup_closed_sessions.assert_not_awaited()
