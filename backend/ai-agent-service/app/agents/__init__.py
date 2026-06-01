"""
AI 智能客服系统 - Agent 模块（Skill-centric 架构）

基于 LangChain + LangGraph 的 Agent 框架，采用 Skill-centric 设计：
- Skill = 自包含的能力模块（Tool 集合 + Prompt + 意图路由）
- Agent = Skill 的声明式组合（配置驱动）

新增 Agent 只需：
1. 在 agents/ 目录添加 AgentConfig 声明
2. 在 graph/skills/ 目录添加需要的 SkillConfig
3. 注册后即可使用

模块说明：
- customer_service_agent.py: BaseAgent 实现 + get_agent 工厂
- agent_config.py: AgentConfig 数据类 + 注册表
- agent_router.py: 用户身份 → Agent 类型路由
- agents/: Agent 声明文件（mibao.py, xiaobu.py, ...）
"""

from app.agents.customer_service_agent import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    get_agent,
    reset_agent,
    # 向后兼容别名（测试文件可能仍通过旧类名导入）
    CustomerServiceAgent,
    WorkAssistantAgent,
)
from app.agents.agent_config import (
    AgentConfig,
    register_agent,
    get_agent_config,
    get_all_agent_configs,
)
from app.agents.agent_router import AgentRouter, get_agent_router

# 注册所有内置 Agent（触发 agents/__init__.py 中的注册逻辑）
import app.agents.agents  # noqa: F401

__all__ = [
    # Agent 运行时
    "BaseAgent",
    "AgentContext",
    "AgentResponse",
    "get_agent",
    "reset_agent",
    # 向后兼容别名
    "CustomerServiceAgent",
    "WorkAssistantAgent",
    # Agent 配置
    "AgentConfig",
    "register_agent",
    "get_agent_config",
    "get_all_agent_configs",
    # Agent 路由
    "AgentRouter",
    "get_agent_router",
]
