"""
领域本体模块测试 — schema 加载与状态枚举校验（issue #2821 切片 1 + 延续切片 B）

覆盖 app/ontology/loader.load_ontology 的公共契约：
- 默认 schema.yaml 存在且可加载，返回 Ontology 七对象（核心四对象 + 员工/加工项/分类）
- 各对象状态枚举与代码真值一致（独立真值来源）
- 非法状态值加载校验必须拒绝并报错

issue #5245 追加（B 组：本体漂移收口）：
- 词表 STATUS_LEXICON ↔ schema 的 status 枚举键集**双向一致**（B4：已删对象不留死条目）
- 关系目标 fail-closed 校验：`relations[].target` ∈ objects ∪ external_targets（B6，含注入式红证）
- `source` 挂载点对齐真实载体（B1~B3：逐个 Java 实体/迁移取证，见 schema.yaml 注释）

Seam: app.ontology.loader.load_ontology() → Ontology（唯一公共入口，
不触碰内部 models/加载实现细节）。
"""
# case_ids: ON-001

import pytest

from app.ontology.loader import STATUS_LEXICON, load_ontology, OntologySchemaError

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


@pytest.fixture(scope="module")
def ontology():
    """加载默认 schema.yaml（与包同目录）"""
    return load_ontology()


class TestOntologyLoad:
    def test_load_returns_eight_objects(self, ontology):
        """默认 schema 必须包含八对象（核心四 + 扩展四）"""
        names = sorted(ontology.objects.keys())
        # 知识库对象（knowledge_document）已随旧 RAG 知识库移除（issue #3051），当前七对象
        assert names == [
            "aftersales", "category", "customer", "employee",
            "order", "processing_item", "product_sku",
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


class TestStatusLexiconIntegrity:
    """词表 ↔ schema 双向一致（issue #5245 B4）：不留死条目，也不漏活枚举。"""

    def test_lexicon_equals_schema_status_enum_keys(self, ontology):
        """词表键集必须**恰好**等于 schema 里 type=enum 的 status 属性集（两个方向都判）。

        * 多一条（如已删对象 `knowledge_document.status`）= 死条目：loader 永远命中不到它，
          却让「词表 = 三端真契约清单」这句话失真（V36 已 DROP RAG 表、本体对象同步移除）；
        * 少一条 = 该对象的 status 枚举**没有**加载期铁律校验（静默失去判别力）。
        """
        schema_keys = {
            f"{name}.status"
            for name, obj in ontology.objects.items()
            if obj.properties.get("status") is not None
            and obj.properties["status"].type == "enum"
        }
        assert set(STATUS_LEXICON) == schema_keys

    def test_deleted_object_is_not_in_lexicon(self, ontology):
        """knowledge_document 由 V36 删表、本体对象同步移除 ⇒ 词表不得再留它。"""
        assert "knowledge_document.status" not in STATUS_LEXICON
        assert "knowledge_document" not in ontology.objects


class TestRelationTargetValidation:
    """关系目标 fail-closed 校验（issue #5245 B6）。"""

    # 切片范围外的承载者：登记为**外部概念**，不补成本体对象
    EXTERNAL_TARGETS = {
        "order_item", "product", "processing_category", "agent_session", "tenant",
    }

    def test_every_relation_target_is_declared_or_external(self, ontology):
        """默认 schema 的每个关系目标都必须可解析（悬空即漏网）。"""
        known = set(ontology.objects) | set(ontology.external_targets)
        dangling = [
            f"{name}.{rel.name} → {rel.target}"
            for name, obj in ontology.objects.items()
            for rel in obj.relations
            if rel.target not in known
        ]
        assert dangling == []

    def test_external_registry_covers_the_five_known_others(self, ontology):
        """这五个概念**登记为外部**而不是补成本体对象（补 = 造第二份会漂移的事实源）。"""
        assert set(ontology.external_targets) == self.EXTERNAL_TARGETS
        assert set(ontology.objects) & self.EXTERNAL_TARGETS == set()

    def test_dangling_relation_target_rejected(self, tmp_path):
        """注入式红证：未登记的悬空 target ⇒ 必须拒绝加载（判据不放宽）。

        若有人把 `_validate_relation_targets` 改成空实现（或只在默认 schema 上"看着对"），
        这条立刻红 —— 它喂的是**另一份最小 schema**，不依赖默认 schema 的现状。
        """
        bad = tmp_path / "dangling_target.yaml"
        bad.write_text(
            "objects:\n"
            "  order:\n"
            "    properties:\n"
            "      id:\n"
            "        type: string\n"
            "    relations:\n"
            "      - name: has_stuff\n"
            "        target: ghost_object\n",
            encoding="utf-8",
        )
        with pytest.raises(OntologySchemaError) as excinfo:
            load_ontology(bad)
        assert "ghost_object" in str(excinfo.value)
        assert "has_stuff" in str(excinfo.value)

    def test_object_and_external_overlap_rejected(self, tmp_path):
        """同名同时登记在两处 ⇒ 拒绝（两处都有 = 无从判定哪份是真值源）。"""
        bad = tmp_path / "overlap.yaml"
        bad.write_text(
            "objects:\n"
            "  order:\n"
            "    properties:\n"
            "      id:\n"
            "        type: string\n"
            "external_targets:\n"
            "  order: 与本体对象同名（错形态）\n",
            encoding="utf-8",
        )
        with pytest.raises(OntologySchemaError) as excinfo:
            load_ontology(bad)
        assert "order" in str(excinfo.value)


class TestPropertySourcesMatchRealCarriers:
    """issue #5245 B1~B3：`source` 必须指向真实载体（逐个 Java 实体/迁移取证）。"""

    def test_product_sku_status_points_at_the_product_column(self, ontology):
        """`ProductSku.java` 无 status 字段 ⇒ 改指 `Product.status`（4 值状态机真值）。"""
        status = ontology.objects["product_sku"].properties["status"]
        assert status.source == "Product.status"
        assert status.enum_values == PRODUCT_STATUS_LEDGER

    def test_product_sku_has_no_phantom_attributes(self, ontology):
        """`product_skus` 表与 `ProductSku.java` 都无 attributes ⇒ 该属性已删除（不得复活）。"""
        assert "attributes" not in ontology.objects["product_sku"].properties

    def test_aftersales_uses_the_real_field_name(self, ontology):
        """真实字段名 = `ticket_type` / `ticketType`（DB / Java / Agent 三端一致）。"""
        props = ontology.objects["aftersales"].properties
        assert "type" not in props
        assert props["ticket_type"].source == "AfterSalesTicket.ticketType"

    def test_customer_sources_match_customer_profiles(self, ontology):
        """`customer_profiles` 无 name/address/user_id ⇒ 三个属性改指真实列。"""
        props = ontology.objects["customer"].properties
        assert props["wechat_nickname"].source == "CustomerProfile.wechatNickname"
        assert props["wechat_openid"].source == "CustomerProfile.wechatOpenid"
        assert (
            props["default_receiver_address"].source
            == "CustomerProfile.defaultReceiverAddress"
        )
        assert {"name", "address", "user_id"} & set(props) == set()


class TestProcessingItemFeeRule:
    """issue #5245 B5：V101 已删加工项单价/计价方式 ⇒ 规则文本不得再引用加工项单价。"""

    def test_rule_points_at_the_fee_combination_truth_source(self, ontology):
        rules = [r.text for r in ontology.objects["processing_item"].rules]
        assert not any("加工项单价" in t for t in rules)
        assert any("加工费组合" in t for t in rules)


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