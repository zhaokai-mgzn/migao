"""
AI 智能客服系统 - 双 Agent 架构

基于 LangGraph StateGraph 实现的智能 Agent，支持两种身份：
- 小布（CustomerServiceAgent）：C 端客服，面向消费者
- 米宝（WorkAssistantAgent）：B 端工作助手，面向商家/管理员

公共逻辑提取到 BaseAgent 基类：
- LangGraph StateGraph 驱动的对话流程（缓存→路由→Skill→建议）
- 流式输出（SSE，通过 astream_events v2）
- 对话历史管理（Memory）
- 多租户上下文

使用阿里云百炼（DashScope）的 OpenAI 兼容接口作为 LLM 后端
"""

from typing import AsyncGenerator, Optional, List, Dict, Any, Union
from dataclasses import dataclass
import json
import traceback

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from loguru import logger


from app.tools import (
    ToolContext,
    ToolRegistry,
    create_default_registry,
    set_tool_context,
)


@dataclass
class AgentResponse:
    """Agent 响应数据类"""
    content: str
    type: str = "text"  # text / tool_call / tool_result / suggestions / error
    tool_calls: Optional[List[Dict]] = None
    metadata: Optional[Dict[str, Any]] = None


def _extract_msg_content(msg) -> str:
    """从 AIMessage 中提取有效文本内容（去除 think 标签）

    用于提取 LLM 在 tool_calls 之前生成的文本，确保不丢失展示给用户的文本。
    """
    import re
    content = msg.content or ""
    if isinstance(content, list):
        text_parts = [
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        content = "".join(text_parts)
    # 移除 <think>...</think> 块
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    return cleaned


@dataclass
class AgentContext:
    """
    Agent 执行上下文

    包含用户身份、租户信息、会话信息等
    """
    user_id: str
    tenant_id: int
    session_id: str
    role: str = "customer"
    identity_type: str = "wechat_mini"
    user_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "role": self.role,
            "identity_type": self.identity_type,
            "user_name": self.user_name,
        }
    
    def to_tool_context(self) -> ToolContext:
        """转换为 ToolContext"""
        return ToolContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            role=self.role,
        )


class BaseAgent:
    """
    Agent 基类（配置驱动版）

    从 AgentConfig 获取所有差异化配置，无需子类。
    公共逻辑：图构建、流式对话、非流式对话等。
    """

    # 不需要流式输出的辅助节点
    _IGNORED_STREAM_NODES = {"suggestions"}

    def __init__(
        self,
        agent_type: str = "xiaobu",
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """初始化 Agent

        Args:
            agent_type: Agent 类型标识，如 "mibao", "xiaobu"
            tool_registry: Tool 注册器（保留兼容性）
        """
        from app.graph.builder import build_agent_graph
        from app.agents.agent_config import get_agent_config

        self._agent_type = agent_type
        self._agent_config = get_agent_config(agent_type)
        self.graph = build_agent_graph(agent_type)

        # 保留 tool_registry 引用（向后兼容）
        if tool_registry is None:
            self.tool_registry = create_default_registry()
        else:
            self.tool_registry = tool_registry
    
    def _convert_history(self, chat_history: Optional[List[Dict[str, Any]]]) -> list:
        """转换对话历史格式为 LangChain 消息（支持多模态）"""
        history = []
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                content_type = msg.get("content_type", "text")
                images = msg.get("images")
                
                if role == "user":
                    # 多模态消息：构建 content 列表
                    if content_type == "mixed" and images:
                        multimodal_content: List[Dict[str, Any]] = [
                            {"type": "text", "text": content}
                        ]
                        for img_url in images:
                            multimodal_content.append({
                                "type": "image_url",
                                "image_url": {"url": img_url}
                            })
                        history.append(HumanMessage(content=multimodal_content))
                    else:
                        history.append(HumanMessage(content=content))
                elif role == "assistant":
                    history.append(AIMessage(content=content))
        return history
    
    async def _build_initial_state(
        self,
        messages: list,
        context: AgentContext,
    ) -> dict:
        """构建 LangGraph 图的初始状态"""
        # 从 session memory 加载路由信息（跨 graph 调用持久化）
        pending_skill = ""
        try:
            import json
            from app.memory.session_memory import SessionMemory
            mem = SessionMemory()
            pending_skill = await mem.get_pending_skill(context.session_id) or ""
            # P&E Plan 存在时，用 plan 的 skill 覆盖路由，防止意图分类器跳 skill
            if not pending_skill:
                plan_raw = await mem.get_plan_state(context.session_id)
                if plan_raw:
                    plan = json.loads(plan_raw)
                    plan_skill = plan.get("skill_name", "")
                    if plan_skill:
                        pending_skill = plan_skill
        except Exception:
            pass

        return {
            "messages": messages,
            "agent_type": self._agent_type,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "user_name": getattr(context, "user_name", None),
            "session_id": context.session_id,
            "role": context.role,
            "intent_result": None,
            "route_decision": None,
            "entities": {},
            "intent_chain": [],
            "stage": "initial",
            "cached_answer": None,
            "final_answer": "",
            "skill_used": "",
            "suggestions": [],
            "pending_interact_skill": pending_skill,
        }
    
    async def achat(
        self,
        message: Union[str, List[Dict[str, Any]]],
        context: AgentContext,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentResponse:
        """
        非流式对话
        
        Args:
            message: 用户消息（字符串或多模态内容列表）
            context: Agent 执行上下文
            chat_history: 对话历史（可选）
        
        Returns:
            AgentResponse: Agent 响应
        """
        try:
            messages = self._convert_history(chat_history)
            messages.append(HumanMessage(content=message))
            
            set_tool_context(context.to_tool_context())
            
            initial_state = await self._build_initial_state(messages, context)
            result = await self.graph.ainvoke(initial_state)
            
            return AgentResponse(
                content=result.get("final_answer", ""),
                type="text",
            )
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            return AgentResponse(
                content="抱歉，我遇到了一些问题，请稍后重试或联系人工客服。",
                type="error",
                metadata={"error": str(e)},
            )
    
    async def astream_chat(
        self,
        message: Union[str, List[Dict[str, Any]]],
        context: AgentContext,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[AgentResponse, None]:
        """
        流式对话 — 使用 LangGraph graph.astream(stream_mode="updates")
        
        通过 graph.astream 获取每个节点的状态更新，可靠地提取：
        - Skill 节点的 final_answer → AgentResponse(type="text")
        - Skill 节点的 messages 中的 ToolMessage → AgentResponse(type="tool_result")
        - suggestions 节点的 suggestions → AgentResponse(type="suggestions")
        - direct_reply / cache 节点的 final_answer → AgentResponse(type="text")
        
        Args:
            message: 用户消息（字符串或多模态内容列表）
            context: Agent 执行上下文
            chat_history: 对话历史（可选）
        
        Yields:
            AgentResponse: 流式响应片段
        """
        try:
            # 1. 构建消息列表
            messages = self._convert_history(chat_history)
            messages.append(HumanMessage(content=message))
            
            # 2. 设置 Tool 上下文（通过 contextvars 传递给各 Skill 的 Tool 执行）
            set_tool_context(context.to_tool_context())
            
            # 3. 构建初始 state
            initial_state = await self._build_initial_state(messages, context)
            
            logger.info(
                f"[astream_chat] Starting graph | agent={self._agent_type} "
                f"tenant={context.tenant_id} "
                f"user={context.user_id} session={context.session_id} "
                f"history_count={len(chat_history) if chat_history else 0}"
            )
            
            # 4. 状态追踪
            tool_results_queue: List[tuple] = []  # (tool_name, result_dict)
            suggestions: List[str] = []
            text_streamed = False
            tool_calls_detected: List[Dict[str, Any]] = []
            
            # 5. 使用 graph.astream(stream_mode="updates") 获取节点级输出
            # 每次迭代 yield 一个 dict: {node_name: state_update_dict}
            async for node_output in self.graph.astream(
                initial_state, stream_mode="updates"
            ):
                # node_output 格式: {"node_name": {state_update_dict}}
                for node_name, output in node_output.items():
                    if not isinstance(output, dict):
                        continue
                    
                    logger.debug(
                        f"[astream_chat] Node '{node_name}' completed | "
                        f"keys={list(output.keys())}"
                    )
                    
                    # — 提取 ToolMessage（来自 Skill 节点的 execute_skill 返回）
                    node_msgs = output.get("messages")
                    if isinstance(node_msgs, list):
                        for msg in node_msgs:
                            # 检测 AIMessage 中的 tool_calls
                            if isinstance(msg, AIMessage) and msg.tool_calls:
                                # 先流式输出 LLM 在 tool_calls 之前的文本内容（如有）
                                # 修复 text_streamed=False 问题：Qwen 模型可在同一消息中先输出文本再调用工具
                                text_before_tools = _extract_msg_content(msg)
                                if text_before_tools and not text_streamed:
                                    logger.info(
                                        f"[astream_chat] Emitting text before tool_calls | "
                                        f"len={len(text_before_tools)}"
                                    )
                                    yield AgentResponse(
                                        type="text", content=text_before_tools
                                    )
                                    text_streamed = True
                                for tc in msg.tool_calls:
                                    tool_calls_detected.append({
                                        "tool": tc["name"],
                                        "tool_input": tc["args"],
                                    })
                                    yield AgentResponse(
                                        type="tool_call",
                                        content="",
                                        tool_calls=[{
                                            "tool": tc["name"],
                                            "tool_input": tc["args"],
                                        }],
                                    )
                            # 提取 ToolMessage 结果
                            elif isinstance(msg, ToolMessage):
                                tool_name = getattr(msg, "name", None) or "unknown"
                                try:
                                    result_dict = (
                                        json.loads(msg.content)
                                        if isinstance(msg.content, str)
                                        else {}
                                    )
                                except (json.JSONDecodeError, TypeError):
                                    result_dict = {"data": str(msg.content)}
                                tool_results_queue.append((tool_name, result_dict))
                    
                    # — 文本回复（final_answer 来自 Skill 节点或 direct_reply）
                    final_answer = output.get("final_answer", "")
                    if final_answer and not text_streamed:
                        logger.info(
                            f"[astream_chat] Emitting text from node '{node_name}' | "
                            f"skill_used={output.get('skill_used', '')} len={len(final_answer)}"
                        )
                        yield AgentResponse(
                            type="text", content=final_answer
                        )
                        text_streamed = True
                    
                    # — 提取 suggestions
                    sugs = output.get("suggestions")
                    if isinstance(sugs, list) and sugs:
                        suggestions = sugs
            
            # 6. 图执行完毕：发送积压的 tool_result 事件
            for tool_name, result_dict in tool_results_queue:
                yield AgentResponse(
                    type="tool_result",
                    content="",
                    tool_calls=[{
                        "tool": tool_name,
                        "result": result_dict,
                    }],
                )
            
            # 7. 发送 suggestions 事件
            if suggestions:
                yield AgentResponse(
                    type="suggestions",
                    content="",
                    metadata={"suggestions": suggestions},
                )
            
            logger.info(
                f"[astream_chat] Completed | agent={self._agent_type} "
                f"tenant={context.tenant_id} "
                f"session={context.session_id} "
                f"tools={len(tool_calls_detected)} suggestions={len(suggestions)} "
                f"text_streamed={text_streamed}"
            )
            
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                f"[astream_chat] Error | agent={self._agent_type} "
                f"tenant={context.tenant_id} "
                f"user={context.user_id} session={context.session_id} "
                f"error={type(e).__name__}: {e}\n"
                f"traceback={tb[:800]}"
            )
            yield AgentResponse(
                content=f"抱歉，遇到问题: {type(e).__name__}: {str(e)}",
                type="error",
                metadata={"error": str(e), "traceback": tb[:500]},
            )
    
    async def get_greeting(self, context: AgentContext) -> str:
        """获取欢迎语（优先从 direct_replies 获取，避免配置重复）"""
        # 优先使用 direct_replies["greeting"]，与 direct_reply_node 共用同一文本
        greeting = self._agent_config.get_direct_reply("greeting")
        return greeting or self._agent_config.greeting


# 全局 Agent 实例（懒加载，按 agent_type 缓存）
_agent_instances: Dict[str, BaseAgent] = {}


def get_agent(
    tool_registry: Optional[ToolRegistry] = None,
    agent_type: str = "xiaobu",
) -> BaseAgent:
    """
    获取全局 Agent 实例（配置驱动单例）

    从 AgentConfig 注册表中获取 Agent 配置，
    统一使用 BaseAgent 构建，无需区分子类。

    Args:
        tool_registry: 可选的 ToolRegistry 实例
        agent_type: Agent 类型，如 "mibao", "xiaobu"

    Returns:
        BaseAgent: Agent 实例
    """
    global _agent_instances
    if agent_type not in _agent_instances:
        _agent_instances[agent_type] = BaseAgent(
            agent_type=agent_type,
            tool_registry=tool_registry,
        )
    return _agent_instances[agent_type]


def reset_agent():
    """重置全局 Agent 实例（用于测试）

    同时清除 Agent 意图缓存，确保测试间隔离。
    """
    global _agent_instances
    _agent_instances = {}

    # 同步清除 nodes.py 中的意图缓存
    try:
        from app.graph.nodes import reset_agent_intents_cache
        reset_agent_intents_cache()
    except (ImportError, AttributeError):
        pass


# ────────────────────── 向后兼容别名 ──────────────────────
# 测试文件可能仍通过旧类名导入，提供别名避免 ImportError

class CustomerServiceAgent(BaseAgent):
    """小布 C 端客服（向后兼容别名，等价于 BaseAgent(agent_type='xiaobu')）"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        super().__init__(agent_type="xiaobu", tool_registry=tool_registry)


class WorkAssistantAgent(BaseAgent):
    """米宝 B 端工作助手（向后兼容别名，等价于 BaseAgent(agent_type='mibao')）"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        super().__init__(agent_type="mibao", tool_registry=tool_registry)
