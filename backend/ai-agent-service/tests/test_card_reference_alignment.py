"""B 端米宝 product_list 卡片引用对齐测试（issue #3009 / case PR-018）。

背景（sess_66c12e3cf3a14ee0 复盘）：
用户问「查一下低库存商品的具体清单」，LLM 文本正确筛出 5 件低库存商品，
但 AI 气泡下方渲染了 2 页 × 10 张原始返回的商品卡——卡片内容是工具原始
返回（未过滤），与 LLM 文本的最终口径不一致（两层皮）。

方案 B（引用对齐）：
- mibao（B 端）：tool_result 阶段不发 product_list 卡片，延迟到 LLM 文本
  流结束后，按文本中实际引用的商品名/ID 过滤，只发被引用的商品；
  文本未引用任何商品 → 不下发卡片（宁可无卡，不误导）。
- xiaobu（C 端）：保持现状，product_search 有结果即发全量卡片
  （货架浏览体验不回退）。
"""
# case_ids: PR-018

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.chat import _filter_products_by_reference, _agent_stream_to_sse
from app.agents.customer_service_agent import AgentContext, AgentResponse


def _ctx(role="admin"):
    return AgentContext(user_id="u1", tenant_id=1, session_id="s1", role=role)


def _agent_with(*responses, agent_type="xiaobu"):
    agent = MagicMock()
    agent._agent_type = agent_type

    async def astream(*a, **kw):
        for r in responses:
            yield r

    agent.astream_chat = astream
    return agent


def _memory():
    sm = AsyncMock()
    sm.save_message = AsyncMock(return_value="msg_1")
    return sm


def _product(pid, name):
    return {"id": pid, "name": name, "price": 10, "stock": 5}


def _tool_result(tool, products, page=1):
    return AgentResponse(
        content="",
        type="tool_result",
        tool_calls=[{
            "tool": tool,
            "result": {
                "success": True,
                "data": {
                    "products": products,
                    "total": len(products),
                    "page": page,
                    "size": 10,
                },
            },
        }],
    )


async def _collect_events(responses, agent_type="mibao"):
    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        events = [e async for e in _agent_stream_to_sse(
            agent=_agent_with(*responses, agent_type=agent_type),
            message="查一下低库存商品的具体清单",
            context=_ctx(),
            chat_history=[],
            tool_registry=MagicMock(),
            session_memory=_memory(),
            session_id="s1", tenant_id=1, user_id="u1",
        )]
    return events


def _card_payloads(events):
    """提取 card 事件的 (type, data) 列表"""
    out = []
    for e in events:
        if e.startswith("event: card"):
            payload = json.loads(e.split("data: ", 1)[1])
            out.append(payload)
    return out


# ═══════════════════════════════════════════════
# 纯函数：引用过滤
# ═══════════════════════════════════════════════

class TestFilterProductsByReference:
    def test_keeps_name_referenced_in_content(self):
        products = [
            _product("p1", "E2E最简_89358"),
            _product("p2", "V2574_删除测试_onsale"),
            _product("p3", "P0-1回归-30447"),
        ]
        content = "库存偏低：E2E最简_89358、V2574_删除测试_onsale"
        kept = _filter_products_by_reference(content, products)
        names = [p["name"] for p in kept]
        assert names == ["E2E最简_89358", "V2574_删除测试_onsale"]

    def test_keeps_id_referenced_in_content(self):
        products = [_product("p_abc", "雪尼尔遮光帘"), _product("p_def", "棉麻纱帘")]
        kept = _filter_products_by_reference("商品 p_abc 库存告急", products)
        assert [p["id"] for p in kept] == ["p_abc"]

    def test_no_reference_returns_empty(self):
        products = [_product("p1", "A商品"), _product("p2", "B商品")]
        assert _filter_products_by_reference("没有任何商品被提及", products) == []

    def test_empty_content_returns_empty(self):
        products = [_product("p1", "A商品")]
        assert _filter_products_by_reference("", products) == []

    def test_handles_products_passed_by_data_container(self):
        """兼容 card.data 整体（{products: [...]}）与裸数组两种入参"""
        products = [_product("p1", "遮光窗帘")]
        data = {"products": products, "total": 1}
        kept = _filter_products_by_reference("遮光窗帘", data)
        assert len(kept) == 1


# ═══════════════════════════════════════════════
# SSE 集成：mibao 引用对齐
# ═══════════════════════════════════════════════

class TestMibaoReferenceAlignedCards:
    @pytest.mark.asyncio
    async def test_text_only_referenced_products_render(self):
        """文本引用 2 件 → product_list 卡片只含这 2 件"""
        all_products = [
            _product("p1", "E2E最简_89358"),
            _product("p2", "E2E最简_10846"),
            _product("p3", "V2574_删除测试_onsale"),
            _product("p4", "P0-1回归-30447"),
            _product("p5", "V2574_产品_upsert验证2"),
        ]
        responses = [
            AgentResponse(content="我来查询低库存商品。", type="text"),
            _tool_result("product_search", all_products),
            AgentResponse(content="库存偏低的商品：E2E最简_89358（0件）、P0-1回归-30447（50件）。", type="text"),
        ]
        events = await _collect_events(responses, agent_type="mibao")
        cards = _card_payloads(events)
        assert len(cards) == 1
        assert cards[0]["type"] == "product_list"
        names = [p["name"] for p in cards[0]["data"]["products"]]
        assert names == ["E2E最简_89358", "P0-1回归-30447"]

    @pytest.mark.asyncio
    async def test_no_reference_sends_no_card(self):
        """文本未引用任何商品 → 不下发 product_list 卡片"""
        responses = [
            AgentResponse(content="正在查询……", type="text"),
            _tool_result("product_search", [_product("p1", "雪尼尔遮光帘")]),
            AgentResponse(content="查询完成，库存整体正常。", type="text"),
        ]
        events = await _collect_events(responses, agent_type="mibao")
        assert _card_payloads(events) == []

    @pytest.mark.asyncio
    async def test_two_pages_each_filtered_by_reference(self):
        """两页返回各自过滤：页1 引用 1 件、页2 引用 1 件 → 两张卡各含一件"""
        page1 = [_product("p1", "E2E最简_89358"), _product("p2", "E2E最简_10846")]
        page2 = [_product("p3", "V2574_删除测试_onsale"), _product("p4", "P0-1回归-30447")]
        responses = [
            AgentResponse(content="", type="tool_call", tool_calls=[{"tool": "product_search", "tool_input": {"page": 1}}]),
            _tool_result("product_search", page1, page=1),
            AgentResponse(content="", type="tool_call", tool_calls=[{"tool": "product_search", "tool_input": {"page": 2}}]),
            _tool_result("product_search", page2, page=2),
            AgentResponse(content="告急商品：E2E最简_89358、P0-1回归-30447。", type="text"),
        ]
        events = await _collect_events(responses, agent_type="mibao")
        cards = _card_payloads(events)
        assert len(cards) == 2
        all_names = [p["name"] for c in cards for p in c["data"]["products"]]
        assert all_names == ["E2E最简_89358", "P0-1回归-30447"]

    @pytest.mark.asyncio
    async def test_order_card_not_deferred(self):
        """非 product_list 卡片（order）不受引用对齐影响，照常发送"""
        responses = [
            AgentResponse(
                content="", type="tool_result",
                tool_calls=[{
                    "tool": "order_query",
                    "result": {"success": True, "data": {"order": {"id": "o1", "order_no": "ORD-1"}}},
                }],
            ),
            AgentResponse(content="找到订单 ORD-1。", type="text"),
        ]
        events = await _collect_events(responses, agent_type="mibao")
        cards = _card_payloads(events)
        assert len(cards) == 1
        assert cards[0]["type"] == "order"


# ═══════════════════════════════════════════════
# SSE 集成：xiaobu 保持现状（不回归）
# ═══════════════════════════════════════════════

class TestXiaobuKeepsFullCards:
    @pytest.mark.asyncio
    async def test_xiaobu_sends_all_products_unfiltered(self):
        """小布：product_search 有结果即发全量卡片（货架浏览）"""
        products = [_product("p1", "雪尼尔遮光帘"), _product("p2", "棉麻纱帘")]
        responses = [
            _tool_result("product_search", products),
            AgentResponse(content="为您找到 2 款窗帘：雪尼尔遮光帘、棉麻纱帘。", type="text"),
        ]
        events = await _collect_events(responses, agent_type="xiaobu")
        cards = _card_payloads(events)
        assert len(cards) == 1
        assert len(cards[0]["data"]["products"]) == 2