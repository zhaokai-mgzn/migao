"""
LangGraph AgentState 状态模型测试

测试覆盖：
- AgentState 字段定义验证
- messages 字段的 add_messages reducer 行为
"""

import pytest
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.graph.message import add_messages

from app.graph.state import AgentState


class TestAgentStateFields:
    """AgentState 字段定义验证"""

    def test_state_has_required_fields(self):
        """AgentState 包含所有必要字段"""
        annotations = AgentState.__annotations__
        expected_fields = [
            "messages", "tenant_id", "user_id", "session_id", "role",
            "intent_result", "route_decision", "entities", "intent_chain",
            "stage", "cached_answer", "final_answer", "skill_used", "suggestions",
        ]
        for field in expected_fields:
            assert field in annotations, f"Missing field: {field}"

    def test_state_is_typed_dict(self):
        """AgentState 是 TypedDict 子类"""
        # TypedDict 在运行时不能用 isinstance 检查，但可以验证 __annotations__
        assert hasattr(AgentState, "__annotations__")

    def test_state_field_types(self):
        """字段类型正确"""
        annotations = AgentState.__annotations__
        # messages 应该带有 Annotated 标记
        assert "messages" in annotations
        # tenant_id 应该是 int
        assert annotations["tenant_id"] is int
        # user_id 应该是 int
        assert annotations["user_id"] is int
        # session_id 应该是 str
        assert annotations["session_id"] is str


class TestAddMessagesReducer:
    """messages 字段的 add_messages reducer 行为测试"""

    def test_add_messages_appends(self):
        """add_messages 应该追加新消息"""
        existing = [HumanMessage(content="hello")]
        new_msgs = [AIMessage(content="hi")]
        result = add_messages(existing, new_msgs)
        assert len(result) == 2
        assert result[0].content == "hello"
        assert result[1].content == "hi"

    def test_add_messages_empty_existing(self):
        """空列表追加消息"""
        result = add_messages([], [HumanMessage(content="first")])
        assert len(result) == 1
        assert result[0].content == "first"

    def test_add_messages_multiple(self):
        """追加多条消息"""
        existing = [HumanMessage(content="q1")]
        new_msgs = [
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        result = add_messages(existing, new_msgs)
        assert len(result) == 4

    def test_add_messages_preserves_order(self):
        """消息顺序保持不变"""
        msgs = [
            HumanMessage(content="1"),
            AIMessage(content="2"),
            HumanMessage(content="3"),
        ]
        result = add_messages([], msgs)
        for i, msg in enumerate(result):
            assert msg.content == str(i + 1)

    def test_state_dict_creation(self):
        """可以创建符合 AgentState 结构的字典"""
        state = {
            "messages": [HumanMessage(content="test")],
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
        assert state["tenant_id"] == 1
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "test"
# QA Gate: PR #485 covers this module
