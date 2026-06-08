"""
多模态消息 + URL 重写 + Agent 感知建议 集成测试

通过真实 HTTP 层（httpx.AsyncClient + ASGITransport）验证：
1. 多模态消息发送 → graph 执行不崩溃 → SSE 正常返回（PR #163）
2. CDN URL 在多模态消息中被重写为 OSS URL（PR #167）
3. suggestions_node 根据 agent_type 返回不同建议（PR #169）

与单元测试的区别：
- 单元测试：Mock 所有依赖，验证纯函数/单组件
- 集成测试：走真实 API 层 + graph 执行，仅 Mock LLM 调用和 DB
"""

import json
import time
from contextlib import contextmanager
from typing import List, Dict, Any
from unittest.mock import patch, AsyncMock, MagicMock

import jwt
import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage

from app.agents.customer_service_agent import AgentResponse, AgentContext, reset_agent
from app.tools.registry import reset_tool_registry


# ========== 测试常量 ==========

TEST_JWT_SECRET = "test-secret-key-for-unit-tests"
TEST_TENANT_ID = 1
TEST_USER_ID = "user_integ_001"


def _make_token(user_id: str = TEST_USER_ID, tenant_id: int = TEST_TENANT_ID, **extra) -> str:
    payload = {
        "userId": user_id, "tenantId": tenant_id,
        "identityType": "account", "roles": ["admin"],
        "exp": int(time.time()) + 3600, "sub": user_id, **extra,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _parse_sse_events(raw: str) -> List[Dict[str, Any]]:
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(": "):
            continue
        event_type = data_str = None
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


# ========== In-Memory Session Store ==========

class InMemorySessionStore:
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
        from datetime import datetime
        sid = f"sess_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow()
        self.sessions[sid] = {
            "id": sid, "tenant_id": tenant_id, "customer_id": customer_id,
            "title": title or f"会话 {now:%Y-%m-%d}", "metadata": {},
            "status": "active", "channel": channel, "created_at": now, "updated_at": now,
        }
        return sid

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def get_sessions(self, tenant_id, customer_id, page=1, size=20):
        return [s for s in self.sessions.values()
                if s["tenant_id"] == tenant_id and s["customer_id"] == customer_id]

    async def save_message(self, session_id, role, content, tool_calls=None,
                           tenant_id=None, content_type="text", extra_metadata=None):
        from datetime import datetime
        self._counter += 1
        mid = f"msg_{self._counter:06d}"
        now = datetime.utcnow()
        meta = {}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        if extra_metadata:
            meta.update(extra_metadata)
        self.messages.append({
            "id": mid, "session_id": session_id, "role": role,
            "content_type": content_type, "content": content,
            "tool_calls": tool_calls, "metadata": meta,
            "created_at": now, "tenant_id": tenant_id,
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


_store = InMemorySessionStore()


# ========== Agent Mock ==========

async def _simple_agent_stream(message, context, chat_history):
    """简单的 Agent mock：直接返回文本，不崩溃"""
    yield AgentResponse(content="收到", type="text")
    yield AgentResponse(content="您的消息了。", type="text")


async def _agent_stream_with_suggestions(message, context, chat_history):
    """Agent mock：返回文本 + 触发 suggestions 事件"""
    yield AgentResponse(content="好的，我来帮您处理。", type="text")


# ========== Fixtures ==========

@pytest.fixture(autouse=True)
def _reset():
    reset_agent()
    reset_tool_registry()
    _store.reset()
    yield
    reset_agent()
    reset_tool_registry()
    _store.reset()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


class _SessionMemoryFactory:
    def __call__(self, *args, **kwargs):
        return _store


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


def _patch_app():
    return [
        patch("app.utils.database.init_db", new_callable=AsyncMock),
        patch("app.utils.database.close_db", new_callable=AsyncMock),
        patch("app.utils.redis_client.init_redis", new_callable=AsyncMock),
        patch("app.utils.redis_client.close_redis", new_callable=AsyncMock),
        patch("app.main.get_rag_pipeline", new_callable=AsyncMock, side_effect=ImportError, create=True),
        patch("app.main.get_vector_store", new_callable=AsyncMock, side_effect=ImportError, create=True),
        patch("app.config.settings.DEBUG", True),
        patch("app.config.settings.JWT_PUBLIC_KEY", ""),
        # Mock DB query for user nickname
        patch("app.api.chat.AsyncSessionLocal", create=True),
    ]


async def _create_client():
    from app.main import create_app
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _send_and_collect(client, session_id, message, images=None, headers=None):
    body = {"session_id": session_id, "message": message}
    if images:
        body["images"] = images
    resp = await client.post("/api/chat/send", json=body, headers=headers, timeout=30)
    assert resp.status_code == 200
    return resp.text, _parse_sse_events(resp.text)


# ========== 集成测试：多模态消息端到端（PR #163）==========

class TestMultimodalIntegration:
    """多模态消息集成测试：验证发送带图片的消息不崩溃"""

    async def test_send_multimodal_message_no_crash(self, auth_headers):
        """发送带图片的消息 → graph 正常执行 → SSE 返回 text 事件"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw, events = await _send_and_collect(
                    client, sid, "你能引导我创建订单不",
                    images=["https://oss.example.com/test.jpg"],
                    headers=auth_headers,
                )
                event_types = [e["event"] for e in events]
                # 必须包含 loading + text + done，不能有 error
                assert "loading" in event_types
                assert "text" in event_types
                assert "done" in event_types
                assert "error" not in event_types, f"收到错误事件: {events}"

    async def test_multimodal_message_stored_with_images(self, auth_headers):
        """多模态消息被正确存储，metadata 中包含 images"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _send_and_collect(
                    client, sid, "看看这张图",
                    images=["https://oss.example.com/a.jpg", "https://oss.example.com/b.jpg"],
                    headers=auth_headers,
                )
                # 验证存储的消息
                user_msgs = [m for m in _store.messages if m["role"] == "user"]
                assert len(user_msgs) >= 1
                user_msg = user_msgs[0]
                assert user_msg["content_type"] == "mixed"
                assert "images" in user_msg["metadata"]
                assert len(user_msg["metadata"]["images"]) == 2

    async def test_multimodal_max_3_images(self, auth_headers):
        """超过 3 张图片返回错误"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
        ]
        with _apply_patches(patches) as mocks:
            mock_agent = MagicMock()
            mock_agent.astream_chat = _simple_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                raw, events = await _send_and_collect(
                    client, sid, "测试",
                    images=["https://a.com/1.jpg", "https://a.com/2.jpg",
                            "https://a.com/3.jpg", "https://a.com/4.jpg"],
                    headers=auth_headers,
                )
                event_types = [e["event"] for e in events]
                assert "error" in event_types


# ========== 集成测试：URL 重写（PR #167）==========

class TestUrlRewriteIntegration:
    """URL 重写集成测试：验证 CDN URL 被重写为 OSS URL"""

    async def test_cdn_url_rewritten_in_multimodal_message(self, auth_headers):
        """CDN 域名的图片 URL 在构建多模态消息时被重写为 OSS URL"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
            patch("app.api.chat.settings"),
        ]

        with _apply_patches(patches) as mocks:
            mock_settings = mocks[12]
            mock_settings.IMAGE_URL_REWRITE_FROM = "https://admin.migaozn.com"
            mock_settings.IMAGE_URL_REWRITE_TO = "https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com"
            captured_message = {}

            async def _capture_agent_stream(message, context, chat_history):
                captured_message["content"] = message
                yield AgentResponse(content="图片已收到", type="text")

            mock_agent = MagicMock()
            mock_agent.astream_chat = _capture_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _send_and_collect(
                    client, sid, "这张图是什么",
                    images=["https://admin.migaozn.com/chat/1/photo.jpg"],
                    headers=auth_headers,
                )
                # 验证传给 Agent 的消息中 URL 已被重写
                msg_content = captured_message["content"]
                assert isinstance(msg_content, list), "多模态消息应该是 list"
                image_items = [item for item in msg_content if item.get("type") == "image_url"]
                assert len(image_items) == 1
                rewritten_url = image_items[0]["image_url"]["url"]
                assert rewritten_url == "https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com/chat/1/photo.jpg"
                assert "admin.migaozn.com" not in rewritten_url

    async def test_non_cdn_url_unchanged(self, auth_headers):
        """非 CDN 域名的 URL 不被重写"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
            patch("app.api.chat.settings"),
        ]

        with _apply_patches(patches) as mocks:
            mock_settings = mocks[12]
            mock_settings.IMAGE_URL_REWRITE_FROM = "https://admin.migaozn.com"
            mock_settings.IMAGE_URL_REWRITE_TO = "https://oss.example.com"
            captured_message = {}

            async def _capture_agent_stream(message, context, chat_history):
                captured_message["content"] = message
                yield AgentResponse(content="ok", type="text")

            mock_agent = MagicMock()
            mock_agent.astream_chat = _capture_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _send_and_collect(
                    client, sid, "看看这张",
                    images=["https://other-domain.com/photo.jpg"],
                    headers=auth_headers,
                )
                msg_content = captured_message["content"]
                image_items = [item for item in msg_content if item.get("type") == "image_url"]
                assert image_items[0]["image_url"]["url"] == "https://other-domain.com/photo.jpg"

    async def test_url_rewrite_disabled_when_config_empty(self, auth_headers):
        """URL 重写配置为空时不做替换"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
            patch("app.api.chat.settings"),
        ]

        with _apply_patches(patches) as mocks:
            mock_settings = mocks[12]
            mock_settings.IMAGE_URL_REWRITE_FROM = ""
            mock_settings.IMAGE_URL_REWRITE_TO = ""
            captured_message = {}

            async def _capture_agent_stream(message, context, chat_history):
                captured_message["content"] = message
                yield AgentResponse(content="ok", type="text")

            mock_agent = MagicMock()
            mock_agent.astream_chat = _capture_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                await _send_and_collect(
                    client, sid, "看看",
                    images=["https://admin.migaozn.com/chat/1/photo.jpg"],
                    headers=auth_headers,
                )
                msg_content = captured_message["content"]
                image_items = [item for item in msg_content if item.get("type") == "image_url"]
                # 配置为空，URL 不变
                assert image_items[0]["image_url"]["url"] == "https://admin.migaozn.com/chat/1/photo.jpg"

    async def test_history_images_also_rewritten(self, auth_headers):
        """历史消息中的图片 URL 也被重写"""
        patches = _patch_app() + [
            patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
            patch("app.api.chat.get_agent"),
            patch("app.api.chat.get_tool_registry"),
            patch("app.api.chat.settings"),
        ]

        with _apply_patches(patches) as mocks:
            mock_settings = mocks[12]
            mock_settings.IMAGE_URL_REWRITE_FROM = "https://admin.migaozn.com"
            mock_settings.IMAGE_URL_REWRITE_TO = "https://oss.example.com"
            captured_history = {}

            async def _capture_agent_stream(message, context, chat_history):
                captured_history["history"] = chat_history
                yield AgentResponse(content="ok", type="text")

            mock_agent = MagicMock()
            mock_agent.astream_chat = _capture_agent_stream
            mocks[10].return_value = mock_agent

            async with await _create_client() as client:
                sid = await _store.create_session(TEST_TENANT_ID, TEST_USER_ID)
                # 先发一条带图片的消息（存入历史）
                await _send_and_collect(
                    client, sid, "第一张图",
                    images=["https://admin.migaozn.com/chat/1/first.jpg"],
                    headers=auth_headers,
                )
                # 再发一条（触发历史加载）
                await _send_and_collect(
                    client, sid, "第二张图",
                    images=["https://admin.migaozn.com/chat/1/second.jpg"],
                    headers=auth_headers,
                )
                # 验证历史消息中的图片 URL 也被重写
                history = captured_history.get("history", [])
                for entry in history:
                    if "images" in entry:
                        for img_url in entry["images"]:
                            assert "admin.migaozn.com" not in img_url, \
                                f"历史消息中仍有未重写的 CDN URL: {img_url}"


# ========== 集成测试：Agent 感知建议（PR #169）==========

class TestAgentAwareSuggestionsIntegration:
    """Agent 感知建议集成测试：验证米宝和小布返回不同建议"""

    def test_mibao_presets_differ_from_xiaobu(self):
        """米宝和小布对同一意图的预设建议不同"""
        from app.suggestions.follow_up import (
            MIBAO_PRESET_SUGGESTIONS, XIAOBU_PRESET_SUGGESTIONS,
        )
        # greeting 意图
        assert MIBAO_PRESET_SUGGESTIONS["greeting"] != XIAOBU_PRESET_SUGGESTIONS["greeting"]
        # order_query 意图
        assert MIBAO_PRESET_SUGGESTIONS["order_query"] != XIAOBU_PRESET_SUGGESTIONS["order_query"]

    def test_mibao_has_all_27_intents(self):
        """米宝预设覆盖所有 27 个意图"""
        from app.suggestions.follow_up import MIBAO_PRESET_SUGGESTIONS
        from app.router.intent_config import IntentType
        for intent in IntentType:
            assert intent.value in MIBAO_PRESET_SUGGESTIONS, \
                f"米宝缺少意图 {intent.value} 的预设"

    def test_mibao_no_consumer_phrases(self):
        """米宝预设不包含 C 端消费者文案"""
        from app.suggestions.follow_up import MIBAO_PRESET_SUGGESTIONS
        consumer_phrases = ["浏览热门商品", "咨询窗帘定制", "联系人工客服", "浏览商品"]
        for intent, suggestions in MIBAO_PRESET_SUGGESTIONS.items():
            for s in suggestions:
                for phrase in consumer_phrases:
                    assert phrase not in s, \
                        f"米宝预设 [{intent}] 包含 C 端文案: '{s}'"

    def test_mibao_management_intents_have_b2b_suggestions(self):
        """米宝管理类意图的建议包含 B 端操作关键词"""
        from app.suggestions.follow_up import MIBAO_PRESET_SUGGESTIONS
        b2b_intents = [
            "customer_manage", "employee_manage", "category_manage",
            "system_settings", "dashboard", "data_report",
            "role_manage", "permission_manage",
        ]
        for intent in b2b_intents:
            suggestions = MIBAO_PRESET_SUGGESTIONS.get(intent, [])
            assert len(suggestions) >= 2, f"米宝管理意图 {intent} 建议不足 2 个"
            all_text = " ".join(suggestions)
            # B 端建议应包含管理类动词
            b2b_keywords = ["查看", "管理", "创建", "配置", "分析", "导出", "分配", "调整", "处理"]
            has_b2b = any(kw in all_text for kw in b2b_keywords)
            assert has_b2b, f"米宝管理意图 [{intent}] 建议缺少 B 端关键词: {suggestions}"

    async def test_generator_returns_mibao_suggestions_by_default(self):
        """默认 agent_type 返回米宝建议"""
        from app.suggestions.follow_up import (
            FollowUpSuggestionGenerator, MIBAO_PRESET_SUGGESTIONS,
        )
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "qwen3.6-flash"
            gen = FollowUpSuggestionGenerator()
            gen._api_key = ""  # 禁用动态生成，只用预设

            result = await gen.generate(
                query="查看订单", answer="这是订单列表",
                intent_type="order_query",
            )
            assert result == MIBAO_PRESET_SUGGESTIONS["order_query"]

    async def test_generator_returns_xiaobu_suggestions(self):
        """agent_type=xiaobu 返回小布建议"""
        from app.suggestions.follow_up import (
            FollowUpSuggestionGenerator, XIAOBU_PRESET_SUGGESTIONS,
        )
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "qwen3.6-flash"
            gen = FollowUpSuggestionGenerator()
            gen._api_key = ""

            result = await gen.generate(
                query="查看订单", answer="这是订单列表",
                intent_type="order_query", agent_type="xiaobu",
            )
            assert result == XIAOBU_PRESET_SUGGESTIONS["order_query"]

    async def test_suggestions_node_passes_agent_type(self):
        """suggestions_node 将 state 中的 agent_type 传给 generator"""
        from app.graph.nodes import suggestions_node
        from langchain_core.messages import HumanMessage

        captured_kwargs = {}

        async def _mock_generate(query, answer, intent_type, agent_type="mibao", chat_history=None):
            captured_kwargs["agent_type"] = agent_type
            return ["建议1", "建议2"]

        mock_gen = MagicMock()
        mock_gen.generate = _mock_generate

        with patch("app.suggestions.follow_up.FollowUpSuggestionGenerator", return_value=mock_gen):
            state = {
                "messages": [HumanMessage(content="测试消息")],
                "tenant_id": 1,
                "user_id": "user_001",
                "session_id": "sess_001",
                "role": "admin",
                "agent_type": "mibao",
                "intent_result": {"intent": "order_query"},
                "final_answer": "这是回答",
            }
            result = await suggestions_node(state)
            assert captured_kwargs["agent_type"] == "mibao"
            assert result["suggestions"] == ["建议1", "建议2"]

    async def test_suggestions_node_xiaobu_passes_xiaobu(self):
        """suggestions_node 对 xiaobu agent 传递 agent_type=xiaobu"""
        from app.graph.nodes import suggestions_node
        from langchain_core.messages import HumanMessage

        captured_kwargs = {}

        async def _mock_generate(query, answer, intent_type, agent_type="mibao", chat_history=None):
            captured_kwargs["agent_type"] = agent_type
            return ["s1", "s2"]

        mock_gen = MagicMock()
        mock_gen.generate = _mock_generate

        with patch("app.suggestions.follow_up.FollowUpSuggestionGenerator", return_value=mock_gen):
            state = {
                "messages": [HumanMessage(content="你好")],
                "tenant_id": 1,
                "user_id": "user_001",
                "session_id": "sess_001",
                "role": "customer",
                "agent_type": "xiaobu",
                "intent_result": {"intent": "greeting"},
                "final_answer": "您好！",
            }
            result = await suggestions_node(state)
            assert captured_kwargs["agent_type"] == "xiaobu"
