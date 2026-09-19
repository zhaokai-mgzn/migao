# case_ids: PP-010, PG-018
"""工序路线模型 v2 真值源（issue #4427，母单 #4423 的 P1/3）—— **9/9 逐字重建** + 规则/价目自洽。

## 本文件判什么（P1 = 纯增量，运行时行为零变化）

`routing.py` 新增**第二份并存的真值源**（`ROUTE_TEMPLATE_NAME_DEFAULT` / `ROUTE_MAINLINE_STEPS` /
`OPERATION_LOGICAL_NAMES` / `OPERATION_POSITION_PRICES` / `ROUTE_RULES` / `build_route_v2`），
与旧常量（`OPERATION_CATALOG` / `ROUTINGS` / `SPECIAL_OPTION_ROUTINGS`）**一字不动地并存**。
本文件是它的判据，且**判据值全部硬编码在文件内**（不从被测实现推导 —— 否则「实现自洽」就能骗过测试）：

1. **9/9 逐字重建（最重要）**：`build_route_v2` 重建 9 个 `(部位, 工艺)` 组合，与
   ① **冻结期望序列**（母单 #4423 §二 已实证）② **旧 `ROUTINGS` 按 `OPERATION_LOGICAL_NAMES`
   归一后的序列** 三方逐字比对（含顺序）。
2. 逻辑工序名映射 **35 → 28**（7 组部位变体）。
3. 部位价目 **28 × 3 = 84 行**、`applicable` 显式；**不发明任何工序/单价**（每个单价都能溯源到
   `OPERATION_CATALOG`）。
4. 规则表 **26 条** = 工艺变体 10 + 特殊选项 16（16 条 = `SPECIAL_OPTION_ROUTINGS` 逐条搬迁，
   **工序名与锚点都归一为逻辑名** —— `布三边`→`三边`、`布帘车被`→`车被`、`精裁-布`→`精裁`）。
5. 旧常量与旧行为**零变化**（`build_routing` 对同一 9 个组合的输出逐字不变）。

## 红证（「不会红的断言 = 空断言」，见 `TestInjectedDrift`）

五条注入式自证，各自证明一条判据**真能红**：少一条规则 / 规则优先级颠倒 / 规则工序名错 /
部位适用性开关失效 / 逻辑名映射漂移。

## ⚠️ 一处如实登记的规格张力（不是本单引入的 bug，交 P2 决策）

`余料做帘头`（#4230 的**推算**映射）把 `帘头制作` 插进 **布帘/纱帘** 路线，而母单冻结的
部位适用性把 `帘头制作` 限在 `{帘头}` ⇒ 新模型的**部位适用性过滤会把它滤掉**（旧实现不会）。
9/9 重建**不受影响**（那是主线）；差异由
`TestSpecialOptionsRebuild::test_yield_curtain_head_option_is_filtered_by_applicability` 显式钉住，
P2 切换消费路径前必须裁定（要么放开 `帘头制作@布帘` 的适用性，要么给该选项补部位限定）。

## 关联

母单 #4423 · 真值源 `docs/curtain-production-rules.md` §2/§3 · 领域设计
`docs/design/position-instance-routing-model.md` §9 · 种子多源收敛守卫
`tests/unit_ci_workflows/test_production_catalog_seed.py`（`routing.py` ↔ V71 ↔ `schema.sql`）。
"""
from __future__ import annotations

import pytest

from app.production.routing import (
    OPERATION_CATALOG,
    OPERATION_LOGICAL_NAMES,
    OPERATION_POSITION_PRICES,
    ROUTE_MAINLINE_STEPS,
    ROUTE_RULES,
    ROUTE_TEMPLATE_NAME_DEFAULT,
    ROUTINGS,
    SPECIAL_OPTION_ROUTINGS,
    build_routing,
    build_route_v2,
)

POSITIONS = ("布帘", "纱帘", "帘头")

# ── ① 主线（落库的 9 道；「工艺槽位」不落库，只在文档里）──
MAINLINE = ["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]

# ── ② 9 个组合的**冻结期望序列**（母单 #4423 §二 实证；本单不自行改动）──
EXPECTED_REBUILT = {
    ("布帘", "韩褶"): ["精裁", "三边", "韩褶", "上车布", "熨烫", "定型", "复烫", "车被",
                       "外帘打卷", "外帘装袋", "外帘发货"],
    ("布帘", "打孔"): ["精裁", "三边", "打孔", "熨烫", "定型", "复烫", "车被",
                       "外帘打卷", "外帘装袋", "外帘发货"],
    ("布帘", "四爪钩"): ["精裁", "三边", "上车布", "熨烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"],
    ("布帘", "穿杆"): ["精裁", "三边", "熨烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "韩褶"): ["精裁", "三边", "韩褶", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "打孔"): ["精裁", "三边", "打孔", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "四爪钩"): ["精裁", "三边", "上车布", "外帘打卷", "外帘装袋", "外帘发货"],
    ("纱帘", "穿杆"): ["精裁", "三边", "外帘打卷", "外帘装袋", "外帘发货"],
    ("帘头", "平幔"): ["精裁", "三边", "帘头制作", "定型", "外帘打卷", "外帘装袋", "外帘发货"],
}
EXPECTED_COUNTS = {
    ("布帘", "韩褶"): 11, ("布帘", "打孔"): 10, ("布帘", "四爪钩"): 8, ("布帘", "穿杆"): 7,
    ("纱帘", "韩褶"): 6, ("纱帘", "打孔"): 6, ("纱帘", "四爪钩"): 6, ("纱帘", "穿杆"): 5,
    ("帘头", "平幔"): 7,
}

# ── ③ 逻辑工序名映射（35 → 28）：7 组部位变体 + 去后缀/无后缀者 ──
VARIANT_GROUPS = {
    "精裁": ("精裁-布", "精裁-纱"),
    "裁剪": ("裁剪-布", "裁剪-纱"),
    "三边": ("布三边", "纱三边"),
    "韩褶": ("韩褶-布", "韩褶-纱"),
    "上车布": ("上车布-布", "上车布-纱"),
    "打孔": ("打孔-布", "打孔-纱"),
    "绑带": ("绑带-布", "绑带-纱"),
}
SUFFIX_STRIPPED = {
    "拼1次-布": "拼1次", "拼2次-布": "拼2次", "拼3次-布": "拼3次",
    "花边-布": "花边", "铅坠-布": "铅坠", "接高-布": "接高",
    "熨烫-布": "熨烫", "定型-布": "定型", "复烫-布": "复烫",
    "布帘车被": "车被",
    "logo条-布": "logo条", "立边-布": "立边", "扣环-布": "扣环", "防翘扣-布": "防翘扣",
    "帘头制作": "帘头制作", "外帘打卷": "外帘打卷", "外帘装袋": "外帘装袋",
    "外帘发货": "外帘发货", "质检": "质检", "抱枕": "抱枕", "腰靠垫": "腰靠垫",
}
EXPECTED_LOGICAL_NAMES = {
    **{old: logical for logical, olds in VARIANT_GROUPS.items() for old in olds},
    **SUFFIX_STRIPPED,
}

# ── ④ 部位适用性（列出 = applicable TRUE；未列出的部位 = FALSE）──
APPLICABLE = {
    "精裁": {"布帘", "纱帘", "帘头"},
    "裁剪": {"布帘", "纱帘", "帘头"},
    "三边": {"布帘", "纱帘", "帘头"},
    "韩褶": {"布帘", "纱帘", "帘头"},
    "上车布": {"布帘", "纱帘"},
    "打孔": {"布帘", "纱帘", "帘头"},
    "拼1次": {"布帘"},
    "拼2次": {"布帘"},
    "拼3次": {"布帘"},
    "花边": {"布帘"},
    "铅坠": {"布帘"},
    "接高": {"布帘"},
    "帘头制作": {"帘头"},
    "熨烫": {"布帘"},
    "定型": {"布帘", "帘头"},
    "复烫": {"布帘"},
    "车被": {"布帘"},
    "外帘打卷": {"布帘", "纱帘", "帘头"},
    "外帘装袋": {"布帘", "纱帘", "帘头"},
    "质检": {"布帘", "纱帘", "帘头"},
    "外帘发货": {"布帘", "纱帘", "帘头"},
    "绑带": {"布帘", "纱帘"},
    "抱枕": {"布帘", "纱帘", "帘头"},
    "腰靠垫": {"布帘", "纱帘", "帘头"},
    "logo条": {"布帘"},
    "立边": {"布帘"},
    "扣环": {"布帘"},
    "防翘扣": {"布帘"},
}

# ── ⑤ 逻辑工序单价（**不得发明**：逐条可从 OPERATION_CATALOG 溯源）──
LOGICAL_UNIT_PRICES = {
    "精裁": 0.4, "裁剪": 0.4, "三边": 0.4, "韩褶": 0.4, "上车布": 0.5, "打孔": 0.15,
    "拼1次": 0.8, "拼2次": 1.2, "拼3次": 1.6, "花边": 0.6, "铅坠": 0.3, "接高": 1.0,
    "帘头制作": 2.0, "熨烫": 0.35, "定型": 0.4, "复烫": 0.35, "车被": 0.4,
    "外帘打卷": 1.0, "外帘装袋": 1.0, "质检": 1.5, "外帘发货": 1.0, "绑带": 0.5,
    "抱枕": 2.0, "腰靠垫": 2.0, "logo条": 0.6, "立边": 0.5, "扣环": 0.3, "防翘扣": 0.2,
}

# ── ⑥ 规则表 26 条（工艺 10 + 特殊选项 16）；元组 = (触发值, 部位限定, 动作, 工序, 锚点) ──
EXPECTED_CRAFT_RULES = [
    ("韩褶", None, "insert", "韩褶", "三边"),
    ("韩褶", "布帘", "insert", "上车布", "韩褶"),
    ("打孔", None, "insert", "打孔", "三边"),
    ("四爪钩", None, "insert", "上车布", "三边"),
    ("四爪钩", None, "remove", "定型", None),
    ("四爪钩", None, "remove", "复烫", None),
    ("穿杆", None, "remove", "定型", None),
    ("穿杆", None, "remove", "复烫", None),
    ("平幔", None, "insert", "帘头制作", "三边"),
    ("平幔", None, "remove", "复烫", None),
]
EXPECTED_OPTION_RULES = [
    ("拼1次", None, "insert", "拼1次", "三边"),
    ("拼2次", None, "insert", "拼2次", "三边"),
    ("拼3次", None, "insert", "拼3次", "三边"),
    ("加花边", None, "insert", "花边", "三边"),
    ("加铅块", None, "insert", "铅坠", "三边"),
    ("接高", None, "insert", "接高", "精裁"),
    ("双眼皮接高", None, "insert", "接高", "精裁"),
    ("余料做绑带", None, "insert", "绑带", "车被"),
    ("布绑带", None, "insert", "绑带", "车被"),
    ("余料做帘头", None, "insert", "帘头制作", "三边"),
    ("抱枕", None, "insert", "抱枕", "外帘打卷"),
    ("纱绑带", None, "insert", "绑带", "车被"),
    ("加logo条", None, "insert", "logo条", "三边"),
    ("加立边", None, "insert", "立边", "三边"),
    ("扣环", None, "insert", "扣环", "三边"),
    ("防翘扣", None, "insert", "防翘扣", "三边"),
]


def _rule_key(rule) -> tuple:
    """规则 → 业务键元组（不含 id / priority / status：优先级由 `TestRuleOrdering` 单独钉）。"""
    return (rule["trigger_value"], rule["position"], rule["action"],
            rule["operation"], rule["after_operation"])


def _rules_of(kind: str) -> list:
    return [_rule_key(r) for r in ROUTE_RULES if r["trigger_kind"] == kind]


# ── 判据 1：9/9 逐字重建（本单最重要的判据）──

class TestVerbatimRebuild:
    """`build_route_v2` 重建 9 个组合 —— 与冻结期望、旧 `ROUTINGS` 归一序列三方逐字一致。"""

    @pytest.mark.parametrize("curtain_type,craft", sorted(EXPECTED_REBUILT))
    def test_rebuild_matches_frozen_expectation(self, curtain_type, craft):
        """新真值源 ↔ **冻结期望**（硬编码在文件内，不从实现推导）。"""
        got = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        expected = EXPECTED_REBUILT[(curtain_type, craft)]
        assert got == expected, (
            f"{curtain_type}×{craft} 重建结果与冻结期望不一致（含顺序）：\n"
            f"  实测 = {got}\n  期望 = {expected}")

    @pytest.mark.parametrize("curtain_type,craft", sorted(EXPECTED_REBUILT))
    def test_rebuild_matches_old_routings_normalized(self, curtain_type, craft):
        """新真值源 ↔ **旧 `ROUTINGS`**（按 `OPERATION_LOGICAL_NAMES` 归一）—— 表示法收敛不改语义。"""
        got = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        old = [OPERATION_LOGICAL_NAMES[op] for op in ROUTINGS[(curtain_type, craft)]]
        assert got == old, (
            f"{curtain_type}×{craft}：新模型重建 ≠ 旧 ROUTINGS 归一序列\n"
            f"  新 = {got}\n  旧 = {old}")

    @pytest.mark.parametrize("curtain_type,craft", sorted(EXPECTED_REBUILT))
    def test_rebuild_sequence_length(self, curtain_type, craft):
        """道数逐条钉死（11/10/8/7/6/6/6/5/7）—— 少一道或多一道都红。"""
        got = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        assert len(got) == EXPECTED_COUNTS[(curtain_type, craft)], (
            f"{curtain_type}×{craft} 道数 {len(got)} ≠ {EXPECTED_COUNTS[(curtain_type, craft)]}")

    def test_nine_combinations_all_rebuilt_verbatim(self):
        """一次性汇总 9/9（PR 证据里贴的就是这条的输出原文）。"""
        report, mismatched = [], []
        for key in sorted(EXPECTED_REBUILT):
            got = build_route_v2({"curtain_type": key[0], "craft": key[1]})
            expected = EXPECTED_REBUILT[key]
            ok = got == expected
            report.append(f"{key[0]}×{key[1]} {len(got)}/{len(expected)} {'✅' if ok else '❌'}")
            if not ok:
                mismatched.append(key)
        print("\n逐字重建 9/9 结果：\n  " + "\n  ".join(report))
        assert not mismatched, f"以下组合重建不一致：{mismatched}"
        assert len(report) == 9

    def test_three_sources_agree_on_all_nine(self):
        """三方（冻结期望 / 旧 ROUTINGS 归一 / 新重建）在 9 个组合上全等。"""
        assert set(ROUTINGS) == set(EXPECTED_REBUILT), "旧 ROUTINGS 的键集变化 ⇒ 零行为变化被破坏"
        for key, expected in EXPECTED_REBUILT.items():
            assert [OPERATION_LOGICAL_NAMES[op] for op in ROUTINGS[key]] == expected, \
                f"旧 ROUTINGS{key} 归一后 ≠ 冻结期望"
            assert build_route_v2({"curtain_type": key[0], "craft": key[1]}) == expected, \
                f"新重建{key} ≠ 冻结期望"


# ── 判据 2：逻辑工序名映射（35 → 28；7 组部位变体）──

class TestLogicalNames:
    def test_mapping_is_frozen_verbatim(self):
        """映射逐条等于冻结值（不从实现推导）—— 35 个旧名 → 28 个逻辑名。"""
        assert OPERATION_LOGICAL_NAMES == EXPECTED_LOGICAL_NAMES

    def test_mapping_covers_old_catalog_exactly(self):
        """键集 == `OPERATION_CATALOG` 的 35 道旧工序（漏一个 ⇒ 某道工序在新模型里无逻辑名）。"""
        assert set(OPERATION_LOGICAL_NAMES) == set(OPERATION_CATALOG)
        assert len(OPERATION_LOGICAL_NAMES) == 35
        assert len(set(OPERATION_LOGICAL_NAMES.values())) == 28

    @pytest.mark.parametrize("logical,olds", sorted(VARIANT_GROUPS.items()))
    def test_variant_group_members_map_to_the_group_name(self, logical, olds):
        """7 组部位变体：每个旧名都映射到组名（`韩褶-布`/`韩褶-纱` → `韩褶`）。"""
        assert {OPERATION_LOGICAL_NAMES[old] for old in olds} == {logical}

    @pytest.mark.parametrize("logical,olds", sorted(VARIANT_GROUPS.items()))
    def test_variant_group_shares_group_and_unit(self, logical, olds):
        """同组各变体的 `group_name` / `unit` **必须一致** —— 否则「同一道工序」不成立。

        合并成一行逻辑工序的前提是「它们只是同一道工序的两种部位写法」；分组/单位不同
        意味着两个不同的车间口径被压成一行（单价与计件都会错）。
        （`scope` 同组一致性由种子侧守卫 `test_production_catalog_seed.py` 钉 —— 那才读得到 scope。）
        """
        attrs = {old: (OPERATION_CATALOG[old]["group"], OPERATION_CATALOG[old]["unit"]) for old in olds}
        assert len(set(attrs.values())) == 1, f"{logical} 组内变体的 group/unit 不一致：{attrs}"

    def test_variant_groups_are_exactly_the_seven(self):
        """恰好 7 组、每组 2 个变体（多一组/少一组都红）。"""
        grouped = {}
        for old, logical in OPERATION_LOGICAL_NAMES.items():
            grouped.setdefault(logical, []).append(old)
        multi = {k: sorted(v) for k, v in grouped.items() if len(v) > 1}
        assert multi == {k: sorted(v) for k, v in VARIANT_GROUPS.items()}
        assert len(multi) == 7


# ── 判据 3：部位价目 84 行（28 × 3），`applicable` 显式，**不发明单价** ──

class TestPositionPrices:
    def test_matrix_is_28_by_3(self):
        """28 道逻辑工序 × 3 部位 = 84 行；每行都显式带 `unit_price` 与 `applicable`。"""
        assert set(OPERATION_POSITION_PRICES) == set(LOGICAL_UNIT_PRICES)
        assert len(OPERATION_POSITION_PRICES) == 28
        rows = 0
        for logical, by_position in OPERATION_POSITION_PRICES.items():
            assert set(by_position) == set(POSITIONS), f"{logical} 的部位键集 ≠ {POSITIONS}"
            for pos in POSITIONS:
                cell = by_position[pos]
                assert set(cell) == {"unit_price", "applicable"}, (
                    f"{logical}@{pos} 的字段集 = {sorted(cell)}（必须显式落 unit_price + applicable）")
                rows += 1
        assert rows == 84

    @pytest.mark.parametrize("logical", sorted(APPLICABLE))
    def test_applicability_matches_frozen_matrix(self, logical):
        """适用性逐条等于冻结矩阵（未列出的部位 = 不做）。"""
        got = {pos for pos in POSITIONS if OPERATION_POSITION_PRICES[logical][pos]["applicable"]}
        assert got == APPLICABLE[logical], \
            f"{logical} 适用部位 {sorted(got)} ≠ {sorted(APPLICABLE[logical])}"

    @pytest.mark.parametrize("logical", sorted(APPLICABLE))
    def test_price_is_evidenced_where_applicable_and_absent_where_not(self, logical):
        """适用 ⇒ 落实证单价；**明确不做 ⇒ 不落价（None）**（「明确不做」与「没定价」可区分）。"""
        for pos in POSITIONS:
            cell = OPERATION_POSITION_PRICES[logical][pos]
            if pos in APPLICABLE[logical]:
                assert cell["unit_price"] == LOGICAL_UNIT_PRICES[logical], (
                    f"{logical}@{pos} 单价 {cell['unit_price']} ≠ 实证值 {LOGICAL_UNIT_PRICES[logical]}")
            else:
                assert cell["unit_price"] is None, (
                    f"{logical}@{pos} 明确不做却落了价 {cell['unit_price']}（会把「不做」与「有价」混淆）")

    def test_no_invented_prices(self):
        """**不发明单价**：逻辑单价逐条能从 `OPERATION_CATALOG`（旧真值源）溯源，且旧变体单价一致。"""
        for old, logical in OPERATION_LOGICAL_NAMES.items():
            assert OPERATION_CATALOG[old]["unit_price"] == LOGICAL_UNIT_PRICES[logical], (
                f"{old} 的旧单价 {OPERATION_CATALOG[old]['unit_price']} ≠ 新逻辑单价 "
                f"{LOGICAL_UNIT_PRICES[logical]} ⇒ 新模型发明/篡改了单价")

    def test_no_invented_operations(self):
        """**不发明工序**：主线与规则里的工序名/锚点都必须在 28 道逻辑工序集合内。"""
        logical_set = set(LOGICAL_UNIT_PRICES)
        assert set(ROUTE_MAINLINE_STEPS) <= logical_set
        for rule in ROUTE_RULES:
            assert rule["operation"] in logical_set, f"规则引用了不存在的工序：{rule}"
            assert rule["after_operation"] is None or rule["after_operation"] in logical_set, \
                f"规则锚点不是逻辑工序名：{rule}"

    def test_mainline_is_the_frozen_nine(self):
        """主线 = 落库的 9 道（「工艺槽位」不落库）；模板名 = 用户可命名的默认名。"""
        assert ROUTE_MAINLINE_STEPS == MAINLINE
        assert ROUTE_TEMPLATE_NAME_DEFAULT == "窗帘工序路线（默认）"


# ── 判据 4：规则表 26 条（工艺 10 + 特殊选项 16）──

class TestRouteRules:
    def test_rule_count_and_kinds(self):
        """恰好 26 条：工艺 10 + 特殊选项 16；无第三种触发类型（P1 不落 shaped/processing_item）。"""
        assert len(ROUTE_RULES) == 26
        kinds = [r["trigger_kind"] for r in ROUTE_RULES]
        assert kinds.count("craft") == 10
        assert kinds.count("option") == 16
        assert set(kinds) == {"craft", "option"}

    def test_craft_rules_are_frozen_verbatim(self):
        """10 条工艺规则逐条等于冻结值（触发键 = ERP 工艺名，逐字一致）。"""
        assert _rules_of("craft") == EXPECTED_CRAFT_RULES

    def test_option_rules_are_frozen_verbatim(self):
        """16 条特殊选项规则逐条等于冻结值（工序名与锚点**都归一为逻辑名**）。"""
        assert _rules_of("option") == EXPECTED_OPTION_RULES

    def test_option_rules_are_the_migration_of_special_option_routings(self):
        """16 条 = `SPECIAL_OPTION_ROUTINGS` 逐条搬迁 —— 键集与「归一后的工序/锚点」双向一致。"""
        migrated = {opt: (None, "insert",
                          OPERATION_LOGICAL_NAMES[spec["operation"]],
                          OPERATION_LOGICAL_NAMES[spec["after"]])
                    for opt, spec in SPECIAL_OPTION_ROUTINGS.items()}
        assert len(migrated) == 16
        assert dict((r[0], r[1:]) for r in EXPECTED_OPTION_RULES) == migrated

    def test_rule_actions_are_insert_or_remove(self):
        """动作闭词表 `{insert, remove}`；`remove` 不带锚点、`insert` 必须带锚点。"""
        for rule in ROUTE_RULES:
            assert rule["action"] in ("insert", "remove")
            if rule["action"] == "remove":
                assert rule["after_operation"] is None, f"remove 规则不该有锚点：{rule}"
            else:
                assert rule["after_operation"] is not None, f"insert 规则缺锚点：{rule}"

    def test_priorities_are_distinct_and_deterministic(self):
        """优先级两两不同（排序完全确定，不依赖 Python 排序稳定性）。"""
        priorities = [r["priority"] for r in ROUTE_RULES]
        assert len(set(priorities)) == len(priorities) == 26


class TestRuleOrdering:
    """顺序敏感：`insert 上车布 after 韩褶` 必须排在 `insert 韩褶 after 三边` **之后**。"""

    def test_hanzhe_rules_order_is_load_bearing(self):
        idx = {(r["trigger_value"], r["operation"]): r["priority"] for r in ROUTE_RULES}
        assert idx[("韩褶", "韩褶")] < idx[("韩褶", "上车布")], (
            "`insert 上车布 after 韩褶` 必须先落锚点「韩褶」再插「上车布」，否则会追加到末尾")

    def test_rules_are_declared_in_priority_order(self):
        """规则列表本身按 priority 升序声明（声明顺序 == 生效顺序，读代码即知行为）。"""
        priorities = [r["priority"] for r in ROUTE_RULES]
        assert priorities == sorted(priorities)


# ── 判据 5：零行为变化（旧常量 / 旧函数）──

class TestZeroBehaviourChange:
    def test_old_route_truth_source_is_untouched(self):
        """旧 `ROUTINGS` 一字不动：9 条路线，布帘×韩褶 仍是 11 道**旧工序名**。"""
        assert len(ROUTINGS) == 9
        assert ROUTINGS[("布帘", "韩褶")] == [
            "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
            "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
        ]

    def test_old_build_routing_is_untouched(self):
        """`build_routing` 对 9 个组合仍返回**旧工序名**逐字序列（消费路径未切换）。"""
        for key, olds in ROUTINGS.items():
            got = build_routing({"curtain_type": key[0], "craft": key[1]})
            assert got == olds, f"build_routing{key} 输出变化 ⇒ P1「零行为变化」被破坏"

    def test_new_truth_source_is_a_second_source_not_a_replacement(self):
        """新真值源是**并存的第二份**：旧快照仍带部位后缀（7 组变体），新主线一律是逻辑名。"""
        assert list(ROUTE_MAINLINE_STEPS) != list(ROUTINGS[("布帘", "韩褶")])
        old_names = {op for ops in ROUTINGS.values() for op in ops}
        assert {"精裁-布", "布三边", "韩褶-布", "上车布-布"} <= old_names
        assert not ({"精裁-布", "布三边", "韩褶-布", "上车布-布"} & set(ROUTE_MAINLINE_STEPS))


# ── 判据 6：特殊选项规则 ⇒ 条件工序落位（与旧 `build_routing` 同口径）──

class TestSpecialOptionsRebuild:
    """勾一个特殊选项 ⇒ 新模型把条件工序插在与旧实现**相同**的相对位置（P2 切换的行为护栏）。

    旧实现：`_insert_after(route, 旧工序名, 旧锚点名)`；新实现：规则表 `insert` + 逻辑名锚点。
    两侧把结果归一到逻辑名后必须逐字一致 —— `余料做帘头` 除外（见类尾的显式登记）。
    """

    #: 旧实现会插、而新模型按**部位适用性**会滤掉的选项（如实登记，**不是**期望行为）
    POSITION_FILTERED_OPTIONS = frozenset({"余料做帘头"})
    BASE = {"curtain_type": "布帘", "craft": "韩褶"}

    @pytest.mark.parametrize(
        "option", sorted(set(SPECIAL_OPTION_ROUTINGS) - POSITION_FILTERED_OPTIONS))
    def test_option_rule_inserts_at_the_same_relative_position(self, option):
        old = [OPERATION_LOGICAL_NAMES[op]
               for op in build_routing({**self.BASE, "special_options": [option]})]
        new = build_route_v2({**self.BASE, "special_options": [option]})
        assert new == old, f"选项「{option}」的条件工序位置与旧实现不一致：\n  新 = {new}\n  旧 = {old}"

    def test_yield_curtain_head_option_is_filtered_by_applicability(self):
        """如实登记（规格张力，交 P2 裁定）：`余料做帘头` 在布帘上被部位适用性滤掉。

        `帘头制作` 的冻结适用性是 `{帘头}`，而该选项把它插进**布帘**路线 ⇒ 新模型把它滤掉，
        旧实现会保留 ⇒ 若 P2 直接切换消费路径，这道工序会**从布帘订单上消失**（少发工人钱）。
        本测试钉住的是**当前（规格照抄）行为**，P2 前必须裁定：
        要么放开 `帘头制作@布帘`，要么给该选项补部位限定。
        """
        option = "余料做帘头"
        old = [OPERATION_LOGICAL_NAMES[op]
               for op in build_routing({**self.BASE, "special_options": [option]})]
        new = build_route_v2({**self.BASE, "special_options": [option]})
        assert "帘头制作" in old, "旧实现确实会插入「帘头制作」（差异的另一侧，缺它则本测试无意义）"
        assert "帘头制作" not in new, (
            "部位适用性过滤不再滤掉「帘头制作」⇒ 规格张力已消解，请同步删掉本登记并放开 P2 口径")
        assert new == [op for op in old if op != "帘头制作"]

    def test_option_trigger_is_exact_match_not_substring(self):
        """触发键是**精确匹配**：`拼1次加强版` 不得命中 `拼1次` 规则（防 contains 式错配）。"""
        assert build_route_v2({**self.BASE, "special_options": ["拼1次加强版"]}) == \
            build_route_v2(self.BASE)

    def test_unknown_craft_yields_mainline_plus_applicability_only(self):
        """未知工艺 ⇒ 只有主线 + 部位适用性（不静默套用别的工艺规则）。"""
        assert build_route_v2({"curtain_type": "纱帘", "craft": "罗马帘"}) == \
            ["精裁", "三边", "外帘打卷", "外帘装袋", "外帘发货"]


# ── 判据 7：注入式自证（每条判据都要能红）──

class TestInjectedDrift:
    """「不会红的断言 = 空断言」：逐条注入漂移，证明上面的比对**真能**照出来。"""

    def _rebuild(self, key):
        return build_route_v2({"curtain_type": key[0], "craft": key[1]})

    def test_missing_rule_is_detected(self, monkeypatch):
        """少一条规则（`韩褶 + 布帘 insert 上车布`）⇒ 布帘×韩褶 从 11 道掉到 10 道。"""
        import app.production.routing as routing
        pruned = [r for r in ROUTE_RULES
                  if not (r["trigger_value"] == "韩褶" and r["operation"] == "上车布")]
        assert len(pruned) == 25
        monkeypatch.setattr(routing, "ROUTE_RULES", pruned)
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_REBUILT[("布帘", "韩褶")]

    def test_inverted_priority_is_detected(self, monkeypatch):
        """规则优先级颠倒（`上车布` 先于 `韩褶`）⇒ 锚点还不存在 ⇒ 追加到末尾，顺序即错。"""
        import app.production.routing as routing
        swapped = [dict(r) for r in ROUTE_RULES]
        for rule in swapped:
            if rule["trigger_value"] == "韩褶" and rule["operation"] == "韩褶":
                rule["priority"] = 20
            elif rule["trigger_value"] == "韩褶" and rule["operation"] == "上车布":
                rule["priority"] = 10
        monkeypatch.setattr(routing, "ROUTE_RULES", swapped)
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_REBUILT[("布帘", "韩褶")]

    def test_wrong_operation_name_is_detected(self, monkeypatch):
        """规则工序名写错（`韩褶` → 另一个**存在但不对**的逻辑工序 `打孔`）⇒ 重建序列不等。"""
        import app.production.routing as routing
        drifted = [dict(r) for r in ROUTE_RULES]
        for rule in drifted:
            if rule["trigger_value"] == "韩褶" and rule["operation"] == "韩褶":
                rule["operation"] = "打孔"
        monkeypatch.setattr(routing, "ROUTE_RULES", drifted)
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_REBUILT[("布帘", "韩褶")]

    def test_unknown_operation_name_fails_closed(self, monkeypatch):
        """规则引用了**没有价目行**的工序 ⇒ 显式失败（KeyError），不静默产出无价工序。"""
        import app.production.routing as routing
        drifted = [dict(r) for r in ROUTE_RULES]
        for rule in drifted:
            if rule["trigger_value"] == "韩褶" and rule["operation"] == "韩褶":
                rule["operation"] = "褶韩"
        monkeypatch.setattr(routing, "ROUTE_RULES", drifted)
        with pytest.raises(KeyError):
            self._rebuild(("布帘", "韩褶"))

    def test_applicability_filter_is_load_bearing(self, monkeypatch):
        """把「熨烫@纱帘」打开 ⇒ 纱帘×韩褶 多出「熨烫」⇒ 部位适用性过滤不是装饰。"""
        import app.production.routing as routing
        opened = {logical: {pos: dict(cell) for pos, cell in by_position.items()}
                  for logical, by_position in OPERATION_POSITION_PRICES.items()}
        opened["熨烫"]["纱帘"] = {"unit_price": 0.35, "applicable": True}
        monkeypatch.setattr(routing, "OPERATION_POSITION_PRICES", opened)
        assert self._rebuild(("纱帘", "韩褶")) != EXPECTED_REBUILT[("纱帘", "韩褶")]

    def test_logical_name_mapping_drift_is_detected(self):
        """映射漂移（`纱三边` → `三边-纱`）⇒ 与冻结映射不等，且旧 ROUTINGS 归一序列随之偏离期望。"""
        drifted = dict(EXPECTED_LOGICAL_NAMES)
        drifted["纱三边"] = "三边-纱"
        assert drifted != EXPECTED_LOGICAL_NAMES
        normalized_old = [drifted[op] for op in ROUTINGS[("纱帘", "穿杆")]]
        assert normalized_old != EXPECTED_REBUILT[("纱帘", "穿杆")]
