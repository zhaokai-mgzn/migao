"""
测试 app.core.logistics_trace_cache — 第三方物流轨迹查询缓存层

被缓存的事实（issue #6185）：`LogisticsTrackTool._call_logistics_api()`
（阿里云市场 wuliu.market.alicloudapi.com/kdi）**按次计费**，同一运单号在短期内
被顾客追问 / 会话重放 / C 端「我的物流」逐单扇出时会**重复计费**。

TTL 口径（用户 2026-10-03 裁定，分档 + 每档加 1 小时）见模块常量。
"""
# case_ids: OR-005, OR-013

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core import logistics_trace_cache as ltc
from app.core.logistics_trace_cache import (
    LogisticsTraceCache,
    TTL_NO_INFO,
    TTL_TERMINAL,
    TTL_TRANSIT,
    _hash_phone,
    make_logistics_track_key,
    ttl_for_status,
)
from app.tools.base import ToolContext


# ========== TTL 分档（issue #6185 的判定核心） ==========

class TestTtlTiers:
    """TTL 分档：终态 90 分钟 / 在途 65 分钟 / 兜底 60 分钟 / 无信息 120 秒"""

    def test_terminal_statuses_get_longest_ttl(self):
        assert ttl_for_status("delivered") == TTL_TERMINAL == 5400
        assert ttl_for_status("returned") == TTL_TERMINAL == 5400

    def test_in_transit_statuses_get_middle_ttl(self):
        assert ttl_for_status("in_transit") == TTL_TRANSIT == 3900
        assert ttl_for_status("out_for_delivery") == TTL_TRANSIT == 3900
        assert ttl_for_status("picked") == TTL_TRANSIT == 3900

    def test_unknown_or_missing_status_gets_floor_ttl(self):
        assert ttl_for_status("exception") == TTL_TRANSIT == 3900
        assert ttl_for_status(None) == TTL_TRANSIT == 3900
        assert ttl_for_status("") == TTL_TRANSIT == 3900

    def test_tiers_are_strictly_ordered(self):
        """三档严格递增 —— 写反了（终态比在途短）这里会红"""
        assert TTL_NO_INFO < TTL_TRANSIT < TTL_TERMINAL


# ========== 缓存 key ==========

class TestCacheKey:
    """key 必须含租户；手机尾号不得明文出现"""

    def test_key_separates_tenants(self):
        k1 = make_logistics_track_key(1, "SF123", "SFEXPRESS", "9000")
        k2 = make_logistics_track_key(2, "SF123", "SFEXPRESS", "9000")
        assert k1 != k2

    def test_key_separates_tracking_numbers_and_companies(self):
        base = make_logistics_track_key(1, "SF123", "SFEXPRESS", None)
        assert base != make_logistics_track_key(1, "SF124", "SFEXPRESS", None)
        assert base != make_logistics_track_key(1, "SF123", "YTO", None)
        assert base != make_logistics_track_key(1, "SF123", "SFEXPRESS", "9000")

    def test_phone_tail_never_appears_in_plaintext(self):
        key = make_logistics_track_key(1, "SF123", "SFEXPRESS", "9000")
        assert "9000" not in key
        assert _hash_phone("9000") in key

    def test_phone_hash_is_stable_and_discriminating(self):
        assert _hash_phone("9000") == _hash_phone("9000")
        assert _hash_phone("9000") != _hash_phone("9001")
        assert _hash_phone(None) == "none"


# ========== _decode：205 不得被读成「已签收」假轨迹 ==========

class TestDecodeNoInfo:
    """status=205（计费但无信息）：不得记成成功读数，也不得返回 None（那是「调用失败」的信号）"""

    def test_205_decodes_to_success_with_empty_traces(self):
        decoded = LogisticsTraceCache._decode({"status": "205", "result": {}})
        assert decoded is not None, "205 是「查到了、但暂无轨迹」，不是调用失败"
        assert decoded["traces"] == []
        assert "暂无物流信息" in decoded["latest"]["content"]

    def test_205_does_not_claim_delivered(self):
        """轨迹为空时不得推断成终态 —— 否则刚发货的运单会被缓存 90 分钟"""
        decoded = LogisticsTraceCache._decode({"status": "205", "result": {}})
        assert decoded["status"] == "in_transit"
        assert ttl_for_status(decoded["status"]) == TTL_TRANSIT


# ========== 缓存层本体（Redis mock） ==========

class _FakeRedis:
    """记录 set 的 TTL，便于断言分档真的生效"""

    def __init__(self):
        self.store = {}
        self.set_calls = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append({"key": key, "ex": ex, "value": value})

    async def close(self):
        pass


class _FakeRedisModule:
    def __init__(self, pool):
        self.redis_pool = pool


def _patch_redis(fake: _FakeRedis):
    """把缓存层借到的 Redis 客户端换成 fake"""
    module = _FakeRedisModule(pool=object())
    client = AsyncMock(wraps=fake)
    client.get = AsyncMock(side_effect=fake.get)
    client.set = AsyncMock(side_effect=fake.set)
    client.close = AsyncMock(side_effect=fake.close)
    return patch.multiple(
        ltc,
        redis_module=module,
        redis_async=type("R", (), {"Redis": lambda connection_pool=None: client}),
    ), client


class TestRoundTripAndTtlWiring:
    async def test_delivered_payload_is_stored_under_terminal_ttl(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            ok = await cache.set(
                1, "SF123", "SFEXPRESS", None,
                {"status": "0", "result": {
                    "type": "SFEXPRESS", "number": "SF123",
                    "list": [{"time": "2026-09-01 10:00", "context": "已签收，签收人：本人"}]}},
            )
        assert ok is True
        assert client.set.await_count == 1
        assert fake.set_calls[0]["ex"] == TTL_TERMINAL

    async def test_in_transit_payload_is_stored_under_transit_ttl(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            await cache.set(
                1, "YT999", "YTO", None,
                {"status": "0", "result": {
                    "type": "YTO", "number": "YT999",
                    "list": [{"time": "2026-09-01 09:00", "context": "快件已到达【杭州转运中心】"}]}},
            )
        assert fake.set_calls[0]["ex"] == TTL_TRANSIT

    async def test_no_info_payload_is_stored_under_short_ttl(self):
        """205 也计费 ⇒ 必须缓存，但用短 TTL（刚发货反复重查是主要浪费源）"""
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            ok = await cache.set(1, "JD0001", "JD", None, {"status": "205", "result": {}})
        assert ok is True
        assert fake.set_calls[0]["ex"] == TTL_NO_INFO == 120

    async def test_get_returns_the_decoded_payload(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            await cache.set(1, "SF123", "SFEXPRESS", "9000", {"status": "205", "result": {}})
            got = await cache.get(1, "SF123", "SFEXPRESS", "9000")
        assert got["traces"] == []
        assert got["tracking_number"] == "SF123"

    async def test_get_is_tenant_scoped(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            await cache.set(1, "SF123", "SFEXPRESS", None, {"status": "205", "result": {}})
            other_tenant = await cache.get(2, "SF123", "SFEXPRESS", None)
        assert other_tenant is None

    async def test_get_misses_on_unknown_key(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            got = await LogisticsTraceCache().get(1, "NOPE", None, None)
        assert got is None


class TestRedisFailuresNeverEscape:
    """缓存层任何异常都不得抛给上游（与 AdminApiCache 同口径）"""

    async def test_pool_absent_get_returns_none(self):
        with patch.object(ltc.redis_module, "redis_pool", None):
            assert await LogisticsTraceCache().get(1, "SF123", None, None) is None

    async def test_pool_absent_set_returns_false(self):
        with patch.object(ltc.redis_module, "redis_pool", None):
            assert await LogisticsTraceCache().set(1, "SF123", None, None, {"status": "0"}) is False

    async def test_redis_get_exception_is_swallowed(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        client.get = AsyncMock(side_effect=RuntimeError("redis down"))
        with ctx:
            assert await LogisticsTraceCache().get(1, "SF123", None, None) is None

    async def test_redis_set_exception_is_swallowed(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        client.set = AsyncMock(side_effect=RuntimeError("redis down"))
        with ctx:
            assert await LogisticsTraceCache().set(1, "SF123", None, None, {"status": "0"}) is False

    async def test_corrupt_cached_json_is_swallowed(self):
        fake = _FakeRedis()
        fake.store[make_logistics_track_key(1, "SF123", None, None)] = "{not json"
        ctx, client = _patch_redis(fake)
        with ctx:
            assert await LogisticsTraceCache().get(1, "SF123", None, None) is None


class TestCachedValueIsJsonSerializable:
    async def test_stored_value_round_trips_through_json(self):
        fake = _FakeRedis()
        ctx, client = _patch_redis(fake)
        with ctx:
            cache = LogisticsTraceCache()
            await cache.set(
                1, "SF123", "SFEXPRESS", None,
                {"status": "0", "result": {
                    "type": "SFEXPRESS", "number": "SF123",
                    "list": [{"time": "2026-09-01 10:00", "context": "已签收"}]}},
            )
            raw = fake.set_calls[0]["value"]
        payload = json.loads(raw)
        assert payload["traces"][0]["content"] == "已签收"
        assert payload["company"] == "顺丰速运"


# ========== 接线：Tool 真的走缓存（「判据绿 ≠ 接线在」） ==========

def _ok_api_response(status: str = "0", context: str = "快件已到达【杭州转运中心】"):
    """最小可用的第三方成功响应"""
    return {"status": status, "result": {
        "type": "SFEXPRESS", "number": "SF1234567890",
        "list": [{"time": "2026-09-01 10:00", "context": context}],
    }}


class TestToolConsultsCache:
    """`_track_by_number` 的接线：命中缓存 ⇒ 第三方 API **一次都不调**"""

    async def test_second_call_is_served_from_cache_without_touching_api(self):
        from app.tools.logistics_track import LogisticsTrackTool

        fake = _FakeRedis()
        ctx, _client = _patch_redis(fake)
        with ctx:
            tool = LogisticsTrackTool()
            with patch.object(
                tool, "_call_logistics_api", new=AsyncMock(return_value=_ok_api_response())
            ) as api, patch("app.tools.logistics_track.settings") as ms:
                ms.LOGISTICS_APPCODE = "x"
                ms.LOGISTICS_API_URL = "https://f/kdi"
                ctxobj = ToolContext(tenant_id=1, user_id="u1", session_id="s1")

                first = await tool._track_by_number(ctxobj, "SF1234567890", "顺丰速运")
                second = await tool._track_by_number(ctxobj, "SF1234567890", "顺丰速运")

        assert api.await_count == 1, "同一运单第二次查询必须命中缓存，不得重复计费"
        assert first.success is True
        assert second.success is True
        assert second.data["traces"] == first.data["traces"]
        assert second.data["status_text"] == first.data["status_text"]

    async def test_successful_response_is_written_to_cache(self):
        from app.tools.logistics_track import LogisticsTrackTool

        fake = _FakeRedis()
        ctx, _client = _patch_redis(fake)
        with ctx:
            tool = LogisticsTrackTool()
            with patch.object(
                tool, "_call_logistics_api", new=AsyncMock(return_value=_ok_api_response())
            ), patch("app.tools.logistics_track.settings") as ms:
                ms.LOGISTICS_APPCODE = "x"
                ms.LOGISTICS_API_URL = "https://f/kdi"
                await tool._track_by_number(
                    ToolContext(tenant_id=1, user_id="u1", session_id="s1"),
                    "SF1234567890", "顺丰速运",
                )

        assert len(fake.set_calls) == 1, "成功响应必须写回缓存（否则永远命中不了）"
        assert fake.set_calls[0]["ex"] == TTL_TRANSIT

    async def test_failed_api_call_is_not_cached(self):
        """调用失败（返回 None）⇒ 不写缓存，不让故障状态活 65 分钟"""
        from app.tools.logistics_track import LogisticsTrackTool

        fake = _FakeRedis()
        ctx, _client = _patch_redis(fake)
        with ctx:
            tool = LogisticsTrackTool()
            with patch.object(
                tool, "_call_logistics_api", new=AsyncMock(return_value=None)
            ), patch("app.tools.logistics_track.settings") as ms:
                ms.LOGISTICS_APPCODE = "x"
                ms.LOGISTICS_API_URL = "https://f/kdi"
                await tool._track_by_number(
                    ToolContext(tenant_id=1, user_id="u1", session_id="s1"),
                    "SF1234567890", "顺丰速运",
                )

        assert fake.set_calls == []

    async def test_cache_hit_uses_current_order_id_not_the_cached_one(self):
        """同一运单被两笔订单引用时，命中的必须是**本次**订单号"""
        from app.tools.logistics_track import LogisticsTrackTool

        fake = _FakeRedis()
        ctx, _client = _patch_redis(fake)
        with ctx:
            tool = LogisticsTrackTool()
            with patch.object(
                tool, "_call_logistics_api", new=AsyncMock(return_value=_ok_api_response())
            ) as api, patch("app.tools.logistics_track.settings") as ms:
                ms.LOGISTICS_APPCODE = "x"
                ms.LOGISTICS_API_URL = "https://f/kdi"
                ctxobj = ToolContext(tenant_id=1, user_id="u1", session_id="s1")

                await tool._track_by_number(ctxobj, "SF1234567890", "顺丰速运", "ORD-A")
                second = await tool._track_by_number(ctxobj, "SF1234567890", "顺丰速运", "ORD-B")

        assert api.await_count == 1
        assert second.data["order_id"] == "ORD-B"

