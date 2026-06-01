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

from app.agents.agent_config import get_agent_config, get_all_agent_configs


class AgentRouter:
    """Agent 路由器

    根据用户身份和上下文决定使用哪个 Agent。

    当前路由规则：
    - admin/agent/tenant_admin 等内部角色 → mibao（工作助手）
    - customer 等外部角色 → xiaobu（C 端客服）

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
            channel: 渠道标识，如 "mini_app", "admin_web", "wechat_work"

        Returns:
            str: Agent 名称（如 "mibao", "xiaobu"）
        """
        role = getattr(user_identity, "role", "customer")

        # 优先查找明确匹配角色的 Agent
        all_configs = get_all_agent_configs()

        # 按优先级排序：内部角色优先匹配 mibao，外部角色优先匹配 xiaobu
        # 使用 AgentConfig.allowed_roles 作为唯一数据源（不再硬编码）
        internal_roles: set[str] = set()
        if "mibao" in all_configs:
            internal_roles = set(all_configs["mibao"].allowed_roles)

        if role in internal_roles:
            # 内部角色：优先返回 mibao
            if "mibao" in all_configs:
                return "mibao"
        else:
            # 外部角色：优先返回 xiaobu
            if "xiaobu" in all_configs:
                return "xiaobu"

        # 兜底：返回第一个注册的 Agent
        if all_configs:
            first_agent = next(iter(all_configs))
            logger.warning(
                f"[AgentRouter] No matching agent for role={role}, "
                f"falling back to '{first_agent}'"
            )
            return first_agent

        # 极端兜底
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
