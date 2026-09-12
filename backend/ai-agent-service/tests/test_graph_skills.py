"""
LangGraph Skill 节点测试

测试覆盖：
- 各 Skill 节点注册的 Tool 子集
- Skill 执行后返回正确的 state 字段
- ToolContext 从 state 正确构建
- base_skill 的 execute_skill 逻辑
"""
# case_ids: AG-004, CH-003, CH-023, MC-008, DF-018, HR-005, CU-003, CH-010, CH-012

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from app.graph.skills.order_skill import ORDER_TOOLS, ORDER_SKILL_CONFIG
from app.graph.skills.product_skill import PRODUCT_TOOLS, PRODUCT_SKILL_CONFIG
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, KNOWLEDGE_SKILL_CONFIG
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, AFTERSALES_SKILL_CONFIG
from app.graph.skills.general_agent import GENERAL_TOOLS, GENERAL_SKILL_CONFIG
from app.graph.skills.base_skill import build_tool_context, execute_skill, _extract_content, get_skill_llm
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
        assert all("confirmed_write_tool" not in c for c in commits), (
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
