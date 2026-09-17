# case_ids: API-002
"""展示卡卡型落库：`metadata.cards` = 本轮**真实发出**的卡型（issue #4016 A15 前置）。

## 为什么先补落库（而不是先裁卡片）

审计实测（#4016「一」/「六」）：展示卡**完全不落库** —— 全库 `session_messages.metadata`
里 `cards` 键出现 **0** 次，卡片只走 SSE、流完即忘。后果有两层：

1. **裁剪没有数据基础**：想问「哪种卡被真实使用」只能靠猜，而 `#4016` 的方向恰恰是
   「以实测为依据裁剪、不凭感觉」；
2. **与 `interactive` 不对称**：`interactive` 载荷早已通过 `save_message(interactive=…)`
   落库并被 `get_history` 回传（issue #3036 / #3883，见 `test_interact_payload_persist.py`），
   展示卡却是**只写不读**的空缺 —— 刷新/重开会话后卡片消失（#3883 对交互卡修的正是这个）。

## 落库口径（判据的三条硬约束）

1. **事实驱动**：写入的卡型**只能**来自 `_card_payload` 真正下发的那一个值 ——
   落库集合必须与 SSE 上 `event: card` 的卡型集合**逐字相等**（本文 `test_persisted_types_equal_emitted_types`），
   不许出现「声称发卡但没发」（#3970 同族）或「发了却没记」。
2. **只记真实使用**：B 端米宝的 `product_list` 走**引用对齐**延迟发卡 ——
   若最终文本没引用任何商品，卡片被**丢弃**（chat.py「宁可无卡，不误导」），
   此时**不得**记成一次 `product_list` 使用（否则用量统计被虚高的 pending 卡污染，
   而统计正是本项要支撑的产出）。
3. **不新增静默失效**：无卡轮次不写 `cards` 键（不是写空列表）—— 与 `interactive` 同形
   （`if interactive:` 才写），使「有卡轮次」在 SQL 里可直接用 `metadata ? 'cards'` 圈出。

## 红证

改前（本文件与之对应的实现尚未落地时）：`save_message` 的 `extra_metadata` 恒为 `None`
⇒ `test_emitted_card_type_persisted_to_metadata` 红（实测 `assert None == {'cards': ['order']}`）。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.chat import _agent_stream_to_sse
from app.agents.customer_service_agent import AgentContext, AgentResponse


def _ctx(role="customer"):
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


def _tool_result(tool, data, success=True):
    return AgentResponse(
        content="",
        type="tool_result",
        tool_calls=[{"tool": tool, "result": {"success": success, "data": data}}],
    )


def _text(content):
    return AgentResponse(content=content, type="text")


async def _collect(responses, agent_type="xiaobu"):
    """跑完整个 `_agent_stream_to_sse`，返回 (SSE 事件列表, session_memory mock)。"""
    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        sm = _memory()
        events = [e async for e in _agent_stream_to_sse(
            agent=_agent_with(*responses, agent_type=agent_type),
            message="查一下", context=_ctx(), chat_history=[],
            tool_registry=MagicMock(), session_memory=sm,
            session_id="s1", tenant_id=1, user_id="u1",
        )]
    return events, sm


def _emitted_card_types(events):
    """SSE 上真实下发的卡型（真值，非落库副本）—— 与落库值对账用。"""
    return [
        json.loads(e.split("data: ", 1)[1])["type"]
        for e in events if e.startswith("event: card")
    ]


def _persisted_cards(sm):
    return (sm.save_message.await_args.kwargs.get("extra_metadata") or {}).get("cards")


ORDER = {"id": "o-1", "orderNo": "ORD-001", "status": "confirmed", "totalAmount": 128.0}
LOGISTICS = {"tracking_number": "SF1234567890", "status": "运输中"}

# 生产进度卡载荷：`production_progress_query` 成功时返回的正是这个形状
# （progress_percent / current_operation / expected_delivery_date，见该工具第 171 行）
PRODUCTION_PROGRESS = {
    "order_id": "CSO260915-02615",
    "order_no": "CSO260915-02615",
    "status": "producing",
    "progress_percent": 40,
    "current_operation": "韩褶",
    "pending_operations": ["韩褶", "定型", "打包"],
    "expected_delivery_date": "2026-09-25",
}
# 无加工单的**合法**返回（success=true、0%/空工序）—— UI-045 要求此时仍展示卡（「暂无生产进度」）
PRODUCTION_PROGRESS_EMPTY = {"order_no": "EVAL-ORD-0002", "progress_percent": 0, "positions": []}


class TestCardTypePersisted:
    @pytest.mark.asyncio
    async def test_emitted_card_type_persisted_to_metadata(self):
        """真实发出的卡型必须落库（A15：裁剪的用量数据基础）。"""
        events, sm = await _collect([_tool_result("order_query", {"order": ORDER})])
        assert _emitted_card_types(events) == ["order"], "前置：本轮确实发出了 order 卡"
        assert _persisted_cards(sm) == ["order"], (
            "展示卡卡型未落库（metadata.cards 缺失）—— 用量统计无数据基础（#4016 A15）"
        )

    @pytest.mark.asyncio
    async def test_persisted_types_equal_emitted_types(self):
        """事实驱动：落库集合与 SSE 卡型集合**逐字相等**（不多记、不漏记）。"""
        events, sm = await _collect([
            _tool_result("order_query", {"order": ORDER}),
            _tool_result("logistics_track", LOGISTICS),
        ])
        assert _persisted_cards(sm) == _emitted_card_types(events) == ["order", "logistics"]

    @pytest.mark.asyncio
    async def test_no_card_turn_writes_no_cards_key(self):
        """负例（R2）：没发卡的轮次不得凭空产生 cards 记录或空壳列表。"""
        events, sm = await _collect([_tool_result("product_search", {"products": []})])
        assert _emitted_card_types(events) == [], "前置：空结果不发卡"
        extra = sm.save_message.await_args.kwargs.get("extra_metadata")
        assert _persisted_cards(sm) is None, f"无卡轮次不该有 cards 记录：{extra}"
        assert "cards" not in (extra or {}), "无卡轮次写空列表会让统计多出空档（口径不一致）"

    @pytest.mark.asyncio
    async def test_duplicate_card_types_recorded_once(self):
        """同一轮重复发同型卡（两次 product_search）只记一次类型（统计口径 = 类型维度）。"""
        events, sm = await _collect([
            _tool_result("product_search", {"products": [{"id": "p1", "name": "常青藤"}]}),
            _tool_result("product_search", {"products": [{"id": "p2", "name": "遮光帘"}]}),
        ])
        assert _emitted_card_types(events) == ["product_list", "product_list"]
        assert _persisted_cards(sm) == ["product_list"]

    @pytest.mark.asyncio
    async def test_production_progress_card_emitted_and_persisted(self):
        """**端到端那一格**（#4016 P14 用户 2026-09-18 裁定「补发射点」）：

        工具结果 → 真的发出 `event: card`（type=production_progress）→ 真的落进
        `metadata.cards`。证明的是「能力**可达**」，不是「后端函数能返回一个字符串」——
        后者正是本单的病根（卡片交付在 main、组件永不渲染）。
        """
        events, sm = await _collect(
            [_tool_result("production_progress_query", PRODUCTION_PROGRESS)]
        )
        assert _emitted_card_types(events) == ["production_progress"], (
            "工具结果没有发出生产进度卡 ⇒ 发射点没接上（组件仍然永不渲染）"
        )
        # 载荷就是工具返回的 data（事实驱动，无中间改写）
        card_payload = json.loads(
            next(e.split("data: ", 1)[1] for e in events if e.startswith("event: card"))
        )
        assert card_payload["type"] == "production_progress"
        assert card_payload["data"]["progress_percent"] == 40
        assert _persisted_cards(sm) == ["production_progress"], (
            "该卡型未落 metadata.cards ⇒ 用量统计仍看不到它"
        )

    @pytest.mark.asyncio
    async def test_production_progress_empty_state_still_sends_card(self):
        """空态也要发卡（R2 负例）：无加工单是**合法**结果，卡里显示「暂无生产进度」。

        判据不能用「有工序」——`production_progress_query` 对无加工单的订单**同样 success=true**
        （0%/空工序）。若按「有工序」判据，UI-045 的空态要求（不空白、不显示假进度）永远看不到卡。
        """
        events, sm = await _collect(
            [_tool_result("production_progress_query", PRODUCTION_PROGRESS_EMPTY)]
        )
        assert _emitted_card_types(events) == ["production_progress"]
        assert _persisted_cards(sm) == ["production_progress"]

    @pytest.mark.asyncio
    async def test_failed_production_progress_sends_no_card(self):
        """失败不发卡（R2 负例）：success=False 时既无卡事件、也无 cards 记录（无假进度）。"""
        events, sm = await _collect(
            [_tool_result("production_progress_query", {}, success=False)]
        )
        assert _emitted_card_types(events) == []
        assert _persisted_cards(sm) is None

    @pytest.mark.asyncio
    async def test_dropped_reference_aligned_card_is_not_counted(self):
        """只记**真实使用**：B 端引用对齐丢弃的 pending 卡不算一次 product_list 使用。

        米宝 `product_search` 走延迟发卡，最终文本未引用任何商品 ⇒ 卡片被丢弃
        （chat.py「未引用任何商品 → 不发卡（宁可无卡，不误导）」）。
        此时若把 pending 记成已用，用量统计就被「发了又被丢掉」的卡污染。
        """
        events, sm = await _collect(
            [_tool_result("product_search", {"products": [{"id": "p1", "name": "常青藤"}]})],
            agent_type="mibao",
        )
        assert _emitted_card_types(events) == [], "前置：未被文本引用的商品卡必须被丢弃"
        assert _persisted_cards(sm) is None, (
            "被丢弃的引用对齐卡被记成了 product_list 使用 —— 用量统计失真"
        )