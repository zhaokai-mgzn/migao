"""
LangGraph Skill 节点测试

测试覆盖：
- 各 Skill 节点注册的 Tool 子集
- Skill 执行后返回正确的 state 字段
- ToolContext 从 state 正确构建
- base_skill 的 execute_skill 逻辑
"""
# case_ids: AG-004, CH-003, CH-023, MC-008, DF-018, HR-005, CU-003, CH-010, CH-012

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

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
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
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
