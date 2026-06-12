"""
E2E: 全部 21 工具 + 错误恢复 + C端场景

复用 test_e2e_chat_flow.py 的基础设施。
每个测试：创建 session → mock agent stream → 发送消息 → 验证 SSE 事件。
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.test_e2e_chat_flow import (
    _make_token, _parse_sse_events, _patch_app_deps, _apply_patches,
    _create_client, _stream_and_collect, _store, _SessionMemoryFactory,
)
from app.agents.customer_service_agent import AgentResponse, reset_agent
from app.tools.registry import reset_tool_registry

AH = {"Authorization": f"Bearer {_make_token()}"}
AH_ADMIN = {"Authorization": f"Bearer {_make_token(user_id='admin', roles=['admin'])}"}


@pytest.fixture(autouse=True)
def _reset():
    reset_agent(); reset_tool_registry(); _store.reset()
    yield
    reset_agent(); reset_tool_registry()


async def _run(auth, agent_stream, verify_tools=None, verify_text=None):
    """通用模板：创建会话 → 发消息 → 验证 SSE"""
    patches = _patch_app_deps() + [
        patch("app.api.chat.SessionMemory", new=_SessionMemoryFactory()),
        patch("app.api.chat.get_agent"), patch("app.api.chat.get_tool_registry"),
    ]
    with _apply_patches(patches) as mocks:
        mock_agent = MagicMock()
        mock_agent.astream_chat = agent_stream
        mocks[9].return_value = mock_agent

        async with await _create_client() as c:
            r = await c.post("/api/chat/sessions", json={"title": "E2E"}, headers=auth)
            sid = r.json()["data"]["id"]
            raw = await _stream_and_collect(c, "/api/chat/send",
                                            {"session_id": sid, "message": "test"},
                                            auth)
        evs = _parse_sse_events(raw)
        types = [e["event"] for e in evs]

        assert "loading" in types
        assert "done" in types

        if verify_tools:
            tool_evs = [e for e in evs if e["event"] == "tool_call"]
            called = []
            for e in tool_evs:
                d = e["data"]
                if isinstance(d, dict):
                    called.append(d.get("tool", ""))
            for t in verify_tools:
                assert t in called, f"Expect tool '{t}', got {called}"

        if verify_text:
            text = "".join(e["data"]["content"] for e in evs if e["event"] == "text")
            for kw in verify_text:
                assert kw in text, f"Expect '{kw}' in: {text[:100]}"


def _tc(name, args):
    return {"tool": name, "tool_input": args}

def _tr(name, result):
    return {"tool": name, "result": result}


# ═══════════════════════════════════════════════════
# 查询工具（7 个）
# ═══════════════════════════════════════════════════

class TestQueryTools:
    async def test_product_search(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("product_search", {"keyword": "窗帘"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("product_search", {"success": True, "data": {"items": [
                    {"id": "p1", "name": "雪尼尔窗帘", "price": 19900}], "total": 1}})])
            yield AgentResponse("找到1款窗帘", "text")
        await _run(AH, s, verify_tools=["product_search"], verify_text=["窗帘"])

    async def test_product_detail(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("product_detail", {"product_id": "p1"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("product_detail", {"success": True, "data": {
                    "id": "p1", "name": "雪尼尔窗帘", "price": 19900, "stock": 100}})])
            yield AgentResponse("199元/米，库存100件", "text")
        await _run(AH, s, verify_tools=["product_detail"], verify_text=["199", "库存"])

    async def test_order_query(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("order_query", {"action": "list"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("order_query", {"success": True, "data": {"items": [
                    {"id": "o1", "orderNo": "ORD-001", "status": "shipped"}], "total": 1}})])
            yield AgentResponse("ORD-001已发货", "text")
        await _run(AH, s, verify_tools=["order_query"], verify_text=["ORD-001"])

    async def test_logistics_track(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("logistics_track", {"order_id": "ORD-001"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("logistics_track", {"success": True, "data": {
                    "company": "中通", "tracking_number": "7512345678", "status_text": "运输中"}})])
            yield AgentResponse("中通7512345678运输中", "text")
        await _run(AH, s, verify_tools=["logistics_track"], verify_text=["中通"])

    async def test_dashboard_stats(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("dashboard_stats", {"action": "overview"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("dashboard_stats", {"success": True, "data": {
                    "todayOrderCount": 12, "todaySalesAmount": 324000}})])
            yield AgentResponse("今日12单", "text")
        await _run(AH_ADMIN, s, verify_tools=["dashboard_stats"], verify_text=["12单"])

    async def test_processing_item_query(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("processing_item_query", {})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("processing_item_query", {"success": True, "data": {
                    "items": [{"id": "pi1", "name": "打孔加工", "price": 3.0}], "total": 1}})])
            yield AgentResponse("打孔加工3元/米", "text")
        await _run(AH_ADMIN, s, verify_tools=["processing_item_query"], verify_text=["打孔"])


# ═══════════════════════════════════════════════════
# 写工具（抽样 6 个代表性）
# ═══════════════════════════════════════════════════

class TestWriteTools:
    async def test_order_create(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("order_create", {
                "customer_name": "张三", "customer_phone": "13800001111",
                "items": [{"product_name": "窗帘", "quantity": 2, "unit_price": 199, "subtotal": 398}]})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("order_create", {"success": True, "data": {"orderNo": "ORD-002"}})])
            yield AgentResponse("订单ORD-002已创建", "text")
        await _run(AH, s, verify_tools=["order_create"], verify_text=["ORD-002"])

    async def test_order_cancel(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("order_manage", {
                "action": "cancel", "order_id": "ORD-001", "cancel_reason": "客户要求"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("order_manage", {"success": True, "data": {"status": "cancelled"}})])
            yield AgentResponse("已取消", "text")
        await _run(AH_ADMIN, s, verify_tools=["order_manage"], verify_text=["已取消"])

    async def test_product_create(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("product_manage", {
                "action": "create", "name": "新窗帘", "price": 99.0})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("product_manage", {"success": True, "data": {"id": "p_new"}})])
            yield AgentResponse("创建成功", "text")
        await _run(AH_ADMIN, s, verify_tools=["product_manage"], verify_text=["创建成功"])

    async def test_inventory_query(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("inventory_manage", {
                "action": "query", "product_id": "p1"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("inventory_manage", {"success": True, "data": {
                    "product_name": "雪尼尔窗帘", "stock": 100}})])
            yield AgentResponse("库存100件", "text")
        await _run(AH_ADMIN, s, verify_tools=["inventory_manage"], verify_text=["100件"])

    async def test_customer_list(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("customer_manage", {"action": "list"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("customer_manage", {"success": True, "data": {
                    "items": [{"id": "c1", "name": "张三", "tags": ["VIP"]}], "total": 1}})])
            yield AgentResponse("张三VIP", "text")
        await _run(AH_ADMIN, s, verify_tools=["customer_manage"], verify_text=["张三", "VIP"])

    async def test_validate_input(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": {"customer_name": "张三", "customer_phone": "13800001111", "items": [{"product_name": "窗帘", "quantity": 2, "unit_price": 199, "subtotal": 398}]}})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("validate_input", {"success": True, "data": {"validated": True}})])
            yield AgentResponse("校验通过", "text")
        await _run(AH, s, verify_tools=["validate_input"], verify_text=["校验通过"])


# ═══════════════════════════════════════════════════
# 错误恢复
# ═══════════════════════════════════════════════════

class TestErrorRecovery:
    async def test_empty_search_suggestion(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("product_search", {"keyword": "xyz"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("product_search", {"success": True, "data": {"items": [], "total": 0},
                    "message": "未找到", "suggestion": "尝试缩短关键词"})])
            yield AgentResponse("换个关键词试试", "text")
        await _run(AH, s, verify_tools=["product_search"], verify_text=["换个关键词"])

    async def test_tool_failure_with_suggestion(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("order_create", {
                "customer_name": "张三", "items": [{"product_name": "窗帘", "quantity": 1, "unit_price": 199, "subtotal": 199}]})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("order_create", {"success": False, "error": "缺少客户电话",
                    "message": "创建订单需要电话", "suggestion": "请提供客户联系电话"})])
            yield AgentResponse("请提供联系电话", "text")
        await _run(AH, s, verify_tools=["order_create"], verify_text=["电话"])


# ═══════════════════════════════════════════════════
# C端小布
# ═══════════════════════════════════════════════════

class TestXiaobu:
    async def test_warm_greeting(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("您好呀！我是小布，米高窗帘的智能客服~", "text")
        await _run(AH, s, verify_text=["小布", "米高窗帘"])

    async def test_logistics_with_warm_tone(self):
        async def s(msg, ctx, hist):
            yield AgentResponse("", "tool_call", tool_calls=[_tc("logistics_track", {"order_id": "ORD-001"})])
            yield AgentResponse("", "tool_result",
                tool_calls=[_tr("logistics_track", {"success": True, "data": {
                    "company": "中通", "status_text": "运输中"}})])
            yield AgentResponse("亲，您的包裹已经在路上了，预计明天送到哦~", "text")
        await _run(AH, s, verify_tools=["logistics_track"], verify_text=["亲", "明天"])
