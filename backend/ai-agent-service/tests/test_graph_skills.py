"""
LangGraph Skill 节点测试

测试覆盖：
- 各 Skill 节点注册的 Tool 子集
- Skill 执行后返回正确的 state 字段
- ToolContext 从 state 正确构建
- base_skill 的 execute_skill 逻辑
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.skills.order_skill import ORDER_TOOLS, order_node
from app.graph.skills.product_skill import PRODUCT_TOOLS, product_node
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, knowledge_node
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, aftersales_node
from app.graph.skills.general_agent import GENERAL_TOOLS, general_node
from app.graph.skills.base_skill import build_tool_context, execute_skill
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
        assert "product_search" not in ORDER_TOOLS
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
        """通用 Agent 包含全部非知识库 Tool（knowledge_search/knowledge_manage 已禁用）"""
        expected = {
            "order_query", "order_manage", "logistics_track",
            "product_search", "product_detail", "product_manage",
            "inventory_manage",
            # [RAG 禁用] "knowledge_search", "knowledge_manage",
            "processing_item_query", "customer_manage",
            "employee_manage", "role_manage", "dashboard_stats",
            "after_sales_manage",
            "notification_manage", "settings_manage",
            "session_manage", "quick_reply_manage",
            "category_manage", "processing_item_manage",
        }
        assert set(GENERAL_TOOLS) == expected

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

    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_no_tool_calls(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_tracker
    ):
        """LLM 直接返回文本，无 tool_calls"""
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        # Mock LLM response (no tool_calls)
        mock_response = MagicMock(spec=AIMessage)
        mock_response.content = "这是回复"
        mock_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_get_llm.return_value = mock_llm

        # Mock tracker
        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

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
        assert "entities" in result

    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_execute_skill_with_tool_call(
        self, mock_set_ctx, mock_create_reg, mock_get_llm, mock_get_tracker
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

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = [MagicMock()]
        mock_registry.get_tool.return_value = mock_tool
        mock_create_reg.return_value = mock_registry

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

        # Mock tracker
        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = ["123"]
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

        state = _make_state()
        result = await execute_skill(
            state=state,
            skill_name="order",
            tool_names=["order_query"],
            system_prompt="你是订单助手",
        )

        assert result["final_answer"] == "您的订单已找到"
        assert result["skill_used"] == "order"
        assert result["entities"]["order_nos"] == ["123"]


# ========== Skill 节点调用测试 ==========

class TestSkillNodes:
    """各 Skill 节点正确调用 execute_skill"""

    @patch("app.graph.skills.order_skill.execute_skill")
    async def test_order_node(self, mock_execute):
        """order_node 调用 execute_skill"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "order"}
        state = _make_state()
        result = await order_node(state)
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["skill_name"] == "order"
        assert call_kwargs.kwargs["tool_names"] == ORDER_TOOLS

    @patch("app.graph.skills.product_skill.execute_skill")
    async def test_product_node(self, mock_execute):
        """product_node 调用 execute_skill"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "product"}
        state = _make_state()
        result = await product_node(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "product"
        assert mock_execute.call_args.kwargs["tool_names"] == PRODUCT_TOOLS

    @patch("app.graph.skills.knowledge_skill.execute_skill")
    async def test_knowledge_node(self, mock_execute):
        """knowledge_node 调用 execute_skill"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "knowledge"}
        state = _make_state()
        result = await knowledge_node(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "knowledge"
        assert mock_execute.call_args.kwargs["tool_names"] == KNOWLEDGE_TOOLS

    @patch("app.graph.skills.aftersales_skill.execute_skill")
    async def test_aftersales_node(self, mock_execute):
        """aftersales_node 调用 execute_skill"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "aftersales"}
        state = _make_state()
        result = await aftersales_node(state)
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["skill_name"] == "aftersales"
        assert mock_execute.call_args.kwargs["tool_names"] == AFTERSALES_TOOLS

    @patch("app.graph.skills.general_agent.execute_skill")
    async def test_general_node(self, mock_execute):
        """general_node 调用 execute_skill"""
        mock_execute.return_value = {"final_answer": "ok", "skill_used": "general"}
        state = _make_state()
        result = await general_node(state)
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


class TestExecuteSkillVisionRetry:
    """Vision 分支空响应重试 (Issue #204)

    当 Vision LLM 返回空内容时，应自动重试 1 次（共 2 次调用），
    而非直接触发兜底 "暂时无法生成回复"。
    """

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_vision_empty_first_then_success(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker,
    ):
        """首次 Vision 调用返回空内容，重试后成功返回内容"""
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        # Mock breaker — 直接透传调用（不熔断）
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        # 第一次返回空内容，第二次返回正常内容
        empty_response = MagicMock(spec=AIMessage)
        empty_response.content = ""
        empty_response.tool_calls = []

        good_response = MagicMock(spec=AIMessage)
        good_response.content = "图片显示这是一款 HOME YUUR 品牌的色卡系列"
        good_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[empty_response, good_response])
        mock_get_llm.return_value = mock_llm

        # Mock tracker
        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

        state = _make_multimodal_state()
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        # 重试后应获得正确内容
        assert result["final_answer"] == "图片显示这是一款 HOME YUUR 品牌的色卡系列"
        # LLM 应被调用 2 次（首次空 + 重试成功）
        assert mock_llm.ainvoke.call_count == 2

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_vision_empty_both_attempts(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker,
    ):
        """两次 Vision 调用都返回空内容，最终 final_answer 为空"""
        # Mock registry
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        # Mock breaker
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        # 两次都返回空
        empty_response = MagicMock(spec=AIMessage)
        empty_response.content = ""
        empty_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=empty_response)
        mock_get_llm.return_value = mock_llm

        # Mock tracker
        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

        state = _make_multimodal_state()
        result = await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )

        # 两次都空 → final_answer 为空（由 chat.py 兜底处理）
        assert result["final_answer"] == ""
        # LLM 应被调用 2 次（最大重试次数）
        assert mock_llm.ainvoke.call_count == 2
