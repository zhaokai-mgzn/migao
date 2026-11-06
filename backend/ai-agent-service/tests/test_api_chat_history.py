# case_ids: MC-269
"""`app/api/chat_history.py`（chat.py 切片单元）的镜像判据。

只经单元自身 import（不经 `chat.py`）⇒ 同时证明单元可独立装配、无反向依赖。

钉的行为（都是「搬运最容易切坏」的面）：
① 历史 → agent 形态：`<think>` 剥离、页面信封剥离、**存量主动提示行跳过**（读侧消化、不回放）；
② 会话归属守卫：404 / 跨租户 403 / 非本人 403 —— 三种拒绝都要**具名错误码**；
③ 落库单一策略点：#4084 的 fail-open / fail-closed 两个分支 + **失败必留痕**（审计行含分类与 incident 短码）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from loguru import logger

from app.api.chat_history import (
    PERSIST_FAILED_MARK,
    _convert_history_to_agent_format,
    _format_datetime,
    _guard_session,
    _history_user_text,
    _is_legacy_proactive_tip_row,
    _raise_session_error,
    _report_persist_failure,
    _save_message_or_report,
)
from app.context.menu_navigator import LEGACY_PROACTIVE_TIP_MARK
from app.context.page_registry import (
    PAGE_CONTEXT_ENVELOPE_CLOSE,
    PAGE_CONTEXT_ENVELOPE_OPEN,
    PAGE_CONTEXT_ENVELOPE_TAIL,
    PAGE_CONTEXT_UNKNOWN_NOTICE,
    render_page_context,
)


def _memory(session=None, save=None, side_effect=None):
    memory = MagicMock()
    memory.get_session = AsyncMock(return_value=session)
    memory.save_message = (
        AsyncMock(side_effect=side_effect) if side_effect else AsyncMock(return_value=save))
    return memory


class TestHistoryConversion:
    def test_think_block_is_stripped_from_assistant(self):
        out = _convert_history_to_agent_format(
            [{"role": "assistant", "content": "<think>推理</think>答复"}])
        assert out == [{"role": "assistant", "content": "答复"}]

    def test_legacy_proactive_tip_row_is_skipped(self):
        rows = [
            {"role": "assistant", "content": f"x{LEGACY_PROACTIVE_TIP_MARK}y"},
            {"role": "assistant", "content": "正常回复"},
        ]
        assert _convert_history_to_agent_format(rows) == [
            {"role": "assistant", "content": "正常回复"}]
        assert _is_legacy_proactive_tip_row(rows[0]) is True
        assert _is_legacy_proactive_tip_row(rows[1]) is False

    def test_page_context_envelope_is_stripped_from_user_text(self):
        enveloped = (
            f"{PAGE_CONTEXT_ENVELOPE_OPEN}销售订单列表；{PAGE_CONTEXT_ENVELOPE_TAIL}"
            f"{PAGE_CONTEXT_ENVELOPE_CLOSE}我想问下这单到哪了"
        )
        assert _history_user_text("user", enveloped) == "我想问下这单到哪了"
        # 降级形态（未登记 route）同一条口径：只留用户的话
        degraded = PAGE_CONTEXT_UNKNOWN_NOTICE + "我想问下这单到哪了"
        assert _history_user_text("user", degraded) == "我想问下这单到哪了"
        assert render_page_context("我想问下这单到哪了", None) == degraded
        # 助手消息不是"用户说的话"，原样（信封只该由用户行携带）
        assert _history_user_text("assistant", enveloped) == enveloped

    def test_format_datetime_normalizes_to_utc_z(self):
        assert _format_datetime(
            __import__("datetime").datetime(2026, 11, 6, 11, 42)) == "2026-11-06T11:42:00Z"
        assert _format_datetime("2026-11-06T11:42:00+00:00") == "2026-11-06T11:42:00Z"


class TestSessionGuard:
    def test_missing_session_is_404(self):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_guard_session(_memory(None), "sess-1", tenant_id=1, user_id="u1"))
        assert exc.value.status_code == 404
        assert exc.value.detail["error"]["code"] == "SESSION_NOT_FOUND"

    def test_cross_tenant_is_403(self):
        session = {"tenant_id": 2, "customer_id": "u1"}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_guard_session(_memory(session), "sess-1", tenant_id=1, user_id="u1"))
        assert exc.value.status_code == 403
        assert exc.value.detail["error"]["message"] == "无权访问该会话"

    def test_other_users_session_is_403(self):
        session = {"tenant_id": 1, "customer_id": "u9"}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_guard_session(_memory(session), "sess-1", tenant_id=1, user_id="u1"))
        assert exc.value.status_code == 403

    def test_owner_passes_and_gets_the_row_back(self):
        session = {"tenant_id": 1, "customer_id": "u1", "session_id": "sess-1"}
        got = asyncio.run(_guard_session(_memory(session), "sess-1", tenant_id=1, user_id="u1"))
        assert got is session

    def test_error_codes_map_to_http_status(self):
        with pytest.raises(HTTPException) as exc:
            _raise_session_error("SESSION_CLOSED", "会话已关闭")
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc:
            _raise_session_error("SOMETHING_ELSE", "未知")
        assert exc.value.status_code == 400


class TestPersistStrategyPoint:
    def test_success_returns_message_id(self):
        got = asyncio.run(_save_message_or_report(
            _memory(save="msg-1"), source="chat.assistant",
            session_id="sess-1", role="assistant", content="hi"))
        assert got == "msg-1"

    def test_fail_open_returns_none_but_leaves_an_audit_line(self):
        records = []
        sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
        try:
            got = asyncio.run(_save_message_or_report(
                _memory(side_effect=TypeError("drift")), source="chat.assistant",
                session_id="sess-1", role="assistant", content="hi"))
        finally:
            logger.remove(sink)
        # fail-open 的**契约**是「返回 None（= 没写进去）且**恰好**留一条审计行」，两条一起断言
        assert (got, len(records)) == (None, 1)
        assert records[0].startswith(f"{PERSIST_FAILED_MARK} (CODE DEFECT) op=save_message")
        assert "write=chat.assistant" in records[0]
        assert "incident=" in records[0]

    def test_fail_closed_reraises_after_reporting(self):
        with pytest.raises(ValueError):
            asyncio.run(_save_message_or_report(
                _memory(side_effect=ValueError("boom")), source="chat.user",
                fail_open=False, session_id="sess-1", role="user", content="hi"))

    def test_incident_id_is_deterministic_per_session_and_exc_type(self):
        def audit(exc, session_id):
            return _report_persist_failure(
                exc=exc, op="save_message", source="chat.assistant", session_id=session_id)

        first = audit(TypeError("a"), "sess-1")
        second = audit(TypeError("b"), "sess-1")
        other = audit(TypeError("a"), "sess-2")
        assert first == second
        assert first != other
        assert len(first) == 8
