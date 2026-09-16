# case_ids: CH-010, CH-030
"""interact 工具路径的 interactive 载荷必须持久化到消息 metadata（issue #3883）

根因（`app/api/chat.py::_agent_stream_to_sse`）：
- LLM 幻觉 `<interact>` XML 分支（issue #3036 / UI-032）会设置
  `last_interactive_payload` → 收尾 `save_message(interactive=…)` 落库
  → 刷新/重开会话后确认/选择/表单卡仍在、`interactive_answered` 可标记；
- 但 **interact 工具正常路径**只 `yield SSEEvent.interactive(...)`，没有设置
  `last_interactive_payload` → 收尾永远 `None` → metadata 无 interactive 键
  → 卡片刷新即消失、只读锁也无从标记（#3883）。

本测试钉住：interact 工具结果（choice/confirm/form）必须与 XML 分支同协议，
把工具 `data` 写入 `save_message` 的 interactive 参数，且逐字段一致（透传）。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.chat import _agent_stream_to_sse
from app.agents.customer_service_agent import AgentContext, AgentResponse


def _ctx(role="customer"):
    return AgentContext(user_id="u1", tenant_id=1, session_id="s1", role=role)


def _agent_with(*responses):
    agent = MagicMock()
    agent._agent_type = "xiaobu"

    async def astream(*a, **kw):
        for r in responses:
            yield r

    agent.astream_chat = astream
    return agent


def _memory():
    sm = AsyncMock()
    sm.save_message = AsyncMock(return_value="msg_1")
    return sm


def _interact_tool_result(data, success=True):
    return AgentResponse(
        content="",
        type="tool_result",
        tool_calls=[{
            "tool": "interact",
            "result": {"success": success, "data": data},
        }],
    )


async def _collect(responses):
    """跑完整个 _agent_stream_to_sse，返回 (SSE 事件列表, session_memory mock)"""
    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        sm = _memory()
        events = [e async for e in _agent_stream_to_sse(
            agent=_agent_with(*responses),
            message="下单", context=_ctx(), chat_history=[],
            tool_registry=MagicMock(), session_memory=sm,
            session_id="s1", tenant_id=1, user_id="u1",
        )]
    return events, sm


CHOICE_DATA = {
    "component": "choice",
    "title": "请选择支付方式",
    "options": [
        {"label": "微信支付", "value": "wechat"},
        {"label": "余额支付", "value": "balance"},
    ],
}

CONFIRM_DATA = {
    "component": "confirm",
    "title": "请确认订单信息",
    "fields": [
        {"label": "商品", "value": "遮光窗帘"},
        {"label": "合计", "value": "¥528"},
    ],
    "confirmLabel": "确认下单",
    "cancelLabel": "再改改",
    "confirmValue": "确认：商品=遮光窗帘",
}

FORM_DATA = {
    "component": "form",
    "title": "新建商品",
    "formFields": [
        {"key": "name", "label": "商品名称", "value": "常青藤", "required": True},
        {"key": "price", "label": "单价", "placeholder": "请输入单价"},
    ],
    "submitLabel": "提交",
}


class TestInteractToolPayloadPersisted:
    @pytest.mark.parametrize("data", [CHOICE_DATA, CONFIRM_DATA, FORM_DATA],
                             ids=["choice", "confirm", "form"])
    @pytest.mark.asyncio
    async def test_payload_persisted_to_metadata(self, data):
        """interact 工具结果必须像 XML 分支一样写入 save_message.interactive。"""
        events, sm = await _collect([_interact_tool_result(data)])
        body = "".join(events)
        assert "event: interactive" in body
        sm.save_message.assert_awaited_once()
        kwargs = sm.save_message.await_args.kwargs
        assert kwargs.get("interactive") == data, \
            "interact 工具路径 interactive 载荷未持久化（issue #3883）"

    @pytest.mark.asyncio
    async def test_confirm_fields_passthrough(self):
        """落库载荷与工具 data 逐字段一致（component/title/fields/confirmValue 透传）。"""
        _, sm = await _collect([_interact_tool_result(CONFIRM_DATA)])
        payload = sm.save_message.await_args.kwargs.get("interactive")
        assert payload["component"] == "confirm"
        assert payload["title"] == "请确认订单信息"
        assert payload["fields"] == CONFIRM_DATA["fields"]
        assert payload["confirmValue"] == "确认：商品=遮光窗帘"

    @pytest.mark.asyncio
    async def test_interactive_event_payload_matches_saved(self):
        """SSE interactive 事件与落库载荷同源：data: 里能解析出 component/title。"""
        events, sm = await _collect([_interact_tool_result(CHOICE_DATA)])
        saved = sm.save_message.await_args.kwargs.get("interactive")
        event_line = next(e.split("data: ", 1)[1] for e in events
                          if e.startswith("event: interactive"))
        event_payload = json.loads(event_line)
        assert saved["component"] == "choice"
        assert event_payload["component"] == "choice"
        assert event_payload["title"] == "请选择支付方式"

    @pytest.mark.asyncio
    async def test_failed_interact_not_persisted(self):
        """success=False 时不发 interactive 事件、也不写 interactive 元数据。"""
        events, sm = await _collect([_interact_tool_result(dict(CONFIRM_DATA), success=False)])
        body = "".join(events)
        assert "event: interactive" not in body
        sm.save_message.assert_awaited_once()
        assert sm.save_message.await_args.kwargs.get("interactive") is None
