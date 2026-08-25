"""app/utils/database.py 单元测试（issue #2430，utils 域数据库会话生命周期）

覆盖：
- get_db_session：正常路径 commit + finally close / 异常路径 rollback 后向上抛
- init_db：SELECT 1 探活成功 / 探活失败向上 raise
- close_db：释放连接池（engine.dispose）
"""
# case_ids: UT-002

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.utils.database as database_module


def _make_session_cm(session):
    """构造 AsyncSessionLocal() 返回的异步上下文管理器 mock。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_engine_begin_cm(conn):
    """构造 engine.begin() 返回的异步上下文管理器 mock。"""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestGetDbSession:
    @pytest.mark.asyncio
    async def test_commits_and_closes_on_success(self):
        session = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        cm = _make_session_cm(session)

        with patch.object(database_module, "AsyncSessionLocal", return_value=cm):
            gen = database_module.get_db_session()
            db = await gen.__anext__()
            assert db is session
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

        session.commit.assert_awaited_once()
        session.close.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rolls_back_and_rethrows_on_error(self):
        session = AsyncMock()
        session.commit = AsyncMock(side_effect=RuntimeError("boom"))
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        cm = _make_session_cm(session)

        with patch.object(database_module, "AsyncSessionLocal", return_value=cm):
            gen = database_module.get_db_session()
            await gen.__anext__()
            with pytest.raises(RuntimeError, match="boom"):
                await gen.__anext__()

        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()


class TestInitDb:
    @pytest.mark.asyncio
    async def test_probes_connection(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        begin_cm = _make_engine_begin_cm(conn)
        mock_engine = MagicMock()
        mock_engine.begin.return_value = begin_cm

        with patch.object(database_module, "engine", new=mock_engine):
            await database_module.init_db()

        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_on_probe_failure(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=RuntimeError("no db"))
        begin_cm = _make_engine_begin_cm(conn)
        mock_engine = MagicMock()
        mock_engine.begin.return_value = begin_cm

        with patch.object(database_module, "engine", new=mock_engine):
            with pytest.raises(RuntimeError, match="no db"):
                await database_module.init_db()


class TestCloseDb:
    @pytest.mark.asyncio
    async def test_disposes_engine(self):
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with patch.object(database_module, "engine", new=mock_engine):
            await database_module.close_db()

        mock_engine.dispose.assert_awaited_once()
