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

        # 兜底分流（P1-C 修复，RBAC 走查）：
        # - C 端角色（customer/agent）→ 最小权限 xiaobu（安全兜底不变）
        # - 商户员工（admin-api 签发的后台 JWT，含「角色管理」自定义角色码，
        #   无法在 allowed_roles 白名单穷举）→ mibao；米宝工具级权限仍由
        #   permissions claim 强控（required_permissions），自定义角色无权限码
        #   自然被工具拒绝，不会越权暴露管理能力。
        all_configs = get_all_agent_configs()
        role_l = (role or "").lower()
        if role_l in ("customer", "agent"):
            safe_fallback = all_configs.get("xiaobu") or all_configs.get("customer_general")
            if safe_fallback:
                logger.warning(
                    f"[AgentRouter] C-end role={role} no exact match, "
                    f"falling back to least-privileged agent '{safe_fallback.name}'"
                )
                return safe_fallback.name
        merchant_fallback = all_configs.get("mibao")
        if merchant_fallback:
            logger.warning(
                f"[AgentRouter] Merchant-staff role={role} not in any agent's "
                f"allowed_roles (custom role), routing to '{merchant_fallback.name}'"
            )
            return merchant_fallback.name

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
