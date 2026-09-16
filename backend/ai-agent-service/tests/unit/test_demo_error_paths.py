# case_ids: OR-014
"""一个回合失败 ≠ 会话死掉：瞬时类异常的一次自动恢复 + 用户侧纯中文可继续话术。

**两条客户现场会看到的错误路径**（issue #3810 演示护航包，A/B 两段）：

A. `app/graph/skills/base_skill.py` 的 ReAct 循环 `except Exception`：
   改前 —— 任何异常都直接吞成一句兜底并 `break`，同一会话连吞 N 轮撞同一个瞬时故障
   （#3805 实测 R9–R11 连续 3 轮同一句）。改后 —— **事实驱动**判据（`_is_retryable`：
   异常类型是否属瞬时/可重试）+ **本迭代是否已重试过**，允许 **1 次**自动恢复；
   不可重试类不得被无脑重试（反向守卫）。

B. `app/agents/customer_service_agent.py::astream_chat` 与 `app/api/chat.py` 的 SSE error
   分支：改前把 `{异常类型}: {消息}` 原样拼给用户（`处理失败: ValueError: ...`），
   英文类名/内部字段直接上屏；改后为**纯中文短句**，技术细节落日志 + `incident` 短码。

**判据为什么是事实驱动**：重试与否只看「异常类型/是否可重试」与「本迭代是否重试过」
这两条**事实**，不看兜底话术里有没有关键词 —— 靠措辞判断会把事实问题变成字符串匹配，
换一句同义话术就失效。反向守卫（不可重试类**不得**重试）与正向用例（可重试类重试一次即
成功）成对存在，缺任一条都是空断言（只测"会重试"会把无脑重试也判绿）。

红线：熔断 / 超时 / 轮次耗尽的守卫与话术**一字未动**（它们各有独立分支，见本文件尾部）。
C. 能力自我否定（`capability_denial_text_hit`，issue #3785）的判据与话术**一字未动** ——
   本文件末尾用"话术不含成功/取消标记"做**间接**守卫（避免失败话术污染 pending_skill 判定），
   判据本身不在本包改动面内。
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from openai import InternalServerError

import app.graph.skills.base_skill as base_skill
import app.llm.retry_policy as retry_policy
from app.graph.skills.base_skill import execute_skill

#: 用户可见兜底话术（#3810 措辞）：纯中文、"这轮没成功"、给出可执行的下一步
FALLBACK_TEXT = "刚才这轮没成功，请您再说一次，我继续为您办理。"
#: 审计行稳定标记（跨落点 grep 聚合入口）；本包新增的"重试"行用另一个标记，
#: 故"恰好 N 条审计行"的断言不会被重试行扰动。
AUDIT_MARK = "LLM failed"
RETRY_MARK = "LLM call 重试"
#: 熔断 / 超时 / 轮次耗尽的既有话术（本包**不动**，用作回归守卫）
BREAKER_TEXT = "抱歉，AI 服务暂时不可用，请稍后重试。"
TIMEOUT_TEXT = "抱歉，响应超时，请换个方式描述您的需求。"


def _http_500(message: str = "upstream 500") -> InternalServerError:
    """真实的供应商 5xx 异常（`openai.InternalServerError`，带 status_code=500）。"""
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    return InternalServerError(message, response=httpx.Response(500, request=request), body=None)


def _make_state(session_id: str = "sess_3810", tenant_id: int = 7) -> dict:
    return {
        "messages": [HumanMessage(content="帮我把这单下了")],
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
    """捕获日志记录（含 loguru 的 exception/traceback 字段）。

    用显式 sink 而不是 caplog：loguru 不接标准 logging，只有能拿到
    `record["exception"]` 才算证明了"traceback 真的落盘了"。
    """
    records: list = []
    sink_id = logger.add(lambda m: records.append(m.record), level="DEBUG", format="{message}")
    try:
        yield records
    finally:
        logger.remove(sink_id)


def _lines(records, mark: str) -> list:
    return [r for r in records if mark in r["message"]]


def _sse_payload(frame: str) -> dict:
    """取 SSE 帧的 `data:` JSON 载荷（用节点里的 `event:`/JSON 语法本身不算技术术语泄漏）。"""
    import json

    lines = [ln for ln in frame.splitlines() if ln.startswith("data: ")]
    assert len(lines) == 1, f"SSE 帧格式异常：{frame!r}"
    return json.loads(lines[0][len("data: "):])


def _incident_id(line: str) -> str:
    m = re.search(r"incident=(\S+)", line)
    assert m, f"审计行缺 incident 短码：{line!r}"
    return m.group(1)


async def _run_one_turn(
    exc,
    *,
    session_id: str = "sess_3810",
    tenant_id: int = 7,
    skill_name: str = "customer_order",
) -> tuple:
    """跑一轮 execute_skill，其 LLM 调用每次抛 `exc`。

    ⚠️ **必须把 `call_with_retry` 打断成"仅 1 次尝试"**，否则测的是**两层重试的叠加**：
    `call_with_retry`（策略层，`settings.LLM_RETRY_MAX_ATTEMPTS` 次 + 指数退避）
    包在 `execute_skill` 的业务重试之外 —— 那样"调了几次 LLM"既慢又与真实 sleep 耦合。
    本文件要钉的是**业务层**（一轮 = 一次机会 + 1 次自动恢复），策略层另有
    `tests/test_llm_retry_policy.py` 覆盖；两层用的可重试判据是同一个 `_is_retryable`，
    故 `TestTransientClassificationIsFactBased` 直接把该判据钉死。
    """
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

    async def _single_attempt(factory, **kwargs):
        return await factory()

    with patch.object(base_skill, "create_skill_registry", return_value=registry), \
            patch.object(base_skill, "set_tool_context"), \
            patch.object(base_skill, "get_skill_llm", return_value=llm), \
            patch.object(base_skill, "get_breaker", return_value=breaker), \
            patch.object(base_skill, "call_with_retry", _single_attempt):
        result = await execute_skill(
            state=_make_state(session_id, tenant_id),
            skill_name=skill_name,
            tool_names=[],
            system_prompt="你是测试助手",
        )
    return result, llm


async def _run_one_turn_then_succeed(
    first_exc,
    *,
    session_id: str = "sess_3810",
    tenant_id: int = 7,
    skill_name: str = "customer_order",
) -> tuple:
    """第一调用抛 `first_exc`，第二调用返回正常回复（= 瞬时故障的自愈形态）。"""
    registry = MagicMock()
    registry.get_langchain_tools.return_value = []
    registry.get_names.return_value = []
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=[first_exc, AIMessage(content="好的，这就为您办理。")])

    breaker = MagicMock()

    async def _passthrough(fn):
        return await fn()

    breaker.call = _passthrough

    async def _single_attempt(factory, **kwargs):
        return await factory()

    with patch.object(base_skill, "create_skill_registry", return_value=registry), \
            patch.object(base_skill, "set_tool_context"), \
            patch.object(base_skill, "get_skill_llm", return_value=llm), \
            patch.object(base_skill, "get_breaker", return_value=breaker), \
            patch.object(base_skill, "call_with_retry", _single_attempt):
        result = await execute_skill(
            state=_make_state(session_id, tenant_id),
            skill_name=skill_name,
            tool_names=[],
            system_prompt="你是测试助手",
        )
    return result, llm


class TestTransientExceptionGetsOneAutomaticRecovery:
    """正向：可重试（事实：异常类型属瞬时类）⇒ 本轮自动重试一次，且不消耗额外轮次"""

    @pytest.mark.asyncio
    async def test_retryable_exception_recovers_same_turn(self, audit_records):
        # 第 1 次调用抛供应商 500，第 2 次成功（= 演示现场"再撞一次就好了"的形态）
        result, llm = await _run_one_turn_then_succeed(_http_500())

        assert llm.ainvoke.await_count == 2, (
            "可重试异常必须在本轮自动重试**恰好一次**（实得 %d 次调用）" % llm.ainvoke.await_count
        )
        assert result["final_answer"] == "好的，这就为您办理。", (
            "重试成功后必须交付模型的真实回复，不得仍回兜底话术"
        )
        # 重试事件可见（否则"重试发生过"在日志里查不到）
        retry_lines = [r["message"] for r in _lines(audit_records, RETRY_MARK)]
        assert len(retry_lines) == 1, f"应有 1 条重试行，实得 {retry_lines}"
        assert "InternalServerError" in retry_lines[0], "重试行必须带异常类型"
        assert _incident_id(retry_lines[0]), "重试行必须带 incident 短码"
        # 重试**成功**时不得落终态审计行（否则"吞了几轮"的聚合计数被污染）
        assert not _lines(audit_records, AUDIT_MARK), (
            "重试已成功，不应再落 LLM failed 终态审计行"
        )

    @pytest.mark.asyncio
    async def test_retry_also_fails_then_fallback_is_honest(self, audit_records):
        """重试仍失败 ⇒ 如实兜底（不得伪装成功），且审计行**恰好 1 条**（可聚合）"""
        result, llm = await _run_one_turn(_http_500("still down"))

        assert llm.ainvoke.await_count == 2, "瞬时类异常只给 1 次额外机会，不得无限重试"
        assert result["final_answer"] == FALLBACK_TEXT
        lines = _lines(audit_records, AUDIT_MARK)
        assert len(lines) == 1, f"终态审计行应恰好 1 条（重试行是另一个标记），实得 {len(lines)}"
        assert "error=InternalServerError" in lines[0]["message"]
        assert lines[0]["exception"] is not None, "审计行必须带 traceback"


class TestNonRetryableIsNotRetried:
    """反向守卫：不可重试类**不得**被无脑重试（否则只是把失败拖长、多烧配额）"""

    @pytest.mark.asyncio
    async def test_bad_request_is_not_retried(self, audit_records):
        result, llm = await _run_one_turn(ValueError("provider payload 400"))

        assert llm.ainvoke.await_count == 1, (
            "不可重试类异常（参数/编程错误）必须**立即**失败，不得重试（实得 %d 次调用）"
            % llm.ainvoke.await_count
        )
        assert result["final_answer"] == FALLBACK_TEXT
        assert not [r for r in _lines(audit_records, RETRY_MARK)], (
            "不可重试类异常不得出现重试行"
        )
        assert len(_lines(audit_records, AUDIT_MARK)) == 1

    @pytest.mark.asyncio
    async def test_retry_budget_is_one_per_turn(self):
        """重试预算 = **每回合 1 次**：同一回合内再失败 ⇒ 直接如实兜底并结束本回合。

        若把预算写成"每迭代 1 次"，同一故障持续时 8 个迭代会全烧在重试上（实测 8 次调用），
        最后退化成"轮次耗尽"话术 —— 用户仍无进展，还白烧 8 次配额。
        写成"整轮 0 次"则上面的正向用例挂。两条用例成对，才钉得住这个数。
        """
        result, llm = await _run_one_turn(_http_500("always down"))

        # 第 1 次失败 → 重试 1 次（= 本回合的预算）；第 2 次也失败 → 如实兜底，不再试。
        assert llm.ainvoke.await_count == 2, (
            "同一回合的重试预算必须是 1（实得 %d 次调用）" % llm.ainvoke.await_count
        )
        assert result["final_answer"] == FALLBACK_TEXT, (
            "预算耗尽后必须如实兜底，不得退化成「轮次耗尽」话术：%r" % result["final_answer"]
        )


class TestSessionKeepsGoingAfterFailure:
    """A 的会话层判据：#3805 形态（同会话连续多轮同一异常）⇒ 每轮都是可继续的中文回复"""

    @pytest.mark.asyncio
    async def test_three_consecutive_failed_turns_are_all_resumable(self, audit_records):
        for _ in range(3):
            result, llm = await _run_one_turn(ValueError("bad payload"))
            assert result["final_answer"] == FALLBACK_TEXT
            assert not re.search(r"[A-Za-z]", result["final_answer"]), (
                "顾客可见文本出现英文/技术术语：%r" % result["final_answer"]
            )

        lines = _lines(audit_records, AUDIT_MARK)
        assert len(lines) == 3, f"3 轮应落 3 条终态审计行，实得 {len(lines)}"
        ids = {_incident_id(r["message"]) for r in lines}
        assert len(ids) == 1, f"同会话同一异常必须共用一个 incident 短码（可聚合），实得 {ids}"

    @pytest.mark.asyncio
    async def test_fallback_wording_carries_no_flow_completion_marker(self):
        """措辞守卫：兜底话术不得含写流程的「成功/取消」标记。

        为什么这是**行为**守卫而不只是措辞偏好：`execute_skill` 第 10 步对
        `CREATION_SKILL_NAMES` 的流程用这些标记判"流程是否已完成"来决定是否清
        `pending_skill`（见该处 `success_markers` / `cancel_markers`）。兜底话术若含
        "已创建"/"已下单"一类词，**失败的**写流程会被当成"已完成"解锁 ——
        那就是把失败伪装成成功（#3810 明令禁止）。
        """
        markers = ("创建成功", "已创建", "下单成功", "工单已创建", "售后工单",
                   "账号已创建", "角色已创建", "标签已添加", "已更新", "已添加",
                   "已取消", "已取消创建", "好的，已取消", "不创建了", "算了不买了")
        for marker in markers:
            assert marker not in FALLBACK_TEXT, (
                f"兜底话术含流程完成标记 {marker!r} ⇒ 失败的写流程会被判成已完成并解锁"
            )


class TestTransientClassificationIsFactBased:
    """判据是**事实**（异常类型/是否可重试），不是措辞 —— 直接钉在分类函数上"""

    def test_sdk_transport_and_5xx_are_retryable_facts(self):
        # 供应商连接层错误 ⇒ 事实上的瞬时类
        assert retry_policy._is_retryable(httpx.ConnectError("connection refused")) is True
        assert retry_policy._is_retryable(httpx.ReadTimeout("read timed out")) is True
        # HTTP 5xx（含 openai 的 InternalServerError，带 status_code=500）
        assert retry_policy._is_retryable(_http_500()) is True

    def test_programming_and_4xx_errors_are_not_retryable_facts(self):
        assert retry_policy._is_retryable(ValueError("bad payload")) is False
        assert retry_policy._is_retryable(KeyError("order_create")) is False
        assert retry_policy._is_retryable(RuntimeError("boom")) is False


class TestExistingGuardsUntouched:
    """回归守卫：熔断 / 超时的守卫与话术**一字未动**（本包只加瞬时类重试与话术合规）"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_wording_unchanged(self):
        from app.core import CircuitBreakerOpenError

        result, llm = await _run_one_turn(CircuitBreakerOpenError("open"))
        assert result["final_answer"] == BREAKER_TEXT, "熔断话术被改动（本包不得动它）"
        assert llm.ainvoke.await_count == 1, "熔断不得被重试（会与熔断器冲突）"

    @pytest.mark.asyncio
    async def test_timeout_wording_unchanged(self):
        import asyncio

        result, llm = await _run_one_turn(asyncio.TimeoutError())
        assert result["final_answer"] == TIMEOUT_TEXT, "超时话术被改动（本包不得动它）"
        assert llm.ainvoke.await_count == 1, "超时由 call_with_retry/熔断兜，不在本包重试面内"


class TestSseErrorPathHidesTechnicalDetail:
    """B：SSE / Agent 错误路径的用户可见文本去技术细节，技术细节落日志 + incident"""

    @staticmethod
    def _ctx(session_id="sess_sse"):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id=session_id,
                            role="customer", identity_type="customer")

    @pytest.mark.asyncio
    async def test_astream_chat_error_text_is_chinese_and_logged(self, audit_records):
        from app.agents.customer_service_agent import BaseAgent

        agent = BaseAgent.__new__(BaseAgent)
        agent._agent_type = "xiaobu"
        agent.graph = MagicMock()
        agent.graph.astream = MagicMock(side_effect=ValueError("secret field tenant_id=42"))
        agent._build_initial_state = AsyncMock(return_value={})

        out = []
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mock_sm.return_value.get_pending_skill = AsyncMock(return_value="")
            mock_sm.return_value.get_plan_state = AsyncMock(return_value=None)
            async for resp in agent.astream_chat("你好", self._ctx()):
                out.append(resp)

        err = [r for r in out if r.type == "error"]
        assert len(err) == 1, f"应恰好 1 个 error 响应，实得 {len(err)}"
        content = err[0].content
        # 用户侧：纯中文、说明没成功、可继续（不是静默成功，也不是无信息量通用句）
        assert content == FALLBACK_TEXT, f"用户可见错误文本不合规：{content!r}"
        assert not re.search(r"[A-Za-z]", content), f"错误文本出现英文/技术术语：{content!r}"
        assert "ValueError" not in content and "tenant_id" not in content
        assert "Traceback" not in content
        # 归因：日志里有类型 + incident + traceback；会话号作为上下文入日志
        lines = _lines(audit_records, "astream_chat")
        failed = [r for r in lines if "error=" in r["message"]]
        assert len(failed) == 1, f"应有 1 条审计行，实得 {[r['message'] for r in failed]}"
        assert "error=ValueError" in failed[0]["message"]
        assert "session=sess_sse" in failed[0]["message"]
        assert _incident_id(failed[0]["message"])
        assert failed[0]["exception"] is not None, "审计行必须带 traceback"

    def test_sse_bridge_error_frame_has_no_technical_detail(self, audit_records):
        """`_agent_stream_to_sse` 必须把 Agent 的 error 响应转成**纯中文** SSE 帧。"""
        import asyncio

        from app.agents.customer_service_agent import AgentResponse
        from app.api.chat import _agent_stream_to_sse

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(content=FALLBACK_TEXT, type="error",
                                    metadata={"error_type": "ValueError"})

        class _Mem:
            async def add_message(self, **kw):
                return None

            async def save(self, *a, **kw):
                return None

        ctx = self._ctx()
        gen = _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(), _Mem(),
                                   "sess_sse", 1, "u1")

        async def _collect():
            out = []
            async for chunk in gen:
                out.append(chunk)
            return out

        frames = asyncio.run(_collect())
        err_frames = [f for f in frames if f.startswith("event: error")]
        assert len(err_frames) == 1, f"应恰好 1 个 error 帧，实得 {err_frames}"
        message = _sse_payload(err_frames[0])["message"]
        assert message == FALLBACK_TEXT, f"SSE error 帧话术不合规：{message!r}"
        assert not re.search(r"[A-Za-z]", message), (
            f"SSE error 帧话术出现英文/技术术语：{message!r}"
        )

    def test_sse_event_error_payload_is_what_the_endpoints_send(self):
        """`SSEEvent.error` 的序列化形态：两个 chat.py 分支都只发纯中文短句。"""
        from app.api.sse import SSEEvent

        frame = SSEEvent.error(FALLBACK_TEXT)
        assert frame.startswith("event: error\n")
        message = _sse_payload(frame)["message"]
        assert message == FALLBACK_TEXT
        assert not re.search(r"[A-Za-z]", message), (
            f"error 事件载荷含英文/技术术语：{message!r}"
        )

    def test_chat_error_branches_do_not_interpolate_exception(self):
        """静态守卫：`chat.py` 不得再把异常对象插进用户可见 error 文本。

        为什么用静态断言：两个分支分别位于 SSE 生成器与 `_agent_stream_to_sse` 内层，
        端到端触发需要真实 provider；而**回归风险恰恰是"有人手滑把细节加回去"**，
        故直接把"不得出现 `{type(e).__name__}` 上式插值"钉住（配合上面的行为用例）。
        """
        import inspect

        import app.api.chat as chat_api

        src = inspect.getsource(chat_api)
        offenders = re.findall(r"SSEEvent\.error\(f?[^)]*type\(", src)
        assert not offenders, f"SSE error 文本仍在插值异常类型：{offenders}"
