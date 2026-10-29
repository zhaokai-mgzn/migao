"""会话级工作记忆（焦点对象）—— issue #8173 的定点判据。

只覆盖 B 端（mibao）：回写 / 持久化 / 恢复 / 注入 / 确定性指代解析；C 端零行为改变。
红证口径（逐条可复算）：删回写 ⇒ 用例 1 红；删持久化/恢复 ⇒ 往返用例红；
删注入或把它放进非 mibao 分支 ⇒ 注入/`C 端不变` 用例红；把「无焦点/类型不匹配」改成猜 ⇒ 指代用例红。
"""
# case_ids: OR-073, OR-074

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.memory import focus as focus_mod


_ORDER_RESULT = {"success": True, "data": {"orders": [{"order_no": "7732"}]}}
_ORDER_TOOL_RESULTS = [({"name": "order_query"}, "{}", _ORDER_RESULT)]
_ORDER_FOCUS = {
    "entity": "order",
    "id": "7732",
    "label": "#7732",
    "source_tool": "order_query",
    "turn": 4,
}
_CUSTOMER_FOCUS = {
    "entity": "customer",
    "id": "c-1001",
    "label": "张三",
    "source_tool": "customer_manage",
    "turn": 5,
}


@pytest.fixture
def fake_store(monkeypatch):
    """把 SessionStateStore 换成内存实现（回写与恢复都走它 ⇒ 测的是真实接线）。"""

    class _Store:
        snapshot = {}

        def __init__(self, db_session=None):
            self._db = db_session

        async def load(self, session_id):
            return json.loads(json.dumps(self.snapshot)) if self.snapshot else None

        async def commit(self, session_id, state):
            type(self).snapshot = json.loads(json.dumps(state))
            return True

    _Store.snapshot = {}
    monkeypatch.setattr("app.memory.session_state_store.SessionStateStore", _Store)
    return _Store


# ── 1. 回写：工具结果含订单号 ⇒ 焦点写入且 source_tool 正确 ──────────────────
async def test_order_tool_result_writes_focus_with_source_tool(fake_store):
    updated = await focus_mod.remember_from_tool_results(
        "sess_focus", _ORDER_TOOL_RESULTS, turn=4
    )

    assert updated["entity"] == "order"
    assert updated["id"] == "7732"
    assert updated["label"] == "#7732"
    assert updated["source_tool"] == "order_query"
    assert updated["turn"] == 4
    # 删掉持久化（只返回不 commit）⇒ 这条红
    assert fake_store.snapshot["focus"]["id"] == "7732"
    assert fake_store.snapshot["focus"]["source_tool"] == "order_query"


async def test_unrecognized_tool_result_does_not_touch_store(fake_store):
    assert await focus_mod.remember_from_tool_results(
        "sess_focus", [({"name": "knowledge_search"}, "{}", {"success": True, "data": {}})], turn=1
    ) is None
    assert fake_store.snapshot == {}


async def test_customer_tool_result_writes_customer_focus(fake_store):
    updated = await focus_mod.remember_from_tool_results(
        "sess_cust",
        [({"name": "customer_manage"}, "{}", {
            "success": True,
            "data": {"customers": [{"id": "c-1001", "name": "张三"}]},
        })],
        turn=5,
    )
    assert updated["entity"] == "customer"
    assert updated["id"] == "c-1001"
    assert updated["label"] == "张三"
    assert updated["source_tool"] == "customer_manage"
    assert focus_mod.resolve_reference("这个客户", updated) == "c-1001"


async def test_product_tool_result_writes_product_focus(fake_store):
    updated = await focus_mod.remember_from_tool_results(
        "sess_prod",
        [({"name": "product_detail"}, "{}", {
            "success": True,
            "data": {"id": 9, "name": "遮光窗帘"},
        })],
        turn=2,
    )
    assert updated["entity"] == "product"
    assert updated["id"] == "9"
    assert updated["label"] == "遮光窗帘"
    assert updated["source_tool"] == "product_detail"
    assert focus_mod.resolve_reference("这个商品", updated) == "9"


# ── 2. 确定性指代解析（不调 LLM）───────────────────────────────────────────
@pytest.mark.parametrize("text", ["这单的明细", "这一单呢", "该订单发货了吗", "刚才那单再看下"])
def test_resolve_order_reference(text):
    assert focus_mod.resolve_reference(text, _ORDER_FOCUS) == "7732"


def test_resolve_order_reference_without_focus_is_none():
    assert focus_mod.resolve_reference("这单的明细", {}) is None
    assert focus_mod.resolve_reference("这单的明细", None) is None


def test_resolve_customer_under_order_focus_is_none():
    # 改成「乱猜」⇒ 这条红：订单焦点下不得把「这个客户」解析成订单 id
    assert focus_mod.resolve_reference("这个客户的电话", _ORDER_FOCUS) is None


def test_resolve_customer_under_customer_focus():
    assert focus_mod.resolve_reference("这个客户的电话", _CUSTOMER_FOCUS) == "c-1001"


def test_resolve_order_reference_under_customer_focus_is_none():
    assert focus_mod.resolve_reference("这单的明细", _CUSTOMER_FOCUS) is None


# ── 3. prompt 注入：≤3 行；空焦点 0 行；C 端不注入 ──────────────────────────
def test_prompt_injection_is_at_most_three_lines():
    state = {"agent_type": "mibao", "focus": _ORDER_FOCUS}
    injected = focus_mod.inject_focus_prompt("BASE", state)
    added = injected[len("BASE"):].strip("\n")

    assert "当前焦点：订单 #7732（来源 order_query，第 4 轮）" in added
    assert len(added.splitlines()) <= 3


def test_prompt_injection_empty_focus_adds_zero_lines():
    assert focus_mod.inject_focus_prompt(
        "BASE", {"agent_type": "mibao", "focus": {}}
    ) == "BASE"


def test_malformed_turn_does_not_break_injection():
    """持久化脏数据（turn 非数字）不得让注入路径抛错（fire-and-forget 纪律）。"""
    dirty = dict(_ORDER_FOCUS, turn="第4轮")
    injected = focus_mod.inject_focus_prompt(
        "BASE", {"agent_type": "mibao", "focus": dirty}
    )
    assert injected.startswith("BASE")
    assert "当前焦点：订单 #7732（来源 order_query）" in injected


def test_prompt_injection_skips_c_end():
    # C 端（xiaobu）即使会话状态里有焦点也**逐字节不注入** ⇒ 改成无条件注入即红
    state = {"agent_type": "xiaobu", "focus": _ORDER_FOCUS}
    assert focus_mod.inject_focus_prompt("BASE", state) == "BASE"


# ── 3b. 指代接线：命中才追加一行（空 / 类型不匹配 / C 端 ⇒ 零追加）────────────
def test_reference_hint_line_on_order_match():
    line = focus_mod.reference_hint_line("这单的明细", _ORDER_FOCUS)
    assert line == "本轮指代：「这单」= 订单 #7732"
    assert "\n" not in line


def test_reference_hint_line_customer_under_order_focus_is_empty():
    # 负例：订单焦点下说「这个客户」⇒ 不追加（改成「出现」即本条红）
    assert focus_mod.reference_hint_line("这个客户的电话", _ORDER_FOCUS) == ""


def test_reference_hint_line_without_focus_is_empty():
    assert focus_mod.reference_hint_line("这单的明细", {}) == ""


def test_prepare_turn_wires_reference_hint():
    """接线守卫（§28.2）：删掉 prepare_turn 里的追加 / mibao 门 ⇒ 本条红。"""
    source = (_APP / "graph/skills/execution/prepare_turn.py").read_text(encoding="utf-8")
    assert 'if resolve_reference(_confirm_msg, state.get("focus")):' in source
    assert 'system_prompt += "\\n" + reference_hint_line(_confirm_msg, state.get("focus"))' in source
    # C 端逐字节不变的结构门（xiaobu 不进这段）
    assert 'if state.get("agent_type") == "mibao":' in source


# ── 4. recent 封顶 3 条 ────────────────────────────────────────────────────
def test_recent_is_capped_at_three():
    current = {}
    for i in range(5):
        current = focus_mod.update_focus(current, {
            "entity": "order", "id": str(i), "label": f"#{i}",
            "source_tool": "order_query", "turn": i,
        })
    assert current["id"] == "4"
    assert [item["id"] for item in current["recent"]] == ["4", "3", "2"]


# ── 5. store 往返：持久化后下一轮 _build_initial_state 仍能恢复 ─────────────
async def test_focus_survives_store_roundtrip_and_initial_state(fake_store):
    await focus_mod.remember_from_tool_results("sess_rt", _ORDER_TOOL_RESULTS, turn=4)

    from app.agents.customer_service_agent import AgentContext, WorkAssistantAgent
    from app.memory.session_memory import SessionMemory

    agent = WorkAssistantAgent()
    context = AgentContext(
        user_id="100", tenant_id=1, session_id="sess_rt", role="admin"
    )
    with patch.object(SessionMemory, "get_plan_state", AsyncMock(return_value=None)), \
            patch.object(SessionMemory, "get_pending_skill", AsyncMock(return_value=None)):
        state = await agent._build_initial_state(
            [HumanMessage(content="这单的明细")], context
        )

    # 删掉 _build_initial_state 里的 focus 恢复 ⇒ 这条红
    assert state["focus"]["id"] == "7732"
    assert state["focus"]["source_tool"] == "order_query"


async def test_c_end_initial_state_ignores_persisted_focus(fake_store):
    fake_store.snapshot = {"focus": json.loads(json.dumps(_ORDER_FOCUS))}

    from app.agents.customer_service_agent import AgentContext, CustomerServiceAgent
    from app.memory.session_memory import SessionMemory

    agent = CustomerServiceAgent()
    context = AgentContext(
        user_id="100", tenant_id=1, session_id="sess_c", role="customer"
    )
    with patch.object(SessionMemory, "get_plan_state", AsyncMock(return_value=None)), \
            patch.object(SessionMemory, "get_pending_skill", AsyncMock(return_value=None)):
        state = await agent._build_initial_state(
            [HumanMessage(content="这单的明细")], context
        )

    assert state["focus"] == {}


# ── 6. 接线守卫（判据本体绿 ≠ 接线在，§28.2）：摘掉调用点 ⇒ 红 ─────────────
_APP = Path(__file__).resolve().parents[1] / "app"


def test_react_turn_wires_focus_writeback():
    source = (_APP / "graph/skills/execution/react_turn.py").read_text(encoding="utf-8")
    assert "remember_from_tool_results" in source
    assert 'state.get("agent_type") == "mibao"' in source


def test_prepare_turn_wires_focus_injection():
    source = (_APP / "graph/skills/execution/prepare_turn.py").read_text(encoding="utf-8")
    assert "inject_focus_prompt(system_prompt, state)" in source
