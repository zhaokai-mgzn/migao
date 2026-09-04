# case_ids: MC-015, CH-024
"""用户记忆合规 API 测试（issue #2815，个保法查询权/删除权）

覆盖：GET /memories（查询本人记忆）与 DELETE /memories（删除本人记忆）端点。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.chat import get_user_memories, delete_user_memories
from app.utils.auth import UserIdentity


def _user(tenant_id: int = 1, user_id: str = "u1") -> UserIdentity:
    return UserIdentity(
        tenant_id=tenant_id,
        user_id=user_id,
        role="customer",
        identity_type="wechat_mini",
        permissions=[],
    )


class TestGetUserMemories:
    @pytest.mark.asyncio
    async def test_returns_memories(self):
        """GET /memories：返回当前用户 xiaobu 记忆列表"""
        rows = [
            {"id": "m1", "type": "preference", "key": "curtain_style",
             "value": "奶油风", "importance": 0.8,
             "created_at": "2026-09-01", "updated_at": "2026-09-02"},
        ]
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.get_all_memories = AsyncMock(return_value=rows)
            resp = await get_user_memories(_user(), agent_type="xiaobu")

        assert resp["success"] is True
        assert resp["data"]["memories"] == rows
        mock_cls.return_value.get_all_memories.assert_awaited_once_with(
            1, "u1", agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_default_agent_type_xiaobu(self):
        """未传 agent_type 时默认 xiaobu（C 端记忆）"""
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.get_all_memories = AsyncMock(return_value=[])
            await get_user_memories(_user())

        mock_cls.return_value.get_all_memories.assert_awaited_once_with(
            1, "u1", agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        """DB 异常 → 返回空列表而非 500"""
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.get_all_memories = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            resp = await get_user_memories(_user(), agent_type="xiaobu")

        assert resp["success"] is True
        assert resp["data"]["memories"] == []


class TestDeleteUserMemories:
    @pytest.mark.asyncio
    async def test_returns_deleted_count(self):
        """DELETE /memories：删除本人 xiaobu 记忆并返回条数"""
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.delete_all = AsyncMock(return_value=3)
            resp = await delete_user_memories(_user(), agent_type="xiaobu")

        assert resp["success"] is True
        assert resp["data"]["deleted"] == 3
        mock_cls.return_value.delete_all.assert_awaited_once_with(
            1, "u1", agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_default_agent_type_xiaobu(self):
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.delete_all = AsyncMock(return_value=0)
            await delete_user_memories(_user())

        mock_cls.return_value.delete_all.assert_awaited_once_with(
            1, "u1", agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self):
        """DB 异常 → 返回 0 而非 500"""
        with patch("app.api.chat.UserMemoryManager") as mock_cls:
            mock_cls.return_value.delete_all = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            resp = await delete_user_memories(_user(), agent_type="xiaobu")

        assert resp["success"] is True
        assert resp["data"]["deleted"] == 0
