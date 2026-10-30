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

issue #8172 追加（动作要素出库）：
- schema 的「动作段」已删除（原 19 条、其中 13 条指向注册表里不存在的工具）⇒ 能力真值只认 tools registry
- 元守卫 `TestActionsSectionStaysOut`：schema 再出现该键 ⇒ 红（含注入式自证 + 「只改注释不红」的对照读数）

Seam: app.ontology.loader.load_ontology() → Ontology（唯一公共入口，
不触碰内部 models/加载实现细节）。
"""
# case_ids: ON-001

import re

import pytest
import yaml

from app.ontology.loader import (
    DEFAULT_SCHEMA_PATH,
    STATUS_LEXICON,
    OntologySchemaError,
    load_ontology,
)

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
        """每个对象必须有属性/关系/规则三要素（缺一不可）。

        动作要素已于 issue #8172 出库（能力真值在 tools registry）⇒ 这里不再断言它，
        回潮判据由 TestActionsSectionStaysOut 承担。
        """
        for name, obj in ontology.objects.items():
            assert obj.properties, f"{name} 缺属性"
            assert obj.relations is not None, f"{name} 缺关系"
            assert obj.rules, f"{name} 缺规则"
        # 模型侧也钉住：OntologyObject 不得再有 actions 字段（issue #8172 删的是模型，不只是 YAML）
        assert not hasattr(ontology.objects["order"], "actions"), "OntologyObject.actions 应已删除（#8172）"


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


# ── 动作要素已出库（issue #8172）：原句 → 新载体（承重句不许静默丢弃）──────────────────
# schema 原有 19 条动作（7 个对象），本单全部删除。删除前逐条审 description / preconditions：
#
# | 原动作（对象） | 承重的那一句 | 去向（新载体） |
# |---|---|---|
# | order.order_query | 查询订单（B 端 order_query / C 端 customer_order_query） | schema 的 intent_ownership.order_query.description（逐字保留同一句） |
# | order.order_create | 创建订单（写工具确认闸，GB-03） | app/tools/order_create.py 的 requires_confirmation = True；GB-03 定义见 docs/wiki/gb47746-2026-compliance.md |
# | order.order_update | preconditions：action ∈ {update_status, update_logistics, confirm_payment, cancel, refund} | app/tools/order_manage.py 的 VALID_ACTIONS（逐字同集合）+ 工具说明里的 PATCH /api/admin/agent/orders/{id} |
# | product_sku.product_query | 查询商品/SKU（B 端 product / C 端 customer_product） | app/graph/skills/product_skill.py（name=product）与 app/graph/skills/customer_product_skill.py（name=customer_product） |
# | product_sku.product_create | 创建商品（含图片建品属性求证） | app/tools/product_manage.py 的 action=create；「识别 → 求证」范式见 docs/design/agent-clarification-capability-research.md 的 G7 仲裁与 tests/test_prompt_snapshots.py |
# | product_sku.sku_price_update | preconditions：price >= 0 / 单 SKU 改价（PATCH …/skus/{skuId}） | admin-api AgentProductController.updateSkuPriceById → ProductService 的 `price.signum() < 0` 拒绝（负价守卫确实是判据，不只是注释）；工具侧能力 = app/tools/sku_update.py |
# | aftersales.aftersales_create | preconditions：创建恒 pending，由商户审核 | 🔴 **已由 rules 承载**：schema 的 rules 逐字保留「售后申请创建恒 pending，由商户审核；…」（本单不动 rules）；写工具确认闸 = app/tools/aftersale_create.py 的 requires_confirmation = True |
# | aftersales.aftersales_query | C 端强制按本人订单反查 | schema 的 rules「C 端售后查询按 X-User-Id 反查本人订单…」；工具 = app/tools/aftersale_query.py（C 端走 customer_aftersales skill） |
# | aftersales.aftersales_update | 售后处理（B 端） | ⚠️ **无等价载体**：after_sales_manage 只剩 list / detail（B 端写能力已按 #5247 解绑，工具里没有处理动作） |
# | customer.customer_query | 查询客户（B 端 customer_query / C 端仅本人） | 工具 = app/tools/customer_manage.py（list / detail / list_tags / profile_view / value_view）；⚠️ 「C 端仅本人」**无等价载体**（C 端没有客户查询工具，元元侧客户数据由 order_query 按 X-User-Id 兜底） |
# | customer.customer_create | 客户建档（下单自动建档） | admin-api CustomerProfileMapper（建档三写面：下单自动建档 / 手工建档 / 接口重试，撞唯一键不插）；agent 工具层无 create action |
# | employee.employee_manage | 员工管理（查询/新增/状态变更，B 端 staff skill） | app/graph/skills/staff_skill.py（STAFF_TOOLS）；⚠️ 「新增/状态变更」**无等价载体**（#5247 后 B 端员工写面移除，employee_manage 只剩 list/detail） |
# | employee.staff_manage | 人事管理（B 端 staff skill） | app/graph/skills/staff_skill.py（intents 含 staff_manage，STAFF_TOOLS 已只读化）—— 本句只有「技能归属」这一层含义，工具名 staff_manage 从来不存在 |
# | employee.role_manage | 角色管理（分配角色，B 端 staff skill） | 工具 = app/tools/role_manage.py（list / all / detail / list_permissions）；⚠️ 「分配角色」**无等价载体**（#5247 只读化） |
# | employee.permission_manage | 权限管理（B 端 staff skill） | 权限目录**只读**查询 = role_manage 的 action=list_permissions；技能归属 = staff_skill 的 intents 含 permission_manage |
# | processing_item.processing_item_query | 查询加工项（算料） | app/tools/processing_item_query.py（product skill 绑定） |
# | processing_item.processing_manage | 加工项管理（创建/修改，B 端） | app/tools/processing_item_manage.py（create_processing_item / update_item / delete_item / toggle_item_status）；技能 = product skill 的 intents 含 processing_manage |
# | category.category_query | 查询分类 | app/tools/category_manage.py 的 action=tree（工具**只有** tree 一个只读 action） |
# | category.category_manage | 分类管理（创建/修改，B 端 product skill） | 技能归属 = app/graph/skills/product_skill.py；⚠️ **「创建/修改」无等价载体**（category_manage 工具只剩 tree 只读，#5247） |
#
# 标 ⚠️ 的 **6 处**是「原文与现状相反」而不是「少了个载体」：aftersales_update 的售后处理、
# customer_query 的「C 端仅本人」、employee_manage 的「新增/状态变更」、role_manage 的「分配角色」、
# category_manage 的「创建/修改」，再加上 aftersales_update 同族的 B 端写能力 —— 这些写面已按
# #5247（B 端只读化）移出 agent 面。宁可删掉，也不把它搬进任何「看起来有体系」的第二份声明。
# （staff_manage 的工具名不存在属另一类：句子本身只声明技能归属，已由 staff_skill 承载。）

ACTIONS_KEY_RE = re.compile(r"^\s*actions\s*:")


def find_actions_keys(text: str) -> list:
    """返回 schema 文本里出现的动作键（`<行号>: <行内容>`；**注释行不算**）。

    为什么查**原文**而不是只查解析结果：动作段删除后 loader 不再解析它 ⇒ 有人加回去
    **也不会报错**（静默被忽略 —— 正是「看着有、实际没人读」的形态）⇒ 必须直接查源文件。
    """
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if ACTIONS_KEY_RE.match(line):
            hits.append(f"{lineno}: {stripped}")
    return hits


class TestActionsSectionStaysOut:
    """issue #8172：动作段已出库，且不许回潮（元守卫）。"""

    def test_default_schema_has_no_actions_key(self):
        """默认 schema 既不许有动作键，解析结果里也不许有（源文件 + 解析两侧都判）。"""
        text = DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8")
        assert find_actions_keys(text) == [], "schema.yaml 又出现动作键（issue #8172 已出库）"
        data = yaml.safe_load(text)
        offenders = [name for name, obj in data["objects"].items() if "actions" in obj]
        assert offenders == [], f"这些对象又重新声明了动作: {offenders}"

    def test_actions_key_injection_is_detected(self, tmp_path):
        """判别力自证（注入式红证）：把一条动作段灌回 schema 副本 ⇒ 判据必须红并具名行号。

        若这条判据退化成恒绿（比如只看 `OntologyObject` 有没有该属性 —— 而模型已经没有它了），
        这条自证立刻红：它喂的是**另一份带动作段的文本**，不依赖默认 schema 的现状。
        """
        text = DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8")
        anchor = "    relations:\n      - name: has_items"
        injected = text.replace(
            anchor,
            "    actions:\n      - name: ghost_action\n" + anchor,
            1,
        )
        assert injected != text, "注入锚（order.relations）必须命中，否则这条自证是空跑"
        assert len(find_actions_keys(injected)) == 1
        assert "actions:" in find_actions_keys(injected)[0]
        data = yaml.safe_load(injected)
        assert [n for n, o in data["objects"].items() if "actions" in o] == ["order"]

    def test_commented_occurrence_is_not_red(self, tmp_path):
        """对照读数：只有**注释里**提到该键 ⇒ 不红（守卫不许被自己的说明文案喂红）。"""
        text = "# actions: 本键已出库（issue #8172）\n" + DEFAULT_SCHEMA_PATH.read_text(
            encoding="utf-8"
        )
        assert find_actions_keys(text) == []


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