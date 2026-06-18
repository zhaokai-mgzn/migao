"""
Skill 注册表 + 节点函数工厂

SkillRegistry 管理所有已注册的 SkillConfig，并提供：
- Skill 注册/查询/遍历
- 自动生成 LangGraph 节点函数（消除 13 个 Skill 文件的样板代码）
- 意图→路由 key 聚合查询（供 intent_router 使用）
"""

from typing import Callable, Dict, List, Optional, Set
from loguru import logger

from app.graph.skills.skill_config import SkillConfig


class SkillRegistry:
    """Skill 注册表

    管理所有 SkillConfig 实例，提供节点函数工厂和路由查询。

    Usage:
        registry = SkillRegistry()
        registry.register(order_skill_config)
        registry.register(product_skill_config)

        # 获取 Skill 配置
        config = registry.get("order")

        # 自动生成 LangGraph 节点函数
        node_func = registry.create_node_function(config, persona="mibao")
        graph.add_node("order_skill", node_func)

        # 查询意图→路由 key 映射
        route_map = registry.get_intent_to_route_map()
    """

    def __init__(self):
        self._skills: Dict[str, SkillConfig] = {}

    def register(self, config: SkillConfig) -> "SkillRegistry":
        """注册 Skill

        Args:
            config: SkillConfig 实例

        Returns:
            SkillRegistry: 支持链式调用

        Raises:
            ValueError: Skill 名称已存在时仅警告，覆盖注册
        """
        if config.name in self._skills:
            logger.warning(
                f"[SkillRegistry] Skill '{config.name}' already registered, overwriting"
            )
        self._skills[config.name] = config
        logger.info(
            f"[SkillRegistry] Registered: {config.name} | "
            f"domain={config.domain} tools={len(config.tool_names)} "
            f"intents={len(config.intents)} personas={list(config.system_prompts.keys())}"
        )
        return self

    def get(self, name: str) -> Optional[SkillConfig]:
        """获取 Skill 配置

        Args:
            name: Skill 名称

        Returns:
            Optional[SkillConfig]: 配置实例或 None
        """
        return self._skills.get(name)

    def get_or_raise(self, name: str) -> SkillConfig:
        """获取 Skill 配置，不存在时抛异常

        Args:
            name: Skill 名称

        Returns:
            SkillConfig: 配置实例

        Raises:
            KeyError: Skill 未注册
        """
        config = self._skills.get(name)
        if config is None:
            available = ", ".join(sorted(self._skills.keys())) or "(empty)"
            raise KeyError(
                f"Skill '{name}' not found. Available: {available}"
            )
        return config

    def get_all(self) -> List[SkillConfig]:
        """获取所有已注册的 Skill 配置"""
        return list(self._skills.values())

    def get_names(self) -> List[str]:
        """获取所有已注册的 Skill 名称"""
        return list(self._skills.keys())

    def has(self, name: str) -> bool:
        """检查 Skill 是否已注册"""
        return name in self._skills

    # ────────────── 节点函数工厂 ──────────────

    def create_node_function(
        self, config: SkillConfig, persona: str
    ) -> Callable:
        """自动生成 LangGraph 节点函数

        根据 SkillConfig 和 persona 自动生成一个 `async def xxx_node(state) -> dict`
        函数，内部调用 execute_skill()。这消除了当前 13 个 Skill 文件中的样板代码。

        Args:
            config: Skill 配置
            persona: 人格标识，用于选择 System Prompt

        Returns:
            Callable: 可直接传给 graph.add_node() 的异步函数
        """
        system_prompt = config.get_prompt(persona)
        skill_name = config.name
        tool_names = config.tool_names
        max_iterations = config.max_iterations

        async def _skill_node(state: dict) -> dict:
            """自动生成的 Skill 节点函数"""
            from app.graph.skills.base_skill import execute_skill

            return await execute_skill(
                state=state,
                skill_name=skill_name,
                tool_names=tool_names,
                system_prompt=system_prompt,
                max_iterations=max_iterations,
            )

        # 设置函数名，便于日志和调试
        _skill_node.__name__ = f"{skill_name}_node"
        _skill_node.__qualname__ = f"{skill_name}_node"
        _skill_node.__doc__ = f"Auto-generated node for Skill '{skill_name}' (persona={persona})"

        return _skill_node

    # ────────────── 路由查询 ──────────────

    def get_intent_to_route_map(self, persona: str | None = "mibao") -> Dict[str, str]:
        """聚合所有 Skill 的意图→路由 key 映射

        返回的字典可直接替代 nodes.py 中的 _INTENT_TO_ROUTE 硬编码映射。

        Args:
            persona: 按 persona 过滤 Skill（None 表示不过滤，返回全部）。
                     默认 "mibao"，避免 C 端 skill 的意图覆盖 B 端映射。

        Returns:
            Dict[str, str]: {intent_value: route_key} 映射

        Note:
            如果多个 Skill 声明了相同的 intent，后者覆盖前者并记录警告。
        """
        intent_map: Dict[str, str] = {}
        for config in self._skills.values():
            # 按 persona 过滤：skill 的 system_prompts 包含该 persona 才纳入
            if persona and persona not in config.system_prompts:
                continue
            for route_key in config.route_keys:
                for intent in config.intents:
                    if intent in intent_map and intent_map[intent] != route_key:
                        logger.warning(
                            f"[SkillRegistry] Intent '{intent}' mapped to "
                            f"'{intent_map[intent]}' and '{route_key}', "
                            f"using '{route_key}'"
                        )
                    intent_map[intent] = route_key
        return intent_map

    def get_all_intents(self) -> Set[str]:
        """获取所有 Skill 声明的意图集合"""
        intents: Set[str] = set()
        for config in self._skills.values():
            intents.update(config.intents)
        return intents

    def get_intents_for_skills(self, skill_names: List[str]) -> List[str]:
        """获取指定 Skill 子集的所有意图

        用于 Agent 感知的意图分类——只列出该 Agent 能处理的意图。

        Args:
            skill_names: Skill 名称列表

        Returns:
            List[str]: 去重后的意图列表
        """
        intents: Set[str] = set()
        for name in skill_names:
            config = self._skills.get(name)
            if config:
                intents.update(config.intents)
        return sorted(intents)

    def get_skill_route_map(
        self, skill_names: List[str], fallback_skill: str
    ) -> Dict[str, str]:
        """为指定的 Skill 子集构建完整的路由映射

        返回的字典可直接传给 graph.add_conditional_edges()。

        Args:
            skill_names: Agent 使用的 Skill 名称列表
            fallback_skill: 兜底 Skill 名称

        Returns:
            Dict[str, str]: {route_key: node_id} 映射，
                            node_id 格式为 "{skill_name}_skill"
        """
        route_map: Dict[str, str] = {"direct_reply": "direct_reply"}

        all_skills = list(skill_names)
        if fallback_skill not in all_skills:
            all_skills.append(fallback_skill)

        for skill_name in all_skills:
            config = self._skills.get(skill_name)
            if not config:
                logger.warning(
                    f"[SkillRegistry] Skill '{skill_name}' not found, skipping"
                )
                continue

            node_id = f"{skill_name}_skill"
            for route_key in config.route_keys:
                route_map[route_key] = node_id

        return route_map

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __repr__(self) -> str:
        return f"SkillRegistry(skills={list(self._skills.keys())})"


# ────────────── 全局单例 ──────────────

_skill_registry_instance: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取全局 SkillRegistry 实例（懒加载 + 单例）

    首次调用时触发所有 Skill 的注册（通过 _register_all_skills()），
    后续调用直接返回缓存实例。

    Returns:
        SkillRegistry: 全局 Skill 注册表
    """
    global _skill_registry_instance
    if _skill_registry_instance is None:
        _skill_registry_instance = SkillRegistry()
        _register_all_skills(_skill_registry_instance)
        logger.info(
            f"[SkillRegistry] Global registry initialized with "
            f"{len(_skill_registry_instance)} skills"
        )
    return _skill_registry_instance


def reset_skill_registry():
    """重置全局 SkillRegistry（用于测试）"""
    global _skill_registry_instance
    _skill_registry_instance = None


def _register_all_skills(registry: SkillRegistry):
    """注册所有内置 Skill

    从各 Skill 文件导入 SkillConfig 并注册。
    每个 Skill 文件导出一个 SkillConfig 实例（如 ORDER_SKILL_CONFIG）。

    包含米宝（B 端）和小布（C 端）两套 Skill 配置。
    Agent 通过 AgentConfig.skill_names 选择使用哪些 Skill。
    """
    # 延迟导入避免循环依赖

    # ── 米宝（B 端工作助手）Skill ──
    from app.graph.skills.order_skill import ORDER_SKILL_CONFIG
    from app.graph.skills.product_skill import PRODUCT_SKILL_CONFIG
    from app.graph.skills.aftersales_skill import AFTERSALES_SKILL_CONFIG
    from app.graph.skills.customer_skill import CUSTOMER_SKILL_CONFIG
    from app.graph.skills.staff_skill import STAFF_SKILL_CONFIG
    from app.graph.skills.settings_skill import SETTINGS_SKILL_CONFIG
    from app.graph.skills.data_skill import DATA_SKILL_CONFIG
    from app.graph.skills.knowledge_skill import KNOWLEDGE_SKILL_CONFIG
    from app.graph.skills.general_agent import GENERAL_SKILL_CONFIG

    # ── 小布（C 端客服）Skill ──
    from app.graph.skills.customer_order_skill import CUSTOMER_ORDER_SKILL_CONFIG
    from app.graph.skills.customer_product_skill import CUSTOMER_PRODUCT_SKILL_CONFIG
    from app.graph.skills.customer_knowledge_skill import CUSTOMER_KNOWLEDGE_SKILL_CONFIG
    from app.graph.skills.customer_general_skill import CUSTOMER_GENERAL_SKILL_CONFIG
    from app.graph.skills.customer_aftersales_skill import CUSTOMER_AFTERSALES_SKILL_CONFIG

    for config in [
        # 米宝 Skill
        ORDER_SKILL_CONFIG,
        PRODUCT_SKILL_CONFIG,
        AFTERSALES_SKILL_CONFIG,
        CUSTOMER_SKILL_CONFIG,
        STAFF_SKILL_CONFIG,
        SETTINGS_SKILL_CONFIG,
        DATA_SKILL_CONFIG,
        KNOWLEDGE_SKILL_CONFIG,
        GENERAL_SKILL_CONFIG,
        # 小布 Skill
        CUSTOMER_ORDER_SKILL_CONFIG,
        CUSTOMER_PRODUCT_SKILL_CONFIG,
        CUSTOMER_KNOWLEDGE_SKILL_CONFIG,
        CUSTOMER_GENERAL_SKILL_CONFIG,
        CUSTOMER_AFTERSALES_SKILL_CONFIG,
    ]:
        registry.register(config)
