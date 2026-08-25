# case_ids: MC-001, MC-002
"""记忆提取器单元测试（app/memory/extractor.py）

覆盖：_parse_extraction_result / extract_memories_from_turn / extract_and_save。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.extractor import (
    _parse_extraction_result,
    extract_memories_from_turn,
    extract_and_save,
)


class TestParseExtractionResult:
    """_parse_extraction_result：纯 JSON / 内嵌数组 / 非法输入"""

    def test_pure_json_array(self):
        result = _parse_extraction_result(
            '[{"type": "preference", "key": "style", "value": "简约", "importance": 0.8}]'
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "preference"
        assert result[0]["key"] == "style"

    def test_json_array_embedded_in_text(self):
        result = _parse_extraction_result(
            '好的，提取结果如下：[{"type": "fact", "key": "order", "value": "ORD123"}] 以上'
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "fact"

    def test_non_json_returns_empty(self):
        assert _parse_extraction_result("这里没有 JSON") == []

    def test_dict_not_list_returns_empty(self):
        assert _parse_extraction_result('{"type": "preference"}') == []

    def test_blank_returns_empty(self):
        assert _parse_extraction_result("   ") == []


class TestExtractMemoriesFromTurn:
    """extract_memories_from_turn：短对话跳过 / LLM 流程 / 异常兜底"""

    @pytest.mark.asyncio
    async def test_short_turn_skips_without_llm(self):
        with patch("app.memory.extractor.LLMFactory") as mock_factory:
            result = await extract_memories_from_turn(
                user_message="你好",
                assistant_reply="您好",
                session_id="s1",
            )
        assert result == []
        mock_factory.create_suggestion_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_result_gets_context_appended(self):
        mock_response = MagicMock()
        mock_response.content = '[{"type": "fact", "key": "phone", "value": "138"}]'
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.memory.extractor.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="我的手机号是13800138000",
                assistant_reply="好的，已记录您的手机号。",
                session_id="sess-1",
            )

        assert len(result) == 1
        assert result[0]["context"] == "session=sess-1 | user: 我的手机号是13800138000"

    @pytest.mark.asyncio
    async def test_existing_context_not_overwritten(self):
        mock_response = MagicMock()
        mock_response.content = (
            '[{"type": "fact", "key": "phone", "value": "138", "context": "已有"}]'
        )
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.memory.extractor.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="我的手机号是13800138000",
                assistant_reply="好的，已记录您的手机号。",
                session_id="sess-2",
            )

        assert result[0]["context"] == "已有"

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))

        with patch(
            "app.memory.extractor.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="帮我查一下订单状态好吗",
                assistant_reply="您的订单已经发货，请注意查收物流信息。",
                session_id="sess-3",
            )

        assert result == []


class TestExtractAndSave:
    """extract_and_save：无记忆 / 保存成功 / 保存异常"""

    @pytest.mark.asyncio
    async def test_no_memories_returns_zero(self):
        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=[],
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="你好", assistant_reply="您好",
                session_id="s1",
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_batch_upsert_returns_count(self):
        items = [{"type": "fact", "key": "phone", "value": "138"}]
        mock_manager = MagicMock()
        mock_manager.batch_upsert = AsyncMock(return_value=1)

        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=items,
        ), patch(
            "app.memory.user_memory.UserMemoryManager",
            return_value=mock_manager,
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="我的手机号是13800138000", assistant_reply="好的，已记录。",
                session_id="s1",
            )
        assert count == 1
        mock_manager.batch_upsert.assert_awaited_once_with(1, "u1", items)

    @pytest.mark.asyncio
    async def test_batch_upsert_exception_returns_zero(self):
        items = [{"type": "fact", "key": "phone", "value": "138"}]
        mock_manager = MagicMock()
        mock_manager.batch_upsert = AsyncMock(side_effect=RuntimeError("db down"))

        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=items,
        ), patch(
            "app.memory.user_memory.UserMemoryManager",
            return_value=mock_manager,
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="我的手机号是13800138000", assistant_reply="好的，已记录。",
                session_id="s1",
            )
        assert count == 0
