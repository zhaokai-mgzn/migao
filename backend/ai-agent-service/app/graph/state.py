"""AgentState - LangGraph 图的状态模型定义（会话管理重构 P3：已精简）"""

from typing import TypedDict, Optional, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 图的全局状态，贯穿所有节点。

    P3 精简：移除 graph 内零消费的死字段
    （recent_entities / cached_answer / intent_chain / stage / entities）。
    跨轮状态（pending_interact_skill）由 SessionStateStore 持久化，
    _build_initial_state 负责恢复。
    """

    # 对话消息列表 - 使用 LangGraph 的 add_messages reducer 自动追加
    messages: Annotated[list[BaseMessage], add_messages]

    # Agent 类型
    agent_type: str                  # "mibao" 或 "xiaobu"

    # 用户身份信息
    tenant_id: int
    user_id: int
    user_name: Optional[str]         # 用户昵称（注入到 System Prompt）
    session_id: str
    role: str

    # 意图识别
    intent_result: Optional[dict]    # IntentResult 序列化
    route_decision: Optional[dict]   # RouteDecision 序列化

    # 输出
    final_answer: str                # 最终回答文本
    skill_used: str                  # 使用的 Skill 名称
    suggestions: list[str]           # 后续问题建议

    # 跨轮状态持久化
    pending_interact_skill: str      # 跨轮锁定的 Skill（如 product/order），防止 LLM 分类器误判跳走
