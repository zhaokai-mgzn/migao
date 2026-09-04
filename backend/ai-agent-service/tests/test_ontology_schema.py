"""
领域本体模块测试 — schema 加载与状态枚举校验（issue #2821 切片 1 + 延续切片 B）

覆盖 app/ontology/loader.load_ontology 的公共契约：
- 默认 schema.yaml 存在且可加载，返回 Ontology 八对象（核心四对象 + 员工/加工项/分类/知识）
- 各对象状态枚举与代码真值一致（独立真值来源）
- 非法状态值加载校验必须拒绝并报错

Seam: app.ontology.loader.load_ontology() → Ontology（唯一公共入口，
不触碰内部 models/加载实现细节）。
"""
# case_ids: ON-001

import pytest

from app.ontology.loader import load_ontology, OntologySchemaError

# ── 独立真值来源（2026-09-04 核对）──
# 核心对象：docs/wiki/CONTRACT-LEDGER.md §一
ORDER_STATUS_LEDGER = [
    "pending", "confirmed", "producing", "shipped", "completed", "cancelled",
]
AFTERSALES_STATUS_LEDGER = [
    "pending", "processing", "rejected", "resolved", "closed",
]
PRODUCT_STATUS_LEDGER = [
    "draft", "on_sale", "off_sale", "under_review",
]
# 扩展对象（切片 B）：AgentEmployeeService.java:38 错误消息 / DTO 注释 / admin-web types
EMPLOYEE_STATUS_LEDGER = ["online", "offline", "busy"]
PROCESSING_ITEM_STATUS_LEDGER = ["active", "inactive"]
CATEGORY_STATUS_LEDGER = ["active", "inactive"]
KNOWLEDGE_DOC_STATUS_LEDGER = ["processed", "processing", "failed"]


@pytest.fixture(scope="module")
def ontology():
    """加载默认 schema.yaml（与包同目录）"""
    return load_ontology()


class TestOntologyLoad:
    def test_load_returns_eight_objects(self, ontology):
        """默认 schema 必须包含八对象（核心四 + 扩展四）"""
        names = sorted(ontology.objects.keys())
        assert names == [
            "aftersales", "category", "customer", "employee",
            "knowledge_document", "order", "processing_item", "product_sku",
        ]

    def test_each_object_has_required_sections(self, ontology):
        """每个对象必须有属性/关系/动作/规则四要素（缺一不可）"""
        for name, obj in ontology.objects.items():
            assert obj.properties, f"{name} 缺属性"
            assert obj.relations is not None, f"{name} 缺关系"
            assert obj.actions is not None, f"{name} 缺动作"
            assert obj.rules is not None, f"{name} 缺规则"


class TestOrderStatusEnum:
    def test_order_status_matches_ledger(self, ontology):
        """订单状态枚举与 CONTRACT-LEDGER 完全一致（生产中是 producing 非 processing）"""
        order = ontology.objects["order"]
        assert order.properties["status"].enum_values == ORDER_STATUS_LEDGER

    def test_aftersales_status_matches_ledger(self, ontology):
        aftersales = ontology.objects["aftersales"]
        assert aftersales.properties["status"].enum_values == AFTERSALES_STATUS_LEDGER

    def test_product_status_matches_ledger(self, ontology):
        product = ontology.objects["product_sku"]
        assert product.properties["status"].enum_values == PRODUCT_STATUS_LEDGER


class TestExtendedObjectStatusEnum:
    """切片 B 扩展对象状态枚举（独立真值：service 错误消息 / DTO 注释 / admin-web types）"""

    def test_employee_status_matches_ledger(self, ontology):
        """员工状态与 AgentEmployeeService 合法值一致（online/offline/busy）"""
        employee = ontology.objects["employee"]
        assert employee.properties["status"].enum_values == EMPLOYEE_STATUS_LEDGER

    def test_processing_item_status_matches_ledger(self, ontology):
        """加工项状态与前端 ProcessingItemStatus 一致（active/inactive）"""
        item = ontology.objects["processing_item"]
        assert item.properties["status"].enum_values == PROCESSING_ITEM_STATUS_LEDGER

    def test_category_status_matches_ledger(self, ontology):
        """分类状态与 CategoryCreateRequest 注释一致（active/inactive）"""
        category = ontology.objects["category"]
        assert category.properties["status"].enum_values == CATEGORY_STATUS_LEDGER

    def test_knowledge_doc_status_matches_ledger(self, ontology):
        """知识文档状态与前端 KnowledgeDocStatus 一致（processed/processing/failed）"""
        doc = ontology.objects["knowledge_document"]
        assert doc.properties["status"].enum_values == KNOWLEDGE_DOC_STATUS_LEDGER


class TestEnumValidation:
    def test_invalid_status_value_rejected(self, tmp_path):
        """非法状态值（processing 混入订单枚举）必须拒绝并报错"""
        bad_schema = tmp_path / "bad_schema.yaml"
        bad_schema.write_text(
            """
objects:
  order:
    properties:
      status:
        type: enum
        values: [pending, processing]
            """,
            encoding="utf-8",
        )
        with pytest.raises(OntologySchemaError):
            load_ontology(bad_schema)

    def test_missing_status_enum_rejected(self, tmp_path):
        """状态属性缺少 values 定义必须拒绝"""
        bad_schema = tmp_path / "no_values.yaml"
        bad_schema.write_text(
            """
objects:
  order:
    properties:
      status:
        type: enum
            """,
            encoding="utf-8",
        )
        with pytest.raises(OntologySchemaError):
            load_ontology(bad_schema)
