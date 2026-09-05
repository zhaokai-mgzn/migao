"""
会话工作状态存储 单元测试（会话管理重构 P1）

SessionStateStore 是跨轮工作状态的单一事实源（PG session_states 表）。
覆盖：
- load：不存在 / 存在 / 空 state
- commit：插入 / 覆盖更新（upsert）/ 空 state
- clear：删除
- 序列化往返：复杂状态 JSON 往返一致
"""
# case_ids: CH-005

import pytest
import json
from unittest.mock import AsyncMock
from datetime import timezone

from app.memory.session_state_store import SessionStateStore


class MockDBResult:
    """模拟数据库查询结果"""

    def __init__(self, rows=None, single_row=None, rowcount=0):
        self._rows = rows or []
        self._single_row = single_row
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._single_row


@pytest.fixture
def mock_db():
    """mock 数据库 session，支持 async context manager"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


@pytest.fixture
def store(mock_db):
    s = SessionStateStore()
    s._get_session = AsyncMock(return_value=mock_db)
    return s


class TestLoad:
    async def test_load_missing_returns_none(self, store, mock_db):
        """不存在的会话 → None"""
        mock_db.execute.return_value = MockDBResult(single_row=None)
        assert await store.load("s_missing") is None

    async def test_load_existing_returns_parsed_state(self, store, mock_db):
        """存在会话 → 返回解析后的 state dict"""
        raw = {"entities": {"product_ids": [{"id": "p1", "name": "窗帘"}]},
               "pending_skill": "product"}
        mock_db.execute.return_value = MockDBResult(single_row=(json.dumps(raw),))
        state = await store.load("s1")
        assert state == raw
        assert state["entities"]["product_ids"][0]["name"] == "窗帘"

    async def test_load_empty_state_returns_empty_dict(self, store, mock_db):
        """state 为空字符串或 '{}' → 空 dict（不返回 None）"""
        mock_db.execute.return_value = MockDBResult(single_row=("{}",))
        assert await store.load("s1") == {}

    async def test_load_jsonb_column_returns_dict(self, store, mock_db):
        """asyncpg 对 jsonb 列返回 dict（非 str）→ 原样返回，不得崩溃

        生产事故（sess_9cfeb2c8b3df4a8f）：真实 PG jsonb 经 asyncpg 解码为 dict，
        json.loads(dict) 抛 TypeError → load 恒返回 None → 跨轮状态全部失效。
        此前测试用 json.dumps 字符串 mock，掩盖了该缺陷。
        """
        raw = {"pending_validated_input": {"target_tool": "product_manage",
                                           "target_action": "create",
                                           "params": {"name": "窗帘"}}}
        mock_db.execute.return_value = MockDBResult(single_row=(raw,))
        state = await store.load("s1")
        assert state == raw
        assert state["pending_validated_input"]["target_tool"] == "product_manage"

    async def test_load_jsonb_none_state_returns_none(self, store, mock_db):
        """jsonb state 为 None（不应发生但需防御）→ None，不崩溃"""
        mock_db.execute.return_value = MockDBResult(single_row=(None,))
        assert await store.load("s1") is None

    async def test_load_db_error_returns_none(self, store, mock_db):
        """DB 异常降级为 None，不抛出"""
        mock_db.execute.side_effect = Exception("DB down")
        assert await store.load("s1") is None


class TestCommit:
    async def test_commit_calls_upsert_sql(self, store, mock_db):
        """commit 执行 upsert 并提交事务"""
        state = {"pending_skill": "product", "entities": {}}
        result = await store.commit("s1", state)
        assert result is True
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    async def test_commit_roundtrip(self, store, mock_db):
        """commit → load 往返一致（含复杂嵌套）"""
        state = {
            "entities": {
                "product_ids": [{"id": "p1", "name": "遮光窗帘", "source": "product_search"}],
                "order_nos": [{"id": "o1", "no": "ORD-001", "source": "order_query"}],
            },
            "pending_skill": "order",
            "stage": "confirming",
            "vision_fields": {"name": "窗帘"},
            "last_skill": "order",
            "tool_results": [{"tool": "order_query", "summary": "3 条"}],
        }
        await store.commit("s1", state)

        # 模拟第二次查询返回 commit 写入的内容
        mock_db.execute.return_value = MockDBResult(single_row=(json.dumps(state),))
        loaded = await store.load("s1")
        assert loaded == state

    async def test_commit_empty_state(self, store, mock_db):
        """空 state 也允许提交（清空语义）"""
        assert await store.commit("s1", {}) is True

    async def test_commit_db_error_returns_false(self, store, mock_db):
        """DB 异常返回 False，不抛出"""
        mock_db.execute.side_effect = Exception("DB down")
        assert await store.commit("s1", {"pending_skill": "x"}) is False

    async def test_commit_binds_aware_utc_updated_at(self, store, mock_db):
        """commit 的 updated_at 必须是 aware UTC

        线上 sess_60238786c0694dbc 实证：naive utcnow 经 asyncpg 按连接时区
        （Asia/Shanghai）解读 → session_states.updated_at 落库偏移 8h。
        """
        assert await store.commit("s1", {"pending_skill": "product"}) is True

        params = mock_db.execute.call_args.args[1]
        assert params["now"].tzinfo is not None, "updated_at 必须是 timezone-aware"
        assert params["now"].tzinfo == timezone.utc, "updated_at 必须是 UTC"


class TestClear:
    async def test_clear_executes_delete(self, store, mock_db):
        """clear 执行 DELETE 并提交"""
        mock_db.execute.return_value = MockDBResult(rowcount=1)
        result = await store.clear("s1")
        assert result is True
        mock_db.commit.assert_called_once()

    async def test_clear_missing_returns_true(self, store, mock_db):
        """清理不存在的会话也返回 True（幂等）"""
        mock_db.execute.return_value = MockDBResult(rowcount=0)
        assert await store.clear("s1") is True

    async def test_clear_db_error_returns_false(self, store, mock_db):
        """DB 异常返回 False，不抛出"""
        mock_db.execute.side_effect = Exception("DB down")
        assert await store.clear("s1") is False
