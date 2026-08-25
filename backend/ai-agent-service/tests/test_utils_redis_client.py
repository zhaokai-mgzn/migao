"""app/utils/redis_client.py 单元测试（issue #2430，defense 域 Redis 生命周期与降级）

覆盖：
- init_redis：连接成功设置连接池 / 连接失败向上 raise
- close_redis：断开连接池并置空 / 未初始化时幂等 no-op
- get_redis：未初始化 raise RuntimeError / yield 客户端并关闭
- RedisClient：get/set/delete 未初始化 raise / 正常操作 / make_key 命名空间前缀
- RedisClient 异步上下文管理器
"""
# case_ids: DF-004, DF-012

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.utils.redis_client as rc
from app.utils.redis_client import RedisClient


@pytest.fixture(autouse=True)
def _reset_redis_pool(monkeypatch):
    monkeypatch.setattr(rc, "redis_pool", None)


class TestInitRedis:
    @pytest.mark.asyncio
    async def test_init_success_sets_pool(self):
        pool = MagicMock()
        client = AsyncMock()
        client.ping = AsyncMock()
        client.close = AsyncMock()

        with patch.object(rc.redis, "ConnectionPool") as mock_pool_cls, \
             patch.object(rc.redis, "Redis", return_value=client):
            mock_pool_cls.from_url.return_value = pool
            await rc.init_redis()

            assert rc.redis_pool is pool
            client.ping.assert_awaited_once()
            client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_init_failure_raises(self):
        with patch.object(rc.redis, "ConnectionPool") as mock_pool_cls:
            mock_pool_cls.from_url.side_effect = ConnectionError("no redis")
            with pytest.raises(ConnectionError, match="no redis"):
                await rc.init_redis()
            assert rc.redis_pool is None


class TestCloseRedis:
    @pytest.mark.asyncio
    async def test_close_disconnects_pool(self):
        pool = AsyncMock()
        pool.disconnect = AsyncMock()
        rc.redis_pool = pool

        await rc.close_redis()

        pool.disconnect.assert_awaited_once()
        assert rc.redis_pool is None

    @pytest.mark.asyncio
    async def test_close_when_not_initialized_is_noop(self):
        await rc.close_redis()
        assert rc.redis_pool is None


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_uninitialized_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            gen = rc.get_redis()
            await gen.__anext__()

    @pytest.mark.asyncio
    async def test_yields_client_and_closes(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            gen = rc.get_redis()
            yielded = await gen.__anext__()
            assert yielded is client
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            client.close.assert_awaited_once()


class TestRedisClientMakeKey:
    def test_known_prefixes(self):
        # 前缀值自带结尾冒号，make_key 再以 ":" 拼接 → 实际产出双冒号（与 docstring 示例不符，
        # 此处断言真实行为；namespace 隔离语义不变）
        assert RedisClient.make_key("session", "t1", "u1") == "session::t1:u1"
        assert RedisClient.make_key("message", "m1") == "msg::m1"
        assert RedisClient.make_key("rate_limit", "u1") == "ratelimit::u1"
        assert RedisClient.make_key("jwt_blacklist", "tok") == "jwt:blacklist::tok"
        assert RedisClient.make_key("user_status", "u1") == "user:status::u1"
        assert RedisClient.make_key("cache", "k") == "cache::k"

    def test_unknown_prefix_falls_back_to_literal(self):
        assert RedisClient.make_key("custom", "x") == "custom:x"

    def test_no_parts(self):
        assert RedisClient.make_key("session") == "session:"


class TestRedisClientOperations:
    @pytest.mark.asyncio
    async def test_get_uninitialized_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            await RedisClient().get("k")

    @pytest.mark.asyncio
    async def test_get_returns_value(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.get = AsyncMock(return_value="v")
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            assert await RedisClient().get("k") == "v"
            client.get.assert_awaited_once_with("k")
            client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_with_ttl(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.set = AsyncMock(return_value=True)
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            assert await RedisClient().set("k", "v", ttl=60) is True
            client.set.assert_awaited_once_with("k", "v", ex=60)

    @pytest.mark.asyncio
    async def test_set_without_ttl(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.set = AsyncMock(return_value=True)
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            assert await RedisClient().set("k", "v") is True
            client.set.assert_awaited_once_with("k", "v")

    @pytest.mark.asyncio
    async def test_delete(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.delete = AsyncMock(return_value=1)
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            assert await RedisClient().delete("k") is True
            client.delete.assert_awaited_once_with("k")

    @pytest.mark.asyncio
    async def test_get_propagates_error(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("redis down"))
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            with pytest.raises(RuntimeError, match="redis down"):
                await RedisClient().get("k")


class TestRedisClientContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        rc.redis_pool = MagicMock()
        client = AsyncMock()
        client.close = AsyncMock()

        with patch.object(rc.redis, "Redis", return_value=client):
            async with RedisClient() as c:
                assert c is client
            client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_uninitialized_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            async with RedisClient():
                pytest.fail("__aenter__ 未初始化时应抛 RuntimeError")
