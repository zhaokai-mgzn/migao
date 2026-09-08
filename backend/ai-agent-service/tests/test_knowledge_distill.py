"""
知识提炼单元测试（LLM WIKI 板块 P5b，issue #3051）
覆盖：JSON 数组容错抽取、候选清洗、异常降级（不阻断调用方）。
"""
# case_ids: API-020

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.distill import (
    _extract_json_array,
    _sanitize_candidates,
    _truncate_conversation,
    distill,
)

GOOD_JSON = """[{"title": "窗帘多久洗一次", "answer": "建议每 3-6 个月清洗一次。", "category": "faq", "keywords": "清洗,周期", "confidence": 0.92, "evidence": "顾客问：多久洗一次"}]"""


class TestExtractJsonArray:
    def test_direct_array(self):
        assert _extract_json_array(GOOD_JSON)[0]["title"] == "窗帘多久洗一次"

    def test_fenced_block(self):
        assert _extract_json_array(f"```json\n{GOOD_JSON}\n```")[0]["title"] == "窗帘多久洗一次"

    def test_text_with_array(self):
        text = f"以下是提炼结果：\n{GOOD_JSON}\n请查收。"
        assert _extract_json_array(text)[0]["title"] == "窗帘多久洗一次"

    def test_invalid_returns_none(self):
        assert _extract_json_array("抱歉，我无法提炼") is None
        assert _extract_json_array("") is None


class TestSanitizeCandidates:
    def test_drop_empty_title_answer(self):
        raw = [
            {"title": "有效", "answer": "有效回答", "confidence": "0.9"},
            {"title": "", "answer": "没标题"},
            {"title": "没回答", "answer": "  "},
            "not a dict",
        ]
        result = _sanitize_candidates(raw)
        assert len(result) == 1
        assert result[0]["title"] == "有效"
        assert result[0]["confidence"] == 0.9

    def test_confidence_clamped(self):
        result = _sanitize_candidates([{"title": "t", "answer": "a", "confidence": "1.5"}])
        assert result[0]["confidence"] == 1.0


class TestTruncateConversation:
    def test_short_kept(self):
        assert _truncate_conversation("短文本") == "短文本"

    def test_long_truncated(self):
        long_text = "内容" * 5000
        assert len(_truncate_conversation(long_text)) < 4000


class TestDistill:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=GOOD_JSON))
        with patch("app.knowledge.distill.LLMFactory.create_suggestion_llm", return_value=mock_llm):
            result = await distill("顾客：多久洗一次？\n客服：建议每3-6个月。")
        assert len(result) == 1
        assert result[0]["title"] == "窗帘多久洗一次"
        assert result[0]["confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_unparseable_falls_back_empty(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="无法解析"))
        with patch("app.knowledge.distill.LLMFactory.create_suggestion_llm", return_value=mock_llm):
            result = await distill("顾客：你好\n客服：您好！")
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_empty(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))
        with patch("app.knowledge.distill.LLMFactory.create_suggestion_llm", return_value=mock_llm):
            result = await distill("顾客：多少钱\n客服：88元/米")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self):
        assert await distill("") == []


@pytest.mark.asyncio
async def test_internal_endpoint_distill(monkeypatch):
    """internal /knowledge/distill 端点函数：返回候选列表（直调，绕过 Depends 认证）"""
    from app.api.internal import distill_knowledge
    from app.api.internal import KnowledgeDistillRequest

    async def fake_distill(text, max_candidates=5):
        return [{"title": "t", "answer": "a", "category": "faq", "keywords": "", "confidence": 0.9, "evidence": "e"}]

    monkeypatch.setattr("app.api.internal.distill", fake_distill)
    req = KnowledgeDistillRequest(tenant_id=1, conversation_text="顾客：x\n客服：y")
    result = await distill_knowledge(req, authorized=True)
    assert result["success"] is True
    assert result["data"]["candidates"][0]["title"] == "t"
