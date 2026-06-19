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

from app.graph.skills.order_skill import ORDER_TOOLS, ORDER_SKILL_CONFIG
from app.graph.skills.product_skill import PRODUCT_TOOLS, PRODUCT_SKILL_CONFIG
from app.graph.skills.knowledge_skill import KNOWLEDGE_TOOLS, KNOWLEDGE_SKILL_CONFIG
from app.graph.skills.aftersales_skill import AFTERSALES_TOOLS, AFTERSALES_SKILL_CONFIG
from app.graph.skills.general_agent import GENERAL_TOOLS, GENERAL_SKILL_CONFIG
from app.graph.skills.base_skill import build_tool_context, execute_skill, _extract_content
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
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_text_path_strips_history_image_url(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker,
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
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_text_path_preserves_standalone_image_as_placeholder(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker,
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

        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

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
                if msg.content == "[图片]":
                    found_placeholder = True
        assert found_placeholder, "纯图片历史消息应转为 '[图片]' 占位符"

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_multi_round_text_after_image_all_succeed(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """模拟生产场景：图片→文本→文本→文本，所有跟进消息都不崩溃

        这是 issue #204 regression 的真实场景：
        Turn 1: 图片消息 → Vision 成功
        Turn 2: "价格信息" → BadRequestError (修复前)
        Turn 3: "库存信息" → BadRequestError (修复前)
        Turn 4: "确认" → Circuit breaker OPEN (修复前)

        修复后，Turns 2-4 都应正常执行。
        """
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_get_breaker.return_value = mock_breaker

        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

        # 模拟 3 轮连续调用（Turn 2, 3, 4），每轮 history 中都含有图片
        calls = []
        for round_idx, user_msg in enumerate([
            "2699《花序》23.8元/米",
            "库存情况 200",
            "确认创建",
        ]):
            # 构建越来越长的历史（image → AI → text → AI → text → ...）
            messages_for_this_round = [
                HumanMessage(content=[
                    {"type": "text", "text": "创建一个商品"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/skb.jpg"}},
                ]),
                AIMessage(content="好的，请提供商品价格"),
            ]
            # 添加前几轮的对话
            for prev_msg, prev_reply in calls:
                messages_for_this_round.append(HumanMessage(content=prev_msg))
                messages_for_this_round.append(AIMessage(content=prev_reply))
            messages_for_this_round.append(HumanMessage(content=user_msg))

            captured = []
            async def _capture(messages):
                captured.extend(messages)
                resp = MagicMock(spec=AIMessage)
                resp.content = f"已记录: {user_msg}"
                resp.tool_calls = []
                return resp

            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(side_effect=_capture)
            mock_llm.model_name = "qwen3.6-flash"
            mock_get_llm.return_value = mock_llm

            state = _make_state()
            state["messages"] = [m for m in messages_for_this_round]  # copy

            result = await execute_skill(
                state=state,
                skill_name="product",
                tool_names=[],
                system_prompt="你是商品助手",
            )

            # 每轮都成功返回（没有抛异常）
            assert user_msg in result["final_answer"], (
                f"Round {round_idx + 1} failed: {result.get('final_answer', '')}"
            )

            # 确认传给 LLM 的消息不含 image_url
            for msg in captured:
                if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                    for item in msg.content:
                        if isinstance(item, dict):
                            assert item.get("type") != "image_url", (
                                f"Round {round_idx + 1}: 不应含 image_url"
                            )

            calls.append((user_msg, f"已记录: {user_msg}"))

        # 3 轮全部跑完
        assert len(calls) == 3

    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_pure_text_conversation_unchanged(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker,
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

        mock_tracker = MagicMock()
        mock_entities = MagicMock()
        mock_entities.order_nos = []
        mock_entities.phone_numbers = []
        mock_entities.product_names = []
        mock_entities.product_ids = []
        mock_entities.amounts = []
        mock_tracker.get_entities.return_value = mock_entities
        mock_get_tracker.return_value = mock_tracker

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


class TestExecuteSkillVisionRetry:
    """Vision 分支空响应重试 (Issue #204)

    当 Vision LLM 返回空内容时，应自动重试 1 次（共 2 次调用），
    而非直接触发兜底 "暂时无法生成回复"。
    """

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_vision_empty_first_then_success(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """首次 Vision 调用返回空内容，重试后成功 → 图片分析结果传给文本 LLM + Tool Calling"""
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

        # Vision LLM: 第一次返回空内容，第二次返回图片分析
        empty_response = MagicMock(spec=AIMessage)
        empty_response.content = ""
        empty_response.tool_calls = []

        vision_response = MagicMock(spec=AIMessage)
        vision_response.content = "图片显示这是一款 HOME YUUR 品牌的色卡系列"
        vision_response.tool_calls = []

        # 文本 LLM: 接收图片分析结果后生成最终回复
        text_response = MagicMock(spec=AIMessage)
        text_response.content = "根据图片分析，这是一款 HOME YUUR 色卡系列，请问需要创建商品吗？"
        text_response.tool_calls = []

        mock_vision_llm = MagicMock()
        mock_vision_llm.ainvoke = AsyncMock(side_effect=[empty_response, vision_response])

        mock_text_llm = MagicMock()
        mock_text_llm.ainvoke = AsyncMock(return_value=text_response)

        # get_skill_llm 调用顺序：1) Vision LLM  2) 文本 LLM (enable_thinking=True)
        mock_get_llm.side_effect = [mock_vision_llm, mock_text_llm]

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

        # 文本 LLM 生成最终回复
        assert result["final_answer"] == "根据图片分析，这是一款 HOME YUUR 色卡系列，请问需要创建商品吗？"
        # Vision LLM 调用 2 次，文本 LLM 调用 1 次
        assert mock_vision_llm.ainvoke.call_count == 2
        assert mock_text_llm.ainvoke.call_count == 1

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_vision_empty_both_attempts(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """两次 Vision 调用都返回空内容 → 返回友好提示，不进入 Tool Calling"""
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

        # Vision LLM 完全失败 → 返回友好提示，引导用户用文字描述
        assert "图片分析暂时无法完成" in result["final_answer"]
        # LLM 应被调用 2 次（最大重试次数）
        assert mock_llm.ainvoke.call_count == 2


class TestExecuteSkillVisionToTextFixes:
    """验证 Vision→text 回退路径的三个修复 (Code Review #207 补充测试)"""

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_vision_aimessage_not_in_history(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """修复 #1: Vision LLM 的 AIMessage 不应出现在返回的对话历史中"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # Vision LLM 返回分析
        vision_resp = MagicMock(spec=AIMessage)
        vision_resp.content = "图片显示这是一款2699系列色卡，包含16个色号"
        vision_resp.tool_calls = []

        # 文本 LLM 返回最终回复
        text_resp = MagicMock(spec=AIMessage)
        text_resp.content = "好的，请问需要创建这些商品吗？"
        text_resp.tool_calls = []

        mock_vision_llm = MagicMock()
        mock_vision_llm.ainvoke = AsyncMock(return_value=vision_resp)
        mock_text_llm = MagicMock()
        mock_text_llm.ainvoke = AsyncMock(return_value=text_resp)
        mock_get_llm.side_effect = [mock_vision_llm, mock_text_llm]

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
            state=state, skill_name="product", tool_names=[],
            system_prompt="你是商品助手",
        )

        # 返回的 messages 中不应包含 Vision LLM 的 AIMessage
        returned_messages = result.get("messages", [])
        vision_in_history = any(
            isinstance(m, AIMessage)
            and "2699系列色卡" in (m.content or "")
            for m in returned_messages
        )
        assert not vision_in_history, (
            "Vision LLM AIMessage 不应出现在返回的 messages 中"
        )

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_messages_cleaned_before_text_llm(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """修复 #2: 文本 LLM 收到的 messages 不应含 image_url"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        vision_resp = MagicMock(spec=AIMessage)
        vision_resp.content = "色卡分析结果"
        vision_resp.tool_calls = []

        text_resp = MagicMock(spec=AIMessage)
        text_resp.content = "确认信息"
        text_resp.tool_calls = []

        mock_vision_llm = MagicMock()
        mock_vision_llm.ainvoke = AsyncMock(return_value=vision_resp)
        mock_text_llm = MagicMock()
        mock_text_llm.ainvoke = AsyncMock(return_value=text_resp)
        mock_get_llm.side_effect = [mock_vision_llm, mock_text_llm]

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
        await execute_skill(
            state=state, skill_name="product", tool_names=[],
            system_prompt="你是商品助手",
        )

        # get_skill_llm 第二次调用（文本 LLM）的 messages 参数应不含 image_url
        text_llm_call_args = mock_get_llm.call_args_list[1]
        text_llm_messages = text_llm_call_args[1].get("messages", [])
        for msg in text_llm_messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                has_image = any(
                    isinstance(item, dict) and item.get("type") == "image_url"
                    for item in msg.content
                )
                assert not has_image, (
                    f"文本 LLM 收到的消息不应含 image_url: {msg.content}"
                )

    @patch("app.graph.plan_executor._load_plan", return_value=None)
    @patch("app.graph.plan_executor.should_use_plan_execute", return_value=False)
    @patch("app.graph.skills.base_skill.get_breaker")
    @patch("app.graph.skills.base_skill.get_tracker")
    @patch("app.graph.skills.base_skill.get_skill_llm")
    @patch("app.graph.skills.base_skill.create_skill_registry")
    @patch("app.graph.skills.base_skill.set_tool_context")
    async def test_text_length_recalculated_after_vision(
        self, mock_set_ctx, mock_create_reg, mock_get_llm,
        mock_get_tracker, mock_get_breaker, mock_pe, mock_load_plan,
    ):
        """修复 #3: Vision 成功后 text_length 应重新计算（含 vision_context）"""
        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_create_reg.return_value = mock_registry

        mock_breaker = MagicMock()
        async def _passthrough(fn):
            return await fn()
        mock_breaker.call = _passthrough
        mock_get_breaker.return_value = mock_breaker

        # Vision 返回 50 字符的分析
        vision_resp = MagicMock(spec=AIMessage)
        vision_resp.content = "X" * 50
        vision_resp.tool_calls = []

        text_resp = MagicMock(spec=AIMessage)
        text_resp.content = "OK"
        text_resp.tool_calls = []

        mock_vision_llm = MagicMock()
        mock_vision_llm.ainvoke = AsyncMock(return_value=vision_resp)
        mock_text_llm = MagicMock()
        mock_text_llm.ainvoke = AsyncMock(return_value=text_resp)
        mock_get_llm.side_effect = [mock_vision_llm, mock_text_llm]

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
        await execute_skill(
            state=state, skill_name="product", tool_names=[],
            system_prompt="你是商品助手",
        )

        # 第二次 get_skill_llm 调用的 text_length 应 ≥ vision_context 长度
        text_llm_call_args = mock_get_llm.call_args_list[1]
        reported_text_length = text_llm_call_args[1].get("text_length", 0)
        # vision_context 包含 "图片分析结果" + 50 字符分析 ≈ 100+ 字符
        assert reported_text_length >= 100, (
            f"text_length 应包含 vision_context，实际: {reported_text_length}"
        )
# QA Gate: PR #485 covers this module
