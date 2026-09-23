"""
领域本体加载器（issue #2821 切片 1）

职责：schema.yaml（YAML 单一事实源）→ Ontology 数据模型，并在加载时做
结构校验 + 状态枚举铁律校验（与 CONTRACT-LEDGER 对齐，防止 schema 漂移）。

Seam: load_ontology(path=None) → Ontology；所有加载异常统一抛 OntologySchemaError。
"""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.ontology.models import (
    ActionDef,
    IntentOwnership,
    Ontology,
    OntologyObject,
    PropertyDef,
    RelationDef,
    RuleDef,
)


class OntologySchemaError(ValueError):
    """本体 schema 加载/校验失败（结构缺失、枚举漂移、非法取值）"""


# 默认 schema 与 loader 同目录
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.yaml"

# ── 状态枚举铁律词表（独立真值来源：CONTRACT-LEDGER §一 + 代码真值）──
# 加载时校验：schema 中的 <对象>.status 枚举必须与词表**逐字一致**，
# 否则 OntologySchemaError——从源头拦截"processing/producing"类漂移。
STATUS_LEXICON: Dict[str, List[str]] = {
    "order.status": ["pending", "confirmed", "producing", "shipped", "completed", "cancelled"],
    "aftersales.status": ["pending", "processing", "rejected", "resolved", "closed"],
    "product_sku.status": ["draft", "on_sale", "off_sale", "under_review"],
    # 切片 B 扩展对象（2026-09-04 代码真值：AgentEmployeeService 错误消息 /
    # DTO 注释 / admin-web types）
    "employee.status": ["online", "offline", "busy"],
    "processing_item.status": ["active", "inactive"],
    "category.status": ["active", "inactive"],
    # 🔴 2026-09-23 删除 `knowledge_document.status`（issue #5245 B4）：该对象已随旧 RAG
    # 知识库退场 —— `V36__drop_rag_knowledge_tables.sql` DROP 掉 knowledge_documents 等表，
    # 本体侧 knowledge_document 对象亦已移除（现存 7 对象）。留着它是**死条目**：
    # 词表里再也没有对象能命中它（loader 按 `<对象名>.status` 取值），却让「词表 =
    # 三端真契约清单」这句话失真。词表与 schema 的双向一致性由
    # backend/ai-agent-service/tests/test_ontology_schema.py（ON-001）机械判据钉住。
}


def _schema_error(msg: str) -> OntologySchemaError:
    return OntologySchemaError(msg)


def load_ontology(path: Optional[Path | str] = None) -> Ontology:
    """加载本体 schema。

    Args:
        path: schema.yaml 路径；缺省用包内默认 schema.yaml。

    Returns:
        Ontology: 校验通过的领域本体。

    Raises:
        OntologySchemaError: 文件缺失/YAML 解析失败/结构缺失/状态枚举漂移。
    """
    schema_path = Path(path) if path else DEFAULT_SCHEMA_PATH
    if not schema_path.exists():
        raise _schema_error(f"本体 schema 不存在: {schema_path}")

    try:
        with open(schema_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise _schema_error(f"YAML 解析失败 {schema_path}: {e}") from e

    if not isinstance(data, dict) or not isinstance(data.get("objects"), dict):
        raise _schema_error("schema 缺少 objects 映射（必须为 dict）")

    version = str(data.get("version", "1.0"))
    objects: Dict[str, OntologyObject] = {}
    for name, obj_raw in data["objects"].items():
        objects[name] = _parse_object(name, obj_raw)
    external_targets = _parse_external_targets(data.get("external_targets"))
    _validate_relation_targets(objects, external_targets)
    intent_ownership = _parse_intent_ownership(data.get("intent_ownership"))
    return Ontology(
        version=version,
        objects=objects,
        intent_ownership=intent_ownership,
        external_targets=external_targets,
    )


def _parse_external_targets(raw: object) -> Dict[str, str]:
    """解析 external_targets 段 → {外部概念名: 登记理由}（issue #5245 B6）。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _schema_error("external_targets 必须为映射（外部概念名: 登记理由）")
    return {str(k): str(v) for k, v in raw.items()}


def _validate_relation_targets(
    objects: Dict[str, OntologyObject], external_targets: Dict[str, str]
) -> None:
    """relations[].target 必须落在 objects 或 external_targets（issue #5245 B6，fail-closed）。

    改前 `order_item` / `product` / `processing_category` / `agent_session` / `tenant`
    五个悬空目标**无人校验**：本体可以引用一个不存在的对象而永不报错（同一形态的另一半
    是 `source:` 从未与 Java 实体/DB 列对账，见 #5245 B7「待办」）。
    错误消息同时给出两个登记处，避免"红却指不出怎么修"。
    """
    overlap = sorted(set(objects) & set(external_targets))
    if overlap:
        raise _schema_error(
            f"关系目标同时登记为本体对象与外部概念: {overlap} —— 只能选一处"
            f"（两处都有 ⇒ 无从判定谁是真值源）"
        )
    for obj_name, obj in objects.items():
        for rel in obj.relations:
            if rel.target not in objects and rel.target not in external_targets:
                raise _schema_error(
                    f"对象 {obj_name} 的关系 {rel.name} 指向未登记目标 '{rel.target}'："
                    f"要么在本体 objects 建对象，要么在 external_targets 显式登记为外部概念"
                )


def _parse_object(name: str, obj_raw: object) -> OntologyObject:
    if not isinstance(obj_raw, dict):
        raise _schema_error(f"对象 {name} 定义必须为映射")
    display_name = str(obj_raw.get("display_name", name))

    properties_raw = obj_raw.get("properties")
    if not isinstance(properties_raw, dict):
        raise _schema_error(f"对象 {name} 缺少 properties 映射")
    properties: Dict[str, PropertyDef] = {}
    for pname, p_raw in properties_raw.items():
        properties[pname] = _parse_property(name, pname, p_raw)

    # 状态枚举铁律校验：schema 声明的 status 枚举与 CONTRACT-LEDGER 词表逐字一致
    status_prop = properties.get("status")
    if status_prop is not None and status_prop.type == "enum":
        lexicon_key = f"{name}.status"
        expected = STATUS_LEXICON.get(lexicon_key)
        if expected is not None and status_prop.enum_values != expected:
            raise _schema_error(
                f"对象 {name} 的 status 枚举与 CONTRACT-LEDGER 不一致: "
                f"schema={status_prop.enum_values} 铁律={expected}"
            )

    relations = _parse_relations(name, obj_raw.get("relations"))
    actions = _parse_actions(name, obj_raw.get("actions"))
    rules = _parse_rules(name, obj_raw.get("rules"))

    return OntologyObject(
        name=name,
        display_name=display_name,
        properties=properties,
        relations=relations,
        actions=actions,
        rules=rules,
    )


def _parse_property(obj_name: str, pname: str, p_raw: object) -> PropertyDef:
    if not isinstance(p_raw, dict):
        raise _schema_error(f"对象 {obj_name} 属性 {pname} 定义必须为映射")
    ptype = str(p_raw.get("type", "string"))
    enum_values: Optional[List[str]] = None
    if ptype == "enum":
        values = p_raw.get("values")
        if not isinstance(values, list) or not values:
            raise _schema_error(f"对象 {obj_name} 属性 {pname} type=enum 必须提供非空 values")
        enum_values = [str(v) for v in values]
    return PropertyDef(
        name=pname,
        type=ptype,
        enum_values=enum_values,
        required=bool(p_raw.get("required", False)),
        source=str(p_raw.get("source", "")),
        description=str(p_raw.get("description", "")),
    )


def _parse_relations(obj_name: str, relations_raw: object) -> List[RelationDef]:
    relations: List[RelationDef] = []
    if not isinstance(relations_raw, list):
        return relations
    for r_raw in relations_raw:
        if not isinstance(r_raw, dict):
            raise _schema_error(f"对象 {obj_name} relations 项必须为映射")
        relations.append(
            RelationDef(
                name=str(r_raw.get("name", "")),
                target=str(r_raw.get("target", "")),
                cardinality=str(r_raw.get("cardinality", "1:N")),
                description=str(r_raw.get("description", "")),
            )
        )
    return relations


def _parse_actions(obj_name: str, actions_raw: object) -> List[ActionDef]:
    actions: List[ActionDef] = []
    if not isinstance(actions_raw, list):
        return actions
    for a_raw in actions_raw:
        if not isinstance(a_raw, dict):
            raise _schema_error(f"对象 {obj_name} actions 项必须为映射")
        allowed = a_raw.get("allowed_agents")
        actions.append(
            ActionDef(
                name=str(a_raw.get("name", "")),
                confirmation_required=bool(a_raw.get("confirmation_required", False)),
                allowed_agents=[str(x) for x in allowed] if isinstance(allowed, list) else None,
                preconditions=[str(x) for x in a_raw.get("preconditions", [])],
                description=str(a_raw.get("description", "")),
            )
        )
    return actions


def _parse_rules(obj_name: str, rules_raw: object) -> List[RuleDef]:
    rules: List[RuleDef] = []
    if not isinstance(rules_raw, list):
        return rules
    for r_raw in rules_raw:
        if isinstance(r_raw, str):
            rules.append(RuleDef(text=r_raw, severity="must"))
        elif isinstance(r_raw, dict):
            rules.append(
                RuleDef(
                    text=str(r_raw.get("text", "")),
                    severity=str(r_raw.get("severity", "must")),
                )
            )
        else:
            raise _schema_error(f"对象 {obj_name} rules 项必须为字符串或映射")
    return rules


def _parse_intent_ownership(intent_raw: object) -> Dict[str, IntentOwnership]:
    """解析 intent_ownership 段 → {intent: IntentOwnership}

    每个 intent 必须声明 route_key；agents 缺省为空（表示未声明可达性）。
    """
    owned: Dict[str, IntentOwnership] = {}
    if not isinstance(intent_raw, dict):
        return owned
    for intent, spec in intent_raw.items():
        if not isinstance(spec, dict):
            raise _schema_error(f"intent_ownership.{intent} 定义必须为映射")
        route_key = str(spec.get("route_key", ""))
        if not route_key:
            raise _schema_error(f"intent_ownership.{intent} 缺少 route_key")
        agents_raw = spec.get("agents")
        agents = [str(x) for x in agents_raw] if isinstance(agents_raw, list) else []
        owned[intent] = IntentOwnership(
            intent=intent,
            route_key=route_key,
            agents=agents,
            description=str(spec.get("description", "")),
        )
    return owned
