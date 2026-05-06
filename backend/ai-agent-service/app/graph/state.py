"""AgentState - LangGraph 图的状态模型定义"""

from typing import TypedDict, Optional, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 图的全局状态，贯穿所有节点。"""

    # 对话消息列表 - 使用 LangGraph 的 add_messages reducer 自动追加
    messages: Annotated[list[BaseMessage], add_messages]

    # Agent 类型
    agent_type: str                  # "mibao" 或 "xiaobu"

    # 用户身份信息
    tenant_id: int
    user_id: int
    session_id: str
    role: str

    # 意图识别
    intent_result: Optional[dict]    # IntentResult 序列化
    route_decision: Optional[dict]   # RouteDecision 序列化

    # 上下文追踪
    entities: dict                   # 提取的关键实体
    intent_chain: list[str]          # 意图变化序列
    stage: str                       # 对话阶段 (initial/querying/confirming/processing/completed)

    # 缓存
    cached_answer: Optional[str]     # 语义缓存命中的答案

    # 输出
    final_answer: str                # 最终回答文本
    skill_used: str                  # 使用的 Skill 名称
    suggestions: list[str]           # 后续问题建议
