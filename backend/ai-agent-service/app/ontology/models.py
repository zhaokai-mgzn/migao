"""
领域本体数据模型（issue #2821 切片 1）

四对象（订单/商品SKU/售后单/客户）× 四要素（属性/关系/动作/规则）——
对应 Palantir 式 Object/Link/Action/Rule 骨架，作为 MIGAO 业务语义的
机器可消费单一事实源（TBox）。全部 frozen dataclass，加载后不可变。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PropertyDef:
    """对象属性定义

    name: 属性名（snake_case，对齐 Agent 侧语义）
    type: 类型（string / int / decimal / bool / enum / datetime）
    enum_values: type=enum 时的合法取值（单一事实源，与 CONTRACT-LEDGER 对齐）
    required: 是否必填
    source: 挂载点（Java 实体字段名 / 前端 TS 字段名），供跨端对账
    description: 语义说明
    """
    name: str
    type: str
    enum_values: Optional[List[str]] = None
    required: bool = False
    source: str = ""
    description: str = ""


@dataclass(frozen=True)
class RelationDef:
    """对象关系定义（Link）

    name: 关系名
    target: 目标对象名（ontology 内）
    cardinality: 基数（1:N / N:1 / N:M）
    description: 关系语义
    """
    name: str
    target: str
    cardinality: str = "1:N"
    description: str = ""


@dataclass(frozen=True)
class ActionDef:
    """对象动作定义（Action）

    name: 动作名（对齐工具/端点语义）
    confirmation_required: 是否需确认闸（写操作守卫，GB-03）
    allowed_agents: 允许的 Agent 白名单（缺省=两端都允许；[]=不允许任何 Agent）
    preconditions: 前置条件（本体规则化表达）
    description: 动作语义
    """
    name: str
    confirmation_required: bool = False
    allowed_agents: Optional[List[str]] = None
    preconditions: List[str] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class RuleDef:
    """业务规则（Axiom）——机器可校验的约束声明

    text: 规则文本（可直接注入 prompt / 用于断言）
    severity: must（硬约束，违反即拒绝）| should（软约束，需澄清/提示）
    """
    text: str
    severity: str = "must"


@dataclass(frozen=True)
class OntologyObject:
    """领域对象（订单/商品SKU/售后单/客户…）"""
    name: str
    display_name: str
    properties: Dict[str, PropertyDef] = field(default_factory=dict)
    relations: List[RelationDef] = field(default_factory=list)
    actions: List[ActionDef] = field(default_factory=list)
    rules: List[RuleDef] = field(default_factory=list)

    def get_property(self, name: str) -> Optional[PropertyDef]:
        return self.properties.get(name)


@dataclass(frozen=True)
class IntentOwnership:
    """意图归属声明（intent → route_key → agents）

    单一事实源：schema.intent_ownership 声明每个业务 intent 属于哪个路由
    以及哪些 Agent 必须可达。契约校验（app.ontology.contract）据此与
    skill_registry 实际映射对比，把『修改 B 端 intent 必须验证 xiaobu』
    从注释承诺变为机器校验。
    """
    intent: str
    route_key: str
    agents: List[str] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class Ontology:
    """领域本体：对象集合 + 版本

    四对象（order / product_sku / aftersales / customer）作为切片 1 范围；
    objects 为 name → OntologyObject 映射。
    intent_ownership: intent → IntentOwnership 归属表（切片 3）。
    """
    version: str
    objects: Dict[str, OntologyObject] = field(default_factory=dict)
    intent_ownership: Dict[str, IntentOwnership] = field(default_factory=dict)

    def get_object(self, name: str) -> Optional[OntologyObject]:
        return self.objects.get(name)
