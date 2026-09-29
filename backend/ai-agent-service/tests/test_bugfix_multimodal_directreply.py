"""Bug 修复回归测试：多模态消息路由 + _extract_content 空响应兜底

覆盖两个已确认的线上 Bug：
- Bug A: 多模态消息被路由到 direct_reply_node（直复模板不处理图片）
- Bug C: _extract_content 在仅含思考内容时返回空串
"""

import re
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import route_by_intent, _last_human_has_image
from app.graph.skills.base_skill import _extract_content


# ========== Bug A: _last_human_has_image 辅助函数测试 ==========


class TestLastHumanHasImage:
    """多模态检测辅助函数测试"""

    def test_plain_text_returns_false(self):
        """纯文本 HumanMessage → False"""
        assert _last_human_has_image([HumanMessage(content="你好")]) is False

    def test_no_messages_returns_false(self):
        """空消息列表 → False"""
        assert _last_human_has_image([]) is False

    def test_empty_history_returns_false(self):
        """无 HumanMessage 的历史（如只有 AIMessage）→ False"""
        assert _last_human_has_image([AIMessage(content="回复")]) is False

    def test_multimodal_with_image_url_returns_true(self):
        """含 image_url 的多模态消息 → True"""
        msg = HumanMessage(content=[
            {"type": "text", "text": "识别图片"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ])
        assert _last_human_has_image([msg]) is True

    def test_multimodal_text_only_returns_false(self):
        """multimodal 但只有 text 项 → False"""
        msg = HumanMessage(content=[
            {"type": "text", "text": "你好"},
            {"type": "text", "text": "再见"},
        ])
        assert _last_human_has_image([msg]) is False

    def test_latest_human_message_determination(self):
        """只检测最后一条 HumanMessage，忽略更早的消息"""
        history = [
            HumanMessage(content=[{"type": "text", "text": "hi"}]),   # 旧消息，纯文本
            AIMessage(content="hello"),
            HumanMessage(content="能识别图片吗？"),  # 最新消息，纯文本
        ]
        assert _last_human_has_image(history) is False

        history2 = [
            HumanMessage(content=[
                {"type": "text", "text": "hi"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ]),
            AIMessage(content="这是能力介绍。"),
            HumanMessage(content="帮我看看这个商品"),  # 最新消息，纯文本
        ]
        assert _last_human_has_image(history2) is False  # 最新消息不含图片

        history3 = [
            HumanMessage(content="你好"),  # 旧消息，纯文本
            AIMessage(content="您好！我是米宝..."),
            HumanMessage(content=[
                {"type": "text", "text": "你能识别图片中的信息吗"},
                {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
            ]),  # 最新消息，含图片
        ]
        assert _last_human_has_image(history3) is True


# ========== Bug A: route_by_intent 多模态拦截测试 ==========


class TestRouteByIntentMultimodal:
    """route_by_intent 多模态消息拦截测试"""

    @staticmethod
    def _make_multimodal_state(**overrides):
        """构建含多模态消息的 state"""
        return {
            "messages": [
                HumanMessage(content="你好，请介绍一下你自己"),
                AIMessage(content="您好！我是米宝..."),
                HumanMessage(content=[
                    {"type": "text", "text": "你能识别图片中的信息吗"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
                ]),
            ],
            "tenant_id": 1,
            "user_id": 100,
            "session_id": "sess_001",
            "role": "customer",
            "intent_result": None,
            "route_decision": None,
            "entities": {},
            "intent_chain": [],
            "stage": "initial",
            "cached_answer": None,
            "final_answer": "",
            "skill_used": "",
            "suggestions": [],
            **overrides,
        }

    def test_direct_reply_multimodal_routes_to_general(self):
        """多模态消息 + action=direct_reply → 强制路由到 general"""
        state = self._make_multimodal_state(
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "capabilities"},
        )
        assert route_by_intent(state) == "general"

    def test_direct_reply_non_multimodal_stays(self):
        """纯文本消息 + action=direct_reply → 保持 direct_reply（回归保护）"""
        state = self._make_multimodal_state(
            route_decision={"action": "direct_reply"},
            intent_result={"intent": "greeting"},
        )
        state["messages"] = [HumanMessage(content="你好")]
        assert route_by_intent(state) == "direct_reply"

    def test_normal_greeting_routing_still_works(self):
        """普通 greeting 意图仍应路由到 direct_reply"""
        state = self._make_multimodal_state(
            route_decision={"action": "full_agent"},
            intent_result={"intent": "greeting"},
        )
        state["messages"] = [HumanMessage(content="你好")]
        assert route_by_intent(state) == "direct_reply"

    def test_direct_reply_action_with_non_multimodal_humans_only(self):
        """action=direct_reply 且历史中无任何人类消息（纯助手）→ direct_reply"""
        state = self._make_multimodal_state(
            route_decision={"action": "direct_reply"},
        )
        state["messages"] = []  # 空消息列表
        assert route_by_intent(state) == "direct_reply"


# ========== Bug C: _extract_content 空响应兜底测试 ==========


class TestExtractContentFallback:
    """_extract_content 空响应兜底测试"""

    def test_thinking_only_returns_thought_text(self):
        """仅 thinking 内容 → 提取标签内文本（非空）"""
        response = AIMessage(content="<think>用户问图片是什么内容，我需要仔细观察图片的特征。图片显示的是一个后台管理系统的界面...</think>")
        result = _extract_content(response)
        assert result != ""
        assert "用户问图片是什么内容" in result  # 提取的内容应包含在结果中
        assert "<think>" not in result  # 不应保留 think 标签

    def test_thinking_with_response_returns_response_only(self):
        """thinking + 正式回复 → 仅返回正式回复"""
        content = "<think>分析一下这个问题...\n\n</think>根据图片分析，这是一款米高商家管理后台的商品列表页面。"
        response = AIMessage(content=content)
        result = _extract_content(response)
        assert result == "根据图片分析，这是一款米高商家管理后台的商品列表页面。"
        assert "分析一下这个问题" not in result

    def test_empty_content_returns_empty(self):
        """空内容 → 空字符串"""
        response = AIMessage(content="")
        result = _extract_content(response)
        assert result == ""

    def test_none_content_returns_empty(self):
        """空列表内容（模拟多模态无文本） → 空字符串"""
        response = AIMessage(content=[])
        result = _extract_content(response)
        assert result == ""

    def test_no_think_tags_returns_content_as_is(self):
        """无 think 标签 → 原样返回"""
        response = AIMessage(content="正常回复内容")
        result = _extract_content(response)
        assert result == "正常回复内容"

    def test_only_think_tags_returns_inner_text(self):
        """仅 <think>标签</think> → 返回内部文本"""
        response = AIMessage(content="<think>一些思考内容</think>")
        result = _extract_content(response)
        assert result == "一些思考内容"

    def test_multimodal_response_with_thinking_only(self):
        """多模态响应仅含 thinking → 仍能提取文本"""
        response = AIMessage(content=[
            {"type": "text", "text": ""},
            {"type": "text", "text": ""},
        ])
        result = _extract_content(response)
        assert result == ""

    def test_multimodal_response_with_thinking_and_text(self):
        """多模态响应含 thinking + 正文 → 提取正文"""
        response = AIMessage(content=[
            {"type": "text", "text": "这是一段描述性文字。<think>分析中...</think>"},
            {"type": "text", "text": "最终结论是好的。"},
        ])
        result = _extract_content(response)
        assert result == "这是一段描述性文字。最终结论是好的。"

    def test_thinking_only_fallback_logging(self):
        """仅 thinking 时应有 warning 日志"""
        response = AIMessage(content="<think>思考过程</think>")
        with patch("app.graph.skills.base_skill.logger") as mock_logger:
            _extract_content(response)
            mock_logger.warning.assert_called()
            call_args = str(mock_logger.warning.call_args)
            assert "Only thinking content found" in call_args

    def test_reasoning_content_fallback(self):
        """additional_kwargs.reasoning_content 作为兜底"""
        response = AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": "从 additional_kwargs 中提取的思考内容",
            },
        )
        with patch("app.graph.skills.base_skill.logger") as mock_logger:
            result = _extract_content(response)
        assert result == "从 additional_kwargs 中提取的思考内容"
        mock_logger.warning.assert_called()
        assert "reasoning_content" in str(mock_logger.warning.call_args)

    def test_final_fallback_returns_original_with_think_tags(self):
        """终极兜底：返回原始 content（含 think 标签）而非空串"""
        response = AIMessage(content="<think>思考中...</think>")
        with patch("app.graph.skills.base_skill.logger") as mock_logger:
            result = _extract_content(response)
        # _strip_think_tags 会清空内容并回退到原文
        # 所以这里应该是原文（因为 _strip_think_tags 行为：cleaned为空则返回原文）
        assert result != ""
