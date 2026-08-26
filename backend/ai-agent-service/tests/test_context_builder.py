"""
上下文构建管道 单元测试（会话管理重构 P3）

ContextBuilder 历史压缩职责：
- compress_history：超限时压缩早期消息为摘要（原 ConversationTracker 职责，已迁入）
- 摘要回写 SessionStateStore（state.summary）
"""
# case_ids: CH-005

import pytest
from unittest.mock import AsyncMock, patch

from app.memory.context_builder import ContextBuilder


class TestCompressHistory:
    """历史压缩（原 tracker.compress_history 语义）"""

    @pytest.mark.asyncio
    async def test_no_compression_short_history(self):
        """短历史不压缩"""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
        ]
        result = await ContextBuilder().compress_history(history, "s1", max_turns=10)
        assert result == history

    @pytest.mark.asyncio
    async def test_compression_triggered(self):
        """超长历史触发压缩：首条为 system 摘要，总长缩短"""
        history = []
        for i in range(12):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})

        with patch.object(
            ContextBuilder, "_summarize_history",
            new_callable=AsyncMock,
            return_value="对话摘要内容",
        ):
            result = await ContextBuilder().compress_history(
                history, "s1", max_turns=10, keep_recent=5
            )

        assert result[0]["role"] == "system"
        assert "摘要" in result[0]["content"]
        assert len(result) < len(history)

    @pytest.mark.asyncio
    async def test_empty_history(self):
        """空历史不压缩"""
        result = await ContextBuilder().compress_history([], "s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_summary_written_back_to_state(self):
        """压缩后摘要回写 SessionStateStore（state.summary）"""
        history = []
        for i in range(12):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})

        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value={"pending_skill": "order"})
        mock_store.commit = AsyncMock(return_value=True)

        with patch.object(
            ContextBuilder, "_summarize_history",
            new_callable=AsyncMock,
            return_value="对话摘要内容",
        ), patch("app.memory.context_builder.SessionStateStore", return_value=mock_store):
            await ContextBuilder().compress_history(history, "s1", max_turns=10, keep_recent=5)

        mock_store.commit.assert_called_once()
        state = mock_store.commit.call_args[0][1]
        assert state["summary"] == "对话摘要内容"
        # 合并语义：保留已有 pending_skill
        assert state["pending_skill"] == "order"

    @pytest.mark.asyncio
    async def test_previous_summary_fed_into_summarize(self):
        """滚动摘要：已有 summary 被读回并作为 previous_summary 传入本次摘要"""
        history = []
        for i in range(12):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})

        mock_store = AsyncMock()
        # 第一次 load 返回已有 summary；第二次 load（写回时）同样返回
        mock_store.load = AsyncMock(return_value={"summary": "旧摘要", "pending_skill": "order"})
        mock_store.commit = AsyncMock(return_value=True)

        summarize_mock = AsyncMock(return_value="新摘要")

        with patch.object(
            ContextBuilder, "_summarize_history", summarize_mock,
        ), patch("app.memory.context_builder.SessionStateStore", return_value=mock_store):
            await ContextBuilder().compress_history(history, "s1", max_turns=10, keep_recent=5)

        # 断言 _summarize_history 收到 previous_summary="旧摘要"
        kwargs = summarize_mock.call_args.kwargs
        assert kwargs.get("previous_summary") == "旧摘要"
