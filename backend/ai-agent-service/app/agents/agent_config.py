"""
Agent 配置定义

AgentConfig 是 Skill-centric 架构中 Agent 的声明式配置。
每个 Agent 是一组 Skill 的组合，通过配置驱动而非代码驱动。

新增 Agent 只需：
1. 创建 AgentConfig 声明文件（如 supply_chain.py）
2. 在 agents/__init__.py 中注册
3. 不需要修改 builder.py / nodes.py / intent_router.py
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Type
from loguru import logger


@dataclass(frozen=True)
class AgentConfig:
    """Agent 声明式配置

    frozen=True 确保配置在注册后不可变。

    Attributes:
        name: Agent 唯一标识，如 "mibao", "xiaobu", "supply_chain"
        display_name: 人类可读名称，如 "米宝", "小布", "链宝"
        persona: Prompt 人格 key，用于从 SkillConfig.system_prompts 中选择 Prompt
        skill_names: 该 Agent 使用的 Skill 名称列表（按优先级排列）
        fallback_skill: 兜底 Skill 名称（处理低置信度和跨领域问题）
        allowed_roles: 允许使用该 Agent 的角色集合
        greeting: 欢迎语文本
        direct_replies: 直接回复模板，如 {"greeting": "...", "farewell": "..."}
                        用于 direct_reply_node 替代硬编码的回复
    """
    name: str
    display_name: str
    persona: str
    skill_names: List[str] = field(default_factory=list)
    fallback_skill: str = "general"
    allowed_roles: Set[str] = field(default_factory=set)
    greeting: str = "您好！有什么可以帮您的吗？"
    direct_replies: Dict[str, str] = field(default_factory=dict)

    def get_direct_reply(self, intent: str) -> Optional[str]:
        """获取指定意图的直接回复文本

        Args:
            intent: 意图类型字符串

        Returns:
            Optional[str]: 回复文本，无直接回复时返回 None
        """
        return self.direct_replies.get(intent)

    def get_all_skill_names(self) -> List[str]:
        """获取所有 Skill 名称（包括 fallback）"""
        all_names = list(self.skill_names)
        if self.fallback_skill and self.fallback_skill not in all_names:
            all_names.append(self.fallback_skill)
        return all_names

    def allows_role(self, role: str) -> bool:
        """检查指定角色是否允许使用该 Agent"""
        if not self.allowed_roles:
            return True  # 空集合表示不限制
        return role in self.allowed_roles


# ────────────── Agent 注册表 ──────────────

_agent_configs: Dict[str, AgentConfig] = {}


def register_agent(config: AgentConfig) -> None:
    """注册 Agent 配置

    Args:
        config: AgentConfig 实例
    """
    if config.name in _agent_configs:
        logger.warning(
            f"[AgentConfig] Agent '{config.name}' already registered, overwriting"
        )
    _agent_configs[config.name] = config
    logger.info(
        f"[AgentConfig] Registered: {config.name} ({config.display_name}) | "
        f"skills={config.skill_names} fallback={config.fallback_skill} "
        f"roles={len(config.allowed_roles)}"
    )


def get_agent_config(name: str) -> AgentConfig:
    """获取 Agent 配置

    Args:
        name: Agent 名称

    Returns:
        AgentConfig: 配置实例

    Raises:
        KeyError: Agent 未注册
    """
    config = _agent_configs.get(name)
    if config is None:
        available = ", ".join(sorted(_agent_configs.keys())) or "(empty)"
        raise KeyError(
            f"Agent '{name}' not found. Available: {available}"
        )
    return config


def get_all_agent_configs() -> Dict[str, AgentConfig]:
    """获取所有已注册的 Agent 配置"""
    return dict(_agent_configs)


def find_agent_for_role(role: str, channel: str = "") -> Optional[str]:
    """根据用户角色和渠道查找合适的 Agent

    Args:
        role: 用户角色
        channel: 渠道标识（预留扩展）

    Returns:
        Optional[str]: Agent 名称，无匹配时返回 None
    """
    for name, config in _agent_configs.items():
        if config.allows_role(role):
            return name
    return None


def reset_agent_configs():
    """重置所有 Agent 配置（用于测试）

    同时清除 Agent 意图缓存，确保测试间隔离。
    """
    global _agent_configs
    _agent_configs = {}

    # 同步清除 nodes.py 中的意图缓存
    try:
        from app.graph.nodes import reset_agent_intents_cache
        reset_agent_intents_cache()
    except (ImportError, AttributeError):
        pass
