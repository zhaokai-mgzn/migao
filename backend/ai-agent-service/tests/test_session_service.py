"""
会话生命周期状态机 单元测试（会话管理重构 P2）

SessionService 是会话状态迁移的唯一写入者：
- 状态迁移表：active ⇄ closed
- 非法迁移（active→active、closed→closed）被拒绝
- 底层 SQL 委托 SessionMemory（close/reopen/delete 已实现）
"""
# case_ids: CH-005

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.session_service import SessionService


@pytest.fixture
def service():
    mem = MagicMock()
    s = SessionService(memory=mem)
    return s, mem


class TestStateTransitions:
    """状态迁移表（active ⇄ closed）"""

    def test_valid_transitions(self):
        """允许的迁移：active→closed, closed→active"""
        assert SessionService.can_transition("active", "closed") is True
        assert SessionService.can_transition("closed", "active") is True

    def test_invalid_transitions(self):
        """非法迁移：active 不可 reopen（需先 close），closed 不可重复 close"""
        assert SessionService.can_transition("active", "active") is False
        assert SessionService.can_transition("closed", "closed") is False

    def test_same_state_not_allowed(self):
        assert SessionService.can_transition("active", "active") is False


class TestClose:
    async def test_close_active_success(self, service):
        """active → closed，委托 SessionMemory.close_session"""
        s, mem = service
        mem.close_session = AsyncMock(return_value=True)
        result = await s.close("s1")
        assert result is True
        mem.close_session.assert_awaited_once_with("s1")

    async def test_close_already_closed_idempotent(self, service):
        """已 closed 的会话再 close 返回 True（幂等，不抛异常）"""
        s, mem = service
        mem.close_session = AsyncMock(return_value=True)
        assert await s.close("s1") is True


class TestReopen:
    async def test_reopen_closed_success(self, service):
        """closed → active，委托 SessionMemory.reopen_session"""
        s, mem = service
        mem.get_session = AsyncMock(return_value={"status": "closed"})
        mem.reopen_session = AsyncMock(return_value=True)
        result = await s.reopen("s1")
        assert result is True
        mem.reopen_session.assert_awaited_once_with("s1")

    async def test_reopen_active_returns_false(self, service):
        """active 会话不可 reopen（非法迁移，返回 False）"""
        s, mem = service
        mem.get_session = AsyncMock(return_value={"status": "active"})
        result = await s.reopen("s1")
        assert result is False


class TestExpire:
    async def test_expire_idle_delegates(self, service):
        """active → expired 批量委托 close_idle_sessions"""
        s, mem = service
        mem.close_idle_sessions = AsyncMock(return_value=3)
        count = await s.expire_idle(idle_minutes=30)
        assert count == 3
        mem.close_idle_sessions.assert_awaited_once_with(idle_minutes=30)


class TestPurge:
    async def test_purge_delegates(self, service):
        """purged 物理清理委托 cleanup_closed_sessions"""
        s, mem = service
        mem.cleanup_closed_sessions = AsyncMock(return_value=5)
        count = await s.purge(older_than_days=90)
        assert count == 5
        mem.cleanup_closed_sessions.assert_awaited_once_with(older_than_days=90)


class TestSendGate:
    async def test_send_gate_valid_session(self, service):
        """合法会话：返回 (session, None)，刷新 last_activity"""
        s, mem = service
        session = {"session_id": "s1", "tenant_id": 1, "customer_id": "u1", "status": "active"}
        mem.get_session = AsyncMock(return_value=session)
        mem.touch_activity = AsyncMock(return_value=True)

        result, error = await s.send_gate("s1", tenant_id=1, user_id="u1")
        assert result == session
        assert result["session_id"] == "s1"
        assert not error  # 无错误
        mem.touch_activity.assert_awaited_once_with("s1")

    async def test_send_gate_missing_session(self, service):
        """会话不存在 → (None, (code, message))"""
        s, mem = service
        mem.get_session = AsyncMock(return_value=None)
        result, error = await s.send_gate("s1", tenant_id=1, user_id="u1")
        assert error == ("SESSION_NOT_FOUND", "会话不存在")
        assert not result  # 会话不存在 → 无会话对象

    async def test_send_gate_cross_tenant(self, service):
        """跨租户 → PERMISSION_DENIED"""
        s, mem = service
        mem.get_session = AsyncMock(return_value={"tenant_id": 2, "customer_id": "u1", "status": "active"})
        _, error = await s.send_gate("s1", tenant_id=1, user_id="u1")
        assert error[0] == "PERMISSION_DENIED"

    async def test_send_gate_cross_user(self, service):
        """跨用户 → PERMISSION_DENIED"""
        s, mem = service
        mem.get_session = AsyncMock(return_value={"tenant_id": 1, "customer_id": "other", "status": "active"})
        _, error = await s.send_gate("s1", tenant_id=1, user_id="u1")
        assert error[0] == "PERMISSION_DENIED"

    async def test_send_gate_closed(self, service):
        """closed 会话 → SESSION_CLOSED"""
        s, mem = service
        mem.get_session = AsyncMock(return_value={"tenant_id": 1, "customer_id": "u1", "status": "closed"})
        _, error = await s.send_gate("s1", tenant_id=1, user_id="u1")
        assert error[0] == "SESSION_CLOSED"

    async def test_send_gate_empty_session_id_creates(self, service):
        """无 session_id 时由调用方负责创建，gate 返回 (None, None) 表示需新建"""
        s, mem = service
        result, error = await s.send_gate("", tenant_id=1, user_id="u1")
        assert (result, error) == (None, None)
        # 空 session_id 直接短路，不触碰 DB
        assert not mem.get_session.called
        assert not mem.touch_activity.called
