# case_ids: OR-014
"""`app/utils/error_incident.py` 的契约：跨落点**同一条**归因口径（issue #3809 / #3810）。

为什么要单独钉住这个模块：`incident=` 短码口径原先只长在 `base_skill` 里，#3810 起
`customer_service_agent.astream_chat` 与 `api/chat.py` 的两个 SSE 兜底都要用它。
复用是**口径**上的复用 —— 抄两份哈希算法时，同一会话的同一异常会在不同落点算出
**不同**短码，聚合（"同一会话连吞 N 轮"）当场失效。故这里把"单一实现"的行为钉死：
同一 `(会话, 异常类型)` ⇒ 同码；不同会话或不同异常类型 ⇒ 异码；短码不回显内部标识。

同时钉住**用户可见 vs 归因**的边界：审计行只承载类型/单行脱敏消息/短码 + traceback，
不含用户话术；用户那一句由调用方给纯中文短句（见 `test_demo_error_paths.py`）。
"""
import re
from unittest.mock import MagicMock, patch

import pytest

from app.utils.error_incident import (
    EXC_MSG_MAX,
    current_request_id,
    llm_incident_id,
    log_exception_audit,
    safe_exc_message,
)

#: 审计行里"一行 = 一条审计"的格式契约（能被 `error=<类型>: <消息> | incident=` 切开）
AUDIT_SPLIT = " | incident="


class TestIncidentIdIsStableAndDiscriminative:
    def test_same_session_and_type_share_one_code(self):
        """同一会话连续 N 轮吞同一个异常必须共用一个短码 —— 否则聚合不出来（#3805 核心）。"""
        assert llm_incident_id("sess_A", "ValueError") == llm_incident_id("sess_A", "ValueError")

    def test_different_session_or_type_do_not_share(self):
        base = llm_incident_id("sess_A", "ValueError")
        assert llm_incident_id("sess_B", "ValueError") != base, "不同会话不得共码（会串会话）"
        assert llm_incident_id("sess_A", "KeyError") != base, "不同异常类型不得共码（会掩盖根因）"

    def test_code_is_short_hex_and_leaks_nothing(self):
        code = llm_incident_id("sess_secret_3810", "ValueError")
        assert re.fullmatch(r"[0-9a-f]{8}", code), f"短码应为 8 位十六进制：{code!r}"
        assert "sess_secret" not in code, "短码不得回显会话号"

    def test_empty_inputs_do_not_crash(self):
        """非请求上下文（后台任务/单测）里 session_id 可能为空 —— 不得抛异常。"""
        assert re.fullmatch(r"[0-9a-f]{8}", llm_incident_id("", ""))


class TestExcMessageIsAuditSafe:
    def test_multiline_collapsed_to_one_line(self):
        assert "\n" not in safe_exc_message(ValueError("a\nb\nc"))

    def test_phone_masked(self):
        assert "138****8000" in safe_exc_message(ValueError("phone 13800138000 rejected"))

    def test_truncated_to_limit(self):
        text = safe_exc_message(ValueError("x" * (EXC_MSG_MAX + 500)))
        assert len(text) == EXC_MSG_MAX + 1, f"超长消息未按上限截断：{len(text)}"
        assert text.endswith("…")


class TestAuditLineFormat:
    """落笔点的格式契约：`<mark> session=<sid> error=<类型>: <消息> | incident=<码> <extra>`"""

    @staticmethod
    def _fake_logger():
        logger = MagicMock()
        logger.opt.return_value = logger
        return logger

    def test_mark_type_incident_and_extra_are_recorded(self):
        logger = self._fake_logger()
        incident = log_exception_audit(
            logger=logger, mark="[probe] Error", exc=ValueError("boom"),
            session_id="sess_A", extra="tenant=7 iter=1 req=-",
        )

        logger.opt.assert_called_once()
        logger.error.assert_called_once()
        line = logger.error.call_args.args[0]
        assert line.startswith("[probe] Error session=sess_A ")
        assert "error=ValueError: boom" in line
        assert f"incident={incident}" in line
        assert line.endswith("tenant=7 iter=1 req=-")

    def test_returns_the_code_that_is_written_to_the_line(self):
        """返回值必须与写进日志的短码一致 —— 调用方要把它回给上层，不一致就无法对账。"""
        logger = self._fake_logger()
        incident = log_exception_audit(
            logger=logger, mark="[probe]", exc=KeyError("order_create"), session_id="sess_A")
        assert f"incident={incident}" in logger.error.call_args.args[0]

    def test_traceback_goes_to_loguru_exception_field(self):
        """traceback 必须走 `logger.opt(exception=…)`（只有它能算"真的落盘"），
        而不是拼进消息里（拼进去会撕开"一行 = 一条审计"）。"""
        logger = self._fake_logger()
        exc = ValueError("boom")
        log_exception_audit(logger=logger, mark="[probe]", exc=exc, session_id="s")

        assert logger.opt.call_args.kwargs.get("exception") is exc
        assert "Traceback" not in logger.error.call_args.args[0]

    def test_missing_session_still_produces_a_parseable_line(self):
        logger = self._fake_logger()
        log_exception_audit(logger=logger, mark="[probe]", exc=ValueError("v"))
        line = logger.error.call_args.args[0]
        assert "session=-" in line, "无会话上下文时记 `-`，字段位不得缺（下游按位解析）"
        assert AUDIT_SPLIT in line


class TestRequestAnchor:
    """`req=` 把「用户看到那一句的那一轮」锚到中间件的请求日志窗口。"""

    def test_request_id_from_middleware_context(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.middleware.logging_middleware import RequestLoggingMiddleware

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/probe")
        def probe():
            return {"req": current_request_id()}

        resp = TestClient(app).get("/probe", headers={"X-Request-ID": "abc12345"})
        assert resp.json()["req"] == "abc12345", "审计行取不到中间件注入的 request_id"

    def test_no_request_context_falls_back_to_dash(self):
        with patch("app.utils.error_incident.get_request_id", return_value=""):
            assert current_request_id() == "-", "非请求上下文记 `-`，不得抛异常"


@pytest.mark.parametrize("exc", [ValueError("v"), KeyError("k"), RuntimeError("r")])
def test_audit_never_puts_exception_text_in_a_user_visible_field(exc):
    """边界守卫：审计落笔点只产出**日志**，不返回任何用户可见文本。

    调用方（base_skill / customer_service_agent / chat.py）各自给纯中文话术；
    本模块若哪天开始返回"给用户看的字符串"，这条会挂。
    """
    logger = MagicMock()
    logger.opt.return_value = logger
    returned = log_exception_audit(logger=logger, mark="[probe]", exc=exc, session_id="s")
    assert re.fullmatch(r"[0-9a-f]{8}", returned), (
        f"落笔点应只返回 incident 短码（哈希、不含内部细节），实得 {returned!r}"
    )
