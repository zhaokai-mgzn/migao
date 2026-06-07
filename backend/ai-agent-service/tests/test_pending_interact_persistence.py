"""
验证 pending_interact_skill 跨 graph 调用持久化

Bug: _build_initial_state 每次创建全新 state，不加载上一轮的 pending_interact_skill
修复: SessionMemory.set/get/clear_pending_skill → sessions.metadata JSONB
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from langchain_core.messages import HumanMessage
from app.memory.session_memory import SessionMemory
from app.graph.skills.base_skill import execute_skill


async def _create_test_session(mem: SessionMemory, session_id: str, tenant_id: int = 1, user_id: str = "user_superadmin") -> str:
    """创建测试用 session，返回 session_id"""
    sid = await mem.create_session(
        tenant_id=tenant_id,
        customer_id=user_id,
        title="[测试] pending_skill 持久化验证",
    )
    return sid


# ===================================================================
# Part 1: SessionMemory 持久化（直接验证 DB 读写）
# ===================================================================

class TestSessionMemoryPersistence:
    """验证 set/get/clear 方法正确读写 DB sessions.metadata"""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        mem = SessionMemory()
        sid = await _create_test_session(mem, "sess_test_persist_setget")
        try:
            await mem.set_pending_skill(sid, "product")
            assert await mem.get_pending_skill(sid) == "product"
        finally:
            await mem.clear_pending_skill(sid)

    @pytest.mark.asyncio
    async def test_clear(self):
        mem = SessionMemory()
        sid = await _create_test_session(mem, "sess_test_persist_clear")
        try:
            await mem.set_pending_skill(sid, "order")
            await mem.clear_pending_skill(sid)
            assert await mem.get_pending_skill(sid) == ""
        finally:
            await mem.clear_pending_skill(sid)

    @pytest.mark.asyncio
    async def test_overwrite(self):
        mem = SessionMemory()
        sid = await _create_test_session(mem, "sess_test_persist_overwrite")
        try:
            await mem.set_pending_skill(sid, "product")
            await mem.set_pending_skill(sid, "order")
            assert await mem.get_pending_skill(sid) == "order"
        finally:
            await mem.clear_pending_skill(sid)

    @pytest.mark.asyncio
    async def test_nonexistent_returns_empty(self):
        mem = SessionMemory()
        assert await mem.get_pending_skill("sess_nonexistent_999") == ""

    @pytest.mark.asyncio
    async def test_multiple_sessions_independent(self):
        """不同 session 的 pending_skill 互不干扰"""
        mem = SessionMemory()
        sid_a = await _create_test_session(mem, "sess_test_persist_A")
        sid_b = await _create_test_session(mem, "sess_test_persist_B")
        try:
            await mem.set_pending_skill(sid_a, "product")
            await mem.set_pending_skill(sid_b, "order")

            assert await mem.get_pending_skill(sid_a) == "product"
            assert await mem.get_pending_skill(sid_b) == "order"

            await mem.clear_pending_skill(sid_a)
            assert await mem.get_pending_skill(sid_a) == ""
            assert await mem.get_pending_skill(sid_b) == "order"  # B 不受影响
        finally:
            await mem.clear_pending_skill(sid_a)
            await mem.clear_pending_skill(sid_b)


# ===================================================================
# Part 2: 完整三步交互场景复现
# ===================================================================

@pytest.mark.asyncio
class TestThreeStepInteractFlow:
    """
    复现用户报告的场景:
      form(收集商品信息) → choice(选择加工项) → confirm(确认创建)
    每步的 pending_skill 都应持久化，最终一步正确路由到 product_skill
    """

    async def test_flow_persistence(self):
        mem = SessionMemory()
        sid = await _create_test_session(mem, "sess_test_three_step")

        try:
            # 确保初始干净
            assert await mem.get_pending_skill(sid) == ""

            # Step 1: form 提交 → LLM 调 interact(form) → pending = product
            await mem.set_pending_skill(sid, "product")
            assert await mem.get_pending_skill(sid) == "product"

            # Step 2: form 数据到达 → graph 加载 pending=product → 路由到 product_skill
            #         LLM 调 interact(choice) → pending 继续 = product
            loaded = await mem.get_pending_skill(sid)
            assert loaded == "product", "Step 2: 应能从 DB 加载 pending_skill"
            await mem.set_pending_skill(sid, "product")  # 续期

            # Step 3: choice 选择到达 → graph 加载 pending=product → 路由到 product_skill
            #         LLM 调 product_manage → no interact → clear pending
            loaded = await mem.get_pending_skill(sid)
            assert loaded == "product", "Step 3: 应仍能从 DB 加载 pending_skill"
            await mem.clear_pending_skill(sid)

            # 最终验证清除
            assert await mem.get_pending_skill(sid) == ""
        finally:
            await mem.clear_pending_skill(sid)


# ===================================================================
# Part 3: execute_skill 同步持久化（mock LLM + 真实 SessionMemory DB）
# ===================================================================

def _make_state(session_id, **overrides):
    """构建测试用 state dict"""
    s = {
        "messages": [HumanMessage(content="创建商品")],
        "tenant_id": 1, "user_id": 100, "user_name": "test",
        "session_id": session_id, "role": "admin",
        "agent_type": "mibao",
        "intent_result": {
            "intent": "product_inquiry", "confidence": 0.95, "source": "rule"
        },
        "route_decision": {"action": "full_agent"},
        "entities": {}, "intent_chain": [], "stage": "initial",
        "cached_answer": None, "final_answer": "", "skill_used": "",
        "suggestions": [],
    }
    s.update(overrides)
    return s


class TestExecuteSkillStateLogic:
    """验证 execute_skill 的 pending_skill 状态逻辑（不需要 DB）"""

    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_interact_writes_to_db(
        self, _set_ctx, _create_reg, _get_tracker
    ):
        """interact 成功后 execute_skill 应写 pending_skill 到 DB"""
        mem = SessionMemory()
        sid = await _create_test_session(mem, "sess_test_exec_writedb")

        try:
            # Mock interact tool
            tool = MagicMock()
            tool_result = MagicMock()
            tool_result.success = True
            tool_result.data = {"component": "form", "title": "创建商品"}
            tool_result.error = None
            tool_result.message = "ok"
            tool.execute = AsyncMock(return_value=tool_result)

            reg = MagicMock()
            reg.get_langchain_tools.return_value = [MagicMock()]
            reg.get_tool.return_value = tool
            _create_reg.return_value = reg

            # Mock LLM → 调 interact
            resp = MagicMock()
            resp.content = "请填写信息"
            resp.tool_calls = [
                {"name": "interact", "args": {"component": "form", "title": "test"}, "id": "t1"}
            ]

            with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_fn:
                llm = MagicMock()
                llm.bind_tools.return_value = llm
                llm.ainvoke = AsyncMock(return_value=resp)
                mock_llm_fn.return_value = llm

                trk = MagicMock()
                ent = MagicMock()
                for a in ("order_nos", "phone_numbers", "product_names",
                          "product_ids", "amounts"):
                    setattr(ent, a, [])
                trk.get_entities.return_value = ent
                _get_tracker.return_value = trk

                result = await execute_skill(
                    state=_make_state(sid),
                    skill_name="product",
                    tool_names=["interact"],
                    system_prompt="你是商品助手",
                )

            # 验证 state 中有 pending_skill
            assert result.get("pending_interact_skill") == "product", (
                f"state 中应有 'product', 实际: {result.get('pending_interact_skill')}"
            )
            # 验证 DB 中也持久化了
            assert await mem.get_pending_skill(sid) == "product", (
                "DB 中应有 'product'（interact 成功后必须持久化）"
            )
        finally:
            await mem.clear_pending_skill(sid)

    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_no_interact_clears_db(
        self, _set_ctx, _create_reg, _get_tracker
    ):
        """上一轮有 pending，本轮不调 interact → DB 清除"""
        sid = "sess_test_exec_cleardb"
        mem = SessionMemory()

        # 模拟上一轮 persist
        await mem.set_pending_skill(sid, "product")

        try:
            reg = MagicMock()
            reg.get_langchain_tools.return_value = []
            _create_reg.return_value = reg

            resp = MagicMock()
            resp.content = "已创建"
            resp.tool_calls = []

            with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_fn:
                llm = MagicMock()
                llm.bind_tools.return_value = llm
                llm.ainvoke = AsyncMock(return_value=resp)
                mock_llm_fn.return_value = llm

                trk = MagicMock()
                ent = MagicMock()
                for a in ("order_nos", "phone_numbers", "product_names",
                          "product_ids", "amounts"):
                    setattr(ent, a, [])
                trk.get_entities.return_value = ent
                _get_tracker.return_value = trk

                result = await execute_skill(
                    state=_make_state(sid, pending_interact_skill="product"),
                    skill_name="product",
                    tool_names=[],
                    system_prompt="你是商品助手",
                )

            assert result.get("pending_interact_skill") == "", (
                f"应清除, 实际: {result.get('pending_interact_skill')}"
            )
            assert await mem.get_pending_skill(sid) == "", (
                "DB 应清除 pending_skill"
            )
        finally:
            await mem.clear_pending_skill(sid)
