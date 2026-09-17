"""会话记录区分「工具调了」与「工具成了」—— 落库 metadata.tool_results（issue #4052）。

背景（实测 @8cca7664）：`app/api/chat.py` 里 `grep -c tool_results` = **0** ——
落库的只有 `metadata.tool_calls`（工具名 + args，即「调了什么」）；工具的**结果**
只在 SSE 里 `SSEEvent.tool_result(...)` 发给前端、**从不落库**。
⇒ DB `session_messages.metadata` 无法区分「调了 order_create」与「order_create 真落库」，
事后取证/回放/门禁只能拿到「调用了谁」，拿不到「成没成」。

判据（本文件即红证）：从**真 SSE 桥** `_agent_stream_to_sse` 出发，跑**真**
`SessionMemory.save_message`（只把 DB 会话换成记录 SQL 入参的替身），断言**落库 metadata 的内容**：
① 失败调用与成功调用的落库 metadata 不再同形；② `tool_results[i]` 与 `tool_calls[i]` 逐项对齐，
同名工具同回合多次调用时**逐次**配对（不合并/不塌缩）；③ 未执行的调用（`tool_not_found`，见 #3976）
既不进 `tool_calls` 也不进 `tool_results`；④ 只落元信息三键（无 `data` 载荷/用户 PII，
`error` 文本先过既有脱敏层）。
红证形态（改前）：metadata 里**没有** `tool_results` 键 ⇒ 上述断言全红，且一次失败调用与
一次成功调用的 metadata **完全一样**（`tool_calls` 相同 ⇒ 落库字节相同）。

case_ids 选择理由：
  · CH-010（chat.yml「选购下单表单化交互」）：该用例注释记录的正是本缺陷的假绿形态 ——
    「order_create 两次都返回 tool_execution_failed，订单一条没落，用例却因
    『工具名出现在 tool_calls』判 100%」（#3361/#3778）。本改动是它在**会话记录**侧的对应判据。
  · CH-011（chat.yml「数据安全 - 跨用户订单查询拒绝 + 订单卡片手机号脱敏」）：
    结果元信息随 metadata 进历史回放，脱敏约束（不放载荷/PII）由该用例代言。
"""
# case_ids: CH-010, CH-011

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


class _CapturingDb:
    """DB 会话替身：只替**存储层**，`SessionMemory.save_message` 本体照跑。"""

    def __init__(self):
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.params.append(params or {})
        return MagicMock()

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _resp(kind, *, tool=None, tool_input=None, result=None, content=""):
    """构造 AgentResponse（懒 import：沿用仓库「用例内 import app.*」惯例）。"""
    from app.agents.customer_service_agent import AgentResponse

    if kind in ("tool_call", "tool_result"):
        payload = ({"tool_input": tool_input} if kind == "tool_call"
                   else {"result": result})
        return AgentResponse(type=kind, content="", tool_calls=[{"tool": tool, **payload}])
    return AgentResponse(type=kind, content=content)


def _persisted_metadata(events, *, role="admin", message="确认下单"):
    """真 SSE 桥 → 真 save_message → 返回**落库那条消息**的 metadata（已反序列化）。

    断言对象是「DB 拿到的 metadata 字符串」的内容，而不是替身记下的调用入参 ——
    后者只能证明"传了参数"，证明不了"落库成什么样"。
    """
    from app.agents.customer_service_agent import AgentContext
    from app.api.chat import _agent_stream_to_sse
    from app.memory.session_memory import SessionMemory

    db = _CapturingDb()
    memory = SessionMemory(db_session=db)

    class _Agent:
        _agent_type = "mibao"

        async def astream_chat(self, msg, ctx, history):
            for ev in events:
                yield ev

    context = AgentContext(user_id="u1", tenant_id=1, session_id="sess-4052",
                           role=role, identity_type=role)

    async def _collect():
        return [c async for c in _agent_stream_to_sse(
            _Agent(), message, context, [], MagicMock(), memory,
            "sess-4052", 1, "u1")]

    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        chunks = asyncio.run(_collect())

    inserts = [p for p in db.params if "metadata" in p]
    assert len(inserts) == 1, f"应有且仅有一条 assistant 消息落库: {db.params}"
    raw = inserts[0]["metadata"]
    assert isinstance(raw, str) and raw, f"metadata 必须是落库用的 JSON 字符串: {raw!r}"
    assert chunks, "SSE 流不得为空（本轮必须真的跑过桥）"
    return json.loads(raw)


class TestToolResultsPersisted:
    """落库 metadata 必须能区分「调了」与「成了」（issue #4052 的核判据）。"""

    def test_failure_and_success_records_are_distinguishable(self):
        """红证：只有一次调用时，失败记录与成功记录的 metadata 必须不同。

        改前两者 metadata **逐字节相同**（`tool_calls` 只记工具名 + args，
        两次调用的 args 一致 ⇒ 落库内容一致）—— 取证时无法区分订单是否真落库。
        """
        failed = _persisted_metadata([
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "甲"}),
            _resp("tool_result", tool="order_create",
                  result={"success": False, "error": "tool_execution_failed",
                          "message": "工具执行失败，请稍后重试"}),
            _resp("text", content="很抱歉，这单没建成。"),
        ])
        succeeded = _persisted_metadata([
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "甲"}),
            _resp("tool_result", tool="order_create",
                  result={"success": True, "data": {"order_no": "2026091700001"}}),
            _resp("text", content="订单已建好。"),
        ])
        assert failed.get("tool_results"), (
            f"落库 metadata 缺 tool_results ⇒ 区分不出「调了」与「成了」: {failed}")
        assert failed["tool_results"] == [
            {"tool": "order_create", "success": False, "error": "tool_execution_failed"},
        ], f"失败的调用必须落成 success=False + 错误码: {failed['tool_results']}"
        assert succeeded["tool_results"] == [
            {"tool": "order_create", "success": True, "error": None},
        ], f"成功的调用必须落成 success=True 且无错误码: {succeeded['tool_results']}"
        assert failed != succeeded, (
            f"失败与成功两条会话记录必须可区分（改前两者完全相同）: {failed}")

    def test_same_tool_called_twice_records_one_result_per_call(self):
        """同名工具一回合调两次：两条结果**逐次**配对，不塌缩成一条。

        结果按到达顺序与同名调用 FIFO 配对（生产端 `astream_chat` 按 ToolMessage
        顺序补发 tool_result）—— 塌缩/错位都会让「哪一次成了」不可判。
        """
        meta = _persisted_metadata([
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "甲"}),
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "乙"}),
            _resp("tool_result", tool="order_create",
                  result={"success": False, "error": "tool_execution_failed"}),
            _resp("tool_result", tool="order_create",
                  result={"success": True, "data": {"order_no": "2026091700001"}}),
            _resp("text", content="已为您处理。"),
        ])
        calls = meta.get("tool_calls") or []
        results = meta.get("tool_results") or []
        assert len(calls) == 2, f"同名两次调用都要留在 tool_calls: {calls}"
        assert len(results) == 2, f"每次调用各一条结果（不合并）: {results}"
        assert [r["tool"] for r in results] == ["order_create", "order_create"]
        assert results[0]["success"] is False, f"第 1 次调用失败: {results[0]}"
        assert results[1]["success"] is True, f"第 2 次调用成功: {results[1]}"

    def test_not_found_call_is_neither_call_nor_result(self):
        """#3976 同口径：未执行的调用（`tool_not_found`）不得被记成「执行结果」。

        同名两次调用时还须证明**剔除的是与本次结果配对的那一次**（首条）——
        否则 `tool_results` 会与 `tool_calls` 错位：结果说「成了」，
        却配到那条**从未执行**的调用上。
        """
        meta = _persisted_metadata([
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "甲"}),
            _resp("tool_call", tool="order_create", tool_input={"customer_name": "乙"}),
            _resp("tool_result", tool="order_create",
                  result={"success": False, "error": "tool_not_found",
                          "message": "工具 order_create 不可用"}),
            _resp("tool_result", tool="order_create",
                  result={"success": True, "data": {"order_no": "2026091700001"}}),
            _resp("text", content="已为您处理。"),
        ])
        calls = meta.get("tool_calls") or []
        results = meta.get("tool_results") or []
        assert len(calls) == 1, f"未执行的调用必须从 tool_calls 剔除（#3976）: {calls}"
        assert calls[0]["args"] == {"customer_name": "乙"}, (
            f"剔除的必须是与 tool_not_found 结果配对的那一次（首条）: {calls}")
        assert results == [{"tool": "order_create", "success": True, "error": None}], (
            f"未执行的调用不得记成执行结果，且剩余结果须与剩余调用对齐: {results}")

    def test_result_without_call_event_is_recorded_and_keeps_pairing(self):
        """代码收口执行（#3410/#3976）：结果**没有**对应的 tool_call 事件时照样落库。

        `base_skill` 8.4 在「模型确认后不动手」时代码直接执行写工具（实证 #3976 的
        B 端订单即此路径）—— 它只产出 ToolMessage（⇒ 只有 tool_result 事件），
        没有 AIMessage tool_calls（⇒ 没有 tool_call 事件）。语义分工：
        `tool_calls` = **模型发起**的调用；`tool_results` = **实际执行**的结果。
        关键是不能因为"没配到调用"就丢结果，也不能挤掉同名调用的配对位。
        """
        meta = _persisted_metadata([
            _resp("tool_call", tool="product_search", tool_input={"keyword": "窗帘"}),
            _resp("tool_result", tool="product_search", result={"success": True, "data": {}}),
            _resp("tool_result", tool="order_create",
                  result={"success": True, "data": {"order_no": "2026091700001"}}),
            _resp("text", content="已为您处理。"),
        ])
        assert meta.get("tool_results") == [
            {"tool": "product_search", "success": True, "error": None},
            {"tool": "order_create", "success": True, "error": None},
        ], f"收口执行的结果不得丢，且不得挤掉同名调用的配对位: {meta.get('tool_results')}"
        assert [c["tool"] for c in (meta.get("tool_calls") or [])] == ["product_search"], (
            f"收口执行不是模型发起的调用 ⇒ 不进 tool_calls: {meta.get('tool_calls')}")

    def test_result_metadata_has_no_payload_and_masks_pii(self):
        """只落元信息三键：无 `data` 载荷；`error` 文本先过既有脱敏层（C 端）。

        注意作用域：`tool_calls.args` 里本就带原始入参（既有行为，本改动不扩也不缩），
        这里断言的是**新增的 `tool_results`** 不带载荷、不带未脱敏 PII。
        """
        meta = _persisted_metadata([
            _resp("tool_call", tool="notification_manage",
                  tool_input={"action": "send", "phone": "13800138000"}),
            _resp("tool_result", tool="notification_manage",
                  result={"success": False, "error": "手机号 13800138000 无法送达",
                          "message": "顾客 张三 的通知发送失败",
                          "data": {"customer_phone": "13800138000", "customer_name": "张三"}}),
            _resp("text", content="通知发送失败。"),
        ], role="customer")
        results = meta.get("tool_results") or []
        assert len(results) == 1, f"失败但**执行过**的调用必须有结果元信息: {results}"
        entry = results[0]
        assert set(entry) == {"tool", "success", "error"}, (
            f"只允许元信息三键（data/message 载荷一律不进 metadata）: {entry}")
        assert entry["success"] is False
        blob = json.dumps(entry, ensure_ascii=False)
        assert "13800138000" not in blob, f"用户 PII 必须先过脱敏层: {blob}"
        assert "张三" not in blob, f"data 载荷不得进 metadata: {blob}"