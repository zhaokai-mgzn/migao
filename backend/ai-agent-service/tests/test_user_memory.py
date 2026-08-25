"""用户记忆管理单元测试（app/memory/user_memory.py）

覆盖：
- get_important_memories：importance 阈值过滤 + 降序 + LIMIT 20
- format_for_prompt：preference/fact/feedback 分组 XML，无记忆返回空串
- upsert：按 tenant+user+key 去重（存在更新 / 不存在插入 mem_ 前缀 ID）；异常返回 None
- batch_upsert / decay_importance / delete / delete_by_key
"""
# case_ids: CH-005
import pytest

from app.memory.user_memory import UserMemoryManager


class FakeResult:
    def __init__(self, rows=None, single=None, scalar=None, rowcount=0):
        self._rows = rows or []
        self._single = single
        self._scalar = scalar
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._single

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, results=None, error=None):
        self._results = list(results or [])
        self.error = error
        self.executed = []
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.error is not None:
            raise self.error
        if self._results:
            return self._results.pop(0)
        return FakeResult()

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


def _memory_row(id_, type_, key, value, importance=0.8):
    return (id_, 1, "user_1", type_, key, value, importance, "ctx", "2026-01-01", "2026-01-02")


class TestGetImportantMemories:
    @pytest.mark.asyncio
    async def test_maps_rows_to_dicts(self):
        rows = [
            _memory_row("m1", "fact", "city", "杭州", importance=0.9),
            _memory_row("m2", "fact", "name", "张三", importance=0.7),
        ]
        session = FakeSession(results=[FakeResult(rows=rows)])
        mgr = UserMemoryManager(db_session=session)

        memories = await mgr.get_important_memories(1, "user_1")

        assert len(memories) == 2
        assert memories[0]["id"] == "m1"
        assert memories[0]["key"] == "city"
        assert memories[1]["id"] == "m2"
        assert memories[1]["importance"] == 0.7

    @pytest.mark.asyncio
    async def test_passes_importance_threshold_in_sql(self):
        session = FakeSession(results=[FakeResult(rows=[])])
        mgr = UserMemoryManager(db_session=session)
        await mgr.get_important_memories(1, "user_1")
        # 阈值过滤在 SQL 层，参数须含 min_importance 且默认 0.5
        params = session.executed[0][1]
        assert params["min_importance"] == 0.5

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        session = FakeSession(results=[FakeResult(rows=[])])
        mgr = UserMemoryManager(db_session=session)
        await mgr.get_important_memories(1, "user_1", min_importance=0.9)
        # 阈值通过 SQL 参数透传
        params = session.executed[0][1]
        assert params["min_importance"] == 0.9


class TestFormatForPrompt:
    @pytest.mark.asyncio
    async def test_groups_by_type(self):
        rows = [
            _memory_row("m1", "preference", "color", "深蓝"),
            _memory_row("m2", "fact", "city", "杭州"),
            _memory_row("m3", "feedback", "like", "喜欢遮光"),
        ]
        session = FakeSession(results=[FakeResult(rows=rows)])
        mgr = UserMemoryManager(db_session=session)

        text = await mgr.format_for_prompt(1, "user_1")

        assert "<preferences>" in text
        assert "<facts>" in text
        assert "<feedback>" in text
        assert "深蓝" in text
        assert "city: 杭州" in text

    @pytest.mark.asyncio
    async def test_no_memories_returns_empty(self):
        session = FakeSession(results=[FakeResult(rows=[])])
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.format_for_prompt(1, "user_1") == ""


class TestUpsert:
    @pytest.mark.asyncio
    async def test_insert_new_memory(self):
        session = FakeSession(results=[FakeResult(single=None), FakeResult()])
        mgr = UserMemoryManager(db_session=session)

        memory_id = await mgr.upsert(1, "user_1", "fact", "city", "杭州")

        assert memory_id.startswith("mem_")
        assert session.committed == 1

    @pytest.mark.asyncio
    async def test_update_existing_memory(self):
        session = FakeSession(results=[FakeResult(single=("mem_old",)), FakeResult()])
        mgr = UserMemoryManager(db_session=session)

        memory_id = await mgr.upsert(1, "user_1", "fact", "city", "上海")

        assert memory_id == "mem_old"
        assert session.committed == 1

    @pytest.mark.asyncio
    async def test_failure_rolls_back_and_returns_none(self):
        session = FakeSession(results=[FakeResult(single=None)], error=RuntimeError("db down"))
        mgr = UserMemoryManager(db_session=session)

        memory_id = await mgr.upsert(1, "user_1", "fact", "city", "杭州")

        assert (memory_id is None)
        assert session.rolled_back == 1


class TestBatchUpsert:
    @pytest.mark.asyncio
    async def test_counts_success(self):
        session = FakeSession(results=[FakeResult(single=None), FakeResult()])
        mgr = UserMemoryManager(db_session=session)

        count = await mgr.batch_upsert(1, "user_1", [
            {"type": "fact", "key": "k1", "value": "v1"},
            {"type": "fact", "key": "k2", "value": "v2"},
        ])

        assert count == 2


class TestDecayImportance:
    @pytest.mark.asyncio
    async def test_returns_rowcount(self):
        session = FakeSession(results=[FakeResult(rowcount=3)])
        mgr = UserMemoryManager(db_session=session)

        affected = await mgr.decay_importance(1, "user_1", decay_factor=0.9)

        assert affected == 3
        assert session.committed == 1

    @pytest.mark.asyncio
    async def test_failure_returns_zero(self):
        session = FakeSession(results=[FakeResult()], error=RuntimeError("boom"))
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.decay_importance(1, "user_1") == 0


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        session = FakeSession(results=[FakeResult()])
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.delete("mem_x") is True

    @pytest.mark.asyncio
    async def test_delete_failure_returns_false(self):
        session = FakeSession(results=[FakeResult()], error=RuntimeError("boom"))
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.delete("mem_x") is False

    @pytest.mark.asyncio
    async def test_delete_by_key_returns_rowcount_flag(self):
        session = FakeSession(results=[FakeResult(rowcount=1)])
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.delete_by_key(1, "user_1", "city") is True

    @pytest.mark.asyncio
    async def test_delete_by_key_missing_returns_false(self):
        session = FakeSession(results=[FakeResult(rowcount=0)])
        mgr = UserMemoryManager(db_session=session)
        assert await mgr.delete_by_key(1, "user_1", "city") is False
