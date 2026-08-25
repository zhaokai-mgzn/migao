"""app/api/sse.py 单元测试 — SSE 事件构建与流构建器。

覆盖 SSEEvent 全部事件类型（text/tool_call/tool_result/card/done/error/
heartbeat/suggestions/interactive/loading）与 SSEStreamBuilder 链式追加、
build 拼接、迭代协议，确保 SSE 帧格式稳定。
"""
# case_ids: API-006

import json

from app.api.sse import SSEEvent, SSEStreamBuilder


def _parse_data(event: str):
    """提取 SSE 帧的 event 名与 data 字段（data 为 JSON 对象）。"""
    lines = event.strip().split("\n")
    event_name = lines[0].split(": ", 1)[1]
    data = json.loads(lines[1].split(": ", 1)[1])
    return event_name, data


class TestSSEEventText:
    def test_text_unicode_not_escaped(self):
        event = SSEEvent.text("你好，世界")
        assert event.startswith("event: text\n")
        assert "你好，世界" in event
        assert event.endswith("\n\n")

    def test_text_shape(self):
        event = SSEEvent.text("hello")
        name, data = _parse_data(event)
        assert name == "text"
        assert data == {"content": "hello"}


class TestSSEEventToolCall:
    def test_tool_call_shape(self):
        event = SSEEvent.tool_call("order_query", {"page": 1})
        name, data = _parse_data(event)
        assert name == "tool_call"
        assert data == {"tool": "order_query", "args": {"page": 1}}


class TestSSEEventToolResult:
    def test_tool_result_shape(self):
        event = SSEEvent.tool_result("order_query", {"success": True})
        name, data = _parse_data(event)
        assert name == "tool_result"
        assert data == {"tool": "order_query", "result": {"success": True}}


class TestSSEEventCard:
    def test_card_shape(self):
        event = SSEEvent.card("order", {"items": [{"id": "o1"}]})
        name, data = _parse_data(event)
        assert name == "card"
        assert data == {"type": "order", "data": {"items": [{"id": "o1"}]}}


class TestSSEEventDone:
    def test_done_shape(self):
        event = SSEEvent.done("sess_1", "msg_1")
        name, data = _parse_data(event)
        assert name == "done"
        assert data == {"session_id": "sess_1", "message_id": "msg_1"}


class TestSSEEventError:
    def test_error_without_code(self):
        event = SSEEvent.error("出错了")
        name, data = _parse_data(event)
        assert name == "error"
        assert data == {"message": "出错了"}
        assert "code" not in data

    def test_error_with_code(self):
        event = SSEEvent.error("出错了", "SESSION_CLOSED")
        name, data = _parse_data(event)
        assert name == "error"
        assert data == {"message": "出错了", "code": "SESSION_CLOSED"}


class TestSSEEventHeartbeat:
    def test_heartbeat_is_comment_frame(self):
        event = SSEEvent.heartbeat()
        assert event == ": heartbeat\n\n"
        assert "data:" not in event


class TestSSEEventSuggestions:
    def test_suggestions_shape(self):
        event = SSEEvent.suggestions(["查订单", "看售后"])
        name, data = _parse_data(event)
        assert name == "suggestions"
        assert data == {"questions": ["查订单", "看售后"]}


class TestSSEEventInteractive:
    def test_interactive_payload_merges_type(self):
        event = SSEEvent.interactive("choice", {"title": "请选择"})
        name, data = _parse_data(event)
        assert name == "interactive"
        assert data == {"type": "choice", "title": "请选择"}


class TestSSEEventLoading:
    def test_loading_default(self):
        event = SSEEvent.loading()
        name, data = _parse_data(event)
        assert name == "loading"
        assert data == {"content": "正在处理..."}

    def test_loading_custom(self):
        event = SSEEvent.loading("正在查询...")
        name, data = _parse_data(event)
        assert data == {"content": "正在查询..."}


class TestSSEStreamBuilder:
    def test_build_empty(self):
        assert SSEStreamBuilder().build() == ""

    def test_fluent_chain_all_events(self):
        builder = SSEStreamBuilder()
        result = (
            builder
            .add_loading("思考中")
            .add_text("你好")
            .add_tool_call("order_query", {"page": 1})
            .add_tool_result("order_query", {"success": True})
            .add_card("order", {"items": []})
            .add_error("失败", "ERR")
            .add_done("sess", "msg")
            .build()
        )
        assert result.count("event: ") == 7
        assert "event: loading" in result
        assert "event: text" in result
        assert "event: tool_call" in result
        assert "event: tool_result" in result
        assert "event: card" in result
        assert "event: error" in result
        assert "event: done" in result

    def test_iter_protocol(self):
        builder = SSEStreamBuilder()
        builder.add_text("a").add_text("b")
        events = list(iter(builder))
        assert len(events) == 2
        assert all(e.startswith("event: text") for e in events)

    def test_build_joins_in_order(self):
        builder = SSEStreamBuilder()
        out = builder.add_text("1").add_text("2").build()
        assert out.index("1") < out.index("2")
