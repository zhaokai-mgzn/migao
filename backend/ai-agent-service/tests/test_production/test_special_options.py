# case_ids: PP-013
"""特殊选项 → 条件工序 / 计件系数（issue #4230，v1a-PY 半边）

真值源 `docs/curtain-production-rules.md` §1【默】特殊选项清单（19 项，下单勾选，
影响用料/工序/计件系数）+ §4「条件系数表：特殊选项 → 工序 → 系数（如 一分为二 ×1.7）」。

本单治的病：19 项里只有 9 项在 `SPECIAL_OPTION_ROUTINGS` 里有映射 ⇒ 另外 10 项
**既不加工序、也不加系数、也没有任何登记** —— 「忘了映射」与「本来就不计件」在数据上
**长得一模一样**（都是 `.get(opt)` 返回 None 的静默黑洞）。本文件把三类登记变成
**会红的测试**：19 项中的每一项都必须落在「加工序 / 加系数 / 不计件」三类之一，
**不允许有第四类「未登记」**（`TestCriterion1CoverageGate`）。

#4589 改判（用户裁定 2026-09-19：「计件工资 = 数量 × 计件单价，不需要考虑系数」）：
- `routing.py::factor_for` 已删除，工序实例**不再带 `factor` 键**；
- `OPTION_FACTOR_SCOPES` **保留**（它是 V59/V72 **已发布**迁移种子与 `schema.sql` 终态的
  真值源镜像，三源收敛守卫依赖它），但自本单起**零消费** —— 本文件用「注入限定档后
  实例逐值不变」证明它对运行期**没有任何影响**（见 `TestCriterion4FactorScope`）。

#4604 口径（用户裁定 B：**不追溯**）：系数只从**新报工**退场，**历史实例**仍按**当时快照**的
系数继续算（历史金额一字不变）。⇒ 判据 4 的「零消费」只针对**下单流程**（`routing.py` 不写
`factor`）；`compute_piecework` 对**带 `factor` 的历史实例**仍必须乘 —— 见
`TestCriterion7ErpNameAlignment::test_erp_name_money_halves_are_split_by_snapshot` 的历史半边。

红证（实现前逐条红，红因已核）：
- 判据 1：10 个未登记选项 ⇒ `test_every_truth_source_option_is_registered` 红（列名点名）；
- 判据 2：5 道新工序不在 `OPERATION_CATALOG` ⇒ `test_new_operations_are_in_catalog` KeyError；
- 判据 3：`布绑带`/`余料做帘头`/`抱枕` 无映射 ⇒ 路线里根本没有该工序 ⇒ 断言红；
- 判据 4：`OPTION_FACTOR_SCOPES` 未定义 ⇒ import 即红（Collection Error）；
- 判据 5：`余料带回-布` 未登记为不计件 ⇒ 判据 1 红（同一条门禁覆盖）。
"""

import pytest

from app.production.routing import (
    NON_PIECEWORK_OPTIONS,
    OPERATION_CATALOG,
    OPTION_FACTOR_SCOPES,
    PENDING_CUSTOMER_CONFIRMATION_OPTIONS,
    SPECIAL_OPTION_ROUTINGS,
    build_routing,
    instance_operations,
)

# 真值源 §1【默】特殊选项清单 —— **逐字**抄录（19 项），选项名 = **ERP 名**（issue #4389 裁定 R-e）。
# 单一源在 `docs/curtain-production-rules.md` §1；本清单是它的**测试侧快照**，
# 真值源增删选项而此处不跟 ⇒ 判据 1 的红会点名差异（不是静默漂移）。
TRUTH_SOURCE_OPTIONS = [
    "余料带回-布", "余料带回-纱", "布绑带", "纱绑带", "加logo条", "加立边",
    "加花边", "拼1次", "拼2次", "拼3次", "加铅块", "接高", "双眼皮接高",
    "扣环", "抱枕", "防翘扣", "一分为二", "余料做绑带", "余料做帘头",
]

# ERP 截图实证、但**不在**真值源 §1 的 19 项清单里的选项（issue #4389 判据 2）。
# `余料带回`（无后缀）是 ERP 的第三种形态；§1 只列了 `余料带回-布/-纱` ⇒ 它该归三类中的
# 哪一类**无真值源依据**（只有截图）⇒ 登记在 `PENDING_CUSTOMER_CONFIRMATION_OPTIONS`
# 等客户确认，**不猜**、也不让它落进静默黑洞。
ERP_ONLY_OPTIONS = ["余料带回"]

# 布帘·韩褶基准走线（真值源 §3，行业实证 11 道）
BASE_ROUTE = [
    "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
    "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
]

POSITION = {
    "curtain_type": "布帘",
    "craft": "韩褶",
    "is_shaped": True,
    "special_options": [],
    "open_count": 2,
}
CALC = {"pleat_count": 48, "fabric_meters": 12.3, "panels": 4, "holes": 72,
        "set_count": 1, "source": "formula"}

# A′ 类新增 5 道工序：选项 → (工序名, 分组, 单位, 单价)
NEW_OPERATIONS = {
    "纱绑带": ("绑带-纱", "其他", "套", 0.5),
    "加logo条": ("logo条-布", "车位", "米", 0.6),
    "加立边": ("立边-布", "车位", "米", 0.5),
    "扣环": ("扣环-布", "车位", "个", 0.3),
    "防翘扣": ("防翘扣-布", "车位", "个", 0.2),
}


def _route(options):
    return build_routing({**POSITION, "special_options": options})


def _by_op(options, calc=None):
    insts = instance_operations({**POSITION, "special_options": options}, calc or CALC)
    return {i["operation"]: i for i in insts}


# ══════════════════════════════════════════════════════════════════════════
# 判据 1（本单最重要的结构判据）：19 项全覆盖门禁 —— 不留「未登记」第四类
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion1CoverageGate:

    def test_truth_source_option_list_is_nineteen(self):
        """前置自断言：清单本身就是真值源 §1 的 19 项（清单漏项 ⇒ 门禁空跑）。"""
        assert len(TRUTH_SOURCE_OPTIONS) == 19
        assert len(set(TRUTH_SOURCE_OPTIONS)) == 19

    def test_every_truth_source_option_is_registered(self):
        """**19 项每一项**都必须落在「加工序 / 加系数 / 不计件」三类之一。

        三类 = `SPECIAL_OPTION_ROUTINGS[opt]["operation"]` / `OPTION_FACTOR_SCOPES[opt]`
        / `NON_PIECEWORK_OPTIONS`。缺任一登记 ⇒ 点名列出（实现前这里列出 10 个选项）。
        """
        unregistered = [
            opt for opt in TRUTH_SOURCE_OPTIONS
            if not (
                SPECIAL_OPTION_ROUTINGS.get(opt, {}).get("operation")
                or opt in OPTION_FACTOR_SCOPES
                or opt in NON_PIECEWORK_OPTIONS
            )
        ]
        assert unregistered == [], (
            f"这些真值源选项既没加工序、也没加系数、也没登记为不计件（静默黑洞）: {unregistered}"
        )

    def test_every_erp_only_option_is_explicitly_registered(self):
        """§1 之外的 ERP 实证选项（`余料带回`）同样**不得零登记**（issue #4389 判据 2）。

        第四类「**待客户确认**」（`PENDING_CUSTOMER_CONFIRMATION_OPTIONS`）不是「未登记」：
        它是一份**显式**的登记，语义 = 「已知其存在、尚未定论归哪一类」——
        与 `.get(opt) → None` 的静默黑洞在数据上**可区分**。
        """
        unregistered = [opt for opt in ERP_ONLY_OPTIONS
                        if opt not in PENDING_CUSTOMER_CONFIRMATION_OPTIONS]
        assert unregistered == [], (
            f"ERP 实证但 §1 未列的选项既没登记进三类、也没进待确认集合（静默黑洞）: {unregistered}"
        )

    def test_option_registered_in_exactly_one_category(self):
        """三类互斥：一个选项不得既加工序又加系数（v1 口径，避免双重计费）。"""
        both = [
            opt for opt in TRUTH_SOURCE_OPTIONS
            if SPECIAL_OPTION_ROUTINGS.get(opt, {}).get("operation")
            and opt in OPTION_FACTOR_SCOPES
        ]
        assert both == []

    def test_registry_has_no_option_outside_truth_source(self):
        """反向门禁：登记表里不得有真值源之外的选项（拼错名字 ⇒ 静默失效）。

        「真值源」= §1 的 19 项 ∪ ERP 实证但 §1 未列的 `ERP_ONLY_OPTIONS`（issue #4389）。
        """
        known = set(TRUTH_SOURCE_OPTIONS) | set(ERP_ONLY_OPTIONS)
        registered = (
            set(SPECIAL_OPTION_ROUTINGS) | set(OPTION_FACTOR_SCOPES)
            | set(NON_PIECEWORK_OPTIONS) | set(PENDING_CUSTOMER_CONFIRMATION_OPTIONS)
        )
        assert registered - known == set()

    def test_non_piecework_options_are_exactly_the_leftover_returns(self):
        """C 类显式登记：只是把余料还给客户，不增加车间工序 ⇒ 不计件（键 = ERP 名）。"""
        assert NON_PIECEWORK_OPTIONS == {"余料带回-布", "余料带回-纱"}

    def test_every_mapped_operation_exists_in_catalog(self):
        """映射指向的工序必须在工序库里（否则 `instance_operations` 会 KeyError）。"""
        missing = [
            opt for opt, rule in SPECIAL_OPTION_ROUTINGS.items()
            if rule.get("operation") and rule["operation"] not in OPERATION_CATALOG
        ]
        assert missing == []


# ══════════════════════════════════════════════════════════════════════════
# 判据 2：A′ 类 5 道新工序已入库（分组/单位/单价齐全）+ 有映射指向它们
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion2NewOperations:

    @pytest.mark.parametrize("option", sorted(NEW_OPERATIONS))
    def test_new_operations_are_in_catalog(self, option):
        operation, group, unit, unit_price = NEW_OPERATIONS[option]
        assert OPERATION_CATALOG[operation] == {
            "group": group, "unit": unit, "unit_price": unit_price,
        }

    @pytest.mark.parametrize("option", sorted(NEW_OPERATIONS))
    def test_new_operations_have_mapping(self, option):
        operation = NEW_OPERATIONS[option][0]
        assert SPECIAL_OPTION_ROUTINGS[option]["operation"] == operation

    def test_new_operation_inserted_after_anchor(self):
        """新工序经 build_routing 真的插进路线（纱绑带 插在 布帘车被 之后）。"""
        route = _route(["纱绑带"])
        assert route.index("绑带-纱") == route.index("布帘车被") + 1

    def test_new_operations_carry_their_own_unit_price(self):
        """单价/单位随工序实例下发（不是选项侧的占位值）。"""
        insts = _by_op(["加logo条", "扣环"])
        assert insts["logo条-布"]["unit"] == "米"
        assert insts["logo条-布"]["unit_price"] == 0.6
        assert insts["扣环-布"]["unit"] == "个"
        assert insts["扣环-布"]["unit_price"] == 0.3


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：A 类三条复用映射 —— 真的插进路线，且锚点位置正确
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion3ReusedOperations:

    def test_bu_bangdai_after_curtain_quilted(self):
        """布绑带 → 绑带-布，插在 布帘车被 之后（即 外帘打卷 之前）。"""
        route = _route(["布绑带"])
        assert route == [
            "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布", "定型-布",
            "复烫-布", "布帘车被", "绑带-布", "外帘打卷", "外帘装袋", "外帘发货",
        ]
        assert route.index("绑带-布") == route.index("布帘车被") + 1
        assert route.index("绑带-布") == route.index("外帘打卷") - 1

    def test_yuliao_liantou_after_three_sides(self):
        """余料做帘头 → 帘头制作，插在 布三边 之后。"""
        route = _route(["余料做帘头"])
        assert route.index("帘头制作") == route.index("布三边") + 1
        assert route == [
            "精裁-布", "布三边", "帘头制作", "韩褶-布", "上车布-布", "熨烫-布",
            "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
        ]

    def test_baozhen_inserted_before_wrapping(self):
        """抱枕 → 抱枕，插在 外帘打卷 之后（打卷之后、装袋之前）。"""
        route = _route(["抱枕"])
        assert route.index("抱枕") == route.index("外帘打卷") + 1
        assert route.index("抱枕") == route.index("外帘装袋") - 1

    def test_reused_operations_absent_without_option(self):
        """不带选项时三道复用工序都不出现（判据 6 的选项侧形态）。"""
        route = _route([])
        for operation in ("绑带-布", "帘头制作", "抱枕"):
            assert operation not in route

    def test_reused_operations_have_quantity_and_price(self):
        """复用工序的应做数量/单价随实例下发（数量仍走 `_qty_for`，无第二份算料逻辑）。

        ⚠️ 越界发现（不在本单范围，未顺手改）：「个」类工序（帘头制作/抱枕/腰靠垫）不在
        `KNOWN_QTY_UNITS` 里，而 `_qty_for` 对未声明单位**回落「米」分支** ⇒ 拿到的是用料
        米数（12.3）而不是「个」的口径。本条按**现状**断言并显式标注，避免把缺陷固化成
        「正确值」（同族口径见 tests/test_production/test_operation_qty.py 的
        `test_unknown_unit_ops_are_fallback`）。
        """
        insts = _by_op(["布绑带", "余料做帘头", "抱枕"])
        assert insts["绑带-布"]["qty"] == 1.0        # 套：引擎待补键 ⇒ 兜底 1
        assert insts["绑带-布"]["unit_price"] == 0.5
        assert insts["帘头制作"]["qty"] == CALC["fabric_meters"]   # 个：未声明单位 ⇒ 回落米口径
        assert insts["帘头制作"]["unit_price"] == 2.0
        assert insts["抱枕"]["unit_price"] == 2.0


# ══════════════════════════════════════════════════════════════════════════
# 判据 4（#4589 改判）：系数已从算法退场 —— 真值源表保留、运行期**零消费**
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion4FactorScope:

    def test_historical_factor_truth_source_is_still_the_migration_seed(self):
        """`OPTION_FACTOR_SCOPES` 是**历史真值源**（V59/V72 已发布迁移种子 + schema.sql 终态的镜像）。

        #4589 之后它**零消费**（`factor_for` 已删），但**不能删**：三源收敛守卫
        （`tests/unit_ci_workflows/test_production_catalog_seed.py`）按它比对**已发布**迁移的种子
        —— 删了它 = 删守卫（守卫只能靠删断言才绿，那是停手信号，不是修法）。
        """
        assert len(OPTION_FACTOR_SCOPES) == 1
        (scope,) = OPTION_FACTOR_SCOPES["一分为二"]
        assert scope["factor"] == 1.7
        assert scope["operation_name"] is None
        assert scope["curtain_type"] is None

    def test_one_split_no_longer_changes_instances(self):
        """「一分为二」命中真值源档位 ⇒ 工序实例**逐值不变**、且**没有 `factor` 键**。

        红证（改前）：`instance_operations` 落 `"factor": factor_for(...)` = 1.7 ⇒
        `"factor" not in i` 对 11 道工序**逐条红**。
        """
        with_option = instance_operations({**POSITION, "special_options": ["一分为二"]}, CALC)
        without = instance_operations(POSITION, CALC)
        assert [i["operation"] for i in with_option] == [i["operation"] for i in without]
        assert all("factor" not in i for i in with_option)
        assert [(i["qty"], i["unit_price"]) for i in with_option] == \
               [(i["qty"], i["unit_price"]) for i in without]

    def test_no_option_instances_carry_no_factor_key(self):
        """不带选项 ⇒ 实例同样**没有 `factor` 键**（不是「恒 1.0」—— 这个概念不在实例里了）。"""
        insts = instance_operations(POSITION, CALC)
        assert all("factor" not in i for i in insts)

    def test_factor_scopes_are_inert_even_when_extended(self):
        """**零消费判据**：往真值源注入逐工序限定档（布三边 ×2.0）⇒ 实例**逐值不变**。

        改前：限定档生效 ⇒ `布三边` 的 factor = 2.0、其余 1.7。改后：没有任何读者。
        """
        scope = OPTION_FACTOR_SCOPES["一分为二"]
        scoped = {"factor": 2.0, "operation_name": "布三边", "curtain_type": None,
                  "source": "推算"}
        scope.append(scoped)
        try:
            by_op = _by_op(["一分为二"])
            without = _by_op([])
        finally:
            scope.remove(scoped)
        assert all("factor" not in i for i in by_op.values())
        assert {k: (v["qty"], v["unit_price"]) for k, v in by_op.items()} == \
               {k: (v["qty"], v["unit_price"]) for k, v in without.items()}

    def test_curtain_type_scoped_factor_is_inert_too(self):
        """部位限定档同样零消费（注入「布帘 ×1.5」⇒ 布帘/纱帘两侧实例都不变）。"""
        scope = OPTION_FACTOR_SCOPES["一分为二"]
        scoped = {"factor": 1.5, "operation_name": None, "curtain_type": "布帘",
                  "source": "推算"}
        scope.append(scoped)
        try:
            on_cloth = instance_operations({**POSITION, "special_options": ["一分为二"]}, CALC)
            on_silk = instance_operations(
                {**POSITION, "curtain_type": "纱帘", "craft": "韩褶",
                 "special_options": ["一分为二"]}, CALC)
        finally:
            scope.remove(scoped)
        assert all("factor" not in i for i in on_cloth)
        # 🔴 issue #4937：`ROUTINGS` 去部位化 ⇒ 纱帘取**布帘那一行**（工艺 `韩褶` 的权威序列）
        # —— 旧期望 `精裁-纱/纱三边/韩褶-纱…`（纱帘专属行）随基线退休。
        assert [i["operation"] for i in on_silk] == [
            "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
            "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
        ], (
            "纱帘×韩褶 的实例序列 ≠ 工艺 `韩褶` 的基准序列 ⇒ 部位仍在参与取路"
            "（issue #4937：部位不再参与任何取价、取路、筛选、配置）")
        assert all("factor" not in i for i in on_silk)

    def test_independent_options_no_longer_multiply(self):
        """**两个**「加系数」选项并存 ⇒ 不再相乘（系数概念已退场；逐值不变）。"""
        fake = "_测试用选项"
        OPTION_FACTOR_SCOPES[fake] = [
            {"factor": 2.0, "operation_name": None, "curtain_type": None, "source": "推算"}]
        try:
            by_op = _by_op(["一分为二", fake])
        finally:
            OPTION_FACTOR_SCOPES.pop(fake, None)
        assert all("factor" not in i for i in by_op.values())
        assert by_op["韩褶-布"]["unit_price"] == 0.4

    def test_unknown_option_does_not_change_instances(self):
        """未登记的选项名同样不改实例（系数路径已不存在 ⇒ 逐值不变）。"""
        insts = instance_operations({**POSITION, "special_options": ["不存在选项"]}, CALC)
        assert all("factor" not in i for i in insts)
        assert [i["operation"] for i in insts] == BASE_ROUTE


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：C 类（不计件）显式 —— 路线不变、实例无 factor 键
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion5NonPiecework:

    @pytest.mark.parametrize("option", ["余料带回-布", "余料带回-纱"])
    def test_leftover_return_changes_nothing(self, option):
        """余料带回 ⇒ 路线逐值不变、实例逐值不变（**不是因为查不到映射**）。"""
        route = _route([option])
        assert route == BASE_ROUTE
        insts = instance_operations({**POSITION, "special_options": [option]}, CALC)
        assert [i["operation"] for i in insts] == BASE_ROUTE
        assert all("factor" not in i for i in insts)

    def test_leftover_return_is_registered_not_silent(self):
        """显式登记（而不是 `.get()` 返回 None 的静默黑洞）—— 这是判据 5 的判据本体。"""
        assert "余料带回-布" in NON_PIECEWORK_OPTIONS
        assert "余料带回-纱" in NON_PIECEWORK_OPTIONS
        assert "余料带回-布" not in SPECIAL_OPTION_ROUTINGS
        assert "余料带回-布" not in OPTION_FACTOR_SCOPES


# ══════════════════════════════════════════════════════════════════════════
# 判据 6：不回归 —— 无选项时路线与改动前逐值相同
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion6NoRegression:

    def test_empty_options_route_is_unchanged(self):
        assert _route([]) == BASE_ROUTE

    def test_empty_options_instances_are_unchanged(self):
        insts = instance_operations(POSITION, CALC)
        assert [i["operation"] for i in insts] == BASE_ROUTE
        assert [i["seq"] for i in insts] == list(range(1, 12))
        assert all("factor" not in i for i in insts)
        assert [i["qty"] for i in insts] == [
            12.3, 12.3, 48.0, 12.3, 12.3, 12.3, 12.3, 12.3, 1.0, 1.0, 1.0,
        ]

    def test_existing_nine_options_still_map(self):
        """存量 9 项映射逐条不回退（本单只增不改）。"""
        assert SPECIAL_OPTION_ROUTINGS["拼1次"] == {"operation": "拼1次-布", "after": "布三边"}
        assert SPECIAL_OPTION_ROUTINGS["拼2次"] == {"operation": "拼2次-布", "after": "布三边"}
        assert SPECIAL_OPTION_ROUTINGS["拼3次"] == {"operation": "拼3次-布", "after": "布三边"}
        assert SPECIAL_OPTION_ROUTINGS["加花边"] == {"operation": "花边-布", "after": "布三边"}
        assert SPECIAL_OPTION_ROUTINGS["加铅块"] == {"operation": "铅坠-布", "after": "布三边"}
        assert SPECIAL_OPTION_ROUTINGS["接高"] == {"operation": "接高-布", "after": "精裁-布"}
        assert SPECIAL_OPTION_ROUTINGS["双眼皮接高"] == {"operation": "接高-布", "after": "精裁-布"}
        assert SPECIAL_OPTION_ROUTINGS["余料做绑带"] == {"operation": "绑带-布", "after": "布帘车被"}
        assert SPECIAL_OPTION_ROUTINGS["布绑带"] == {"operation": "绑带-布", "after": "布帘车被"}


# ══════════════════════════════════════════════════════════════════════════
# 判据 7（issue #4389）：特殊选项名**逐字对齐行业 ERP**（join key，错一个字静默失效）
#
# 真值源 = 用户提供的行业 ERP 订单录入页截图（2026-09-19，与真值源 §1 同源系统）+ 用户裁定
# R-e「以 ERP 为准改」。特殊选项名是「订单选配 → 车间工序 / 计件系数」的 join key，
# 改的是**工人工资**，故每条都要有红证。
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion7ErpNameAlignment:
    """判据 7：三张表的键 = ERP 名；第三种 `余料带回`（无后缀）显式登记。

    红证（修复前逐条实测，见 PR body）：
    - 判据 1：`OPTION_FACTOR_SCOPES` 的键是 `一分二`，而 ERP 名是 `一分为二` ⇒
      `test_erp_name_no_longer_reaches_the_money` 的前身（当时断言「命中 ×1.7」）红
      （factor 静默退回 1.0 = 少发工人钱）；
    - 判据 2：`NON_PIECEWORK_OPTIONS` 只有 `余料带回(布)/(纱)` 两种旧写法 ⇒
      `test_leftover_return_erp_names_are_registered` 红；第三种 `余料带回`（无后缀）**零登记** ⇒
      `test_third_leftover_return_is_explicitly_registered` 红（落进静默黑洞）。

    #4589/#4604 起「进了钱」这条拆成**两半**（用户裁定 B 不追溯）：新实例不再带系数（半边 ①），
    # 历史实例仍按当时快照的系数算（半边 ②）—— 两半都钉，缺任一半都会让口径漂移。
    """

    def test_erp_name_one_split_into_two_no_longer_applies_factor(self):
        """判据 1（#4589 改判）：用 ERP 名 `一分为二` 走一遍 ⇒ 实例**逐值不变、无 `factor` 键**。

        改前：ERP 名命中 `OPTION_FACTOR_SCOPES` ⇒ 每道工序 factor = 1.7。改后：系数已退场。
        """
        with_option = instance_operations({**POSITION, "special_options": ["一分为二"]}, CALC)
        assert all("factor" not in i for i in with_option)
        assert all(i["operation"] != "一分为二" for i in with_option)
        assert [i["operation"] for i in with_option] == BASE_ROUTE

    def test_erp_name_money_halves_are_split_by_snapshot(self):
        """判据 1 的「进了钱」半边（#4604 改判，用户裁定 B 不追溯）—— 两半都断言：

        ① **新实例**（`instance_operations` 产出，**无 `factor` 键**）⇒ 系数缺省 1 ⇒ 合计 = 不带选项；
        ② **历史实例**（当时快照 `factor=1.7`）⇒ 合计 = 不带选项的 **1.7 倍**（历史金额一字不变）。

        红证（main 实测）：实现里两处都不乘系数 ⇒ 历史半边期望 1.7 倍而实测 1.0 倍 ⇒ 红。
        """
        from app.production.piecework import compute_piecework
        plain = instance_operations(POSITION, CALC)
        with_erp = instance_operations({**POSITION, "special_options": ["一分为二"]}, CALC)
        logs = [{"operation": i["operation"], "worker": "李红梅", "qty": i["qty"],
                 "qualified_qty": i["qty"], "type": "normal"} for i in plain]
        base = compute_piecework(plain, logs)["total"]
        assert base > 0, "前置自断言：合计必须非 0（否则比值判据空跑）"
        # ① 新实例：无 `factor` 键 ⇒ 缺省 1 ⇒ 与不带选项一致
        assert compute_piecework(with_erp, logs)["total"] == pytest.approx(base, abs=0.01), \
            "新实例（无 factor 键）⇒ 系数缺省 1，不得再改变计件合计"
        # ② 历史实例：当时快照 1.7 ⇒ 仍按 1.7 倍计（不追溯）
        historical = [{**i, "factor": 1.7} for i in plain]
        assert compute_piecework(historical, logs)["total"] == pytest.approx(base * 1.7, abs=0.05), \
            "历史实例（快照 factor=1.7）⇒ 计件合计必须仍是 1.7 倍（issue #4604 不追溯）"

    def test_registry_keys_are_exactly_the_erp_names(self):
        """判据 1/2 的**注册表键**半边：三张表的键里不得残留旧写法。

        只钉注册表键（不钉运行期行为）：若将来给存量订单加「旧名 → 新名」的兼容别名层，
        本判据仍成立（别名在查表层，不在注册表键里）—— 逐字对齐的是**真值源键**。
        """
        registered = (set(SPECIAL_OPTION_ROUTINGS) | set(OPTION_FACTOR_SCOPES)
                      | set(NON_PIECEWORK_OPTIONS))
        stale = {"一分二", "余料带回(布)", "余料带回(纱)"} & registered
        assert stale == set(), f"注册表键里残留旧写法（ERP 名才是 join key）: {sorted(stale)}"

    @pytest.mark.parametrize("option", ["余料带回-布", "余料带回-纱"])
    def test_leftover_return_erp_names_are_registered(self, option):
        """判据 2：ERP 写法 `余料带回-布` / `余料带回-纱` 是**显式登记**的不计件项（不是查不到）。"""
        assert option in NON_PIECEWORK_OPTIONS
        assert option not in SPECIAL_OPTION_ROUTINGS
        assert option not in OPTION_FACTOR_SCOPES

    def test_third_leftover_return_is_explicitly_registered(self):
        """判据 2：ERP 的**第三种**形态 `余料带回`（无后缀）必须显式登记（不落静默黑洞）。

        登记在 `PENDING_CUSTOMER_CONFIRMATION_OPTIONS`（**待客户确认**集合）而非
        `NON_PIECEWORK_OPTIONS`：真值源 §1 的 19 项清单里**没有**它（只有 `余料带回(布/纱)`），
        我们手上只有截图这一个证据 ⇒ **不猜**它归哪一类，但**也不让它变成「忘了映射」**。
        """
        assert "余料带回" in PENDING_CUSTOMER_CONFIRMATION_OPTIONS
        # 「不假装已定论」：它不得同时出现在任何一个已定论的三类登记里
        assert "余料带回" not in SPECIAL_OPTION_ROUTINGS
        assert "余料带回" not in OPTION_FACTOR_SCOPES
        assert "余料带回" not in NON_PIECEWORK_OPTIONS

    def test_pending_option_is_not_a_silent_black_hole(self):
        """判据 2 的判别性半边：待确认选项**不加工序、不改系数**（行为同不计件），
        但它在数据上**有名字**（本集合）⇒ 与「忘了映射」可区分。

        判别性：换成**已定论**的不计件项（`余料带回-布`）行为一致、换成**未登记**的假名行为
        也一致 —— 所以「行为一致」不是判据；判据是**登记表里有它**（上一条）+ 本条的行为可预期。
        """
        route = _route(["余料带回"])
        assert route == BASE_ROUTE
        assert all("factor" not in i for i in instance_operations(
            {**POSITION, "special_options": ["余料带回"]}, CALC))

    def test_pending_set_is_disjoint_from_decided_categories(self):
        """待确认集合与三类已定论登记**互斥**（否则「待确认」会被读成「已定论」）。"""
        decided = (set(SPECIAL_OPTION_ROUTINGS) | set(OPTION_FACTOR_SCOPES)
                   | set(NON_PIECEWORK_OPTIONS))
        assert PENDING_CUSTOMER_CONFIRMATION_OPTIONS & decided == set()
