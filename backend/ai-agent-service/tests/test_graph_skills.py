"""
LangGraph Skill 节点测试

测试覆盖：
- 各 Skill 节点注册的 Tool 子集
- Skill 执行后返回正确的 state 字段
- ToolContext 从 state 正确构建
- base_skill 的 execute_skill 逻辑
"""
# case_ids: AG-004, CH-003, CH-023, MC-008, DF-018, HR-005, CU-003, CH-010, CH-012, OR-017, OR-021, OR-022

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from app.graph.skills.order_skill import ORDER_TOOLS, ORDER_SKILL_CONFIG
from app.graph.skills.product_skill import PRODUCT_TOOLS, PRODUCT_SKILL_CONFIG
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, KNOWLEDGE_SKILL_CONFIG
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, AFTERSALES_SKILL_CONFIG
from app.graph.skills.general_agent import GENERAL_TOOLS, GENERAL_SKILL_CONFIG
from app.graph.skills.base_skill import (
    build_tool_context, execute_skill, _extract_content, get_skill_llm,
    _masked_phone_write_block, KNOWN_RAW_PHONES_KEY, _capability_denial_reason,
    capability_denial_text_hit,
    _confirm_card_seen,
    _conversation_mentions_dimensions, _form_prefill_fidelity_block,
    _stated_purchase_quantities, _quantity_choice_block,
    _curtain_calc_dimension_block, _should_code_close_loop,
)
import app.graph.skills.base_skill as lr2
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
        # PP-006 回归防线：processing_manage 意图路由到 product_skill（intents 配置），
        # 但 PRODUCT_TOOLS 曾缺 processing_item_manage → agent 说「只有查询加工项能力」
        # （工具列表里确实没有创建加工项的工具，能力误宣的架构根因）
        assert "processing_item_manage" in PRODUCT_TOOLS
        assert "order_query" not in PRODUCT_TOOLS

    def test_knowledge_tools(self):
        """知识 Skill 绑定 knowledge_search + processing_item_query（issue #3085：加工计价走工具实时查询；knowledge_manage 管理操作走 admin-web，不注册工具）"""
        assert "knowledge_search" in KNOWLEDGE_TOOLS
        assert "processing_item_query" in KNOWLEDGE_TOOLS
        assert "knowledge_manage" not in KNOWLEDGE_TOOLS
        assert len(KNOWLEDGE_TOOLS) == 2

    def test_aftersales_tools(self):
        """售后 Skill 包含正确的 Tool（knowledge_search 已禁用）"""
        assert "order_query" in AFTERSALES_TOOLS
        assert "order_manage" in AFTERSALES_TOOLS
        # [RAG 禁用] assert "knowledge_search" in AFTERSALES_TOOLS
        assert "after_sales_manage" in AFTERSALES_TOOLS
        assert "product_search" not in AFTERSALES_TOOLS

    def test_general_tools_includes_all(self):
        """通用兜底 Skill 包含查询 + 基础管理 Tool + interact（澄清卡承载，Phase 2 #2789）"""
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
            "processing_item_manage",
            "category_manage",
            "interact",
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

    @patch("app.memory.session_memory.SessionMemory")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_staff_skill_sets_pending_on_incomplete(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_mem_cls
    ):
        """HR-005 回归：staff 域创建流程未完成时必须锁 pending_skill，
        否则用户后续轮补信息时重新路由被关键词误判跳域（此前 creation_skills 缺 staff）。"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "请补充权限信息"  # 未完成（无成功 marker）
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        mock_mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

        state = _make_state()
        result = await execute_skill(
            state=state, skill_name="staff", tool_names=[], system_prompt="你是人事助手",
        )
        assert result["pending_interact_skill"] == "staff"

    @patch("app.memory.session_memory.SessionMemory")
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_customer_skill_sets_pending_on_incomplete(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker, mock_mem_cls
    ):
        """CU-003 回归：customer 域写流程未完成时锁 pending_skill。"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry
        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker
        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "请确认要操作哪一位客户"  # 未完成
        mock_response.tool_calls = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm
        mock_mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

        state = _make_state()
        result = await execute_skill(
            state=state, skill_name="customer", tool_names=[], system_prompt="你是客户助手",
        )
        assert result["pending_interact_skill"] == "customer"

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_long_session_no_length_hint_appended_to_user_msg(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_breaker
    ):
        """长会话（>20 条消息）时最后一条用户消息不被附加任何提示文本。

        回归背景（sess_c1fce183dae24f22 复盘）：旧实现把「当前对话已持续 N 轮」
        的会话长度提示直接拼在最新 HumanMessage 的 content 后面，污染了
        _is_explicit_confirmation 的判定输入（长度 > 24 无法识别为确认），
        导致长会话中写操作确认被反复拦截、确认死循环。

        修复后：不再计算/拼接会话长度提示，用户消息原样保留。
        """
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

        # 构造 >20 条消息的长会话，最后一条是用户确认消息（模拟真实死循环现场）
        messages = []
        for i in range(22):
            messages.append(HumanMessage(content=f"用户消息{i}"))
            messages.append(AIMessage(content=f"助手回复{i}"))
        messages.append(HumanMessage(content="确认补充商品属性"))

        state = _make_state(messages=messages)
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        assert result["final_answer"] == "这是回复"
        # 关键断言：最后一条用户消息未被附加「会话长度」提示（confirm 判定不受污染）
        last_content = state["messages"][-1].content
        assert last_content == "确认补充商品属性", f"用户消息被附加了提示: {last_content!r}"
        assert "当前对话已持续" not in str(last_content)
        # 确认词仍能被确认守卫识别
        from app.graph.skills.base_skill import _is_explicit_confirmation
        assert _is_explicit_confirmation(str(last_content)) is True

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

    @patch("app.graph.skills.base_skill.LLMFactory")
    def test_role_manage_enables_thinking(self, mock_factory):
        """role_manage 创建角色是多步写操作（查权限→选权限→确认→create），应开深度思考
        （HR-005 无思考致多意图路由误判 + 参数漏传）。"""
        mock_factory.create_skill_llm.return_value = MagicMock()
        get_skill_llm(intent="role_manage", tool_count=3)
        kwargs = mock_factory.create_skill_llm.call_args.kwargs
        assert kwargs.get("enable_thinking") is True

    @patch("app.graph.skills.base_skill.LLMFactory")
    def test_category_manage_enables_thinking(self, mock_factory):
        """category_manage 建品分类选择是多步流程，应开深度思考。"""
        mock_factory.create_skill_llm.return_value = MagicMock()
        get_skill_llm(intent="category_manage", tool_count=2)
        kwargs = mock_factory.create_skill_llm.call_args.kwargs
        assert kwargs.get("enable_thinking") is True

    @patch("app.graph.skills.base_skill.LLMFactory")
    def test_customer_manage_enables_thinking(self, mock_factory):
        """customer_manage 客户写操作（重名澄清→选→确认）应开深度思考（CU-003/004）。"""
        mock_factory.create_skill_llm.return_value = MagicMock()
        get_skill_llm(intent="customer_manage", tool_count=3)
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


class TestVisionClarifyGuide:
    """Phase 1（issue #2777）：多模态输入的意图澄清引导

    用户随手发图（可能不带文字/带口语短句）时，vision prompt 注入段必须引导模型：
    1. 先呈现"我的理解"（图里是什么 + 可能的用途）
    2. 意图模糊时给出候选意图让用户确认（不硬猜直接执行）
    对应 G2/G3 缺口与低学历用户场景（docs/design/agent-clarification-capability-research.md §6 Phase 1）。
    """

    @pytest.fixture(autouse=True)
    def _capture(self):
        """构造 mock：拦截传给 LLM 的 messages，返回无 tool 的空回复"""
        captured = []

        async def _capture_and_respond(messages):
            captured.extend(messages)
            resp = MagicMock(spec=AIMessage)
            resp.content = "好的，我明白了。"
            resp.tool_calls = []
            return resp

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture_and_respond)
        mock_llm.model_name = "qwen3.6-flash"

        patchers = [
            patch("app.graph.skills.base_skill.create_skill_registry", return_value=mock_registry),
            patch("app.graph.skills.base_skill.set_tool_context"),
            patch("app.graph.skills.base_skill.get_breaker", return_value=mock_breaker),
            patch("app.graph.skills.base_skill.get_skill_llm", return_value=mock_llm),
        ]
        for p in patchers:
            p.start()
        self.captured = captured
        yield
        for p in patchers:
            p.stop()

    async def test_multimodal_prompt_includes_clarify_guide(self):
        """多模态 system prompt 必须包含意图澄清引导（图片≠直接下单指令）"""
        from app.graph.skills.base_skill import VISION_CLARIFY_GUIDE

        captured = self.captured
        state = _make_multimodal_state()
        await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        # 校验常量存在且完整（防误删）
        assert "我的理解" in VISION_CLARIFY_GUIDE
        assert "候选意图" in VISION_CLARIFY_GUIDE

        # 校验注入到 system prompt（首条 SystemMessage）
        system_msgs = [m for m in captured if isinstance(m, SystemMessage)]
        assert system_msgs, "应存在 SystemMessage"
        joined = "\n".join(getattr(m, "content", "") or "" for m in system_msgs)
        assert "候选意图" in joined, "多模态 system prompt 缺少澄清引导段"

    async def test_text_path_does_not_inject_clarify_guide(self):
        """纯文本路径不应注入图片澄清引导（防无关上下文膨胀）"""
        captured = self.captured
        state = _make_state()
        state["messages"] = [HumanMessage(content="帮我查一下订单")]
        await execute_skill(
            state=state,
            skill_name="order",
            tool_names=[],
            system_prompt="你是订单助手",
        )
        system_msgs = [m for m in captured if isinstance(m, SystemMessage)]
        joined = "\n".join(getattr(m, "content", "") or "" for m in system_msgs)
        assert "候选意图" not in joined, "纯文本路径不应注入图片澄清引导"


class TestVisionGroundedGuide:
    """Phase 2c（issue #2799）：图片澄清候选 grounded 到店铺真实商品"""

    def test_guide_contains_grounded_instruction(self):
        """VISION_CLARIFY_GUIDE 必须引导商品类候选先检索真实商品（不编造）。"""
        from app.graph.skills.base_skill import VISION_CLARIFY_GUIDE
        assert "product_search" in VISION_CLARIFY_GUIDE, "澄清引导缺 grounded 检索指令"
        assert "编造" in VISION_CLARIFY_GUIDE, "澄清引导缺不编造约束"
        assert "没搜到" in VISION_CLARIFY_GUIDE, "澄清引导缺无命中兜底话术"


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


class TestCustomerSkillPendingLock:
    """C 端（小布）多轮流程必须锁 pending_skill —— 否则第二轮就跳出 Skill

    根因（CI 实证 run 34613307565，CH-012）：
    `creation_skills = {"product","order","aftersales","staff","customer"}` 里**全是 B 端
    Skill 名**，而小布的 Skill 叫 `customer_order` / `customer_aftersales` /
    `customer_product` / `customer_quote` —— 名字对不上 → **C 端多轮流程从不锁
    pending_skill** → 用户第二轮说「第一笔订单」「数量 3 米」「确认下单」这类碎片时被
    重新意图分类 → 跳出原 Skill：

        路由 dump: R1 intent=after_sales → aftersales   ← 正确进入
                   R2 intent=order_query → order        ← 第二轮就跳走

    后果：上下文断裂，退货/下单流程反复从头开始（CH-010 4 轮、OR-014 7 轮反复重来）。
    这是「名字不匹配」型缺陷 —— 类型系统查不出来，只有行为测试能拦住。
    """

    def _run(self, skill_name: str, content: str = "请补充信息") -> dict:
        import asyncio

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            from app.tools.product_detail import ProductDetailTool
            from app.tools.interact import InteractTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: {
                "product_detail": ProductDetailTool(),
                "interact": InteractTool(),
            }.get(n)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            response = MagicMock(spec=AIMessage)
            response.content = content  # 无成功 marker → 流程未完成
            response.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(return_value=response)
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            # 用 asyncio.run（新建 loop）而非 get_event_loop().run_until_complete：
            # 后者在**全量跑**时会被别的用例关掉/取消当前 loop →
            # RuntimeError: There is no current event loop（单独跑本文件却通过，
            # 典型的测试隔离缺陷 —— 全量跑才暴露）。
            return asyncio.run(
                execute_skill(state=_make_state(), skill_name=skill_name,
                              tool_names=[], system_prompt="你是小布")
            )

    @pytest.mark.parametrize("skill_name", ["customer_order", "customer_aftersales"])
    def test_customer_write_flow_locks_pending_when_incomplete(self, skill_name):
        result = self._run(skill_name)
        assert result["pending_interact_skill"] == skill_name, (
            f"{skill_name} 未锁 pending_skill —— 用户第二轮补充信息会被重新路由跳出该 Skill"
        )

    @pytest.mark.parametrize("skill_name", [
        "customer_product", "customer_quote", "customer_general", "customer_knowledge",
    ])
    def test_readonly_customer_skills_do_not_lock(self, skill_name):
        """**只读**查询/选品/算料/问答 Skill 不得锁 —— 锁住会把用户困在里面出不来

        `customer_product` 没有 `order_create`：CH-010 的 R4「确认下单」正是要
        **切到 customer_order** 才能落单。锁住它 → 用户卡在只读 Skill 里 → 下单永远不发生。
        （该边界是本次修复的**反向**约束：只锁写流程，不锁只读流程。）
        """
        result = self._run(skill_name)
        assert result.get("pending_interact_skill", "") in ("", None), (
            f"{skill_name} 不应锁 pending_skill"
        )

    def test_lock_set_matches_write_flow_skills_systemically(self):
        """系统性不变式：C 端**含需确认写工具**的 Skill 必须锁，其余必须不锁

        从工具注册表**推导**"该不该锁"，而不是抄一份名单 —— 这样新增 C 端写流程
        Skill 时（或给只读 Skill 加写工具时）本测试会主动拦住，而不是等 CI 跑出
        「第二轮跳出 Skill」再回头查（本次缺陷就是这么来的：名单只写了 B 端名，
        类型系统与静态检查都看不出来）。
        """
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        from app.graph.skills.base_skill import CREATION_SKILL_NAMES
        from app.graph.skills.skill_registry import get_skill_registry
        from app.tools.registry import get_tool_registry

        skill_reg = get_skill_registry()
        tool_reg = get_tool_registry()
        should_lock, should_not_lock, missing_tool = [], [], []

        for name in XIAOBU_CONFIG.get_all_skill_names():
            config = skill_reg.get(name)
            if config is None:
                continue
            binds_write = False
            for tool_name in (config.tool_names or []):
                tool = tool_reg.get_tool(tool_name)
                if tool is None:
                    missing_tool.append(f"{name}.{tool_name}")
                    continue
                # 判据 = **需确认的写工具**（destructive / requires_confirmation）：
                # 这类工具的 validate→confirm→execute 链条天然跨轮，必须锁。
                # 刻意不用 `not read_only`：那会把 human_handoff 这类**一次性**写操作
                # 也算进来（customer_general 就会被误判成写流程 —— 实测踩到），
                # 进而把用户锁在兜底 Skill 里。
                if (getattr(tool, "destructive", False)
                        or getattr(tool, "requires_confirmation", False)):
                    binds_write = True
            (should_lock if binds_write else should_not_lock).append(name)

        assert not missing_tool, f"Skill 绑定了未注册工具：{missing_tool}"
        assert should_lock, "推导出的写流程 Skill 为空 —— 解析疑似失效（测试会空转假绿）"

        unlocked = [n for n in should_lock if n not in CREATION_SKILL_NAMES]
        over_locked = [n for n in should_not_lock if n in CREATION_SKILL_NAMES]
        assert not unlocked, (
            f"以下 C 端 Skill 含写工具但未锁 pending_skill，多轮写流程会在第二轮被"
            f"重新分类跳走：{unlocked}（加入 CREATION_SKILL_NAMES）"
        )
        assert not over_locked, (
            f"以下 C 端 Skill 是只读的却被锁住，用户会困在里面切不到下单域：{over_locked}"
            f"（从 CREATION_SKILL_NAMES 移除）"
        )

    def test_backend_names_still_lock(self):
        """B 端行为不回归"""
        result = self._run("staff")
        assert result["pending_interact_skill"] == "staff"


class TestConfirmGateGuidance:
    """确认门禁的话术必须**可执行**：Skill 没绑 `interact` 时不能说"请调用 interact"

    背景（issue #3317）：`_requires_confirmation` 拦截未确认写操作时固定返回
    「请调用 interact（component=confirm）展示操作预览」—— 但 B 端 `staff`/`settings`/
    `data` 三个 Skill **没有绑定 `interact`**，这条指令对 LLM 是**不可执行的**。
    实测现象：模型拿到"请调用 X"却没有 X，反复重试或直接放弃。

    为什么不给这些 Skill 直接补 `interact`（issue #3317 的另一种解法）：
    证据不支持 —— 用例库里涉及这 6 个工具的 16 条用例**没有一条**断言 `interact`
    （含 smoke 的 HR-001/HR-004，它们靠**口头确认**走通并长期通过）。
    补工具会改变 B 端交互形态（可能开始弹卡），而 B 端 105 条用例只能在
    手动、面向生产的评测里验证 —— 收益不明而回归面很大。
    故采取"**让话术与能力匹配**"：有 `interact` → 要求弹卡；没有 → 要求文本复述+口头确认。
    """

    def _gate_result(self, *, has_interact: bool):
        """跑一次带写工具的 execute_skill，捕获确认门禁返回的 message"""
        import asyncio
        from types import SimpleNamespace

        from app.tools.base import BaseTool, ToolResult

        class _WriteTool(BaseTool):
            name = "amazing_write"
            description = "写操作（测试用）"
            read_only = False
            requires_confirmation = True
            parameters = {"type": "object", "properties": {}}

            async def execute(self, context, **kwargs):
                return ToolResult(success=True, data={}, message="done")

        class _Interact(BaseTool):
            name = "interact"
            description = "交互卡片"
            read_only = True
            parameters = {"type": "object", "properties": {}}

            async def execute(self, context, **kwargs):
                return ToolResult(success=True, data={}, message="card")

        captured = {}

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            tools = {"amazing_write": _WriteTool()}
            if has_interact:
                tools["interact"] = _Interact()

            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tools.get(n)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            # 第一轮返回写工具调用（未确认 → 必被门禁拦），第二轮收尾
            call_msg = MagicMock(spec=AIMessage)
            call_msg.content = ""
            call_msg.tool_calls = [{"name": "amazing_write", "args": {}, "id": "c1"}]
            end_msg = MagicMock(spec=AIMessage)
            end_msg.content = "好的"
            end_msg.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call_msg, end_msg])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            async def _fake_execute(tool, args, ctx, state):
                # 模拟门禁：不真正执行，直接把门禁消息回传（真实路径由 _run_one_tool 内部判断）
                captured["called"] = True
                return "", {}

            with patch("app.graph.skills.base_skill._execute_tool_safe", _fake_execute):
                result = asyncio.run(execute_skill(
                    state=_make_state(messages=[HumanMessage(content="删了这个员工")]),
                    skill_name="staff", tool_names=list(tools.keys()),
                    system_prompt="你是人事助手",
                ))
        return result, captured

    def test_gate_message_requires_card_when_interact_available(self):
        """有 interact → 指引弹卡。

        ⚠️ 断言必须落在**门禁消息的特征串**（`component=confirm`）上，不能只查
        `"interact" in str(result)` —— 结果里包含 system prompt 与历史消息，
        `interact` 一词可能来自别处，那样「永远走 else 分支」也能通过（首版即此假绿，
        被变异测试 M2 抓出）。
        """
        result, _ = self._gate_result(has_interact=True)
        blob = str(result)
        assert "component=confirm" in blob, "有 interact 时应指引弹卡确认"
        assert "完整复述" not in blob, "有 interact 时不应走文本复述分支"

    def test_gate_message_does_not_demand_unavailable_tool(self):
        result, _ = self._gate_result(has_interact=False)
        blob = str(result)
        assert "component=confirm" not in blob, (
            "Skill 未绑定 interact 时，门禁不能说「请调用 interact（component=confirm）」——"
            "那是不可执行指令，会让模型反复重试或放弃（issue #3317）"
        )
        assert "完整复述" in blob, "应改为要求用文本完整复述操作并请用户回复确认"


class TestProcessingItemsFallback:
    """加工项漏问代码兜底（OR-017 抖动根因，模式 C 代码管）

    业务铁律「商品有加工项 → confirm 前必须先问」只在 prompt/工具描述里时，
    约 1/3 轮次 LLM 会漏掉（CI 实证 run 34622425044 ✅ / 34626024229 ❌ /
    34662285260 ❌，**同代码同用例**）。本兜底把「先问加工项」变成**确定性**：
    检测到 confirm 卡而加工项未问 → 把该卡改写为加工项 choice 卡。
    """

    def _result(self, name, data, success=True):
        return ({"name": name, "args": {}, "id": "x"},
                json.dumps({"success": success, "data": data}),
                {"success": success, "data": data})

    def _detail_msg(self, items):
        payload = {"success": True, "data": {"processing_items": items}}
        return ToolMessage(content=json.dumps(payload, ensure_ascii=False),
                           tool_call_id="d1", name="product_detail")

    def _user(self, text):
        return HumanMessage(content=text)

    def test_rewrites_confirm_to_choice_when_items_unasked(self):
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0, "unit": "米",
                  "pricingMethod": "per_meter"}]
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm], [self._user("帮我下单"), self._detail_msg(items)])
        assert plan is not None
        idx, data = plan
        assert idx == 0
        assert data["component"] == "choice"
        assert data["multiSelect"] is True
        assert data["options"][0]["value"] == "proc_item_pi1"
        assert "打孔" in data["options"][0]["label"]

    def test_no_rewrite_when_processing_choice_already_emitted(self):
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0}]
        choice = self._result("interact", {"component": "choice", "multiSelect": True,
                                           "title": "加工项", "options": [{"value": "proc_item_pi1"}]})
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [choice, confirm], [self._user("帮我下单"), self._detail_msg(items)])
        assert plan is None, "已问过加工项 → 不得改写"

    def test_no_rewrite_when_user_declined(self):
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0}]
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm], [self._user("不需要加工项"), self._detail_msg(items)])
        assert plan is None, "顾客明确拒绝过 → 不得硬弹卡"

    def test_no_rewrite_without_confirm(self):
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0}]
        choice = self._result("interact", {"component": "choice", "title": "选颜色",
                                           "options": [{"value": "white"}]})
        plan = lr2._plan_processing_items_rewrite(
            [choice], [self._user("选品"), self._detail_msg(items)])
        assert plan is None

    def test_no_rewrite_without_product_detail(self):
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm], [self._user("确认下单")])
        assert plan is None, "没有加工项数据不得改写"

    def test_rewrite_works_cross_turn(self):
        """product_detail 与 confirm 跨轮（OR-017 实测形态：R1 查详情、R2 发卡）"""
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0},
                 {"id": "pi2", "name": "折边", "unitPrice": 12.0}]
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm], [self._user("确认下单"), self._detail_msg(items)])
        assert plan is not None
        assert len(plan[1]["options"]) == 2

    def test_options_capped(self):
        items = [{"id": f"p{i}", "name": f"n{i}", "unitPrice": i} for i in range(20)]
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm], [self._user("下单"), self._detail_msg(items)])
        assert plan is not None and len(plan[1]["options"]) <= 6

    def test_decline_detection_uses_last_user_message(self):
        """拒绝判定只看**最近一条**用户消息（更早的"不需要"不算）"""
        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0}]
        confirm = self._result("interact", {"component": "confirm", "fields": []})
        plan = lr2._plan_processing_items_rewrite(
            [confirm],
            [self._user("不需要加工项"), self._user("那就确认下单吧"), self._detail_msg(items)])
        assert plan is not None, "最近一条用户消息没有拒绝 → 应改写"


class TestProcessingItemsFallbackWiring:
    """兜底的**接线**必须在 execute_skill 里真正生效（不只纯函数对）"""

    def _run_execute(self):
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        items = [{"id": "pi1", "name": "打孔", "unitPrice": 8.0, "unit": "米",
                  "pricingMethod": "per_meter"}]

        async def fake_execute(tool, args, ctx, state):
            if tool.name == "product_detail":
                return (json.dumps({"success": True, "data": {"processing_items": items}}),
                        {"success": True, "data": {"processing_items": items}})
            if tool.name == "interact":
                return (json.dumps({"success": True,
                                    "data": {"component": "confirm", "fields": []}}),
                        {"success": True, "data": {"component": "confirm", "fields": []}})
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            from app.tools.product_detail import ProductDetailTool
            from app.tools.interact import InteractTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: {
                "product_detail": ProductDetailTool(),
                "interact": InteractTool(),
            }.get(n)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            # 第 1 次 LLM 调用：product_detail；第 2 次：interact(confirm)；第 3 次：收尾文本
            def make_call(name, args):
                m = MagicMock(spec=_AI)
                m.content = ""
                m.tool_calls = [{"name": name, "args": args, "id": "t1"}]
                return m

            final = MagicMock(spec=_AI)
            final.content = "好的，为您确认订单"
            final.tool_calls = []

            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[
                make_call("product_detail", {"id": "prod_x"}),
                make_call("interact", {"component": "confirm", "fields": []}),
                final,
            ])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            state = _make_state(messages=[
                HumanMessage(content="我要买夏日清风窗帘，确认下单"),
                ToolMessage(content=json.dumps({"success": True,
                                                "data": {"processing_items": items}}),
                            tool_call_id="d0", name="product_detail"),
            ])
            return asyncio.run(execute_skill(
                state=state, skill_name="customer_order",
                tool_names=["product_detail", "interact"],
                system_prompt="你是小布",
            ))

    def test_confirm_card_rewritten_to_choice_card(self):
        result = self._run_execute()
        blob = str(result)
        # 改写后的 choice 卡必须进入本轮产物（chat.py 据此发 interactive choice 事件）
        assert "component" in blob and "proc_item_pi1" in blob, (
            "execute_skill 未把 confirm 卡改写为加工项 choice 卡（接线失效）"
        )
        assert '"component": "choice"' in blob, f"confirm 卡未被改写为 choice:\n{blob[:600]}"


class TestInflightHandoffGuard:
    """C 端在办流程中禁止「无信号误转人工」（CH-012 实证，代码兜底）

    CH-012 run 34673167164 轨迹：R1 下发「请选择要申请退货的订单」choice 卡 →
    R3 用户仅回「质量问题」→ agent 调 `human_handoff`（并创建投诉工单）→ 流程被放弃，
    随后 R4 才恢复但轮数耗尽 → `aftersale_create` 未发生（用例判 0 分）。
    用户消息既非显式请求、也无负面情绪、更非能力外诉求 —— 纯属模型放弃在办流程。
    """

    def _run(self, last_user_msg: str, *, with_card: bool, explicit_human: bool = False,
             pending_skill: str = ""):
        import asyncio

        sent_tools = []

        async def fake_execute(tool, args, ctx, state):
            sent_tools.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        history = [HumanMessage(content="我要退货")]
        if with_card:
            history.append(ToolMessage(
                content=json.dumps({"success": True,
                                    "data": {"component": "choice",
                                             "title": "请选择要申请退货的订单",
                                             "options": [{"value": "o1"}]}}),
                tool_call_id="c0", name="interact"))
        history.append(HumanMessage(content=last_user_msg))

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            from app.tools.human_handoff import HumanHandoffTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                HumanHandoffTool() if n == "human_handoff" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "human_handoff", "args": {}, "id": "h1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            result = asyncio.run(execute_skill(
                state=_make_state(messages=history, pending_interact_skill=pending_skill),
                skill_name="customer_aftersales",
                tool_names=["human_handoff"], system_prompt="你是小布的售后客服",
            ))
        return result, sent_tools

    def test_blocks_signal_less_handoff_during_inflight_flow(self):
        result, sent = self._run("质量问题", with_card=True)
        assert "handoff_blocked_inflight" in str(result), (
            "在办流程中无信号转人工未被拦截 —— agent 会放弃在办业务并创建投诉工单（CH-012 实证）"
        )
        assert "human_handoff" not in sent, "被拦截时不得真正执行转人工"

    def test_allows_explicit_handoff_request(self):
        """回归：顾客明确说「转人工」时必须放行（CH-008/013/015 依赖）"""
        result, sent = self._run("转人工", with_card=True)
        assert "human_handoff" in sent, "显式转人工请求被误拦"

    def test_allows_emotional_escalation(self):
        """回归：情绪激动时放行（CH-014 依赖）"""
        _result, sent = self._run("你们又没解决，气死我了", with_card=True)
        assert "human_handoff" in sent, "负面情绪转人工被误拦"

    def test_allows_handoff_without_inflight_card(self):
        """没有在办卡片（未进入多轮流程）时不拦截 —— 保持既有行为"""
        _result, sent = self._run("质量问题", with_card=False)
        assert "human_handoff" in sent, "无在办流程时不应拦截转人工"

    def test_blocks_when_pending_skill_marks_inflight(self):
        """历史消息里扫不到卡片、但**跨轮 pending_interact_skill 非空** → 同样必须拦。

        CI 实证（run 34689293179，CH-012）：R1 已下发选单卡、R3 顾客只回退货原因
        「质量问题」，agent 直接 human_handoff 并建投诉工单 —— 当时"扫消息历史"这条路
        判为 False（state["messages"] 未带回上一轮的 interact ToolMessage），
        兜底形同虚设。pending_interact_skill 是「流程锁定中」的持久化权威标记
        （卡片发出即写、写成功即清），必须并入判据。
        """
        result, sent = self._run("质量问题", with_card=False,
                                 pending_skill="customer_aftersales")
        assert "handoff_blocked_inflight" in str(result), (
            "pending_interact_skill 非空（在办流程）时仍放行了无信号转人工"
        )
        assert "human_handoff" not in sent

    def test_block_message_names_flow_tool(self):
        """拦截话术必须点名下一步该调的工具（issue #3361，CI run 34703192730）。

        实证：CH-012 R2/R3/R4 连续被拦 3 次，模型只反复重试 human_handoff，
        始终不调 aftersale_create → 售后单永不创建。
        原话术只说"请继续完成当前流程"，没说"调用哪个工具"，模型无从下手。
        """
        import asyncio, json as _json

        sent_tools = []

        async def fake_execute(tool, args, ctx, state):
            sent_tools.append(tool.name)
            return (_json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            from app.tools.human_handoff import HumanHandoffTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            # 技能工具集里**有** aftersale_create（CH-012 的真实情形）
            registry.get_tool.side_effect = lambda n: (
                HumanHandoffTool() if n == "human_handoff" else (MagicMock() if n == "aftersale_create" else None))
            create_reg.return_value = registry

            breaker = MagicMock()
            async def _pt(fn): return await fn()
            breaker.call = _pt
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "human_handoff", "args": {}, "id": "h1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock(); llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            result = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="质量问题")],
                                  pending_interact_skill="customer_aftersales"),
                skill_name="customer_aftersales",
                tool_names=["human_handoff", "aftersale_create"],
                system_prompt="p",
            ))

        assert "handoff_blocked_inflight" in str(result)
        assert "aftersale_create" in str(result), (
            "拦截话术未点名 aftersale_create —— 模型只会反复重试转人工（CH-012 实证）"
        )
        assert "不要再次调用 human_handoff" in str(result), "未显式禁止重复调用转人工"

    def test_pending_skill_does_not_block_explicit_request(self):
        """回归：pending 非空但顾客明确要求转人工 → 仍必须放行。"""
        _result, sent = self._run("转人工", with_card=False, pending_skill="customer_aftersales")
        assert "human_handoff" in sent, "显式转人工被 pending 判据误拦"


class TestCardConfirmValueRecognition:
    """确认卡 confirmValue 必须被识别为**显式确认**（写操作落库的前置）

    实证（run 34678939564 + DB 审计）：17/17「全绿」，但 orders 表**没有新增订单** ——
    下单类用例的 `order_create` 被确认门禁**拦截**了（confirmValue 因含上下文而 >24 字，
    过不了 `_is_explicit_confirmation` 的长度上限），用例却因「工具被调用」而判通过
    （调了 ≠ 成了）。DB 审计这一新防线当场揭穿了这层假绿。

    根因：interact 工具描述**强制** confirmValue 含上下文（「确认下单：遮光窗帘 米白
    3米 ¥528…」），而 `_is_explicit_confirmation` 对「确认」前缀的消息限长 24 字符
    （防"指令措辞绕过"）→ 卡片点击回传的长 confirmValue 被误判为"非确认" →
    写操作永不落库。**这是生产路径的同类 bug**（mini-app 点确认卡同样被拦）。

    修复：系统把发出的 confirm 卡 confirmValue 记入会话状态；用户消息**精确等于**
    该值 → 视为显式确认（用户点了按钮，是最强的确认信号；精确匹配系统自产自展示的
    值，不存在"指令措辞绕过"面）。
    """

    LONG_CONFIRM = "确认下单：遮光窗帘 米白 散剪 门幅2.8米 3米 ¥474，收货人张三"

    def test_long_confirm_value_fails_old_heuristic(self):
        """前序事实：长 confirmValue 过不了旧的 24 字上限（本 bug 的触发条件）"""
        from app.graph.skills.base_skill import _is_explicit_confirmation
        assert len(self.LONG_CONFIRM) > 24
        assert _is_explicit_confirmation(self.LONG_CONFIRM) is False

    def test_exact_match_is_confirmation(self):
        from app.graph.skills.base_skill import _is_card_confirm_value
        assert _is_card_confirm_value(self.LONG_CONFIRM, self.LONG_CONFIRM) is True
        # 前缀相同但内容不同（用户自己改写的文本）→ 不是卡片点击
        assert _is_card_confirm_value("确认下单：我自己写的内容", self.LONG_CONFIRM) is False
        assert _is_card_confirm_value(None, self.LONG_CONFIRM) is False
        assert _is_card_confirm_value("", self.LONG_CONFIRM) is False
        assert _is_card_confirm_value(self.LONG_CONFIRM, None) is False

    def test_short_oral_confirmation_still_works(self):
        """回归：口头短确认（24 字内）仍按旧路径识别"""
        from app.graph.skills.base_skill import _is_explicit_confirmation
        assert _is_explicit_confirmation("确认") is True


class _FakeGroundedStore:
    """内存会话状态，预置「本会话已查过商品详情」（issue #3361 接地闸门要求）。

    为什么必须显式 fake：这些测试此前隐式依赖"SessionStateStore 连不上 → 各分支降级"，
    而**本机有 PG 时**它会真的读写 → 行为随环境漂移（接地闸门上线后当场暴露：
    本机有 PG 的会话状态里没有接地标记 → order_create 被拦 → 7 条测试红）。

    预置接地标记后，测试与 DB 无关：既覆盖确认链/去重逻辑，又不被基础设施可用性左右。
    """

    _states: dict = {}

    def __init__(self, *a, **k):
        pass

    async def load(self, session_id: str) -> dict:
        return dict(_FakeGroundedStore._states.setdefault(
            session_id, {"grounded_product_detail": {"product_id": "prod_eval_blackout"}}))

    async def commit(self, session_id: str, full: dict) -> None:
        _FakeGroundedStore._states[session_id] = dict(full)


def _patch_grounded_store():
    return patch("app.memory.session_state_store.SessionStateStore", _FakeGroundedStore)


class TestCardConfirmWriteExecutes:
    """集成：长 confirmValue 点击后，写操作**真的执行**（不再被门禁拦截）

    run 34678939564 + DB 审计实证：17/17 全绿但 orders 无新增 —— order_create
    被门禁拦截（confirmValue >24 字）、用例靠"工具被调用"假绿。本测试锁死
    「点击确认卡 → 写操作放行」这条落库闭环。
    """

    @pytest.fixture(autouse=True)
    def _grounded_store(self):
        _FakeGroundedStore._states = {}
        with _patch_grounded_store():
            yield


    LONG_CONFIRM = "确认下单：遮光窗帘 米白 散剪 门幅2.8米 3米 ¥474，收货人张三"

    def _run_confirm_then_write(self):
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        executed = []

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            if tool.name == "interact":
                return (json.dumps({"success": True,
                                    "data": {"component": "confirm",
                                             "confirmValue": TestCardConfirmWriteExecutes.LONG_CONFIRM}}),
                        {"success": True,
                         "data": {"component": "confirm",
                                  "confirmValue": TestCardConfirmWriteExecutes.LONG_CONFIRM}})
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            from app.tools.interact import InteractTool
            from app.tools.order_create import OrderCreateTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: {
                "interact": InteractTool(), "order_create": OrderCreateTool(),
            }.get(n)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            def make_call(name, args):
                m = MagicMock(spec=_AI)
                m.content = ""
                m.tool_calls = [{"name": name, "args": args, "id": "t1"}]
                return m

            final = MagicMock(spec=_AI)
            final.content = "订单已提交"
            final.tool_calls = []

            # 第 1 轮：发确认卡；第 2 轮（用户点了卡）：写工具；第 3 轮：收尾
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[
                make_call("interact", {"component": "confirm",
                                       "confirmValue": self.LONG_CONFIRM, "fields": []}),
                make_call("order_create", {"customer_name": "张三", "customer_phone": "13800138000",
                                           "items": []}),
                final,
            ])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            # 会话状态里预置最近确认卡的值（等同上一轮发出后已持久化）
            store_state = {"grounded_product_detail": {"product_id": "prod_eval_blackout"},
                       "last_confirm_value": self.LONG_CONFIRM,
                           # 接地前置（issue #3361）：本类测"确认卡点击→写操作放行"，
                           # 下单接地闸门要求会话状态里有该标记
                           "grounded_product_detail": {"product_id": "prod_eval_blackout"}}
            store_cls = patch("app.memory.session_state_store.SessionStateStore")
            with store_cls as _sc:
                _inst = MagicMock()
                _inst.load = AsyncMock(return_value=dict(store_state))
                _inst.commit = AsyncMock(return_value=None)
                _sc.return_value = _inst
                result = asyncio.run(execute_skill(
                    state=_make_state(messages=[HumanMessage(content=self.LONG_CONFIRM)]),
                    skill_name="customer_order",
                    tool_names=["interact", "order_create"],
                    system_prompt="你是小布",
                ))
        return result, executed

    def test_long_confirm_click_allows_write(self):
        result, executed = self._run_confirm_then_write()
        assert "order_create" in executed, (
            "点击确认卡后 order_create 未执行（仍被 24 字上限的门禁拦截）——"
            "写操作永不落库（DB 审计实证的假绿根因）"
        )
        assert "confirmation_required" not in str(result)


class TestCardConfirmValuePersisted:
    """确认卡**发出时**必须把 confirmValue 持久化（否则下一轮点击无法精确匹配）"""

    LONG_CONFIRM = TestCardConfirmWriteExecutes.LONG_CONFIRM

    def test_emit_persists_confirm_value(self):
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        committed = {}

        async def fake_execute(tool, args, ctx, state):
            if tool.name == "interact":
                return (json.dumps({"success": True,
                                    "data": {"component": "confirm",
                                             "confirmValue": self.LONG_CONFIRM}}),
                        {"success": True,
                         "data": {"component": "confirm",
                                  "confirmValue": self.LONG_CONFIRM}})
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            from app.tools.interact import InteractTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                InteractTool() if n == "interact" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            def make_call(name, args):
                m = MagicMock(spec=_AI)
                m.content = ""
                m.tool_calls = [{"name": name, "args": args, "id": "t1"}]
                return m

            final = MagicMock(spec=_AI)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[
                make_call("interact", {"component": "confirm",
                                       "confirmValue": self.LONG_CONFIRM, "fields": []}),
                final,
            ])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            inst = MagicMock()
            inst.load = AsyncMock(return_value={})
            inst.commit = AsyncMock(side_effect=lambda sid, full: committed.update(full))
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="帮我下单")]),
                skill_name="customer_order",
                tool_names=["interact"], system_prompt="你是小布",
            ))

        assert committed.get("last_confirm_value") == self.LONG_CONFIRM, (
            "确认卡发出后未持久化 confirmValue —— 下一轮点击无法精确匹配，"
            "写操作仍会被 24 字上限的门禁拦截（DB 审计实证的假绿根因）"
        )


class TestWriteConfirmedAcrossTurns:
    """确认卡点击后，跨轮补充信息（验证码）的写操作必须放行

    CI 实证（run 34682324499 诊断）：stored=「确认下单：…总额528元…」但 order_create
    轮的消息是验证码「123456」—— confirmValue 在**上一轮**匹配，本轮是补充信息。
    旧门禁要求「本轮消息=确认」→ 写操作被拦。修复：卡片匹配时记录
    `confirmed_write_tool`，写工具成功执行后清除（闭环语义与 pending 一致）。
    """

    @pytest.fixture(autouse=True)
    def _grounded_store(self):
        _FakeGroundedStore._states = {}
        with _patch_grounded_store():
            yield


    LONG_CONFIRM = "确认下单：遮光窗帘 3米 米白 纳米圈打孔，总额528元，收货人张三 13800138000"

    def test_write_executes_on_code_turn_after_card_confirm(self):
        """模拟真实两轮：R1 用户点击确认卡（精确匹配）；R2 用户给验证码 → order_create"""
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        executed = []
        store_state = {"last_confirm_value": self.LONG_CONFIRM,
                       "confirmed_write_tool": "order_create",  # R1 匹配后已记录
                       # 接地前置（issue #3361）：本用例测"验证码轮放行"，不测接地闸门
                       "grounded_product_detail": {"product_id": "prod_eval_blackout"}}

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            from app.tools.order_create import OrderCreateTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                OrderCreateTool() if n == "order_create" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=_AI)
            call.content = ""
            call.tool_calls = [{"name": "order_create",
                                "args": {"customer_name": "张三", "customer_phone": "13800138000",
                                         "sms_code": "123456", "items": []}, "id": "t1"}]
            final = MagicMock(spec=_AI)
            final.content = "订单已提交"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            inst = MagicMock()
            inst.load = AsyncMock(side_effect=lambda sid: dict(store_state))
            inst.commit = AsyncMock(side_effect=lambda sid, full: store_state.update(full))
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="123456")]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="你是小布",
            ))

        assert "order_create" in executed, (
            "确认卡在上一轮匹配后，本轮验证码消息仍被门禁拦截（confirmed_write_tool 未生效）"
        )

    def test_clear_after_success_requires_reconfirm(self):
        """写成功后确认标记清除：下一次同类写操作无新确认时必须仍被拦"""
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        executed = []
        store_state = {}  # 无 confirmed_write_tool（模拟成功后被清除）

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            from app.tools.order_create import OrderCreateTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                OrderCreateTool() if n == "order_create" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=_AI)
            call.content = ""
            call.tool_calls = [{"name": "order_create", "args": {}, "id": "t1"}]
            final = MagicMock(spec=_AI)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            inst = MagicMock()
            inst.load = AsyncMock(return_value=dict(store_state))
            inst.commit = AsyncMock()
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="随便说点什么")]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="你是小布",
            ))

        assert "order_create" not in executed, (
            "无新确认的写操作被放行了（confirmed_write_tool 残留/清除逻辑失效）—— 安全漏洞"
        )


class TestWriteConfirmedLifecycle:
    """记录与清除两个代码路径的直接覆盖（M1/M3 变异缺口）"""

    LONG_CONFIRM = "确认下单：遮光窗帘 3米 米白 纳米圈打孔，总额528元，收货人张三 13800138000"

    def _run(self, store_state, user_msg, tool_calls):
        # 接地前置（issue #3361）：本类测确认链，不测接地闸门
        store_state.setdefault("grounded_product_detail", {"product_id": "prod_eval_blackout"})
        import asyncio

        from langchain_core.messages import AIMessage as _AI

        commits = []
        executed = []

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            from app.tools.order_create import OrderCreateTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                OrderCreateTool() if n == "order_create" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            def make_call(name, args):
                m = MagicMock(spec=_AI)
                m.content = ""
                m.tool_calls = [{"name": name, "args": args, "id": "t1"}]
                return m

            final = MagicMock(spec=_AI)
            final.content = "订单已提交"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[make_call(*tc) for tc in tool_calls] + [final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            # 接地前置（issue #3361）：本类测的是"确认链/跨轮放行"，下单接地闸门要求
            # 会话状态里有 grounded_product_detail —— 不显式声明的话会被闸门拦（不是本类要测的）
            store_state.setdefault("grounded_product_detail", {"product_id": "prod_eval_blackout"})
            inst = MagicMock()
            inst.load = AsyncMock(side_effect=lambda sid: dict(store_state))
            inst.commit = AsyncMock(side_effect=lambda sid, full: commits.append(dict(full)))
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="你是小布",
            ))
        return commits, executed

    def test_card_match_records_confirmed_write_tool(self):
        """确认卡精确匹配轮 → 记录 confirmed_write_tool（供下一轮补充信息放行）"""
        commits, executed = self._run(
            {"last_confirm_value": self.LONG_CONFIRM},
            self.LONG_CONFIRM,
            [("order_create", {"customer_name": "张三"})],
        )
        assert "order_create" in executed, "确认卡精确匹配轮写操作应放行"
        assert any(c.get("confirmed_write_tool") == "order_create" for c in commits), (
            "确认卡匹配后未记录 confirmed_write_tool —— 下一轮补充信息（验证码）会被拦"
        )

    def test_success_clears_confirmed_write_tool(self):
        """写成功后清除 confirmed_write_tool —— 下一次同类写操作需重新确认"""
        commits, executed = self._run(
            {"confirmed_write_tool": "order_create"},
            "123456",
            [("order_create", {"customer_name": "张三"})],
        )
        assert "order_create" in executed, "前轮已确认的写操作应放行"
        assert commits, "写成功后的清除提交不存在（测试会空转假绿）"
        # 断言**最终状态**而非"每个提交都不含该键"：写成功后还会有别的记账提交
        # （如 issue #3379 的 `last_sms_code` 记码），那些提交里会带上当时仍存在的
        # confirmed_write_tool 快照 —— 但安全性质是"**最终**不带该标记"。
        last = commits[-1]
        assert "confirmed_write_tool" not in last, (
            "写成功后未清除 confirmed_write_tool —— 后续同类写操作会在无新确认时被放行（安全漏洞）"
        )


class TestTurnStartCardConfirmRecord:
    """确认卡点击轮（turn-start）即记录 confirmed_write_tool —— 不依赖本轮调写工具

    CI 实证（run 34683286448）：confirmValue 在上一轮匹配，但 agent 在本轮（验证码轮）
    才调 order_create；此前记录点只在「写工具被调用且卡片精确匹配」时 —— 本轮消息不是
    卡片值 → 记录永不发生 → 写操作仍被拦。
    """

    LONG_CONFIRM = "确认下单：遮光窗帘 3米 米白 纳米圈打孔，总额528元，收货人张三 13800138000"

    def test_record_on_confirm_click_turn(self):
        import asyncio

        from app.graph.skills.base_skill import _inject_pending_validated
        from app.graph.pending_validated import PENDING_KEY

        committed = {}

        with patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            inst = MagicMock()
            inst.load = AsyncMock(return_value={
                "last_confirm_value": self.LONG_CONFIRM,
                PENDING_KEY: {"target_tool": "order_create", "target_action": "create",
                              "params": {}},
            })
            inst.commit = AsyncMock(side_effect=lambda sid, full: committed.update(full))
            store_cls.return_value = inst

            asyncio.run(_inject_pending_validated(
                "原提示词",
                {"session_id": "sess_t1"},
                self.LONG_CONFIRM,  # 用户点击确认卡回传的精确值
            ))

        assert committed.get("confirmed_write_tool") == "order_create", (
            "确认卡点击轮未记录 confirmed_write_tool（turn-start 记录失效）—— "
            "下一轮补充信息（验证码）写操作仍会被门禁拦"
        )

    def test_no_record_without_pending(self):
        """没有已校验待执行状态时，卡片确认不产生放行标记"""
        import asyncio

        from app.graph.skills.base_skill import _inject_pending_validated

        committed = {}

        with patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            inst = MagicMock()
            inst.load = AsyncMock(return_value={"last_confirm_value": self.LONG_CONFIRM})
            inst.commit = AsyncMock(side_effect=lambda sid, full: committed.update(full))
            store_cls.return_value = inst

            asyncio.run(_inject_pending_validated(
                "p", {"session_id": "s2"}, self.LONG_CONFIRM))
        assert "confirmed_write_tool" not in committed


class TestTextConfirmationRecordedAcrossTurns:
    """文本确认（「确认」）也必须在**确认轮**记录 confirmed_write_tool（issue #3361）。

    CI 实证（run 34689293179，OR-017）：
      R3 顾客回「确认」→ 模型只调 validate_input 并下发确认卡（**没写**）；
      R4 顾客回手机验证码「123456」→ stored confirmValue（'确认下单'）不匹配、
      本轮文本也不像确认 → 门禁以「未确认」拦下 order_create → 订单永不落库。
    旧实现只在「卡片 confirmValue 精确匹配」时记录，文本明确确认（短句「确认」）
    这条路径漏记 —— 而 `_is_explicit_confirmation` 本来就是门禁认可的确认判据。
    """

    def _run(self, last_user_msg, pending, stored=None):
        import asyncio

        from app.graph.skills.base_skill import _inject_pending_validated
        from app.graph.pending_validated import PENDING_KEY

        committed = {}
        state = {"last_confirm_value": stored} if stored else {}
        if pending:
            state[PENDING_KEY] = pending

        with patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            inst = MagicMock()
            inst.load = AsyncMock(return_value=state)
            inst.commit = AsyncMock(side_effect=lambda sid, full: committed.update(full))
            store_cls.return_value = inst
            asyncio.run(_inject_pending_validated("p", {"session_id": "s1"}, last_user_msg))
        return committed

    def test_short_text_confirmation_records(self):
        committed = self._run("确认", {"target_tool": "order_create", "target_action": "create"})
        assert committed.get("confirmed_write_tool") == "order_create", (
            "文本确认轮未记录放行标记 —— 下一轮补充信息（验证码）写操作会被门禁拦"
        )

    def test_sms_code_turn_does_not_record(self):
        """补充信息轮（验证码）本身不构成确认 —— 不得误记录（门禁不能被绕过）。"""
        committed = self._run("123456", {"target_tool": "order_create", "target_action": "create"})
        assert "confirmed_write_tool" not in committed

    def test_no_pending_no_record(self):
        committed = self._run("确认", None)
        assert "confirmed_write_tool" not in committed

    def test_card_click_still_records(self):
        """卡片点击路径不得回归（原有行为）。"""
        long_val = "确认下单：遮光窗帘 3米 米白 打孔，总额528元，收货人张三"
        committed = self._run(long_val,
                              {"target_tool": "order_create", "target_action": "create"},
                              stored=long_val)
        assert committed.get("confirmed_write_tool") == "order_create"


class TestInTurnDuplicateWriteCoalescing:
    """同轮重复写调用合并（issue #3361）：防止「一次意图 = 两次写」。

    CI 实证（CH-010，run 34691137050）：一轮里 `order_create ×3`（模型把同一次下单
    意图重复表达了三遍）。写工具刻意不走 60s 读缓存（重复的**非幂等写**不能被静默
    吞掉），于是三次都真执行 → 2 次 `tool_execution_failed`、1 次成功 —— **幸而**没有
    变成 2 张订单。合并规则与缓存的关键区别：作用域仅本轮（下一次回复即失效），
    且**参数不同不合并**（那是两次不同的写需求）。
    """

    @pytest.fixture(autouse=True)
    def _grounded_store(self):
        _FakeGroundedStore._states = {}
        with _patch_grounded_store():
            yield


    def _run(self, tool_calls, read_only=False):
        import asyncio
        from app.graph.skills.base_skill import execute_skill

        executed = []

        async def fake_execute_safe(tool, args, ctx, state):
            executed.append((tool.name, dict(args)))
            return (json.dumps({"success": True, "data": {"id": "x"}}),
                    {"success": True, "data": {"id": "x"}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute_safe):
            fake_tool = MagicMock()
            fake_tool.name = "order_create"
            fake_tool.read_only = read_only
            fake_tool.destructive = False
            fake_tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: fake_tool if n == "order_create" else None
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = tool_calls
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            result = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="确认下单")]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="p",
            ))
        return executed, result

    def _tc(self, args, cid="c1"):
        return {"name": "order_create", "args": args, "id": cid}

    def test_identical_write_calls_execute_once(self):
        executed, result = self._run([
            self._tc({"items": [{"product_id": "p1"}], "sms_code": "123456"}, "c1"),
            self._tc({"items": [{"product_id": "p1"}], "sms_code": "123456"}, "c2"),
            self._tc({"items": [{"product_id": "p1"}], "sms_code": "123456"}, "c3"),
        ])
        assert len(executed) == 1, (
            f"同轮同参数的写调用未合并（执行了 {len(executed)} 次）—— "
            "运气差会变成重复下单"
        )
        # 三个 tool_call 都必须拿到结果（不能有调用悬空）
        msgs = result.get("messages") or []
        tool_msgs = [m for m in msgs if type(m).__name__ == "ToolMessage"]
        assert len(tool_msgs) == 3, f"合并后每个 tool_call 仍须有结果消息，实际 {len(tool_msgs)}"

    def test_different_args_not_coalesced(self):
        """参数不同 = 两次不同的写需求 → 必须执行两次（不能误合并）。"""
        executed, _ = self._run([
            self._tc({"items": [{"product_id": "p1"}]}, "c1"),
            self._tc({"items": [{"product_id": "p2"}]}, "c2"),
        ])
        assert len(executed) == 2

    def test_read_only_duplicates_unchanged(self):
        """只读工具不受此逻辑影响（它走 60s 读缓存，语义不变）。"""
        executed, _ = self._run([
            self._tc({}, "c1"), self._tc({}, "c2"),
        ], read_only=True)
        assert len(executed) == 2


class TestHallucinatedToolArgSanitize:
    """模型幻觉参数净化（issue #3361，CI 实证 run 34703192730）。

    dump 原文：
        [tool-exec] order_create ERROR: OrderCreateTool.execute() got an unexpected
        keyword argument 'action'
    LLM 会把别家工具的字段顺手带过来（`aftersale_create`/`after_sales_manage` 有 `action`，
    `order_create` 没有）→ TypeError → `tool_execution_failed` → 模型重试两次才成功
    （CH-010/OR-014 抖动的真因，单条用例白跑 200-400s）。

    修法：执行前按工具 `execute()` 签名丢弃不受支持的 kwarg，并打警告（可见、不静默）。
    """

    def _tool(self, **kwargs):
        captured = {}

        async def execute(self, context, name: str, items: list, sms_code=None, **rest):
            captured.update({"name": name, "items": items, "sms_code": sms_code, "rest": rest})
            return "ok"

        class T:
            name = "order_create"
            read_only = False
            destructive = False
            requires_confirmation = False

        T.execute = execute
        t = T()
        return t, captured

    @pytest.fixture(autouse=True)
    def _clear_sig_cache(self):
        """签名缓存是模块级 dict：测试替身同名会串味，逐测清空。"""
        from app.graph.skills.base_skill import _accepted_param_names
        _accepted_param_names._cache = {}
        yield
        _accepted_param_names._cache = {}

    def test_unexpected_kwarg_dropped(self, capsys):
        """多余参数（action）必须被丢弃，调用照常成功。

        替身必须用**显式签名**（真实 order_create 就是这样：无 **kwargs）——
        带 **kwargs 的工具按设计不做净化（不能吞合法参数），用 **kwargs 替身测不出净化。
        """
        import asyncio
        from app.graph.skills.base_skill import _execute_tool_safe

        seen = {}

        async def fake_execute(context, name: str, items: list, sms_code=None):
            seen.update({"name": name, "items": items, "sms_code": sms_code})
            from app.tools.base import ToolResult
            return ToolResult(success=True, data={"ok": True}, message="ok")

        class T:
            name = "order_create"
            read_only = False
            destructive = False
            requires_confirmation = False

        T.execute = staticmethod(fake_execute)

        with patch("app.graph.skills.base_skill._auto_resolve_ids",
                   new=AsyncMock(side_effect=lambda tool, args, state: args)), \
             patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
                   staticmethod(lambda tool, args: args)):
            _, result_dict = asyncio.run(_execute_tool_safe(
                T(), {"name": "张三", "items": [], "action": "create"}, MagicMock(), {"session_id": "s"}))
        assert result_dict.get("success") is True, "净化后调用应成功"
        assert "action" not in seen, "幻觉参数 action 未被丢弃"
        assert seen.get("name") == "张三" and seen.get("items") == []

    def test_normal_args_pass_through(self):
        """正常参数不得被误删（净化只针对签名外的键）。"""
        import asyncio
        from app.graph.skills.base_skill import _execute_tool_safe

        seen = {}

        async def fake_execute(context, **kw):
            seen.update(kw)
            from app.tools.base import ToolResult
            return ToolResult(success=True, data={}, message="ok")

        class T:
            name = "order_create"
            read_only = False
            destructive = False
            requires_confirmation = False
        T.execute = staticmethod(fake_execute)

        with patch("app.graph.skills.base_skill._auto_resolve_ids",
                   new=AsyncMock(side_effect=lambda tool, args, state: args)), \
             patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
                   staticmethod(lambda tool, args: args)):
            asyncio.run(_execute_tool_safe(T(), {"name": "张三", "sms_code": "123456"},
                                           MagicMock(), {"session_id": "s"}))
        assert seen.get("name") == "张三" and seen.get("sms_code") == "123456"

    def test_var_keyword_tool_not_sanitized(self):
        """带 **kwargs 的工具不做净化（不能吞掉合法参数）。"""
        import asyncio
        from app.graph.skills.base_skill import _sanitize_tool_args

        class T:
            name = "flexible"
            async def execute(self, context, **kwargs):
                return "ok"

        out = _sanitize_tool_args(T(), {"anything": 1, "name": "x"})
        assert out == {"anything": 1, "name": "x"}


class TestOrderGroundingGate:
    """下单接地闸门（issue #3361，OR-014 复现型红灯）。

    实证（CI run 34704789166，OR-014）：顾客说「帮我下单，遮光窗帘 3 米，要打孔加工」，
    模型 **一次都没查商品**（R1 tools=-），凭记忆发确认卡（金额 ¥95.4，而该商品真实单价
    ¥168/米）并试图下单 → 单价/加工项/金额全不可信，且用例期望的 product_detail 缺失。

    提示词里的「商品详情铁律（confirm 之前必须先调 product_detail）」模型不守，
    故加代码闸门：本会话没**成功**查过商品详情 → 不许下单，并把可执行步骤写进 tool result。
    """

    def _run(self, grounded: bool, tool_calls):
        import asyncio, json as _json

        sent = []

        async def fake_execute(tool, args, ctx, state):
            sent.append(tool.name)
            return (_json.dumps({"success": True, "data": {"id": "o1"}}),
                    {"success": True, "data": {"id": "o1"}})

        class _Store:
            def __init__(self, state):
                self._state = state

            async def load(self, sid):
                return dict(self._state)

            async def commit(self, sid, full):
                self._state.update(full)

        store_state = {"grounded_product_detail": {"product_id": "p1"}} if grounded else {}

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store(store_state)):
            fake_tool = MagicMock()
            fake_tool.name = "order_create"
            fake_tool.read_only = False
            fake_tool.destructive = False
            fake_tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: fake_tool if n == "order_create" else None
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = tool_calls
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            _ = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="帮我下单")]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="p"))
        return sent, store_state

    def test_blocks_order_without_grounding(self):
        sent, _ = self._run(False, [{"name": "order_create", "args": {}, "id": "c1"}])
        assert sent == [], (
            "本会话没查过商品详情却执行了 order_create —— 价格/加工项不可信（OR-014 实证 ¥95.4）"
        )

    def test_allows_order_when_grounded(self):
        sent, _ = self._run(True, [{"name": "order_create", "args": {}, "id": "c1"}])
        assert sent == ["order_create"], "已查过商品详情时不得误拦下单"

    def test_product_detail_success_records_grounding(self):
        """成功调用 product_detail 后必须落地接地标记（否则闸门永远拦）。"""
        import asyncio, json as _json
        sent = []

        async def fake_execute(tool, args, ctx, state):
            sent.append(tool.name)
            return (_json.dumps({"success": True, "data": {"id": "p9"}}),
                    {"success": True, "data": {"id": "p9"}})

        class _Store:
            def __init__(self, state):
                self._state = state

            async def load(self, sid):
                return dict(self._state)

            async def commit(self, sid, full):
                self._state.update(full)

        store_state = {}
        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store(store_state)):
            fake_tool = MagicMock()
            fake_tool.name = "product_detail"
            fake_tool.read_only = True
            fake_tool.destructive = False
            fake_tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: fake_tool if n == "product_detail" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "product_detail", "args": {"product_id": "p9"}, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="看看这个商品")]),
                skill_name="customer_order",
                tool_names=["product_detail"], system_prompt="p"))
        assert store_state.get("grounded_product_detail"), "product_detail 成功后未落地接地标记"


class TestGroundingAutopilot:
    """接地自动驾驶（issue #3365）：闸门拦下后**代码代跑**只读的 search+detail。

    实证（CI run 34707941520，OR-014）：闸门拦住 6 次，模型仍只重试 order_create，
    提示词与拦截话术都劝不动 → 属模型层不遵从。故代码兜底：代跑
    product_search(keyword=顾客原话里的商品名) → product_detail → 落接地标记 →
    把真实单价回给模型，让它基于真值重新下单。
    只在**唯一命中**时落地（多命中把候选交回模型，不猜商品）。
    """

    def _run(self, search_products, detail_ok=True, user_msg="帮我下单，遮光窗帘 3 米，要打孔加工"):
        import asyncio, json as _json

        calls = []
        store = {}

        class _Store:
            async def load(self, sid):
                return dict(store)

            async def commit(self, sid, full):
                store.update(full)

        async def fake_execute_safe(tool, args, ctx, state):
            calls.append((tool.name, dict(args)))
            if tool.name == "product_search":
                return (_json.dumps({"success": True, "data": {"products": search_products}}),
                        {"success": True, "data": {"products": search_products}})
            if tool.name == "product_detail":
                if not detail_ok:
                    return (_json.dumps({"success": False, "error": "not_found"}),
                            {"success": False, "error": "not_found"})
                return (_json.dumps({"success": True, "data": {"id": args.get("product_id"),
                                                               "name": "遮光窗帘", "price": 168.0}}),
                        {"success": True, "data": {"id": args.get("product_id"),
                                                   "name": "遮光窗帘", "price": 168.0}})
            return (_json.dumps({"success": True, "data": {"id": "o1"}}),
                    {"success": True, "data": {"id": "o1"}})

        def _mk(name):
            m = MagicMock()
            m.name = name
            m.read_only = True
            m.destructive = False
            m.requires_confirmation = False
            return m

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute_safe), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            order_tool = _mk("order_create")
            order_tool.read_only = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: {
                "order_create": order_tool, "product_search": _mk("product_search"),
                "product_detail": _mk("product_detail"),
            }.get(n)
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "order_create", "args": {"items": []}, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            result = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=["order_create", "product_search", "product_detail"],
                system_prompt="p"))
        return calls, store, result

    def test_single_hit_gives_grounded_facts(self):
        calls, store, result = self._run([{"id": "p1", "name": "遮光窗帘"}])
        names = [c[0] for c in calls]
        assert names[:2] == ["product_search", "product_detail"], f"未代跑 search→detail: {names}"
        assert store.get("grounded_product_detail", {}).get("product_id") == "p1", "接地标记未落"
        s = str(result)
        assert "遮光窗帘" in s and "168" in s, "未把真实商品/单价回给模型"

    def test_multiple_hits_not_guessed(self):
        """多命中不得猜商品（否则把错误数据当接地真值）。"""
        calls, store, _ = self._run([{"id": "p1"}, {"id": "p2"}])
        assert [c[0] for c in calls] == ["product_search"], "多命中还继续 product_detail（等于猜商品）"
        assert "grounded_product_detail" not in store

    def test_no_keyword_no_autopilot(self):
        calls, _store, _ = self._run([{"id": "p1"}], user_msg="帮我下单 3 米要打孔加工")
        assert calls == [], "抽不到商品关键词时代跑不应触发（避免搜错）"

    def test_detail_failure_falls_back(self):
        calls, store, result = self._run([{"id": "p1"}], detail_ok=False)
        assert [c[0] for c in calls] == ["product_search", "product_detail"]
        assert "grounded_product_detail" not in store, "detail 失败不得落接地标记"
        assert "product_detail" in str(result), "应回落到分步话术"


class TestSmsCodeBackfill:
    """验证码代码补齐（issue #3365）。

    实证（CI run 34712928371，CH-010）：`order_create!缺少短信验证码 ×3` —— 顾客明明在上一轮
    给了「123456」，模型调 order_create 时就是不带 sms_code → 订单不落库、用例判红，
    而失败长相像"能力不行"（真因是模型漏参 + 工具强校验）。
    代码兜底：顾客上一条消息**整条就是验证码** → 执行前补进 args。
    """

    def _run(self, user_msg, args):
        import asyncio, json as _json

        seen = {}

        async def fake_execute(tool, a, ctx, state):
            seen.update(a)
            return (_json.dumps({"success": True, "data": {"id": "o1"}}),
                    {"success": True, "data": {"id": "o1"}})

        class _Store:
            async def load(self, sid):
                return {"grounded_product_detail": {"product_id": "p1"}}

            async def commit(self, sid, full):
                pass

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = "order_create"
            tool.read_only = False
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == "order_create" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "order_create", "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="p"))
        return seen

    def test_code_backfilled_when_customer_gave_it(self):
        seen = self._run("123456", {"items": []})
        assert seen.get("sms_code") == "123456", "顾客已给验证码但未补齐 → 订单必然被拒"

    def test_no_backfill_when_model_already_passed(self):
        seen = self._run("123456", {"items": [], "sms_code": "654321"})
        assert seen.get("sms_code") == "654321", "模型已带验证码时不得覆盖"

    def test_phone_number_not_mistaken_for_code(self):
        """手机号里含数字片段，绝不能当验证码注入（否则验证必失败且难排查）。"""
        seen = self._run("我的手机号是 13800138000", {"items": []})
        assert "sms_code" not in seen

    def test_backfill_from_stored_code_when_last_message_is_confirm(self):
        """**上一条不是码**时用会话记住的码回填（issue #3379 P2-1）。

        场景：顾客先发「123456」（码轮被记住）→ 再回「确认」→ 模型调 order_create 时没带码。
        若回填链只看"本轮消息"，就会要求顾客**再发一次码**（验收 C-A1 R7 的空转）。
        """
        import json as _json

        seen = {}

        async def fake_execute(tool, a, ctx, state):
            seen.update(a)
            return (_json.dumps({"success": True, "data": {"id": "o1"}}),
                    {"success": True, "data": {"id": "o1"}})

        class _Store:
            async def load(self, sid):
                return {"grounded_product_detail": {"product_id": "p1"},
                        "last_sms_code": "123456"}

            async def commit(self, sid, full):
                pass

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = "order_create"
            tool.read_only = False
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == "order_create" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "order_create", "args": {"items": []}, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            import asyncio as _aio
            _aio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="确认下单")]),
                skill_name="customer_order", tool_names=["order_create"], system_prompt="p"))
        assert seen.get("sms_code") == "123456", \
            "会话里记住的验证码未被回填 → 顾客要再发一次码（空转）"

    def test_extract_sms_code_shapes(self):
        from app.graph.skills.base_skill import extract_sms_code
        assert extract_sms_code("123456") == "123456"
        assert extract_sms_code("验证码 1234") == "1234"
        assert extract_sms_code("短信验证码：123456") == "123456"
        assert extract_sms_code("13800138000") == ""
        assert extract_sms_code("123456 顺便问下") == ""
        assert extract_sms_code("") == ""


class TestSmsCodeRememberedAcrossTurns:
    """验证码要被**记住**，而不是把码轮当确认（验收 P2-1，issue #3379）。

    证据（验收剧本 C-A1 R7，`acceptance/ci-34730957920/.../C-A1.transcript.md`）：
      ```
      用户: 123456
      AI:  …**稍后还需要您手机验证一下**，很快就好哦！
      ```
      该轮未调 order_create（顾客的码**空转**），订单要等下一轮顾客重复「确认下单」才落地；
      且话术自相矛盾（码都发了还说"稍后需要验证"）。

    ## 修法取舍（**安全性质优先**）
    首版把"验证码轮"当确认轮 —— 但那只测就红了：既有的
    `test_sms_code_turn_does_not_record` 锁着"确认门禁不可被绕过"这条**安全性质**
    （顾客没确认订单明细就能下单 = 更严重的问题）。
    故改成：**码轮不确认、但码被记住** → 门禁照旧，顾客的码也不再白给。
    """

    def _run(self, user_msg, store_extra=None):
        import asyncio

        committed = {}
        full = dict(store_extra or {})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                committed.update(new_full)
                full.clear(); full.update(new_full)

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()), \
             patch("app.graph.skills.base_skill.get_breaker") as gb, \
             patch("app.graph.skills.base_skill.get_skill_llm") as gl, \
             patch("app.graph.skills.base_skill.create_skill_registry") as cr, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.return_value = None
            cr.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            gb.return_value = breaker
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[final])
            gl.return_value = llm
            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order", tool_names=["product_search"], system_prompt="p"))
        return committed

    def test_code_turn_is_remembered(self):
        committed = self._run("123456")
        assert committed.get("last_sms_code") == "123456", \
            "验证码轮未记码 → 顾客先给码再确认时会被要求再发一次（空转）"

    def test_code_turn_still_not_a_confirmation(self):
        """安全性质：码轮不得被当成确认（门禁不可绕过）。"""
        committed = self._run("123456")
        assert "confirmed_write_tool" not in committed

    def test_code_turn_does_not_inject_execute_hint(self):
        """码轮**不得**注入"直接执行"提示（门禁不可绕过的可观测形态）。

        首版把码轮当确认 → 就等于"顾客没确认订单明细也能下单"；
        本断言锁住注入层：码轮 + 待执行 order_create → 注入函数必须原样返回。
        """
        import asyncio
        from app.graph.skills.base_skill import _inject_pending_validated

        class _Store:
            async def load(self, sid):
                return {"pending_validated_input": {
                    "target_tool": "order_create", "target_action": "create", "params": {}}}

            async def commit(self, sid, full):
                pass

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            out = asyncio.run(_inject_pending_validated(
                "BASE", {"session_id": "sess_001"}, "123456"))
        assert out == "BASE", "验证码轮被当成确认轮 → 确认门禁被绕过（安全性质）"

    def test_non_code_message_not_remembered(self):
        committed = self._run("这个窗帘多少钱")
        assert not committed.get("last_sms_code")

    def test_phone_number_not_remembered_as_code(self):
        committed = self._run("我的手机号是13800138000")
        assert not committed.get("last_sms_code"), "手机号不得被当验证码记住（extract_sms_code 用 fullmatch）"


class TestGraphReplyMemoryIntegrity:
    """graph 层**不得**改写 `final_content` —— 会话记忆就是模型上下文，必须保原文。

    本类此前叫 `TestCustomerReplyMasking`，断言"`final_answer` 里是 `138****8000`"，
    是**假守卫**：`final_answer` 同时是 `_agent_stream_to_sse` 里
    `full_response.append(clean)` 的来源，也就是 `save_message` 落库的 assistant 消息，
    即模型**下一轮读到的自己的历史**。于是（issue #3386，DB 实证）：

      R5 graph 把 `13800138000` 脱敏成 `138****8000` → 落库 → R7 模型读到残缺值
      → 把 `****` 填成 `0` → `13800008000`（11 位纯数字，`order_create._PHONE_PATTERN`
      完全放行）→ **订单手机号静默写错**：CH-010 订单 `20260913384380002` 落库
      `customer_phone = 13800008000`，而同用例给模型的号码是 `13800138000`。
      顾客会**收不到短信与配送联系**，且全链路无任何告警。

    不变量拆成两条，各守一侧、职责不重叠：
      · **记忆侧（本类）**：graph 返回并落库的文本保持原文 —— 模型要拿它去建单/回显；
      · **展示侧**（`test_api_chat_helpers.py::TestCustomerStreamMasking`、
        `test_chat.py::TestGetHistoryMasking`）：顾客看得到的出站（SSE 文本/卡片、
        C 端 `/history`）脱敏。
    """

    def _run(self, role="customer", reply="您的收货信息：张三 · 13800138000 · 杭州市西湖区文三路1号"):
        import asyncio

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as gb, \
             patch("app.graph.skills.base_skill.get_skill_llm") as gl, \
             patch("app.graph.skills.base_skill.create_skill_registry") as cr, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.return_value = None
            cr.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            gb.return_value = breaker
            final = MagicMock(spec=AIMessage)
            final.content = reply
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[final])
            gl.return_value = llm
            return asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="我的收货信息是什么")], role=role),
                skill_name="customer_order", tool_names=["product_search"], system_prompt="p"))

    def test_customer_answer_keeps_raw_phone(self):
        """C 端答复里的手机号必须**原样返回**（记忆层不脱敏；脱敏只在出站展示层）。"""
        res = self._run(role="customer")
        ans = res.get("final_answer") or ""
        assert "13800138000" in ans, (
            f"记忆被脱敏 → 模型下一轮拿到残缺号码，会把 `****` 填成数字建单（issue #3386）: {ans!r}")
        assert "138****8000" not in ans, f"graph 层不得脱敏（脱敏属出站展示层）: {ans!r}"

    def test_staff_answer_keeps_raw_phone(self):
        """B 端不脱敏：客服要打电话给顾客，脱敏会破坏运营。"""
        res = self._run(role="admin")
        ans = res.get("final_answer") or ""
        assert "13800138000" in ans, f"B 端不应脱敏，实际: {ans!r}"

    def test_short_or_non_phone_digits_untouched(self):
        res = self._run(role="customer", reply="订单号 20260913027050006，数量 3 米，验证码 123456")
        ans = res.get("final_answer") or ""
        assert "20260913027050006" in ans, "订单号不得被改写"
        assert "123456" in ans, "验证码不得被改写"


class TestMaskedPhoneWriteGuard:
    """写工具不得用「掩码形态」的手机号建单（issue #3386，DB 实证静默脏数据）。

    真实事故链：graph 层脱敏 → 落库 assistant 消息 = `138****8000` → 模型下一轮读到
    自己的历史，把 `****` 填成 `0` 得到 `13800008000` —— 11 位纯数字**形态完全合法**，
    `order_create._PHONE_PATTERN`（`^1[3-9]\\d{9}$`）放行，订单手机号静默写错。

    故守卫必须比对**本会话已知的真实号码**（`customer_address_query` 的读结果、顾客
    自己给的号码）：提交值若是已知真号的掩码变体 `138****8000` / `13800008000` /
    `138xxxx8000`，且**顾客本人没说这个号** → 拦下并回放真实号码。
    反向约束同样重要：顾客明确给了新号码时必须放行（改号是合法业务）。
    """

    KNOWN = "13800138000"

    def _run(self, args, last_user_msg="确认下单", known=(KNOWN,), tool_name="order_create"):
        import asyncio

        class _Store:
            async def load(self, sid):
                return {KNOWN_RAW_PHONES_KEY: list(known)}

            async def commit(self, sid, new_full):
                return None

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(_masked_phone_write_block(
                tool_name, args, {"name": tool_name, "args": args, "id": "c1"},
                "sess_1", "customer_order", last_user_msg))

    def _blocked_code(self, out):
        import json as _json
        assert out is not None, "该号码必须被拦下（否则脏数据落库）"
        return _json.loads(out[1]).get("error"), _json.loads(out[1]).get("message", "")

    # ── 拦：掩码形态 ──

    def test_star_filled_variant_blocked(self):
        """`13800008000` = `138****8000` 把 `****` 填成 `0` —— CI 实证的落库形态。"""
        code, msg = self._blocked_code(self._run({"customer_phone": "13800008000"}))
        assert code == "write_blocked_masked_phone"
        assert self.KNOWN in msg, f"拦截时必须回放真实号码供模型复用: {msg!r}"

    def test_star_form_blocked(self):
        code, msg = self._blocked_code(self._run({"customer_phone": "138****8000"}))
        assert code == "write_blocked_masked_phone"
        assert self.KNOWN in msg

    def test_x_filler_variant_blocked(self):
        code, _ = self._blocked_code(self._run({"customer_phone": "138xxxx8000"}))
        assert code == "write_blocked_masked_phone"

    def test_nested_receiver_phone_blocked(self):
        """嵌套载荷里的号码同样拦（`receiver.phone` / `receiver_phone` 都可能出现）。"""
        code, _ = self._blocked_code(self._run({"receiver": {"phone": "13800008000"}}))
        assert code == "write_blocked_masked_phone"

    # ── 放：不得误伤合法业务 ──

    def test_customer_explicit_new_number_passes(self):
        """顾客本轮明确给了这个号 → 放行（顾客是权威来源，不能拦）。"""
        assert self._run({"customer_phone": "13800008000"},
                         last_user_msg="用我另一个号 13800008000") is None

    def test_unrelated_new_number_passes(self):
        """换成完全不同的号码 → 放行（既不是掩码形态，也不是已知号的掩码变体）。"""
        assert self._run({"customer_phone": "13912345678"}) is None

    def test_unknown_number_without_known_phone_passes(self):
        """会话里没有已知真号时不得猜：`13800008000` 本身是合法真号，无权判它是脏数据。"""
        assert self._run({"customer_phone": "13800008000"}, known=()) is None

    def test_write_without_phone_arg_passes(self):
        assert self._run({"customer_name": "张三"}) is None

    def test_non_phone_value_in_phone_key_passes(self):
        """字段名以 `phone` 结尾 ≠ 值就是号码：分机备注 `分机#12` 含 `#` 但数字不足 → 不拦。

        （首版这条测试写成 `phone_model` —— 键名不以 phone 结尾，根本没走到本分支，
        变异测试当场判它"假守卫"；这类"字段选错/没走进代码"的测试必须靠变异才暴露。）
        """
        assert self._run({"contact_phone": "分机#12"}) is None


class TestMaskedPhoneWriteGuardWiring:
    """守卫必须**真的接在写路径上**（M68 教训：只测辅助函数 = 假守卫）。

    断言以"工具没被执行"为准 —— 拦下后 `order_create` 不得真的发出去。
    """

    def _run(self, args, user_msg="确认下单", store_extra=None, tool_name="order_create",
             read_only=False):
        import asyncio, json as _json

        seen = {"calls": []}
        full = {"grounded_product_detail": {"product_id": "p1"}}
        full.update(store_extra or {})

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            data = {"id": "o1"}
            if read_only:
                # 只读工具读回来的原文号码（守卫的"已知真号"判据来源）
                data = {"orderNo": "EVAL-ORD-0002", "customerPhone": "13800138000"}
            return (_json.dumps({"success": True, "data": data}),
                    {"success": True, "data": data})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                seen.setdefault("commits", []).append(dict(new_full))
                full.clear()
                full.update(new_full)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = read_only
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=[tool_name], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def test_masked_phone_never_reaches_tool(self):
        seen = self._run({"customer_name": "张三", "customer_phone": "13800008000"},
                         user_msg="我的手机号是 13800138000",
                         store_extra={KNOWN_RAW_PHONES_KEY: ["13800138000"]})
        assert seen["calls"] == [], "掩码变体号码不得真的调用 order_create（否则脏数据落库）"
        assert "write_blocked_masked_phone" in seen["tool_content"]
        assert "13800138000" in seen["tool_content"], "拦截后必须把真实号码回放给模型"

    def test_read_only_tool_not_blocked(self):
        """只读工具不拦：脏数据风险来自"用掩码值建单"，查询用掩码值只是查不到。

        这条同时是"守卫接线按 read_only 分流"的证据（拦错了会让查询白跑一轮）。
        """
        seen = self._run({"customer_phone": "13800008000", "keyword": "张三"},
                         tool_name="order_query", read_only=True,
                         store_extra={KNOWN_RAW_PHONES_KEY: ["13800138000"]})
        assert len(seen["calls"]) == 1, "只读工具被误拦 → 查询能力白丢一轮"

    def test_read_result_phone_is_remembered(self):
        """只读工具读到的真号必须被记住 —— 否则 C-A2 式流程（号码只来自历史订单）

        下一轮写工具就没有"已知真号"可比对，守卫形同虚设。
        """
        seen = self._run({"keyword": "我的订单"}, tool_name="order_query", read_only=True)
        merged = [p for c in seen.get("commits") or [] for p in (c.get(KNOWN_RAW_PHONES_KEY) or [])]
        assert "13800138000" in merged, f"读到的真号没进会话状态: {seen.get('commits')}"

    def test_clean_phone_still_reaches_tool(self):
        """不能拦成"下单永不成功"：正常号码必须照旧执行。"""
        seen = self._run({"customer_name": "张三", "customer_phone": "13800138000"},
                         user_msg="我的手机号是 13800138000",
                         store_extra={KNOWN_RAW_PHONES_KEY: ["13800138000"]})
        assert len(seen["calls"]) == 1, "正常号码被拦 → 真回归"


class TestCapabilityDenialInHandoffReason:
    """以「AI 自己做不到」为理由转人工 → 拦下（issue #3389，验收 C-A1 实证）。

    实证：C-A1 R9 `human_handoff(reason="顾客需协助下单（智能客服无法代为提交订单）")` ——
    而 order_create 就是 customer_order skill 自己的写工具（OR-014/017/018/019/020 都真实落单）。
    这类"能力误宣"比答错更伤：顾客明明要买，系统告诉他"我下不了单"，转化路径被自己掐断。

    判据只认**明确的自我能力否定**（无法代为提交/没法提交订单/无法帮您下单…），
    顾客显式诉求（"我要转人工"）、情绪诉求、以及正常业务理由（"顾客要求人工核价"）都不拦。
    """

    def test_ca1_reason_detected(self):
        assert _capability_denial_reason({"reason": "顾客需协助下单（智能客服无法代为提交订单）"})

    def test_variants_detected(self):
        """C-A1 原话的等价变体（**施动者是 AI 自己**的否定）。"""
        for why in ["我无法帮您提交订单", "小布没法提交订单", "智能客服无法代为下单",
                    "我没法帮您提交订单", "小布无法下单"]:
            assert _capability_denial_reason({"reason": why}), f"未识别: {why!r}"

    def test_third_party_subject_not_in_scope(self):
        """施动者不是 AI 自己的否定**刻意不认**（歧义大、易误伤）：

        「商品缺货不能创建订单」是**客观业务原因**，拦掉它等于把合法转人工堵死。
        顾客可见话术里的能力误宣由 `check_false_inability`（评测层）兜底。
        """
        assert _capability_denial_reason({"reason": "商品缺货不能创建订单"}) == ""

    def test_summary_field_scanned(self):
        assert _capability_denial_reason({"reason": "顾客需协助", "summary": "无法代为提交订单"})

    def test_legit_reasons_not_detected(self):
        for why in ["顾客明确要求转人工", "顾客情绪激动，需要人工安抚",
                    "顾客要求人工核对加工费", "订单信息有误，需要人工核实收货地址"]:
            assert not _capability_denial_reason({"reason": why}), f"误报: {why!r}"


class TestCapabilityDenialHandoffWiring:
    """守卫必须接在**转人工调用**上：能力误宣理由的 handoff 不得真的执行（issue #3389）。"""

    def _run(self, args, user_msg="确认下单", tool_name="human_handoff",
             pending="customer_order"):
        import asyncio, json as _json

        seen = {"calls": []}
        full = {"pending_interact_skill": pending} if pending else {}

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            return (_json.dumps({"success": True, "data": {"id": "h1"}}),
                    {"success": True, "data": {"id": "h1"}})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                full.clear()
                full.update(new_full)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = False
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=[tool_name], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def test_capability_denial_handoff_blocked(self):
        seen = self._run({"reason": "顾客需协助下单（智能客服无法代为提交订单）"})
        assert seen["calls"] == [], "以能力误宣为理由的转人工不得执行（顾客会以为系统坏了）"
        assert "order_create" in seen["tool_content"], "拦截时必须告诉模型它本来就能下单"

    def test_explicit_user_request_still_hands_off(self):
        """顾客显式要转人工 → 必须放行（不能把正确行为拦成故障）。"""
        seen = self._run({"reason": "顾客明确要求转人工"}, user_msg="我要转人工")
        assert len(seen["calls"]) == 1, "顾客显式要求转人工被拦 → 真回归"

    def test_normal_business_reason_still_hands_off(self):
        seen = self._run({"reason": "顾客要求人工核对加工费"}, user_msg="我要找人工核对加工费")
        assert len(seen["calls"]) == 1, "正常业务理由的转人工被拦 → 真回归"


class TestCurtainCalcDimensionGuard:
    """算料必须以**顾客给的窗户尺寸**为前提（issue #3395，DB 实证多收 3 倍钱）。

    实证（run 34748745308，OR-022）：顾客「我想买遮光窗帘，米白 **3 米**，要纳米圈打孔加工」
    —— 说的是**买 3 米布**；模型却把它当成「窗宽 3 米」，再把窗高默认成 2.7 米去算料：

        P = ceil((3+0.3)×2/2.8) = 3 幅，M = 3×(2.7+0.3) = **9.0 米**

    → `order_create{遮光窗帘×9@168}` 落库 **¥1584**（顾客要的是 ¥528）。同轮还出现 `×9.3`。
    这类"把购买米数当窗宽再乘褶皱倍数"是**钱的正确性**问题，且顾客视角完全无法察觉。

    判据：会话里**必须出现过窗户尺寸措辞**（窗宽/窗高/宽度/高度/尺寸/多宽/多高/米宽/米高）
    才允许算料 —— 模型若需要尺寸会先问，问过之后会话里自然就有这些词 → 自愈，不卡死。
    """

    def test_dimension_mentioned_allows(self):
        for t in ["窗宽 3 米 窗高 2.7 米 2 倍褶皱 帮我算",
                  "3米宽 2.5米高 2倍褶皱 打孔帘 用98元一米",
                  "我家窗户尺寸是 3 米 2.7 米",
                  "窗户多宽多高我量一下"]:
            assert _conversation_mentions_dimensions([HumanMessage(content=t)]), f"误拦: {t!r}"

    def test_purchase_meters_not_dimensions(self):
        """顾客说"要 3 米"是**购买数量**，不是窗户尺寸 → 不得算料（本 issue 的形态）。"""
        msgs = [HumanMessage(content="我想买遮光窗帘，米白 3 米，要纳米圈打孔加工"),
                AIMessage(content="好的，帮您看看～"), HumanMessage(content="3 米")]
        assert not _conversation_mentions_dimensions(msgs), "把购买米数当窗宽 = 多收 3 倍钱"


class TestCurtainCalcDimensionGuardWiring:
    """守卫必须接在工具调用上：无尺寸证据时 curtain_calc 不得真的执行。"""

    def _run(self, args, user_msg="我想买遮光窗帘，米白 3 米，要纳米圈打孔加工",
             tool_name="curtain_calc", history=None):
        import asyncio, json as _json

        seen = {"calls": []}

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            return (_json.dumps({"success": True, "data": {"fabric_meters": 9.0}}),
                    {"success": True, "data": {"fabric_meters": 9.0}})

        class _Store:
            async def load(self, sid):
                return {}

            async def commit(self, sid, f):
                return None

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = True
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            msgs = list(history or []) + [HumanMessage(content=user_msg)]
            res = asyncio.run(execute_skill(
                state=_make_state(messages=msgs),
                skill_name="customer_order",
                tool_names=[tool_name], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def test_calc_blocked_without_dimensions(self):
        seen = self._run({"window_width": 3.0, "window_height": 2.7, "fabric_price": 168.0})
        assert seen["calls"] == [], "顾客没给窗户尺寸就不得算料（会把 3 米算成 9 米）"
        assert "窗" in seen["tool_content"], "必须告诉模型去问窗户尺寸"

    def test_calc_allowed_with_dimensions(self):
        seen = self._run({"window_width": 3.0, "window_height": 2.7, "fabric_price": 168.0},
                         user_msg="窗宽 3 米 窗高 2.7 米 2 倍褶皱 打孔帘 用 98 元一米")
        assert len(seen["calls"]) == 1, "顾客给了尺寸却拦下 → 真回归"

    def test_other_tools_unaffected(self):
        seen = self._run({"keyword": "窗帘"}, tool_name="product_search")
        assert len(seen["calls"]) == 1


class TestConfirmCardFingerprintByContent:
    """confirm 卡的"同一张"判据必须是**内容**，不是标题措辞（issue #3397 实测）。

    实证（run 34751749165，OR-023）：同一张确认卡被模型换了措辞重发 ——
    日志里 `请确认订单信息` ×7、`请确认您的订单信息` ×2 —— 按标题做指纹会当成两张不同的卡，
    于是"同一张卡连发 3 次"的守卫漏判，顾客被反复要求确认同一件事（确认死循环），
    写操作也被拖着不落库。
    """

    def _fp(self, **kw):
        base = {"component": "confirm", "title": "请确认订单信息",
                "fields": [{"label": "商品", "value": "遮光窗帘 米白 3米"},
                           {"label": "总价", "value": "¥528"}]}
        base.update(kw)
        return lr2.card_fingerprint(base)

    def test_title_wording_ignored(self):
        """只换措辞 → 仍是同一张卡（必须同指纹）。"""
        assert self._fp() == self._fp(title="请确认您的订单信息"), "换措辞被当成新卡 = 守卫漏判"

    def test_content_change_is_new_card(self):
        """内容变了（数量 3→4、总价变）→ 是**新卡**（合法重发必须放行）。"""
        other = self._fp(fields=[{"label": "商品", "value": "遮光窗帘 米白 4米"},
                                 {"label": "总价", "value": "¥704"}])
        assert self._fp() != other, "内容变了却同指纹 → 合法重发会被误拦"

    def test_choice_card_still_uses_options(self):
        a = lr2.card_fingerprint({"component": "choice", "title": "选颜色",
                                  "options": [{"value": "1", "label": "米白"}]})
        b = lr2.card_fingerprint({"component": "choice", "title": "选颜色",
                                  "options": [{"value": "2", "label": "浅灰"}]})
        assert a != b, "choice 卡换了选项必须是新卡"


class TestConfirmCardLoopWiring:
    """接线：换措辞的重发必须真的被 `_card_loop_block` 拦下（第 3 次起）。"""

    def _run(self, counts_key_value):
        import asyncio, json as _json
        full = {"card_emit_counts": counts_key_value}

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, f):
                full.clear(); full.update(f)

        args = {"component": "confirm", "title": "请确认您的订单信息",
                "fields": [{"label": "商品", "value": "遮光窗帘 米白 3米"},
                           {"label": "总价", "value": "¥528"}]}
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(lr2._card_loop_block(
                "interact", args, {"name": "interact", "args": args, "id": "c1"},
                "sess_1", "customer_order"))

    def test_third_wording_variant_blocked(self):
        """前两次是另一种措辞、这次换了措辞 → 计数命中（内容同）→ 第 3 次拦下。"""
        fp = lr2.card_fingerprint({"component": "confirm", "title": "请确认订单信息",
                                   "fields": [{"label": "商品", "value": "遮光窗帘 米白 3米"},
                                              {"label": "总价", "value": "¥528"}]})
        out = self._run({fp: 2})
        assert out is not None, "同一张确认卡（换措辞）第 3 次必须被拦下"
        import json as _json
        assert _json.loads(out[1]).get("error") == "card_blocked_repeat_emission"


class TestFormPrefillFidelity:
    """收货信息表单的**预填值必须逐字保真**（issue #3397，实测 run 34750771576）。

    实证：OR-023 老客户下单，库里地址是 `浙江省杭州市西湖区文三路 1 号 1 幢 101 室`，
    模型预填成 `浙江省杭州市西湖区文三路 100 号`（**库里/会话里都没有这个地址**）——
    顾客若不逐字核对就直接提交，订单会寄到错地址；号码同理（掩码值回流更危险）。
    修法：预填值必须来自工具返回值**逐字复制**；模型改写时拦下并回放真值。
    """

    KNOWN_ADDR = "浙江省杭州市西湖区文三路 1 号 1 幢 101 室"
    KNOWN_PHONE = "13800138000"

    def _run(self, form_fields, args=None, last_user_msg="帮我下单，遮光窗帘 3 米",
             known=None):
        import asyncio, json as _json
        store = {"known_raw_phones": [self.KNOWN_PHONE],
                 "known_customer_address": [self.KNOWN_ADDR]}
        store.update(known or {})

        class _Store:
            async def load(self, sid):
                return dict(store)

            async def commit(self, sid, f):
                store.clear(); store.update(f)

        a = args or {"component": "form", "title": "请确认收货信息",
                     "formFields": form_fields}
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *x, **k: _Store()):
            return asyncio.run(_form_prefill_fidelity_block(
                "interact", a, {"name": "interact", "args": a, "id": "c1"},
                "sess_1", "customer_order", last_user_msg,
                {"messages": [], "role": "customer"}))

    def _code(self, out):
        import json as _json
        assert out is not None, "该预填值必须被拦下（改写会造成错寄/掩码建号）"
        return _json.loads(out[1]).get("error"), _json.loads(out[1]).get("message", "")

    def test_mangled_address_blocked(self):
        code, msg = self._code(self._run([
            {"key": "customer_address", "label": "收货地址",
             "value": "浙江省杭州市西湖区文三路 100 号"}]))
        assert code == "form_prefill_altered"
        assert self.KNOWN_ADDR.replace(" ", "") in msg.replace(" ", ""), f"必须回放真值: {msg!r}"

    def test_masked_phone_blocked(self):
        code, _ = self._code(self._run([
            {"key": "customer_phone", "label": "手机号", "value": "138****8000"}]))
        assert code == "form_prefill_altered"

    def test_verbatim_address_passes(self):
        assert self._run([{"key": "customer_address", "value": self.KNOWN_ADDR}]) is None

    def test_whitespace_variant_passes(self):
        """空格差异不算改写（顾客看到的仍是同一地址）。"""
        assert self._run([{"key": "customer_address",
                           "value": "浙江省杭州市西湖区文三路1号1幢101室"}]) is None

    def test_customer_supplied_new_address_passes(self):
        """顾客本条消息**自己给了新地址** → 预填它是对的，不得拦。"""
        out = self._run([{"key": "customer_address", "value": "上海市浦东新区世纪大道 1 号"}],
                        last_user_msg="改成上海市浦东新区世纪大道 1 号")
        assert out is None

    def test_no_known_value_passes(self):
        """会话里没有历史收货信息（新客）→ 无从比对，不拦（OR-022 路径）。"""
        out = self._run([{"key": "customer_address", "value": "随便写的地址"}],
                        known={"known_customer_address": []})
        assert out is None

    def test_non_form_interact_untouched(self):
        out = self._run([], args={"component": "confirm", "title": "确认订单",
                                  "fields": [{"label": "地址", "value": "x"}]})
        assert out is None


class TestFormPrefillFidelityWiring:
    """守卫与**数据来源**都必须接线（M177/M178 抓出的假守卫）。

    只测辅助函数会漏两件事：① 守卫没接在 `interact` 调用路径上（拦不住）；
    ② 读工具返回的地址没被记住（守卫没有真值可比 → 恒放行）。两条都必须有集成证据。
    """

    KNOWN_ADDR = "浙江省杭州市西湖区文三路 1 号 1 幢 101 室"

    def _run(self, args, tool_name="interact", store_extra=None, read_data=None):
        import asyncio, json as _json

        seen = {"calls": [], "commits": []}
        full = {"known_customer_address": [self.KNOWN_ADDR]}
        full.update(store_extra or {})

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            data = read_data if read_data is not None else {"ok": True}
            return (_json.dumps({"success": True, "data": data}),
                    {"success": True, "data": data})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                seen["commits"].append(dict(new_full))
                full.clear(); full.update(new_full)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = tool_name != "interact"
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="帮我下单，遮光窗帘 3 米")]),
                skill_name="customer_order", tool_names=[tool_name], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def test_altered_prefill_never_reaches_customer(self):
        seen = self._run({"component": "form", "title": "请确认收货信息",
                          "formFields": [{"key": "customer_address", "label": "收货地址",
                                          "value": "浙江省杭州市西湖区文三路 100 号"}]})
        assert seen["calls"] == [], "被改写的预填值不得下发（顾客会寄错地址）"
        assert "文三路" in seen["tool_content"], "拦截时必须回放真值"

    def test_verbatim_prefill_passes(self):
        seen = self._run({"component": "form", "title": "请确认收货信息",
                          "formFields": [{"key": "customer_address", "value": self.KNOWN_ADDR}]})
        assert len(seen["calls"]) == 1, "逐字保真的预填被拦 → 真回归"

    def test_read_tool_address_is_remembered(self):
        """读工具返回的地址必须被记住 —— 否则守卫没有真值可比（M178 的形态）。"""
        seen = self._run({"keyword": "x"}, tool_name="customer_address_query",
                         store_extra={"known_customer_address": []},
                         read_data={"has_address": True, "customer_address": self.KNOWN_ADDR})
        merged = [a for c in seen.get("commits") or []
                  for a in (c.get("known_customer_address") or [])]
        assert self.KNOWN_ADDR in merged, f"地址没进会话状态: {seen.get('commits')}"


class TestQuantityChoiceGuard:
    """澄清卡不得把顾客给的数量当窗宽、给出 2 倍用量选项（issue #3402，C-A1 实证）。

    实证（run 34753219595 等，C-A1 主路径）：
      R4 用户「数量 3 米」→ Agent 却发出
      `choice: 请选择窗帘用量 → 3米（¥528，基本无褶皱） | **6米（约¥1056，褶皱饱满，推荐）**`
      —— 顾客说的 3 米就是买 3 米布，Agent 当成窗宽按褶皱倍数算成 6 米，**还标为推荐**（2 倍钱）；
      这张多余卡每轮吃掉一次交互，C-A1 的 repeat_until 用完仍未落单（order_create 未调用）。
    同一认知错误的**第三个出口**（前两个已修：`curtain_calc` 工具层 #3395、入参层 #3394），
    故必须在**产出层（卡片）**也拦。
    """

    def _msgs(self, *texts, role="human"):
        from langchain_core.messages import HumanMessage, AIMessage
        cls = HumanMessage if role == "human" else AIMessage
        return [cls(content=t) for t in texts]

    def test_stated_quantity_extracted(self):
        qs = _stated_purchase_quantities(self._msgs("数量 3 米", "我要买 2.5 米布"))
        assert 3.0 in qs and 2.5 in qs, qs

    def test_plain_measure_without_intent_not_quantity(self):
        """「窗户 3 米宽」不是购买数量（有尺寸语义）→ 不得当数量。"""
        qs = _stated_purchase_quantities(self._msgs("窗户 3 米宽 2.7 米高"))
        assert 3.0 not in qs, qs

    def _run(self, args, msgs):
        import asyncio, json as _json
        class _Store:
            async def load(self, sid):
                return {}
            async def commit(self, sid, f):
                return None
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(_quantity_choice_block(
                "interact", args, {"name": "interact", "args": args, "id": "c1"},
                "sess_1", "customer_order", {"messages": msgs, "role": "customer"}))

    def _card(self, title, labels):
        return {"component": "choice", "title": title,
                "options": [{"label": l, "value": l} for l in labels]}

    def test_ca1_card_blocked(self):
        """C-A1 原卡：用量框架 + 6 米（=2×3）→ 必须拦下。"""
        out = self._run(self._card("请选择窗帘用量（米白·纳米圈打孔）",
                                   ["3米（¥528，基本无褶皱）", "6米（约¥1056，褶皱饱满，推荐）"]),
                        self._msgs("你好，我想买窗帘", "第一款吧，白色，2.8 米门幅，按米卖",
                                   "纳米圈打孔", "数量 3 米"))
        assert out is not None, "2 倍用量选项必须拦下（会把 528 变成 1056）"
        import json as _json
        msg = _json.loads(out[1]).get("message", "")
        assert "3" in msg and "用量" in msg or "数量" in msg, msg

    def test_no_quantity_stated_passes(self):
        """顾客没报过数量 → 无从判断，放行（避免误伤正常选品引导）。"""
        assert self._run(self._card("请选择窗帘用量", ["3米", "6米"]),
                         self._msgs("你好，我想买窗帘")) is None

    def test_customer_added_pleat_request_passes(self):
        """顾客**明确要求**加倍用量（褶皱饱满）→ 放行（这是顾客自己要的）。"""
        out = self._run(self._card("请选择窗帘用量", ["3米", "6米"]),
                        self._msgs("数量 3 米", "我想要褶皱饱满一点，用量加倍吧"))
        assert out is None

    def test_non_multiple_option_passes(self):
        """选项不是倍数（如 2.5/3/3.5 米）→ 不是本缺陷形态，放行。"""
        assert self._run(self._card("请选择窗帘用量", ["2.5米", "3米", "3.5米"]),
                         self._msgs("数量 3 米")) is None

    def test_other_components_untouched(self):
        out = self._run({"component": "confirm", "title": "请确认订单信息",
                         "fields": [{"label": "总价", "value": "¥528"}]},
                        self._msgs("数量 3 米"))
        assert out is None


class TestQuantityChoiceGuardWiring:
    """接线：C-A1 那张「用量」卡必须**真的发不出去**（issue #3402）。

    只测辅助函数会漏"守卫没接在 interact 调用路径上"（本 session 已两次抓出该形态的假守卫）。
    """

    def _run(self, args, user_msgs):
        import asyncio, json as _json
        seen = {"calls": []}

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            return (_json.dumps({"success": True, "data": {"ok": True}}),
                    {"success": True, "data": {"ok": True}})

        class _Store:
            async def load(self, sid):
                return {}

            async def commit(self, sid, f):
                return None

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = "interact"
            tool.read_only = True
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == "interact" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "interact", "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            msgs = [HumanMessage(content=t) for t in user_msgs]
            res = asyncio.run(execute_skill(
                state=_make_state(messages=msgs), skill_name="customer_order",
                tool_names=["interact"], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def _ca1_card(self):
        return {"component": "choice", "title": "请选择窗帘用量（米白·纳米圈打孔）",
                "options": [{"label": "3米（¥528，基本无褶皱）", "value": "数量3米，米白，纳米圈打孔"},
                            {"label": "6米（约¥1056，褶皱饱满，推荐）", "value": "数量6米，米白，纳米圈打孔"}]}

    def test_ca1_card_never_reaches_customer(self):
        seen = self._run(self._ca1_card(),
                         ["你好，我想买窗帘", "第一款吧，白色，2.8 米门幅，按米卖",
                          "纳米圈打孔", "数量 3 米"])
        assert seen["calls"] == [], "把顾客的 3 米当窗宽、推荐 6 米的卡不得下发"
        assert "3" in seen["tool_content"], "拦截时必须说明顾客已给 3 米"

    def test_normal_choice_card_passes(self):
        seen = self._run({"component": "choice", "title": "请选择窗帘颜色",
                          "options": [{"label": "米白", "value": "米白"},
                                      {"label": "浅灰", "value": "浅灰"}]},
                         ["数量 3 米"])
        assert len(seen["calls"]) == 1, "正常选色卡被拦 → 真回归"


class TestGuardsPersonaScope:
    """B / C 两端**共用** base_skill：C 端语义守卫必须只对顾客身份生效。

    背景（人工提醒固化）：`interact` 工具与全部技能守卫都在共享的 `base_skill` 里 ——
    两端卡片由同一个工具产出。若不显式分端，C 端专属判据会作用到 B 端米宝/客服场景：
      · "顾客说买 X 米被当窗宽" → B 端店员代客下单给出"用量/褶皱"选项可能是合法业务动作；
      · "顾客收货信息预填" → B 端客服改客户资料的表格同名 key（customer_phone/address）语义不同。
    分端原则：
      · **C 端语义**守卫（数量口径 / 收货预填 / 算料前提）→ 仅 `role == customer`；
      · **通用数据完整性**守卫（掩码手机号写库）→ 两端都生效（错号码对谁都是错）。
    """

    def _state(self, role):
        from langchain_core.messages import HumanMessage
        return {"role": role, "messages": [HumanMessage(content="数量 3 米")]}

    def _choice_args(self):
        return {"component": "choice", "title": "请选择窗帘用量",
                "options": [{"label": "3米（¥528）", "value": "3米"},
                            {"label": "6米（¥1056，推荐）", "value": "6米"}]}

    def _run_choice(self, role):
        import asyncio
        class _Store:
            async def load(self, sid):
                return {}
            async def commit(self, sid, f):
                return None
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(_quantity_choice_block(
                "interact", self._choice_args(),
                {"name": "interact", "args": self._choice_args(), "id": "c1"},
                "sess_1", "customer_order", self._state(role)))

    def test_quantity_choice_guard_customer_only(self):
        assert self._run_choice("customer") is not None, "C 端必须拦（2 倍用量 = 多收钱）"
        for role in ("admin", "agent", "tenant_admin", ""):
            assert self._run_choice(role) is None, f"role={role!r} 时不该拦（B 端不受影响）"

    def _run_prefill(self, role):
        import asyncio
        args = {"component": "form", "title": "客户资料",
                "formFields": [{"key": "customer_phone", "label": "手机号",
                                "value": "138****8000"}]}
        class _Store:
            async def load(self, sid):
                return {"known_raw_phones": ["13800138000"]}
            async def commit(self, sid, f):
                return None
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(_form_prefill_fidelity_block(
                "interact", args, {"name": "interact", "args": args, "id": "c1"},
                "sess_1", "customer_order", "帮我下单", {"role": role, "messages": []}))

    def test_prefill_guard_customer_only(self):
        assert self._run_prefill("customer") is not None, "C 端掩码预填必须拦"
        for role in ("admin", "agent", ""):
            assert self._run_prefill(role) is None, f"role={role!r} 时不该拦（B 端改资料不受影响）"

    def _run_calc(self, role):
        import asyncio
        class _Store:
            async def load(self, sid):
                return {}
            async def commit(self, sid, f):
                return None
        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            return asyncio.run(_curtain_calc_dimension_block(
                "curtain_calc", {"window_width": 3.0, "window_height": 2.7},
                {"name": "curtain_calc", "args": {}, "id": "c1"},
                "sess_1", "customer_order", {"role": role, "messages": []}))

    def test_calc_guard_customer_only(self):
        assert self._run_calc("customer") is not None, "C 端无尺寸算料必须拦"
        for role in ("admin", "agent", ""):
            assert self._run_calc(role) is None, f"role={role!r} 时不该拦（B 端算料链路不受影响）"

    def test_masked_phone_write_guard_applies_to_both(self):
        """通用数据完整性守卫**两端都要生效**：错号码对 B 端顾客同样是错。"""
        import asyncio
        class _Store:
            async def load(self, sid):
                return {"known_raw_phones": ["13800138000"]}
            async def commit(self, sid, f):
                return None
        for role in ("customer", "admin", "agent"):
            with patch("app.memory.session_state_store.SessionStateStore",
                       side_effect=lambda *a, **k: _Store()):
                out = asyncio.run(_masked_phone_write_block(
                    "order_create", {"customer_phone": "138****8000"},
                    {"name": "order_create", "args": {}, "id": "c1"},
                    "sess_1", "customer_order", "确认下单",
                    {"role": role, "messages": []}))
            assert out is not None, f"role={role!r} 时掩码号码必须拦（通用完整性）"


class TestMibaoFlowsUnaffectedByCendGuards:
    """B 端（米宝）流程不得被 C 端守卫影响 —— 端到端接线级证据（人工提醒固化）。

    为什么必须单独测（而不是靠 CI）：本仓库的 B 端 eval（`agent-eval.yml` / PR gate 的
    smoke）打的是**生产** `ai-api.migaozn.com`，即它验证的是**已部署**的代码，
    **永远跑不到分支上的改动**（C 端有本地 docker 栈，B 端没有）。故"我改了共享的
    base_skill 会不会伤到 B 端"只能靠这里的接线级测试回答。

    覆盖两类：
      · C 端语义守卫（数量口径/收货预填/算料）→ 用 B 端 skill 跑同样形态的产物，**不得拦**；
      · 通用完整性守卫（掩码手机号写库）→ B 端**同样要拦**（错号码对 B 端顾客一样是错）。
    """

    def _run(self, tool_name, args, role="admin", skill="order", msgs=None,
             store=None, read_data=None):
        import asyncio, json as _json
        seen = {"calls": []}
        full = dict(store or {})

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            data = read_data if read_data is not None else {"ok": True}
            return (_json.dumps({"success": True, "data": data}),
                    {"success": True, "data": data})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, f):
                full.clear(); full.update(f)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = tool_name in ("interact", "product_search", "product_detail")
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            state = _make_state(messages=msgs or [HumanMessage(content="给张三下个单，3 米")])
            state["role"] = role
            res = asyncio.run(execute_skill(
                state=state, skill_name=skill, tool_names=[tool_name], system_prompt="p"))
        from langchain_core.messages import ToolMessage as _TM
        seen["tool_content"] = "\n".join(
            str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
            if isinstance(m, _TM))
        return seen

    def test_bend_quantity_choice_card_not_blocked(self):
        """B 端店员代客下单给出"用量/褶皱"选项可能是合法业务动作 → C 端守卫不得拦。"""
        seen = self._run("interact",
                         {"component": "choice", "title": "选择用量",
                          "options": [{"label": "3米", "value": "3米"},
                                      {"label": "6米", "value": "6米"}]},
                         role="admin", skill="order",
                         # ⚠️ 消息里必须**真的带数量意图**（"数量 3 米"）——首版写成
                         # "给张三下个单，3 米"（"下个单" 不匹配意图词）→ 守卫前置条件根本没满足，
                         # 去掉分端也不会红（变异 M194 当场判它假守卫）。
                         msgs=[HumanMessage(content="给张三下个单，数量 3 米，要打孔")])
        assert len(seen["calls"]) == 1, f"B 端被 C 端数量守卫误拦: {seen['tool_content'][:120]}"

    def test_bend_form_edit_not_blocked(self):
        """B 端客服改客户资料（同名 key customer_phone）不得被 C 端预填守卫拦。"""
        seen = self._run("interact",
                         {"component": "form", "title": "客户资料",
                          "formFields": [{"key": "customer_phone", "label": "手机号",
                                          "value": "138****8000"}]},
                         role="admin", skill="customer",
                         store={"known_raw_phones": ["13800138000"]})
        assert len(seen["calls"]) == 1, f"B 端改资料被 C 端预填守卫误拦: {seen['tool_content'][:120]}"

    def test_bend_calc_not_blocked(self):
        """B 端米宝的算料链路不受 C 端算料守卫影响。"""
        seen = self._run("curtain_calc",
                         {"window_width": 3.0, "window_height": 2.7, "fabric_price": 98.0},
                         role="admin", skill="order")
        assert len(seen["calls"]) == 1, "B 端算料被 C 端守卫误拦"

    def test_bend_masked_phone_still_blocked(self):
        """通用完整性守卫对 B 端**仍然生效**（错号码对 B 端顾客一样是错）。"""
        seen = self._run("order_create",
                         {"customer_name": "张三", "customer_phone": "138****8000",
                          "items": [{"product_name": "遮光窗帘", "quantity": 3,
                                     "unit_price": 168.0, "subtotal": 504.0}]},
                         role="admin", skill="order")
        assert seen["calls"] == [], "B 端用掩码号码建单必须同样拦下"
        assert "138" in seen["tool_content"], "拦截时必须回放真号"


class TestConfirmClosureCodeSide:
    """顾客确认后，写操作必须**由代码收口**，不能只靠模型自觉（issue #3410）。

    实证（run 34758421478，C-A1 主路径）：R7 顾客发的是确认卡回传值（系统自产的
    `确认：…` 串），模型回「这就帮您提交~」；R8/R9 顾客两次「确认下单」，模型回
    「都核对好啦」「还差最后一步」—— **整场没有任何 order_create 调用**，订单永不落库，
    验收 L1 报「期望调用 order_create，实际未调用」。
    同一剧本在别的轮次却能通过（模型碰巧调了写工具）→ 间歇性失败。

    既有机制只做到"注入执行提示"（`_inject_pending_validated`），**是否动手仍由模型决定**。
    本用例把收口前移到代码：顾客已明确确认 + 存在已校验待执行写 + 本轮模型没调那个写工具
    → **代码直接执行**（同一条执行路径：同样的门禁、同样的验证码回填链），
    并用工具返回的 message 作为给顾客的回复（真话，不是"这就帮您提交"）。
    """

    PENDING = {"pending_validated_input": {
        "target_tool": "order_create", "target_action": "create",
        "params": {"customer_name": "张三", "customer_phone": "13800138000"}}}

    def _run(self, user_msg, llm_reply, role="customer", store_extra=None,
             model_calls_write=False, fail_with=None):
        import asyncio, json as _json

        seen = {"calls": []}
        full = {"last_confirm_value": "确认：商品=北欧风窗帘；总价=¥408"}
        full.update(self.PENDING)
        full.update(store_extra or {})

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            if fail_with:
                return (_json.dumps({"success": False, "error": fail_with,
                                     "message": "为了您的账户安全，请输入短信验证码"}),
                        {"success": False, "error": fail_with,
                         "message": "为了您的账户安全，请输入短信验证码"})
            return (_json.dumps({"success": True, "data": {"id": "o1", "orderNo": "2026X"},
                                 "message": "订单已帮您提交好啦！订单号 2026X"}),
                    {"success": True, "data": {"id": "o1", "orderNo": "2026X"},
                     "message": "订单已帮您提交好啦！订单号 2026X"})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, f):
                full.clear(); full.update(f)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = "order_create"
            tool.read_only = False
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == "order_create" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            msgs = []
            if model_calls_write:
                call = MagicMock(spec=AIMessage)
                call.content = ""
                call.tool_calls = [{"name": "order_create", "args": {"customer_name": "张三"},
                                    "id": "c1"}]
                msgs.append(call)
            final = MagicMock(spec=AIMessage)
            final.content = llm_reply
            final.tool_calls = []
            msgs.append(final)
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=msgs)
            get_llm.return_value = llm
            state = _make_state(messages=[HumanMessage(content=user_msg)])
            state["role"] = role
            res = asyncio.run(execute_skill(
                state=state, skill_name="customer_order",
                tool_names=["order_create"], system_prompt="p"))
        return res, seen, full

    def test_close_loop_truth_table(self):
        """收口条件的真值表（纯函数，逐项钉住；M207 首版就因内联而无法被观察）。"""
        P = {"target_tool": "order_create"}
        assert _should_code_close_loop(P, "order_create", True, set()) is True
        assert _should_code_close_loop(None, "order_create", True, set()) is False, "无待执行写"
        assert _should_code_close_loop(P, "", True, set()) is False, "无目标工具"
        assert _should_code_close_loop(P, "order_create", False, set()) is False, "未确认不得代下单"
        assert _should_code_close_loop(P, "order_create", True, {"order_create"}) is False, \
            "模型已写过 → 不得重复执行（双单）"
        assert _should_code_close_loop(P, "order_create", True, {"product_search"}) is True

    def test_card_confirm_without_model_call_still_writes(self):
        """C-A1 形态：顾客回确认卡的值、模型只回话 → 代码必须把写执行掉。"""
        res, seen, full = self._run("确认：商品=北欧风窗帘；总价=¥408", "这就帮您提交~ 😊")
        assert len(seen["calls"]) == 1, "顾客已确认却没执行写 → 订单永不落库（C-A1 实证）"
        assert "2026X" in (res.get("final_answer") or ""), (
            f"回复必须基于真实执行结果，而不是'这就帮您提交': {res.get('final_answer')!r}")

    def test_text_confirm_also_closes(self):
        """口头确认（「确认下单」）同样收口。"""
        _res, seen, _f = self._run("确认下单", "好的~")
        assert len(seen["calls"]) == 1

    def test_no_confirmation_no_closure(self):
        """顾客没说确认（新需求/纠偏）→ 不得替顾客下单。"""
        _res, seen, _f = self._run("我再想想，先看看别的颜色", "好的~")
        assert seen["calls"] == [], "未确认就执行写 = 绕过确认门禁（安全性质）"

    def test_model_already_wrote_no_double_execution(self):
        """模型自己调了写工具 → 代码不得重复执行（防双单）。"""
        _res, seen, _f = self._run("确认下单", "好的~", model_calls_write=True)
        assert len(seen["calls"]) == 1, f"重复执行写成双单: {len(seen['calls'])} 次"

    def test_failure_surfaces_tool_message(self):
        """执行失败（如缺验证码）→ 把工具原话给顾客（要码），而不是空转话术。"""
        res, seen, _f = self._run("确认下单", "这就帮您提交~", fail_with="缺少短信验证码")
        assert len(seen["calls"]) == 1
        assert "验证码" in (res.get("final_answer") or ""), res.get("final_answer")

    def test_bend_role_not_closed_by_code(self):
        """B 端不受此收口影响（分端纪律：B 端流程各异，先只在 C 端收口）。"""
        _res, seen, _f = self._run("确认下单", "好的~", role="admin")
        assert seen["calls"] == [], "B 端被 C 端收口逻辑影响"


class TestFalseCancelGuard:
    """「算了」不得在**没有在办流程**时冒充取消（验收发现，issue #3367 / 协议 P1）。

    验收剧本 C-A2 实测（transcripts/ci-34730957920）：
      R1 用户「帮我查一下我的订单」→ 正常列单
      R2 用户「算了，先看看你们有什么窗帘」
         AI：「好的，**已取消**。有什么其他需要帮您的吗？」  ← 无任何工具调用
    两处危害：
      ① **假状态变更**：什么都没在办，却告诉顾客"已取消" —— 顾客可能以为订单/流程被取消了；
      ② **吞掉真实诉求**：「先看看你们有什么窗帘」被整句丢弃（没有 product_search）。
    根因：`_is_cancel_message` 把「算了」当无条件强取消，而 execute_skill 的短路分支
    **不检查"是否有在办流程"**。
    """

    def _run(self, user_msg, store=None, messages=None, pending_skill=""):
        import asyncio, json as _json

        class _Store:
            def __init__(self):
                self.full = dict(store or {})

            async def load(self, sid):
                return dict(self.full)

            async def commit(self, sid, f):
                self.full = dict(f)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as gb, \
             patch("app.graph.skills.base_skill.get_skill_llm") as gl, \
             patch("app.graph.skills.base_skill.create_skill_registry") as cr, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.return_value = None
            cr.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            gb.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "product_search", "args": {"keyword": "窗帘"}, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "为您找到几款热销窗帘"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            gl.return_value = llm
            st = _make_state(messages=messages or [HumanMessage(content=user_msg)])
            if pending_skill:
                st["pending_interact_skill"] = pending_skill
            return asyncio.run(execute_skill(
                state=st, skill_name="customer_order", tool_names=["product_search"],
                system_prompt="p")), llm

    def test_no_false_cancel_when_nothing_inflight(self):
        """没有在办流程时，「算了」不得短路成"已取消"，应正常处理顾客的新诉求。"""
        res, llm = self._run("算了，先看看你们有什么窗帘")
        assert "已取消" not in (res.get("final_answer") or ""), \
            "无在办流程却回「已取消」= 假状态变更（验收 C-A2 实证）"
        assert llm.ainvoke.call_count >= 1, "本该正常进入 ReAct（去处理『看看有什么窗帘』）"

    def test_cancel_still_short_circuits_when_inflight(self):
        """**有**在办流程时，取消仍应短路（原有能力不得退化）。"""
        # 消息序必须是"上一轮下发卡 → 顾客回应它"：卡夹在倒数第二条与最后一条用户消息之间
        res, llm = self._run("算了，不弄了", messages=[
            HumanMessage(content="帮我下单"),
            ToolMessage(content=json_dumps({"success": True, "data": {"component": "confirm"}}),
                        tool_call_id="t1", name="interact"),
            HumanMessage(content="算了，不弄了"),
        ])
        assert "已取消" in (res.get("final_answer") or ""), "在办流程中的取消必须照旧短路"

    def test_pending_skill_alone_must_not_authorize_cancel(self):
        """**流程锁定标记不是"有东西可取消"**（验收重放 run 34731714846 实证）。

        `pending_interact_skill` 在任何 CREATION_SKILL 跑过后都会被写入
        （`customer_order` ∈ 创建类 skill）—— 于是"查一次订单"也会点亮它，
        下一句「算了」照样回"已取消"（首版修复就是这么失效的，被验收重放抓到）。
        故本用例锁住：**只有标记、没有待答卡/待执行写** 时不得短路。
        """
        res, llm = self._run("算了", pending_skill="customer_order")
        assert "已取消" not in (res.get("final_answer") or ""), \
            "仅流程标记就短路 = 假取消（查单后说「算了」会误报已取消）"

    def test_pending_validated_in_store_counts_as_inflight(self):
        """已校验待执行的写操作 = 确有在办流程 → 取消应短路。"""
        res, _ = self._run("算了", store={"pending_validated_input": {
            "target_tool": "order_create", "target_action": "create"}})
        assert "已取消" in (res.get("final_answer") or ""), "有待执行写操作时必须短路"


def json_dumps(o):
    import json
    return json.dumps(o, ensure_ascii=False)


class TestProcessingItemsAskedPersistsCrossTurn:
    """加工项「已问过」必须跨轮记住（OR-017 死循环真因，issue #3365）。

    实证（CI run 34719134577，OR-017）：轨迹新增的 `cardreq=` 显示模型 R3/R4/R5/R6
    **每轮都在请求 confirm 卡**，但 `cards=` 只有 choice —— 因为 `_plan_processing_items_rewrite`
    只看**本轮**问没问过加工项：R2 已经问过并收到答案，R3 起每轮又把模型的 confirm 卡改写成
    同一张加工项卡 → confirm 卡永远落不了地 → 顾客反复答同一题、
    `check_confirm_loop` 判「confirm 卡出现 4 次（R3/R4/R5/R6）」。

    修法：把「加工项已问过」按**商品 id** 持久化到会话，跨轮生效；换商品（新 id）仍会正常再问。
    """

    _ITEMS = [{"id": "pi1", "name": "纳米圈打孔", "unitPrice": 8.0, "unit": "米",
               "pricingMethod": "per_meter"}]

    def _run(self, store_extra=None, product_id="prod_eval_summer"):
        import asyncio, json as _json
        seen = {"commits": []}
        full = dict(store_extra or {})

        async def fake_execute(tool, a, ctx, state):
            return (_json.dumps({"success": True, "data": {
                        "component": "confirm", "title": "请确认订单信息",
                        "confirmValue": "确认下单", "fields": []}}, ensure_ascii=False),
                    {"success": True, "data": {
                        "component": "confirm", "title": "请确认订单信息",
                        "confirmValue": "确认下单", "fields": []}})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                seen["commits"].append(dict(new_full))
                full.clear(); full.update(new_full)

        detail = ToolMessage(
            content=_json.dumps({"success": True, "data": {
                "id": product_id, "name": "夏日清风窗帘",
                "processing_items": self._ITEMS}}, ensure_ascii=False),
            tool_call_id="d1", name="product_detail")

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            for attr, val in (("name", "interact"), ("read_only", False),
                              ("destructive", False), ("requires_confirmation", False)):
                setattr(tool, attr, val)
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == "interact" else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "interact", "args": {
                "component": "confirm", "title": "请确认订单信息", "fields": []}, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="帮我下单"), detail]),
                skill_name="customer_order",
                tool_names=["interact"], system_prompt="p"))
        cards = []
        for m in (res or {}).get("messages", []):
            if isinstance(m, ToolMessage) and m.name == "interact":
                try:
                    cards.append(json.loads(m.content or "{}").get("data") or {})
                except Exception:
                    cards.append({})
        seen["cards"] = cards
        seen["final_store"] = full
        return seen

    def test_rewrite_happens_and_marks_asked(self):
        seen = self._run()
        assert seen["cards"] and seen["cards"][0].get("component") == "choice", \
            "没问过加工项时应改写为 choice 卡（原行为不能坏）"
        asked = seen["final_store"].get("processing_items_asked") or {}
        assert asked, "改写发了加工项卡却未记账 → 下一轮还会再改写（死循环）"

    def test_no_rewrite_when_same_product_already_asked(self):
        seen = self._run(store_extra={"processing_items_asked": {"prod_eval_summer": True}})
        assert seen["cards"] and seen["cards"][0].get("component") == "confirm", \
            "同一商品的加工项已经问过并答过 → confirm 卡必须**放行**（这轮死循环的直接原因）"

    def test_rewrite_happens_for_new_product(self):
        seen = self._run(store_extra={"processing_items_asked": {"prod_other": True}})
        assert seen["cards"] and seen["cards"][0].get("component") == "choice", \
            "换了商品（新 product_id）→ 加工项必须重新问，不能被上一个商品的记账误伤"

    def test_mark_is_per_product(self):
        """记账必须**按商品**：若一律记 `*`，顾客换个商品下单时加工项就再也问不出来了
        （M77 变异就是靠这条被测出来的 —— 首版没有它，变异存活）。"""
        import asyncio
        from app.graph.skills.base_skill import (
            _mark_processing_items_asked, _processing_items_already_asked)
        store = {}

        class _Store:
            async def load(self, sid):
                return dict(store)

            async def commit(self, sid, f):
                store.clear(); store.update(f)

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            asyncio.run(_mark_processing_items_asked("s1", "prod_a"))
            assert asyncio.run(_processing_items_already_asked("s1", "prod_a")), \
                "同一商品应判定为已问过"
            assert not asyncio.run(_processing_items_already_asked("s1", "prod_b")), \
                "换了商品必须判定为未问过（否则新商品的加工项永远问不出来）"

    def test_unknown_product_mark_still_suppresses(self):
        seen = self._run(store_extra={"processing_items_asked": {"*": True}})
        assert seen["cards"] and seen["cards"][0].get("component") == "confirm", \
            "商品 id 拿不到时的兜底记账（*）同样必须生效，否则该路径仍会死循环"


class TestWriteInputRecovery:
    """写工具缺参失败的「要参数」恢复回路（issue #3365，OR-017 CI 实证）。

    CI run 34716531345（OR-017）轨迹：
      R6 confirm 卡「请确认订单信息」→ R7 顾客「确认下单」→ `order_create!缺少短信验证码`
      → R8 顾客「确认」→ **又一张一模一样的 confirm 卡** + `order_create!缺少短信验证码`
      → R9 顾客「123456」被这张卡吃掉（harness 优先答卡）→ `确认死循环: confirm 卡共出现 3 次`。
    真因不是「模型不聪明」，而是代码允许它在缺参后**原样重发确认卡并重复调用注定失败的工具**：
    顾客点多少次确认都得不到「请输入验证码」这句话 —— 生产环境里人也会卡死。
    修法（与 handoff_blocked_inflight 同族）：缺参失败后
      ① 跨轮记住「欠哪个参数」，把「向顾客索要该参数」的指令注入下一轮系统提示；
      ② 该参数仍未到手时，**不再放行同一个写工具**（省掉注定失败的调用）；
      ③ 同一张确认卡（confirmValue 逐字相同）不得二次下发。
    """

    _FLAG = {"tool": "order_create", "error": "缺少短信验证码",
             "message": "为了您的账户安全，创建订单前需要验证手机号。请输入短信验证码",
             "param": "sms_code"}

    def _run(self, user_msg, args, tool_name="order_create", store_extra=None,
             force_fail=None):
        import asyncio, json as _json

        seen = {"calls": [], "commits": []}
        # 前置闸门必须先在夹具里满足（接地闸门会拦未查详情的 order_create）——
        # 否则测的不是本类要测的「缺参恢复」，而是接地闸门（首版夹具就被它误伤：
        # 两个用例都返回 product_not_grounded，断言以"没有调用"通过了，属假绿）。
        full = {"grounded_product_detail": {"product_id": "p1"}}
        full.update(store_extra or {})

        async def fake_execute(tool, a, ctx, state):
            seen["calls"].append((tool, a))
            if force_fail:
                return (force_fail, _json.loads(force_fail))
            return (_json.dumps({"success": True, "data": {"id": "o1"}}),
                    {"success": True, "data": {"id": "o1"}})

        class _Store:
            async def load(self, sid):
                return dict(full)

            async def commit(self, sid, new_full):
                seen["commits"].append(dict(new_full))
                full.clear()
                full.update(new_full)

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            tool = MagicMock()
            tool.name = tool_name
            tool.read_only = False
            tool.destructive = False
            tool.requires_confirmation = False
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: tool if n == tool_name else None
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": tool_name, "args": args, "id": "c1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="customer_order",
                tool_names=[tool_name], system_prompt="p"))
        try:
            from langchain_core.messages import ToolMessage as _TM
            seen["tool_content"] = "\n".join(
                str(getattr(m, "content", "")) for m in (res or {}).get("messages", [])
                if isinstance(m, _TM))
        except Exception:
            seen["tool_content"] = ""
        seen["result"] = res
        seen["final_store"] = dict(full)
        # 抓下发往 LLM 的消息：注入是否**真的到达系统提示**（M68 存活实证：只测
        # 辅助函数会漏掉"接线断了"——改了实现也没人发现）
        try:
            _msgs = llm.ainvoke.call_args_list[0][0][0] if llm.ainvoke.call_args_list else []
            seen["sys_prompt"] = "\n".join(str(getattr(m, "content", "")) for m in _msgs)
        except Exception:
            seen["sys_prompt"] = ""
        return seen

    # ── ① 缺参未补齐 → 不再放行同一个写工具 ──

    def test_repeat_write_blocked_while_waiting_for_input(self):
        seen = self._run("确认", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        assert seen["calls"] == [], \
            "顾客还没给验证码，重复调用 order_create 只会再失败一次（CI 里正是这条 ×2）"

    def test_blocked_write_reports_actionable_guidance(self):
        seen = self._run("确认", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        # 拦截时给模型的 ToolMessage 必须点名要什么，否则模型只能靠猜
        assert "验证码" in self._last_tool_content(seen)

    def _last_tool_content(self, seen):
        return seen.get("tool_content", "")

    def test_write_allowed_once_customer_supplies_code(self):
        seen = self._run("123456", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        assert len(seen["calls"]) == 1, "顾客已给验证码 → 必须放行（否则订单永远落不了库）"
        assert seen["calls"][0][1].get("sms_code") == "123456"

    def test_no_block_without_pending_input_error(self):
        seen = self._run("确认", {"items": []})
        assert len(seen["calls"]) == 1, "没有欠参标记时不得拦截（不能误伤正常下单）"

    def test_any_card_blocked_while_waiting_for_input(self):
        """欠参期间**任何卡片**都不该下发（不只 confirm）。

        实证（run 34721434317，CH-010 首跑）：R6/R7 两张**不同的**卡（choice/confirm）
        各自把"顾客要发的验证码"这一轮吃掉 → R7 order_create!缺少短信验证码。
        故欠参等待期一律不发卡，改用文本索要 —— 这样即使用例没声明 prefer_text，
        验证码也能作为文本落到 agent 手里。
        """
        seen = self._run(
            "已选加工项：纳米圈打孔",
            {"component": "form", "title": "请确认收货信息", "fields": []},
            tool_name="interact",
            store_extra={"last_write_input_error": self._FLAG})
        assert seen["calls"] == [], "欠参等待期发卡 = 抢走顾客要发的验证码（CH-010 实测形态）"

    def test_card_allowed_once_code_supplied(self):
        seen = self._run(
            "123456",
            {"component": "form", "title": "请确认收货信息", "fields": []},
            tool_name="interact",
            store_extra={"last_write_input_error": self._FLAG})
        assert len(seen["calls"]) == 1, "顾客已给验证码 → 卡照常可用（不能把会话锁死）"

    # ── ② 失败即记账 ──

    def test_missing_input_failure_recorded(self):
        seen = self._run("确认", {"items": []},
                         force_fail='{"success": false, "error": "缺少短信验证码"}')
        flags = [c.get("last_write_input_error") for c in seen["commits"]
                 if c.get("last_write_input_error")]
        assert flags, "缺参失败必须跨轮记账，否则下一轮无从知道该要什么"
        assert flags[0].get("param") == "sms_code"

    def test_success_clears_flag(self):
        seen = self._run("123456", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        assert not seen["final_store"].get("last_write_input_error"), \
            "写成功后必须清账，否则后续轮次被永久拦住"

    def test_other_tool_success_does_not_clear_flag(self):
        """只读工具成功不得清账：否则 product_search 一成功，欠参标记就被顺手抹掉，
        下一轮又回到「重发确认卡 + 重复调用注定失败的写工具」的老路。"""
        seen = self._run("确认", {"keyword": "窗帘"}, tool_name="product_search",
                         store_extra={"last_write_input_error": self._FLAG})
        assert seen["final_store"].get("last_write_input_error"), \
            "product_search 成功清掉了 order_create 的欠参标记"

    def test_unrecognizable_missing_param_not_recorded(self):
        """判不出"已补齐"的参数（商品明细）不得记账：否则该写工具被**永久**拦住，
        真实顾客说"就是刚才那款"也解不开。"""
        seen = self._run("确认", {"items": []},
                         force_fail='{"success": false, "error": "缺少商品明细"}')
        assert not seen["final_store"].get("last_write_input_error"), \
            "记账了不可识别的参数 → 该写工具将被永久锁死"

    # ── ③ 同一张确认卡不得二次下发 ──

    def test_same_confirm_card_not_reissued_while_waiting_for_input(self):
        seen = self._run(
            "确认",
            {"component": "confirm", "title": "请确认订单信息",
             "confirmValue": "确认下单", "fields": []},
            tool_name="interact",
            store_extra={"last_write_input_error": self._FLAG,
                         "last_confirm_value": "确认下单"})
        assert seen["calls"] == [], \
            "缺参等待期重发同一张确认卡 = 死循环（顾客点多少次都拿不到验证码提示）"

    def test_confirm_card_allowed_when_nothing_missing(self):
        seen = self._run(
            "确认",
            {"component": "confirm", "title": "请确认订单信息",
             "confirmValue": "确认下单", "fields": []},
            tool_name="interact",
            store_extra={"last_confirm_value": "确认下单"})
        assert len(seen["calls"]) == 1, "没有欠参标记时必须正常下发确认卡"

    # ── ④ 同一张卡反复下发（不限 confirm：choice 卡同样会死循环）──

    def test_same_choice_card_blocked_on_third_emission(self):
        """实证（CI run 34718498228，OR-017）：同一张「加工项」choice 卡连发 5 次
        （R2-R6），顾客每次都把同样的答案回给它 —— 真人会以为系统坏了。
        前两次放行（首次 + 一次合理重问），第三次起拦下并给出可执行指引。"""
        seen = self._run(
            "已选加工项：纳米圈打孔",
            {"component": "choice", "title": "这款商品支持以下加工项，需要哪些呢？（可多选）",
             "options": [{"label": "纳米圈打孔 ¥8/米"}, {"label": "不需要加工"}]},
            tool_name="interact",
            store_extra={"card_emit_counts": {
                "choice|这款商品支持以下加工项，需要哪些呢？（可多选）|纳米圈打孔 ¥8/米、不需要加工": 2}})
        assert seen["calls"] == [], "同一张 choice 卡已发 2 次，第 3 次必须拦下（否则就是 5 连发）"

    def test_same_choice_card_allowed_on_second_emission(self):
        seen = self._run(
            "已选加工项：纳米圈打孔",
            {"component": "choice", "title": "这款商品支持以下加工项，需要哪些呢？（可多选）",
             "options": [{"label": "纳米圈打孔 ¥8/米"}, {"label": "不需要加工"}]},
            tool_name="interact",
            store_extra={"card_emit_counts": {
                "choice|这款商品支持以下加工项，需要哪些呢？（可多选）|纳米圈打孔 ¥8/米、不需要加工": 1}})
        assert len(seen["calls"]) == 1, "第 2 次属合理重问，不能拦"

    def test_changed_options_is_a_different_card(self):
        """选项变了就是**另一张卡**（顾客改了商品/规格后重新确认）→ 不得误伤。"""
        seen = self._run(
            "已选加工项：纳米圈打孔",
            {"component": "choice", "title": "这款商品支持以下加工项，需要哪些呢？（可多选）",
             "options": [{"label": "折边 ¥5/米"}, {"label": "不需要加工"}]},
            tool_name="interact",
            store_extra={"card_emit_counts": {
                "choice|这款商品支持以下加工项，需要哪些呢？（可多选）|纳米圈打孔 ¥8/米、不需要加工": 5}})
        assert len(seen["calls"]) == 1, "选项变了 = 新卡，不该被旧卡的计数拦住"

    def test_emission_counted_on_success(self):
        seen = self._run(
            "已选加工项：纳米圈打孔",
            {"component": "choice", "title": "选一下加工项"},
            tool_name="interact")
        counts = seen["final_store"].get("card_emit_counts") or {}
        assert counts.get("choice|选一下加工项|") == 1, "卡发出后必须计数，否则永远拦不住第 3 次"

    # ── ⑤ 提示注入 ──

    def test_directive_injected_while_waiting(self):
        import asyncio as _asyncio
        from app.graph.skills.base_skill import _inject_write_input_recovery

        _flag = dict(self._FLAG)   # 闭包捕获：嵌套类里的 self 是 store 自己，不是测试实例

        class _Store:
            async def load(self, sid):
                return {"last_write_input_error": _flag}

            async def commit(self, sid, full):
                pass

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            out = _asyncio.run(_inject_write_input_recovery(
                "BASE", {"session_id": "sess_001"}, "确认"))
        assert out != "BASE", "缺参等待期必须注入指令，否则模型不知道要主动索要"
        assert "验证码" in out
        assert "确认卡" in out, "必须显式禁止重发确认卡（模型层不遵从才是真因）"
        assert "BASE" in out

    def test_directive_reaches_llm_system_prompt(self):
        """接线断言：注入必须真的进入本轮系统提示（否则模型永远看不到索要指令）。"""
        seen = self._run("确认", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        assert "上一轮写操作失败" in seen["sys_prompt"], \
            "索要指令没进系统提示 → 注入形同虚设"
        assert "禁止" in seen["sys_prompt"]

    def test_no_directive_in_prompt_once_code_supplied(self):
        seen = self._run("123456", {"items": []},
                         store_extra={"last_write_input_error": self._FLAG})
        assert "上一轮写操作失败" not in seen["sys_prompt"], \
            "顾客已给验证码，还注入索要指令会干扰正常下单"

    def test_directive_absent_when_code_supplied(self):
        import asyncio as _asyncio
        from app.graph.skills.base_skill import _inject_write_input_recovery

        committed = {}
        _flag = dict(self._FLAG)

        class _Store:
            async def load(self, sid):
                return {"last_write_input_error": _flag}

            async def commit(self, sid, full):
                committed.update(full)

        with patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()):
            out = _asyncio.run(_inject_write_input_recovery(
                "BASE", {"session_id": "sess_001"}, "123456"))
        assert out == "BASE", "顾客已给验证码 → 不再注入索要指令"
        assert not committed.get("last_write_input_error"), "且必须顺手清账"


class TestOrderFlowIntentHandoffGuard:
    """顾客**明确在下单**且流程已启动时，无信号转人工 = 放弃流程（issue #3421，验收 C-A1 实证）。

    实证（run 34763744203 验收剧本 C-A1）：顾客 9 轮里反复「确认下单」，
    agent 却以 `human_handoff({"reason": "客户请求协助下单（智能客服无下单权限）"})` 收场，
    全程未调 `order_create`（L1 违规 3 条）。当时的守卫漏在两处：

      ① `CAPABILITY_DENIAL_PATTERNS` 只有「无法下单/无法代为提交」这类**动宾**措辞，
         不含「**无下单权限**」这类**权限**措辞（C-A1 的原话正是后者）；
      ② 兜底要求「有在办卡片（或 pending skill）」才拦，而那一刻卡片已被顾客点掉
         → 判为"无在办"直接放行 —— 流程被放弃却没人拦。

    补法：顾客这一轮在推进下单（下单/确认/数量/购买…）且流程**已有真实进展**
    （`grounded_product_detail`，即真的查过商品）时，无信号转人工一律拦。
    没有进展时不拦（保守）：顾客只是随口说「下单」而 agent 没查过商品，未必是在办流程。
    """

    def _run(self, last_user_msg: str, *, grounded: bool, with_card: bool = False,
             skill: str = "customer_order",
             reason: str = "顾客需协助下单"):
        import asyncio

        sent_tools = []

        async def fake_execute(tool, args, ctx, state):
            sent_tools.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        history = [HumanMessage(content="我想买遮光窗帘，米白 3 米")]
        if with_card:
            history.append(ToolMessage(
                content=json.dumps({"success": True,
                                    "data": {"component": "confirm", "title": "请确认订单信息",
                                             "confirmValue": "确认：商品=遮光窗帘"}}),
                tool_call_id="c0", name="interact"))
        history.append(HumanMessage(content=last_user_msg))

        store = MagicMock()
        store.load = AsyncMock(return_value=(
            {"grounded_product_detail": {"product_id": "prod_eval_blackout"}} if grounded else {}))

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            from app.tools.human_handoff import HumanHandoffTool
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                HumanHandoffTool() if n == "human_handoff" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=AIMessage)
            call.content = ""
            call.tool_calls = [{"name": "human_handoff",
                                "args": {"reason": reason}, "id": "h1"}]
            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            result = asyncio.run(execute_skill(
                state=_make_state(messages=history),
                skill_name=skill,
                tool_names=["human_handoff"], system_prompt="你是小布",
            ))
        return result, sent_tools

    def test_blocks_when_customer_is_ordering_and_product_grounded(self):
        """C-A1 形态：顾客「确认下单」+ 已查过商品 + 无在办卡 → 必须拦。

        ⚠️ 这里刻意用**中性理由**（"顾客需协助下单"，不含能力否定的措辞）：
        若用 C-A1 原话（含「无下单权限」），会先被**能力误宣**规则拦下，
        这条规则（意图 × 流程进展）就永远不被覆盖 —— 测试要打在它自己的判据上。
        """
        result, sent = self._run("确认下单", grounded=True)
        assert "handoff_blocked_inflight" in str(result), (
            "顾客在下单、商品也查过了，却允许无信号转人工 —— 流程被放弃（C-A1 实证）"
        )
        assert "human_handoff" not in sent, "被拦截时不得真正执行转人工"

    def test_ca1_permission_denial_reason_blocked_even_when_not_grounded(self):
        """C-A1 原话（含「无下单权限」）→ 即使没有流程进展，也按**能力误宣**拦下。

        两条规则互补：措辞类由能力误宣规则兜（不依赖流程状态），
        中性理由则靠"意图 × 流程进展"兜。缺任何一条 C-A1 都会漏。"""
        result, sent = self._run("确认下单", grounded=False,
                                 reason="客户请求协助下单（智能客服无下单权限）")
        assert "handoff_blocked_capability_denial" in str(result), (
            "C-A1 原话未被能力误宣规则拦下 —— 「无下单权限」措辞漏了"
        )
        assert "human_handoff" not in sent

    def test_blocks_without_pending_card_only_when_grounded(self):
        """没有在办卡、但顾客在下单且商品已查 → 拦；没查过商品 → 放行（保守，避免误伤）。"""
        blocked, _ = self._run("确认下单", grounded=True)
        allowed, _ = self._run("确认下单", grounded=False)
        assert "handoff_blocked_inflight" in str(blocked)
        assert "handoff_blocked_inflight" not in str(allowed), (
            "流程没有真实进展时不应拦（顾客随口一句「下单」不等于在办流程）"
        )

    def test_explicit_human_request_still_allowed(self):
        """顾客明确要人工（CH-008/013/015 依赖）→ 必须放行，即使正在下单。

        ⚠️ 消息里**必须同时含下单措辞**（"别下单了"）—— 否则 `_has_ordering_intent` 直接为假，
        这条测试就绕过了新分支，"有没有检查显式诉求"根本没被覆盖
        （变异实测 M250：去掉信号检查时该测试仍绿 → 断言是假的）。
        """
        result, sent = self._run("别下单了，我要转人工", grounded=True)
        assert "handoff_blocked_inflight" not in str(result), (
            "顾客显式要求人工却被拦 —— 真实诉求被堵死"
        )

    def test_other_skill_not_affected(self):
        """守卫只作用于 C 端办单/售后 skill：其它 skill 的转人工不受影响。"""
        result, _ = self._run("确认下单", grounded=True, skill="customer_knowledge")
        assert "handoff_blocked_inflight" not in str(result), (
            "非办单 skill 被误拦 —— 守卫作用域过宽"
        )


class TestCapabilityDenialPermissionPhrasing:
    """「无下单权限」这类**权限**措辞也是能力误宣（issue #3421，C-A1 原话）。"""

    def test_permission_phrasing_detected(self):
        for why in ["客户请求协助下单（智能客服无下单权限）",
                    "小布没有下单权限",
                    "无权限下单，需要人工协助",
                    "顾客需协助下单（智能客服无法帮您完成订单）"]:
            assert _capability_denial_reason({"reason": why}), f"未识别权限类误宣: {why!r}"

    def test_legit_reasons_still_not_detected(self):
        """不能因为加了措辞就把正常业务理由误判（回归 #3389 的边界）。"""
        for why in ["商品缺货不能创建订单", "顾客要求人工核对加工费",
                    "订单信息有误，需要人工核实收货地址", "顾客明确要求转人工"]:
            assert not _capability_denial_reason({"reason": why}), f"误报: {why!r}"


class TestCapabilityDenialTextHit:
    """回复文本里的能力误宣识别（issue #3443，C-A1 transcript 实证）。

    判据与评测侧 `_false_inability_hit` 同源：「agent 主语 + 否定动词」与「下单动作词」
    必须在**同一句**且距离很近 —— 否则正常开场白（"我是小布，您的专属咨询客服"）会被误判。
    """

    def test_ca1_phrasings_detected(self):
        """C-A1 三轮的原话（run 34773014637 transcript）。"""
        for t in ["亲，小布这边是咨询客服，没办法直接帮您提交订单哦，不过下单很简单，我教您~",
                  "我是咨询客服，没有权限帮您直接提交订单哦，下单还是需要您在小程序里操作完成",
                  "小布这边确实没办法直接帮您提交订单，这是为了保护您的订单和支付安全哦。"]:
            assert capability_denial_text_hit(t), f"未识别: {t!r}"

    def test_self_intro_not_flagged(self):
        assert capability_denial_text_hit("亲，我是小布，您的专属咨询客服～") == ""

    def test_success_phrasing_not_flagged(self):
        for t in ["已经帮您提交订单啦，订单号 20260914691810001",
                  "好的，我这就帮您下单", "订单已创建，请您核对"]:
            assert capability_denial_text_hit(t) == "", f"误报: {t!r}"

    def test_unrelated_inability_not_flagged(self):
        """没有下单动作词的否定不算（如"这个我没法确认"）—— 避免把正常求助判红。"""
        assert capability_denial_text_hit("这个我没法确认，麻烦您再说明一下") == ""

    def test_cross_sentence_not_flagged(self):
        """跨句不算：否定在上一句、动作词在下一句 → 不判定（窗口限制）。"""
        t = "小布这边没法查到这个信息。我帮您下单吧"
        assert capability_denial_text_hit(t) == ""


class TestTextDenialCorrectiveRetry:
    """文本级能力误宣 → 带纠正提示**重答一次**（issue #3443）。

    为什么必须动运行时：`order_create` 就在手上，agent 却说"没有权限帮您提交订单"，
    还发一张「转人工协助下单」的卡把顾客推向人工（C-A1 run 34773014637 实证：
    顾客亲手选了人工、整场未下单）。#3421 修的是**工具参数**级、本条是**回复文本**级。
    """

    def _run(self, replies, *, skill="customer_order", has_order_tool=True):
        import asyncio

        sent = []

        async def fake_execute(tool, args, ctx, state):
            sent.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        def _msg(content):
            m = MagicMock(spec=AIMessage)
            m.content = content
            m.tool_calls = []
            return m

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (object() if (n == "order_create" and has_order_tool) else None)
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[_msg(c) for c in replies])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
            out = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="确认下单")]),
                skill_name=skill, tool_names=["order_create"], system_prompt="你是小布",
            ))
        return out, llm, sent

    def test_denial_text_triggers_one_corrective_retry(self):
        denial = "亲，小布这边是咨询客服，没办法直接帮您提交订单哦~"
        ok = "好嘞，这就帮您提交订单，请核对下面的订单信息～"
        out, llm, _ = self._run([denial, ok])
        assert out["final_answer"] == ok, f"能力误宣文本被原样发出：{out['final_answer']!r}"
        assert llm.ainvoke.await_count == 2, "没有发生纠正重答"
        # 纠正提示必须真的注入了（否则模型无从改口）
        second_call_msgs = llm.ainvoke.await_args_list[1].args[0]
        blob = " ".join(str(getattr(m, "content", "")) for m in second_call_msgs)
        assert "你可以真实下单" in blob or "order_create" in blob, "纠正提示未注入"

    def test_only_one_retry_even_if_model_keeps_denying(self):
        """只纠正一次：模型死不改口时按原样发出（绝不无限重试烧轮次）。"""
        denial = "小布这边没办法直接帮您提交订单哦"
        out, llm, _ = self._run([denial, denial, denial])
        assert llm.ainvoke.await_count == 2, f"重试次数不为 1：{llm.ainvoke.await_count}"
        assert "没办法直接帮您提交订单" in out["final_answer"]

    def test_other_skill_untouched(self):
        """非办单 skill 说"下不了单"可能属实 → 不拦、不重答。"""
        denial = "这边没办法直接帮您提交订单哦"
        out, llm, _ = self._run([denial], skill="customer_knowledge")
        assert out["final_answer"] == denial
        assert llm.ainvoke.await_count == 1

    def test_skipped_when_order_tool_unavailable(self):
        """没有 order_create 时"我下不了单"是事实，不能拦（避免堵死正确行为）。"""
        denial = "小布这边没办法直接帮您提交订单哦"
        out, llm, _ = self._run([denial], has_order_tool=False)
        assert out["final_answer"] == denial
        assert llm.ainvoke.await_count == 1


class TestConfirmCardSeenSubReason:
    """`confirmation_required` 必须**能区分**两种形态（issue #3445）。

    同样一句 `must_succeed: order_create 共 1 次调用无一成功（R10:confirmation_required）`，
    成因却可能是"模型从没发过确认卡就直接写"或"发过卡但顾客回的是文本" ——
    修法完全不同（补卡 vs 修点卡链路），而 fast 档看不到容器日志，只能靠 error 码自述。
    """

    @staticmethod
    def _card_round(component="confirm", ok=True):
        payload = {"success": ok, "data": {"component": component, "title": "请确认订单信息"}}
        return ToolMessage(content=json.dumps(payload, ensure_ascii=False),
                           tool_call_id="c1", name="interact")

    def test_detects_confirm_card(self):
        assert _confirm_card_seen([HumanMessage(content="确认下单"), self._card_round()]) is True

    def test_other_card_types_do_not_count(self):
        assert _confirm_card_seen([self._card_round("choice")]) is False
        assert _confirm_card_seen([self._card_round("form")]) is False

    def test_failed_card_does_not_count(self):
        """没发出去的卡（success=false）不算"发过确认卡"。"""
        assert _confirm_card_seen([self._card_round(ok=False)]) is False

    def test_non_interact_tool_ignored(self):
        m = ToolMessage(content=json.dumps({"success": True, "data": {"component": "confirm"}}),
                        tool_call_id="x", name="product_detail")
        assert _confirm_card_seen([m]) is False

    def test_empty_and_garbage_are_safe(self):
        assert _confirm_card_seen([]) is False
        assert _confirm_card_seen([ToolMessage(content="not json", tool_call_id="y", name="interact")]) is False


class TestConfirmationGateNoCardRepro:
    """**本地驱动确认门禁**（issue #3445 的测试基建缺口）+ `no_card` 复现。

    上一轮补细分码时发现：既有用例只测到工具层 `_requires_confirmation`，
    **没有任何用例**让写调用真的走到门禁 —— 于是接线只能靠 CI 指纹验证。
    本类把这个 harness 补上（也是 #3445 验收标准第 2 条）。

    配方（踩过才知道）：
      · skill 用 `customer_order`、工具给 `order_create`；
      · 会话状态里要有 `grounded_product_detail`（否则先被**接地门禁**拦成 product_not_grounded）；
      · `last_user_msg` **不能是明确确认**（如「确认」）—— `_requires_confirmation` 对
        明确确认直接返回 False（= 文本确认放行），那就永远走不到确认门禁；
        实测 CI 里触发 `no_card` 的正是"顾客刚给了验证码 123456 而模型直接去写"这种轮次。
    """

    def _run(self, last_user_msg: str, *, with_confirm_card: bool = False):
        import asyncio

        executed = []

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        class _Store:
            async def load(self, sid):
                return {"grounded_product_detail": {"product_id": "prod_eval_blackout"}}

            async def commit(self, sid, full):
                return True

            async def clear(self, sid):
                return True

        history = [HumanMessage(content="我想买遮光窗帘，米白 3 米，要纳米圈打孔加工")]
        if with_confirm_card:
            history.append(ToolMessage(
                content=json.dumps({"success": True,
                                    "data": {"component": "confirm", "title": "请确认订单信息"}},
                                   ensure_ascii=False),
                tool_call_id="c0", name="interact"))
        history.append(HumanMessage(content=last_user_msg))

        call = MagicMock(spec=AIMessage)
        call.content = ""
        call.tool_calls = [{"name": "order_create",
                            "args": {"items": [{"product_name": "遮光窗帘", "quantity": 3,
                                                "unit_price": 168}],
                                     "customer_name": "张三", "customer_phone": "13800138000",
                                     "customer_address": "浙江省杭州市西湖区文三路1号1幢101室"},
                            "id": "t1"}]
        final = MagicMock(spec=AIMessage)
        final.content = "好的"
        final.tool_calls = []

        from app.tools.order_create import OrderCreateTool
        tool = OrderCreateTool()

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: _Store()), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (tool if n == "order_create" else None)
            create_reg.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            get_breaker.return_value = breaker
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
            out = asyncio.run(execute_skill(
                state=_make_state(messages=history),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="你是小布",
            ))
        return out, executed

    def test_no_card_blocked_when_last_msg_is_not_confirmation(self):
        """顾客刚给完验证码、模型直接写单且**从没发过确认卡** → 门禁拦下并给出 no_card 细分。"""
        out, executed = self._run("123456")
        blob = str(out)
        assert "confirmation_required_no_card" in blob, f"门禁未按预期拦下：{blob[:300]}"
        assert "order_create" not in executed, "被拦下的写调用不得真的执行"

    def test_card_shown_yields_card_not_clicked(self):
        """发过确认卡、但这一轮消息不是卡值 → 细分应为 card_not_clicked。"""
        out, executed = self._run("123456", with_confirm_card=True)
        blob = str(out)
        assert "confirmation_required_card_not_clicked" in blob, f"细分不对：{blob[:300]}"
        assert "order_create" not in executed

    def test_explicit_confirmation_still_passes(self):
        """反向守卫：明确确认（文本）时不该被这条门禁拦（`_requires_confirmation` 的既有语义）。"""
        out, executed = self._run("确认")
        assert "confirmation_required" not in str(out), "明确确认被误拦"
