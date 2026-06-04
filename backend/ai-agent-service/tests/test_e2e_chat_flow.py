"""
AI 对话完整链路 E2E 测试

覆盖四个维度：
1. 对话链路 E2E（创建会话→发送消息→SSE流式响应）
2. Tool 调用链路（product_search/product_detail/knowledge_search）
3. 会话管理全流程（创建→列表→删除→历史）
4. 多轮对话与记忆
"""

import json
import time
from datetime import datetime
from typing import AsyncGenerator, List, Dict, Any
from unittest.mock import patch, AsyncMock, MagicMock

import jwt
import pytest
from httpx import AsyncClient, ASGITransport

from app.agents.customer_service_agent import AgentResponse, AgentContext, reset_agent
from app.tools.registry import reset_tool_registry


# ========== 测试常量 ==========

TEST_JWT_SECRET = "test-secret-key-for-unit-tests"
TEST_TENANT_ID = 1
TEST_USER_ID = "user_e2e_001"
TEST_USER_ID_B = "user_e2e_002"


# ========== 辅助函数 ==========

def _make_token(
    user_id: str = TEST_USER_ID,
    tenant_id: int = TEST_TENANT_ID,
    **extra,
) -> str:
    """生成测试 JWT Token"""
    payload = {
        "userId": user_id,
        "tenantId": tenant_id,
        "identityType": "wechat_mini",
        "roles": ["customer"],
        "exp": int(time.time()) + 3600,
        "sub": user_id,
        **extra,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _parse_sse_events(raw: str) -> List[Dict[str, Any]]:
    """解析 SSE 原始文本为事件列表"""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(": "):
            continue
        event_type = None
        data_str = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type and data_str:
            try:
                events.append({"event": event_type, "data": json.loads(data_str)})
            except json.JSONDecodeError:
                events.append({"event": event_type, "data": data_str})
    return events


# ========== Session 存储（in-memory 用于 E2E） ==========

class InMemorySessionStore:
    """内存会话存储，替代真实 DB"""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.messages: List[Dict] = []
        self._msg_counter = 0

    def reset(self):
        self.sessions.clear()
        self.messages.clear()
        self._msg_counter = 0

    async def create_session(self, tenant_id, customer_id, title=None, channel="web"):
        import uuid
        sid = f"sess_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow()
        if not title:
            title = f"会话 {now.strftime('%Y-%m-%d')}"
        self.sessions[sid] = {
            "id": sid,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "title": title,
            "metadata": {"title": title},
            "status": "active",
            "channel": channel,
            "created_at": now,
            "updated_at": now,
        }
        return sid

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def get_sessions(self, tenant_id, customer_id, page=1, size=20):
        items = [
            s for s in self.sessions.values()
            if s["tenant_id"] == tenant_id and s["customer_id"] == customer_id
        ]
        items.sort(key=lambda s: s["updated_at"], reverse=True)
        offset = (page - 1) * size
        result = items[offset: offset + size]
        # 附加 message_count
        for s in result:
            s["message_count"] = sum(
                1 for m in self.messages if m["session_id"] == s["id"]
            )
        return result

    async def save_message(self, session_id, role, content, tool_calls=None, tenant_id=None, content_type="text", extra_metadata=None):
        self._msg_counter += 1
        mid = f"msg_{self._msg_counter:06d}"
        now = datetime.utcnow()
        meta = {}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        if extra_metadata:
            meta.update(extra_metadata)
        self.messages.append({
            "id": mid,
            "session_id": session_id,
            "role": role,
            "content_type": content_type,
            "content": content,
            "tool_calls": tool_calls,
            "metadata": meta,
            "created_at": now,
            "tenant_id": tenant_id,
        })
        if session_id in self.sessions:
            self.sessions[session_id]["updated_at"] = now
        return mid

    async def get_history(self, session_id, limit=20):
        msgs = [m for m in self.messages if m["session_id"] == session_id]
        msgs.sort(key=lambda m: m["created_at"])
        return msgs[-limit:]

    async def delete_session(self, session_id):
        self.messages = [m for m in self.messages if m["session_id"] != session_id]
        self.sessions.pop(session_id, None)
        return True

    async def session_exists(self, session_id):
        return session_id in self.sessions


# 全局 store 实例（每次 fixture 重置）
_store = InMemorySessionStore()


# ========== Fixtures ==========

@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试重置全局单例"""
    reset_agent()
    reset_tool_registry()
    _store.reset()
    yield
    reset_agent()
    reset_tool_registry()


@pytest.fixture
def auth_headers():
    """返回带 JWT 的请求头"""
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def auth_headers_user_b():
    """用户 B 的请求头"""
    return {"Authorization": f"Bearer {_make_token(user_id=TEST_USER_ID_B)}"}


class _SessionMemoryFactory:
    """SessionMemory 工厂，调用时返回 InMemorySessionStore"""
    def __call__(self, *args, **kwargs):
        return _store


async def _simple_agent_stream(message, context, chat_history):
    """简单的 Agent mock 流式响应"""
    yield AgentResponse(content="您好", type="text")
    yield AgentResponse(content="！有什么可以帮您的？", type="text")


async def _agent_stream_with_tool(message, context, chat_history):
    """带 Tool 调用的 Agent mock 流式响应"""
    yield AgentResponse(
        content="",
        type="tool_call",
        tool_calls=[{"tool": "product_search", "tool_input": {"keyword": "窗帘"}}],
    )
    yield AgentResponse(
        content="",
        type="tool_result",
        tool_calls=[{
            "tool": "product_search",
            "result": {
                "success": True,
                "data": {
                    "products": [
                        {"id": "p1", "name": "遮光窗帘", "price": 199.0},
                        {"id": "p2", "name": "纱帘", "price": 99.0},
                    ],
                    "total": 2,
                },
            },
        }],
    )
    yield AgentResponse(content="为您找到2款窗帘产品。", type="text")


async def _agent_stream_error(message, context, chat_history):
    """Agent 抛出异常的 mock"""
    raise Exception("DashScope API timeout")
    yield  # noqa: make it a generator


def _patch_app_deps():
    """返回启动 app 所需的所有 patch context managers"""
    return [
        patch("app.utils.database.init_db", new_callable=AsyncMock),
        patch("app.utils.database.close_db", new_callable=AsyncMock),
        patch("app.utils.redis_client.init_redis", new_callable=AsyncMock),
        patch("app.utils.redis_client.close_redis", new_callable=AsyncMock),
        patch("app.main.get_rag_pipeline", new_callable=AsyncMock, side_effect=ImportError, create=True),
        patch("app.main.get_vector_store", new_callable=AsyncMock, side_effect=ImportError, create=True),
        # Auth: DEBUG mode 会自动解码 JWT（无需公钥）
        patch("app.config.settings.DEBUG", True),
        patch("app.config.settings.JWT_PUBLIC_KEY", ""),
    ]


async def _create_client() -> AsyncClient:
    """创建 httpx AsyncClient"""
    from app.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


async def _stream_and_collect(client: AsyncClient, url: str, json_body: dict, headers: dict) -> str:
    """发送 POST 请求并收集完整 SSE 响应"""
    resp = await client.post(url, json=json_body, headers=headers, timeout=30)
    assert resp.status_code == 200
    return resp.text


# ========== 1. 对话链路 E2E ==========

class TestChatFlowE2E:
    """对话链路端到端测试"""

    async def test_create_session_and_send_message(self, auth_headers):
        """创建会话 → 发送消息 → 收到 SSE 响应"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent") ,
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            # get_agent is mocks[9] (after 8 _patch_app_deps)
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                # 1. 创建会话
                resp = await client.post(
                    "/api/chat/sessions",
                    json={"title": "测试会话"},
                    headers=auth_headers,
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["success"] is True
                session_id = body["data"]["id"]
                assert session_id.startswith("sess_")

                # 2. 发送消息
                raw = await _stream_and_collect(
                    client,
                    "/api/chat/send",
                    {"session_id": session_id, "message": "你好"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                event_types = [e["event"] for e in events]
                assert "loading" in event_types
                assert "text" in event_types
                assert "done" in event_types

    async def test_sse_stream_events_format(self, auth_headers):
        """SSE 事件格式正确：loading → text → done"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID, "fmt test")
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "测试格式"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                # loading 是第一个事件
                assert events[0]["event"] == "loading"
                assert "content" in events[0]["data"]
                # done 是最后一个事件
                assert events[-1]["event"] == "done"
                done_data = events[-1]["data"]
                assert "session_id" in done_data
                assert "message_id" in done_data

    async def test_chat_response_contains_valid_content(self, auth_headers):
        """响应包含有效文本内容"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "你好呀"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                text_events = [e for e in events if e["event"] == "text"]
                assert len(text_events) >= 1
                full_text = "".join(e["data"]["content"] for e in text_events)
                assert len(full_text) > 0
                assert "您好" in full_text

    async def test_chat_with_tool_invocation(self, auth_headers):
        """对话触发 Tool 调用并返回结果"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _agent_stream_with_tool
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "有什么窗帘"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                event_types = [e["event"] for e in events]
                assert "tool_call" in event_types
                assert "tool_result" in event_types
                assert "text" in event_types

                # 验证 tool_call 事件内容
                tc = next(e for e in events if e["event"] == "tool_call")
                assert tc["data"]["tool"] == "product_search"

    async def test_chat_error_handling_graceful_degradation(self, auth_headers):
        """DashScope 异常时优雅降级（返回 error 事件）"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _agent_stream_error
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "你好"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                event_types = [e["event"] for e in events]
                assert "error" in event_types
                err = next(e for e in events if e["event"] == "error")
                assert "message" in err["data"]


# ========== 2. Tool 调用链路 ==========

class TestToolCallE2E:
    """Tool 调用链路测试"""

    async def test_product_search_tool_e2e(self, auth_headers):
        """用户问商品 → Agent 调 product_search → 返回商品列表"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _agent_stream_with_tool
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "搜索遮光窗帘"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                tr = next(e for e in events if e["event"] == "tool_result")
                result = tr["data"]["result"]
                assert result["success"] is True
                assert len(result["data"]["products"]) == 2

                # 验证 card 事件也被发送
                card_events = [e for e in events if e["event"] == "card"]
                assert len(card_events) == 1
                assert card_events[0]["data"]["type"] == "product_list"

    async def test_product_detail_tool_e2e(self, auth_headers):
        """用户问商品详情 → Agent 调 product_detail → 返回详情"""

        async def _detail_stream(message, context, chat_history):
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "product_detail", "tool_input": {"product_id": "p1"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{
                    "tool": "product_detail",
                    "result": {
                        "success": True,
                        "data": {"product": {"id": "p1", "name": "遮光窗帘", "price": 199.0}},
                    },
                }],
            )
            yield AgentResponse(content="这款遮光窗帘售价199元。", type="text")

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _detail_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "p1 商品详情"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                tc = next(e for e in events if e["event"] == "tool_call")
                assert tc["data"]["tool"] == "product_detail"
                card_events = [e for e in events if e["event"] == "card"]
                assert len(card_events) == 1
                assert card_events[0]["data"]["type"] == "product_detail"

    async def test_knowledge_search_tool_e2e(self, auth_headers):
        """用户问售后 → Agent 调 knowledge_search → RAG 返回"""

        async def _ks_stream(message, context, chat_history):
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "knowledge_search", "tool_input": {"query": "退换货政策"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{
                    "tool": "knowledge_search",
                    "result": {
                        "success": True,
                        "data": {"chunks": [{"content": "7天无理由退换"}], "source_count": 1},
                    },
                }],
            )
            yield AgentResponse(content="根据知识库，支持7天无理由退换。", type="text")

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _ks_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "退换货政策是什么"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                tc = next(e for e in events if e["event"] == "tool_call")
                assert tc["data"]["tool"] == "knowledge_search"
                text_events = [e for e in events if e["event"] == "text"]
                full_text = "".join(e["data"]["content"] for e in text_events)
                assert "7天" in full_text

    async def test_multiple_tools_in_single_conversation(self, auth_headers):
        """单次对话中调用多个 Tool"""

        async def _multi_stream(message, context, chat_history):
            # Tool 1: product_search
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "product_search", "tool_input": {"keyword": "窗帘"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{
                    "tool": "product_search",
                    "result": {
                        "success": True,
                        "data": {"products": [{"id": "p1", "name": "遮光窗帘", "price": 199}], "total": 1},
                    },
                }],
            )
            # Tool 2: product_detail
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "product_detail", "tool_input": {"product_id": "p1"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{
                    "tool": "product_detail",
                    "result": {
                        "success": True,
                        "data": {"product": {"id": "p1", "name": "遮光窗帘", "price": 199}},
                    },
                }],
            )
            yield AgentResponse(content="找到一款遮光窗帘，售价199元。", type="text")

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _multi_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw = await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "帮我找窗帘并看详情"},
                    auth_headers,
                )
                events = _parse_sse_events(raw)
                tc_events = [e for e in events if e["event"] == "tool_call"]
                assert len(tc_events) == 2
                tool_names = [e["data"]["tool"] for e in tc_events]
                assert "product_search" in tool_names
                assert "product_detail" in tool_names


# ========== 3. 会话管理全流程 ==========

class TestSessionManagement:
    """会话管理全流程测试"""

    async def test_session_lifecycle_create_list_delete(self, auth_headers):
        """创建 → 列表 → 删除"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                # 创建
                resp = await client.post(
                    "/api/chat/sessions",
                    json={"title": "生命周期测试"},
                    headers=auth_headers,
                )
                assert resp.status_code == 200
                sid = resp.json()["data"]["id"]

                # 列表
                resp = await client.get("/api/chat/sessions", headers=auth_headers)
                assert resp.status_code == 200
                items = resp.json()["data"]["items"]
                ids = [s["id"] for s in items]
                assert sid in ids

                # 删除
                resp = await client.delete(f"/api/chat/sessions/{sid}", headers=auth_headers)
                assert resp.status_code == 200
                assert resp.json()["success"] is True

                # 再次列表，确认已删除
                resp = await client.get("/api/chat/sessions", headers=auth_headers)
                items = resp.json()["data"]["items"]
                assert sid not in [s["id"] for s in items]

    async def test_session_history_messages(self, auth_headers):
        """获取会话历史消息"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                # 创建会话并发消息
                resp = await client.post(
                    "/api/chat/sessions", json={"title": "历史测试"}, headers=auth_headers,
                )
                sid = resp.json()["data"]["id"]

                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "第一条消息"},
                    auth_headers,
                )

                # 获取历史
                resp = await client.get(f"/api/chat/history/{sid}", headers=auth_headers)
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert data["session_id"] == sid
                messages = data["messages"]
                assert len(messages) >= 2  # user + assistant
                roles = [m["role"] for m in messages]
                assert "user" in roles
                assert "assistant" in roles

    async def test_session_isolation_between_users(self, auth_headers, auth_headers_user_b):
        """不同用户的会话隔离"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                # 用户 A 创建会话
                resp_a = await client.post(
                    "/api/chat/sessions", json={"title": "A的会话"}, headers=auth_headers,
                )
                sid_a = resp_a.json()["data"]["id"]

                # 用户 B 创建会话
                resp_b = await client.post(
                    "/api/chat/sessions", json={"title": "B的会话"}, headers=auth_headers_user_b,
                )
                sid_b = resp_b.json()["data"]["id"]

                # 用户 A 列表不应看到 B 的会话
                resp = await client.get("/api/chat/sessions", headers=auth_headers)
                ids_a = [s["id"] for s in resp.json()["data"]["items"]]
                assert sid_a in ids_a
                assert sid_b not in ids_a

                # 用户 B 列表不应看到 A 的会话
                resp = await client.get("/api/chat/sessions", headers=auth_headers_user_b)
                ids_b = [s["id"] for s in resp.json()["data"]["items"]]
                assert sid_b in ids_b
                assert sid_a not in ids_b

                # 用户 B 尝试访问 A 的会话历史 → 403
                resp = await client.get(f"/api/chat/history/{sid_a}", headers=auth_headers_user_b)
                assert resp.status_code == 403

    async def test_quick_actions_menu(self, auth_headers):
        """快捷功能菜单返回正确"""
        patches = _patch_app_deps()
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp = await client.get("/api/chat/quick-actions", headers=auth_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                actions = data["data"]["actions"]
                assert len(actions) >= 4
                action_ids = [a["id"] for a in actions]
                # B 端管理视角的快捷操作
                assert "order_manage" in action_ids
                assert "product_manage" in action_ids
                assert "dashboard" in action_ids
                assert "customer_manage" in action_ids
                # 每个 action 有必要字段
                for a in actions:
                    assert "name" in a
                    assert "icon" in a
                    assert "prompt" in a


# ========== 4. 多轮对话与记忆 ==========

class TestMultiTurnMemory:
    """多轮对话与记忆测试"""

    async def test_multi_turn_context_memory(self, auth_headers):
        """多轮对话上下文记忆：Agent 收到对话历史"""
        captured_histories = []

        async def _capturing_stream(message, context, chat_history):
            captured_histories.append(list(chat_history) if chat_history else [])
            yield AgentResponse(content="收到", type="text")

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _capturing_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)

                # 第一轮
                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "你好"},
                    auth_headers,
                )
                # 第二轮
                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid, "message": "推荐窗帘"},
                    auth_headers,
                )

                # 第二轮时 Agent 收到的 chat_history 应包含之前的消息
                assert len(captured_histories) == 2
                # 第一轮历史为空或只有自己
                # 第二轮历史应该包含第一轮的 user + assistant
                second_history = captured_histories[1]
                assert len(second_history) >= 2

    async def test_session_memory_persists_across_messages(self, auth_headers):
        """会话记忆跨消息持久化"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)

                # 发送三条消息
                for msg in ["消息1", "消息2", "消息3"]:
                    await _stream_and_collect(
                        client, "/api/chat/send",
                        {"session_id": sid, "message": msg},
                        auth_headers,
                    )

                # 检查历史
                resp = await client.get(f"/api/chat/history/{sid}", headers=auth_headers)
                messages = resp.json()["data"]["messages"]
                # 每条消息都有 user + assistant = 6条
                assert len(messages) >= 6
                user_msgs = [m for m in messages if m["role"] == "user"]
                assert len(user_msgs) == 3

    async def test_new_session_has_no_previous_context(self, auth_headers):
        """新会话无历史上下文"""
        captured_histories = []

        async def _capturing_stream(message, context, chat_history):
            captured_histories.append(list(chat_history) if chat_history else [])
            yield AgentResponse(content="你好", type="text")

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _capturing_stream
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                # 会话 1 发两条
                sid1 = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid1, "message": "第一会话消息1"},
                    auth_headers,
                )
                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid1, "message": "第一会话消息2"},
                    auth_headers,
                )

                # 新建会话 2
                sid2 = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _stream_and_collect(
                    client, "/api/chat/send",
                    {"session_id": sid2, "message": "第二会话第一条"},
                    auth_headers,
                )

                # 会话 2 的第一条消息历史应该为空
                # captured_histories[0]=sid1第1条, [1]=sid1第2条, [2]=sid2第1条
                assert len(captured_histories) == 3
                sid2_first_history = captured_histories[2]
                # 新会话第一次发消息时，只有刚保存的 user 消息
                # 不应包含会话 1 的任何消息
                for h in sid2_first_history:
                    assert "第一会话" not in h.get("content", "")


# ========== 辅助：批量 patch ==========

from contextlib import contextmanager


@contextmanager
def _apply_patches(patches):
    """批量应用 patch 列表，返回所有 mock 对象列表"""
    started = []
    try:
        for p in patches:
            m = p.start()
            started.append(m)
        yield started
    finally:
        for p in patches:
            p.stop()
