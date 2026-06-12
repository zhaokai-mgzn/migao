"""
Agent 路由层

根据用户身份（role）和渠道（channel）决定使用哪个 Agent。
替代 chat.py 中的 if/else 硬判断。

扩展点：
- 未来可根据 tenant 的订阅套餐决定可用 Agent
- 可根据渠道（mini_app / admin_web / wechat_work）路由到不同 Agent
"""

from typing import Optional
from loguru import logger

from app.agents.agent_config import find_agent_for_role, get_all_agent_configs


class AgentRouter:
    """Agent 路由器

    根据用户身份和上下文决定使用哪个 Agent。

    路由规则由 AgentConfig.allowed_roles 驱动（非硬编码）：
    - find_agent_for_role() 遍历所有已注册 Agent 找匹配角色
    - 无匹配时 fallback 到第一个注册的 Agent
    - 未注册任何 Agent 时返回 "xiaobu" 作为极端兜底

    扩展时可添加 channel、tenant 订阅等维度。
    """

    def route(
        self,
        user_identity,
        channel: str = "",
    ) -> str:
        """路由到合适的 Agent

        Args:
            user_identity: 用户身份信息（UserIdentity 对象或类似结构）
            channel: 渠道标识（预留扩展）

        Returns:
            str: Agent 名称（如 "mibao", "xiaobu"）
        """
        role = getattr(user_identity, "role", "customer")

        # 使用声明式角色匹配（AgentConfig.allowed_roles 作为唯一数据源）
        agent_name = find_agent_for_role(role, channel)
        if agent_name:
            logger.debug(
                f"[AgentRouter] Matched agent='{agent_name}' for role='{role}'"
            )
            return agent_name

        # 兜底：优先返回最小权限 Agent（xiaobu），避免误暴露管理后台能力
        all_configs = get_all_agent_configs()
        safe_fallback = all_configs.get("xiaobu") or all_configs.get("customer_general")
        if safe_fallback:
            logger.warning(
                f"[AgentRouter] No matching agent for role={role}, "
                f"falling back to least-privileged agent '{safe_fallback.name}'"
            )
            return safe_fallback.name

        # 极端兜底
        if all_configs:
            first_agent = next(iter(all_configs))
            logger.error(
                f"[AgentRouter] No safe fallback agent, using first agent: '{first_agent}'"
            )
            return first_agent

        logger.error("[AgentRouter] No agents registered at all!")
        return "xiaobu"


# 全局路由器实例
_agent_router: Optional[AgentRouter] = None


def get_agent_router() -> AgentRouter:
    """获取全局 AgentRouter 实例"""
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter()
    return _agent_router
