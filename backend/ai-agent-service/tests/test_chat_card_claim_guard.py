# case_ids: PR-014, PR-017
"""文本声称有确认卡但未发卡时，改写为纯文本确认指引（issue #3929）。

生产实证（B 端米宝 agent，主模型 deepseek-flash，会话 sess_2efa2071bb1747d8，
2026-09-15）：模型经常在文本里说「请点下方确认卡片 / 确认无误请点下方卡片，
我立即写入」，但该回合根本没调 interact 工具 → SSE 无 interactive 事件 →
客户看不到卡、没有可点击按钮。用户 19:43:57 直接问「为什么我看不到？
下方卡片在哪里？」。对照：真正发出的卡（interact 被调用的回合）用户全部点到了
→ 渲染无问题，问题是**发卡缺失**。

已有防线为何漏：
- #3045 确认卡片铁律是 prompt 级规则（PROMPT-rules.md），flash 模型仍漏；
- #3445/#3882 的代码兜底在 base_skill.py 8.3b，只覆盖「模型先写单被
  confirmation_required_no_card 门禁拦回」的形态——本会话模型根本没尝试写，
  只嘴上请确认，该兜底不触发。

本测试钉住 chat.py 收尾守卫（_agent_stream_to_sse，save_message 之前）：
- `_rewrite_card_claims`（纯函数）：卡片声称片段 →「回复『确认』」纯文本指引，
  其余文本保留；#3883 的「刷新页面/重新进入对话」误导性建议一并剥离；
- `_agent_stream_to_sse` 层面联动：仅当无交互载荷且本轮无 interact 调用时才改写；
  有载荷 / 有 interact 调用（哪怕失败）→ 原样落库（负例：19:49:22 真实发出的
  confirm 卡消息不得被误改）。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.chat import _agent_stream_to_sse, _rewrite_card_claims
from app.agents.customer_service_agent import AgentContext, AgentResponse


# 生产会话逐字文本（重放证据，sess_2efa2071bb1747d8）
CLAIM_CREATE = "确认无误请点下方确认卡片，我立即创建。"
CLAIM_WRITE = "确认无误请点下方卡片，我立即写入。"
CLAIM_SET = "确认无误请点下方卡片，我立即设置。"
MISLEAD = "（卡片一般在消息下方显示，也可以试试刷新页面或重新进入对话。）"
# 守卫追加的直播气泡提示（并入同一条消息气泡末尾，done 之前）
STREAM_NOTE = "（注：确认卡片未显示，请直接回复「确认」以继续）"


class TestRewriteCardClaims:
    """纯函数层：声称片段改写 + 误导性建议剥离（判别性用例 = 生产逐字文本）。"""

    def test_claim_create_rewritten(self):
        rewritten = _rewrite_card_claims(CLAIM_CREATE)
        assert rewritten == "确认无误请回复『确认』，我立即创建。", rewritten
        assert "点下方" not in rewritten and "确认卡片" not in rewritten
        assert "回复『确认』" in rewritten

    def test_claim_write_rewritten(self):
        rewritten = _rewrite_card_claims(CLAIM_WRITE)
        assert rewritten == "确认无误请回复『确认』，我立即写入。", rewritten
        assert "点下方" not in rewritten and "确认卡片" not in rewritten
        assert "回复『确认』" in rewritten

    def test_claim_set_rewritten(self):
        rewritten = _rewrite_card_claims(CLAIM_SET)
        assert rewritten == "确认无误请回复『确认』，我立即设置。", rewritten
        assert "点下方" not in rewritten and "确认卡片" not in rewritten
        assert "回复『确认』" in rewritten

    def test_misleading_refresh_advice_stripped(self):
        rewritten = _rewrite_card_claims(MISLEAD)
        assert rewritten == "", rewritten
        assert "刷新页面" not in rewritten and "重新进入对话" not in rewritten

    def test_claim_and_misleading_advice_both_handled(self):
        text = CLAIM_SET + MISLEAD
        rewritten = _rewrite_card_claims(text)
        assert "回复『确认』" in rewritten and "我立即设置。" in rewritten
        assert "点下方" not in rewritten
        assert "刷新页面" not in rewritten and "重新进入对话" not in rewritten

    def test_no_claim_unchanged(self):
        for text in (
            "好的，已为您查询到相关信息，请查看上方结果卡片。",
            "确认设置后我立即为您处理。",   # 19:49:22 真实 confirm 卡消息里的「确认设置」
            "您好，很高兴为您服务。",
        ):
            assert _rewrite_card_claims(text) == text, text

    def test_empty_unchanged(self):
        assert _rewrite_card_claims("") == ""


# ── _agent_stream_to_sse 层面：守卫与 last_interactive_payload / interact 调用联动 ──

def _ctx():
    return AgentContext(user_id="u1", tenant_id=1, session_id="s1", role="admin")


def _agent_with(*responses):
    agent = MagicMock()
    agent._agent_type = "xiaobu"

    async def astream(*a, **kw):
        for r in responses:
            yield r

    agent.astream_chat = astream
    return agent


def _interact_tool_result(data, success=True):
    return AgentResponse(
        content="",
        type="tool_result",
        tool_calls=[{
            "tool": "interact",
            "result": {"success": success, "data": data},
        }],
    )


async def _run_stream(responses):
    """跑完 _agent_stream_to_sse，返回 (events, session_memory mock)。"""
    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        sm = AsyncMock()
        sm.save_message = AsyncMock(return_value="msg_1")
        events = [e async for e in _agent_stream_to_sse(
            agent=_agent_with(*responses),
            message="确认设置",
            context=_ctx(),
            chat_history=[],
            tool_registry=MagicMock(),
            session_memory=sm,
            session_id="s1", tenant_id=1, user_id="u1",
        )]
    return events, sm


class TestStreamCardClaimGuard:
    @pytest.mark.asyncio
    async def test_no_payload_claim_text_rewritten_before_save(self):
        """无交互载荷 + 声称「点下方卡片」→ 落库文本改写为纯文本确认指引，
        且直播气泡（文本流结束后、done 之前）追加一条可执行提示。"""
        events, sm = await _run_stream([
            AgentResponse(content=CLAIM_SET, type="text"),
        ])
        sm.save_message.assert_awaited_once()
        saved = sm.save_message.await_args.kwargs.get("content")
        assert saved == "确认无误请回复『确认』，我立即设置。", saved
        assert "点下方" not in saved and "确认卡片" not in saved
        assert "回复『确认』" in saved
        assert sm.save_message.await_args.kwargs.get("interactive") is None
        # 追加提示：正常文本流结束之后、done 之前（并入同一条消息气泡末尾）
        note_events = [e for e in events if "确认卡片未显示" in e]
        assert note_events, f"未追加直播提示事件：{events!r}"
        assert note_events[0].startswith("event: text"), note_events[0]
        idx_claim = next(i for i, e in enumerate(events) if CLAIM_SET in e)
        idx_note = next(i for i, e in enumerate(events) if "确认卡片未显示" in e)
        idx_done = next(i for i, e in enumerate(events) if e.startswith("event: done"))
        assert idx_claim < idx_note < idx_done, (
            f"提示事件位置错误：claim@{idx_claim} note@{idx_note} done@{idx_done}")

    @pytest.mark.asyncio
    async def test_payload_present_text_unchanged(self):
        """19:49:22 形态：本轮真发了 confirm 卡（interact 工具成功 + 载荷）
        → 文本原样落库，不得被误改。"""
        payload = {"component": "confirm", "title": "请确认设置",
                   "fields": [{"label": "开关", "value": "on"}],
                   "confirmValue": "确认设置"}
        responses = [
            AgentResponse(content="好的，请确认设置无误后我立即为您处理。", type="text"),
            AgentResponse(content="", type="tool_call",
                          tool_calls=[{"tool": "interact",
                                       "tool_input": {"component": "confirm"}}]),
            _interact_tool_result(payload),
        ]
        events, sm = await _run_stream(responses)
        sm.save_message.assert_awaited_once()
        saved = sm.save_message.await_args.kwargs.get("content")
        assert saved == "好的，请确认设置无误后我立即为您处理。", saved
        assert sm.save_message.await_args.kwargs.get("interactive") == payload
        assert not any("确认卡片未显示" in e for e in events), "有载荷不得追加提示"

    @pytest.mark.asyncio
    async def test_interact_called_but_failed_no_rewrite(self):
        """本轮调过 interact 工具（即便失败没发出卡）→ 不动作（有 interact 调用即让位）。"""
        responses = [
            AgentResponse(content=CLAIM_SET, type="text"),
            AgentResponse(content="", type="tool_call",
                          tool_calls=[{"tool": "interact",
                                       "tool_input": {"component": "confirm"}}]),
            _interact_tool_result({"component": "confirm"}, success=False),
        ]
        events, sm = await _run_stream(responses)
        sm.save_message.assert_awaited_once()
        saved = sm.save_message.await_args.kwargs.get("content")
        assert saved == CLAIM_SET, saved
        assert not any("确认卡片未显示" in e for e in events), "有 interact 调用不得追加提示"
