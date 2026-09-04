"""
领域本体模块测试 — schema 加载与状态枚举校验（issue #2821 切片 1）

覆盖 app/ontology/loader.load_ontology 的公共契约：
- 默认 schema.yaml 存在且可加载，返回 Ontology 四对象
- 订单/售后/商品状态枚举与 CONTRACT-LEDGER 铁律一致（独立真值来源）
- 非法状态值加载校验必须拒绝并报错

Seam: app.ontology.loader.load_ontology() → Ontology（唯一公共入口，
不触碰内部 models/加载实现细节）。
"""
# case_ids: ON-001

import pytest

from app.ontology.loader import load_ontology, OntologySchemaError

# ── 独立真值来源：docs/wiki/CONTRACT-LEDGER.md §一（2026-09-04 核对）──
ORDER_STATUS_LEDGER = [
    "pending", "confirmed", "producing", "shipped", "completed", "cancelled",
]
AFTERSALES_STATUS_LEDGER = [
    "pending", "processing", "rejected", "resolved", "closed",
]
PRODUCT_STATUS_LEDGER = [
    "draft", "on_sale", "off_sale", "under_review",
]


@pytest.fixture(scope="module")
def ontology():
    """加载默认 schema.yaml（与包同目录）"""
    return load_ontology()


class TestOntologyLoad:
    def test_load_returns_four_objects(self, ontology):
        """默认 schema 必须包含四核心对象"""
        names = sorted(ontology.objects.keys())
        assert names == ["aftersales", "customer", "order", "product_sku"]

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
