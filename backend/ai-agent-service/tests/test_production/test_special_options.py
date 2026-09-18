# case_ids: PP-013
"""特殊选项 → 条件工序 / 计件系数（issue #4230，v1a-PY 半边）

真值源 `docs/curtain-production-rules.md` §1【默】特殊选项清单（19 项，下单勾选，
影响用料/工序/计件系数）+ §4「条件系数表：特殊选项 → 工序 → 系数（如 一分二 ×1.7）」。

本单治的病：19 项里只有 9 项在 `SPECIAL_OPTION_ROUTINGS` 里有映射 ⇒ 另外 10 项
**既不加工序、也不加系数、也没有任何登记** —— 「忘了映射」与「本来就不计件」在数据上
**长得一模一样**（都是 `.get(opt)` 返回 None 的静默黑洞）。本文件把三类登记变成
**会红的测试**：19 项中的每一项都必须落在「加工序 / 加系数 / 不计件」三类之一，
**不允许有第四类「未登记」**（`TestCriterion1CoverageGate`）。

v1 边界（issue #4230 §2.4，**刻意不做**）：
- 只种「一分二 ×1.7」一个系数档（唯一的**实证**值，行业 ERP）；按工序/分组细算出的
  系数（车位 ≈×2.0 / 后道 ×1.0 / 裁剪 ×1.2）是**推算**，v1 不启用 ⇒ 本文件不断言推算值；
- 系数结构保留 `operation_name` 档位（`None` = 该部位全部工序）—— 用「以限定值构造」
  的用例证明该档位**可用**（`test_operation_scoped_factor_applies_to_that_operation_only`），
  而不是只留一个空壳字段。

红证（实现前逐条红，红因已核）：
- 判据 1：10 个未登记选项 ⇒ `test_every_truth_source_option_is_registered` 红（列名点名）；
- 判据 2：5 道新工序不在 `OPERATION_CATALOG` ⇒ `test_new_operations_are_in_catalog` KeyError；
- 判据 3：`布绑带`/`余料做帘头`/`抱枕` 无映射 ⇒ 路线里根本没有该工序 ⇒ 断言红；
- 判据 4：`OPTION_FACTOR_SCOPES` 未定义 ⇒ import 即红（Collection Error）；
- 判据 5：`余料带回(布)` 未登记为不计件 ⇒ 判据 1 红（同一条门禁覆盖）。
"""

import pytest

from app.production.routing import (
    NON_PIECEWORK_OPTIONS,
    OPERATION_CATALOG,
    OPTION_FACTOR_SCOPES,
    SPECIAL_OPTION_ROUTINGS,
    build_routing,
    instance_operations,
)

# 真值源 §1【默】特殊选项清单 —— **逐字**抄录（19 项）。
# 单一源在 `docs/curtain-production-rules.md` §1；本清单是它的**测试侧快照**，
# 真值源增删选项而此处不跟 ⇒ 判据 1 的红会点名差异（不是静默漂移）。
TRUTH_SOURCE_OPTIONS = [
    "余料带回(布)", "余料带回(纱)", "布绑带", "纱绑带", "加logo条", "加立边",
    "加花边", "拼1次", "拼2次", "拼3次", "加铅块", "接高", "双眼皮接高",
    "扣环", "抱枕", "防翘扣", "一分二", "余料做绑带", "余料做帘头",
]

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

    def test_option_registered_in_exactly_one_category(self):
        """三类互斥：一个选项不得既加工序又加系数（v1 口径，避免双重计费）。"""
        both = [
            opt for opt in TRUTH_SOURCE_OPTIONS
            if SPECIAL_OPTION_ROUTINGS.get(opt, {}).get("operation")
            and opt in OPTION_FACTOR_SCOPES
        ]
        assert both == []

    def test_registry_has_no_option_outside_truth_source(self):
        """反向门禁：登记表里不得有真值源之外的选项（拼错名字 ⇒ 静默失效）。"""
        registered = (
            set(SPECIAL_OPTION_ROUTINGS) | set(OPTION_FACTOR_SCOPES) | set(NON_PIECEWORK_OPTIONS)
        )
        assert registered - set(TRUTH_SOURCE_OPTIONS) == set()

    def test_non_piecework_options_are_exactly_the_leftover_returns(self):
        """C 类显式登记：只是把余料还给客户，不增加车间工序 ⇒ 不计件。"""
        assert NON_PIECEWORK_OPTIONS == {"余料带回(布)", "余料带回(纱)"}

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
# 判据 4：系数结构 —— v1 唯一档「一分二 ⇒ 全部工序 ×1.7」+ operation_name 档位可用
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion4FactorScope:

    def test_v1_seeds_only_the_empirical_factor(self):
        """v1 只种「一分二 ⇒ 1.7 / 该部位全部工序」（唯一实证值；推算值不启用）。"""
        assert len(OPTION_FACTOR_SCOPES) == 1
        (scope,) = OPTION_FACTOR_SCOPES["一分二"]
        assert scope["factor"] == 1.7
        assert scope["operation_name"] is None
        assert scope["curtain_type"] is None

    def test_one_split_applies_factor_to_every_operation(self):
        """一分二 ⇒ 该部位每道工序实例 factor = 1.7，且不插工序。"""
        insts = instance_operations({**POSITION, "special_options": ["一分二"]}, CALC)
        assert [i["factor"] for i in insts] == [1.7] * 11
        assert all(i["operation"] != "一分二" for i in insts)

    def test_no_option_factor_is_one(self):
        """不带选项 ⇒ factor 恒 1.0（逐值）。"""
        insts = instance_operations(POSITION, CALC)
        assert [i["factor"] for i in insts] == [1.0] * 11

    def test_operation_scoped_factor_applies_to_that_operation_only(self):
        """`operation_name` 限定档位**可用**：只作用于点名的工序（v1 种子不用它）。

        构造方式 = 临时给「一分二」追加一个限定档（布三边 ×2.0），断言只有 `布三边` 生效、
        其余工序仍为平摊档 1.7 ⇒ 证明结构支持「逐工序系数」，而不是只留一个无人消费的空壳字段。
        """
        scope = OPTION_FACTOR_SCOPES["一分二"]
        scoped = {"factor": 2.0, "operation_name": "布三边", "curtain_type": None,
                  "source": "推算"}
        scope.append(scoped)
        try:
            by_op = _by_op(["一分二"])
        finally:
            scope.remove(scoped)
        assert by_op["布三边"]["factor"] == 2.0          # 限定档覆盖平摊档（不是相乘）
        assert by_op["韩褶-布"]["factor"] == 1.7
        assert by_op["外帘装袋"]["factor"] == 1.7

    def test_curtain_type_scoped_factor_applies_to_that_position_only(self):
        """`curtain_type` 限定档位可用：只在点名的部位生效（如只对布帘乘系数）。"""
        scope = OPTION_FACTOR_SCOPES["一分二"]
        scoped = {"factor": 1.5, "operation_name": None, "curtain_type": "布帘",
                  "source": "推算"}
        scope.append(scoped)
        try:
            on_cloth = instance_operations({**POSITION, "special_options": ["一分二"]}, CALC)
            on_silk = instance_operations(
                {**POSITION, "curtain_type": "纱帘", "craft": "韩褶",
                 "special_options": ["一分二"]}, CALC)
        finally:
            scope.remove(scoped)
        assert [i["factor"] for i in on_cloth] == [1.5] * 11          # 部位命中 ⇒ 限定档生效
        assert [i["operation"] for i in on_silk] == [
            "精裁-纱", "纱三边", "韩褶-纱", "外帘打卷", "外帘装袋", "外帘发货",
        ]
        assert [i["factor"] for i in on_silk] == [1.7] * 6            # 部位不命中 ⇒ 回落平摊档

    def test_factor_multiplies_across_independent_options(self):
        """**两个**加系数选项并存 ⇒ 系数相乘（独立倍率的合成口径；v1 只种一个档）。"""
        fake = "_测试用选项"
        OPTION_FACTOR_SCOPES[fake] = [
            {"factor": 2.0, "operation_name": None, "curtain_type": None, "source": "推算"}]
        try:
            by_op = _by_op(["一分二", fake])
        finally:
            OPTION_FACTOR_SCOPES.pop(fake, None)
        assert by_op["韩褶-布"]["factor"] == pytest.approx(3.4)

    def test_unknown_option_does_not_change_factor(self):
        """未登记的选项名不得悄悄改系数（v1 口径：只认登记表）。"""
        insts = instance_operations({**POSITION, "special_options": ["不存在选项"]}, CALC)
        assert [i["factor"] for i in insts] == [1.0] * 11


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：C 类（不计件）显式 —— 路线不变、factor 仍 1.0
# ══════════════════════════════════════════════════════════════════════════

class TestCriterion5NonPiecework:

    @pytest.mark.parametrize("option", ["余料带回(布)", "余料带回(纱)"])
    def test_leftover_return_changes_nothing(self, option):
        """余料带回 ⇒ 路线逐值不变、factor 逐值仍 1.0（**不是因为查不到映射**）。"""
        route = _route([option])
        assert route == BASE_ROUTE
        assert [i["factor"] for i in instance_operations(
            {**POSITION, "special_options": [option]}, CALC)] == [1.0] * 11

    def test_leftover_return_is_registered_not_silent(self):
        """显式登记（而不是 `.get()` 返回 None 的静默黑洞）—— 这是判据 5 的判据本体。"""
        assert "余料带回(布)" in NON_PIECEWORK_OPTIONS
        assert "余料带回(纱)" in NON_PIECEWORK_OPTIONS
        assert "余料带回(布)" not in SPECIAL_OPTION_ROUTINGS
        assert "余料带回(布)" not in OPTION_FACTOR_SCOPES


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
        assert [i["factor"] for i in insts] == [1.0] * 11
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
