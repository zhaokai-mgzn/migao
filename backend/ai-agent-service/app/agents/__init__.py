"""
AI 智能客服系统 - Agent 模块

基于 LangChain 实现的 AI Agent 框架

架构决策说明：
================
原计划使用 Hermes Agent（Nous Research 推出的自进化 Agent 框架），
但经调研发现：
1. Hermes Agent 目前主要通过 GitHub 源码安装，非 PyPI 标准包
2. 安装和配置相对复杂，需要额外的环境准备
3. 文档和社区支持尚不完善

因此当前采用 LangChain Agent 作为替代方案：
- LangChain 是成熟的 LLM 应用框架，PyPI 标准包
- 提供完善的 Tool calling、Memory 管理和 Streaming 支持
- 与阿里云百炼（DashScope）集成良好
- 有丰富的文档和社区支持

未来如需迁移到 Hermes Agent，可基于当前 Tool 抽象层进行替换，
因为 Tool 定义和 Agent 接口设计是框架无关的。
================

模块说明：
- customer_service_agent.py: 双 Agent 实现（BaseAgent / CustomerServiceAgent / WorkAssistantAgent）
"""

from app.agents.customer_service_agent import (
    BaseAgent,
    CustomerServiceAgent,
    WorkAssistantAgent,
    AgentContext,
    AgentResponse,
    get_agent,
    reset_agent,
)

__all__ = [
    "BaseAgent",
    "CustomerServiceAgent",
    "WorkAssistantAgent",
    "AgentContext",
    "AgentResponse",
    "get_agent",
    "reset_agent",
]
