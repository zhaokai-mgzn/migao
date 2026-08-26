"""
Tests for app/agents/customer_service_agent.py
Covers: AgentResponse, AgentContext, BaseAgent, get_agent, reset_agent,
         _extract_msg_content, backward compat aliases, and the async
         methods (_build_initial_state / achat / astream_chat).
"""
# case_ids: AG-001, AG-002, AG-003, AG-004, AG-005, AG-006

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.customer_service_agent import (
    AgentResponse,
    AgentContext,
    _extract_msg_content,
    get_agent,
    reset_agent,
    CustomerServiceAgent,
    WorkAssistantAgent,
    BaseAgent,
)
from app.tools import ToolContext


class TestAgentResponse:
    def test_default_values(self):
        resp = AgentResponse(content="hello")
        assert resp.content == "hello"
        assert resp.type == "text"
        assert resp.tool_calls is None
        assert resp.metadata is None

    def test_tool_call_response(self):
        resp = AgentResponse(content="", type="tool_call",
            tool_calls=[{"tool": "search", "tool_input": {"q": "test"}}])
        assert resp.type == "tool_call"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["tool"] == "search"

    def test_error_response_with_metadata(self):
        resp = AgentResponse(content="error", type="error",
            metadata={"error": "ConnectionError"})
        assert resp.type == "error"
        assert resp.metadata["error"] == "ConnectionError"


class TestAgentContext:
    def test_default_values(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1")
        assert ctx.role == "customer"
        assert ctx.identity_type == "wechat_mini"
        assert ctx.user_name is None

    def test_custom_values(self):
        ctx = AgentContext(user_id="u2", tenant_id=200, session_id="s2",
            role="admin", identity_type="web", user_name="TestUser")
        assert ctx.role == "admin"
        assert ctx.identity_type == "web"
        assert ctx.user_name == "TestUser"

    def test_to_dict(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1", user_name="Alice")
        d = ctx.to_dict()
        assert d["user_id"] == "u1"
        assert d["tenant_id"] == 100
        assert d["role"] == "customer"
        assert d["user_name"] == "Alice"
        assert "identity_type" in d

    def test_to_tool_context(self):
        ctx = AgentContext(user_id="u1", tenant_id=100, session_id="s1", role="customer")
        tc = ctx.to_tool_context()
        assert isinstance(tc, ToolContext)
        assert tc.tenant_id == 100
        assert tc.user_id == "u1"


class TestExtractMsgContent:
    def test_plain_text(self):
        msg = MagicMock()
        msg.content = "hello world"
        assert _extract_msg_content(msg) == "hello world"

    def test_strips_think_tags(self):
        msg = MagicMock()
        msg.content = "<think>reasoning</think>actual response"
        assert _extract_msg_content(msg) == "actual response"

    def test_multiline_think_tag(self):
        msg = MagicMock()
        msg.content = "<think>\nline1\nline2\n</think>visible"
        assert _extract_msg_content(msg) == "visible"

    def test_no_think_tag(self):
        msg = MagicMock()
        msg.content = "normal response"
        assert _extract_msg_content(msg) == "normal response"

    def test_multimodal_content_list(self):
        msg = MagicMock()
        msg.content = [
            {"type": "text", "text": "part1"},
            {"type": "image_url", "image_url": {"url": "http://x.com/1.jpg"}},
            {"type": "text", "text": "part2"},
        ]
        assert _extract_msg_content(msg) == "part1part2"

    def test_empty_think_only(self):
        msg = MagicMock()
        msg.content = "<think>reasoning</think>"
        assert _extract_msg_content(msg) == ""


class TestConvertHistory:
    @pytest.fixture
    def agent(self):
        reset_agent()
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            cfg = MagicMock()
            cfg.get_direct_reply = MagicMock(return_value=None)
            cfg.greeting = "test"
            mock_cfg.return_value = cfg
            return BaseAgent(agent_type="xiaobu")

    def test_empty_history(self, agent):
        assert agent._convert_history(None) == []

    def test_empty_list(self, agent):
        assert agent._convert_history([]) == []

    def test_user_message(self, agent):
        from langchain_core.messages import HumanMessage
        result = agent._convert_history([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)
        assert result[0].content == "hello"

    def test_assistant_message(self, agent):
        from langchain_core.messages import AIMessage
        result = agent._convert_history([{"role": "assistant", "content": "hi"}])
        assert len(result) == 1
        assert isinstance(result[0], AIMessage)

    def test_mixed_history(self, agent):
        result = agent._convert_history([
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ])
        assert len(result) == 3

    def test_multimodal_message(self, agent):
        result = agent._convert_history([{
            "role": "user", "content": "img", "content_type": "mixed",
            "images": ["http://x.com/1.jpg"]}])
        assert len(result) == 1
        assert isinstance(result[0].content, list)

    def test_unknown_role_skipped(self, agent):
        assert agent._convert_history([{"role": "system", "content": "x"}]) == []


class TestGetGreeting:
    @pytest.fixture
    def agent(self):
        reset_agent()
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            cfg = MagicMock()
            cfg.get_direct_reply = MagicMock(return_value="Hello from config")
            cfg.greeting = "default greeting"
            mock_cfg.return_value = cfg
            return BaseAgent(agent_type="xiaobu")

    @pytest.mark.asyncio
    async def test_returns_direct_reply_greeting(self, agent):
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        assert await agent.get_greeting(ctx) == "Hello from config"

    @pytest.mark.asyncio
    async def test_falls_back_to_agent_config_greeting(self, agent):
        agent._agent_config.get_direct_reply.return_value = None
        ctx = AgentContext(user_id="u1", tenant_id=1, session_id="s1")
        assert await agent.get_greeting(ctx) == "default greeting"


class TestGetAgent:
    def setup_method(self):
        reset_agent()

    def teardown_method(self):
        reset_agent()

    def test_get_agent_returns_instance(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = get_agent(agent_type="xiaobu")
            assert agent is not None
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "xiaobu"

    def test_same_instance_for_same_type(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            a2 = get_agent(agent_type="xiaobu")
            assert a1 is a2

    def test_different_types_separate(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            a2 = get_agent(agent_type="mibao")
            assert a1 is not a2

    def test_reset_clears_cache(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            a1 = get_agent(agent_type="xiaobu")
            reset_agent()
            a2 = get_agent(agent_type="xiaobu")
            assert a1 is not a2


class TestBackwardCompatAliases:
    def test_customer_service_agent(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = CustomerServiceAgent()
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "xiaobu"

    def test_work_assistant_agent(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = WorkAssistantAgent()
            assert isinstance(agent, BaseAgent)
            assert agent._agent_type == "mibao"


# ── 异步方法覆盖（issue #2429：_build_initial_state / achat / astream_chat）──


def _bare_agent(agent_type="xiaobu"):
    """构造不带真实 graph/config 的 BaseAgent（跳过 __init__，供异步方法单测）。"""
    agent = BaseAgent.__new__(BaseAgent)
    agent._agent_type = agent_type
    return agent


class TestBaseAgentInitRegistry:
    """BaseAgent.__init__ 的 tool_registry 双分支（AG-002）。"""

    def test_init_uses_provided_registry(self):
        custom = MagicMock()
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            agent = BaseAgent(agent_type="xiaobu", tool_registry=custom)
        assert agent.tool_registry is custom

    def test_init_creates_default_registry_when_none(self):
        with patch("app.graph.builder.build_agent_graph") as mock_build, \
             patch("app.agents.agent_config.get_agent_config") as mock_cfg, \
             patch("app.agents.customer_service_agent.create_default_registry") as mock_create:
            mock_build.return_value = MagicMock()
            mock_cfg.return_value = MagicMock(get_direct_reply=lambda x: None, greeting="t")
            mock_create.return_value = MagicMock()
            agent = BaseAgent(agent_type="xiaobu")
        assert agent.tool_registry is mock_create.return_value
        mock_create.assert_called_once()


class TestBuildInitialState:
    """_build_initial_state：plan 优先 / pending_skill 回退 / SessionMemory 异常兜底（AG-003）。"""

    @staticmethod
    def _ctx():
        return AgentContext(
            user_id="u1", tenant_id=1, session_id="s1",
            role="customer", user_name="小布",
        )

    @pytest.mark.asyncio
    async def test_plan_state_has_priority(self):
        agent = _bare_agent()
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value='{"skill_name": "customer_order"}')
            mem.get_pending_skill = AsyncMock()
            state = await agent._build_initial_state([], self._ctx())
        assert state["pending_interact_skill"] == "customer_order"
        mem.get_pending_skill.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_pending_skill(self):
        agent = _bare_agent()
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value=None)
            mem.get_pending_skill = AsyncMock(return_value="aftersales")
            state = await agent._build_initial_state([], self._ctx())
        assert state["pending_interact_skill"] == "aftersales"

    @pytest.mark.asyncio
    async def test_plan_state_empty_skill_falls_back(self):
        agent = _bare_agent()
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value='{"skill_name": ""}')
            mem.get_pending_skill = AsyncMock(return_value="order_query")
            state = await agent._build_initial_state([], self._ctx())
        assert state["pending_interact_skill"] == "order_query"

    @pytest.mark.asyncio
    async def test_session_memory_exception_degrades(self):
        agent = _bare_agent()
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mock_sm.side_effect = RuntimeError("db down")
            state = await agent._build_initial_state([], self._ctx())
        assert state["pending_interact_skill"] == ""

    @pytest.mark.asyncio
    async def test_returns_13_keys(self):
        """P3 精简后 _build_initial_state 返回 13 个键（原 18，死字段已移除）"""
        agent = _bare_agent()
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value=None)
            mem.get_pending_skill = AsyncMock(return_value="")
            state = await agent._build_initial_state(
                [HumanMessage(content="hi")], self._ctx()
            )
        assert len(state) == 13
        assert state["messages"][0].content == "hi"
        assert state["agent_type"] == "xiaobu"
        assert state["tenant_id"] == 1
        assert state["user_id"] == "u1"
        assert state["user_name"] == "小布"
        assert state["session_id"] == "s1"
        assert state["role"] == "customer"
        # 死字段已移除
        assert "entities" not in state
        assert "recent_entities" not in state
        assert "cached_answer" not in state


class TestAchat:
    """achat 非流式：happy path + 异常兜底（AG-004）。"""

    @staticmethod
    def _ctx():
        return AgentContext(user_id="u1", tenant_id=1, session_id="s1")

    def _agent(self, result=None, exc=None):
        agent = _bare_agent()
        agent.graph = MagicMock()
        agent.graph.ainvoke = AsyncMock(side_effect=exc) if exc else AsyncMock(return_value=result or {})
        return agent

    @pytest.mark.asyncio
    async def test_returns_final_answer_as_text(self):
        agent = self._agent({"final_answer": "你好，我是小布"})
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value=None)
            mem.get_pending_skill = AsyncMock(return_value="")
            resp = await agent.achat("你好", self._ctx())
        assert resp.type == "text"
        assert resp.content == "你好，我是小布"
        agent.graph.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_returns_error_fallback(self):
        agent = self._agent(exc=RuntimeError("boom"))
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value=None)
            mem.get_pending_skill = AsyncMock(return_value="")
            resp = await agent.achat("你好", self._ctx())
        assert resp.type == "error"
        assert "稍后重试" in resp.content
        assert resp.metadata["error"] == "boom"


class TestAstreamChat:
    """astream_chat 流式事件序列：tool_call / tool_result / text / suggestions / error（AG-005）。"""

    @staticmethod
    def _ctx():
        return AgentContext(user_id="u1", tenant_id=1, session_id="s1")

    def _agent(self, stream_nodes):
        agent = _bare_agent()
        agent.graph = MagicMock()

        async def _stream(*args, **kwargs):
            for node in stream_nodes:
                yield node

        agent.graph.astream = _stream
        return agent

    async def _collect(self, agent, message="查订单"):
        out = []
        with patch("app.memory.session_memory.SessionMemory") as mock_sm:
            mem = mock_sm.return_value
            mem.get_plan_state = AsyncMock(return_value=None)
            mem.get_pending_skill = AsyncMock(return_value="")
            async for resp in agent.astream_chat(message, self._ctx()):
                out.append(resp)
        return out

    @pytest.mark.asyncio
    async def test_tool_call_with_text_before(self):
        ai = AIMessage(
            content="让我查一下",
            tool_calls=[{"name": "order_query", "args": {"q": "订单"}, "id": "call_1"}],
        )
        agent = self._agent([{"skill": {"messages": [ai]}}])
        out = await self._collect(agent)
        types = [r.type for r in out]
        assert "text" in types
        assert "tool_call" in types
        text = next(r for r in out if r.type == "text")
        assert text.content == "让我查一下"
        tc = next(r for r in out if r.type == "tool_call")
        assert tc.tool_calls[0]["tool"] == "order_query"

    @pytest.mark.asyncio
    async def test_tool_result_json_parsed(self):
        tm = ToolMessage(content='{"data": [1, 2]}', name="order_query", tool_call_id="c1")
        agent = self._agent([{"skill": {"messages": [tm]}}])
        out = await self._collect(agent)
        tr = next(r for r in out if r.type == "tool_result")
        assert tr.tool_calls[0]["tool"] == "order_query"
        assert tr.tool_calls[0]["result"] == {"data": [1, 2]}

    @pytest.mark.asyncio
    async def test_tool_result_degraded_on_bad_json(self):
        tm = ToolMessage(content="not-json{{{", name="order_query", tool_call_id="c1")
        agent = self._agent([{"skill": {"messages": [tm]}}])
        out = await self._collect(agent)
        tr = next(r for r in out if r.type == "tool_result")
        assert tr.tool_calls[0]["result"] == {"data": "not-json{{{"}

    @pytest.mark.asyncio
    async def test_final_answer_yields_text(self):
        agent = self._agent([{"skill": {"final_answer": "这是最终答案"}}])
        out = await self._collect(agent)
        texts = [r for r in out if r.type == "text"]
        assert texts[-1].content == "这是最终答案"

    @pytest.mark.asyncio
    async def test_suggestions_yielded(self):
        agent = self._agent([
            {"skill": {"final_answer": "答案"}},
            {"suggestions": {"suggestions": ["查物流", "查售后"]}},
        ])
        out = await self._collect(agent)
        sug = next(r for r in out if r.type == "suggestions")
        assert sug.metadata["suggestions"] == ["查物流", "查售后"]

    @pytest.mark.asyncio
    async def test_non_dict_node_output_skipped(self):
        agent = self._agent([
            {"skill": "not-a-dict"},
            {"other": {"final_answer": "ok"}},
        ])
        out = await self._collect(agent)
        texts = [r for r in out if r.type == "text"]
        assert texts[-1].content == "ok"

    @pytest.mark.asyncio
    async def test_exception_yields_error(self):
        agent = _bare_agent()
        agent.graph = MagicMock()
        agent.graph.astream = MagicMock(side_effect=RuntimeError("stream boom"))
        out = await self._collect(agent)
        assert out[-1].type == "error"
        assert "RuntimeError" in out[-1].content


class TestResetAgentExcept:
    """reset_agent 清缓存异常被忽略（AG-006）。"""

    def test_reset_ignores_cache_reset_errors(self):
        reset_agent()
        with patch("app.graph.nodes.reset_agent_intents_cache", side_effect=AttributeError("no cache")):
            reset_agent()  # 不应抛异常
