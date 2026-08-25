"""app/api/chat.py 单元测试 — 会话生命周期、卡片判定、历史转换、SSE 流。

覆盖：sessions 生命周期（create/list/close/reopen/delete/history）的
租户隔离与用户所有权、_should_send_card/_detect_card_type、_rewrite_image_url、
_convert_history_to_agent_format 多模态、suggestion-feedback、quick-actions、
send_message 会话校验与 __PAGE__ 协议守卫、_agent_stream_to_sse 事件序列。
"""
# case_ids: API-001, API-002, API-003, API-004, API-005

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.chat import (
    _should_send_card,
    _detect_card_type,
    _rewrite_image_url,
    _convert_history_to_agent_format,
    _format_datetime,
    _get_user_nickname,
    _agent_stream_to_sse,
    send_message,
    create_session,
    list_sessions,
    close_session_endpoint,
    reopen_session_endpoint,
    delete_session,
    get_history,
    suggestion_feedback,
    get_quick_actions,
)
from app.api.schemas import ChatSendRequest, ChatSessionCreate
from app.utils.auth import UserIdentity
from app.agents.customer_service_agent import AgentContext, AgentResponse


def _user(tenant_id=1, user_id="user_1", role="customer"):
    return UserIdentity(
        user_id=user_id, tenant_id=tenant_id,
        identity_type="wechat_mini", role=role,
    )


def _session(tenant_id=1, customer_id="user_1", status="active", **extra):
    s = {
        "id": "sess_1",
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": "测试会话",
        "status": status,
        "created_at": "2026-06-20T10:00:00Z",
        "updated_at": "2026-06-20T10:00:00Z",
    }
    s.update(extra)
    return s


def _memory(get_session=None, **methods):
    m = AsyncMock()
    m.get_session = AsyncMock(return_value=get_session)
    for k, v in methods.items():
        setattr(m, k, v if isinstance(v, AsyncMock) else AsyncMock(return_value=v))
    return m


# ═══════════════════════════════════════════════
# 卡片判定
# ═══════════════════════════════════════════════

class TestShouldSendCard:
    def test_failed_result_no_card(self):
        assert _should_send_card("product_search", {"success": False}) is False

    def test_product_search_with_products(self):
        assert _should_send_card("product_search", {"success": True, "data": {"products": [{"id": 1}]}}) is True

    def test_product_search_empty(self):
        assert _should_send_card("product_search", {"success": True, "data": {"products": []}}) is False

    def test_product_detail_with_product(self):
        assert _should_send_card("product_detail", {"success": True, "data": {"product": {"id": 1}}}) is True

    def test_product_detail_none(self):
        assert _should_send_card("product_detail", {"success": True, "data": {"product": None}}) is False

    def test_logistics_track(self):
        assert _should_send_card("logistics_track", {"success": True, "data": {"tracking_number": "SF1"}}) is True
        assert _should_send_card("logistics_track", {"success": True, "data": {}}) is False

    def test_order_query_single_order(self):
        assert _should_send_card("order_query", {"success": True, "data": {"order": {"id": "o1"}}}) is True

    def test_order_query_orders_list(self):
        assert _should_send_card("order_query", {"success": True, "data": {"orders": [{"id": "o1"}]}}) is True

    def test_order_query_items_list(self):
        assert _should_send_card("order_query", {"success": True, "data": {"items": [{"id": "o1"}]}}) is True

    def test_order_query_empty(self):
        assert _should_send_card("order_query", {"success": True, "data": {}}) is False

    def test_unknown_tool(self):
        assert _should_send_card("other_tool", {"success": True, "data": {"x": 1}}) is False


class TestDetectCardType:
    def test_mapping(self):
        assert _detect_card_type("product_search", {}) == "product_list"
        assert _detect_card_type("product_detail", {}) == "product_detail"
        assert _detect_card_type("logistics_track", {}) == "logistics"
        assert _detect_card_type("order_query", {}) == "order"
        assert _detect_card_type("unknown", {}) is None


# ═══════════════════════════════════════════════
# 历史转换 + 图片 URL 重写
# ═══════════════════════════════════════════════

class TestConvertHistory:
    def test_metadata_dict_images(self):
        result = _convert_history_to_agent_format([{
            "role": "user", "content": "看图",
            "metadata": {"images": ["https://a.com/1.jpg", "http://bad.com/2.jpg", "/api/files/3.jpg"]},
        }])
        assert result[0]["images"] == ["https://a.com/1.jpg", "/api/files/3.jpg"]

    def test_metadata_json_string_images(self):
        import json
        result = _convert_history_to_agent_format([{
            "role": "user", "content": "看图",
            "metadata": json.dumps({"images": ["https://a.com/1.jpg"]}),
        }])
        assert result[0]["images"] == ["https://a.com/1.jpg"]

    def test_metadata_json_invalid(self):
        result = _convert_history_to_agent_format([{
            "role": "user", "content": "hi", "metadata": "{not json",
        }])
        assert "images" not in result[0]

    def test_content_type_passthrough(self):
        result = _convert_history_to_agent_format([{
            "role": "user", "content": "hi", "content_type": "mixed",
        }])
        assert result[0]["content_type"] == "mixed"


class TestRewriteImageUrl:
    @patch("app.api.chat.settings")
    def test_rewrite(self, mock_settings):
        mock_settings.IMAGE_URL_REWRITE_FROM = "cdn.a.com"
        mock_settings.IMAGE_URL_REWRITE_TO = "oss.a.com"
        assert _rewrite_image_url("https://cdn.a.com/x.jpg") == "https://oss.a.com/x.jpg"

    @patch("app.api.chat.settings")
    def test_no_rewrite_config(self, mock_settings):
        mock_settings.IMAGE_URL_REWRITE_FROM = ""
        mock_settings.IMAGE_URL_REWRITE_TO = ""
        assert _rewrite_image_url("https://cdn.a.com/x.jpg") == "https://cdn.a.com/x.jpg"


# ═══════════════════════════════════════════════
# 会话生命周期
# ═══════════════════════════════════════════════

class TestCreateSession:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_create(self, MockSM):
        m = _memory(get_session=_session())
        m.create_session = AsyncMock(return_value="sess_1")
        MockSM.return_value = m
        result = await create_session(ChatSessionCreate(title="t"), current_user=_user())
        assert result["success"] is True
        assert result["data"]["id"] == "sess_1"
        assert result["data"]["user_id"] == "user_1"


class TestListSessions:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_list(self, MockSM):
        m = _memory(get_sessions=[_session()])
        MockSM.return_value = m
        result = await list_sessions(page=1, size=20, current_user=_user())
        assert result["success"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["status"] == "active"


class TestCloseSession:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_not_found(self, MockSM):
        MockSM.return_value = _memory(get_session=None)
        with pytest.raises(HTTPException) as e:
            await close_session_endpoint("sess_x", current_user=_user())
        assert e.value.status_code == 404
        assert e.value.detail["error"]["code"] == "SESSION_NOT_FOUND"

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_cross_tenant(self, MockSM):
        MockSM.return_value = _memory(get_session=_session(tenant_id=2))
        with pytest.raises(HTTPException) as e:
            await close_session_endpoint("sess_1", current_user=_user(tenant_id=1))
        assert e.value.status_code == 403

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_cross_user(self, MockSM):
        MockSM.return_value = _memory(get_session=_session(customer_id="other"))
        with pytest.raises(HTTPException) as e:
            await close_session_endpoint("sess_1", current_user=_user())
        assert e.value.status_code == 403

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_already_closed_idempotent(self, MockSM):
        m = _memory(get_session=_session(status="closed"))
        MockSM.return_value = m
        result = await close_session_endpoint("sess_1", current_user=_user())
        assert result["success"] is True
        assert result["data"]["status"] == "closed"
        m.close_session.assert_not_called()

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_close_active(self, MockSM):
        m = _memory(get_session=_session(status="active"))
        MockSM.return_value = m
        result = await close_session_endpoint("sess_1", current_user=_user())
        assert result["data"]["status"] == "closed"
        m.close_session.assert_awaited_once_with("sess_1")


class TestReopenSession:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_not_found(self, MockSM):
        MockSM.return_value = _memory(get_session=None)
        with pytest.raises(HTTPException) as e:
            await reopen_session_endpoint("sess_x", current_user=_user())
        assert e.value.status_code == 404

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_already_active(self, MockSM):
        m = _memory(get_session=_session(status="active"))
        MockSM.return_value = m
        result = await reopen_session_endpoint("sess_1", current_user=_user())
        assert result["success"] is True
        assert result["data"]["message"] == "会话已是活跃状态"
        m.reopen_session.assert_not_called()

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_reopen_closed(self, MockSM):
        m = _memory(get_session=_session(status="closed"))
        MockSM.return_value = m
        result = await reopen_session_endpoint("sess_1", current_user=_user())
        assert result["data"]["status"] == "active"
        m.reopen_session.assert_awaited_once_with("sess_1")


class TestDeleteSession:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_not_found(self, MockSM):
        MockSM.return_value = _memory(get_session=None)
        with pytest.raises(HTTPException) as e:
            await delete_session("sess_x", current_user=_user())
        assert e.value.status_code == 404

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_cross_tenant(self, MockSM):
        MockSM.return_value = _memory(get_session=_session(tenant_id=2))
        with pytest.raises(HTTPException) as e:
            await delete_session("sess_1", current_user=_user(tenant_id=1))
        assert e.value.status_code == 403

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_cross_user(self, MockSM):
        MockSM.return_value = _memory(get_session=_session(customer_id="other"))
        with pytest.raises(HTTPException) as e:
            await delete_session("sess_1", current_user=_user())
        assert e.value.status_code == 403

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_delete_success(self, MockSM):
        m = _memory(get_session=_session())
        MockSM.return_value = m
        result = await delete_session("sess_1", current_user=_user())
        assert result["success"] is True
        assert result["data"]["session_id"] == "sess_1"
        m.delete_session.assert_awaited_once_with("sess_1")


class TestGetHistory:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_not_found(self, MockSM):
        MockSM.return_value = _memory(get_session=None)
        with pytest.raises(HTTPException) as e:
            await get_history("sess_x", current_user=_user())
        assert e.value.status_code == 404

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_cross_tenant(self, MockSM):
        MockSM.return_value = _memory(get_session=_session(tenant_id=2))
        with pytest.raises(HTTPException) as e:
            await get_history("sess_1", current_user=_user(tenant_id=1))
        assert e.value.status_code == 403

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_success(self, MockSM):
        msg = {
            "id": "m1", "session_id": "sess_1", "role": "user", "content": "hi",
            "content_type": "mixed", "created_at": "2026-06-20T10:00:00Z",
            "metadata": {"images": ["https://a.com/1.jpg"]},
        }
        m = _memory(get_session=_session(), get_history=[msg])
        MockSM.return_value = m
        result = await get_history("sess_1", current_user=_user())
        assert result["success"] is True
        assert result["data"]["messages"][0]["images"] == ["https://a.com/1.jpg"]


# ═══════════════════════════════════════════════
# 建议反馈 + 快捷操作
# ═══════════════════════════════════════════════

class TestSuggestionFeedback:
    @patch("app.suggestions.preference_tracker.PreferenceTracker")
    @pytest.mark.asyncio
    async def test_feedback(self, MockTracker):
        tracker = MagicMock()
        tracker.record_click = AsyncMock()
        MockTracker.return_value = tracker
        result = await suggestion_feedback(
            {"session_id": "s1", "suggestion": "查看订单"}, current_user=_user()
        )
        assert result == {"ok": True}
        tracker.record_click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_feedback_empty_suggestion(self):
        result = await suggestion_feedback(
            {"session_id": "s1", "suggestion": ""}, current_user=_user()
        )
        assert result == {"ok": True}


class TestQuickActions:
    @pytest.mark.asyncio
    async def test_quick_actions(self):
        result = await get_quick_actions(current_user=_user())
        assert result["success"] is True
        ids = [a["id"] for a in result["data"]["actions"]]
        assert "order_manage" in ids
        assert "product_manage" in ids
        assert "dashboard" in ids
        assert "after_sales" in ids


# ═══════════════════════════════════════════════
# send_message 校验 + __PAGE__ 守卫
# ═══════════════════════════════════════════════

class TestSendMessageValidation:
    @patch("app.api.chat.get_agent")
    @patch("app.api.chat.get_tool_registry")
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_session_not_found(self, MockSM, _reg, _agent):
        MockSM.return_value = _memory(get_session=None)
        with pytest.raises(HTTPException) as e:
            await send_message(ChatSendRequest(session_id="sess_x", message="hi"), current_user=_user())
        assert e.value.status_code == 404
        assert e.value.detail["error"]["code"] == "SESSION_NOT_FOUND"

    @patch("app.api.chat.get_agent")
    @patch("app.api.chat.get_tool_registry")
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_closed_session(self, MockSM, _reg, _agent):
        MockSM.return_value = _memory(get_session=_session(status="closed"))
        with pytest.raises(HTTPException) as e:
            await send_message(ChatSendRequest(session_id="sess_1", message="hi"), current_user=_user())
        assert e.value.status_code == 409
        assert e.value.detail["error"]["code"] == "SESSION_CLOSED"

    @patch("app.api.chat._handle_page_request")
    @pytest.mark.asyncio
    async def test_page_protocol_delegation(self, mock_page):
        mock_page.return_value = MagicMock()
        req = ChatSendRequest(message="__PAGE__|order_query|{\"page\":1}")
        await send_message(req, current_user=_user())
        mock_page.assert_awaited_once()


class TestPageRequest:
    async def _collect(self, response):
        out = []
        async for chunk in response.body_iterator:
            out.append(chunk)
        return "".join(out)

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_bad_format(self, MockSM):
        from app.api.chat import _handle_page_request
        MockSM.return_value = _memory(get_session=_session())
        req = ChatSendRequest(session_id="sess_1", message="__PAGE__|bad")
        resp = await _handle_page_request(req, tenant_id=1, user_id="user_1", current_user=_user())
        body = await self._collect(resp)
        assert "翻页请求格式错误" in body

    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_non_whitelisted_tool(self, MockSM):
        from app.api.chat import _handle_page_request
        MockSM.return_value = _memory(get_session=_session())
        req = ChatSendRequest(session_id="sess_1", message="__PAGE__|order_create|{\"x\":1}")
        resp = await _handle_page_request(req, tenant_id=1, user_id="user_1", current_user=_user())
        body = await self._collect(resp)
        assert "不支持该操作的分页查询" in body


# ═══════════════════════════════════════════════
# SSE 流生成器
# ═══════════════════════════════════════════════

def _agent_with(*responses):
    agent = MagicMock()
    async def astream(*a, **kw):
        for r in responses:
            yield r
    agent.astream_chat = astream
    return agent


class TestAgentStreamToSSE:
    def _ctx(self):
        return AgentContext(user_id="u1", tenant_id=1, session_id="s1", role="customer")

    @pytest.mark.asyncio
    async def test_text_stream(self):
        with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
             patch("app.api.chat._generate_title_async", new=AsyncMock()):
            sm = _memory()
            sm.save_message = AsyncMock(return_value="msg_1")
            events = [e async for e in _agent_stream_to_sse(
                agent=_agent_with(AgentResponse(content="你好", type="text")),
                message="你好", context=self._ctx(), chat_history=[],
                tool_registry=MagicMock(), session_memory=sm,
                session_id="s1", tenant_id=1, user_id="u1",
            )]
        body = "".join(events)
        assert "event: loading" in body
        assert "event: text" in body
        assert "event: done" in body

    @pytest.mark.asyncio
    async def test_tool_result_card_interactive(self):
        with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
             patch("app.api.chat._generate_title_async", new=AsyncMock()):
            sm = _memory()
            sm.save_message = AsyncMock(return_value="msg_1")
            responses = [
                AgentResponse(content="查到了", type="text"),
                AgentResponse(content="", type="tool_call", tool_calls=[{"tool": "order_query", "tool_input": {"page": 1}}]),
                AgentResponse(content="", type="tool_result", tool_calls=[{"tool": "order_query", "result": {"success": True, "data": {"order": {"id": "o1"}}}}]),
            ]
            events = [e async for e in _agent_stream_to_sse(
                agent=_agent_with(*responses), message="查订单", context=self._ctx(),
                chat_history=[], tool_registry=MagicMock(), session_memory=sm,
                session_id="s1", tenant_id=1, user_id="u1",
            )]
        body = "".join(events)
        assert "event: tool_call" in body
        assert "event: tool_result" in body
        assert "event: card" in body

    @pytest.mark.asyncio
    async def test_empty_reply_fallback(self):
        with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
             patch("app.api.chat._generate_title_async", new=AsyncMock()):
            sm = _memory()
            sm.save_message = AsyncMock(return_value="msg_1")
            # 只产生空文本 → 走降级兜底文案
            events = [e async for e in _agent_stream_to_sse(
                agent=_agent_with(AgentResponse(content="<think>x</think>", type="text")),
                message="hi", context=self._ctx(), chat_history=[],
                tool_registry=MagicMock(), session_memory=sm,
                session_id="s1", tenant_id=1, user_id="u1",
            )]
        body = "".join(events)
        assert "抱歉，我暂时无法生成回复" in body

    @pytest.mark.asyncio
    async def test_agent_error(self):
        with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
             patch("app.api.chat._generate_title_async", new=AsyncMock()):
            agent = MagicMock()
            async def astream(*a, **kw):
                yield AgentResponse(type="error", content="内部错误")
                return
            agent.astream_chat = astream
            sm = _memory()
            sm.save_message = AsyncMock(return_value="msg_1")
            events = [e async for e in _agent_stream_to_sse(
                agent=agent, message="hi", context=self._ctx(), chat_history=[],
                tool_registry=MagicMock(), session_memory=sm,
                session_id="s1", tenant_id=1, user_id="u1",
            )]
        body = "".join(events)
        assert "event: error" in body
        assert "内部错误" in body


# ═══════════════════════════════════════════════
# 时间格式化 + 用户昵称
# ═══════════════════════════════════════════════

class TestFormatDatetime:
    def test_naive_datetime(self):
        from datetime import datetime
        assert _format_datetime(datetime(2026, 6, 20, 10, 0, 0)) == "2026-06-20T10:00:00Z"

    def test_aware_datetime_converts_to_utc(self):
        from datetime import datetime, timezone, timedelta
        dt = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        assert _format_datetime(dt) == "2026-06-20T04:00:00Z"

    def test_string_double_suffix(self):
        assert _format_datetime("2026-06-20T10:00:00+00:00Z") == "2026-06-20T10:00:00Z"
        assert _format_datetime("2026-06-20T10:00:00+00:00") == "2026-06-20T10:00:00Z"

    def test_plain_string_untouched(self):
        assert _format_datetime("abc") == "abc"


class TestGetUserNickname:
    @pytest.mark.asyncio
    async def test_redis_cache_hit(self):
        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value="小明")
        with patch("app.utils.redis_client.redis_pool", object()), \
             patch("redis.asyncio.Redis", return_value=fake_client):
            result = await _get_user_nickname(1, "u1")
        assert result == "小明"

    @pytest.mark.asyncio
    async def test_all_failure_returns_none(self):
        # Redis 禁用（redis_pool=None）→ DB 抛异常 → 静默返回 None
        with patch("app.utils.redis_client.redis_pool", None), \
             patch("app.utils.database.AsyncSessionLocal", side_effect=RuntimeError("db down")):
            result = await _get_user_nickname(1, "u1")
        # 静默降级：DB 异常被吞、不向上抛，昵称不可得（None，非任何用户名）
        assert not result
