# case_ids: OR-016, AS-007
"""F19 非幂等写的幂等键（issue #4037）—— 断言红证先行。

## 缺陷
全仓 `idempotenc|clientRequestId|request_id` 仅 2 处无关命中 ⇒ **非幂等写没有幂等键**。
叠加两条既有事实——**HTTP 客户端超时 25s**（`AdminApiClient(timeout=25.0)`）而
**工具超时 30s**（`_execute_tool_safe`）——「**订单已落库但客户端报失败**」的窗口
客观存在；而失败话术原文还写着「确认后**重试**」⇒ **LLM 重试 = 重复下单 = 直接资金损失**。

## 修法（两层，各管一段）
1. **工具层**：每次**逻辑写请求**生成/复用一个 `clientRequestId`，经
   `X-Client-Request-Id` 下发；**同一个重试窗内请求同一个 ID**（这是"服务端能去重"的前提）。
2. **服务端**（Java，本包同步交付）：按 `(tenant_id, clientRequestId)` 去重，
   同键第二次到达 ⇒ 回放首次结果，不再落库。
3. **话术层**：失败话术去掉「重试」，改为「**先核实是否已建单**」——
   F19 与话术是同一风险面：让模型重试就等于让它重复下单。

## 红证形态
改前：`order_create`/`aftersale_create`/`human_handoff` 的 POST 调用**没有任何**
`X-Client-Request-Id` 头，且失败话术含「重试」二字（下节逐条断言）。

## 作用域（issue #4195 后续）
键 = (重试窗, **会话作用域**)（`session_id`，缺省回退 `user_id`）⇒ 本文件钉的是**F19 语义**
（同一会话/同一窗 ⇒ 同一键、跨窗轮换）；**跨会话必须不同键**的判据与接线锁在
`tests/test_idempotency_key_session_scope.py`（含"改前必红"的实测证据）。
"""
import re
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.aftersale_create import AftersaleCreateTool
from app.tools.base import ToolContext
from app.tools.human_handoff import HumanHandoffTool
from app.tools.order_create import (
    _IDEMPOTENCY_WINDOW_SECONDS,
    OrderCreateTool,
    _idempotency_scope,
    _request_window_id,
    _window_id,
)

REQUESTS_HEADER = "X-Client-Request-Id"


def _order_items():
    return [{"product_name": "遮光窗帘", "quantity": 3,
             "unit_price": 168, "subtotal": 528.0}]


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess_1", role="agent")


@pytest.fixture(autouse=True)
def _reset_window_id():
    """清掉窗口号缓存（缓存键是窗口号本身，见 `_window_id` 的注释）。"""
    _window_id.cache_clear()
    yield
    _window_id.cache_clear()


def _with_library(client, price=168):
    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": "p1", "name": "遮光窗帘"}], "total": 1}}
        return {"success": True, "data": {
            "id": "p1", "name": "遮光窗帘", "price": price, "basePrice": price,
            "skus": [{"id": "p1-1", "skuCode": "SKU-1", "colorName": "米白", "price": price}]}}

    client.get = AsyncMock(side_effect=_get)
    client.post = AsyncMock(return_value={
        "success": True, "data": {"id": "order-1", "orderNo": "ORD-1", "totalAmount": 528.0}})
    return client


class TestRequestWindowId:
    """幂等键本体：**同一（会话, 重试窗）内必须是同一个值**（否则服务端去重根本无从谈起）。

    ⚠️ 作用域 = 会话（issue #4195）后键不再"无参可算"：本类的断言一律显式给一个
    `ToolContext`；"无身份"走的是另一条**登记过**的回退分支（不去重），判据与红证在
    `tests/test_idempotency_key_session_scope.py`。
    """

    def test_same_window_same_key(self, agent_ctx):
        assert _request_window_id(agent_ctx) == _request_window_id(agent_ctx), (
            "同一会话同一重试窗内两次取键得到不同的值 ⇒ 服务端无法去重（重试照样重复下单）")

    def test_key_is_url_safe(self, agent_ctx):
        """幂等键要进 HTTP 头/日志，必须是安全的可打印 ASCII。"""
        assert re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", _request_window_id(agent_ctx))

    def test_key_rotates_after_window(self):
        """跨窗必须换新键：**顾客真的想再打一单**时不能被当成重试吞掉（R2）。

        ⚠️ 这条断言钉住的是一个**真实踩过的实现缺陷**：把窗口号缓存在
        `@lru_cache` 无参函数里（lru_cache 的键是"调用参数"、不是返回值）⇒ 首次算出的
        窗口号被**永久冻结** ⇒ 幂等键进程生命周期内永不轮换 ⇒ 合法复购全被当成重试吞掉。
        故这里直接断言"**同一会话**、两个不同窗口号 ⇒ 两个不同键"，不依赖缓存内部实现。
        """
        now = 1_700_000_000.0
        w1 = int(now // _IDEMPOTENCY_WINDOW_SECONDS)
        w2 = int((now + _IDEMPOTENCY_WINDOW_SECONDS * 2) // _IDEMPOTENCY_WINDOW_SECONDS)
        assert w1 != w2, "自检：构造的两个窗口号必须不同（否则本断言为空断言）"
        assert _window_id(w1, "sess_1") != _window_id(w2, "sess_1"), (
            "跨窗仍复用同一幂等键 ⇒ 正常复购会被误判为重复提交")

    def test_current_window_follows_clock(self, agent_ctx):
        """`_request_window_id(context)` 必须**跟着时钟走**（不是启动时定格的那个窗）。"""
        scope = _idempotency_scope(agent_ctx)
        with patch("app.tools.order_create.time.time", return_value=1_700_000_000.0):
            assert _request_window_id(agent_ctx) == _window_id(1_700_000_000 // 600, scope)
        with patch("app.tools.order_create.time.time",
                   return_value=1_700_000_000.0 + _IDEMPOTENCY_WINDOW_SECONDS * 3):
            assert _request_window_id(agent_ctx) == _window_id(
                int((1_700_000_000.0 + _IDEMPOTENCY_WINDOW_SECONDS * 3) // 600), scope)


class TestOrderCreateSendsIdempotencyKey:
    """下单请求必须带 `X-Client-Request-Id`。"""

    async def _run(self, ctx, post):
        client = AsyncMock()
        _with_library(client)
        client.post = post
        with patch("app.tools.order_create.get_admin_api_client", return_value=client):
            tool = OrderCreateTool()
            return await tool.execute(context=ctx, customer_name="张三",
                                      customer_phone="13800138000", items=_order_items())

    async def test_post_carries_client_request_id(self, agent_ctx):
        post = AsyncMock(return_value={
            "success": True, "data": {"id": "o1", "orderNo": "ORD-1"}})
        result = await self._run(agent_ctx, post)
        assert result.success is True, result.message
        headers = post.await_args.kwargs.get("headers") or {}
        assert headers.get(REQUESTS_HEADER), (
            f"下单 POST 未带 {REQUESTS_HEADER}（= 无幂等键，落库了再报失败就会重复下单）：{headers}")

    async def test_two_retries_share_one_key(self, agent_ctx):
        """同一重试窗内连续两次下单 ⇒ **同一个幂等键**（服务端据此去重）。"""
        seen = []

        async def _post(*a, **kw):
            seen.append((kw.get("headers") or {}).get(REQUESTS_HEADER))
            return {"success": True, "data": {"id": f"o{len(seen)}", "orderNo": f"ORD-{len(seen)}"}}

        await self._run(agent_ctx, AsyncMock(side_effect=_post))
        await self._run(agent_ctx, AsyncMock(side_effect=_post))
        assert len(seen) == 2 and seen[0] and seen[0] == seen[1], (
            f"两次重试的幂等键不同（{seen}）⇒ 服务端去重失效，重试会重复下单")

    async def test_replayed_response_is_surfaced(self, agent_ctx):
        """服务端回放（同键去重命中）⇒ 结果里必须**显式说明是同一单**，不能说得像新单。"""
        post = AsyncMock(return_value={
            "success": True, "data": {"id": "o1", "orderNo": "ORD-1", "replayed": True}})
        result = await self._run(agent_ctx, post)
        assert result.success is True
        assert "ORD-1" in (result.message or "")
        assert (result.data or {}).get("replayed") is True, (
            "回放标记被吞掉 ⇒ 模型会把重试当新单播报（同一单说成两单）")


class TestAftersaleCreateSendsIdempotencyKey:
    """售后建单（C 端 `aftersale_create`）同样必须带幂等键。"""

    async def test_post_carries_client_request_id(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="sess_2", role="customer")
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "o1", "orderNo": "ORD-1"}]}})
        client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "t1", "ticketNo": "AS-1"}})
        with patch("app.tools.aftersale_create.get_admin_api_client", return_value=client):
            result = await AftersaleCreateTool().execute(
                context=ctx, order_id="ORD-1", ticket_type="refund", reason="色差")
        assert result.success is True, result.message
        headers = client.post.await_args.kwargs.get("headers") or {}
        assert headers.get(REQUESTS_HEADER), f"售后建单未带 {REQUESTS_HEADER}：{headers}"
        # R2 负例：既有的来源声明头一个都不能丢
        assert headers.get("X-Agent-Client") == ctx.ticket_source


class TestHumanHandoffSendsIdempotencyKey:
    """转人工（`human_handoff`）同样必须带幂等键。"""

    async def test_post_carries_client_request_id(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="sess_3", role="customer")
        client = AsyncMock()
        client.post = AsyncMock(return_value={
            "success": True, "data": {"id": "t1", "ticketNo": "AS-9"}})
        with patch("app.tools.human_handoff.get_admin_api_client", return_value=client), \
             patch.object(HumanHandoffTool, "_notify_admins",
                          AsyncMock(return_value={"delivered": 1, "error": ""})), \
             patch("app.tools.human_handoff._load_ai_context",
                   AsyncMock(return_value={"summary": "", "messages": []})):
            result = await HumanHandoffTool().execute(context=ctx, reason="顾客要求转人工")
        assert result.success is True, result.message
        # ⚠️ 必须取**首个** POST：转人工后续还会打「通知管理员」「创建人工会话」两个 POST，
        # `await_args` 只给最后一次调用 —— 用它取头会读到无头的那个调用（假红）。
        first = client.post.await_args_list[0].kwargs
        headers = first.get("headers") or {}
        assert headers.get(REQUESTS_HEADER), f"转人工建单未带 {REQUESTS_HEADER}：{headers}"


class TestFailureWordingDropsRetry:
    """失败话术**不得**出现「重试」—— 让模型重试等于让它重复下单（F19 同一风险面）。"""

    @staticmethod
    def _retry_hits(text: str) -> bool:
        return "重试" in (text or "")

    async def test_order_create_failure_wording(self, agent_ctx):
        client = AsyncMock()
        _with_library(client)
        client.post = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("app.tools.order_create.get_admin_api_client", return_value=client):
            result = await OrderCreateTool().execute(
                context=agent_ctx, customer_name="张三",
                customer_phone="13800138000", items=_order_items())
        assert result.success is False
        blob = f"{result.message} {result.suggestion}"
        assert not self._retry_hits(blob), f"下单失败话术仍含「重试」：{blob}"
        assert "核实" in blob or "已建单" in blob, f"未引导「先核实是否已建单」：{blob}"

    async def test_aftersale_create_failure_wording(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="sess_4", role="customer")
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "o1", "orderNo": "ORD-1"}]}})
        client.post = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("app.tools.aftersale_create.get_admin_api_client", return_value=client):
            result = await AftersaleCreateTool().execute(
                context=ctx, order_id="ORD-1", ticket_type="refund", reason="色差")
        assert result.success is False
        blob = f"{result.message} {result.suggestion}"
        assert not self._retry_hits(blob), f"售后失败话术仍含「重试」：{blob}"

    async def test_human_handoff_failure_wording(self):
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="sess_5", role="customer")
        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("app.tools.human_handoff.get_admin_api_client", return_value=client):
            result = await HumanHandoffTool().execute(context=ctx, reason="顾客要求转人工")
        assert result.success is False
        blob = f"{result.message} {result.suggestion}"
        assert not self._retry_hits(blob), f"转人工失败话术仍含「重试」：{blob}"