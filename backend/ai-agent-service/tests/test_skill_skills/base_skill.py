"""base_skill 单元测试（app/graph/skills/base_skill.py）

覆盖：
- _requires_confirmation：destructive 工具确认守卫 + 只读 action 豁免（回归 DF-008）
- _is_explicit_confirmation：确认词判定
- _strip_think_tags / _extract_content：思考标签剥离与内容提取
- _extract_usage：token 用量提取（usage_metadata / response_metadata 兼容）
- _track_llm_cost：成本追踪调用（无 usage 时跳过）
- build_tool_context / _extract_intent_name / _sanitize_messages_for_text_path
- _execute_tool_safe：只读缓存 / 超时 / 异常错误处理
"""
# case_ids: DF-008, DF-015, CH-001
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.skills.base_skill import (
    _execute_tool_safe,
    _extract_content,
    _extract_intent_name,
    _extract_usage,
    _is_explicit_confirmation,
    _requires_confirmation,
    _sanitize_messages_for_text_path,
    _strip_think_tags,
    _track_llm_cost,
    build_tool_context,
)


class TestRequiresConfirmationReadActions:
    """destructive 工具的只读 action 免确认（核心修复行为）"""

    @staticmethod
    def _make_tool(destructive=True, read_only_actions=()):
        return type("FakeTool", (), {
            "destructive": destructive,
            "read_only_actions": frozenset(read_only_actions),
        })()

    def test_read_action_exempt_for_destructive_tool(self):
        t = self._make_tool(read_only_actions={"list", "detail", "tree"})
        assert _requires_confirmation(t, {"action": "list"}, "查客户列表") is False
        assert _requires_confirmation(t, {"action": "detail"}, "查客户详情") is False
        assert _requires_confirmation(t, {"action": "tree"}, "看看分类") is False

    def test_write_action_still_requires_without_confirm(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"action": "update"}, "帮我改一下") is True
        assert _requires_confirmation(t, {"action": "delete"}, "帮我删除") is True

    def test_write_action_passes_with_confirm(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"action": "delete"}, "确认删除") is False

    def test_non_destructive_tool_never_requires(self):
        t = self._make_tool(destructive=False)
        assert _requires_confirmation(t, {"action": "delete"}, "删除") is False

    def test_operation_param_alias_supported(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {"operation": "list"}, "查一下") is False

    def test_missing_action_defaults_to_confirm_required(self):
        t = self._make_tool(read_only_actions={"list"})
        assert _requires_confirmation(t, {}, "查一下") is True


class TestIsExplicitConfirmation:
    def test_exact_confirm_words(self):
        for w in ("确认", "确定", "好的", "可以", "同意", "ok", "yes", "confirm"):
            assert _is_explicit_confirmation(w) is True

    def test_confirm_substring_short(self):
        assert _is_explicit_confirmation("确认删除订单123") is True

    def test_non_confirm_rejected(self):
        assert _is_explicit_confirmation("帮我删除") is False

    def test_empty_rejected(self):
        assert _is_explicit_confirmation("") is False


class TestStripThinkTags:
    def test_removes_think_block(self):
        assert _strip_think_tags("<think>思考</think>你好") == "你好"

    def test_multiline_think_block(self):
        assert _strip_think_tags("<think>\n多行思考\n</think>回答") == "回答"

    def test_no_think_passthrough(self):
        assert _strip_think_tags("普通文本") == "普通文本"

    def test_empty_returns_empty(self):
        assert _strip_think_tags("") == ""

    def test_non_string_coerced(self):
        assert _strip_think_tags(123) == "123"


class TestExtractContent:
    def test_plain_content(self):
        resp = AIMessage(content="你好")
        assert _extract_content(resp) == "你好"

    def test_strips_think_tags(self):
        resp = AIMessage(content="<think>计划</think>最终回答")
        assert _extract_content(resp) == "最终回答"

    def test_multimodal_content_list(self):
        resp = AIMessage(content=[
            {"type": "text", "text": "图片说明"},
            {"type": "image_url", "image_url": {"url": "x"}},
        ])
        assert _extract_content(resp) == "图片说明"

    def test_thinking_only_falls_back_to_inner(self):
        resp = AIMessage(content="<think>只有思考内容</think>")
        assert _extract_content(resp) == "只有思考内容"

    def test_empty_falls_back_to_reasoning(self):
        resp = AIMessage(content="", additional_kwargs={"reasoning_content": "推理内容"})
        assert _extract_content(resp) == "推理内容"


class TestExtractUsage:
    def test_usage_metadata(self):
        resp = type("R", (), {
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5},
            "response_metadata": {},
        })()
        assert _extract_usage(resp) == (10, 5)

    def test_response_metadata_token_usage(self):
        resp = type("R", (), {
            "usage_metadata": None,
            "response_metadata": {"token_usage": {"prompt_tokens": 3, "completion_tokens": 4}},
        })()
        assert _extract_usage(resp) == (3, 4)

    def test_no_usage_returns_none(self):
        resp = type("R", (), {"usage_metadata": None, "response_metadata": {}})()
        assert (_extract_usage(resp) is None)


class TestTrackLlmCost:
    def test_tracks_when_usage_present(self):
        resp = type("R", (), {"usage_metadata": {"input_tokens": 10, "output_tokens": 5}})()
        with patch("app.graph.skills.base_skill.cost_tracker.track_call") as mock_track:
            _track_llm_cost(resp, "model-x", 1, "sess-1")
        mock_track.assert_called_once()
        args = mock_track.call_args
        assert args.kwargs["input_tokens"] == 10
        assert args.kwargs["output_tokens"] == 5

    def test_skips_when_no_usage(self):
        resp = type("R", (), {"usage_metadata": None, "response_metadata": {}})()
        with patch("app.graph.skills.base_skill.cost_tracker.track_call") as mock_track:
            _track_llm_cost(resp, "model-x", 1, "sess-1")
        mock_track.assert_not_called()


class TestBuildToolContext:
    def test_builds_from_state(self):
        state = {
            "tenant_id": 7,
            "user_id": "u1",
            "session_id": "s1",
            "role": "customer",
        }
        ctx = build_tool_context(state)
        assert ctx.tenant_id == 7
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"
        assert ctx.role == "customer"


class TestExtractIntentName:
    def test_enum_value(self):
        intent = type("I", (), {"value": "order_query"})()
        state = {"intent_result": {"intent": intent}}
        assert _extract_intent_name(state) == "order_query"

    def test_string_intent(self):
        state = {"intent_result": {"intent": "greeting"}}
        assert _extract_intent_name(state) == "greeting"

    def test_missing_intent(self):
        assert _extract_intent_name({}) == ""


class TestSanitizeMessagesForTextPath:
    def test_mixed_content_keeps_text(self):
        msg = HumanMessage(content=[
            {"type": "text", "text": "帮我查"},
            {"type": "image_url", "image_url": {"url": "x"}},
        ])
        out = _sanitize_messages_for_text_path([msg])
        assert out[0].content == "帮我查"

    def test_image_only_becomes_placeholder(self):
        msg = HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])
        out = _sanitize_messages_for_text_path([msg])
        assert out[0].content == "[图片]"

    def test_plain_text_unchanged(self):
        msg = HumanMessage(content="纯文本")
        out = _sanitize_messages_for_text_path([msg])
        assert out[0].content == "纯文本"

    def test_non_human_unchanged(self):
        msg = AIMessage(content="assistant")
        out = _sanitize_messages_for_text_path([msg])
        assert out[0] is msg


class TestExecuteToolSafe:
    @staticmethod
    def _result_obj(success=True, data=None, error=None, message="", suggestion=""):
        return type("R", (), {
            "success": success, "data": data, "error": error,
            "message": message, "suggestion": suggestion,
        })()

    @pytest.mark.asyncio
    async def test_success_read_only(self):
        tool = type("T", (), {
            "name": "product_search", "read_only": True,
            "execute": AsyncMock(return_value=self._result_obj(success=True, data={"a": 1})),
        })()
        state = {"session_id": "s1", "tenant_id": 1}
        with patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
                   side_effect=lambda t, a: a), \
             patch("app.graph.skills.base_skill._auto_resolve_ids",
                   new=AsyncMock(side_effect=lambda t, a, s: a)):
            result_str, result_dict = await _execute_tool_safe(tool, {"q": "窗帘"}, None, state)
        assert result_dict["success"] is True
        assert result_dict["data"] == {"a": 1}

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        async def slow(*a, **k):
            raise __import__("asyncio").TimeoutError()
        tool = type("T", (), {"name": "t1", "read_only": False, "execute": slow})()
        state = {"session_id": "s1", "tenant_id": 1}
        with patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
                   side_effect=lambda t, a: a), \
             patch("app.graph.skills.base_skill._auto_resolve_ids",
                   new=AsyncMock(side_effect=lambda t, a, s: a)):
            result_str, result_dict = await _execute_tool_safe(tool, {}, None, state)
        assert result_dict["success"] is False
        assert result_dict["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        async def boom(*a, **k):
            raise RuntimeError("boom")
        tool = type("T", (), {"name": "t1", "read_only": False, "execute": boom})()
        state = {"session_id": "s1", "tenant_id": 1}
        with patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
                   side_effect=lambda t, a: a), \
             patch("app.graph.skills.base_skill._auto_resolve_ids",
                   new=AsyncMock(side_effect=lambda t, a, s: a)), \
             patch("app.graph.skills.base_skill.logger"):
            result_str, result_dict = await _execute_tool_safe(tool, {}, None, state)
        assert result_dict["success"] is False
        assert result_dict["error"] == "tool_execution_failed"
