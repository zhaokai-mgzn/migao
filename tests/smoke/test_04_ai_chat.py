"""
AI 对话链路冒烟测试 (P1)

覆盖：SSE 流式对话建立、商品咨询 Tool 调用、物流查询、知识库检索。
"""

import json
import time

import pytest

from .config import EnvConfig
from .helpers import SmokeTestClient


@pytest.mark.p1
@pytest.mark.ai_chat
class TestAIChatSSE:
    """AI 对话 SSE 流式测试"""

    def test_create_session(self, authed_ai_client: SmokeTestClient):
        """创建对话会话"""
        resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "冒烟测试会话",
        })
        assert resp.status_code == 200, f"Create session failed: {resp.status_code} {resp.text}"
        data = resp.json()
        session_data = data.get("data", data)
        assert session_data.get("id"), "Session has no ID"

    def test_chat_send_message(self, authed_ai_client: SmokeTestClient):
        """发送消息获取 SSE 流式响应"""
        # 创建会话
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "SSE 测试",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")
        if not session_id:
            pytest.skip("No session ID returned")

        # 发送消息
        resp = authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "你好",
        })
        assert resp.status_code == 200, f"Chat send failed: {resp.status_code} {resp.text}"

        # 验证 SSE 响应格式
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            # 流式响应 - 验证 SSE 数据结构（至少含一个 data: 行）
            assert "data:" in resp.text, f"SSE response missing data: {resp.text[:100]}"
        else:
            # 非流式响应也接受
            data = resp.json()
            assert data is not None

    def test_chat_product_inquiry(self, authed_ai_client: SmokeTestClient):
        """商品咨询触发 Tool 调用"""
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "商品咨询测试",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")

        resp = authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "有什么好看的窗帘推荐吗？我想要遮光效果好的",
        })
        assert resp.status_code == 200, f"Product inquiry failed: {resp.status_code}"

        # 验证响应包含有效内容
        if "text/event-stream" in resp.headers.get("content-type", ""):
            # 检查 SSE 事件中是否有 tool_call 或 text/card 事件
            text = resp.text
            has_content = (
                "event: text" in text
                or "event: tool_call" in text
                or "event: card" in text
                or "event: done" in text
            )
            assert has_content, f"No valid SSE events in response: {text[:500]}"

    def test_chat_logistics_query(self, authed_ai_client: SmokeTestClient):
        """物流查询 Tool 调用"""
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "物流查询测试",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")

        resp = authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "我的订单物流到哪了？订单号 ORD20240101001",
        })
        assert resp.status_code == 200, f"Logistics query failed: {resp.status_code}"

    def test_chat_knowledge_search(self, authed_ai_client: SmokeTestClient):
        """知识库检索 Tool 调用"""
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "知识库测试",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")

        resp = authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "你们的退换货政策是什么？",
        })
        assert resp.status_code == 200, f"Knowledge search failed: {resp.status_code}"

    def test_chat_history(self, authed_ai_client: SmokeTestClient):
        """获取对话历史"""
        # 先创建会话并发送消息
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "历史记录测试",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")

        # 发送消息
        authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "测试消息",
        })

        # 等待处理完成
        time.sleep(1)

        # 查询历史
        resp = authed_ai_client.get(f"/api/chat/history/{session_id}")
        assert resp.status_code == 200, f"Chat history failed: {resp.status_code}"
        data = resp.json()
        history_data = data.get("data", data)
        messages = history_data.get("messages", [])
        assert isinstance(messages, list), "History messages should be a list"

    def test_list_sessions(self, authed_ai_client: SmokeTestClient):
        """获取会话列表"""
        resp = authed_ai_client.get("/api/chat/sessions", params={
            "page": 1,
            "size": 10,
        })
        assert resp.status_code == 200, f"List sessions failed: {resp.status_code}"
        data = resp.json()
        session_data = data.get("data", data)
        items = session_data.get("items", session_data.get("records", []))
        assert isinstance(items, list), "Sessions should be a list"

    def test_delete_session(self, authed_ai_client: SmokeTestClient):
        """删除对话会话"""
        # 创建临时会话
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "待删除会话",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create session")

        session_id = session_resp.json().get("data", {}).get("id")

        # 删除
        resp = authed_ai_client.delete(f"/api/chat/sessions/{session_id}")
        assert resp.status_code == 200, f"Delete session failed: {resp.status_code}"
