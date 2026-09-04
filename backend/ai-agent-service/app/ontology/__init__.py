"""领域本体包（issue #2821）

四对象（订单/商品SKU/售后单/客户）的机器可消费单一事实源：
schema.yaml（YAML 定义）+ loader（加载与铁律校验）+ models（数据模型）。
"""

from app.ontology.loader import OntologySchemaError, load_ontology
from app.ontology.models import Ontology, OntologyObject

__all__ = ["Ontology", "OntologyObject", "OntologySchemaError", "load_ontology"]
