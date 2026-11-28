"""
澄清轮次护栏纯函数测试（issue #2796）

覆盖 judge_clarify / tick_clarify / should_force_example 的状态机语义：
- 澄清轮计数递增、非澄清轮清零、上限封顶
- force_example 标记与兜底话术存在性
- apply_clarify_guard：SessionStateStore 持久化 + 上限改写路由
"""
# case_ids: CH-003, CH-018

import json

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
        """兜底话术必须给具体示例（低学历可照说），且**不得**再指向已退场的转人工出口。

        变更沿革（用户裁定 2026-09-19：「不应该存在 human_handoff 这种东西，以后全是
        AI 来判断」）：原断言要求话术里出现「转人工」作为出口 —— 转人工能力退场后，
        这句会把用户指向一个**不存在**的入口（比没有出口更糟）。
        替代出口 = **继续用例子引导**（"直接把想问的原话发我"）：低学历用户照说不难，
        且不承诺任何系统做不到的事。
        """
        assert "①" in CLARIFY_FORCE_EXAMPLE_TEXT, "兜底话术缺具体示例"
        # 低学历友好：句式可照抄（祈使句示例）
        assert "直接说一句" in CLARIFY_FORCE_EXAMPLE_TEXT
        # 退场面：不得出现转人工出口话术（按"人工"定位，因为该话术本来就不含工具名）
        for forbidden in ("转人工", "人工客服", "联系客服"):
            assert forbidden not in CLARIFY_FORCE_EXAMPLE_TEXT, (
                f"澄清兜底话术又出现了「{forbidden}」—— 转人工能力已退场，"
                f"这是把用户指向不存在的入口（假承诺）"
            )
        # 替代出口存在（不是"删掉出口了事"）：必须给"继续说"的可执行下一步
        assert "发我" in CLARIFY_FORCE_EXAMPLE_TEXT, "删掉了出口却没给替代路径"


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


# ── 「意图不明 ⇒ 不得臆断检索」（CH-003 收强，issue #9280）──────────────────────
#
# 缺陷实证（run 46086496186 的 xiaobu 腿逐字）：
#   R1 you=帮我看看 tools=['product_search','product_search','product_detail']
#      callargs=product_search{"keyword":"遮光窗帘"}; product_search{"keyword":"奶油风"}
# ⇒ 模型从「帮我看看」**猜出两个顾客从未提过的关键词**并查详情。
# 本节的判据要能同时守住两半：**拦住臆断** + **不误伤明确输入**。
#
# 红证（改这一处即红）：
#   · 把 `judge_speculative_search` 的「实质意图」判据删掉 ⇒ 第 1 条红（该拦的放行了）；
#   · 把「明确输入放行」那半删掉 ⇒ 第 2/3 条红（正常检索被拦）；
#   · 把 C 端调用点摘掉（`_WRITE_GATE_CHAIN` 里的 `speculative_search` / 本模块的 import）
#     ⇒ 第 7 条红（源码一致性判据）。

_VAGUE_UTTERANCE = "帮我看看"


def test_vague_input_blocks_guessed_keyword():
    """「帮我看看」+ 猜出来的关键词 ⇒ 拦下，且拦截话术要求**追问/候选卡**（不是搜索）。"""
    from app.graph.clarify_guard import judge_speculative_search

    reason = judge_speculative_search(
        "product_search", {"keyword": "遮光窗帘"}, [_VAGUE_UTTERANCE])
    assert "interact(component=choice)" in reason          # 候选卡（唯一可执行动作）
    assert "不要默认直接搜" in reason                       # prompt 铁律逐字
    assert "遮光窗帘" in reason                             # 具名指出"这是你猜的"
    assert "未执行" in reason


def test_clear_input_allows_the_same_search():
    """明确输入（说了品类）⇒ **必须放行**（防过度拦截）。"""
    from app.graph.clarify_guard import judge_speculative_search

    assert judge_speculative_search(
        "product_search", {"keyword": "遮光窗帘"}, ["遮光窗帘多少钱"]) == ""


def test_substantive_intent_allows_search_with_model_added_attribute():
    """顾客说了品类（「我要买窗帘」）⇒ 允许按品类检索 —— 即使定语是模型补的。

    「明确度判据」与「检索词接地」是**两条独立放行线**：本条只有前者成立
    （「遮光窗帘」不是顾客原话），删掉前者本条即红。
    """
    from app.graph.clarify_guard import judge_speculative_search

    assert judge_speculative_search(
        "product_search", {"keyword": "遮光窗帘"}, ["我要买窗帘"]) == ""


def test_user_worded_attribute_allows_search():
    """顾客自己说过「奶油风」⇒ 照着原话搜不算臆断（接地判据）。"""
    from app.graph.clarify_guard import judge_speculative_search

    assert judge_speculative_search(
        "product_search", {"keyword": "奶油风"}, ["奶油风"]) == ""
    # 组合词里只要有一个词是顾客说过的，也不算臆断
    assert judge_speculative_search(
        "product_search", {"keyword": "奶油风 窗帘"}, ["奶油风"]) == ""


def test_order_number_input_allows_order_query():
    """顾客给了订单号 ⇒ customer_order_query 必须放行。"""
    from app.graph.clarify_guard import judge_speculative_search

    assert judge_speculative_search(
        "customer_order_query", {"order_no": "202411280001"},
        ["我的订单 202411280001 到哪了"]) == ""
    # 明确输入即便换成别的工具也照样放行（实质意图判据在会话面，不在参数面）
    assert judge_speculative_search(
        "product_search", {"keyword": "遮光窗帘"}, ["遮光窗帘多少钱"]) == ""


def test_detail_after_real_search_is_allowed():
    """先搜后详（id 来自真实结果）= 接地 ⇒ 放行；凭空查详情 ⇒ 拦。"""
    from app.graph.clarify_guard import judge_speculative_search

    assert judge_speculative_search(
        "product_detail", {"product_id": "p_123"}, [_VAGUE_UTTERANCE],
        executed_tools={"product_search"}) == ""
    assert judge_speculative_search(
        "product_detail", {"product_id": "p_123"}, [_VAGUE_UTTERANCE]) != ""


def test_non_search_tools_are_out_of_scope():
    """只读目录/卡片/写工具不在本判据射程内（不误伤其它门禁）。"""
    from app.graph.clarify_guard import judge_speculative_search

    for tool in ("interact", "processing_item_query", "order_create"):
        assert judge_speculative_search(tool, {}, [_VAGUE_UTTERANCE]) == ""


def test_c_end_wiring_is_present():
    """源码一致性：C 端执行链必须挂着这条判据（摘掉即红）。

    三处一起钉住（任何一处被摘掉 ⇒ 本判据红）：
      ① `app/graph/nodes.py` 的澄清护栏挂点（`apply_clarify_guard`）—— C 端 graph 走同一份实现；
      ② `app/graph/skills/base_skill.py` 的接线函数（判据本体只在 `clarify_guard`，不复制）；
      ③ `app/graph/skills/execution/react_turn.py` 的 `_WRITE_GATE_CHAIN` 注册。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    nodes_src = (root / "app" / "graph" / "nodes.py").read_text(encoding="utf-8")
    base_src = (root / "app" / "graph" / "skills" / "base_skill.py").read_text(encoding="utf-8")
    react_src = (root / "app" / "graph" / "skills" / "execution" / "react_turn.py").read_text(
        encoding="utf-8")

    assert "from app.graph.clarify_guard import apply_clarify_guard" in nodes_src
    assert "from app.graph.clarify_guard import (" in base_src
    assert "judge_speculative_search(" in base_src
    assert "def _speculative_search_block(" in base_src
    assert '("speculative_search", _gate_speculative_search)' in react_src


def test_c_end_gate_blocks_vague_and_passes_clear():
    """C 端接线函数的行为面（不是只查符号存在）。"""
    from app.graph.skills.base_skill import _speculative_search_block
    from langchain_core.messages import HumanMessage

    vague_state = {
        "role": "customer",
        "messages": [HumanMessage(content=_VAGUE_UTTERANCE)],
    }
    blocked = _speculative_search_block(
        "product_search", {"keyword": "遮光窗帘"}, {"name": "product_search"},
        "sess_ch003", "customer_general", vague_state)
    payload = json.loads(blocked[1])
    assert payload["success"] is False
    assert payload["error"] == "speculative_search_without_intent"
    assert "interact(component=choice)" in payload["message"]

    clear_state = {
        "role": "customer",
        "messages": [HumanMessage(content="遮光窗帘多少钱")],
    }
    assert _speculative_search_block(
        "product_search", {"keyword": "遮光窗帘"}, {"name": "product_search"},
        "sess_ch003", "customer_general", clear_state) is None

    # 在办卡流程（方向已澄清过）⇒ 放行
    pending_state = dict(vague_state, pending_interact_skill="customer_product")
    assert _speculative_search_block(
        "product_search", {"keyword": "遮光窗帘"}, {"name": "product_search"},
        "sess_ch003", "customer_general", pending_state) is None


def test_b_end_search_semantics_untouched():
    """B 端（黄金策）不受本判据影响 —— 「不改 B 端语义」这一条要可判。"""
    from app.graph.skills.base_skill import _speculative_search_block

    assert _speculative_search_block(
        "product_manage", {"keyword": "遮光窗帘"}, {"name": "product_manage"},
        "sess_b", "product", {"role": "admin"}) is None
