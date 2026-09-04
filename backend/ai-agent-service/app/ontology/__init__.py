"""领域本体包（issue #2821）

四对象（订单/商品SKU/售后单/客户）的机器可消费单一事实源：
schema.yaml（YAML 定义）+ loader（加载与铁律校验）+ models（数据模型）。
"""

from app.ontology.contract import check_intent_ownership
from app.ontology.loader import OntologySchemaError, load_ontology
from app.ontology.models import IntentOwnership, Ontology, OntologyObject

__all__ = [
    "IntentOwnership",
    "Ontology",
    "OntologyObject",
    "OntologySchemaError",
    "check_intent_ownership",
    "load_ontology",
]
