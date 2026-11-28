# case_ids: KF-019
"""app/api/kf_reply.py 单元测试 — 微信客服 AI 回复生成（issue #9302）。

口径（用户裁定 2026-11-28：C 端「不提供 agent 形态，只提供技术能力」）：

- **只发一条最终正文**：中间过程话术（「正在查询…」「稍等」）必须被丢弃 —— 微信客服 48h 内最多 5 条、
  单条 ≤2048 字节，中间气泡既烧预算又更差；
- **单轮工具调用 ≤3**：超出 ⇒ 判不可用（admin-api 转人工）；
- **总超时 ≤8s**：超时 ⇒ 判不可用；
- **fail-closed**：内核报错 / 空正文 ⇒ `success=false`（`KF_REPLY_UNAVAILABLE`），
  admin-api 据此转人工，绝不把半句话或兜底道歉发给客户。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.customer_service_agent import AgentResponse
from app.api.kf_reply import ERR_REPLY_UNAVAILABLE, generate_reply
from app.config import settings


def _text(content: str) -> AgentResponse:
    return AgentResponse(type="text", content=content)


def _tool_call(tool: str) -> AgentResponse:
    return AgentResponse(type="tool_call", content="", tool_calls=[{"tool": tool, "tool_input": {}}])


class _FakeAgent:
    """假内核：按给定事件序列流式产出（零 LLM、零 DB）。"""

    def __init__(self, events, delay: float = 0.0):
        self._events = events
        self._delay = delay

    async def astream_chat(self, message, context):
        for event in self._events:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield event


def _patch_agent(events, delay: float = 0.0):
    return patch("app.api.kf_reply.get_agent", return_value=_FakeAgent(events, delay))


# ============ 产文 ============


class TestGenerateReply:
    @pytest.mark.asyncio
    async def test_returns_only_final_answer(self):
        """中间过程（正在查询…）丢弃，只留最后一条正文。"""
        events = [_text("正在查询库存，请稍等"), _tool_call("customer_product_query"),
                  _text("这款雪尼尔 68 元一米")]
        with _patch_agent(events):
            generated = await generate_reply(1, "s-1", "这款多少钱", "wm-1")

        assert (generated.text if generated else "") == "这款雪尼尔 68 元一米"
        assert "正在查询" not in (generated.text if generated else "")
        assert (generated.tool_calls if generated else -1) == 1

    @pytest.mark.asyncio
    async def test_three_tool_calls_allowed(self):
        events = [_tool_call("a"), _tool_call("b"), _tool_call("c"), _text("这款雪尼尔 68 元一米")]
        with _patch_agent(events):
            generated = await generate_reply(1, "s-1", "这款多少钱")

        assert (generated.tool_calls if generated else -1) == 3
        assert (generated.text if generated else "") != ""

    @pytest.mark.asyncio
    async def test_too_many_tool_calls_is_unavailable(self):
        """第 4 次工具调用 ⇒ 判不可用（admin-api 转人工），不产半成品。"""
        events = [_tool_call("a"), _tool_call("b"), _tool_call("c"), _tool_call("d"),
                  _text("这款雪尼尔 68 元一米")]
        with _patch_agent(events):
            assert await generate_reply(1, "s-1", "这款多少钱") is None

    @pytest.mark.asyncio
    async def test_kernel_error_is_unavailable(self):
        events = [AgentResponse(type="error", content="刚才这轮没成功，请您再说一次")]
        with _patch_agent(events):
            assert await generate_reply(1, "s-1", "这款多少钱") is None

    @pytest.mark.asyncio
    async def test_blank_answer_is_unavailable(self):
        with _patch_agent([_text("   ")]):
            assert await generate_reply(1, "s-1", "这款多少钱") is None

    @pytest.mark.asyncio
    async def test_timeout_is_unavailable(self):
        with patch("app.api.kf_reply.REPLY_TIMEOUT_SECONDS", 0.01):
            with _patch_agent([_text("这款雪尼尔 68 元一米")], delay=0.05):
                assert await generate_reply(1, "s-1", "这款多少钱") is None

    @pytest.mark.asyncio
    async def test_empty_input_skips_kernel(self):
        with patch("app.api.kf_reply.get_agent") as factory:
            assert await generate_reply(1, "s-1", "   ") is None
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_kernel_exception_is_unavailable(self):
        broken = AsyncMock(side_effect=RuntimeError("graph boom"))
        agent = type("A", (), {"astream_chat": lambda self, m, c: broken()})()
        with patch("app.api.kf_reply.get_agent", return_value=agent):
            assert await generate_reply(1, "s-1", "这款多少钱") is None


# ============ 端点 ============


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


def _post(client, payload=None, token="__default__"):
    return client.post(
        "/api/internal/kf/reply",
        headers={
            "X-Service-Token": settings.SERVICE_TOKEN if token == "__default__" else token
        },
        json=payload or {"tenant_id": 1, "session_id": "s-1", "text": "这款多少钱"},
    )


class TestReplyEndpoint:
    def test_ok_returns_one_text(self, client):
        from app.api.kf_reply import Generated

        with patch("app.api.kf_reply.generate_reply",
                   new=AsyncMock(return_value=Generated(text="这款雪尼尔 68 元一米", tool_calls=2))):
            resp = _post(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["text"] == "这款雪尼尔 68 元一米"
        assert body["data"]["tool_calls"] == 2

    def test_unavailable_is_reported_not_500(self, client):
        with patch("app.api.kf_reply.generate_reply", new=AsyncMock(return_value=None)):
            resp = _post(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == ERR_REPLY_UNAVAILABLE

    def test_requires_service_token(self, client):
        assert _post(client, token="wrong-token").status_code in (401, 403)
