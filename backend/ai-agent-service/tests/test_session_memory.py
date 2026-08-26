"""
会话记忆管理 单元测试

测试 SessionMemory 的核心方法：create_session, save_message, get_history, 
get_session, delete_session 等
"""
# case_ids: CH-005, CH-006, DA-004

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
from datetime import datetime

from app.memory.session_memory import SessionMemory


class MockDBResult:
    """模拟数据库查询结果"""
    
    def __init__(self, rows=None, single_row=None, scalar_val=None, rowcount=0):
        self._rows = rows or []
        self._single_row = single_row
        self._scalar_val = scalar_val
        self.rowcount = rowcount
    
    def fetchall(self):
        return self._rows
    
    def fetchone(self):
        return self._single_row

    def scalar(self):
        return self._scalar_val


@pytest.fixture
def mock_db():
    """创建一个 mock 数据库 session，支持 async context manager"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    
    # 支持 async with await self._get_session() as db: 模式
    # _get_session 返回的对象需要支持 __aenter__/__aexit__
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


@pytest.fixture
def memory(mock_db):
    """使用 mock db 初始化的 SessionMemory"""
    # mock _get_session 返回 mock_db (作为 async context manager)
    mem = SessionMemory(db_session=None)
    # patch _get_session 返回 mock_db
    mem._get_session = AsyncMock(return_value=mock_db)
    return mem


class TestCreateSession:
    """创建会话"""

    async def test_create_session_success(self, memory, mock_db):
        """成功创建会话"""
        session_id = await memory.create_session(
            tenant_id=1,
            customer_id="user_001",
            title="测试会话",
        )

        assert session_id.startswith("sess_")
        assert len(session_id) > 5
        mock_db.execute.assert_called()
        mock_db.commit.assert_called_once()

    async def test_create_session_default_title(self, memory, mock_db):
        """创建会话 - 使用默认标题"""
        session_id = await memory.create_session(
            tenant_id=1,
            customer_id="user_001",
        )

        assert session_id.startswith("sess_")
        mock_db.execute.assert_called()

    async def test_create_session_with_channel(self, memory, mock_db):
        """创建会话 - 指定渠道"""
        session_id = await memory.create_session(
            tenant_id=1,
            customer_id="user_001",
            channel="wechat_mini",
        )

        assert session_id.startswith("sess_")
        mock_db.commit.assert_called_once()

    async def test_create_session_db_error(self, memory, mock_db):
        """创建会话 - 数据库错误"""
        mock_db.execute.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await memory.create_session(
                tenant_id=1,
                customer_id="user_001",
            )

        mock_db.rollback.assert_called_once()


class TestSaveMessage:
    """保存消息"""

    async def test_save_message_user(self, memory, mock_db):
        """保存用户消息"""
        message_id = await memory.save_message(
            session_id="sess_test_001",
            role="user",
            content="你好，我想咨询窗帘",
            tenant_id=1,
        )

        assert message_id.startswith("msg_")
        # execute 应被调用两次：INSERT message + UPDATE sessions
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    async def test_save_message_assistant(self, memory, mock_db):
        """保存助手消息"""
        message_id = await memory.save_message(
            session_id="sess_test_001",
            role="assistant",
            content="您好！请问您想了解什么类型的窗帘？",
        )

        assert message_id.startswith("msg_")
        mock_db.commit.assert_called_once()

    async def test_save_message_with_tool_calls(self, memory, mock_db):
        """保存包含 tool_calls 的消息"""
        tool_calls = [
            {"name": "product_search", "arguments": {"keyword": "遮光窗帘"}},
        ]

        message_id = await memory.save_message(
            session_id="sess_test_001",
            role="assistant",
            content="正在为您搜索...",
            tool_calls=tool_calls,
        )

        assert message_id.startswith("msg_")
        # 验证 metadata 包含 tool_calls
        call_args = mock_db.execute.call_args_list[0]
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs
        if isinstance(params, dict) and "metadata" in params:
            metadata = json.loads(params["metadata"])
            assert "tool_calls" in metadata

    async def test_save_message_db_error(self, memory, mock_db):
        """保存消息 - 数据库错误"""
        mock_db.execute.side_effect = Exception("Insert failed")

        with pytest.raises(Exception, match="Insert failed"):
            await memory.save_message(
                session_id="sess_test_001",
                role="user",
                content="测试消息",
            )

        mock_db.rollback.assert_called_once()


class TestGetHistory:
    """获取会话历史"""

    async def test_get_history_success(self, memory, mock_db):
        """成功获取历史消息"""
        # 模拟数据库返回（注意：查询是 DESC 排序，代码内部 reversed）
        mock_rows = [
            ("msg_002", "sess_001", "assistant", "text", "您好！有什么可以帮您？", {}, datetime(2026, 4, 18, 10, 1)),
            ("msg_001", "sess_001", "user", "text", "你好", {}, datetime(2026, 4, 18, 10, 0)),
        ]
        mock_db.execute.return_value = MockDBResult(rows=mock_rows)

        messages = await memory.get_history(session_id="sess_001", limit=20)

        assert len(messages) == 2
        # reversed 后应该是正序
        assert messages[0]["id"] == "msg_001"
        assert messages[0]["role"] == "user"
        assert messages[1]["id"] == "msg_002"
        assert messages[1]["role"] == "assistant"

    async def test_get_history_empty(self, memory, mock_db):
        """历史消息为空"""
        mock_db.execute.return_value = MockDBResult(rows=[])

        messages = await memory.get_history(session_id="sess_empty")

        assert messages == []

    async def test_get_history_with_tool_calls(self, memory, mock_db):
        """历史消息包含 tool_calls"""
        mock_rows = [
            (
                "msg_003", "sess_001", "assistant", "text", "搜索中...",
                {"tool_calls": [{"name": "product_search"}]},
                datetime(2026, 4, 18, 10, 2),
            ),
        ]
        mock_db.execute.return_value = MockDBResult(rows=mock_rows)

        messages = await memory.get_history(session_id="sess_001")

        assert len(messages) == 1
        assert messages[0]["tool_calls"] == [{"name": "product_search"}]

    async def test_get_history_db_error(self, memory, mock_db):
        """获取历史 - 数据库错误（返回空列表，不抛异常）"""
        mock_db.execute.side_effect = Exception("Query failed")

        messages = await memory.get_history(session_id="sess_001")

        assert messages == []

    async def test_get_history_custom_limit(self, memory, mock_db):
        """自定义 limit 参数"""
        mock_db.execute.return_value = MockDBResult(rows=[])

        await memory.get_history(session_id="sess_001", limit=5)

        mock_db.execute.assert_called_once()


class TestGetSession:
    """获取单个会话"""

    async def test_get_session_exists(self, memory, mock_db):
        """会话存在"""
        mock_row = (
            "sess_001", 1, "user_001",
            {"title": "测试会话"},
            "active", "web",
            datetime(2026, 4, 18, 10, 0),
            datetime(2026, 4, 18, 10, 5),
        )
        mock_db.execute.return_value = MockDBResult(single_row=mock_row)

        session = await memory.get_session(session_id="sess_001")

        assert session is not None
        assert session["id"] == "sess_001"
        assert session["title"] == "测试会话"
        assert session["status"] == "active"
        assert session["channel"] == "web"

    async def test_get_session_not_exists(self, memory, mock_db):
        """会话不存在"""
        mock_db.execute.return_value = MockDBResult(single_row=None)

        session = await memory.get_session(session_id="sess_nonexist")

        assert session is None

    async def test_get_session_db_error(self, memory, mock_db):
        """获取会话 - 数据库错误（返回 None）"""
        mock_db.execute.side_effect = Exception("Query failed")

        session = await memory.get_session(session_id="sess_001")

        assert session is None


class TestSessionExists:
    """检查会话是否存在"""

    async def test_session_exists_true(self, memory, mock_db):
        """会话存在"""
        mock_row = (
            "sess_001", 1, "user_001", {}, "active", "web",
            datetime(2026, 4, 18), datetime(2026, 4, 18),
        )
        mock_db.execute.return_value = MockDBResult(single_row=mock_row)

        exists = await memory.session_exists("sess_001")
        assert exists is True

    async def test_session_exists_false(self, memory, mock_db):
        """会话不存在"""
        mock_db.execute.return_value = MockDBResult(single_row=None)

        exists = await memory.session_exists("sess_nonexist")
        assert exists is False


class TestDeleteSession:
    """删除会话"""

    async def test_delete_session_success(self, memory, mock_db):
        """成功删除会话"""
        result = await memory.delete_session(session_id="sess_001")

        assert result is True
        # 两次 execute：DELETE messages + DELETE sessions
        assert mock_db.execute.call_count == 2
        mock_db.commit.assert_called_once()

    async def test_delete_session_db_error(self, memory, mock_db):
        """删除会话 - 数据库错误"""
        mock_db.execute.side_effect = Exception("Delete failed")

        with pytest.raises(Exception, match="Delete failed"):
            await memory.delete_session(session_id="sess_001")

        mock_db.rollback.assert_called_once()


class TestCloseSession:
    """关闭会话"""

    async def test_close_session_success(self, memory, mock_db):
        """成功关闭活跃会话，并清理会话工作状态"""
        mock_db.execute.return_value.rowcount = 1
        mock_store = AsyncMock()
        mock_store.clear = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            result = await memory.close_session(session_id="sess_001")

        assert result is True
        mock_db.commit.assert_called_once()
        mock_store.clear.assert_called_once_with("sess_001")

    async def test_close_session_already_closed(self, memory, mock_db):
        """关闭已关闭的会话 — rowcount=0 不影响"""
        mock_db.execute.return_value.rowcount = 0

        result = await memory.close_session(session_id="sess_001")

        # rowcount=0 时返回 False（未更新任何行）
        assert result is False

    async def test_close_session_db_error(self, memory, mock_db):
        """关闭会话 - 数据库错误"""
        mock_db.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            await memory.close_session(session_id="sess_001")

        mock_db.rollback.assert_called_once()


class TestCloseOtherActiveSessions:
    """批量关闭其他活跃会话"""

    async def test_close_other_active_sessions_success(self, memory, mock_db):
        """成功关闭其他活跃会话"""
        mock_db.execute.return_value.rowcount = 3

        count = await memory.close_other_active_sessions(
            tenant_id=1,
            customer_id="user_001",
            except_session_id="sess_current",
        )

        assert count == 3
        mock_db.commit.assert_called_once()

    async def test_close_other_active_sessions_no_others(self, memory, mock_db):
        """没有其他活跃会话需要关闭"""
        mock_db.execute.return_value.rowcount = 0

        count = await memory.close_other_active_sessions(
            tenant_id=1,
            customer_id="user_001",
            except_session_id="sess_current",
        )

        assert count == 0

    async def test_close_other_active_sessions_without_except(self, memory, mock_db):
        """不排除任何会话 — 关闭该用户所有活跃会话"""
        mock_db.execute.return_value.rowcount = 2

        count = await memory.close_other_active_sessions(
            tenant_id=1,
            customer_id="user_001",
        )

        assert count == 2

    async def test_close_other_active_sessions_db_error(self, memory, mock_db):
        """关闭其他活跃会话 - 数据库错误（不抛异常，返回 0）"""
        mock_db.execute.side_effect = Exception("DB error")

        count = await memory.close_other_active_sessions(
            tenant_id=1,
            customer_id="user_001",
        )

        assert count == 0
        mock_db.rollback.assert_called_once()


class TestReopenSession:
    """重新打开已关闭会话"""

    async def test_reopen_session_success(self, memory, mock_db):
        """成功重新打开 closed 会话"""
        mock_db.execute.return_value.rowcount = 1

        result = await memory.reopen_session(session_id="sess_001")

        assert result is True
        mock_db.commit.assert_called_once()

    async def test_reopen_session_not_closed(self, memory, mock_db):
        """重新打开非 closed 会话 — 不会更新"""
        mock_db.execute.return_value.rowcount = 0

        result = await memory.reopen_session(session_id="sess_001")

        assert result is False

    async def test_reopen_session_db_error(self, memory, mock_db):
        """重新打开会话 - 数据库错误"""
        mock_db.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            await memory.reopen_session(session_id="sess_001")

        mock_db.rollback.assert_called_once()


class TestSessionMemoryHelpers:
    """辅助方法"""

    def test_generate_session_id(self):
        """生成 session ID 格式正确"""
        mem = SessionMemory()
        sid = mem._generate_session_id()
        assert sid.startswith("sess_")
        assert len(sid) == 21  # "sess_" + 16 hex chars

    def test_generate_message_id(self):
        """生成 message ID 格式正确"""
        mem = SessionMemory()
        mid = mem._generate_message_id()
        assert mid.startswith("msg_")
        assert len(mid) == 20  # "msg_" + 16 hex chars

    def test_now_iso_format(self):
        """ISO 时间格式"""
        mem = SessionMemory()
        iso_time = mem._now_iso()
        assert iso_time.endswith("Z")
        assert "T" in iso_time

    def test_now_returns_datetime(self):
        """_now 返回 datetime 对象"""
        mem = SessionMemory()
        now = mem._now()
        assert isinstance(now, datetime)

    def test_init_with_db_session(self):
        """带 db_session 初始化"""
        mock_db = AsyncMock()
        mem = SessionMemory(db_session=mock_db)
        assert mem._db is mock_db

    def test_init_without_db_session(self):
        """不带 db_session 初始化"""
        mem = SessionMemory()
        assert mem._db is None


class TestCloseIdleSessions:
    """自动关闭空闲会话"""

    async def test_close_idle_sessions_closes_stale(self, memory, mock_db):
        """关闭空闲会话，并清理其工作状态（决策②）"""
        from datetime import datetime, timedelta
        # 第一次 execute 是 SELECT idle ids；第二次是 UPDATE
        select_result = MockDBResult(rows=[("s1",), ("s2",)])
        update_result = MockDBResult(rowcount=2)
        mock_db.execute.side_effect = [select_result, update_result]
        mock_store = AsyncMock()
        mock_store.clear = AsyncMock(return_value=True)

        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            count = await memory.close_idle_sessions(idle_minutes=30)

        assert count == 2
        assert mock_db.execute.call_count == 2
        # 清理了两个会话的工作状态
        assert mock_store.clear.call_count == 2

    async def test_close_idle_sessions_none_idle(self, memory, mock_db):
        """没有空闲会话时返回0"""
        select_result = MockDBResult(rows=[])
        update_result = MockDBResult(rowcount=0)
        mock_db.execute.side_effect = [select_result, update_result]

        count = await memory.close_idle_sessions(idle_minutes=30)

        assert count == 0

    async def test_close_idle_sessions_handles_error(self, memory, mock_db):
        """数据库错误时返回0，不抛异常"""
        mock_db.execute.side_effect = Exception('DB error')

        count = await memory.close_idle_sessions(idle_minutes=30)

        assert count == 0  # 降级返回0


class TestGetHistoryByTokens:
    """按 token 预算加载历史消息"""

    async def test_returns_messages_and_compression_flag(self, memory, mock_db):
        rows = [
            ("msg_1", "s1", "user", "text", f"hello{i}", {}, 10, "2026-01-01", 10)
            for i in range(5)
        ]
        mock_db.execute.side_effect = [MockDBResult(rows=rows), MockDBResult(scalar_val=8)]

        messages, needs_compression = await memory.get_history_by_tokens(
            "s1", max_tokens=1000
        )

        assert len(messages) == 5
        assert messages[0]["content"] == "hello0"
        assert messages[0]["token_count"] == 10
        assert needs_compression is True  # 总消息 8 > 返回 5 且返回 > min_messages(4)

    async def test_no_compression_when_all_returned(self, memory, mock_db):
        rows = [
            ("msg_1", "s1", "user", "text", "hello", {}, 10, "2026-01-01", 10),
        ]
        mock_db.execute.side_effect = [MockDBResult(rows=rows), MockDBResult(scalar_val=1)]

        messages, needs_compression = await memory.get_history_by_tokens("s1")

        assert needs_compression is False

    async def test_error_falls_back_to_get_history(self, memory, mock_db):
        mock_db.execute.side_effect = Exception("DB down")

        messages, needs_compression = await memory.get_history_by_tokens("s1")

        assert needs_compression is True


class TestPendingSkill:
    """pending_interact_skill 持久化（会话管理重构 P1：经 SessionStateStore）"""

    async def test_set_pending_skill(self, memory, mock_db):
        """写入经 SessionStateStore，commit 一次"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={})
        mock_store.commit = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.set_pending_skill("s1", "product") is True
        mock_store.commit.assert_called_once()
        state = mock_store.commit.call_args[0][1]
        assert state["pending_skill"] == "product"

    async def test_set_pending_skill_empty_clears(self, memory, mock_db):
        """空值清除，且清 metadata 存量避免双写漂移"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"pending_skill": "product", "entities": {}})
        mock_store.commit = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.set_pending_skill("s1", "") is True
        state = mock_store.commit.call_args[0][1]
        assert "pending_skill" not in state
        assert state["entities"] == {}
        # 存量 metadata 也需清除
        assert mock_db.commit.call_count >= 1

    async def test_get_pending_skill_from_store(self, memory, mock_db):
        """优先从 SessionStateStore 读取"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"pending_skill": "product"})
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.get_pending_skill("s1") == "product"
        mock_store.load.assert_called_once_with("s1")

    async def test_get_pending_skill_store_empty_falls_back_to_metadata(self, memory, mock_db):
        """store 无数据时回退读存量 metadata（迁移兼容）"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            mock_db.execute.return_value = MockDBResult(single_row=("order",))
            assert await memory.get_pending_skill("s1") == "order"

    async def test_get_pending_skill_none(self, memory, mock_db):
        """两路都无 → 空字符串"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            mock_db.execute.return_value = MockDBResult(single_row=None)
            assert await memory.get_pending_skill("s1") == ""

    async def test_clear_pending_skill(self, memory, mock_db):
        """清除 store 字段 + metadata 存量"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"pending_skill": "product"})
        mock_store.commit = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.clear_pending_skill("s1") is True
        state = mock_store.commit.call_args[0][1]
        assert "pending_skill" not in state
        assert mock_db.commit.call_count >= 1


class TestPlanState:
    """P&E Plan 状态持久化（仅保留读取路径，写路径已删除）"""

    async def test_get_plan_state(self, memory, mock_db):
        mock_db.execute.return_value = MockDBResult(single_row=('{"steps": []}',))
        assert await memory.get_plan_state("s1") == '{"steps": []}'

    async def test_get_plan_state_empty(self, memory, mock_db):
        mock_db.execute.return_value = MockDBResult(single_row=None)
        assert await memory.get_plan_state("s1") is None


class TestVisionAnalysis:
    """Vision 分析缓存（会话管理重构 P1：经 SessionStateStore）"""

    async def test_set_truncates_to_3000(self, memory, mock_db):
        """写入 store，超长截断 3000"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={})
        mock_store.commit = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            result = await memory.set_vision_analysis("s1", "长" * 4000)
        assert result is True
        state = mock_store.commit.call_args[0][1]
        assert len(state["vision_analysis"]) == 3000

    async def test_get_vision_analysis_from_store(self, memory, mock_db):
        """优先从 store 读取"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"vision_analysis": "分析结果"})
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.get_vision_analysis("s1") == "分析结果"

    async def test_get_vision_analysis_store_empty_falls_back(self, memory, mock_db):
        """store 无数据时回退读 metadata 存量"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            mock_db.execute.return_value = MockDBResult(single_row=("分析结果",))
            assert await memory.get_vision_analysis("s1") == "分析结果"

    async def test_get_vision_analysis_empty(self, memory, mock_db):
        """两路都无 → 空字符串"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            mock_db.execute.return_value = MockDBResult(single_row=None)
            assert await memory.get_vision_analysis("s1") == ""

    async def test_clear_vision_analysis(self, memory, mock_db):
        """清除 store 字段 + metadata 存量"""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"vision_analysis": "x"})
        mock_store.commit = AsyncMock(return_value=True)
        with patch("app.memory.session_memory.SessionStateStore", return_value=mock_store):
            assert await memory.clear_vision_analysis("s1") is True
        state = mock_store.commit.call_args[0][1]
        assert "vision_analysis" not in state
        assert mock_db.commit.call_count >= 1


class TestCleanupClosedSessions:
    async def test_cleanup_returns_count(self, memory, mock_db):
        mock_db.execute.return_value.rowcount = 3
        count = await memory.cleanup_closed_sessions(older_than_days=90)
        assert count == 3
