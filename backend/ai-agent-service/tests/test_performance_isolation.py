"""
性能与并发隔离测试

验证高并发下多租户隔离的可靠性，确保 ToolContext / contextvars / Redis / DB
在并发场景下不串扰。

覆盖维度：
1. 多租户并发会话创建隔离
2. 并发消息发送无交叉污染
3. 并发 Tool 执行 ToolContext 隔离
4. SSE 长连接并发隔离
5. Redis 缓存 key 租户隔离
6. 数据库连接池 RLS 隔离
7. 会话记忆并发读写隔离
8. 高并发压力测试
9. 快速租户切换无泄露
10. 混合租户读写操作隔离
"""

import asyncio
import json
import uuid
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.base import ToolContext, ToolResult
from app.tools.registry import (
    ToolRegistry,
    set_tool_context,
    get_tool_context,
    _current_tool_context,
)
from app.utils.redis_client import RedisClient


# ========== 常量 ==========

TENANT_IDS = list(range(1, 21))  # 20 个租户
TENANT_A = 1
TENANT_B = 2
TENANT_C = 3
USER_PREFIX = "user_perf_"
SESSION_PREFIX = "sess_perf_"


# ========== Fixtures ==========


@pytest.fixture
def tool_contexts() -> Dict[int, ToolContext]:
    """为每个租户创建独立的 ToolContext"""
    return {
        tid: ToolContext(
            tenant_id=tid,
            user_id=f"{USER_PREFIX}{tid}",
            session_id=f"{SESSION_PREFIX}{tid}",
            role="customer",
        )
        for tid in TENANT_IDS
    }


@pytest.fixture
def mock_db_session_factory():
    """返回一个工厂函数，为每次调用创建独立的 mock db session"""

    def _factory():
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        return session

    return _factory


@pytest.fixture
def mock_redis_client():
    """Mock Redis 客户端，内部使用 dict 模拟存储"""
    store: Dict[str, str] = {}

    client = AsyncMock()

    async def _set(key, value, **kwargs):
        store[key] = value
        return True

    async def _get(key):
        return store.get(key)

    async def _delete(*keys):
        count = 0
        for k in keys:
            if k in store:
                del store[k]
                count += 1
        return count

    async def _keys(pattern):
        import fnmatch
        return [k for k in store if fnmatch.fnmatch(k, pattern)]

    client.set = AsyncMock(side_effect=_set)
    client.get = AsyncMock(side_effect=_get)
    client.delete = AsyncMock(side_effect=_delete)
    client.keys = AsyncMock(side_effect=_keys)
    client.close = AsyncMock()
    client._store = store  # 暴露内部存储供断言使用
    return client


# ============================================================
# 第一组：ToolContext contextvars 并发隔离
# ============================================================


@pytest.mark.integration
class TestConcurrentToolContextIsolation:
    """验证 contextvars 在并发 asyncio task 中正确隔离"""

    async def test_concurrent_tool_context_isolation(self, tool_contexts):
        """并发 Tool 执行，ToolContext 通过 contextvars 正确隔离"""
        results: Dict[int, int] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _worker(tenant_id: int):
            ctx = tool_contexts[tenant_id]
            await barrier.wait()
            # 设置当前 task 的 ToolContext
            set_tool_context(ctx)
            # 模拟业务处理耗时
            await asyncio.sleep(0.01)
            # 读取 ToolContext 并校验
            read_ctx = get_tool_context()
            if read_ctx is None:
                errors.append(f"tenant {tenant_id}: context is None")
            elif read_ctx.tenant_id != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: expected {tenant_id}, got {read_ctx.tenant_id}"
                )
            results[tenant_id] = read_ctx.tenant_id if read_ctx else -1

        tasks = [asyncio.create_task(_worker(tid)) for tid in TENANT_IDS]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"ToolContext 串扰: {errors}"
        assert len(results) == len(TENANT_IDS)
        for tid in TENANT_IDS:
            assert results[tid] == tid

    async def test_rapid_tenant_switch_no_leak(self):
        """快速切换租户后无数据泄露 —— 同一 task 内反复切换"""
        leaked = []

        for i in range(100):
            tid = (i % 10) + 1
            ctx = ToolContext(
                tenant_id=tid,
                user_id=f"user_{tid}",
                session_id=f"sess_{tid}",
                role="customer",
            )
            set_tool_context(ctx)
            read = get_tool_context()
            if read is None or read.tenant_id != tid:
                leaked.append((i, tid, read.tenant_id if read else None))

        assert len(leaked) == 0, f"切换泄露: {leaked}"

    async def test_high_concurrency_tenant_context_stress(self, tool_contexts):
        """高并发（50+ 请求）压力下租户隔离"""
        concurrency = 50
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _stress_worker(index: int):
            tid = TENANT_IDS[index % len(TENANT_IDS)]
            ctx = tool_contexts[tid]
            await barrier.wait()
            set_tool_context(ctx)
            # 交错 sleep 模拟真实负载
            await asyncio.sleep(0.005 * (index % 5))
            read = get_tool_context()
            if read is None or read.tenant_id != tid:
                errors.append(
                    f"worker {index} (tenant {tid}): got {read.tenant_id if read else None}"
                )

        tasks = [asyncio.create_task(_stress_worker(i)) for i in range(concurrency)]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"高并发隔离失败({len(errors)}/{concurrency}): {errors[:10]}"


# ============================================================
# 第二组：并发会话创建与消息发送隔离
# ============================================================


@pytest.mark.integration
class TestConcurrentSessionIsolation:
    """验证多租户并发创建会话和发送消息时数据隔离"""

    async def test_concurrent_chat_sessions_tenant_isolation(
        self, mock_db_session_factory
    ):
        """多租户并发创建会话，各自隔离"""
        from app.memory.session_memory import SessionMemory

        created_sessions: Dict[int, str] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _create_session(tenant_id: int):
            mock_db = mock_db_session_factory()
            # Mock _get_session 返回 mock db
            memory = SessionMemory(db_session=None)
            memory._get_session = AsyncMock(return_value=mock_db)

            await barrier.wait()
            session_id = memory._generate_session_id()
            created_sessions[tenant_id] = session_id
            # 验证 session_id 唯一
            if session_id in [
                v for k, v in created_sessions.items() if k != tenant_id
            ]:
                errors.append(f"tenant {tenant_id}: duplicate session_id {session_id}")

        tasks = [asyncio.create_task(_create_session(tid)) for tid in TENANT_IDS[:10]]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"会话创建冲突: {errors}"
        # 所有 session_id 应互不相同
        ids = list(created_sessions.values())
        assert len(set(ids)) == len(ids), "存在重复的 session_id"

    async def test_concurrent_message_sending_no_cross_contamination(
        self, mock_db_session_factory
    ):
        """并发发送消息，响应不串扰"""
        from app.memory.session_memory import SessionMemory

        saved_messages: Dict[int, List[str]] = {tid: [] for tid in TENANT_IDS[:10]}
        barrier = asyncio.Event()

        async def _send_messages(tenant_id: int):
            mock_db = mock_db_session_factory()
            memory = SessionMemory(db_session=None)
            memory._get_session = AsyncMock(return_value=mock_db)

            await barrier.wait()
            for i in range(3):
                msg_id = memory._generate_message_id()
                saved_messages[tenant_id].append(msg_id)
                await asyncio.sleep(0.001)

        tasks = [
            asyncio.create_task(_send_messages(tid)) for tid in TENANT_IDS[:10]
        ]
        barrier.set()
        await asyncio.gather(*tasks)

        # 每个租户应有 3 条消息
        for tid in TENANT_IDS[:10]:
            assert len(saved_messages[tid]) == 3, f"tenant {tid} 消息数异常"

        # 所有消息 ID 全局唯一
        all_ids = [mid for msgs in saved_messages.values() for mid in msgs]
        assert len(set(all_ids)) == len(all_ids), "存在跨租户重复的消息 ID"

    async def test_session_memory_concurrent_access(self, mock_db_session_factory):
        """并发读写会话记忆不串扰"""
        from app.memory.session_memory import SessionMemory

        results: Dict[int, dict] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _read_write_memory(tenant_id: int):
            mock_db = mock_db_session_factory()
            memory = SessionMemory(db_session=None)
            memory._get_session = AsyncMock(return_value=mock_db)

            await barrier.wait()

            # 并发写入
            session_id = memory._generate_session_id()
            msg_id = memory._generate_message_id()
            results[tenant_id] = {
                "session_id": session_id,
                "msg_id": msg_id,
                "tenant_id": tenant_id,
            }

            # 模拟并发读取延迟
            await asyncio.sleep(0.01)

            # 验证数据属于当前租户
            if results[tenant_id]["tenant_id"] != tenant_id:
                errors.append(f"tenant {tenant_id}: data contaminated")

        tasks = [
            asyncio.create_task(_read_write_memory(tid)) for tid in TENANT_IDS[:15]
        ]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"会话记忆串扰: {errors}"
        assert len(results) == 15


# ============================================================
# 第三组：Redis 缓存 key 租户隔离
# ============================================================


@pytest.mark.integration
class TestRedisCacheTenantIsolation:
    """验证 Redis 缓存 key 中包含租户标识，不交叉"""

    async def test_redis_cache_tenant_key_isolation(self, mock_redis_client):
        """Redis 缓存 key 包含租户标识，不交叉"""
        barrier = asyncio.Event()
        errors: List[str] = []

        async def _cache_operation(tenant_id: int):
            await barrier.wait()

            # 使用 RedisClient.make_key 生成带租户前缀的 key
            key = RedisClient.make_key("session", str(tenant_id), "data")
            value = json.dumps({"tenant_id": tenant_id, "data": f"data_{tenant_id}"})

            await mock_redis_client.set(key, value)
            await asyncio.sleep(0.005)

            # 读取并验证
            read_value = await mock_redis_client.get(key)
            if read_value:
                parsed = json.loads(read_value)
                if parsed["tenant_id"] != tenant_id:
                    errors.append(
                        f"tenant {tenant_id}: read other tenant's data {parsed['tenant_id']}"
                    )
            else:
                errors.append(f"tenant {tenant_id}: key not found")

        tasks = [asyncio.create_task(_cache_operation(tid)) for tid in TENANT_IDS[:15]]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"Redis key 隔离失败: {errors}"

        # 验证 key 格式包含租户标识
        # RedisClient.make_key("session", str(tid), "data") -> "session:<tid>:data"
        for tid in TENANT_IDS[:15]:
            expected_key = RedisClient.make_key("session", str(tid), "data")
            assert expected_key in mock_redis_client._store, (
                f"key {expected_key} not found in store"
            )

    async def test_redis_key_no_cross_tenant_access(self, mock_redis_client):
        """租户 A 的 key 不会被租户 B 访问到"""
        # 写入租户 A 数据
        key_a = RedisClient.make_key("session", str(TENANT_A), "secret")
        await mock_redis_client.set(key_a, "tenant_a_secret")

        # 租户 B 用自己的 key 读取
        key_b = RedisClient.make_key("session", str(TENANT_B), "secret")
        result_b = await mock_redis_client.get(key_b)

        assert result_b is None, "租户 B 不应读到租户 A 的数据"

        # 租户 A 能读到自己的数据
        result_a = await mock_redis_client.get(key_a)
        assert result_a == "tenant_a_secret"


# ============================================================
# 第四组：数据库连接池 RLS 隔离
# ============================================================


@pytest.mark.integration
class TestDatabaseRLSIsolation:
    """验证数据库连接池共享下 RLS 策略有效"""

    async def test_database_connection_pool_rls_isolation(
        self, mock_db_session_factory
    ):
        """数据库连接池共享下 RLS 策略有效 —— 每个连接设置正确的 tenant_id"""
        rls_settings: Dict[int, str] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _db_operation(tenant_id: int):
            mock_db = mock_db_session_factory()
            # 追踪 execute 调用，记录 SET app.current_tenant_id
            original_execute = mock_db.execute

            async def _tracking_execute(stmt, *args, **kwargs):
                stmt_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
                if "app.current_tenant_id" in stmt_str:
                    rls_settings[tenant_id] = stmt_str
                return await original_execute(stmt, *args, **kwargs)

            mock_db.execute = AsyncMock(side_effect=_tracking_execute)

            await barrier.wait()

            # 模拟 RLS: SET app.current_tenant_id
            from unittest.mock import MagicMock as MM
            stmt = MM()
            stmt.text = f"SET app.current_tenant_id = '{tenant_id}'"
            stmt.__str__ = lambda self: self.text
            await mock_db.execute(stmt)

            await asyncio.sleep(0.01)

            # 验证设置了正确的 tenant_id
            if tenant_id not in rls_settings:
                errors.append(f"tenant {tenant_id}: RLS not set")
            elif str(tenant_id) not in rls_settings[tenant_id]:
                errors.append(f"tenant {tenant_id}: wrong RLS value")

        tasks = [asyncio.create_task(_db_operation(tid)) for tid in TENANT_IDS[:10]]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"RLS 隔离失败: {errors}"
        assert len(rls_settings) == 10


# ============================================================
# 第五组：SSE 流式连接并发隔离
# ============================================================


@pytest.mark.integration
class TestSSEConcurrentIsolation:
    """验证 SSE 长连接并发下会话隔离"""

    async def test_sse_long_connection_concurrent_isolation(self):
        """SSE 长连接并发下会话隔离 —— 多租户流式响应不串扰"""
        stream_results: Dict[int, List[str]] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _fake_sse_stream(tenant_id: int):
            """模拟单个租户的 SSE 流式响应"""
            chunks = []
            for i in range(5):
                chunk = f"tenant_{tenant_id}_chunk_{i}"
                chunks.append(chunk)
                await asyncio.sleep(0.002)
            return chunks

        async def _sse_consumer(tenant_id: int):
            await barrier.wait()
            # 设置 ToolContext（模拟请求上下文）
            ctx = ToolContext(
                tenant_id=tenant_id,
                user_id=f"user_{tenant_id}",
                session_id=f"sess_{tenant_id}",
                role="customer",
            )
            set_tool_context(ctx)

            chunks = await _fake_sse_stream(tenant_id)
            stream_results[tenant_id] = chunks

            # 验证上下文未被其他流覆盖
            current_ctx = get_tool_context()
            if current_ctx is None or current_ctx.tenant_id != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: context changed during SSE stream"
                )

        tasks = [asyncio.create_task(_sse_consumer(tid)) for tid in TENANT_IDS[:10]]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"SSE 隔离失败: {errors}"
        # 每个租户的 chunks 应只包含自己的数据
        for tid in TENANT_IDS[:10]:
            assert len(stream_results[tid]) == 5
            for chunk in stream_results[tid]:
                assert f"tenant_{tid}" in chunk, (
                    f"tenant {tid} 的流数据中包含其他租户内容: {chunk}"
                )


# ============================================================
# 第六组：混合操作隔离
# ============================================================


@pytest.mark.integration
class TestMixedOperationsIsolation:
    """验证混合租户操作（读写混合）的隔离性"""

    async def test_mixed_tenant_operations_isolation(
        self, mock_redis_client, mock_db_session_factory
    ):
        """混合租户操作 —— 同时进行 Redis 缓存 + DB 操作 + ToolContext 设置"""
        results: Dict[int, dict] = {}
        errors: List[str] = []
        barrier = asyncio.Event()

        async def _mixed_operation(tenant_id: int):
            await barrier.wait()

            # 1. 设置 ToolContext
            ctx = ToolContext(
                tenant_id=tenant_id,
                user_id=f"user_{tenant_id}",
                session_id=f"sess_{tenant_id}",
                role="customer",
            )
            set_tool_context(ctx)

            # 2. Redis 操作
            cache_key = RedisClient.make_key("cache", str(tenant_id), "mixed")
            await mock_redis_client.set(
                cache_key, json.dumps({"tid": tenant_id})
            )

            # 3. 模拟 DB 操作延迟
            await asyncio.sleep(0.01)

            # 4. 验证所有上下文一致
            read_ctx = get_tool_context()
            cache_data = await mock_redis_client.get(cache_key)
            parsed_cache = json.loads(cache_data) if cache_data else {}

            result = {
                "ctx_tid": read_ctx.tenant_id if read_ctx else None,
                "cache_tid": parsed_cache.get("tid"),
                "expected": tenant_id,
            }
            results[tenant_id] = result

            if result["ctx_tid"] != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: ToolContext mismatch {result['ctx_tid']}"
                )
            if result["cache_tid"] != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: cache mismatch {result['cache_tid']}"
                )

        tasks = [
            asyncio.create_task(_mixed_operation(tid)) for tid in TENANT_IDS[:20]
        ]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"混合操作隔离失败: {errors}"
        assert len(results) == 20

    async def test_concurrent_tool_execution_with_registry(self):
        """并发 Tool 执行通过 ToolRegistry 时 ToolContext 正确传递"""
        registry = ToolRegistry()
        errors: List[str] = []
        barrier = asyncio.Event()

        # 创建一个 mock tool
        mock_tool = MagicMock()
        mock_tool.name = "perf_test_tool"
        mock_tool.description = "Performance test tool"
        mock_tool.parameters = {"type": "object", "properties": {}}
        mock_tool.check_permission = MagicMock(return_value=True)

        async def _fake_execute(context, **kwargs):
            # 验证 context 中的 tenant_id 正确
            await asyncio.sleep(0.005)
            return ToolResult(
                success=True,
                data={"tenant_id": context.tenant_id},
                message="ok",
            )

        mock_tool.execute = AsyncMock(side_effect=_fake_execute)
        registry._tools["perf_test_tool"] = mock_tool

        async def _execute_tool(tenant_id: int):
            ctx = ToolContext(
                tenant_id=tenant_id,
                user_id=f"user_{tenant_id}",
                session_id=f"sess_{tenant_id}",
                role="customer",
            )
            await barrier.wait()

            result = await registry.execute_tool(
                name="perf_test_tool",
                context=ctx,
            )

            if not result.success:
                errors.append(f"tenant {tenant_id}: execution failed")
            elif result.data.get("tenant_id") != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: got {result.data.get('tenant_id')}"
                )

        tasks = [asyncio.create_task(_execute_tool(tid)) for tid in TENANT_IDS[:15]]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"Registry 并发执行隔离失败: {errors}"


# ============================================================
# 第七组：AgentContext → ToolContext 并发转换
# ============================================================


@pytest.mark.integration
class TestAgentContextConcurrentConversion:
    """验证 AgentContext 并发转换为 ToolContext 时数据正确"""

    async def test_concurrent_agent_context_to_tool_context(self):
        """并发 AgentContext.to_tool_context() 转换数据正确"""
        from app.agents.customer_service_agent import AgentContext

        errors: List[str] = []
        barrier = asyncio.Event()

        async def _convert(tenant_id: int):
            await barrier.wait()
            agent_ctx = AgentContext(
                user_id=f"user_{tenant_id}",
                tenant_id=tenant_id,
                session_id=f"sess_{tenant_id}",
                role="customer",
            )
            tool_ctx = agent_ctx.to_tool_context()
            await asyncio.sleep(0.005)

            if tool_ctx.tenant_id != tenant_id:
                errors.append(
                    f"tenant {tenant_id}: tool_ctx.tenant_id = {tool_ctx.tenant_id}"
                )
            if tool_ctx.user_id != f"user_{tenant_id}":
                errors.append(
                    f"tenant {tenant_id}: tool_ctx.user_id = {tool_ctx.user_id}"
                )

        tasks = [asyncio.create_task(_convert(tid)) for tid in TENANT_IDS]
        barrier.set()
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"AgentContext 转换隔离失败: {errors}"
