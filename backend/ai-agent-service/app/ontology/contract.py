"""
intent 归属契约校验（issue #2821 切片 3 + 延续切片 A 全量登记）

把「修改 B 端 intent 必须验证 xiaobu 路由仍然正常」从 skill_registry.py:163-166
的注释承诺变为机器校验：以 schema.intent_ownership 为单一事实源，与双端真实
映射（agent_intent_maps）按 agent 分别对比，输出违规清单。

契约（check_intent_ownership v2，按 agent 核对）：
- **存在性**：schema 声明某 agent 可达的 intent，该 agent 映射中必须存在（防假声明）
- **route_key 严格一致性（仅 mibao）**：B 端全局映射是路由约定事实源，mibao 的
  route_key 必须与 schema 逐字一致（防漂移）。xiaobu 因 customer_general 兜底
  skill 会把大量 intent 的 route_key 覆盖为 data，不要求逐字一致，只要求可达。
- **未登记**：任一 agent 映射中的 intent 必须登记 schema（新 intent 漂移，
  include_unregistered=True 时计违规；降级模式忽略）
- **可达性**：schema 声明 agent 可达的 intent，其 route_key 必须在该 agent
  真实可达集合中（改 B 端映射后 xiaobu 视图没跟上 → 违规）
"""

from typing import Dict, List, Set

from app.ontology.models import Ontology


def check_intent_ownership(
    ontology: Ontology,
    agent_intent_maps: Dict[str, Dict[str, str]],
    agent_route_keys: Dict[str, Set[str]],
    include_unregistered: bool = True,
) -> List[str]:
    """校验 intent 归属契约（v2，按 agent 分别核对）。

    Args:
        ontology: 加载后的本体（含 intent_ownership 归属表）
        agent_intent_maps: {agent: {intent: route_key}} 每个 agent 实际注册 skill
            的意图→路由映射（真实可达：由 get_all_skill_names 含 fallback 构建，
            而非 persona 过滤——后者会包含被 RAG 禁用/未启用的 skill）
        agent_route_keys: {agent: set(route_keys)} 每个 agent 真实可达的路由集合
        include_unregistered: 是否把「agent 映射有但 schema 未登记」计为违规。
            默认 True（全量严查）；降级模式传 False（兼容存量过渡期）

    Returns:
        List[str]: 违规清单；空列表 = 全部一致。
    """
    violations: List[str] = []
    owned = ontology.intent_ownership or {}
    if not owned:
        return ["schema 未声明 intent_ownership 段（契约缺失）"]

    schema_intents = set(owned)
    all_actual_intents = set()
    for agent, mapping in agent_intent_maps.items():
        all_actual_intents.update(mapping)

    # 1. 存在性 + route_key 一致性（按 agent 分别核对）
    for intent in sorted(schema_intents):
        info = owned[intent]
        for agent in info.agents or []:
            mapping = agent_intent_maps.get(agent, {})
            # 1a. 假声明：schema 声明该 agent 可达，但该 agent 映射缺失
            if intent not in mapping:
                violations.append(
                    f"intent '{intent}' schema 声明 agent '{agent}' 可达，"
                    f"但该 agent 映射缺失（route_key={info.route_key}）"
                )
                continue
            # 1b. route_key 严格一致性：仅 mibao（B 端是路由约定事实源）
            if agent == "mibao" and mapping[intent] != info.route_key:
                violations.append(
                    f"intent '{intent}' route_key 漂移（mibao）："
                    f"schema={info.route_key} 实际={mapping[intent]}"
                )

    # 2. 未登记（任一 agent 映射中有、schema 无 → 新 intent 漂移）
    if include_unregistered:
        for intent in sorted(all_actual_intents - schema_intents):
            route_keys = sorted(
                {m[intent] for m in agent_intent_maps.values() if intent in m}
            )
            violations.append(
                f"intent '{intent}' 已在 agent 映射（→{route_keys}）但 schema 未登记"
            )

    # 3. 可达性：schema 声明 agent 可达的 intent，route_key 必须在该 agent 可达集合
    for intent in sorted(schema_intents):
        info = owned[intent]
        for agent in info.agents or []:
            reachable = agent_route_keys.get(agent, set())
            if info.route_key not in reachable:
                violations.append(
                    f"intent '{intent}' 声明 agent '{agent}' 可达（route_key={info.route_key}），"
                    f"但该 agent 实际可达路由 {sorted(reachable)} 中缺失"
                )

    return violations
