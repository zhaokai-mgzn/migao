"""
确认-执行链跨 skill 写工具缺失恢复测试（issue #3976）。

覆盖两条缺口的确定性层回归：
- P2：`_run_one_tool` 的 tool_not_found 分支——订单写工具在本 skill 注册表缺失时，
  必须 relock 到归属 skill 并给出**可执行**话术（不得让模型空头承诺「请稍候，我这就提交」）。
- P3：relock 写入的 pending_skill 不得被 execute_skill 轮末跨轮持久化覆盖回原 skill
  （否则下一轮短消息快捷路由仍走无工具的 skill，故障复发）。

实证（sess_202d55d49a254a10，2026-09-17）：B 端米宝在 product skill 内完成
validate_input(order_create) + 确认卡，点卡后答卡轮留在 product → LLM 调 order_create
→ `[product] Tool not found: order_create` → 最终回复「已转到订单流程为您落单…请稍候，
我这就提交」→ orders 表无新订单；且 session_states.pending_skill 在 relock 后被轮末
commit 覆盖回 product。
"""
# case_ids: OR-029
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.graph.skills.base_skill import execute_skill


def _make_state(**overrides):
    """B 端（mibao/admin）product skill 在办下单态（与线上实证同形态）。"""
    state = {
        "messages": [HumanMessage(content="确认下单")],
        "tenant_id": 1,
        "user_id": "user_admin_001",
        "session_id": "sess_t3976",
        "role": "admin",
        "agent_type": "mibao",
        "pending_interact_skill": "product",
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
    state.update(overrides)
    return state


class _FakeGroundedStore:
    """内存会话状态，预置「已校验待执行写 + 已查过商品详情」。

    与 test_graph_skills.py 的 `_FakeGroundedStore` 同构：测试与 DB 无关，
    不依赖本机 PG 可用性（线上形态的 pending_validated_input 即由此承载）。
    """

    _states: dict = {}

    def __init__(self, *a, **k):
        pass

    async def load(self, session_id: str) -> dict:
        return dict(_FakeGroundedStore._states.setdefault(
            session_id,
            {
                "pending_validated_input": {
                    "target_tool": "order_create",
                    "target_action": "create",
                    "params": {
                        "customer_name": "赵凯",
                        "customer_phone": "13456000919",
                        "items": [{"product_name": "2699系列雪尼尔窗帘面料",
                                   "quantity": 10, "unit_price": 23.8,
                                   "subtotal": 238}],
                    },
                },
                "grounded_product_detail": {"product_id": "b4e420cf7819b83f974a325332620b32"},
            },
        ))

    async def commit(self, session_id: str, full: dict) -> None:
        _FakeGroundedStore._states[session_id] = dict(full)

    async def clear(self, session_id: str) -> None:
        _FakeGroundedStore._states.pop(session_id, None)


@pytest.fixture(autouse=True)
def _grounded_store():
    _FakeGroundedStore._states = {}
    with patch("app.memory.session_state_store.SessionStateStore", _FakeGroundedStore):
        yield


class TestOrderWriteToolNotFoundRecovery:
    """P2/P3：订单写工具 tool_not_found 的恢复路径（issue #3976）。"""

    def _mock_env(self, llm_responses, no_think_responses):
        """mock execute_skill 的 LLM / registry / breaker 依赖。"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        # product skill 的注册表没有 order_create → get_tool 返回 None（触发 tool_not_found）
        mock_registry.get_tool.return_value = None

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=llm_responses)

        mock_no_think = MagicMock()
        mock_no_think.bind_tools.return_value = mock_no_think
        mock_no_think.ainvoke = AsyncMock(side_effect=no_think_responses)

        fake_mem = MagicMock()
        fake_mem.set_pending_skill = AsyncMock(return_value=True)
        # relock 已把 pending_skill 迁到 order；轮末持久化必须**保留**它（P3 修复后读回）
        fake_mem.get_pending_skill = AsyncMock(return_value="order")
        fake_mem.get_vision_analysis = AsyncMock(return_value="")
        fake_mem.get_plan_state = AsyncMock(return_value="")
        fake_mem.get_last_confirm_value = AsyncMock(return_value="")

        return {
            "registry": mock_registry,
            "breaker": mock_breaker,
            "llm": mock_llm,
            "no_think": mock_no_think,
            "mem": fake_mem,
        }

    def _tool_call_msg(self):
        r = MagicMock(spec=AIMessage)
        r.content = ""
        r.tool_calls = [
            {"name": "order_create",
             "args": {"action": "create", "customer_name": "赵凯",
                      "customer_phone": "13456000919", "items": []},
             "id": "tc_order_create"}
        ]
        return r

    def _final_text_msg(self):
        r = MagicMock(spec=AIMessage)
        r.content = "好的，我为您下单。"
        r.tool_calls = []
        return r

    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.LLMFactory")
    @patch("app.memory.session_memory.SessionMemory")
    async def test_tool_not_found_relocks_and_keeps_pending_skill(
        self, mock_mem_cls, mock_llm_factory, mock_get_breaker,
        mock_set_ctx, mock_create_reg, mock_get_llm
    ):
        """P2+P3：product skill 内 LLM 调 order_create → tool_not_found：
        ① relock 到归属 skill（order）；② 轮末 pending_skill 不被覆盖回 product；
        ③ 工具结果话术给出可执行下一步（不含空头承诺措辞）。"""
        env = self._mock_env([self._tool_call_msg()], [self._final_text_msg()])
        mock_create_reg.return_value = env["registry"]
        mock_get_breaker.return_value = env["breaker"]
        mock_get_llm.return_value = env["llm"]
        mock_llm_factory.create_skill_llm.return_value = env["no_think"]
        mock_mem_cls.return_value = env["mem"]

        state = _make_state()
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_search", "product_detail"],
            system_prompt="你是商品助手",
        )

        # ── P2①：relock 到归属 skill（order）──
        relock_calls = [c.args[1] for c in env["mem"].set_pending_skill.await_args_list
                        if len(c.args) > 1]
        assert "order" in relock_calls, (
            f"tool_not_found 命中订单写工具时必须 relock 到归属 skill，"
            f"实得 set_pending_skill 参数: {relock_calls}"
        )

        # ── P2③：工具结果话术可执行（给下一步动作，不得"稍候即自动提交"式空头承诺）──
        tool_contents = [
            json.loads(m.content)["message"]
            for m in result["messages"]
            if isinstance(m, ToolMessage) and isinstance(m.content, str)
            and m.content.startswith("{")
        ]
        assert tool_contents, "应有 tool_not_found 的工具结果消息"
        combined = "；".join(tool_contents)
        assert "继续" in combined or "再发" in combined or "确认" in combined, (
            f"tool_not_found 话术必须给出可执行下一步，实得: {combined}"
        )
        assert "请稍候" not in combined and "这就提交" not in combined, (
            f"tool_not_found 话术不得空头承诺（旧缺陷形态），实得: {combined}"
        )

        # ── P3：轮末持久化保留 relock 的 pending_skill（不被覆盖回 product）──
        assert relock_calls[-1] != "product", (
            "轮末跨轮持久化把 relock 写入的 pending_skill 覆盖回 product —— "
            "下一轮短消息快捷路由仍走无 order_create 的 skill（DB 实证复发形态）"
        )
        assert result.get("pending_interact_skill") != "product", (
            "graph 状态 pending_interact_skill 被轮末覆盖回 product"
        )
