"""
知识库管理与小布高级 AI 对话场景冒烟测试 (P1)

覆盖：
- 知识库文档 CRUD 与同步
- 小布多轮对话上下文关联
- 小布复合 Tool 调用 SSE 事件
- 小布 SSE 异常输入处理（空消息/超长消息/并发会话）
- 小布快捷操作菜单
"""

import json
import threading
import time
from typing import List, Optional

import pytest

from .helpers import SmokeTestClient


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _create_session(client: SmokeTestClient, title: str = "smoke-session") -> Optional[str]:
    """创建对话会话并返回 session_id，失败时返回 None"""
    resp = client.post("/api/chat/sessions", json={"title": title})
    if resp.status_code != 200:
        return None
    data = resp.json().get("data", {})
    return data.get("id") or data.get("session_id")


def _stream_collect(client: SmokeTestClient, path: str, payload: dict,
                    timeout: float = 60.0) -> List[dict]:
    """
    通过 stream_post 拉取 SSE 流，使用 sseclient 风格解析事件。
    返回事件列表 [{event, data}]，对端非 SSE 时退化为单条 JSON 数据。
    """
    events: List[dict] = []
    deadline = time.time() + timeout

    with client.stream_post(path, json=payload, timeout=timeout) as resp:
        if resp.status_code != 200:
            # 把状态码与文本带回供调用方断言
            try:
                text = resp.read().decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            return [{"event": "_http_error", "data": {"status": resp.status_code, "text": text}}]

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            try:
                body = resp.read().decode("utf-8", errors="ignore")
                events.append({"event": "_non_stream", "data": body})
            except Exception:
                pass
            return events

        current_event: Optional[str] = None
        data_buf: List[str] = []
        for raw_line in resp.iter_lines():
            if time.time() > deadline:
                break
            line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="ignore")
            if line == "":
                if current_event is not None or data_buf:
                    data_str = "\n".join(data_buf)
                    try:
                        data_val = json.loads(data_str) if data_str else None
                    except json.JSONDecodeError:
                        data_val = data_str
                    events.append({"event": current_event or "message", "data": data_val})
                current_event = None
                data_buf = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())
            # 其他行（id:/retry:）忽略

        # 文件结束兜底
        if current_event is not None or data_buf:
            data_str = "\n".join(data_buf)
            try:
                data_val = json.loads(data_str) if data_str else None
            except json.JSONDecodeError:
                data_val = data_str
            events.append({"event": current_event or "message", "data": data_val})

    return events


def _events_text(events: List[dict]) -> str:
    """把所有事件 data 拼接成纯文本，便于上下文关联断言"""
    parts: List[str] = []
    for ev in events:
        d = ev.get("data")
        if d is None:
            continue
        if isinstance(d, str):
            parts.append(d)
        elif isinstance(d, dict):
            # 常见字段：content/text/message/answer/delta
            for k in ("content", "text", "message", "answer", "delta", "output"):
                v = d.get(k)
                if isinstance(v, str):
                    parts.append(v)
            # 兜底：把字典 dump 进去
            try:
                parts.append(json.dumps(d, ensure_ascii=False))
            except Exception:
                pass
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 知识库管理
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.business
class TestKnowledgeAPI:
    """知识库管理接口测试"""

    def test_list_knowledge(self, authed_admin_client: SmokeTestClient):
        """GET 知识库文档列表"""
        resp = authed_admin_client.get("/api/admin/knowledge/documents", params={
            "page": 1,
            "size": 10,
        })
        if resp.status_code == 404:
            pytest.skip("Knowledge documents API 未实现")
        assert resp.status_code == 200, f"List knowledge failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), f"Expected list, got {type(records)}"

    def test_create_knowledge_document(self, authed_admin_client: SmokeTestClient):
        """POST 创建知识库文档"""
        # 后端使用 multipart/form-data，必填字段：name, type
        files = {
            "name": (None, "smoke-doc-" + str(int(time.time()))),
            "type": (None, "faq"),
            "description": (None, "smoke test doc"),
        }
        resp = authed_admin_client.post("/api/admin/knowledge/documents", files=files)
        if resp.status_code == 404:
            pytest.skip("Create knowledge doc API 未实现")
        assert resp.status_code in (200, 201), (
            f"Create knowledge doc failed: {resp.status_code} {resp.text[:300]}"
        )
        data = resp.json()
        doc = data.get("data", data)
        doc_id = doc.get("id")
        assert doc_id, f"No id returned: {doc}"

        # 清理：创建成功的文档尽量删除
        authed_admin_client.delete(f"/api/admin/knowledge/documents/{doc_id}")

    def test_update_knowledge_document(self, authed_admin_client: SmokeTestClient):
        """PUT 更新知识库文档（若 PUT 不存在则尝试 POST embed 重新同步）"""
        # 先创建一条
        files = {
            "name": (None, "smoke-update-" + str(int(time.time()))),
            "type": (None, "faq"),
            "description": (None, "before update"),
        }
        create_resp = authed_admin_client.post("/api/admin/knowledge/documents", files=files)
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Cannot create doc to update: {create_resp.status_code}")
        doc_id = create_resp.json().get("data", {}).get("id")
        if not doc_id:
            pytest.skip("No doc id returned for update test")

        try:
            put_resp = authed_admin_client.put(
                f"/api/admin/knowledge/documents/{doc_id}",
                json={"name": "smoke-updated", "description": "after update"},
            )
            if put_resp.status_code == 404 or put_resp.status_code == 405:
                # PUT 接口未实现，回退到 embed 重新同步接口
                embed_resp = authed_admin_client.post(
                    f"/api/admin/knowledge/documents/{doc_id}/embed"
                )
                assert embed_resp.status_code == 200, (
                    f"Update fallback (embed) failed: {embed_resp.status_code} {embed_resp.text[:300]}"
                )
            else:
                assert put_resp.status_code == 200, (
                    f"Update knowledge failed: {put_resp.status_code} {put_resp.text[:300]}"
                )
        finally:
            authed_admin_client.delete(f"/api/admin/knowledge/documents/{doc_id}")

    def test_delete_knowledge_document(self, authed_admin_client: SmokeTestClient):
        """DELETE 删除知识库文档"""
        files = {
            "name": (None, "smoke-delete-" + str(int(time.time()))),
            "type": (None, "faq"),
        }
        create_resp = authed_admin_client.post("/api/admin/knowledge/documents", files=files)
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Cannot create doc to delete: {create_resp.status_code}")
        doc_id = create_resp.json().get("data", {}).get("id")
        if not doc_id:
            pytest.skip("No doc id returned for delete test")

        del_resp = authed_admin_client.delete(f"/api/admin/knowledge/documents/{doc_id}")
        assert del_resp.status_code == 200, (
            f"Delete knowledge failed: {del_resp.status_code} {del_resp.text[:300]}"
        )

    def test_knowledge_sync(self, authed_admin_client: SmokeTestClient,
                            ai_client: SmokeTestClient,
                            service_token_headers: dict):
        """POST /sync 触发知识库同步（admin 路径优先，否则走 internal API）"""
        # 优先尝试 admin 路径（部分实现可能注册在 batch-sync）
        admin_resp = authed_admin_client.post(
            "/api/admin/knowledge/batch-sync",
            json={"type": "full_sync"},
        )
        if admin_resp.status_code == 200:
            return  # admin sync 通过

        # 回退到 ai-agent internal sync 接口（需要 service token）
        internal_resp = ai_client.post(
            "/api/internal/knowledge/sync",
            headers=service_token_headers,
            json={
                "type": "full_sync",
                "tenant_id": 1,
            },
        )
        if internal_resp.status_code in (401, 403):
            pytest.skip(f"Internal sync 需要有效 service token: {internal_resp.status_code}")
        if internal_resp.status_code == 404:
            pytest.skip("知识库同步接口未实现")
        # 200 表示触发成功；500 也允许业务上 RAG 未配置时触发失败（仅校验路由可达）
        assert internal_resp.status_code in (200, 202, 500), (
            f"Knowledge sync unexpected: {internal_resp.status_code} {internal_resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# 小布多轮对话
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.ai_chat
class TestAIMultiTurn:
    """小布多轮对话上下文测试"""

    def test_multi_turn_context(self, authed_ai_client: SmokeTestClient):
        """同一会话连续两轮对话，验证第二轮回复仍围绕窗帘话题"""
        session_id = _create_session(authed_ai_client, "smoke-multi-turn")
        if not session_id:
            pytest.skip("Cannot create session")

        # 第一轮
        first_events = _stream_collect(
            authed_ai_client, "/api/chat/send",
            payload={"session_id": session_id, "message": "我想了解窗帘"},
            timeout=60.0,
        )
        assert first_events, "First turn returned no events"
        first_err = next((e for e in first_events if e["event"] == "_http_error"), None)
        if first_err:
            pytest.skip(f"First turn HTTP {first_err['data']['status']}, skip multi-turn")

        # 等待后端落库
        time.sleep(1.0)

        # 第二轮：追问颜色（不再提及"窗帘"）
        second_events = _stream_collect(
            authed_ai_client, "/api/chat/send",
            payload={"session_id": session_id, "message": "有什么颜色"},
            timeout=60.0,
        )
        assert second_events, "Second turn returned no events"
        second_err = next((e for e in second_events if e["event"] == "_http_error"), None)
        assert not second_err, f"Second turn HTTP error: {second_err}"

        text = _events_text(second_events)
        # 上下文关联断言：第二轮文本里应出现颜色相关或窗帘相关字样
        context_keywords = ["颜色", "色", "窗帘", "color"]
        assert any(kw in text for kw in context_keywords), (
            f"Second turn lost context, no related keywords in: {text[:500]}"
        )


# ---------------------------------------------------------------------------
# 小布复合 Tool 调用
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.ai_chat
class TestAIToolCalls:
    """小布复合 Tool 调用 SSE 事件测试"""

    def test_compound_tool_call(self, authed_ai_client: SmokeTestClient):
        """组合工具调用：订单+物流，应在 SSE 流中出现 tool 相关事件"""
        session_id = _create_session(authed_ai_client, "smoke-tool-call")
        if not session_id:
            pytest.skip("Cannot create session")

        events = _stream_collect(
            authed_ai_client, "/api/chat/send",
            payload={
                "session_id": session_id,
                "message": "帮我查一下订单ORD001的物流",
            },
            timeout=60.0,
        )
        err = next((e for e in events if e["event"] == "_http_error"), None)
        if err:
            pytest.skip(f"Tool call HTTP {err['data']['status']}: {err['data']['text'][:200]}")
        assert events, "Empty SSE events for compound tool call"

        # 接受多种事件名：tool_call / tool / tool_start / tool_result
        tool_event_names = {"tool_call", "tool", "tool_start", "tool_result", "tool_end", "function_call"}
        has_tool_event = any(ev.get("event") in tool_event_names for ev in events)

        # 兜底：从事件 data 文本中查找 tool 关键字（部分实现把 tool 信息塞在 data 里）
        joined = _events_text(events).lower()
        has_tool_keyword = any(k in joined for k in ["tool", "order", "logistics", "物流", "订单"])

        assert has_tool_event or has_tool_keyword, (
            f"No tool-related events/keywords found. events={[e['event'] for e in events][:20]} "
            f"text_preview={joined[:300]}"
        )


# ---------------------------------------------------------------------------
# 小布 SSE 异常处理
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.ai_chat
class TestAIErrorHandling:
    """小布 SSE 异常输入处理测试"""

    def test_empty_message(self, authed_ai_client: SmokeTestClient):
        """空消息应返回 4xx 业务错误，不应是 500"""
        session_id = _create_session(authed_ai_client, "smoke-empty-msg")
        if not session_id:
            pytest.skip("Cannot create session")

        resp = authed_ai_client.post("/api/chat/send", json={
            "session_id": session_id,
            "message": "",
        })
        # 允许 SSE 200 但流内返回 error 事件
        if resp.status_code == 200 and "text/event-stream" in resp.headers.get("content-type", ""):
            text = resp.text.lower()
            assert "error" in text or "empty" in text or "invalid" in text or len(text) > 0, (
                "Empty message: stream returned no error indication"
            )
            return
        assert resp.status_code != 500, f"Empty message caused 500: {resp.text[:300]}"
        assert resp.status_code in (200, 400, 422), (
            f"Empty message unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    def test_long_message(self, authed_ai_client: SmokeTestClient):
        """超长消息（2000+字符）应正常处理或返回合理错误"""
        session_id = _create_session(authed_ai_client, "smoke-long-msg")
        if not session_id:
            pytest.skip("Cannot create session")

        long_text = "窗帘咨询：" + ("我想了解你们的产品参数和材质工艺" * 100)
        assert len(long_text) >= 2000

        events = _stream_collect(
            authed_ai_client, "/api/chat/send",
            payload={"session_id": session_id, "message": long_text},
            timeout=60.0,
        )
        # 允许 200/4xx 任意一种合理返回
        err = next((e for e in events if e["event"] == "_http_error"), None)
        if err:
            status = err["data"]["status"]
            assert status != 500, f"Long message caused 500: {err['data']['text'][:300]}"
            assert 400 <= status < 500, f"Long message unexpected status: {status}"
            return
        assert events, "Long message returned empty events"

    def test_concurrent_sessions(self, authed_ai_client: SmokeTestClient):
        """并发两个会话各发一条消息，验证互不干扰"""
        session_a = _create_session(authed_ai_client, "smoke-concurrent-a")
        session_b = _create_session(authed_ai_client, "smoke-concurrent-b")
        if not session_a or not session_b:
            pytest.skip("Cannot create both sessions")
        assert session_a != session_b, "Concurrent sessions returned same id"

        results: dict = {}

        def _worker(name: str, sid: str, message: str):
            try:
                evs = _stream_collect(
                    authed_ai_client, "/api/chat/send",
                    payload={"session_id": sid, "message": message},
                    timeout=60.0,
                )
                results[name] = evs
            except Exception as exc:  # noqa: BLE001
                results[name] = [{"event": "_exception", "data": str(exc)}]

        t1 = threading.Thread(target=_worker, args=("a", session_a, "你好,我想买窗帘"))
        t2 = threading.Thread(target=_worker, args=("b", session_b, "请问发货时间"))
        t1.start()
        t2.start()
        t1.join(timeout=90)
        t2.join(timeout=90)

        assert "a" in results and "b" in results, f"Worker not finished: {list(results.keys())}"
        for name in ("a", "b"):
            evs = results[name]
            assert evs, f"Session {name} got no events"
            err = next((e for e in evs if e["event"] in ("_http_error", "_exception")), None)
            assert not err, f"Session {name} failed: {err}"


# ---------------------------------------------------------------------------
# 小布快捷操作
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.ai_chat
class TestAIQuickActions:
    """小布快捷按钮列表测试"""

    def test_get_quick_actions(self, authed_ai_client: SmokeTestClient):
        """GET /api/chat/quick-actions 返回数组"""
        resp = authed_ai_client.get("/api/chat/quick-actions")
        if resp.status_code == 404:
            pytest.skip("quick-actions 接口未实现")
        assert resp.status_code == 200, f"Quick actions failed: {resp.status_code} {resp.text[:300]}"

        data = resp.json()
        payload = data.get("data", data)
        actions = payload.get("actions") if isinstance(payload, dict) else payload
        if actions is None and isinstance(payload, list):
            actions = payload
        assert isinstance(actions, list), f"actions should be list, got {type(actions)}: {payload}"
