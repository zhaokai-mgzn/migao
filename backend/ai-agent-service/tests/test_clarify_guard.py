"""
澄清轮次护栏纯函数测试（issue #2796）

覆盖 judge_clarify / tick_clarify / should_force_example 的状态机语义：
- 澄清轮计数递增、非澄清轮清零、上限封顶
- force_example 标记与兜底话术存在性
- apply_clarify_guard：SessionStateStore 持久化 + 上限改写路由
"""
# case_ids: CH-003, CH-018

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.graph.clarify_guard import (
    MAX_CLARIFY_ROUNDS,
    CLARIFY_FORCE_EXAMPLE_TEXT,
    CLARIFY_STATE_KEY,
    apply_clarify_guard,
    judge_clarify,
    tick_clarify,
    should_force_example,
)


class TestJudgeClarify:
    """澄清轮次上限判定"""

    def test_below_limit_allows_continue(self):
        assert judge_clarify(0) is False
        assert judge_clarify(1) is False

    def test_at_limit_forces_example(self):
        assert judge_clarify(2) is True
        assert judge_clarify(3) is True  # 封顶后仍 True

    def test_custom_max_rounds(self):
        assert judge_clarify(2, max_rounds=3) is False
        assert judge_clarify(3, max_rounds=3) is True

    def test_default_max_matches_constant(self):
        assert MAX_CLARIFY_ROUNDS == 2


class TestTickClarify:
    """澄清计数更新：澄清轮 +1 / 实质轮清零 / 上限标记"""

    def test_first_clarify_round_increments(self):
        state = tick_clarify({}, was_clarify_round=True)
        assert state["count"] == 1
        assert state["force_example"] is False

    def test_second_clarify_round_triggers_force_example(self):
        state = tick_clarify({"count": 1}, was_clarify_round=True)
        assert state["count"] == 2
        assert state["force_example"] is True

    def test_count_capped_at_max(self):
        state = tick_clarify({"count": 5}, was_clarify_round=True)
        assert state["count"] == MAX_CLARIFY_ROUNDS  # 封顶，不无限增长

    def test_substantive_round_resets_counter(self):
        """用户给出实质意图/点选澄清卡 → 澄清计数清零，重新计。"""
        state = tick_clarify({"count": 2, "force_example": True}, was_clarify_round=False)
        assert state["count"] == 0
        assert state["force_example"] is False

    def test_missing_state_defaults(self):
        state = tick_clarify(None, was_clarify_round=True)
        assert state["count"] == 1
        state = tick_clarify(None, was_clarify_round=False)
        assert state["count"] == 0


class TestForceExample:
    """force_example 状态读取与兜底话术"""

    def test_force_example_flag_read(self):
        assert should_force_example({"force_example": True}) is True
        assert should_force_example({"force_example": False}) is False
        assert should_force_example({}) is False
        assert should_force_example(None) is False

    def test_fallback_text_is_actionable_and_low_reading_level(self):
        """兜底话术必须给具体示例（低学历可照说）且有转人工出口。"""
        assert "转人工" in CLARIFY_FORCE_EXAMPLE_TEXT, "兜底话术缺转人工出口"
        assert "①" in CLARIFY_FORCE_EXAMPLE_TEXT, "兜底话术缺具体示例"
        # 低学历友好：句式可照抄（祈使句示例）
        assert "直接说一句" in CLARIFY_FORCE_EXAMPLE_TEXT


# ── 异步守卫（mock SessionStateStore）──

class _FakeDecision:
    """RouteDecision 替身（含 intent_result 属性）。"""

    def __init__(self, action="full_agent", direct_reply=None, tool_hint=None):
        self.action = action
        self.direct_reply = direct_reply
        self.tool_hint = tool_hint
        self.intent_result = type("IR", (), {"intent": "general", "source": "low_confidence"})()


def _mock_store(state_dict=None, fail=False):
    """mock SessionStateStore：内存 state，fail=True 模拟异常。"""
    store = MagicMock()

    async def _load(sid):
        if fail:
            raise RuntimeError("db down")
        return dict(state_dict or {})

    async def _commit(sid, state):
        if fail:
            raise RuntimeError("db down")
        state_dict.clear()
        state_dict.update(state)
        return True

    store.load = AsyncMock(side_effect=_load)
    store.commit = AsyncMock(side_effect=_commit)
    return store


@pytest.mark.asyncio
async def test_guard_escalates_after_max_rounds():
    """连续澄清轮达到上限后：apply_clarify_guard 改写为 direct_reply 兜底话术。"""
    store = _mock_store({CLARIFY_STATE_KEY: {"count": MAX_CLARIFY_ROUNDS, "force_example": True}})
    with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
        decision = await apply_clarify_guard(
            "sess1", is_clarify_round=True, route_decision=_FakeDecision()
        )
    assert decision.action == "direct_reply"
    assert decision.direct_reply == CLARIFY_FORCE_EXAMPLE_TEXT


@pytest.mark.asyncio
async def test_guard_allows_clarify_below_limit():
    """澄清轮未达上限：路由不改写，计数 +1 写回。"""
    state = {CLARIFY_STATE_KEY: {"count": 1, "force_example": False}}
    store = _mock_store(state)
    with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
        decision = await apply_clarify_guard(
            "sess1", is_clarify_round=True, route_decision=_FakeDecision()
        )
    assert decision.action == "full_agent"  # 未改写，继续澄清
    assert state[CLARIFY_STATE_KEY]["count"] == 2
    assert state[CLARIFY_STATE_KEY]["force_example"] is True  # 本轮刚达上限


@pytest.mark.asyncio
async def test_guard_resets_on_substantive_round():
    """用户给出实质意图（非澄清轮）→ 计数清零。"""
    state = {CLARIFY_STATE_KEY: {"count": 2, "force_example": True}}
    store = _mock_store(state)
    with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
        decision = await apply_clarify_guard(
            "sess1", is_clarify_round=False, route_decision=_FakeDecision()
        )
    assert decision.action == "full_agent"  # 实质轮不改写
    assert state[CLARIFY_STATE_KEY]["count"] == 0
    assert state[CLARIFY_STATE_KEY]["force_example"] is False


@pytest.mark.asyncio
async def test_guard_degrades_gracefully_on_store_failure():
    """存储失败 → 降级返回原路由（不阻断主流程）。"""
    store = _mock_store(fail=True)
    original = _FakeDecision()
    with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
        decision = await apply_clarify_guard(
            "sess1", is_clarify_round=True, route_decision=original
        )
    assert decision is original  # 原样返回


@pytest.mark.asyncio
async def test_guard_noop_without_session():
    """无 session_id → 直接原样返回。"""
    original = _FakeDecision()
    decision = await apply_clarify_guard(
        "", is_clarify_round=True, route_decision=original
    )
    assert decision is original


@pytest.mark.asyncio
async def test_guard_sequence_three_clarify_rounds_then_escalate():
    """端到端序列：轮1、轮2 正常澄清（机会给足），轮3 仍模糊 → 强制兜底。

    预算语义：MAX=2 轮澄清机会；第 3 轮（count 已达上限）不再追问。
    """
    state: dict = {}
    store = _mock_store(state)

    from app.graph.clarify_guard import CLARIFY_STATE_KEY as K

    async def _run(was_clarify):
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            return await apply_clarify_guard(
                "sess_seq", is_clarify_round=was_clarify, route_decision=_FakeDecision()
            )

    # 轮1 澄清 → 正常（count 0→1）
    d1 = await _run(True)
    assert d1.action == "full_agent" and state[K]["count"] == 1
    # 轮2 澄清 → 正常（count 1→2，达上限但本轮仍给机会）
    d2 = await _run(True)
    assert d2.action == "full_agent" and state[K]["count"] == 2
    # 轮3 澄清 → force_example 兜底（不再追问）
    d3 = await _run(True)
    assert d3.action == "direct_reply"
    assert d3.direct_reply == CLARIFY_FORCE_EXAMPLE_TEXT
    # 轮4 用户给出实质意图（如点选了澄清卡/说了明确需求）→ 状态清零，流程恢复
    d4 = await _run(False)
    assert d4.action == "full_agent"
    assert state[K]["count"] == 0
