"""
Skill 配置定义

SkillConfig 是 Skill-centric 架构的核心数据类。
每个 Skill 是一个自包含的能力模块，声明：
- 可用的 Tool 集合
- 处理的意图列表
- 占据的路由 key
- 多人格 System Prompt（同一个 Skill 可服务不同 Agent 人格）

Agent 通过组合不同的 SkillConfig 来构建，不需要修改基础设施代码。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SkillConfig:
    """Skill 声明式配置

    frozen=True 确保配置在注册后不可变，避免运行时意外修改。

    Attributes:
        name: Skill 唯一标识符，如 "order", "product", "supply_chain"
        domain: 领域分组，如 "order", "product", "hr", "supply_chain"
                用于意图命名空间化和日志分组
        display_name: 人类可读名称，如 "订单管理", "商品管理"
        tool_names: 该 Skill 可用的 Tool 名称列表
        route_keys: 在 LangGraph 图中占据的路由 key 列表
                    对应 intent_router 的 route_by_intent 返回值
        intents: 该 Skill 处理的意图类型列表（IntentType 的 value）
                 用于 Agent 感知的意图分类
        system_prompts: 人格→Prompt 映射，如 {"mibao": "...", "xiaobu": "..."}
                        同一个 Skill 可以为不同 Agent 人格提供不同的 Prompt
        default_persona: 当请求的 persona 不在 system_prompts 中时使用的 fallback key
        max_iterations: Tool Calling 最大迭代次数，默认 5
    """
    name: str
    domain: str
    display_name: str
    tool_names: List[str] = field(default_factory=list)
    route_keys: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    system_prompts: Dict[str, str] = field(default_factory=dict)
    default_persona: str = "default"
    max_iterations: int = 5

    def get_prompt(self, persona: str) -> str:
        """获取指定人格的 System Prompt

        优先返回 persona 对应的 Prompt，不存在则返回 default_persona 的 Prompt，
        最终兜底返回空字符串。

        Args:
            persona: 人格标识，如 "mibao", "xiaobu"

        Returns:
            str: System Prompt 文本
        """
        if persona in self.system_prompts:
            return self.system_prompts[persona]
        if self.default_persona in self.system_prompts:
            return self.system_prompts[self.default_persona]
        # 兜底：返回任意一个可用的 prompt
        if self.system_prompts:
            return next(iter(self.system_prompts.values()))
        return ""

    def get_all_intents(self) -> List[str]:
        """获取该 Skill 处理的所有意图列表"""
        return list(self.intents)

    def has_persona(self, persona: str) -> bool:
        """检查是否支持指定人格"""
        return persona in self.system_prompts or self.default_persona in self.system_prompts


# ────────────── 便捷工厂函数 ──────────────


def create_skill_config(
    name: str,
    domain: str,
    display_name: str,
    tool_names: List[str],
    route_keys: Optional[List[str]] = None,
    intents: Optional[List[str]] = None,
    mibao_prompt: str = "",
    xiaobu_prompt: str = "",
    extra_prompts: Optional[Dict[str, str]] = None,
    default_persona: str = "mibao",
    max_iterations: int = 5,
) -> SkillConfig:
    """便捷工厂函数，快速创建 SkillConfig

    提供 mibao_prompt / xiaobu_prompt 快捷参数，
    避免每次手动构建 {"mibao": ..., "xiaobu": ...} 字典。

    Args:
        name: Skill 唯一标识
        domain: 领域分组
        display_name: 人类可读名称
        tool_names: Tool 名称列表
        route_keys: 路由 key 列表，默认 [domain]
        intents: 意图列表，默认 []
        mibao_prompt: 米宝人格 Prompt
        xiaobu_prompt: 小布人格 Prompt
        extra_prompts: 额外人格 Prompt，如 {"supply_chain_agent": "..."}
        default_persona: 默认 fallback 人格
        max_iterations: 最大迭代次数

    Returns:
        SkillConfig: 配置实例
    """
    system_prompts: Dict[str, str] = {}
    if mibao_prompt:
        system_prompts["mibao"] = mibao_prompt
    if xiaobu_prompt:
        system_prompts["xiaobu"] = xiaobu_prompt
    if extra_prompts:
        system_prompts.update(extra_prompts)

    return SkillConfig(
        name=name,
        domain=domain,
        display_name=display_name,
        tool_names=tool_names,
        route_keys=route_keys if route_keys is not None else [domain],
        intents=intents or [],
        system_prompts=system_prompts,
        default_persona=default_persona,
        max_iterations=max_iterations,
    )
