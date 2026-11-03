# case_ids: HR-009, CH-054
"""工具循环的「连续无进展」出口（P1-4 后半，issue #8150）。

被测契约（`backend/ai-agent-service/app/graph/skills/execution/react_turn.py::react_turn`
的 ReAct 循环，`max_iterations` 默认 8）：

1. **实例**：连续 3 轮工具调用**全部失败**（同一工具、同一组参数）⇒ 循环在**第 3 轮后**
   提前结束（LLM 调用总数 = 3 + 1 次换策略 = 4，而不是 8），且**最后一次**模型调用的
   prompt 里含「换策略」指令（要求向对方确认关键信息 / 如实说明卡在哪）。
2. **不误伤**：中途有**任一工具成功** ⇒ `no_progress_streak` 归零，循环继续到自然结束
   （LLM 调用次数与改前一致 —— 这是「不改既有正常路径」的机械形态）。
3. **失败也算无进展**：工具**抛异常**同样累计（不能只数「重复参数」）。

判据读数取的是**行为面**（LLM 调用次数 / 最后一次 prompt / 工具执行次数），不读源码里的
常量 ⇒ 把 `MAX_NO_PROGRESS_ROUNDS` 改成 8（等于关掉本判据）时第 1 条当场红（读数见 PR body）。

边界（照实登记）：本文件断言的是**循环控制流**；「模型拿到换策略指令后实际说了什么」由真实
评测用例 `.github/cases/chat.yml` 的 CH-054 承担（本包不跑真实 LLM 评测）。
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import app.graph.skills.base_skill as base_skill
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.execution import react_turn as react_turn_mod

SKILL = "order"
TOOL = "order_query"
#: 换策略那一次模型调用应当给出的形态（含「确认」= 向对方确认关键信息）
SWITCH_TEXT = "我先跟您确认一下：您要改的是哪一个订单的发货信息？麻烦把单号再核对一下。"
DONE_TEXT = "好的，已经按您说的处理。"


def _make_state() -> dict:
    """B 端黄金策的 AgentState（`_is_customer_role` 只看 "customer" ⇒ 本用例走 B 端纪律）。"""
    return {
        "messages": [HumanMessage(content="帮我把订单 OR-19990101-9999 的发货信息改一下")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_np_8150",
        "role": "admin",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
    }


def _failure_result() -> MagicMock:
    """工具失败结果（`suggestion` 必须显式为空：有 suggestion 会走 `_self_correct_retry`，
    那会额外发一次 LLM 调用，把「调用次数」这条读数污染掉）。"""
    r = MagicMock()
    r.success = False
    r.data = None
    r.error = "order_not_found"
    r.message = "订单不存在"
    r.summary = ""
    r.suggestion = ""
    r.terminal = False
    r.error_code = None
    r.missing_params = []
    return r


def _success_result() -> MagicMock:
    r = MagicMock()
    r.success = True
    r.data = {"orders": []}
    r.error = None
    r.message = "查询成功"
    r.summary = ""
    r.suggestion = ""
    r.terminal = False
    r.error_code = None
    r.missing_params = []
    return r


def _text_reply(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = []
    return msg


def _tool_call_reply(call_id: str, order_no: str) -> MagicMock:
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [{"name": TOOL, "args": {"order_no": order_no}, "id": call_id}]
    return msg


async def _run(plan: list[str], tool_effects: list, *, vary_args: bool = False):
    """跑一次 `execute_skill`，返回 (result, 每次 LLM 调用的 messages, 工具替身)。

    `plan`：本轮模型的**意图序列**（"fail" 发失败型工具调用 / "ok" 发工具调用 / "text"
    结束回复），超出长度按最后一项续用。
    模型行为**按 prompt 判**：一旦最后一次调用的 prompt 里出现「换策略」指令就换策略 ——
    这样一条断言同时证明「指令真的进了 prompt」与「模型是因为它才换的」。
    """
    tool = MagicMock()
    tool.name = TOOL
    tool.read_only = True
    tool.execute = AsyncMock(side_effect=tool_effects)

    registry = MagicMock()
    registry.get_langchain_tools.return_value = [{
        "name": TOOL,
        "description": "查询订单",
        "args_schema": {"type": "object", "properties": {}},
    }]
    registry.get_tool.return_value = tool

    calls: list[list] = []

    async def _respond(messages):
        calls.append(list(messages))
        if any(isinstance(m, SystemMessage) and "换策略" in str(m.content or "")
               for m in messages):
            return _text_reply(SWITCH_TEXT)
        step = plan[min(len(calls) - 1, len(plan) - 1)]
        if step == "text":
            return _text_reply(DONE_TEXT)
        order_no = (f"OR-1999-{len(calls):04d}" if vary_args
                    else "OR-19990101-9999")
        return _tool_call_reply(f"tc_{len(calls)}", order_no)

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=_respond)

    breaker = MagicMock()

    async def _passthrough(fn):
        return await fn()

    breaker.call = _passthrough

    with patch("app.graph.skills.base_skill.create_skill_registry",
               return_value=registry), \
            patch("app.graph.skills.base_skill.get_skill_llm", return_value=llm), \
            patch("app.graph.skills.base_skill.LLMFactory") as factory, \
            patch("app.graph.skills.base_skill.set_tool_context"), \
            patch("app.graph.skills.base_skill.get_breaker", return_value=breaker):
        factory.create_skill_llm.return_value = llm
        result = await execute_skill(
            state=_make_state(),
            skill_name=SKILL,
            tool_names=[TOOL],
            system_prompt="你是黄金策订单助手",
        )
    return result, calls, tool


def _clear_tool_cache() -> None:
    """清 `_execute_tool_safe` 的**跨用例共享**缓存（只存成功结果）：不清会让「成功」透传到
    下一条用例，把「无进展」这条读数变成假绿/假红。缓存是**首次执行时才建**的（lazy）。"""
    cache = getattr(base_skill._execute_tool_safe, "_cache", None)
    if isinstance(cache, dict):
        cache.clear()


@pytest.fixture(autouse=True)
def _fresh_tool_cache():
    _clear_tool_cache()
    yield
    _clear_tool_cache()


def _has_switch_directive(messages: list) -> bool:
    return any(isinstance(m, SystemMessage) and "换策略" in str(m.content or "")
               for m in messages)


async def test_three_failing_rounds_exit_early_with_strategy_switch():
    """实例：连续 3 轮同工具同参数且全失败 ⇒ 第 3 轮后退出 + 最后一次 prompt 含换策略指令。"""
    result, calls, tool = await _run(["fail"], [_failure_result()] * 10)

    assert len(calls) == 4, (
        f"连续 3 轮无进展后应提前退出（3 轮 + 1 次换策略 = 4 次 LLM 调用），"
        f"实际 {len(calls)} 次")
    assert tool.execute.await_count == 3, (
        f"只该执行 3 轮失败调用（不该烧到 8 轮），实际 {tool.execute.await_count} 次")
    assert _has_switch_directive(calls[-1]), "最后一次模型调用的 prompt 里必须含「换策略」指令"
    assert "确认" in result["final_answer"], (
        f"换策略后的回复必须向商家确认关键信息，实际={result['final_answer']!r}")


async def test_any_tool_success_resets_streak_and_keeps_natural_exit():
    """不误伤：中途有任一工具成功 ⇒ streak 归零，循环继续到自然结束（调用次数与改前一致）。"""
    result, calls, tool = await _run(
        ["fail", "fail", "ok", "fail", "fail", "text"],
        [_failure_result(), _failure_result(), _success_result(),
         _failure_result(), _failure_result()],
        vary_args=True,
    )

    assert len(calls) == 6, (
        f"第 3 轮成功应把 streak 归零、继续到自然结束（6 次调用），实际 {len(calls)} 次")
    assert tool.execute.await_count == 5
    assert not any(_has_switch_directive(msgs) for msgs in calls), (
        "正常路径（有成功工具）不得注入换策略指令")
    assert result["final_answer"] == DONE_TEXT


async def test_tool_exception_counts_as_no_progress():
    """失败也算无进展：工具**抛异常**同样累计（不能只数「重复参数」）。"""
    result, calls, tool = await _run(
        ["fail"], [RuntimeError("upstream down")] * 10)

    assert len(calls) == 4, (
        f"工具连续抛异常 3 轮也应提前退出（4 次 LLM 调用），实际 {len(calls)} 次")
    assert tool.execute.await_count == 3
    assert _has_switch_directive(calls[-1])
    assert "确认" in result["final_answer"]


def test_threshold_is_stricter_than_the_iteration_budget():
    """阈值必须严格小于 `execute_skill` 的默认轮次预算 —— 等于 8 就是「把判据关掉」。"""
    default = inspect.signature(execute_skill).parameters["max_iterations"].default
    assert react_turn_mod.MAX_NO_PROGRESS_ROUNDS < default
