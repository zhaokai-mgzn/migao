"""
Agent 声明注册入口

导入所有 Agent 配置文件并注册到全局 AgentConfig 注册表。
新增 Agent 只需在此文件中添加对应的 import 和 register_agent 调用。
"""

from app.agents.agent_config import register_agent
from app.agents.agents.mibao import MIBAO_CONFIG
from app.agents.agents.xiaobu import XIAOBU_CONFIG


def register_all_agents():
    """注册所有内置 Agent"""
    register_agent(MIBAO_CONFIG)
    register_agent(XIAOBU_CONFIG)


# 模块导入时自动注册
register_all_agents()
