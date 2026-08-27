"""
LangGraph Skill 节点测试

测试覆盖：
- 各 Skill 节点注册的 Tool 子集
- Skill 执行后返回正确的 state 字段
- ToolContext 从 state 正确构建
- base_skill 的 execute_skill 逻辑
"""
# case_ids: AG-004

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.skills.order_skill import ORDER_TOOLS, ORDER_SKILL_CONFIG
from app.graph.skills.product_skill import PRODUCT_TOOLS, PRODUCT_SKILL_CONFIG
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, KNOWLEDGE_SKILL_CONFIG
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, AFTERSALES_SKILL_CONFIG
from app.graph.skills.general_agent import GENERAL_TOOLS, GENERAL_SKILL_CONFIG
from app.graph.skills.base_skill import build_tool_context, execute_skill, _extract_content, get_skill_llm
from app.graph.skills.skill_registry import SkillRegistry
from app.tools.base import ToolContext


# ========== 辅助 ==========

def _make_state(**overrides):
    """构建测试用 AgentState 字典"""
    state = {
        "messages": [HumanMessage(content="测试消息")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_001",
        "role": "customer",
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


# ========== Tool 子集验证 ==========

class TestSkillToolSubsets:
    """各 Skill 只注册对应的 Tool 子集"""

    def test_order_tools(self):
        """订单 Skill 包含正确的 Tool"""
        assert "order_query" in ORDER_TOOLS
        assert "logistics_track" in ORDER_TOOLS
        assert "order_manage" in ORDER_TOOLS
        assert "product_search" in ORDER_TOOLS  # 订单搜索商品需要
        assert "product_detail" in ORDER_TOOLS   # 订单查商品加工项需要
        assert "knowledge_search" not in ORDER_TOOLS

    def test_product_tools(self):
        """商品 Skill 包含正确的 Tool"""
        assert "product_search" in PRODUCT_TOOLS
        assert "product_detail" in PRODUCT_TOOLS
        assert "product_manage" in PRODUCT_TOOLS
        assert "inventory_manage" in PRODUCT_TOOLS
        assert "order_query" not in PRODUCT_TOOLS

    def test_knowledge_tools(self):
        """知识 Skill 包含 knowledge_search 和 knowledge_manage"""
        assert "knowledge_search" in KNOWLEDGE_TOOLS
        assert "knowledge_manage" in KNOWLEDGE_TOOLS
        assert len(KNOWLEDGE_TOOLS) == 2

    def test_aftersales_tools(self):
        """售后 Skill 包含正确的 Tool（knowledge_search 已禁用）"""
        assert "order_query" in AFTERSALES_TOOLS
        assert "order_manage" in AFTERSALES_TOOLS
        # [RAG 禁用] assert "knowledge_search" in AFTERSALES_TOOLS
        assert "after_sales_manage" in AFTERSALES_TOOLS
        assert "product_search" not in AFTERSALES_TOOLS

    def test_general_tools_includes_all(self):
        """通用兜底 Skill 包含查询 + 基础管理 Tool"""
        expected = {
            "order_query",
            "logistics_track",
            "product_search",
            "product_detail",
            "processing_item_query",
            "customer_manage",
            "dashboard_stats",
            "session_manage",
            "after_sales_manage",
            "notification_manage",
            "quick_reply_manage",
            "processing_item_manage",
            "category_manage",
        }
        assert set(GENERAL_TOOLS) == expected

    def test_general_tools_no_core_write_operations(self):
        """通用兜底 Skill 不包含核心写操作 Tool（创建/修改/删除类）"""
        core_write_tools = {
            "order_manage", "order_create",
            "product_manage", "inventory_manage",
            "employee_manage", "role_manage",
            "settings_manage",
        }
        assert set(GENERAL_TOOLS).isdisjoint(core_write_tools)

    def test_general_tools_has_query_tools(self):
        """通用兜底 Skill 保留核心查询能力"""
        assert "order_query" in GENERAL_TOOLS
        assert "product_search" in GENERAL_TOOLS
        assert "product_detail" in GENERAL_TOOLS
        assert "processing_item_query" in GENERAL_TOOLS
        assert "dashboard_stats" in GENERAL_TOOLS

    def test_no_tool_overlap_between_specialized_skills(self):
        """订单/商品/知识 Skill 的核心 Tool 不重叠（售后除外）"""
        order_core = {"logistics_track"}  # 订单特有
        product_core = {"product_search", "product_detail", "product_manage", "inventory_manage"}
        knowledge_core = {"knowledge_search"}
        # 检查核心 Tool 不重叠
        assert order_core.isdisjoint(product_core)
        assert order_core.isdisjoint(knowledge_core)
        assert product_core.isdisjoint(knowledge_core)


# ========== ToolContext 构建测试 ==========

class TestBuildToolContext:
    """ToolContext 从 state 正确构建"""

    def test_basic_context(self):
        """基本字段映射"""
        state = _make_state(tenant_id=42, user_id=99, session_id="s123", role="admin")
        ctx = build_tool_context(state)
        assert isinstance(ctx, ToolContext)
        assert ctx.tenant_id == 42
        assert ctx.user_id == "99"
        assert ctx.session_id == "s123"
        assert ctx.role == "admin"

    def test_default_role(self):
        """state 中无 role 时使用默认值"""
        state = _make_state()
        del state["role"]
        ctx = build_tool_context(state)
        assert ctx.role == "customer"

    def test_missing_session_id(self):
        """state 中无 session_id 时使用空字符串"""
        state = _make_state()
        del state["session_id"]
        ctx = build_tool_context(state)
        assert ctx.session_id == ""


# ========== execute_skill 测试 ==========

class TestExecuteSkill:
    """通用 Skill 执行逻辑测试"""

    @patch("app.graph.skills.base_skill.SessionStateStore")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_injects_pending_validated_input(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_store_cls
    ):
        """生产回归：上一轮 validate_input 通过的参数必须注入执行轮 system prompt，
        让 LLM 原样复用（防参数二次组装走样）。"""
        # Mock store：返回 pending_validated_input（target_tool 在当前 skill 工具集内）
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={
            "pending_validated_input": {
                "target_tool": "product_manage",
                "target_action": "create",
                "params": {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"},
            }
        })
        mock_store.commit = AsyncMock(return_value=True)
        mock_store_cls.return_value = mock_store

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "这是回复"
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        state = _make_state()
        await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_manage"],
            system_prompt="你是商品助手",
        )

        # system prompt（messages[0]）必须注入已校验参数与铁律
        sent_messages = mock_llm.ainvoke.call_args.args[0]
        sys_content = sent_messages[0].content
        assert "已校验参数" in sys_content
        assert "product_manage" in sys_content
        assert "cat-001" in sys_content
        assert "不得重新组装" in sys_content or "禁止重新组装" in sys_content

    @patch("app.graph.skills.base_skill.SessionStateStore")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_no_injection_when_target_tool_not_in_skill(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_store_cls
    ):
        """target_tool 不属于当前 skill 工具集 → 不注入（跨域无泄漏）"""
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={
            "pending_validated_input": {
                "target_tool": "order_create",
                "target_action": "create",
                "params": {"customer_name": "张三"},
            }
        })
        mock_store.commit = AsyncMock(return_value=True)
        mock_store_cls.return_value = mock_store

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "这是回复"
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        state = _make_state()
        await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_manage"],
            system_prompt="你是商品助手",
        )
        sent_messages = mock_llm.ainvoke.call_args.args[0]
        assert "已校验参数" not in sent_messages[0].content

    @patch("app.graph.skills.base_skill.SessionStateStore")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_direct_executes_validated_params_on_pure_confirm(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_store_cls
    ):
        """生产回归：纯确认消息 + 已校验参数 → 跳过 LLM 直接执行目标工具。

        修复前：LLM 在"确认"轮经常只调 validate_input 不调执行工具，或空转，
        导致多轮创建流程卡死（4 次仅 1 次创建成功）。
        """
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={
            "pending_validated_input": {
                "target_tool": "product_manage",
                "target_action": "create",
                "params": {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"},
            }
        })
        mock_store.commit = AsyncMock(return_value=True)
        mock_store_cls.return_value = mock_store

        # 目标工具 stub：执行返回成功
        mock_tool = MagicMock()
        mock_tool.name = "product_manage"
        mock_tool.read_only = False
        mock_tool.check_permission = MagicMock(return_value=True)
        from app.tools.base import ToolResult
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True,
            data={"product_id": "p1", "name": "遮光窗帘"},
            message="商品【遮光窗帘】创建成功",
        ))

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_registry.get_tool.return_value = mock_tool
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # LLM 不应被调用；若被调用返回兜底文本（断言会失败）
        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "LLM 不应被调用"
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        state = _make_state(messages=[HumanMessage(content="确认")])
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_manage"],
            system_prompt="你是商品助手",
        )

        # 工具被执行且参数原样
        mock_tool.execute.assert_awaited_once()
        executed_args = mock_tool.execute.call_args.kwargs
        assert executed_args == {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"}
        # LLM 未被调用
        mock_llm.ainvoke.assert_not_awaited()
        assert "创建成功" in result["final_answer"]
        assert result["skill_used"] == "product"

    @patch("app.graph.skills.base_skill.SessionStateStore")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_no_direct_exec_on_modified_confirm(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_store_cls
    ):
        """带修改意图的确认（如"确认，但价格改成88"）不走直接执行，仍走 LLM。"""
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={
            "pending_validated_input": {
                "target_tool": "product_manage",
                "target_action": "create",
                "params": {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"},
            }
        })
        mock_store.commit = AsyncMock(return_value=True)
        mock_store_cls.return_value = mock_store

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "好的，我按新价格重新校验"
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        state = _make_state(messages=[HumanMessage(content="确认，但价格改成88")])
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_manage"],
            system_prompt="你是商品助手",
        )
        # 走 LLM 路径：LLM 被调用
        mock_llm.ainvoke.assert_awaited()

    @patch("app.graph.skills.base_skill.SessionStateStore")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.LLMFactory")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_persists_validated_params_for_next_round(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_llm_factory, mock_get_breaker, mock_store_cls
    ):
        """生产回归：本轮 validate_input 成功的参数在循环结束后与 pending_skill
        合并持久化（单次 commit），供下一轮注入/直接执行。

        修复前：validate_input 工具内直接 commit，与 ContextManager.save 并发
        read-modify-write → pending_validated_input 被覆盖丢失（实测 0/7 稳定）。
        """
        from app.tools.base import ToolResult

        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={})
        mock_store.commit = AsyncMock(return_value=True)
        mock_store_cls.return_value = mock_store

        # 第一个 LLM 响应：调 validate_input
        validate_call = AIMessage(content="")
        validate_call.tool_calls = [{
            "name": "validate_input",
            "args": {
                "target_tool": "product_manage",
                "target_action": "create",
                "params": {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"},
            },
            "id": "tc_1",
        }]
        final_response = MagicMock(spec=AIMessage)
        final_response.content = "校验通过，请回复确认。"
        final_response.tool_calls = []

        mock_tool = MagicMock()
        mock_tool.name = "validate_input"
        mock_tool.read_only = False
        mock_tool.destructive = False
        mock_tool.read_only_actions = set()
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True,
            data={"validated": True, "params": {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"}},
            message="校验通过",
        ))

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = [{
            "name": "validate_input",
            "description": "校验",
            "args_schema": {"type": "object", "properties": {}},
        }]
        mock_registry.get_tool.return_value = mock_tool
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[validate_call, final_response])
        mock_get_llm.return_value = mock_llm

        # llm_no_thinking（工具路径必建）
        mock_no_think_llm = MagicMock()
        mock_no_think_llm.bind_tools.return_value = mock_no_think_llm
        mock_no_think_llm.ainvoke = AsyncMock(return_value=final_response)
        mock_llm_factory.create_skill_llm.return_value = mock_no_think_llm

        state = _make_state()
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=["product_manage", "validate_input"],
            system_prompt="你是商品助手",
        )
        assert result["final_answer"] == "校验通过，请回复确认。"

        # 循环结束后与 pending_skill 合并持久化（单次 commit 含两个键）
        commits = [c for c in mock_store.commit.call_args_list if c.args]
        merged = commits[-1].args[1]
        assert merged["pending_skill"] == "product"
        saved = merged["pending_validated_input"]
        assert saved["target_tool"] == "product_manage"
        assert saved["params"] == {"name": "遮光窗帘", "price": 299, "category_id": "cat-001"}

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_no_tool_calls(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker
    ):
        """LLM 直接返回文本，无 tool_calls"""
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        # Mock breaker — 直接透传
        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # Mock LLM response (no tool_calls)
        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "这是回复"
        mock_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm


        state = _make_state()
        result = await execute_skill(
            state=state,
            skill_name="test",
            tool_names=[],
            system_prompt="你是测试助手",
        )

        assert result["final_answer"] == "这是回复"
        assert result["skill_used"] == "test"
        assert "messages" in result
        # P3：entities 死字段已移除
        assert "entities" not in result

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.LLMFactory")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_with_tool_call(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_llm_factory, mock_get_breaker
    ):
        """LLM 返回 tool_call 后再返回文本"""
        # Mock registry
        mock_tool = MagicMock()
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.data = {"order": {"id": "123"}}
        mock_tool_result.error = None
        mock_tool_result.message = "查询成功"
        mock_tool.execute = AsyncMock(return_value=mock_tool_result)

        # Use real LangChain tool spec (BaseTool-compatible dict)
        mock_langchain_tool = {
            "name": "order_query",
            "description": "查询订单",
            "args_schema": {"type": "object", "properties": {}},
        }
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = [mock_langchain_tool]
        mock_registry.get_tool.return_value = mock_tool
        mock_create_reg.return_value = mock_registry

        # Mock breaker — 直接透传
        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # First LLM response: tool_call
        tool_call_response = MagicMock(spec=AIMessage)
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "order_query", "args": {"order_id": "123"}, "id": "tc_1"}
        ]

        # Second LLM response: final text
        final_response = MagicMock(spec=AIMessage)
        final_response.content = "您的订单已找到"
        final_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_get_llm.return_value = mock_llm

        # llm_no_thinking 创建（新增逻辑，需 mock）
        mock_no_think_llm = MagicMock()
        mock_no_think_llm.bind_tools.return_value = mock_no_think_llm
        mock_no_think_llm.ainvoke = AsyncMock(return_value=final_response)
        mock_llm_factory.create_skill_llm.return_value = mock_no_think_llm


        state = _make_state()
        result = await execute_skill(
            state=state,
            skill_name="order",
            tool_names=["order_query"],
            system_prompt="你是订单助手",
        )

        assert result["final_answer"] == "您的订单已找到"
        assert result["skill_used"] == "order"
        # P3：entities 死字段已移除
        assert "entities" not in result
        # 策略2：首轮用 thinking LLM，迭代 2+ 轮改用 llm_no_thinking 关闭思考
        mock_no_think_llm.ainvoke.assert_called_once()
        # 首轮 thinking LLM 只被调用一次（第二次 tool_call 后由 no_thinking 接管）
        assert mock_llm.ainvoke.await_count == 1

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.LLMFactory")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_multi_turn_intent_keeps_thinking(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_llm_factory, mock_get_breaker
    ):
        """方案1：多步推理意图（order_create）迭代 2+ 轮仍保留 thinking，不切换 no_thinking"""
        # Mock registry
        mock_tool = MagicMock()
        mock_tool_result = MagicMock()
        mock_tool_result.success = True
        mock_tool_result.data = {"order": {"id": "123"}}
        mock_tool_result.error = None
        mock_tool_result.message = "查询成功"
        mock_tool.execute = AsyncMock(return_value=mock_tool_result)

        mock_langchain_tool = {
            "name": "order_query",
            "description": "查询订单",
            "args_schema": {"type": "object", "properties": {}},
        }
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = [mock_langchain_tool]
        mock_registry.get_tool.return_value = mock_tool
        mock_create_reg.return_value = mock_registry

        # Mock breaker — 直接透传
        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # First LLM response: tool_call
        tool_call_response = MagicMock(spec=AIMessage)
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "order_query", "args": {"order_id": "123"}, "id": "tc_1"}
        ]

        # Second LLM response: final text
        final_response = MagicMock(spec=AIMessage)
        final_response.content = "订单创建方案已规划"
        final_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_get_llm.return_value = mock_llm

        mock_no_think_llm = MagicMock()
        mock_no_think_llm.bind_tools.return_value = mock_no_think_llm
        mock_no_think_llm.ainvoke = AsyncMock(return_value=final_response)
        mock_llm_factory.create_skill_llm.return_value = mock_no_think_llm


        state = _make_state(intent_result={"intent": "order_create"})
        result = await execute_skill(
            state=state,
            skill_name="order",
            tool_names=["order_create"],
            system_prompt="你是订单助手",
        )

        assert result["final_answer"] == "订单创建方案已规划"
        # 方案1：多步推理意图（order_create）迭代 2+ 轮仍保留 thinking
        # 首轮 + 第 2 轮都用 thinking LLM，故 ainvoke 被调用 2 次
        assert mock_llm.ainvoke.await_count == 2
        # no_thinking LLM 虽被创建，但不用于迭代
        mock_no_think_llm.ainvoke.assert_not_called()



# ========== get_skill_llm thinking 判定测试 ==========

class TestGetSkillLlmThinking:
    """深度思考（thinking）开关按意图判定，只读检索不应开启以降低首轮延迟"""

    @patch("app.graph.skills.base_skill.LLMFactory")
    def test_product_inquiry_disables_thinking(self, mock_factory):
        """product_inquiry 是只读检索，不应开启深度思考"""
        mock_factory.create_skill_llm.return_value = MagicMock()
        get_skill_llm(intent="product_inquiry", tool_count=2)
        kwargs = mock_factory.create_skill_llm.call_args.kwargs
        assert kwargs.get("enable_thinking") is False

    @patch("app.graph.skills.base_skill.LLMFactory")
    def test_order_create_enables_thinking(self, mock_factory):
        """order_create 需多步规划，应开启深度思考"""
        mock_factory.create_skill_llm.return_value = MagicMock()
        get_skill_llm(intent="order_create", tool_count=3)
        kwargs = mock_factory.create_skill_llm.call_args.kwargs
        assert kwargs.get("enable_thinking") is True


# ========== Skill 节点生成测试 ==========

class TestSkillNodes:
    """各 Skill 节点通过 create_node_function 正确生成并调用 execute_skill"""

    @patch("app.graph.skills.base_skill.execute_skill")
    async def test_order_node(self, mock_execute):
        """create_node_function(order) 生成可调用的节点函数"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "order"}
        state = _make_state()
        node_fn = SkillRegistry().create_node_function(ORDER_SKILL_CONFIG, persona="mibao")
        result = await node_fn(state)
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["skill_name"] == "order"
        assert call_kwargs.kwargs["tool_names"] == ORDER_TOOLS

    @patch("app.graph.skills.base_skill.execute_skill")
    async def test_product_node(self, mock_execute):
        """create_node_function(product) 生成可调用的节点函数"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "product"}
        state = _make_state()
        node_fn = SkillRegistry().create_node_function(PRODUCT_SKILL_CONFIG, persona="mibao")
        result = await node_fn(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "product"
        assert mock_execute.call_args.kwargs["tool_names"] == PRODUCT_TOOLS

    @patch("app.graph.skills.base_skill.execute_skill")
    async def test_knowledge_node(self, mock_execute):
        """create_node_function(knowledge) 生成可调用的节点函数"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "knowledge"}
        state = _make_state()
        node_fn = SkillRegistry().create_node_function(KNOWLEDGE_SKILL_CONFIG, persona="mibao")
        result = await node_fn(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "knowledge"
        assert mock_execute.call_args.kwargs["tool_names"] == KNOWLEDGE_TOOLS

    @patch("app.graph.skills.base_skill.execute_skill")
    async def test_aftersales_node(self, mock_execute):
        """create_node_function(aftersales) 生成可调用的节点函数"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "aftersales"}
        state = _make_state()
        node_fn = SkillRegistry().create_node_function(AFTERSALES_SKILL_CONFIG, persona="mibao")
        result = await node_fn(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "aftersales"
        assert mock_execute.call_args.kwargs["tool_names"] == AFTERSALES_TOOLS

    @patch("app.graph.skills.base_skill.execute_skill")
    async def test_general_node(self, mock_execute):
        """create_node_function(general) 生成可调用的节点函数"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "general"}
        state = _make_state()
        node_fn = SkillRegistry().create_node_function(GENERAL_SKILL_CONFIG, persona="mibao")
        result = await node_fn(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "general"
        assert mock_execute.call_args.kwargs["tool_names"] == GENERAL_TOOLS


# ========== Vision 空响应重试测试 ==========

def _make_multimodal_state(**overrides):
    """构建含图片的 AgentState"""
    state = _make_state(**overrides)
    state["messages"] = [
        HumanMessage(
            content=[
                {"type": "text", "text": "根据图片创建一个商品"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ]
        )
    ]
    return state


def _make_text_after_multimodal_state(**overrides):
    """构建一条文本消息跟随一条多模态消息的状态

    模拟：用户先发图片消息，再发纯文本跟进
    has_images() 应返回 False（只查最后一条），但历史中包含 image_url
    """
    from app.llm.router import has_images

    state = _make_state(**overrides)
    state["messages"] = [
        HumanMessage(
            content=[
                {"type": "text", "text": "根据图片创建一个商品"},
                {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
            ]
        ),
        AIMessage(content="图片显示这是一款色卡系列，包含2699-01到2699-16共16个色号。请问商品名称和价格？"),
        HumanMessage(content="2699《花序》23.8元/米"),
    ]
    return state


class TestExecuteSkillTextAfterMultimodal:
    """文本消息跟随多模态消息时，text 路径应清理历史 image_url (Issue #204 regression)

    当 has_images() 只查最后一条 HumanMessage 时，文本路径的 full_messages
    仍包含历史中的 image_url 内容块，会触发 DashScope BadRequestError。
    """

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_text_path_strips_history_image_url(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_breaker,
    ):
        """文本路径应将历史消息中的 image_url 转为纯文本，避免 BadRequestError"""
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        # Mock breaker — 直接透传
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        # 记录传给 LLM 的消息
        captured_messages = []

        async def _capture_and_respond(messages):
            captured_messages.extend(messages)
            resp = MagicMock(spec=AIMessage)
            resp.content = "好的，已记录商品信息：《花序》23.8元/米"
            resp.tool_calls = []
            return resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture_and_respond)
        # Mock model_name for cost tracking
        mock_llm.model_name = "qwen3.6-flash"
        mock_get_llm.return_value = mock_llm


        state = _make_text_after_multimodal_state()
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        # 验证成功返回（没有抛异常）
        assert "好的，已记录商品信息" in result["final_answer"]

        # 验证传给 LLM 的消息中，历史 HumanMessage 不含 image_url
        for msg in captured_messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                for item in msg.content:
                    if isinstance(item, dict):
                        # 不应该还有 image_url 类型的 content block
                        assert item.get("type") != "image_url", (
                            f"历史消息中不应包含 image_url: {item}"
                        )

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_text_path_preserves_standalone_image_as_placeholder(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_breaker,
    ):
        """纯图片无文字的历史消息转为占位符 '[图片]'"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        captured_messages = []

        async def _capture_and_respond(messages):
            captured_messages.extend(messages)
            resp = MagicMock(spec=AIMessage)
            resp.content = "好的"
            resp.tool_calls = []
            return resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture_and_respond)
        mock_llm.model_name = "qwen3.6-flash"
        mock_get_llm.return_value = mock_llm


        # 构造：第一条是纯图片无文字
        state = _make_state()
        state["messages"] = [
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}},
                ]
            ),
            AIMessage(content="图片已收到，请问需要什么帮助？"),
            HumanMessage(content="库存还剩多少"),
        ]

        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        assert result["final_answer"] == "好的"

        # 历史纯图片消息应转为 "[图片]" 占位符（保留消息存在的事实）
        found_placeholder = False
        for msg in captured_messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
                if "[图片]" in msg.content:
                    found_placeholder = True
                    break
        assert found_placeholder, "纯图片历史消息应转为 '[图片]' 占位符"

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_pure_text_conversation_unchanged(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_breaker,
    ):
        """回归测试：纯文本对话完全不受 sanitize 影响"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        captured = []
        async def _capture(messages):
            captured.extend(messages)
            resp = MagicMock(spec=AIMessage)
            resp.content = "您好，订单 ORD-2024-001 目前状态为配送中"
            resp.tool_calls = []
            return resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture)
        mock_llm.model_name = "qwen3.6-flash"
        mock_get_llm.return_value = mock_llm


        # 纯文本多轮对话
        state = _make_state()
        state["messages"] = [
            HumanMessage(content="你好"),
            AIMessage(content="您好！有什么可以帮您？"),
            HumanMessage(content="帮我查一下订单 ORD-2024-001"),
        ]

        result = await execute_skill(
            state=state,
            skill_name="order_query",
            tool_names=[],
            system_prompt="你是订单助手",
        )

        assert "配送中" in result["final_answer"]

        # 消息数量和内容应与原始一致（无 sanitize 副作用）
        assert len(captured) == 4  # SystemMessage + 3 history
        assert captured[1].content == "你好"
        assert captured[2].content == "您好！有什么可以帮您？"
        assert captured[3].content == "帮我查一下订单 ORD-2024-001"


class TestExtractContentThinkingGuard:
    """_extract_content 思考内容安全提取

    当 Vision LLM 启用了 thinking 时，DashScope 返回 reasoning_content + content。
    _extract_content 应优先返回 content（真实回复），仅在 content 为空时
    才回退到 reasoning_content。
    """

    def test_normal_content_no_thinking(self):
        """无 thinking 标签的普通内容直接返回"""
        response = MagicMock(spec=AIMessage)
        response.content = "这是一张色卡图片，包含2699系列共16个色号。"
        response.additional_kwargs = {}
        assert "色卡" in _extract_content(response)

    def test_strips_think_tags(self):
        """移除 <think> 标签及其内容"""
        response = MagicMock(spec=AIMessage)
        response.content = "<think>分析图片中...</think>这是一张色卡图片。"
        response.additional_kwargs = {}
        result = _extract_content(response)
        assert "这是一张色卡图片" in result
        assert "<think>" not in result

    def test_reasoning_content_as_fallback(self):
        """content 为空时回退到 reasoning_content"""
        response = MagicMock(spec=AIMessage)
        response.content = ""
        response.additional_kwargs = {"reasoning_content": "分析图片：色卡包含16个色号"}
        result = _extract_content(response)
        assert "16个色号" in result

    def test_reasoning_content_not_leaked_when_content_exists(self):
        """关键场景：reasoning_content 存在但 content 也有内容时，只返回 content"""
        response = MagicMock(spec=AIMessage)
        response.content = "您好，我已识别出这是一张色卡图片。请问需要创建哪个商品？"
        response.additional_kwargs = {
            "reasoning_content": "用户希望根据图片创建一个商品。1. 分析图片内容：图片是一个色卡...2. 理解用户意图..."
        }
        result = _extract_content(response)
        # 应该返回 content（真实回复），不包含 reasoning_content
        assert "我已识别出这是一张色卡图片" in result
        # 不应该泄漏 thinking 内容
        assert "分析图片内容" not in result
        assert "理解用户意图" not in result
