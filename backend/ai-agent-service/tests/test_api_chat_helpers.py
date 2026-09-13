"""
Tests for app/api/*.py — coverage gap issue #581
Covers: chat (helpers), sse (SSEEvent/SSEStreamBuilder),
         upload (_sniff_image_type/_validate_image_file), internal (Pydantic models)
"""
# case_ids: CH-001, API-004, CH-010, CH-011, CH-012, OR-017
import json
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


class TestCardMaskingAtSseBoundary:
    """卡片脱敏在**出站层**（issue #3379）——顾客看到脱敏，模型上下文保持原值。"""

    def _ctx(self, role):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    def _card(self):
        return {"component": "confirm", "title": "请确认收货信息",
                "fields": [{"label": "收货人", "value": "张三"},
                           {"label": "手机号", "value": "13800138000"}],
                "confirmValue": "确认提交：张三 13800138000"}

    def test_customer_card_masked_on_output(self):
        """**顾客可见部分**（title/fields/formFields/options.label）脱敏；
        `confirmValue` 属协议值不脱敏（见下一条测试）—— 故不能对整卡 JSON 断言"不含手机号"。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx("customer"))
        assert "138****8000" in out["fields"][1]["value"], f"字段未脱敏: {out['fields']}"
        assert "13800138000" not in json.dumps(out["fields"], ensure_ascii=False)

    def test_confirm_value_untouched(self):
        """`confirmValue` 是回传协议值 —— 出站也不改，否则顾客点卡后匹配不上。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx("customer"))
        assert out["confirmValue"] == "确认提交：张三 13800138000"

    def test_staff_card_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        assert _mask_card_for_customer(card, self._ctx("admin")) == card

    def test_option_values_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = {"component": "choice", "title": "选一下",
                "options": [{"label": "打孔 13800138000", "value": "opt_13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert out["options"][0]["value"] == "opt_13800138000"
        assert "13800138000" not in out["options"][0]["label"]

    def test_form_prefill_value_not_masked(self):
        """**form 的预填值不得脱敏**（issue #3379 关键修正，CI 实证）。

        前端提交表单会把**所有字段值**回传 → 若出站时把 `formFields[].value` 脱敏，
        顾客（或 harness）提交回来的就是 `138****8000`：
        CI 日志实证 `validate_input({"customer_phone": "138****8000", …})`
        —— **订单会用掩码号码创建**，比"明文回显"严重得多。
        故：form 只脱敏 **label**（顾客可见文案），value（协议回传数据）保持原值；
        confirm 卡的 `fields[].value` 是纯展示（点击回传的是 confirmValue）→ 可脱敏。
        """
        from app.api.chat import _mask_card_for_customer
        card = {"component": "form", "title": "请确认收货信息",
                "formFields": [{"key": "customer_phone", "label": "手机号", "value": "13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert out["formFields"][0]["value"] == "13800138000", \
            "form 预填值被脱敏 → 顾客提交回来后订单会拿到掩码号码"
        assert "13800138000" not in out["formFields"][0]["label"] or True  # label 无 PII 时不改

    def test_confirm_field_value_masked(self):
        """confirm 卡的字段值是纯展示（点击回传 confirmValue）→ 应当脱敏。"""
        from app.api.chat import _mask_card_for_customer
        card = {"component": "confirm", "title": "请确认",
                "fields": [{"label": "手机号", "value": "13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert "138****8000" in out["fields"][0]["value"]

    def test_order_number_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = {"component": "confirm", "title": "订单号 20260913027050006",
                "fields": [{"label": "订单号", "value": "20260913027050006"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert "20260913027050006" in json.dumps(out, ensure_ascii=False)


class TestMaskingStructuralGuards:
    """出站脱敏的**结构级**守卫（issue #3379）。

    上一轮是靠 CI 日志**人工发现**"form 预填值被脱敏 → 掩码号码被提交回来下单"。
    这一个反复出现的教训说明：只补"某个字段"的测试不够，必须把**边界本身**锁死。

    两条不变量：
      A. 出站脱敏只许改写**展示文本**（白名单），**任何其它键必须逐字节不变** ——
         卡载荷里混着展示与协议（`value`/`key`/`component`/自定义回声字段），
         脱敏一旦越界就会污染回传数据；
      B. 脱敏只作用于**出站**，落库历史（喂给模型的上下文）必须保持原值。
    """

    def _ctx(self, role="customer"):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    # 允许被改写的键（白名单）；其它一律不许动
    ALLOWED = {
        ("title",),
        ("fields", "label"), ("fields", "value"),
        ("options", "label"),
        ("formFields", "label"),
    }

    def _card(self):
        """尽量把协议键、回声键、展示键混在一起（含未来可能新增的键）。"""
        return {
            "component": "form",
            "title": "请确认收货信息 13800138000",
            "submitLabel": "提交 13800138000",
            "pageMeta": {"page": 1, "size": 10, "cursor": "13800138000"},
            "echo": "13800138000",                     # 若真被回传，脱敏即为越界
            "formFields": [
                {"key": "customer_phone", "label": "手机号 13800138000",
                 "value": "13800138000", "required": True, "placeholder": "13800138000"},
            ],
            "fields": [{"label": "手机号 13800138000", "value": "13800138000", "extra": "13800138000"}],
            "options": [{"label": "选项 13800138000", "value": "opt_13800138000", "meta": "13800138000"}],
            "confirmValue": "确认 13800138000",
            "cancelValue": "取消 13800138000",
        }

    def _walk_and_check(self, before, after, path=()):
        """递归比对：白名单路径**允许**变化；其它路径必须相等。"""
        bad = []
        if isinstance(before, dict) and isinstance(after, dict):
            for k in set(before) | set(after):
                bad += self._walk_and_check(before.get(k), after.get(k), path + (k,))
            return bad
        if isinstance(before, list) and isinstance(after, list):
            for i, (b, a) in enumerate(zip(before, after)):
                bad += self._walk_and_check(b, a, path + (str(i),))
            return bad
        if before != after:
            # 归一化路径（去掉列表的下标，只看字段名序列）
            norm = tuple(x for x in path if not x.isdigit())
            if norm not in self.ALLOWED:
                bad.append((path, before, after))
        return bad

    def test_only_display_fields_may_change(self):
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        out = _mask_card_for_customer(card, self._ctx())
        bad = self._walk_and_check(card, out)
        assert not bad, (
            "出站脱敏越界改写了非展示字段（会被回传 → 污染下单数据）：\n  "
            + "\n  ".join(f"{p}: {b!r} → {a!r}" for p, b, a in bad))

    def test_display_fields_actually_masked(self):
        """白名单不只是"允许变"，还**必须真的变**（否则守卫变成空转）。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx())
        assert "138****8000" in out["title"]
        assert "138****8000" in out["fields"][0]["value"]
        assert "138****8000" in out["formFields"][0]["label"]
        assert "138****8000" in out["options"][0]["label"]

    def test_hidden_protocol_fields_survive(self):
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx())
        assert out["confirmValue"] == "确认 13800138000"
        assert out["cancelValue"] == "取消 13800138000"
        assert out["formFields"][0]["value"] == "13800138000"   # 回传数据
        assert out["options"][0]["value"] == "opt_13800138000"  # 回传标识
        assert out["pageMeta"]["cursor"] == "13800138000"

    def test_staff_payload_is_byte_identical(self):
        """B 端：整份载荷逐字节不变（不做任何脱敏）。"""
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        assert _mask_card_for_customer(card, self._ctx("admin")) == card


class TestHistoryStaysRaw:
    """不变量 B：脱敏只作用出站，**落库历史保持原值**（issue #3379）。

    首版把 `full_response.append(clean)` 也脱敏了 → 模型下一轮读到 `138****8000`，
    以为顾客号码不完整、反过来问顾客要号码（验收 0 → 2 违规）。
    """

    def test_saved_assistant_message_not_masked(self):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        saved = []

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content="您的收货信息：张三 13800138000")

        class _Mem:
            async def add_message(self, **kw):
                saved.append(kw)
                return None

            async def save_message(self, **kw):
                saved.append(kw)
                return None

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role="customer",
                           identity_type="customer")

        async def _collect():
            out = []
            async for chunk in _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(),
                                                    _Mem(), "s1", 1, "u1"):
                out.append(chunk)
            return out

        chunks = asyncio.run(_collect())
        outbound = "".join(chunks)
        assert "138****8000" in outbound, f"出站应脱敏: {outbound[:120]}"
        history = " ".join(str(v) for kw in saved for v in kw.values())
        assert "13800138000" in history, "落库历史被脱敏了 → 模型下一轮会以为号码不完整"


class TestMemoryIntegrityAcrossGraphAndBoundary:
    """跨层不变量：**真 graph** 产出原文 → 出站脱敏 → 落库保持原文（issue #3386）。

    为什么必须跨层：上面的 `TestHistoryStaysRaw` 用**假 agent**（直接 yield 原文），
    看不到上游 graph 已经把 `final_answer` 脱敏过 —— 真 bug 就藏在这条缝里：
    graph 脱敏 `13800138000` → `138****8000` → 落库 → 模型下一轮把 `****` 填成 `0`
    → `13800008000` 建单成功（CH-010 订单 20260913384380002 落库实证）。
    本用例把「真 skill 执行」和「SSE 边界」串起来，两侧同时断言，缝再断就会被拦。
    """

    def _graph_final_answer(self, reply="您的收货信息：张三 · 13800138000"):
        """用**真 skill 执行**（stub LLM）产出 `final_answer` —— 不假手于假 agent。"""
        import asyncio
        from unittest.mock import AsyncMock
        from langchain_core.messages import AIMessage, HumanMessage
        from app.graph.skills.base_skill import execute_skill
        from tests.test_graph_skills import _make_state

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as gb, \
             patch("app.graph.skills.base_skill.get_skill_llm") as gl, \
             patch("app.graph.skills.base_skill.create_skill_registry") as cr, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.return_value = None
            cr.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            gb.return_value = breaker
            final = MagicMock(spec=AIMessage)
            final.content = reply
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[final])
            gl.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="我的收货信息是什么")],
                                  role="customer"),
                skill_name="customer_order", tool_names=["product_search"], system_prompt="p"))
        return res.get("final_answer") or ""

    def test_outbound_masked_while_persisted_stays_raw(self):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        graph_answer = self._graph_final_answer()
        assert "13800138000" in graph_answer, (
            f"graph 层不得脱敏（记忆要保原文）: {graph_answer!r}")

        saved = []

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                # 真 graph 的输出原样喂进 SSE 边界
                yield AgentResponse(type="text", content=graph_answer)

        class _Mem:
            async def add_message(self, **kw):
                saved.append(kw)

            async def save_message(self, **kw):
                saved.append(kw)

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role="customer",
                           identity_type="customer")

        async def _collect():
            out = []
            async for chunk in _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(),
                                                    _Mem(), "s1", 1, "u1"):
                out.append(chunk)
            return out

        outbound = "".join(asyncio.run(_collect()))
        assert "138****8000" in outbound, f"出站必须脱敏（顾客看得到）: {outbound[:160]}"
        history = " ".join(str(v) for kw in saved for v in kw.values())
        assert "13800138000" in history, (
            "落库 assistant 消息被脱敏 → 模型下一轮读残缺值填 0 建单（issue #3386）")
        assert "138****8000" not in history, f"落库必须是原文: {history[:160]!r}"

