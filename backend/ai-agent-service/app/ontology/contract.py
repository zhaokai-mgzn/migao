"""
intent 归属契约校验（issue #2821 切片 3）

把「修改 B 端 intent 必须验证 xiaobu 路由仍然正常」从 skill_registry.py:163-166
的注释承诺变为机器校验：以 schema.intent_ownership 为单一事实源，与
skill_registry 实际映射（get_intent_to_route_map）对比，输出违规清单。

契约（check_intent_ownership）：
- schema 声明 intent 必须存在于 skill 实际映射（B 端新增 intent 未实现 → 违规）
- skill 实际 intent 必须登记在 schema（新 intent 漂移无记录 → 违规）
- schema 的 route_key 与实际映射一致（route_key 漂移 → 违规）
- schema 声明某 agent 可达的 intent，其 route_key 必须在该 agent 可达集合中
  （改 B 端映射后 xiaobu 视图没跟上 → 违规）
"""

from typing import Dict, List, Set

from app.ontology.models import Ontology


def check_intent_ownership(
    ontology: Ontology,
    intent_to_route: Dict[str, str],
    agent_route_keys: Dict[str, Set[str]],
    include_unregistered: bool = True,
) -> List[str]:
    """校验 intent 归属契约。

    Args:
        ontology: 加载后的本体（含 intent_ownership 归属表）
        intent_to_route: skill_registry.get_intent_to_route_map() 的实际
                         intent → route_key 映射（B 端全局映射）
        agent_route_keys: {agent: set(route_keys)} 每个 Agent 实际可达的路由集合
                          （如 mibao/xiaobu 的 skill_names → route_keys 并集）
        include_unregistered: 是否把「skill 已映射但 schema 未登记」计为违规。
            默认 True（全量严查，新增 intent 必须登记）；试点阶段接入
            contract-check.sh 传 False，只严查 schema 已声明范围
            （防假声明/route_key 漂移/双端不可达），未登记项留待全量登记。

    Returns:
        List[str]: 违规清单；空列表 = 全部一致。
    """
    violations: List[str] = []
    owned = ontology.intent_ownership or {}
    if not owned:
        return ["schema 未声明 intent_ownership 段（切片 3 契约缺失）"]

    schema_intents = set(owned)
    actual_intents = set(intent_to_route)

    # 1. schema 声明但实际映射缺失（B 端新增 intent 未实现）
    for intent in sorted(schema_intents - actual_intents):
        violations.append(
            f"intent '{intent}' schema 已声明但 skill 映射缺失（route_key={owned[intent].route_key}）"
        )

    # 2. 实际映射但 schema 未登记（新 intent 漂移无记录；试点阶段可关闭）
    if include_unregistered:
        for intent in sorted(actual_intents - schema_intents):
            violations.append(
                f"intent '{intent}' skill 已映射（→{intent_to_route[intent]}）但 schema 未登记"
            )

    # 3. route_key 漂移
    for intent in sorted(schema_intents & actual_intents):
        expected = owned[intent].route_key
        actual = intent_to_route[intent]
        if expected != actual:
            violations.append(
                f"intent '{intent}' route_key 漂移：schema={expected} 实际={actual}"
            )

    # 4. 双端视图可达性：schema 声明 agents 可达的 intent，route_key 必须在该 agent 集合
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
