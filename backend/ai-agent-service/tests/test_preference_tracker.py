"""
preference_tracker 集成测试

覆盖本次修复的两个关键场景：
1. 非数字 user_id（如 "user_admin_001"）→ 不崩溃，静默跳过
2. 数字 user_id → 正常写入/查询
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestPreferenceTrackerTypeSafety:
    """user_id 类型安全：非数字字符串不应导致崩溃（DataError）"""

    @pytest.fixture
    def tracker(self):
        from app.suggestions.preference_tracker import PreferenceTracker
        return PreferenceTracker()

    @pytest.mark.asyncio
    async def test_record_click_string_user_id_does_not_crash(self, tracker):
        """user_id="user_admin_001" → 静默跳过，不抛异常"""
        # 模拟 _get_session 返回 mock db
        with patch.object(tracker, '_get_session', new_callable=AsyncMock):
            try:
                await tracker.record_click(
                    tenant_id=1,
                    user_id="user_admin_001",  # 非数字！
                    intent_type="order_query",
                    suggestion_text="查看订单",
                )
            except Exception as e:
                pytest.fail(f"record_click should not crash on string user_id: {e}")

    @pytest.mark.asyncio
    async def test_record_click_numeric_user_id_works(self, tracker):
        """user_id="123" → 正常调用 db.execute"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.close = AsyncMock()

        with patch.object(tracker, '_get_session', return_value=mock_db):
            await tracker.record_click(
                tenant_id=1,
                user_id="123",
                intent_type="order_query",
                suggestion_text="查看订单",
            )
            # 验证 DB 被调用
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_top_intents_string_user_id_returns_empty(self, tracker):
        """user_id="user_admin_001" → 返回空列表，不抛异常"""
        try:
            result = await tracker.get_top_intents(
                tenant_id=1,
                user_id="user_admin_001",  # 非数字！
                limit=5,
            )
            assert result == []
        except Exception as e:
            pytest.fail(f"get_top_intents should return empty on string user_id: {e}")

    @pytest.mark.asyncio
    async def test_get_top_intents_numeric_user_id_works(self, tracker):
        """user_id="123" → 正常查询"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("order_query", 5), ("product_inquiry", 3)]
        mock_db.execute.return_value = mock_result
        mock_db.close = AsyncMock()

        with patch.object(tracker, '_get_session', return_value=mock_db):
            result = await tracker.get_top_intents(
                tenant_id=1,
                user_id="123",
                limit=5,
            )
            assert len(result) == 2
            assert result[0]["intent_type"] == "order_query"
            assert result[0]["click_count"] == 5

    @pytest.mark.asyncio
    async def test_get_user_stats_string_user_id_returns_default(self, tracker):
        """user_id="user_admin_001" → 返回默认值"""
        try:
            result = await tracker.get_user_stats(
                tenant_id=1,
                user_id="user_admin_001",
            )
            assert result == {"total_clicks": 0, "top_intents": [], "distinct_intents": 0}
        except Exception as e:
            pytest.fail(f"get_user_stats should return default on string user_id: {e}")

    @pytest.mark.asyncio
    async def test_record_click_empty_user_id_skips(self, tracker):
        """user_id="" → 直接返回"""
        with patch.object(tracker, '_get_session', new_callable=AsyncMock) as mock_session:
            await tracker.record_click(tenant_id=1, user_id="", intent_type="test")
            mock_session.assert_not_called()  # 不应该创建 DB session

    @pytest.mark.asyncio
    async def test_record_click_non_numeric_skips_db_call(self, tracker):
        """user_id="abc123" (含字母) → 不调 DB"""
        mock_db = AsyncMock()
        with patch.object(tracker, '_get_session', return_value=mock_db):
            result = await tracker.record_click(
                tenant_id=1,
                user_id="abc123",  # 无法转为 int
                intent_type="test",
            )
            # 应该提前 return，不调用 db.execute
            mock_db.execute.assert_not_called()
