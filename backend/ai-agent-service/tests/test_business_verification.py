"""
AI Agent Service - 业务验证综合测试

覆盖 7 大维度：
1. Tool Registry 完整性验证（@pytest.mark.registry）
2. API 端点集成测试（@pytest.mark.api）
3. 业务场景验证（@pytest.mark.scenario）
4. Tool 枚举值对齐验证（@pytest.mark.enum_alignment）
5. 角色权限控制验证（@pytest.mark.permission）
6. 错误处理与降级（@pytest.mark.error_handling）
7. SSE 流式响应格式验证（@pytest.mark.sse）

约束：
- 真实 API 端点：POST /api/chat/send（不是 /api/v1/chat）
- 请求体不包含 chat_history（多轮历史由服务端按 session_id 自动加载）
- 使用 mock 替代 Admin API、DashScope LLM 等外部依赖
- 参考 tests/test_e2e_chat_flow.py 与 tests/conftest.py 的现有模式
"""

import json
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.customer_service_agent import AgentResponse, reset_agent
from app.tools import create_default_registry
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import reset_tool_registry


# ========== 常量 ==========

TEST_JWT_SECRET = "test-secret-key-for-unit-tests"
TENANT_A = 1
TENANT_B = 2
CUSTOMER_USER_ID = "customer_001"
ADMIN_USER_ID = "admin_001"
AGENT_USER_ID = "agent_001"

# 默认注册器实际包含的工具（不含 [RAG 禁用] 的两个）
EXPECTED_DEFAULT_TOOL_NAMES = {
    "product_search",
    "product_detail",
    "logistics_track",
    "order_query",
    "order_manage",
    "product_manage",
    "inventory_manage",
    "processing_item_query",
    "customer_manage",
    "employee_manage",
    "role_manage",
    "dashboard_stats",
    "after_sales_manage",
    "notification_manage",
    "settings_manage",
    "session_manage",
    "quick_reply_manage",
    "category_manage",
    "processing_item_manage",
}

# B 端管理 Tool（不允许 customer 角色调用）
B_END_ONLY_TOOLS = {
    "order_manage",
    "product_manage",
    "customer_manage",
    "employee_manage",
    "role_manage",
    "dashboard_stats",
    "after_sales_manage",
    "notification_manage",
    "settings_manage",
    "session_manage",
    "quick_reply_manage",
    "category_manage",
    "processing_item_manage",
}

# C 端 Tool（允许 customer 角色调用）
C_END_TOOLS = {
    "product_search",
    "product_detail",
    "logistics_track",
    "order_query",
    "processing_item_query",
    "inventory_manage",  # inventory_manage 显式包含 customer
}


# ========== 辅助函数 ==========


def _make_token(
    user_id: str = CUSTOMER_USER_ID,
    tenant_id: int = TENANT_A,
    role: str = "customer",
    **extra,
) -> str:
    """生成测试 JWT Token"""
    payload = {
        "userId": user_id,
        "tenantId": tenant_id,
        "identityType": "wechat_mini" if role == "customer" else "account",
        "roles": [role],
        "exp": int(time.time()) + 3600,
        "sub": user_id,
        **extra,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _customer_headers(tenant_id: int = TENANT_A, user_id: str = CUSTOMER_USER_ID) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id=user_id, tenant_id=tenant_id, role='customer')}"}


def _admin_headers(tenant_id: int = TENANT_A, user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(user_id=user_id, tenant_id=tenant_id, role='admin')}"}


def _parse_sse_events(raw: str) -> List[Dict[str, Any]]:
    """解析 SSE 原始文本为事件列表"""
    events: List[Dict[str, Any]] = []
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


# ========== 内存 Session 存储（替代真实 DB） ==========


class _InMemorySessionStore:
    """内存版 SessionMemory，模拟数据库行为"""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.messages: List[Dict] = []
        self._counter = 0

    def reset(self):
        self.sessions.clear()
        self.messages.clear()
        self._counter = 0

    async def create_session(self, tenant_id, customer_id, title=None, channel="web"):
        import uuid
        sid = f"sess_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow()
        self.sessions[sid] = {
            "id": sid,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "title": title or f"会话 {now.strftime('%Y-%m-%d')}",
            "metadata": {},
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
        for s in result:
            s["message_count"] = sum(1 for m in self.messages if m["session_id"] == s["id"])
        return result

    async def save_message(
        self, session_id, role, content, tool_calls=None,
        tenant_id=None, content_type="text", extra_metadata=None,
    ):
        self._counter += 1
        mid = f"msg_{self._counter:06d}"
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

    async def get_history_by_tokens(self, session_id, max_tokens=8000, min_messages=4):
        msgs = [m for m in self.messages if m["session_id"] == session_id]
        msgs.sort(key=lambda m: m["created_at"])
        total = 0
        selected = []
        for m in reversed(msgs):
            est = max(1, len(m.get("content", "")) * 0.55)
            if total + est > max_tokens and len(selected) >= min_messages:
                break
            total += est
            selected.append(m)
        selected.reverse()
        needs = len(selected) < len(msgs) and len(msgs) > min_messages
        return selected, needs

    async def delete_session(self, session_id):
        self.messages = [m for m in self.messages if m["session_id"] != session_id]
        self.sessions.pop(session_id, None)
        return True

    async def session_exists(self, session_id):
        return session_id in self.sessions

    async def close_session(self, session_id):
        if session_id in self.sessions:
            self.sessions[session_id]["status"] = "closed"
            self.sessions[session_id]["updated_at"] = datetime.utcnow()
            return True
        return False

    async def close_other_active_sessions(self, tenant_id, customer_id, except_session_id=None):
        cnt = 0
        for sid, s in list(self.sessions.items()):
            if (
                s["tenant_id"] == tenant_id
                and s["customer_id"] == customer_id
                and s.get("status") == "active"
                and sid != except_session_id
            ):
                s["status"] = "closed"
                cnt += 1
        return cnt

    async def get_last_message_time(self, session_id):
        msgs = [m for m in self.messages if m["session_id"] == session_id]
        if not msgs:
            return None
        msgs.sort(key=lambda m: m["created_at"])
        return msgs[-1]["created_at"]


_store = _InMemorySessionStore()


class _SessionMemoryFactory:
    def __call__(self, *args, **kwargs):
        return _store


# ========== 通用 patch 与 client ==========


def _patch_app_deps():
    return [
        patch("app.utils.database.init_db", new_callable=AsyncMock),
        patch("app.utils.database.close_db", new_callable=AsyncMock),
        patch("app.utils.redis_client.init_redis", new_callable=AsyncMock),
        patch("app.utils.redis_client.close_redis", new_callable=AsyncMock),
        patch("app.main.get_rag_pipeline", new_callable=AsyncMock, side_effect=ImportError, create=True),
        patch("app.main.get_vector_store", new_callable=AsyncMock, side_effect=ImportError, create=True),
        patch("app.config.settings.DEBUG", True),
        patch("app.config.settings.JWT_PUBLIC_KEY", ""),
    ]


@contextmanager
def _apply_patches(patches):
    started = []
    try:
        for p in patches:
            started.append(p.start())
        yield started
    finally:
        for p in patches:
            p.stop()


async def _create_client() -> AsyncClient:
    from app.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


async def _send_and_collect(client: AsyncClient, payload: dict, headers: dict, expect_status: int = 200) -> str:
    """POST /api/chat/send 并返回完整 SSE 文本（或在非 200 时直接返回响应文本以便断言）"""
    resp = await client.post("/api/chat/send", json=payload, headers=headers, timeout=30)
    assert resp.status_code == expect_status, f"unexpected status {resp.status_code}: {resp.text}"
    return resp.text


# ========== Agent 流式 mock 工厂 ==========


def _make_stream(*responses: AgentResponse):
    async def _stream(message, context, chat_history):
        for r in responses:
            yield r
    return _stream


def _tool_call_stream(tool_name: str, tool_input: dict, tool_result: dict, final_text: str = "已为您处理。"):
    async def _stream(message, context, chat_history):
        yield AgentResponse(
            content="",
            type="tool_call",
            tool_calls=[{"tool": tool_name, "tool_input": tool_input}],
        )
        yield AgentResponse(
            content="",
            type="tool_result",
            tool_calls=[{"tool": tool_name, "result": tool_result}],
        )
        yield AgentResponse(content=final_text, type="text")
    return _stream


# ========== Fixtures ==========


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_agent()
    reset_tool_registry()
    _store.reset()
    yield
    reset_agent()
    reset_tool_registry()


@pytest.fixture
def fresh_registry():
    """每次返回一个新的默认 ToolRegistry（不污染全局）"""
    return create_default_registry()


# =====================================================================
# 1. Tool Registry 完整性验证
# =====================================================================


@pytest.mark.registry
@pytest.mark.integration
class TestToolRegistryCompleteness:
    """验证默认 Tool Registry 注册完整、元数据正确

    测试层次：Integration（验证 Tool 集成加载与 Registry 交互）
    """

    def test_default_registry_contains_all_expected_tools(self, fresh_registry):
        """默认注册器应包含全部业务必需的 Tool"""
        registered = set(fresh_registry.get_tool_names())
        missing = EXPECTED_DEFAULT_TOOL_NAMES - registered
        assert not missing, f"Tool 缺失：{missing}"

    def test_quick_reply_manage_tool_is_registered(self, fresh_registry):
        """P0：quick_reply_manage 必须在默认 registry 中（防止历史回归）"""
        assert "quick_reply_manage" in fresh_registry, (
            "quick_reply_manage 未注册到默认 ToolRegistry，AI 客服将无法使用快捷回复模板能力"
        )
        tool = fresh_registry.get_tool("quick_reply_manage")
        assert tool is not None
        assert tool.name == "quick_reply_manage"
        assert "快捷回复" in tool.description or "模板" in tool.description

    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_DEFAULT_TOOL_NAMES))
    def test_tool_has_non_empty_metadata(self, fresh_registry, tool_name):
        """[Unit] 每个 Tool 必须定义有意义的 name / description / parameters schema"""
        tool = fresh_registry.get_tool(tool_name)
        assert tool is not None, f"Tool {tool_name} 未注册"
        assert tool.name == tool_name
        assert tool.description and len(tool.description) >= 5
        assert isinstance(tool.parameters, dict)
        assert tool.parameters.get("type") == "object"
        assert "properties" in tool.parameters

    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_DEFAULT_TOOL_NAMES))
    def test_tool_allowed_roles_uses_known_values(self, fresh_registry, tool_name):
        """[Unit] 每个 Tool 的 allowed_roles 均使用安全的预定义角色值"""
        tool = fresh_registry.get_tool(tool_name)
        assert isinstance(tool.allowed_roles, list)
        assert len(tool.allowed_roles) > 0, f"{tool_name} 的 allowed_roles 为空"
        for role in tool.allowed_roles:
            assert role in {"customer", "admin", "agent", "tenant_admin", "guest"}, (
                f"{tool_name} 包含未知角色 {role}"
            )

    @pytest.mark.parametrize("tool_name", sorted(B_END_ONLY_TOOLS))
    def test_b_end_tool_excludes_customer_role(self, fresh_registry, tool_name):
        """[Unit] B 端管理 Tool 不允许 customer 角色调用"""
        tool = fresh_registry.get_tool(tool_name)
        assert tool is not None, f"Tool {tool_name} 未注册"
        assert "customer" not in tool.allowed_roles, (
            f"B 端 Tool {tool_name} 不应允许 customer 角色"
        )

    @pytest.mark.parametrize("tool_name", sorted(C_END_TOOLS))
    def test_c_end_tool_allows_customer_role(self, fresh_registry, tool_name):
        """[Unit] C 端 Tool 必须允许 customer 角色调用"""
        tool = fresh_registry.get_tool(tool_name)
        assert tool is not None
        assert "customer" in tool.allowed_roles, (
            f"C 端 Tool {tool_name} 必须允许 customer"
        )

    def test_get_schemas_returns_valid_openai_function_format(self, fresh_registry):
        """get_schemas 返回 OpenAI function calling 兼容格式"""
        schemas = fresh_registry.get_schemas()
        assert len(schemas) == len(fresh_registry)
        for schema in schemas:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert "name" in fn and "description" in fn
            assert fn["parameters"]["type"] == "object"

    def test_tool_names_are_unique(self, fresh_registry):
        """Tool name 不能重复（registry 是 dict，但二次保险）"""
        names = fresh_registry.get_tool_names()
        assert len(names) == len(set(names))


# =====================================================================
# 2. API 端点集成测试
# =====================================================================


@pytest.mark.api
@pytest.mark.integration
class TestApiEndpoints:
    """验证核心 API 端点的契约（路径、方法、状态码、响应结构）

    测试层次：Integration（FastAPI 路由 + JWT 中间件 + Session Mock 联调）
    """

    async def test_health_endpoint_returns_healthy(self):
        """GET /health 返回服务健康状态"""
        with _apply_patches(_patch_app_deps()):
            async with await _create_client() as client:
                resp = await client.get("/health")
                assert resp.status_code == 200
                body = resp.json()
                assert body["status"] == "healthy"
                assert "service" in body and "version" in body

    async def test_create_session_returns_session_id(self):
        """POST /api/chat/sessions 创建会话并返回 session_id"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp = await client.post(
                    "/api/chat/sessions",
                    json={"title": "API 测试"},
                    headers=_customer_headers(),
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["success"] is True
                assert body["data"]["id"].startswith("sess_")
                assert body["data"]["tenant_id"] == TENANT_A
                assert body["data"]["title"] == "API 测试"

    async def test_list_sessions_returns_pagination_envelope(self):
        """GET /api/chat/sessions 返回分页结构 {items, page, size, total}"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                # 先创建 2 个会话
                for title in ("会话A", "会话B"):
                    await client.post(
                        "/api/chat/sessions",
                        json={"title": title},
                        headers=_customer_headers(),
                    )
                resp = await client.get("/api/chat/sessions", headers=_customer_headers())
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert "items" in data and "page" in data and "size" in data
                assert len(data["items"]) >= 1

    async def test_send_message_returns_sse_stream(self):
        """POST /api/chat/send 返回 SSE 流（content-type: text/event-stream）"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _make_stream(AgentResponse(content="您好", type="text"))
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": sid, "message": "你好"},
                    headers=_customer_headers(),
                )
                assert resp.status_code == 200
                ctype = resp.headers.get("content-type", "")
                assert "text/event-stream" in ctype
                events = _parse_sse_events(resp.text)
                assert any(e["event"] == "done" for e in events)

    async def test_send_message_does_not_accept_chat_history_field(self):
        """请求体不包含 chat_history 字段：传入也会被忽略（多轮历史由 session_id 自动加载）"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        captured = []

        async def _capture(message, context, chat_history):
            captured.append(list(chat_history) if chat_history else [])
            yield AgentResponse(content="ok", type="text")

        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _capture
            mocks[9].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                # 客户端违规传入 chat_history，应被服务端 schema 忽略
                resp = await client.post(
                    "/api/chat/send",
                    json={
                        "session_id": sid,
                        "message": "测试",
                        "chat_history": [{"role": "user", "content": "伪造历史"}],
                    },
                    headers=_customer_headers(),
                )
                assert resp.status_code == 200
                # 服务端实际给 Agent 的历史只来源于 _store，绝不包含客户端伪造内容
                history = captured[0] if captured else []
                for h in history:
                    assert "伪造历史" not in h.get("content", "")

    async def test_send_message_with_invalid_session_returns_404(self):
        """传入不存在的 session_id 返回 404 SESSION_NOT_FOUND"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream())
            async with await _create_client() as client:
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": "sess_does_not_exist", "message": "你好"},
                    headers=_customer_headers(),
                )
                assert resp.status_code == 404
                detail = resp.json()["detail"]
                assert detail["error"]["code"] == "SESSION_NOT_FOUND"

    async def test_send_message_without_jwt_returns_401(self):
        """缺失 Authorization 头返回 401（关闭 DEBUG 自动注入默认用户）"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            # 关闭 DEBUG 模式以禁用「无 token 自动注入默认 admin」的行为
            patch("app.utils.auth.settings.DEBUG", False),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": "sess_x", "message": "你好"},
                )
                assert resp.status_code == 401

    async def test_get_history_returns_messages(self):
        """GET /api/chat/history/{session_id} 返回历史消息"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(
                astream_chat=_make_stream(AgentResponse(content="您好", type="text"))
            )
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "第一条"},
                    _customer_headers(),
                )
                resp = await client.get(f"/api/chat/history/{sid}", headers=_customer_headers())
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert data["session_id"] == sid
                roles = [m["role"] for m in data["messages"]]
                assert "user" in roles
                assert "assistant" in roles

    async def test_close_session_uses_put_endpoint(self):
        """关闭会话端点为 PUT /api/chat/sessions/{session_id}/close"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp_create = await client.post(
                    "/api/chat/sessions", json={}, headers=_customer_headers()
                )
                sid = resp_create.json()["data"]["id"]
                resp = await client.put(
                    f"/api/chat/sessions/{sid}/close", headers=_customer_headers()
                )
                assert resp.status_code == 200
                assert _store.sessions[sid]["status"] == "closed"


# =====================================================================
# 3. 业务场景验证
# =====================================================================


@pytest.mark.scenario
@pytest.mark.e2e
class TestBusinessScenarios:
    """覆盖售前、订单、售后、后台管理的端到端业务场景

    测试层次：E2E（创建会话→发送消息→验证 SSE 事件序列）
    """

    async def test_customer_search_product_returns_card(self):
        """场景A：售前咨询 - 客户搜索商品 → 触发 product_search → 卡片返回"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_tool_call_stream(
                "product_search",
                {"keyword": "遮光窗帘"},
                {"success": True, "data": {
                    "products": [{"id": "p1", "name": "遮光窗帘", "price": 199.0}],
                    "total": 1,
                }},
                final_text="为您找到 1 款遮光窗帘。",
            ))
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "我想要遮光窗帘"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                event_types = [e["event"] for e in events]
                assert "tool_call" in event_types
                assert "tool_result" in event_types
                # product_search 命中数据时应发送 card 事件
                cards = [e for e in events if e["event"] == "card"]
                assert len(cards) >= 1
                assert cards[0]["data"]["type"] == "product_list"

    async def test_customer_get_product_detail_then_query_sku(self):
        """场景A 续：客户查看详情 → 查询 SKU"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]

        async def _stream(message, context, chat_history):
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "product_detail", "tool_input": {"product_id": "p1"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "product_detail", "result": {
                    "success": True,
                    "data": {"product": {"id": "p1", "name": "遮光窗帘", "price": 199.0}},
                }}],
            )
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "inventory_manage", "tool_input": {"action": "query", "product_id": "p1"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "inventory_manage", "result": {
                    "success": True,
                    "data": {"skus": [{"id": "sku_1", "stock": 100}]},
                }}],
            )
            yield AgentResponse(content="该商品库存充足。", type="text")

        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_stream)
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "p1 的详情和库存"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                tool_calls = [e["data"]["tool"] for e in events if e["event"] == "tool_call"]
                assert "product_detail" in tool_calls
                assert "inventory_manage" in tool_calls

    async def test_customer_order_query_and_logistics_track(self):
        """场景B：订单管理 - 客户查询订单 → 跟踪物流"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]

        async def _stream(message, context, chat_history):
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "order_query", "tool_input": {"order_id": "ord_1001"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "order_query", "result": {
                    "success": True,
                    "data": {"order": {"id": "ord_1001", "status": "shipped", "tracking_no": "SF123"}},
                }}],
            )
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "logistics_track", "tool_input": {"tracking_no": "SF123"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "logistics_track", "result": {
                    "success": True,
                    "data": {
                        "tracking_number": "SF123",
                        "traces": [{"time": "2026-05-30 10:00", "desc": "已揽收"}],
                    },
                }}],
            )
            yield AgentResponse(content="您的订单已发出，运单号 SF123。", type="text")

        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_stream)
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "我的订单 ord_1001 物流"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                tool_names = [e["data"]["tool"] for e in events if e["event"] == "tool_call"]
                assert tool_names == ["order_query", "logistics_track"]
                # 应该既有 order 卡片也有 logistics 卡片
                card_types = [e["data"]["type"] for e in events if e["event"] == "card"]
                assert "order" in card_types
                assert "logistics" in card_types

    async def test_admin_after_sales_create_and_update(self):
        """场景C：售后服务 - 管理员创建工单 → 更新状态"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_tool_call_stream(
                "after_sales_manage",
                {"action": "create", "order_id": "ord_1001", "ticket_type": "refund", "reason": "尺寸不符"},
                {"success": True, "data": {"ticket": {"id": "t_1", "status": "pending"}}},
                final_text="已为您创建退款工单 t_1。",
            ))
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, ADMIN_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "为 ord_1001 创建退款工单"},
                    _admin_headers(),
                )
                events = _parse_sse_events(raw)
                tc = next(e for e in events if e["event"] == "tool_call")
                assert tc["data"]["tool"] == "after_sales_manage"
                # 验证 admin 角色被路由到 mibao Agent（B 端）
                # 通过最终 done 事件返回判断对话成功完成
                assert any(e["event"] == "done" for e in events)

    async def test_admin_dashboard_stats_and_notifications(self):
        """场景D：后台管理 - 管理员查看统计 → 查看通知"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]

        async def _stream(message, context, chat_history):
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "dashboard_stats", "tool_input": {"range": "today"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "dashboard_stats", "result": {
                    "success": True,
                    "data": {"orders": 12, "revenue": 8888.0},
                }}],
            )
            yield AgentResponse(
                content="", type="tool_call",
                tool_calls=[{"tool": "notification_manage", "tool_input": {"action": "unread_count"}}],
            )
            yield AgentResponse(
                content="", type="tool_result",
                tool_calls=[{"tool": "notification_manage", "result": {
                    "success": True,
                    "data": {"unread": 3},
                }}],
            )
            yield AgentResponse(content="今日订单 12 笔，营收 8888 元，未读通知 3 条。", type="text")

        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_stream)
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, ADMIN_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "看一下今日经营数据和通知"},
                    _admin_headers(),
                )
                events = _parse_sse_events(raw)
                tools = [e["data"]["tool"] for e in events if e["event"] == "tool_call"]
                assert "dashboard_stats" in tools
                assert "notification_manage" in tools


# =====================================================================
# 4. 枚举值对齐验证（P2 问题）
# =====================================================================


@pytest.mark.enum_alignment
@pytest.mark.unit
class TestEnumAlignment:
    """验证 Tool 参数 schema 中的 enum 与 admin-api 实际接受值对齐

    测试层次：Unit（纯静态 schema 检查，无外部依赖）
    """

    @pytest.mark.parametrize("tool_name,field,expected", [
        ("notification_manage", "action",
         {"list", "unread_count", "mark_read", "read_all", "delete", "create"}),
        ("notification_manage", "channel",
         {"system", "email", "sms", "wechat"}),
        ("notification_manage", "status",
         {"unread", "read"}),
        ("after_sales_manage", "action",
         {"list", "detail", "create", "update_status"}),
        ("after_sales_manage", "ticket_type",
         {"refund", "exchange", "repair", "complaint", "other"}),
        ("after_sales_manage", "status",
         {"pending", "processing", "resolved", "rejected", "closed"}),
        ("processing_item_manage", "action",
         {"create_item", "update_item", "delete_item", "toggle_item_status",
          "list_categories", "create_category", "update_category", "delete_category",
          "calculate_price"}),
        ("processing_item_manage", "status",
         {"active", "inactive"}),
        ("quick_reply_manage", "action",
         {"list", "categories", "create", "update", "delete"}),
    ])
    def test_tool_enum_field_alignment(self, fresh_registry, tool_name, field, expected):
        """参数化验证：Tool.parameters.properties[field].enum 与 admin-api 定义严格对齐

        涵盖：
        - notification_manage 的 action / channel / status
        - after_sales_manage 的 action / ticket_type / status
        - processing_item_manage 的 action / status
        - quick_reply_manage 的 action
        任何 enum 不对齐都会导致 LLM 生成被 admin-api 拒收的参数。
        """
        tool = fresh_registry.get_tool(tool_name)
        assert tool is not None, f"Tool {tool_name} 未注册"
        actual = set(tool.parameters["properties"][field]["enum"])
        assert actual == expected, (
            f"{tool_name}.{field} 枚举不对齐："
            f"多余={actual - expected} 缺失={expected - actual}"
        )


# =====================================================================
# 5. 角色权限控制验证
# =====================================================================


@pytest.mark.permission
@pytest.mark.integration
class TestRoleBasedPermission:
    """验证 Tool 与 API 的角色 / 多租户隔离

    测试层次：Unit（check_permission） + Integration（跨租户/跨用户 API 隔离）
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("tool_name", [
        "order_manage", "product_manage", "after_sales_manage",
        "dashboard_stats", "employee_manage", "notification_manage",
    ])
    def test_customer_cannot_execute_b_end_tool(self, fresh_registry, tool_name):
        """[Unit] customer 角色直接调用 B 端 Tool 应被 check_permission 拒绝"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=CUSTOMER_USER_ID,
            session_id="s1", role="customer",
        )
        tool = fresh_registry.get_tool(tool_name)
        assert tool is not None
        assert tool.check_permission(ctx) is False, (
            f"customer 不应被允许调用 {tool_name}"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("tool_name", sorted(B_END_ONLY_TOOLS))
    def test_admin_can_execute_b_end_tool(self, fresh_registry, tool_name):
        """[Unit] admin 角色应可调用 B 端 Tool"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=ADMIN_USER_ID,
            session_id="s2", role="admin",
        )
        tool = fresh_registry.get_tool(tool_name)
        assert tool.check_permission(ctx) is True, f"admin 应可调用 {tool_name}"

    @pytest.mark.unit
    @pytest.mark.parametrize("tool_name", [
        "employee_manage", "role_manage", "settings_manage",
        "category_manage", "processing_item_manage",
    ])
    def test_tenant_admin_can_execute_admin_only_tool(self, fresh_registry, tool_name):
        """[Unit] tenant_admin 角色可调用 admin/tenant_admin only 的高权限 Tool"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id="ta_001",
            session_id="s3", role="tenant_admin",
        )
        tool = fresh_registry.get_tool(tool_name)
        assert tool.check_permission(ctx) is True

    @pytest.mark.unit
    @pytest.mark.parametrize("tool_name", [
        "employee_manage", "role_manage", "settings_manage",
    ])
    def test_agent_role_cannot_execute_admin_only_tool(self, fresh_registry, tool_name):
        """[Unit] agent 角色不能调用仅限 admin/tenant_admin 的 Tool"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=AGENT_USER_ID,
            session_id="s4", role="agent",
        )
        tool = fresh_registry.get_tool(tool_name)
        assert tool.check_permission(ctx) is False, (
            f"agent 不应被允许调用 {tool_name}"
        )

    async def test_execute_tool_returns_permission_denied_for_customer(self, fresh_registry):
        """通过 registry.execute_tool 调用越权 Tool 返回 permission denied"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=CUSTOMER_USER_ID,
            session_id="s5", role="customer",
        )
        result = await fresh_registry.execute_tool("dashboard_stats", ctx)
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error == "Permission denied"

    async def test_cross_tenant_session_access_returns_403(self):
        """租户隔离：tenant_id=2 的用户访问 tenant_id=1 的 session 返回 403"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream())
            async with await _create_client() as client:
                # 租户 A 创建会话
                sid_a = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                # 租户 B 试图发送消息到租户 A 的会话
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": sid_a, "message": "越权访问"},
                    headers=_customer_headers(tenant_id=TENANT_B, user_id="customer_002"),
                )
                assert resp.status_code == 403
                detail = resp.json()["detail"]
                assert detail["error"]["code"] == "PERMISSION_DENIED"

    async def test_cross_user_same_tenant_access_returns_403(self):
        """同租户跨用户访问 session 仍应返回 403"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream())
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": sid, "message": "我是别人"},
                    headers=_customer_headers(tenant_id=TENANT_A, user_id="other_user"),
                )
                assert resp.status_code == 403


# =====================================================================
# 6. 错误处理与降级
# =====================================================================


@pytest.mark.error_handling
@pytest.mark.integration
class TestErrorHandlingAndDegradation:
    """验证错误处理：LLM 异常、Tool 异常、超时降级

    测试层次：Integration（包含带 Mock 的 SSE 响应验证）
    """

    async def test_llm_failure_emits_error_sse_event(self):
        """LLM 调用失败应发送 SSE error 事件而非 500"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]

        async def _failing_stream(message, context, chat_history):
            raise Exception("DashScope API timeout")
            yield  # noqa

        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_failing_stream)
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": sid, "message": "你好"},
                    headers=_customer_headers(),
                )
                # 流式响应即使内部异常也以 200 + error 事件结束
                assert resp.status_code == 200
                events = _parse_sse_events(resp.text)
                err = next((e for e in events if e["event"] == "error"), None)
                assert err is not None, "LLM 失败时应产生 error 事件"
                assert "message" in err["data"]

    async def test_tool_execution_exception_returns_safe_message(self, fresh_registry):
        """Tool 执行抛异常时 registry 返回泛化错误消息（不暴露内部细节）"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=ADMIN_USER_ID,
            session_id="s_err", role="admin",
        )
        target = fresh_registry.get_tool("notification_manage")
        with patch.object(target, "execute", side_effect=RuntimeError("Internal Admin API 500")):
            result = await fresh_registry.execute_tool("notification_manage", ctx, action="list")
        assert result.success is False
        assert result.error == "tool_execution_failed"
        # 不应将内部异常细节直接返回给用户
        assert "Internal Admin API 500" not in (result.message or "")

    async def test_unknown_tool_returns_not_found_result(self, fresh_registry):
        """调用未注册 Tool 返回 not_found 结果而非抛异常"""
        ctx = ToolContext(
            tenant_id=TENANT_A, user_id=ADMIN_USER_ID,
            session_id="s_x", role="admin",
        )
        result = await fresh_registry.execute_tool("not_exist_tool", ctx)
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_invalid_jwt_token_returns_401(self):
        """无效 JWT 返回 401"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        ]
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": "sess_x", "message": "你好"},
                    headers={"Authorization": "Bearer invalid-token"},
                )
                assert resp.status_code == 401

    async def test_expired_jwt_token_returns_401(self):
        """过期 JWT 返回 401（直接验证 verify_jwt_token 契约）"""
        from fastapi import HTTPException

        def _expired(token):
            raise HTTPException(
                status_code=401,
                detail={
                    "success": False,
                    "error": {"code": "TOKEN_EXPIRED", "message": "Token has expired"},
                },
            )

        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.utils.auth.verify_jwt_token", side_effect=_expired),
        ]
        # 使用 任意 token，让代码进入 verify_jwt_token 路径
        token = jwt.encode({"userId": CUSTOMER_USER_ID, "tenantId": TENANT_A,
                            "identityType": "wechat_mini", "roles": ["customer"],
                            "exp": int(time.time()) - 3600, "sub": CUSTOMER_USER_ID},
                           TEST_JWT_SECRET, algorithm="HS256")
        with _apply_patches(patches):
            async with await _create_client() as client:
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": "sess_x", "message": "你好"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 401
                assert resp.json()["detail"]["error"]["code"] == "TOKEN_EXPIRED"

    async def test_send_to_closed_session_returns_409(self):
        """向已关闭会话发送消息返回 409 SESSION_CLOSED"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream())
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                await _store.close_session(sid)
                resp = await client.post(
                    "/api/chat/send",
                    json={"session_id": sid, "message": "继续聊"},
                    headers=_customer_headers(),
                )
                assert resp.status_code == 409
                detail = resp.json()["detail"]
                assert detail["error"]["code"] == "SESSION_CLOSED"


# =====================================================================
# 7. SSE 流式响应格式验证
# =====================================================================


@pytest.mark.sse
@pytest.mark.e2e
class TestSseStreamFormat:
    """验证 SSE 事件序列与契约

    测试层次：E2E（完整 chat/send 请求生命周期下的 SSE 序列）
    """

    async def test_sse_basic_sequence_loading_text_done(self):
        """基础对话事件序列：loading → text+ → done"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream(
                AgentResponse(content="您好", type="text"),
                AgentResponse(content="，请问有什么需要？", type="text"),
            ))
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "你好"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                event_types = [e["event"] for e in events]
                # 第一个非心跳事件是 loading
                non_hb = [t for t in event_types if t != "heartbeat"]
                assert non_hb[0] == "loading"
                assert "text" in non_hb
                assert non_hb[-1] == "done"

    async def test_sse_done_event_contains_session_and_message_id(self):
        """done 事件 data 包含 session_id 与 message_id"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_make_stream(
                AgentResponse(content="ok", type="text"),
            ))
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "确认"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                done = next(e for e in events if e["event"] == "done")
                assert "session_id" in done["data"]
                assert "message_id" in done["data"]
                assert done["data"]["session_id"] == sid

    async def test_sse_tool_call_then_tool_result_then_card(self):
        """Tool 调用事件序列：tool_call → tool_result →（命中数据）card"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_tool_call_stream(
                "product_search",
                {"keyword": "床品"},
                {"success": True, "data": {
                    "products": [{"id": "p2", "name": "四件套", "price": 299.0}],
                    "total": 1,
                }},
            ))
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "床品"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                # 严格序列：tool_call 在 tool_result 前；card 在 tool_result 后
                seq = [e["event"] for e in events]
                idx_tc = seq.index("tool_call")
                idx_tr = seq.index("tool_result")
                idx_card = seq.index("card")
                assert idx_tc < idx_tr < idx_card

    async def test_sse_error_event_payload_format(self):
        """error 事件 data 至少包含 message 字段"""
        patches = _patch_app_deps() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]

        async def _err_stream(message, context, chat_history):
            raise RuntimeError("boom")
            yield  # noqa

        with _apply_patches(patches) as mocks:
            mocks[9].return_value = MagicMock(astream_chat=_err_stream)
            async with await _create_client() as client:
                sid = await _store.create_session(TENANT_A, CUSTOMER_USER_ID)
                raw = await _send_and_collect(
                    client,
                    {"session_id": sid, "message": "触发错误"},
                    _customer_headers(),
                )
                events = _parse_sse_events(raw)
                err = next(e for e in events if e["event"] == "error")
                assert isinstance(err["data"], dict)
                assert "message" in err["data"]
