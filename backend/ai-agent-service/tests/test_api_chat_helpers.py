"""
Tests for app/api/*.py — coverage gap issue #581
Covers: chat (helpers), sse (SSEEvent/SSEStreamBuilder),
         upload (_sniff_image_type/_validate_image_file), internal (Pydantic models)
"""
# case_ids: CH-001, API-004, CH-011, CH-012, OR-017
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ═══════════════════════════════════════
# chat.py — helper functions
# ═══════════════════════════════════════

class TestFormatDatetime:
    def test_datetime_naive(self):
        from app.api.chat import _format_datetime
        dt = datetime(2026, 6, 20, 10, 30, 0)
        result = _format_datetime(dt)
        assert result.endswith("Z")
        assert "2026-06-20" in result

    def test_datetime_with_tz(self):
        from app.api.chat import _format_datetime
        dt = datetime(2026, 6, 20, 10, 30, 0, tzinfo=timezone.utc)
        result = _format_datetime(dt)
        assert result.endswith("Z")

    def test_string_double_suffix(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00+00:00Z")
        assert not result.endswith("+00:00Z")
        assert result.endswith("Z")

    def test_string_plus_00_00(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00+00:00")
        assert result.endswith("Z")

    def test_string_no_suffix(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00")
        assert "2026-06-20" in result


class TestConvertHistoryToAgentFormat:
    def test_user_message_passthrough(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_assistant_think_stripped(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "assistant", "content": "<think>reasoning</think>actual reply"}
        ])
        assert result[0]["content"] == "actual reply"
        assert "think" not in result[0]["content"]

    def test_assistant_no_think_passthrough(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "assistant", "content": "plain reply"}
        ])
        assert result[0]["content"] == "plain reply"

    def test_mixed_messages(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "<think>x</think>a1"},
            {"role": "user", "content": "q2"},
        ])
        assert len(result) == 3
        assert result[1]["content"] == "a1"


class TestValidateImageUrl:
    def test_valid_https(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("https://example.com/img.jpg") is True

    def test_valid_api_files(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("/api/files/upload/abc.jpg") is True

    def test_invalid_http(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("http://example.com/img.jpg") is False

    def test_invalid_empty(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("") is False

    def test_invalid_none(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url(None) is False


class TestDetectCardType:
    def test_product_search(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("product_search", {}) == "product_list"

    def test_product_detail(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("product_detail", {}) == "product_detail"

    def test_unknown_tool(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("some_unknown_tool", {}) is None


# ═══════════════════════════════════════
# sse.py — SSEEvent / SSEStreamBuilder
# ═══════════════════════════════════════

class TestSSEEvent:
    def test_text_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.text("hello")
        assert "event: text" in event
        assert "hello" in event

    def test_tool_call_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.tool_call("search", {"q": "test"})
        assert "event: tool_call" in event
        assert "search" in event

    def test_tool_result_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.tool_result("search", {"data": [1, 2]})
        assert "event: tool_result" in event

    def test_error_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.error("something wrong")
        assert "event: error" in event
        assert "something wrong" in event

    def test_suggestions_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.suggestions(["a", "b", "c"])
        assert "event: suggestions" in event


class TestSSEStreamBuilder:
    def test_build_empty(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        assert builder.build() == ""

    def test_build_with_text(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        builder.add_text("hello")
        result = builder.build()
        assert "event: text" in result
        assert "hello" in result

    def test_fluent_chaining(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        result = builder.add_text("hi").add_text("there").build()
        assert "hi" in result
        assert "there" in result

    def test_add_tool_call(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        builder.add_tool_call("search", {"q": "x"})
        result = builder.build()
        assert "event: tool_call" in result


# ═══════════════════════════════════════
# upload.py — image helpers
# ═══════════════════════════════════════

class TestSniffImageType:
    def test_jpeg(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'\xff\xd8\xff\xe0\x00\x10JFIF')
        assert result == 'image/jpeg'

    def test_png(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
        assert result == 'image/png'

    def test_gif(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'GIF89a\x00\x00\x00\x00')
        assert result == 'image/gif'

    def test_webp(self):
        from app.api.upload import _sniff_image_type
        header = b'RIFF\x00\x00\x00\x00WEBP'
        result = _sniff_image_type(header)
        assert result == 'image/webp'

    def test_unknown(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'random bytes here')
        assert result is None

    def test_empty(self):
        from app.api.upload import _sniff_image_type
        assert _sniff_image_type(b'') is None


class TestValidateImageFile:
    def test_valid_jpeg(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "image/jpeg"
        _validate_image_file(mock_file)  # should not raise

    def test_valid_png(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "image/png"
        _validate_image_file(mock_file)

    def test_invalid_type(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "application/pdf"
        with pytest.raises(Exception):
            _validate_image_file(mock_file)


# ═══════════════════════════════════════
# internal.py — Pydantic models
# ═══════════════════════════════════════

class TestInternalModels:
    def test_tool_execute_request(self):
        from app.api.internal import ToolExecuteRequest
        req = ToolExecuteRequest(
            tool_name="product_search",
            arguments={"keyword": "窗帘"},
            tenant_id=1,
            user_id="u1",
        )
        assert req.tool_name == "product_search"
        assert req.tenant_id == 1



# ═══════════════════════════════════════
# 对抗性审查修复 #937 — chat.py / schemas.py
# ═══════════════════════════════════════

class TestChatSSEDoneFix:
    def test_sse_done_event_structure(self):
        """SSE done 事件包含 session_id 和 message_id"""
        from app.api.sse import SSEEvent
        event = SSEEvent.done("sess_001", "msg_001")
        assert "event: done" in event
        assert "sess_001" in event
        assert "msg_001" in event

    def test_sse_interactive_event(self):
        """SSE interactive 事件发送 choice/confirm/form 组件"""
        from app.api.sse import SSEEvent
        event = SSEEvent.interactive("choice", {"title": "test"})
        assert "event: interactive" in event
        assert "choice" in event


class TestSchemasMaxLength:
    def test_message_max_length(self):
        """ChatSendRequest.message 有 max_length=10000 约束"""
        from app.api.schemas import ChatSendRequest
        from pydantic import ValidationError
        import pytest
        # 验证 schema 定义包含 max_length
        field = ChatSendRequest.model_fields["message"]
        assert field.metadata is not None
        # 超长消息应被拒绝
        with pytest.raises(ValidationError):
            ChatSendRequest(message="x" * 10001)


# ═══════════════════════════════════════
# #947 — chat.py: _infer_intent_from_text 关键词推断
# ═══════════════════════════════════════

class TestInferIntentFromText:
    """建议文本 → 意图类型推断（关键词匹配）"""

    def test_order_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("查看订单") == "order_query"
        assert _infer_intent_from_text("查询发货状态") == "order_query"

    def test_logistics_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("物流到哪了") == "logistics_track"
        assert _infer_intent_from_text("快递单号查一下") == "logistics_track"
        assert _infer_intent_from_text("签收了吗") == "logistics_track"

    def test_after_sales_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("申请售后") == "after_sales"
        assert _infer_intent_from_text("我要退款") == "after_sales"
        assert _infer_intent_from_text("工单处理") == "after_sales"

    def test_complaint_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("我要投诉") == "complaint"

    def test_product_inquiry_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("有什么商品") == "product_inquiry"
        assert _infer_intent_from_text("查一下产品") == "product_inquiry"
        assert _infer_intent_from_text("库存有多少") == "product_inquiry"

    def test_category_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("分类管理") == "category_manage"

    def test_processing_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("加工管理") == "processing_manage"

    def test_customer_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("客户管理") == "customer_manage"

    def test_employee_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("员工管理") == "employee_manage"

    def test_role_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("角色管理") == "role_manage"

    def test_permission_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("权限管理") == "permission_manage"

    def test_dashboard_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("经营看板") == "dashboard"
        assert _infer_intent_from_text("看板数据") == "dashboard"

    def test_statistics_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("数据统计") == "statistics"
        assert _infer_intent_from_text("统计报表") == "statistics"

    def test_data_report_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("数据报表") == "data_report"

    def test_notification_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("通知管理") == "notification"
        assert _infer_intent_from_text("消息中心") == "notification"

    def test_knowledge_faq_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("知识问答") == "knowledge_faq"
        assert _infer_intent_from_text("FAQ查询") == "knowledge_faq"

    def test_session_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("会话管理") == "session_manage"

    def test_system_settings_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("系统设置") == "system_settings"

    def test_ai_config_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("AI配置") == "ai_config"
        assert _infer_intent_from_text("模型设置") == "ai_config"

    def test_empty_text_returns_empty(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("") == ""
        assert _infer_intent_from_text(None) == ""

    def test_no_keyword_falls_to_general(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("你好呀") == "general"
        assert _infer_intent_from_text("abc123") == "general"

    def test_first_keyword_wins(self):
        """多个关键词时返回第一个匹配的意图"""
        from app.api.chat import _infer_intent_from_text
        # "订单" 在 "数据" 之前 → order_query
        assert _infer_intent_from_text("查看订单数据") == "order_query"


class TestCustomerStreamMasking:
    """SSE 出站文本脱敏（issue #3379 P2-2 真正的收敛点）。

    为什么必须放在**流式桥**上：C 端回复有**两个生产者** ——
    `final_answer`（技能收尾，已在 base_skill 脱敏）与 **`text_before_tools`**
    （模型调工具前的中间文本，由 `chat.py` 的 `_agent_stream_to_sse` 直接流给顾客）。
    实测 OR-017 R2（run 34735574206，复现型失败）泄露的正是**中间文本**那条路径：
    ```
    ❌ 回复出现完整手机号 13800138000（R2）—— C 端应脱敏为 138****8000
    ```
    在收尾处脱敏永远追不上已经流出去的文本，故收敛到**出站桥**（覆盖全部文本路径）。
    """

    def _ctx(self, role):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    def test_customer_text_masked(self):
        from app.api.chat import _mask_for_customer
        out = _mask_for_customer("已用您上次的收货信息：张三 13800138000 杭州市西湖区文三路1号",
                                 self._ctx("customer"))
        assert "13800138000" not in out and "138****8000" in out

    def test_staff_text_untouched(self):
        from app.api.chat import _mask_for_customer
        text = "客户手机号 13800138000"
        assert _mask_for_customer(text, self._ctx("admin")) == text

    def test_order_number_not_masked(self):
        from app.api.chat import _mask_for_customer
        out = _mask_for_customer("订单号 20260913027050006 已创建", self._ctx("customer"))
        assert "20260913027050006" in out

    def test_empty_and_none(self):
        from app.api.chat import _mask_for_customer
        assert _mask_for_customer("", self._ctx("customer")) == ""
        assert _mask_for_customer(None, self._ctx("customer")) is None


class TestStreamBridgeMaskingWiring:
    """**接线**断言：脱敏必须真的作用在流式桥上（M120 变异存活暴露的缺口）。

    只测 helper 是假守卫 —— 把出站口那行的 `_mask_for_customer(...)` 删掉，
    helper 单测照样全绿（本轮实测 M120 存活）。故这里直接驱动
    `_agent_stream_to_sse`：喂一个含手机号的文本响应，收集 SSE 输出。
    """

    def _run(self, content, role="customer"):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content=content)

        class _Mem:
            async def add_message(self, **kw):
                return None

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                           identity_type="customer")
        gen = _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(), _Mem(),
                                   "s1", 1, "u1")

        async def _collect():
            out = []
            async for chunk in gen:
                out.append(chunk)
            return out

        return asyncio.run(_collect())

    def test_bridge_masks_intermediate_text(self):
        """中间文本（text_before_tools 路径）出站即脱敏 —— 这是 OR-017 R2 泄露的那条。"""
        chunks = self._run("已用您上次的收货信息：张三 13800138000 杭州市西湖区文三路1号")
        joined = "".join(chunks)
        assert "13800138000" not in joined, f"出站文本未脱敏: {joined[:200]}"
        assert "138****8000" in joined

    def test_bridge_keeps_staff_text(self):
        chunks = self._run("客户 13800138000", role="admin")
        assert "13800138000" in "".join(chunks)
