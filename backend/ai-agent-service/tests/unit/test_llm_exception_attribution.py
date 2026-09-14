# case_ids: OR-014
"""LLM 调用异常吞点的**可归因性**（issue #3805，产品侧那一半）。

背景（判定跑 34873715194 / SHA 30527b73，B 端 OR-014 第 2 次尝试）：
`R4/R9/R10/R11` 四轮逐字返回同一句 `抱歉，我遇到了一些问题，请稍后重试。`，四轮 `tools=-`。
该串在 `origin/main` 的**唯一产生点**是 `app/graph/skills/base_skill.py` 的
`execute_skill` 里 `except Exception` 兜底（熔断 / 超时 / 轮次耗尽各有**不同**话术）——
即某类异常被吞成一句**无标识**话术，同一会话连吞 4 次（其中 R9–R11 连续 3 轮），
而产物里看不出异常类型与原因（根因 `undetermined`）。

本文件钉死的**不是话术**，而是归因能力（三条判据，缺一即为回归）：
  ① **身份可查**：日志里能查到异常**类型** + `str(exc)`（单行、脱敏、截断）+ traceback；
  ② **上下文可查**：日志里带 skill / session / 租户 / 轮次，可定位到"哪一轮哪一路"；
  ③ **可聚合**：同一会话 × 同一异常类型 ⇒ **同一个 incident 短码**
     ⇒「连续 N 轮吞同一个异常」的 N 条日志可聚成一个 incident（#3805 最想要的形态）。

同时钉死**话术合规**：兜底话术仍是面向低学历用户的纯中文短句，
**不得**把异常类型/堆栈/英文技术术语抛给用户（这是本单明确的反模式）。
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger
from langchain_core.messages import HumanMessage

import app.graph.skills.base_skill as base_skill
from app.graph.skills.base_skill import execute_skill

#: 用户可见兜底话术（issue #3810 起从「抱歉，我遇到了一些问题，请稍后重试。」改为下面这句）
#: —— 原句是**无信息量通用句**：顾客不知道这轮有没有成功、下一步做什么（#3810 明确禁止
#: 改成"静默成功"或"无信息量通用句"）。新句纯中文、说明"这轮没成功"、给出可执行的下一步，
#: 且**不含**写流程的成功/取消标记（否则「创建类流程」的 pending_skill 判定会把失败的写流程
#: 当成已完成而解锁 —— 那是把失败伪装成成功）。
FALLBACK_TEXT = "刚才这轮没成功，请您再说一次，我继续为您办理。"
#: 审计行里出现的稳定标记（同类吞点的统一检索入口）
AUDIT_MARK = "LLM failed"
#: `str(exc)` 在审计行里的上限（截断上限，防多行/超长异常消息破坏"一行 = 一条审计"）
EXC_MSG_LIMIT = 300


class _ProviderError(RuntimeError):
    """模拟**非超时类**的 LLM 调用异常（httpx/openai 的封装错误、400/422 一类）。

    ⚠️ 不能拿 `TimeoutError` 当样本：Python 3.11 起 `asyncio.TimeoutError is TimeoutError`，
    会被 `except asyncio.TimeoutError` 分支先接住（话术是「抱歉，响应超时…」）——
    那正是 #3805 里**被排除**的形态；本文件的样本必须落在通用 `except Exception` 上。
    """


def _make_state(session_id: str = "sess_3805", tenant_id: int = 7) -> dict:
    return {
        "messages": [HumanMessage(content="帮我下单，遮光窗帘 3 米")],
        "tenant_id": tenant_id,
        "user_id": 100,
        "session_id": session_id,
        "role": "merchant",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }


@pytest.fixture
def audit_records():
    """捕获 ERROR 级日志记录（含 loguru 的 exception/traceback 字段）。

    用显式 sink 而不是 caplog：loguru 不接标准 logging，只有能拿到
    `record["exception"]` 才算证明了"traceback 真的落盘了"。
    """
    records: list = []
    sink_id = logger.add(lambda m: records.append(m.record), level="ERROR", format="{message}")
    try:
        yield records
    finally:
        logger.remove(sink_id)


async def _run_one_turn(
    exc: BaseException,
    *,
    session_id: str = "sess_3805",
    tenant_id: int = 7,
    skill_name: str = "customer_order",
) -> dict:
    """跑一轮 execute_skill，其中 LLM 调用抛 `exc`（= #3805 的触发形态）。"""
    registry = MagicMock()
    registry.get_langchain_tools.return_value = []
    registry.get_names.return_value = []
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=exc)

    breaker = MagicMock()

    async def _passthrough(fn):
        return await fn()

    breaker.call = _passthrough

    with patch.object(base_skill, "create_skill_registry", return_value=registry), \
            patch.object(base_skill, "set_tool_context"), \
            patch.object(base_skill, "get_skill_llm", return_value=llm), \
            patch.object(base_skill, "get_breaker", return_value=breaker):
        return await execute_skill(
            state=_make_state(session_id, tenant_id),
            skill_name=skill_name,
            tool_names=[],
            system_prompt="你是测试助手",
        )


def _audit_lines(records) -> list:
    return [r for r in records if AUDIT_MARK in r["message"]]


def _incident_id(line: str) -> str:
    m = re.search(r"incident=(\S+)", line)
    assert m, f"审计行缺 incident 短码：{line!r}"
    return m.group(1)


class TestFallbackWordingStaysCompliant:
    """兜底话术合规：非技术、低学历可懂、有信息量（issue #3810 的措辞纪律）"""

    @pytest.mark.asyncio
    async def test_user_visible_text_is_non_technical_and_actionable(self):
        result = await _run_one_turn(ValueError("internal provider payload 400"))

        assert result["final_answer"] == FALLBACK_TEXT, (
            "兜底话术被改动 —— 改话术必须同步改本断言并说明理由（#3810 有明确的措辞纪律）"
        )
        # C 端/B 端约定：不得把异常类型、英文技术术语、堆栈抛给用户
        assert not re.search(r"[A-Za-z]", result["final_answer"]), (
            "用户可见兜底话术出现英文/技术术语：%r" % result["final_answer"]
        )
        assert "Traceback" not in result["final_answer"]
        # 反向守卫：不得退化成"静默成功"或"无信息量通用句"（#3810 明令）
        assert "没成功" in result["final_answer"], "顾客必须知道这轮没成功"
        assert "再说一次" in result["final_answer"], "必须给出可执行的下一步（可重试）"


class TestLLMExceptionIsAttributable:
    """异常被吞后必须能在服务端日志里归因（#3805 核心）"""

    @pytest.mark.asyncio
    async def test_audit_line_carries_type_message_and_context(self, audit_records):
        await _run_one_turn(ValueError("bad payload from provider"), tenant_id=42)

        lines = _audit_lines(audit_records)
        assert len(lines) == 1, f"LLM 异常应落**恰好 1 条**审计行，实得 {len(lines)}：{lines}"
        line = lines[0]["message"]

        # ① 异常身份：类型 + str(exc)
        assert "error=ValueError" in line, f"审计行缺异常类型：{line!r}"
        assert "bad payload from provider" in line, f"审计行缺异常消息：{line!r}"
        # ② 上下文：skill / session / 租户 / 轮次
        assert "customer_order" in line, f"审计行缺 skill：{line!r}"
        assert "session=sess_3805" in line, f"审计行缺 session：{line!r}"
        assert "tenant=42" in line, f"审计行缺租户（无法定位到哪个商户）：{line!r}"
        assert "iter=1" in line, f"审计行缺轮次：{line!r}"
        # ③ incident 短码（把用户看到的那句话对到日志里的具体异常）
        assert _incident_id(line)

    @pytest.mark.asyncio
    async def test_traceback_is_recorded_not_just_str(self, audit_records):
        """`str(exc)` 对 KeyError/AttributeError 类异常不可归因 ⇒ 必须有 traceback。"""
        await _run_one_turn(KeyError("order_create"))

        lines = _audit_lines(audit_records)
        assert lines, "LLM 异常未落审计行"
        assert any(r["exception"] is not None for r in lines), (
            "审计行没有 traceback（loguru record['exception'] 为空）——"
            "只有 type+str 时，KeyError/AttributeError 这类异常无法定位到出错行"
        )

    @pytest.mark.asyncio
    async def test_exception_message_is_single_line_truncated_and_masked(self, audit_records):
        """多行/超长异常消息会破坏「一行 = 一条审计」；异常回显里可能带手机号。"""
        noisy = ValueError(
            "provider rejected request\n"
            "body={\"phone\":\"13800138000\"}\n"
            + "padding " * 200
        )
        await _run_one_turn(noisy)

        line = _audit_lines(audit_records)[0]["message"]
        assert "\n" not in line, f"审计行被多行异常消息撕开了：{line!r}"
        # 审计行格式契约：… error=<类型>: <消息> | incident=… ⇒ 消息止于 ` | incident=`
        captured = line.split("error=ValueError:", 1)[1].split(" | incident=", 1)[0].strip()
        assert len(captured) <= EXC_MSG_LIMIT + 1, (
            f"异常消息未截断（{len(captured)} 字符 > 上限 {EXC_MSG_LIMIT}）：{captured[:80]!r}..."
        )
        assert "13800138000" not in line, f"异常回显里的手机号未脱敏：{line!r}"
        assert "138****8000" in line, f"应复用 LogSanitizer 脱敏手机号：{line!r}"


class TestConsecutiveFailuresAggregateToOneIncident:
    """「连续 N 轮吞同一个异常」⇒ N 条日志可聚合成一个 incident（#3805 最想要的能力）"""

    @pytest.mark.asyncio
    async def test_three_consecutive_turns_share_one_incident_id(self, audit_records):
        # #3805 形态复刻：R9/R10/R11 同一会话、同一异常、连续 3 轮
        for _ in range(3):
            result = await _run_one_turn(_ProviderError("llm call failed"))
            assert result["final_answer"] == FALLBACK_TEXT

        lines = _audit_lines(audit_records)
        assert len(lines) == 3, f"3 轮应落 3 条审计行，实得 {len(lines)}"
        ids = {_incident_id(r["message"]) for r in lines}
        assert len(ids) == 1, (
            f"同一会话连续 3 轮的同一个异常应共用一个 incident 短码（可聚合），实得 {ids}"
        )

    @pytest.mark.asyncio
    async def test_incident_id_discriminates_session_and_exception_type(self, audit_records):
        await _run_one_turn(_ProviderError("t"), session_id="sess_A")
        await _run_one_turn(_ProviderError("t"), session_id="sess_B")
        await _run_one_turn(ValueError("v"), session_id="sess_A")

        lines = [r["message"] for r in _audit_lines(audit_records)]
        assert len(lines) == 3
        ids = [_incident_id(line) for line in lines]
        assert ids[0] != ids[1], "不同会话不得共用 incident 短码（否则聚合会串会话）"
        assert ids[0] != ids[2], "不同异常类型不得共用 incident 短码（否则聚合掩盖根因）"

    @pytest.mark.asyncio
    async def test_incident_id_is_stable_and_leaks_nothing(self, audit_records):
        """短码必须是 (session|异常类型) 的确定性哈希：可复现、不含内部细节。"""
        await _run_one_turn(ValueError("v"))
        first = _incident_id(_audit_lines(audit_records)[0]["message"])

        await _run_one_turn(ValueError("v"))
        second = _incident_id(_audit_lines(audit_records)[1]["message"])

        assert first == second, "同一 (会话, 异常类型) 的短码必须稳定，否则历史日志无法对账"
        assert "sess_3805" not in first, "短码不得回显会话号（避免外露内部标识）"


class TestRequestAnchor:
    """`req=` 把「用户看到那一句的那一轮」锚到中间件的请求日志窗口"""

    def test_request_id_reaches_the_audit_helper(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.middleware.logging_middleware import RequestLoggingMiddleware

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/probe")
        def probe():
            return {"req": base_skill._current_request_id()}

        client = TestClient(app)
        resp = client.get("/probe", headers={"X-Request-ID": "abc12345"})
        assert resp.json()["req"] == "abc12345", (
            "审计行的 req= 取不到中间件注入的 request_id —— "
            "这条锚点断了就只能靠时间猜是哪一轮"
        )
        assert resp.headers["X-Request-ID"] == "abc12345"
        # 非请求上下文（单测/后台任务）不得抛异常，记 `-` 即可
        assert base_skill._current_request_id() == "-"
