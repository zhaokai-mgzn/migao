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
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from app.graph.skills.order_skill import ORDER_TOOLS, order_node
from app.graph.skills.product_skill import PRODUCT_TOOLS, product_node
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, knowledge_node
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, aftersales_node
from app.graph.skills.general_agent import GENERAL_TOOLS, general_node
from app.graph.skills.base_skill import build_tool_context, execute_skill, _sanitize_messages
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


# ========== _sanitize_messages 测试 ==========

class TestSanitizeMessages:
    """消息清洗：过滤孤立 ToolMessage，保留合法配对"""

    def test_empty_list(self):
        """空列表不报错"""
        assert _sanitize_messages([]) == []

    def test_no_tool_messages_unchanged(self):
        """不含 ToolMessage 时原样返回"""
        msgs = [
            SystemMessage(content="系统提示"),
            HumanMessage(content="你好"),
            AIMessage(content="你好！"),
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 3
        assert result[0].content == "系统提示"
        assert result[1].content == "你好"
        assert result[2].content == "你好！"

    def test_orphaned_tool_message_removed(self):
        """孤立的 ToolMessage（无匹配 AIMessage.tool_calls）被过滤"""
        msgs = [
            SystemMessage(content="系统提示"),
            HumanMessage(content="查订单"),
            ToolMessage(content='{"id": "123"}', tool_call_id="tc_orphan", name="order_query"),
            AIMessage(content="查到了"),
        ]
        result = _sanitize_messages(msgs)
        # ToolMessage 被过滤，其余保留
        assert len(result) == 3
        assert all(type(m).__name__ != "ToolMessage" for m in result)

    def test_paired_tool_message_kept(self):
        """有匹配 AIMessage.tool_calls 的 ToolMessage 被保留"""
        msgs = [
            SystemMessage(content="系统提示"),
            HumanMessage(content="查订单"),
            AIMessage(
                content="",
                tool_calls=[{"name": "order_query", "args": {"order_id": "123"}, "id": "tc_1"}],
            ),
            ToolMessage(content='{"id": "123"}', tool_call_id="tc_1", name="order_query"),
            AIMessage(content="您的订单已找到"),
        ]
        result = _sanitize_messages(msgs)
        # 全部保留
        assert len(result) == 5
        tool_msgs = [m for m in result if type(m).__name__ == "ToolMessage"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "tc_1"

    def test_multiple_tool_calls_mixed(self):
        """混合场景：部分 ToolMessage 有配对，部分孤立"""
        msgs = [
            SystemMessage(content="系统提示"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "order_query", "args": {}, "id": "tc_valid"},
                ],
            ),
            ToolMessage(content='{"ok": true}', tool_call_id="tc_valid", name="order_query"),
            ToolMessage(content='{"orphan": true}', tool_call_id="tc_orphan", name="product_search"),
            AIMessage(content="结果"),
        ]
        result = _sanitize_messages(msgs)
        # tc_valid 保留，tc_orphan 过滤
        tool_msgs = [m for m in result if type(m).__name__ == "ToolMessage"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "tc_valid"
        assert len(result) == 4  # SystemMessage + AIMessage + 1 ToolMessage + AIMessage

    def test_ai_message_list_content_normalized(self):
        """AIMessage.content 为 list 类型时被归一化为 string（DashScope enable_thinking 场景）"""
        msgs = [
            SystemMessage(content="系统提示"),
            HumanMessage(content="查订单"),
            AIMessage(
                content=[
                    {"type": "text", "text": "我来帮您查询"},
                    {"type": "text", "text": "订单信息"},
                ],
                tool_calls=[{"name": "order_query", "args": {}, "id": "tc_1"}],
            ),
            ToolMessage(content='{"ok": true}', tool_call_id="tc_1", name="order_query"),
        ]
        result = _sanitize_messages(msgs)
        # 所有消息保留
        assert len(result) == 4
        # AIMessage 的 list content 被归一化为 string
        ai_msg = result[2]
        assert isinstance(ai_msg, AIMessage)
        assert isinstance(ai_msg.content, str)
        assert "我来帮您查询" in ai_msg.content
        assert "订单信息" in ai_msg.content
        # tool_calls 保留
        assert len(ai_msg.tool_calls) == 1

    def test_ai_message_empty_content_with_tool_calls_preserved(self):
        """AIMessage.content 为空字符串但有 tool_calls 时正常保留"""
        msgs = [
            SystemMessage(content="系统提示"),
            AIMessage(
                content="",
                tool_calls=[{"name": "order_query", "args": {}, "id": "tc_1"}],
            ),
            ToolMessage(content='{"ok": true}', tool_call_id="tc_1", name="order_query"),
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 3
        ai_msg = result[1]
        assert isinstance(ai_msg.content, str)
        assert ai_msg.content == ""
        # tool_calls 保留
        assert len(ai_msg.tool_calls) == 1

    def test_ai_message_thinking_content_stripped(self):
        """AIMessage 中 <think> 标签内容在归一化时被移除"""
        msgs = [
            AIMessage(
                content="<think>内部推理过程</think>这是最终回复",
                tool_calls=[],
            ),
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "这是最终回复"

    def test_ai_message_additional_kwargs_reasoning_stripped(self):
        """AIMessage 的 additional_kwargs 中的 reasoning_content 被移除（防止被序列化回消息）"""
        msgs = [
            AIMessage(
                content="正常回复",
                additional_kwargs={"reasoning_content": "内部推理..."},
            ),
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 1
        ai_msg = result[0]
        assert ai_msg.content == "正常回复"
        # reasoning_content 被移除
        assert "reasoning_content" not in ai_msg.additional_kwargs

    def test_ai_message_list_content_with_non_text_items(self):
        """AIMessage 的 list content 中包含非 text 类型时，只提取 text 部分"""
        msgs = [
            AIMessage(
                content=[
                    {"type": "text", "text": "有效文本"},
                    {"type": "thinking", "thinking": "内部思考"},
                    {"type": "unknown_type", "data": "unknown"},
                ],
            ),
        ]
        result = _sanitize_messages(msgs)
        assert len(result) == 1
        assert result[0].content == "有效文本"
