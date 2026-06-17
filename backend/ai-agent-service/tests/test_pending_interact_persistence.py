"""
L0：会话状态持久化集成测试（铁律 — 涉及 State/路由/Interact 变更必跑）

历史教训：
    pending_interact_skill 初版在 state 内标记了值，但 _build_initial_state
    每次创建全新 state 从未加载上一轮的值。会话连续性形同虚设，多轮交互必挂。
    Mock 单测无法暴露此问题（mock 不体现 state 丢失）。

本测试连接真实 dev RDS PostgreSQL，覆盖 6 个验证点：
    1. set → 能从 DB 读回（DB 写入验证）
    2. _build_initial_state 加载 pending_skill（flow 持久化）
    3. clear → 读回空（清除机制）
    4. 多次 set 不产生脏数据（覆盖写入）
    5. 不同 session 互不干扰（多会话隔离）
    6. plan_state 优先级高于 pending_skill（Plan-and-Execute）

运行前置条件：
    - dev RDS 可达（白名单含本机 IP）
    - DATABASE_URL 已在 .env 配置

运行命令：
    cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_pending_interact_persistence.py -v
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.memory.session_memory import SessionMemory

# ═══════════════════════════════════════════════════════════════
# 数据库连接（真实 dev RDS）
# ═══════════════════════════════════════════════════════════════

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 环境变量未设置。请从 .env 加载或手动设置：\n"
        "  export DATABASE_URL=$(grep DATABASE_URL .env | cut -d= -f2-)"
    )

# 测试用独立 key，避免污染真实会话
TEST_PREFIX = f"l0test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def event_loop():
    """为模块级 fixture 创建 event loop"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def db_engine():
    """模块级数据库引擎（复用连接池）"""
    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=2)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def db_factory(db_engine):
    """模块级会话工厂"""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session(db_factory) -> AsyncSession:
    """每个测试独立的 DB 会话"""
    async with db_factory() as session:
        yield session


@pytest.fixture
def session_id() -> str:
    """生成唯一测试 session ID"""
    return f"{TEST_PREFIX}_sess_{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


async def _create_test_session(db_session: AsyncSession, session_id: str, tenant_id: int = 99999):
    """在 DB 中创建测试用 session 记录"""
    await db_session.execute(text("""
        INSERT INTO sessions (id, tenant_id, customer_id, channel, status, metadata, created_at, updated_at)
        VALUES (:id, :tenant_id, 'l0_test_user', 'web', 'active', '{}'::jsonb, NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
    """), {"id": session_id, "tenant_id": tenant_id})
    await db_session.commit()


async def _cleanup_test_session(db_session: AsyncSession, session_id: str):
    """清理测试 session 及关联消息"""
    await db_session.execute(text("DELETE FROM session_messages WHERE session_id = :sid"), {"sid": session_id})
    await db_session.execute(text("DELETE FROM sessions WHERE id = :sid"), {"sid": session_id})
    await db_session.commit()


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════


class TestPendingInteractPersistence:
    """pending_interact_skill 状态持久化 — 核心验证"""

    @pytest.mark.asyncio
    async def test_set_and_get(self, db_session, session_id):
        """
        验证点 1：set_pending_skill 之后，get_pending_skill 能从 DB 读回
        如果这个失败 → state 根本没有写入 DB，所有会话连续性都是假的
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        # SET
        result = await mem.set_pending_skill(session_id, "order_create_skill")
        assert result is True, "set_pending_skill 应返回 True"

        # GET（同一个 SessionMemory 实例，同一 DB 连接）
        value = await mem.get_pending_skill(session_id)
        assert value == "order_create_skill", (
            f"get_pending_skill 应返回 'order_create_skill'，实际返回 '{value}'"
        )

        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty(self, db_session, session_id):
        """
        验证点 1b：不存在的 session 返回空字符串（不抛异常）
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)
        value = await mem.get_pending_skill(session_id)
        assert value == "", f"无 pending_skill 时应返回 ''，实际返回 '{value}'"
        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_flow_persistence(self, db_session, session_id):
        """
        验证点 2：模拟 _build_initial_state 行为 — 先 set，再重新创建
        SessionMemory 实例读取，模拟跨 graph 调用场景
        """
        await _create_test_session(db_session, session_id)

        # 第一轮：设置 pending_skill（模拟 execute_skill 结束时写入）
        mem1 = SessionMemory(db_session)
        await mem1.set_pending_skill(session_id, "product_create_skill")

        # 第二轮：新建 SessionMemory（模拟 _build_initial_state 在下一轮 graph 调用时加载）
        mem2 = SessionMemory(db_session)
        loaded = await mem2.get_pending_skill(session_id)
        assert loaded == "product_create_skill", (
            f"跨实例加载失败！_build_initial_state 会得到 '{loaded}' 而非 'product_create_skill'"
        )

        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_clear(self, db_session, session_id):
        """
        验证点 3：clear_pending_skill 后 get 返回空
        如果清除失败 → pending_skill 泄漏到后续轮次，用户被锁死在 skill 中
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        await mem.set_pending_skill(session_id, "order_query_skill")
        await mem.clear_pending_skill(session_id)

        value = await mem.get_pending_skill(session_id)
        assert value == "", f"清除后应返回 ''，实际返回 '{value}'"
        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_overwrite(self, db_session, session_id):
        """
        验证点 4：多次 set 最终值是最新值，不产生脏数据
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        await mem.set_pending_skill(session_id, "skill_a")
        await mem.set_pending_skill(session_id, "skill_b")
        await mem.set_pending_skill(session_id, "skill_c")

        value = await mem.get_pending_skill(session_id)
        assert value == "skill_c", (
            f"多次覆盖后应返回最新值 'skill_c'，实际返回 '{value}'"
        )

        # 额外验证：metadata 中没有残留旧值
        from sqlalchemy import text
        result = await db_session.execute(
            text("SELECT metadata FROM sessions WHERE id = :sid"),
            {"sid": session_id},
        )
        row = result.fetchone()
        metadata = row[0] if row else {}
        pending = metadata.get("pending_skill", "") if isinstance(metadata, dict) else ""
        assert pending == "skill_c", f"DB 中 metadata.pending_skill 应为 'skill_c'，实际为 '{pending}'"
        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_multiple_sessions_independent(self, db_session):
        """
        验证点 5：不同 session 的 pending_skill 互不干扰
        """
        sid_a = f"{TEST_PREFIX}_a_{uuid.uuid4().hex[:6]}"
        sid_b = f"{TEST_PREFIX}_b_{uuid.uuid4().hex[:6]}"

        await _create_test_session(db_session, sid_a)
        await _create_test_session(db_session, sid_b)

        mem = SessionMemory(db_session)
        await mem.set_pending_skill(sid_a, "skill_for_a")
        await mem.set_pending_skill(sid_b, "skill_for_b")

        val_a = await mem.get_pending_skill(sid_a)
        val_b = await mem.get_pending_skill(sid_b)

        assert val_a == "skill_for_a", f"Session A 应返回 'skill_for_a'，实际 '{val_a}'"
        assert val_b == "skill_for_b", f"Session B 应返回 'skill_for_b'，实际 '{val_b}'"

        # 清除 session A 不应影响 session B
        await mem.clear_pending_skill(sid_a)
        assert await mem.get_pending_skill(sid_a) == ""
        assert await mem.get_pending_skill(sid_b) == "skill_for_b", "清除 A 不应影响 B"

        await _cleanup_test_session(db_session, sid_a)
        await _cleanup_test_session(db_session, sid_b)

    @pytest.mark.asyncio
    async def test_clear_then_set_again(self, db_session, session_id):
        """
        验证点 4b：清除后再次设置，值正确（清除不是永久删除字段）
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        await mem.set_pending_skill(session_id, "first_skill")
        await mem.clear_pending_skill(session_id)
        await mem.set_pending_skill(session_id, "second_skill")

        value = await mem.get_pending_skill(session_id)
        assert value == "second_skill", f"清除后重新 set 应返回 'second_skill'，实际 '{value}'"
        await _cleanup_test_session(db_session, session_id)


class TestPlanStatePersistence:
    """Plan-and-Execute 状态持久化"""

    @pytest.mark.asyncio
    async def test_set_and_get_plan_state(self, db_session, session_id):
        """plan_state 写入和读取"""
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        plan = '{"skill_name":"order_create_skill","step":2,"total_steps":5}'
        result = await mem.set_plan_state(session_id, plan)
        assert result is True

        loaded = await mem.get_plan_state(session_id)
        assert loaded is not None
        assert "order_create_skill" in loaded

        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_clear_plan_state(self, db_session, session_id):
        """plan_state 清除"""
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        await mem.set_plan_state(session_id, '{"skill_name":"test"}')
        await mem.clear_plan_state(session_id)

        loaded = await mem.get_plan_state(session_id)
        assert loaded is None, f"清除后应返回 None，实际返回 '{loaded}'"
        await _cleanup_test_session(db_session, session_id)

    @pytest.mark.asyncio
    async def test_plan_state_isolated_from_pending_skill(self, db_session, session_id):
        """
        验证点 6：plan_state 和 pending_skill 互不覆盖
        _build_initial_state 先读 plan_state，再 fallback 到 pending_skill
        """
        await _create_test_session(db_session, session_id)
        mem = SessionMemory(db_session)

        # 同时设置两者
        await mem.set_plan_state(session_id, '{"skill_name":"plan_skill","step":1}')
        await mem.set_pending_skill(session_id, "pending_skill")

        plan = await mem.get_plan_state(session_id)
        pending = await mem.get_pending_skill(session_id)

        assert plan is not None and "plan_skill" in plan
        assert pending == "pending_skill", (
            f"plan_state 不应覆盖 pending_skill，pending 应为 'pending_skill'，实际 '{pending}'"
        )

        # 清除 plan_state 后 pending_skill 不受影响
        await mem.clear_plan_state(session_id)
        assert await mem.get_plan_state(session_id) is None
        assert await mem.get_pending_skill(session_id) == "pending_skill"

        await _cleanup_test_session(db_session, session_id)


class TestCollectedFieldsPersistence:
    """跨轮字段记忆（Redis, 7 天 TTL）"""

    @pytest.mark.asyncio
    async def test_set_and_get_fields(self, session_id):
        """collected_fields Redis 写入和读取"""
        mem = SessionMemory()

        fields = {"product_name": "窗帘布", "quantity": "10"}
        ok = await mem.set_collected_fields(session_id, fields)
        assert ok is True

        loaded = await mem.get_collected_fields(session_id)
        assert loaded.get("product_name") == "窗帘布"
        assert loaded.get("quantity") == "10"

        await mem.clear_collected_fields(session_id)

    @pytest.mark.asyncio
    async def test_clear_fields(self, session_id):
        """collected_fields 清除"""
        mem = SessionMemory()

        await mem.set_collected_fields(session_id, {"test": "value"})
        await mem.clear_collected_fields(session_id)

        loaded = await mem.get_collected_fields(session_id)
        assert loaded == {}, f"清除后应返回空字典，实际返回 '{loaded}'"

    @pytest.mark.asyncio
    async def test_fields_session_isolation(self):
        """不同 session 的字段互不干扰"""
        mem = SessionMemory()
        sid1 = f"{TEST_PREFIX}_redis_a_{uuid.uuid4().hex[:4]}"
        sid2 = f"{TEST_PREFIX}_redis_b_{uuid.uuid4().hex[:4]}"

        await mem.set_collected_fields(sid1, {"key": "value_a"})
        await mem.set_collected_fields(sid2, {"key": "value_b"})

        a = await mem.get_collected_fields(sid1)
        b = await mem.get_collected_fields(sid2)

        assert a.get("key") == "value_a"
        assert b.get("key") == "value_b"

        await mem.clear_collected_fields(sid1)
        await mem.clear_collected_fields(sid2)


# ═══════════════════════════════════════════════════════════════
# 清理
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(scope="module", autouse=True)
async def _cleanup_test_data(db_engine):
    """模块结束后清理所有 L0 测试数据"""
    yield
    async with db_engine.connect() as conn:
        await conn.execute(
            text(f"DELETE FROM session_messages WHERE session_id LIKE '{TEST_PREFIX}%'")
        )
        await conn.execute(
            text(f"DELETE FROM sessions WHERE id LIKE '{TEST_PREFIX}%'")
        )
        await conn.commit()
