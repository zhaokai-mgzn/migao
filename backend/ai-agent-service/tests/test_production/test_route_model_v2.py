# case_ids: PP-010, PG-018
"""工序路线模型 v2 真值源（issue #4427 = 母单 #4423 的 P1/3）—— **去部位化后的冻结基线**。

## 🔴 本文件在 issue #4937 换过一次基线（照实登记）

**旧基线随用户 2026-09-21 裁定退休**：母单 **#4936** 用户原话「这个必须要改，我们移除了部位的
设计，**不计成本的改**」⇒ issue **#4937**（去部位化彻底版）把「部位」从**取价、取路、筛选、配置**
里**全部**移除。本文件原来钉的判据因此**退休并换基线**：

| 旧判据（已退休） | 新基线（本文件现在钉的） |
|---|---|
| `9/9 逐字重建` = 旧 9 条展开路线（`ROUTINGS`）归一序列（与**旧结构**逐字相等） | **部位无关的冻结序列**：同一工艺在**任何**帘种上得到**同一套逻辑工序名** |
| `ROUTINGS` 是 9 条 `(部位, 工艺)` 展开快照、`build_routing` 按 `(部位, 工艺)` 查表 | `ROUTINGS` 只按**工艺**建键（**5 条**）；`build_routing` 只按工艺查表 |
| 部位价目 `30 × 4 = 120 行`、`OPERATION_POSITION_PRICES[工序][部位]`（两级） | 部位价目 **30 行**、`OPERATION_POSITION_PRICES[工序]`（**单键**，与 `V104` / `docs/sql/schema.sql` 终态逐行同值） |
| 规则表 26 条**带 `position`**（部位限定生效） | 规则表 26 条**无 `position`**（O2 退场；`V103` 清空存量值） |

## 🔴 本文件在 issue #4962 **部分回退**了上面第 4 行（照实登记）

用户 2026-09-21 追问后的裁定：「**如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置**」
⇒ issue **#4962** 把「**规则级**部位限定」加回（**只回退这一维**；`applicable` 适用性过滤、
矩阵物理去部位、读面的去部位化**一字不动**）：

| #4937 的形态（已改判） | #4962 的形态（本文件现在钉的） |
|---|---|
| 规则表 26 条**一律无 `position`** | 26 条里**恰好 1 条**带 `position`（`韩褶 → insert 上车布`，`position="布帘"`）—— 与 `V71` 字面量 / `V108__restore_route_rule_positions.sql` / `docs/sql/schema.sql` / Java `ProductionSeedTemplateService#CRAFT_RULES` **同值** |
| 「同一工艺在**任何**帘种上得到**同一套**工序」 | **带 `position` 的规则只在该部位生效** ⇒ `韩褶` 在**布帘**上多出 `上车布`、在**纱帘/帘头**上没有；其余规则（`position` 为空 = 不限）**逐字不变** |

**判据值全部硬编码在文件内**（不从被测实现推导 —— 否则「实现自洽」就能骗过测试）。

## 红证（「不会红的断言 = 空断言」，见 `TestInjectedDrift`）

逐条注入式自证：少一条规则 / 规则优先级颠倒 / 规则工序名错 / 未知工序 fail-closed /
**去掉部位限定 key**（纱帘路线会多出 `上车布` ⇒ 红）/ 逻辑名映射漂移 / 价目表多一行。

## 关联

母单 #4423 · 去部位化母单 #4936 + 包 #4937 · **部位维加回 #4962** · 真值源 `docs/curtain-production-rules.md` §2/§3 ·
种子多源收敛守卫 `tests/unit_ci_workflows/test_production_catalog_seed.py`。
"""
from __future__ import annotations

import pytest

from app.production.routing import (
    FABRIC_MAINLINE_STEPS,
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

#: 🔴 **#4937 之后帘种不再参与「价目适用性」筛选**；**#4962 起规则级部位限定加回**
#: ⇒ 三个帘种的序列**只在「带 `position` 的规则」上分叉**（见 `POSITION_LIMIT_POSITION`）。
CURTAIN_TYPES = ("布帘", "纱帘", "帘头")
#: 工艺维（`ROUTINGS` 的键 / `build_route_v2` 的规则触发值）。
CRAFTS = ("韩褶", "打孔", "四爪钩", "穿杆", "平幔")

# ── ① 主线 ──
#: 窗帘主线（落库的 **10** 道；`打包` 由 issue #4529 插在 `外帘打卷` 与 `外帘装袋` 之间）。
MAINLINE = ["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"]

#: 🔴 **部位限定（issue #4962 加回）**：`V71` 的 26 条规则种子里**唯一**一条带 `position` 的是
#: `韩褶 → insert 上车布`（`position='布帘'`）⇒ **只有「布帘」**的韩褶路线带 `上车布`。
#: ⚠️ `四爪钩 → insert 上车布` 是**另一条**规则（`position` 为空 = 不限部位）⇒ 它**照旧**对所有
#: 帘种生效 —— 这两条规则的名字一样、部位语义不同，别混读。
POSITION_LIMIT_POSITION = "布帘"
POSITION_LIMIT_RULE = ("craft", "韩褶", "insert", "上车布", POSITION_LIMIT_POSITION)

# ── ② 冻结序列（#4937 部位无关基线 ∩ #4962 部位限定规则）──
#: **布帘列**的冻结序列（= `position` 为空的规则 + 那唯一一条 `position='布帘'` 的规则）。
EXPECTED_BY_CRAFT = {
    "韩褶": ["精裁", "三边", "韩褶", "上车布", "熨烫", "定型", "复烫", "车被",
             "外帘打卷", "打包", "外帘装袋", "外帘发货"],
    "打孔": ["精裁", "三边", "打孔", "熨烫", "定型", "复烫", "车被",
             "外帘打卷", "打包", "外帘装袋", "外帘发货"],
    "四爪钩": ["精裁", "三边", "上车布", "熨烫", "车被",
               "外帘打卷", "打包", "外帘装袋", "外帘发货"],
    "穿杆": ["精裁", "三边", "熨烫", "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"],
    "平幔": ["精裁", "三边", "帘头制作", "熨烫", "定型", "车被",
             "外帘打卷", "打包", "外帘装袋", "外帘发货"],
}


def _expected_for(curtain_type: str, craft: str) -> list:
    """某 `(帘种, 工艺)` 的冻结序列（**硬编码判据**，不从实现推导）。

    分叉**只有一处**：`POSITION_LIMIT_RULE`（`韩褶 → 上车布`，限 `布帘`）
    ⇒ 非布帘的韩褶路线里没有 `上车布`。
    """
    seq = list(EXPECTED_BY_CRAFT[craft])
    if craft == POSITION_LIMIT_RULE[1] and curtain_type != POSITION_LIMIT_POSITION:
        seq.remove(POSITION_LIMIT_RULE[3])
    return seq


EXPECTED_REBUILT = {(ct, craft): _expected_for(ct, craft)
                    for ct in CURTAIN_TYPES for craft in EXPECTED_BY_CRAFT}

#: 道数**逐条硬编码**（不从上面的序列推导 —— 独立判据才有判别力）。
#: 唯一分叉 = `韩褶`（布帘 12 / 非布帘 11，差的正是部位限定的那条 `上车布`）。
EXPECTED_COUNTS = {
    ("布帘", "韩褶"): 12, ("布帘", "打孔"): 11, ("布帘", "四爪钩"): 9,
    ("布帘", "穿杆"): 8, ("布帘", "平幔"): 10,
    ("纱帘", "韩褶"): 11, ("纱帘", "打孔"): 11, ("纱帘", "四爪钩"): 9,
    ("纱帘", "穿杆"): 8, ("纱帘", "平幔"): 10,
    ("帘头", "韩褶"): 11, ("帘头", "打孔"): 11, ("帘头", "四爪钩"): 9,
    ("帘头", "穿杆"): 8, ("帘头", "平幔"): 10,
}
#: 布料单（`saleForm=布料`）走**独立主线**（「产品形态」分支，与部位维无关）。
#: ⚠️ **字面量仍是 `配料 → 打包`**（V88 ③ 把**迁移链/bootstrap** 改成了 `裁剪 → 打包`，
#: 但 `routing.py` 属 ai-agent，本次去部位化**未动**它 —— 本文件的判据按**当前真值源**冻结）。
#: 「迁移链/bootstrap ↔ 真值源」的口径折算由
#: `tests/unit_ci_workflows/test_production_catalog_seed.py::_as_truth_caliber` 承担。
FABRIC_EXPECTED = ["配料", "打包"]

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
#: 🔴 **冻结的 35 条**（`_LOGICAL_NAME_PAIRS` 段；被
#: `tests/unit_ci_workflows/test_logical_name_single_source_guard.py` 逐条冻结）。
FROZEN_LOGICAL_NAMES = {
    **{old: logical for logical, olds in VARIANT_GROUPS.items() for old in olds},
    **SUFFIX_STRIPPED,
}

#: issue #4937 追加的 **4 道纱帘变体**（`applicable` 过滤退场后它们会进纱帘路线）。
SHEER_VARIANT_NAMES = {
    "熨烫-纱": "熨烫", "定型-纱": "定型", "复烫-纱": "复烫", "车被-纱": "车被",
}

#: 运行期全表 = 35 条冻结段 + 4 条纱帘段（与 Java 侧
#: `logicalNamePairs()` + `withSheerVariants(...)` 同构）。
EXPECTED_LOGICAL_NAMES = {**FROZEN_LOGICAL_NAMES, **SHEER_VARIANT_NAMES}

# ── ④ 逻辑工序价目（**30 行**，单键；#4937）──
#: 逐值冻结（来源 = `V104` 的四档选行结果；与 `docs/sql/schema.sql` 的 30 行存活格逐行同值）。
LOGICAL_UNIT_PRICES = {
    "精裁": 0.4, "裁剪": 0.4, "三边": 0.4, "韩褶": 0.4, "上车布": 0.5, "打孔": 0.15,
    "拼1次": 0.8, "拼2次": 1.2, "拼3次": 1.6, "花边": 0.6, "铅坠": 0.3, "接高": 1.0,
    "帘头制作": 2.0, "熨烫": 0.35, "定型": 0.4, "复烫": 0.35, "车被": 0.4,
    "外帘打卷": 1.0, "外帘装袋": 1.0, "质检": 1.5, "外帘发货": 1.0, "绑带": 0.5,
    "抱枕": 2.0, "腰靠垫": 2.0, "logo条": 0.6, "立边": 0.5, "扣环": 0.3, "防翘扣": 0.2,
    # issue #4529：两道「**适用但未定价**」的工序（`unit_price is None` ≠ 0 元）
    "配料": None, "打包": None,
}

# ── ⑤ 规则表 26 条；元组 = (触发值, 动作, 工序, 锚点)，**无 position**（#4937 / O2）──
EXPECTED_CRAFT_RULES = [
    ("韩褶", "insert", "韩褶", "三边"),
    ("韩褶", "insert", "上车布", "韩褶"),
    ("打孔", "insert", "打孔", "三边"),
    ("四爪钩", "insert", "上车布", "三边"),
    ("四爪钩", "remove", "定型", None),
    ("四爪钩", "remove", "复烫", None),
    ("穿杆", "remove", "定型", None),
    ("穿杆", "remove", "复烫", None),
    ("平幔", "insert", "帘头制作", "三边"),
    ("平幔", "remove", "复烫", None),
]
EXPECTED_OPTION_RULES = [
    ("拼1次", "insert", "拼1次", "三边"),
    ("拼2次", "insert", "拼2次", "三边"),
    ("拼3次", "insert", "拼3次", "三边"),
    ("加花边", "insert", "花边", "三边"),
    ("加铅块", "insert", "铅坠", "三边"),
    ("接高", "insert", "接高", "精裁"),
    ("双眼皮接高", "insert", "接高", "精裁"),
    ("余料做绑带", "insert", "绑带", "车被"),
    ("布绑带", "insert", "绑带", "车被"),
    ("余料做帘头", "insert", "帘头制作", "三边"),
    ("抱枕", "insert", "抱枕", "外帘打卷"),
    ("纱绑带", "insert", "绑带", "车被"),
    ("加logo条", "insert", "logo条", "三边"),
    ("加立边", "insert", "立边", "三边"),
    ("扣环", "insert", "扣环", "三边"),
    ("防翘扣", "insert", "防翘扣", "三边"),
]


def _rule_key(rule) -> tuple:
    """规则 → 业务键元组（不含 id / priority / status：优先级由 `TestRuleOrdering` 单独钉）。"""
    return (rule["trigger_value"], rule["action"], rule["operation"], rule["after_operation"])


def _rules_of(kind: str) -> list:
    return [_rule_key(r) for r in ROUTE_RULES if r["trigger_kind"] == kind]


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1：**部位无关的冻结重建**（#4937 的新基线；取代旧的 9/9「与旧结构逐字相等」）
# ══════════════════════════════════════════════════════════════════════════════════

class TestPositionFreeRebuild:
    """`build_route_v2` 对 15 个 `(帘种, 工艺)` 组合的产出 = 冻结序列，且**部位无关**。"""

    @pytest.mark.parametrize("curtain_type,craft", sorted(EXPECTED_REBUILT))
    def test_rebuild_matches_frozen_expectation(self, curtain_type, craft):
        """新真值源 ↔ **冻结期望**（硬编码在文件内，不从实现推导）。"""
        got = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        expected = EXPECTED_REBUILT[(curtain_type, craft)]
        assert got == expected, (
            f"{curtain_type}×{craft} 重建结果与冻结期望不一致（含顺序）：\n"
            f"  实测 = {got}\n  期望 = {expected}")

    @pytest.mark.parametrize("curtain_type,craft", sorted(EXPECTED_REBUILT))
    def test_rebuild_sequence_length(self, curtain_type, craft):
        """道数逐条钉死（布帘 12/11/9/8/10；非布帘的韩褶少一道 = 部位限定的 `上车布`）。"""
        got = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        assert len(got) == EXPECTED_COUNTS[(curtain_type, craft)], (
            f"{curtain_type}×{craft} 道数 {len(got)} ≠ {EXPECTED_COUNTS[(curtain_type, craft)]}")

    def test_position_limited_rule_fires_only_on_its_own_position(self):
        """🔴 **本单的核心判据（issue #4962）**：带 `position` 的规则**只在逐字匹配的部位**生效。

        - `韩褶 → insert 上车布`（`position='布帘'`）⇒ **布帘必须生效**、**纱帘/帘头必须不生效**；
        - `四爪钩 → insert 上车布`（`position` 为空 = **不限部位**）⇒ 三个帘种**都**生效
          （反向护栏：不得把「有空值的规则」也一起筛掉 —— 那会静默少工序）。
        """
        cloth = build_route_v2({"curtain_type": "布帘", "craft": "韩褶"})
        assert "上车布" in cloth, (
            "布帘×韩褶 少了部位限定规则插入的 `上车布` ⇒ 规则对**该生效的部位**没生效")
        for other in ("纱帘", "帘头"):
            seq = build_route_v2({"curtain_type": other, "craft": "韩褶"})
            assert "上车布" not in seq, (
                f"{other}×韩褶 带上了 `上车布` ⇒ 部位限定没生效（改前实测就是这一形态："
                f"筛选不存在 ⇒ 规则对所有部位都生效）：{seq}")
        # 反向护栏：`position` 为空 = 不限部位 ⇒ 仍然对所有帘种生效
        for ct in CURTAIN_TYPES:
            assert "上车布" in build_route_v2({"curtain_type": ct, "craft": "四爪钩"}), (
                f"{ct}×四爪钩 少了 `上车布`（那条规则的 `position` 为空 = 不限部位）"
                f" ⇒ 判据把空值也一起筛掉了")

    def test_only_the_position_limited_rules_diverge_across_curtain_types(self):
        """分叉面**只有**带 `position` 的规则：其余工艺在三个帘种上序列**逐字相同**（#4937 不回退）。"""
        for craft in CRAFTS:
            routes = {ct: tuple(build_route_v2({"curtain_type": ct, "craft": craft}))
                      for ct in CURTAIN_TYPES}
            if craft == POSITION_LIMIT_RULE[1]:
                assert len(set(routes.values())) == 2, (
                    f"工艺 `{craft}` 期望恰好两套序列（布帘 / 非布帘），实测："
                    f"{ {ct: list(r) for ct, r in routes.items()} }")
                assert routes["纱帘"] == routes["帘头"], (
                    "两个**非布帘**帘种之间又分叉了 ⇒ 部位限定不是「逐字匹配布帘」这一条判据在起作用")
            else:
                assert len(set(routes.values())) == 1, (
                    f"工艺 `{craft}` 在不同帘种上得到不同序列 ⇒ 部位仍在别处参与取路："
                    f"{ {ct: list(r) for ct, r in routes.items()} }")

    def test_fifteen_combinations_all_rebuilt_verbatim(self):
        """一次性汇总 15/15（PR 证据里贴的就是这条的输出原文）。"""
        report, mismatched = [], []
        for key in sorted(EXPECTED_REBUILT):
            got = build_route_v2({"curtain_type": key[0], "craft": key[1]})
            expected = EXPECTED_REBUILT[key]
            ok = got == expected
            report.append(f"{key[0]}×{key[1]} {len(got)}/{len(expected)} {'OK' if ok else 'NG'}")
            if not ok:
                mismatched.append(key)
        print("\n逐字重建 15/15 结果：\n  " + "\n  ".join(report))
        assert not mismatched, f"以下组合重建不一致：{mismatched}"
        assert len(report) == 15

    def test_fabric_route_starts_from_the_fabric_mainline(self):
        """布料单（`saleForm=布料`）的**主线基底** = `FABRIC_MAINLINE_STEPS`（产品形态分支）。

        ⚠️ 工艺规则**照旧应用**（它们是「工艺」维的，与帘种/部位无关 —— 用户裁定的语义正是
        「部位不再参与取路」，不是「规则不生效」）。所以判据落在**包裹关系**上：
        结果必须**以布料主线为子序列**（顺序保持），而不是「等于布料主线」。
        """
        for craft in CRAFTS:
            got = build_route_v2({"curtain_type": "布料", "craft": craft})
            assert self._is_subsequence(FABRIC_EXPECTED, got), (
                f"布料单 × {craft} 的序列 = {got}，未以布料主线 `{FABRIC_EXPECTED}` 为子序列 ⇒ "
                f"主线基底被换成了窗帘主线（产品形态分支失效）")
        # `穿杆` 没有 insert 规则（只有两条 remove，且布料主线里没有那两道）
        assert build_route_v2({"curtain_type": "布料", "craft": "穿杆"}) == FABRIC_EXPECTED, (
            "布料单 × 穿杆 应恰好等于布料主线（该工艺无 insert 规则）")

    @staticmethod
    def _is_subsequence(needle, haystack) -> bool:
        it = iter(haystack)
        return all(any(x == n for x in it) for n in needle)


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 2：逻辑工序名映射（35 → 28；7 组部位变体）
# ══════════════════════════════════════════════════════════════════════════════════

class TestLogicalNames:
    def test_mapping_is_frozen_verbatim(self):
        """映射逐条等于冻结值（不从实现推导）—— 35 条冻结段 + 4 条纱帘段 → 28 个逻辑名。"""
        assert OPERATION_LOGICAL_NAMES == EXPECTED_LOGICAL_NAMES

    def test_frozen_segment_is_exactly_thirty_five(self):
        """🔴 **冻结段恰好 35 条**（被 `test_logical_name_single_source_guard.py` 逐条钉住）。

        issue #4937 的 4 道纱帘变体**必须**落在冻结段之外（否则那条守卫当场红）——
        本判据把「分段纪律」也钉住（注入：把纱帘变体并回冻结段 ⇒ 红）。
        """
        from app.production.routing import _LOGICAL_NAME_PAIRS
        assert len(_LOGICAL_NAME_PAIRS) == 35, (
            f"冻结段 = {len(_LOGICAL_NAME_PAIRS)} 条，期望 35 —— issue #4937 的 4 道纱帘变体"
            f"落在 `_SHEER_VARIANT_PAIRS` 那一段，不得并回本段")
        assert dict(_LOGICAL_NAME_PAIRS) == FROZEN_LOGICAL_NAMES

    def test_mapping_covers_the_catalog_exactly(self):
        """键集 == `OPERATION_CATALOG` 的**全部**条目（漏一个 ⇒ 某道工序无逻辑名）。"""
        # 🔴 issue #4937：`配料`/`打包`（本身即逻辑名）+ 4 道纱帘变体**都有**条目 ⇒
        # 排除集只剩「名字本身就是逻辑名」那两道。
        assert set(OPERATION_LOGICAL_NAMES) == set(OPERATION_CATALOG) - {"配料", "打包"}
        assert len(OPERATION_LOGICAL_NAMES) == 39
        assert len(set(OPERATION_LOGICAL_NAMES.values())) == 28

    @pytest.mark.parametrize("logical,olds", sorted(VARIANT_GROUPS.items()))
    def test_variant_group_members_map_to_the_group_name(self, logical, olds):
        """7 组部位变体：每个旧名都映射到组名（`韩褶-布`/`韩褶-纱` → `韩褶`）。"""
        assert {OPERATION_LOGICAL_NAMES[old] for old in olds} == {logical}

    @pytest.mark.parametrize("logical,olds", sorted(VARIANT_GROUPS.items()))
    def test_variant_group_shares_group_and_unit(self, logical, olds):
        """同组各变体的 `group_name` / `unit` **必须一致** —— 否则「同一道工序」不成立。"""
        attrs = {old: (OPERATION_CATALOG[old]["group"], OPERATION_CATALOG[old]["unit"]) for old in olds}
        assert len(set(attrs.values())) == 1, f"{logical} 组内变体的 group/unit 不一致：{attrs}"

    def test_variant_groups_are_exactly_the_seven(self):
        """恰好 7 组、每组 2 个变体（多一组/少一组都红）。"""
        grouped = {}
        for old, logical in OPERATION_LOGICAL_NAMES.items():
            grouped.setdefault(logical, []).append(old)
        multi = {k: sorted(v) for k, v in grouped.items() if len(v) > 1}
        # 🔴 issue #4937：4 道纱帘变体让 `熨烫/定型/复烫/车被` 也成了「多条目」组
        # ⇒ 期望随真值源收敛（多一组/少一组都红）。
        assert set(multi) >= set(VARIANT_GROUPS), (
            f"7 组部位变体必须仍在：缺 {sorted(set(VARIANT_GROUPS) - set(multi))}")
        assert set(multi) == set(VARIANT_GROUPS) | {"熨烫", "定型", "复烫", "车被"}, (
            f"多条目组集合漂移：{sorted(multi)}")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 3：逻辑工序价目 **30 行**（单键），`applicable` 恒 True，**不发明单价**
# ══════════════════════════════════════════════════════════════════════════════════

class TestPositionPrices:
    def test_matrix_is_thirty_rows_by_logical_operation(self):
        """**30 道逻辑工序 × 1 行**（issue #4937：部位维退场 ⇒ 单键）。

        ⚠️ 这里是**基线换代**：旧基线是 `30 × 4 = 120` 的两级索引
        （`OPERATION_POSITION_PRICES[工序][部位]`）。部位退场 ⇒ 只按逻辑工序建键，
        与 `V104__deposition_matrix_collapse.sql` / `docs/sql/schema.sql` 的终态一致。
        """
        assert set(OPERATION_POSITION_PRICES) == set(LOGICAL_UNIT_PRICES)
        assert len(OPERATION_POSITION_PRICES) == 30, (
            f"价目行数 = {len(OPERATION_POSITION_PRICES)}，期望 30（一道逻辑工序一行）")
        for logical, cell in OPERATION_POSITION_PRICES.items():
            assert set(cell) == {"unit_price", "applicable"}, (
                f"{logical} 的字段集 = {sorted(cell)}（必须显式落 unit_price + applicable）")

    @pytest.mark.parametrize("logical", sorted(LOGICAL_UNIT_PRICES))
    def test_price_matches_frozen_value(self, logical):
        """单价逐条等于冻结值（**不发明单价**；含「未定价」= `None`）。"""
        cell = OPERATION_POSITION_PRICES[logical]
        expected = LOGICAL_UNIT_PRICES[logical]
        if expected is None:
            assert cell["unit_price"] is None, (
                f"{logical} 落了价 {cell['unit_price']} —— 冻结口径是「留空待商家配」")
        else:
            assert cell["unit_price"] == expected, (
                f"{logical} 单价 {cell['unit_price']} ≠ 实证值 {expected}")

    def test_applicable_is_uniformly_true(self):
        """🔴 `applicable` 恒 `True`（#4937：它**不再是筛选器**，只是「这一行承载这道工序」）。"""
        offenders = {logical: cell["applicable"]
                     for logical, cell in OPERATION_POSITION_PRICES.items()
                     if cell["applicable"] is not True}
        assert offenders == {}, (
            f"价目里出现了 `applicable != True` 的行：{offenders} —— "
            "部位维退场后该列不再区分任何行")

    def test_no_invented_prices(self):
        """**不发明单价**：逻辑单价逐条能从 `OPERATION_CATALOG`（旧真值源）溯源。"""
        for old, logical in OPERATION_LOGICAL_NAMES.items():
            expected = LOGICAL_UNIT_PRICES[logical]
            if expected is None:
                continue
            assert OPERATION_CATALOG[old]["unit_price"] == expected, (
                f"{old} 的旧单价 {OPERATION_CATALOG[old]['unit_price']} ≠ 新逻辑单价 {expected}"
                f" ⇒ 新模型发明/篡改了单价")

    def test_no_invented_operations(self):
        """**不发明工序**：主线与规则里的工序名/锚点都必须在 30 道逻辑工序集合内。"""
        logical_set = set(LOGICAL_UNIT_PRICES)
        assert set(ROUTE_MAINLINE_STEPS) <= logical_set
        assert set(FABRIC_MAINLINE_STEPS) <= logical_set
        for rule in ROUTE_RULES:
            assert rule["operation"] in logical_set, f"规则引用了不存在的工序：{rule}"
            assert rule["after_operation"] is None or rule["after_operation"] in logical_set, \
                f"规则锚点不是逻辑工序名：{rule}"

    def test_mainline_is_the_frozen_ten(self):
        """主线 = 落库的 **10** 道（9 道 + `打包`，issue #4529）；模板名 = 用户可命名的默认名。"""
        assert ROUTE_MAINLINE_STEPS == MAINLINE
        assert ROUTE_MAINLINE_STEPS.count("打包") == 1, "`打包` 在主线上必须恰好 1 行"
        assert ROUTE_TEMPLATE_NAME_DEFAULT == "窗帘工序路线（默认）"
        assert FABRIC_MAINLINE_STEPS == FABRIC_EXPECTED


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 4：规则表 26 条（工艺 10 + 特殊选项 16），**无 position**
# ══════════════════════════════════════════════════════════════════════════════════

class TestRouteRules:
    def test_rule_count_and_kinds(self):
        """恰好 26 条：工艺 10 + 特殊选项 16；无第三种触发类型。"""
        assert len(ROUTE_RULES) == 26
        kinds = [r["trigger_kind"] for r in ROUTE_RULES]
        assert kinds.count("craft") == 10
        assert kinds.count("option") == 16
        assert set(kinds) == {"craft", "option"}

    def test_exactly_one_rule_carries_a_position_key(self):
        """🔴 **部位维加回**（issue #4962）：26 条里**恰好一条**带 `position`，且值逐字冻结。

        `V71` 的 26 条种子行里只有 `rr-v70-02`（`韩褶 → insert 上车布`）带 `position='布帘'`；
        其余 25 条**不得**有该键（有 = 多出一条部位限定，会静默改变别的帘种的工序集）。
        """
        with_position = [(r["trigger_kind"], r["trigger_value"], r["action"], r["operation"],
                          r["position"]) for r in ROUTE_RULES if "position" in r]
        assert with_position == [POSITION_LIMIT_RULE], (
            f"带 `position` 的规则集漂移（期望恰好 {[POSITION_LIMIT_RULE]}）：{with_position}")

    def test_position_key_uses_the_same_value_as_the_migration_seed(self):
        """部位值与迁移/字面量种子**同值**（`V71` 的 `rr-v70-02` = `'布帘'`）。

        三源（本表 / `V108` 写回 / `docs/sql/schema.sql`）由
        `tests/unit_ci_workflows/test_production_catalog_seed.py` 另钉；本条钉**真值源自己**。
        """
        limited = [r for r in ROUTE_RULES if "position" in r]
        assert [r["position"] for r in limited] == [POSITION_LIMIT_POSITION] == ["布帘"]

    def test_craft_rules_are_frozen_verbatim(self):
        """10 条工艺规则逐条等于冻结值（触发键 = ERP 工艺名，逐字一致）。"""
        assert _rules_of("craft") == EXPECTED_CRAFT_RULES

    def test_option_rules_are_frozen_verbatim(self):
        """16 条特殊选项规则逐条等于冻结值（工序名与锚点**都归一为逻辑名**）。"""
        assert _rules_of("option") == EXPECTED_OPTION_RULES

    def test_option_rules_are_the_migration_of_special_option_routings(self):
        """16 条 = `SPECIAL_OPTION_ROUTINGS` 逐条搬迁 —— 键集与「归一后的工序/锚点」双向一致。"""
        migrated = {opt: ("insert",
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


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 5：`ROUTINGS` / `build_routing` 的**去部位化**（#4937 / P2）
# ══════════════════════════════════════════════════════════════════════════════════

class TestRoutingTableIsPositionFree:
    """`ROUTINGS` 从 9 条 `(部位, 工艺)` 收敛为 **5 条工艺**；`build_routing` 不再按部位查表。

    ⚠️ 本类**取代**了旧的 `TestZeroBehaviourChange`（判据曾是「旧 `ROUTINGS` 一字未动 /
    `build_routing` 输出逐字不变」）—— 那条基线随用户 2026-09-21 裁定退休（母单 #4936）。
    """

    def test_routings_is_keyed_by_craft_only(self):
        """键集 = 5 个工艺（**不得**残留 `(部位, 工艺)` 元组键）。"""
        assert set(ROUTINGS) == set(CRAFTS), (
            f"`ROUTINGS` 的键集 = {sorted(ROUTINGS)}，期望 5 个工艺 {sorted(CRAFTS)}")
        assert all(isinstance(k, str) for k in ROUTINGS), (
            f"仍有非字符串键（旧 `(部位, 工艺)` 形态）：{[k for k in ROUTINGS if not isinstance(k, str)]}")

    @pytest.mark.parametrize("craft,olds", [
        ("韩褶", ["精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
                  "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货"]),
        ("打孔", ["精裁-布", "布三边", "打孔-布", "熨烫-布",
                  "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货"]),
        ("四爪钩", ["精裁-布", "布三边", "上车布-布", "熨烫-布",
                    "布帘车被", "外帘打卷", "外帘装袋", "外帘发货"]),
        ("穿杆", ["精裁-布", "布三边", "熨烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货"]),
        ("平幔", ["精裁-布", "布三边", "帘头制作", "定型-布",
                  "外帘打卷", "外帘装袋", "外帘发货"]),
    ])
    def test_route_content_is_frozen_verbatim(self, craft, olds):
        """每条工艺的基准序列**逐字**等于冻结值（工序名与顺序都钉死）。"""
        assert ROUTINGS[craft] == olds, f"工艺 `{craft}` 的序列漂移：{ROUTINGS[craft]}"

    @pytest.mark.parametrize("curtain_type", CURTAIN_TYPES)
    def test_build_routing_ignores_the_curtain_type(self, curtain_type):
        """`build_routing` 在任何帘种上返回**同一条**序列（部位不再参与查表）。"""
        got = build_routing({"curtain_type": curtain_type, "craft": "韩褶"})
        assert got == ROUTINGS["韩褶"], (
            f"{curtain_type}×韩褶 的 `build_routing` 结果 ≠ 工艺基准序列 ⇒ 部位仍在参与查表：{got}")

    def test_unknown_craft_is_rejected(self):
        """未知**工艺** ⇒ 显式 `ValueError`（不静默回落到别的工艺）。"""
        with pytest.raises(ValueError):
            build_routing({"curtain_type": "布帘", "craft": "波浪褶"})

    def test_shape_switch_removes_shaping_operations(self):
        """定型=否 ⇒ 移除 `定型-布`/`复烫-布`（**工艺级**开关，不再表述为「部位级」）。"""
        route = build_routing({"curtain_type": "布帘", "craft": "韩褶", "is_shaped": False})
        assert "定型-布" not in route and "复烫-布" not in route
        assert "韩褶-布" in route


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 6：特殊选项规则 ⇒ 条件工序落位
# ══════════════════════════════════════════════════════════════════════════════════

class TestSpecialOptionsRebuild:
    """勾一个特殊选项 ⇒ 条件工序落在与旧实现**相同**的相对位置（P2 切换的行为护栏）。"""

    BASE = {"curtain_type": "布帘", "craft": "韩褶"}

    @pytest.mark.parametrize("option", sorted(SPECIAL_OPTION_ROUTINGS))
    def test_option_rule_inserts_at_the_same_relative_position(self, option):
        """16 个选项**全部**逐条比对。

        旧基线把 `余料做帘头` 排除在外（它插入的 `帘头制作` 会被部位适用性滤掉）；
        #4937 之后那层过滤已退场 ⇒ **不再有例外**，判据覆盖面反而变大。
        """
        old = [OPERATION_LOGICAL_NAMES[op]
               for op in build_routing({**self.BASE, "special_options": [option]})]
        new = build_route_v2({**self.BASE, "special_options": [option]})
        # 旧实现的 9 条快照里没有 `打包`（V79 才加）⇒ 按主线补上再比（口径归一，不是放宽）
        if "打包" not in old and "外帘装袋" in old:
            idx = old.index("外帘装袋")
            old = old[:idx] + ["打包"] + old[idx:]
        assert new == old, f"选项「{option}」的条件工序位置与旧实现不一致：\n  新 = {new}\n  旧 = {old}"

    def test_yield_curtain_head_option_is_no_longer_filtered(self):
        """🔴 **规格张力已消解**（#4937）：`余料做帘头` 不再被「部位适用性」滤掉。

        旧基线（本文件旧版）如实登记过一条张力：`帘头制作` 的冻结适用性是 `{帘头}`，
        而该选项把它插进**布帘**路线 ⇒ 新模型会把它滤掉、旧实现会保留 ⇒ 那道工序会从
        布帘订单上消失（少发工人钱）。#4937 把适用性过滤整块删掉 ⇒ 张力消失。
        """
        option = "余料做帘头"
        new = build_route_v2({**self.BASE, "special_options": [option]})
        assert "帘头制作" in new, (
            "`余料做帘头` 插入的 `帘头制作` 又被滤掉了 ⇒ 部位适用性过滤没有真正退场")
        assert new.index("帘头制作") == new.index("三边") + 1, f"落位漂移：{new}"

    def test_option_trigger_is_exact_match_not_substring(self):
        """触发键是**精确匹配**：`拼1次加强版` 不得命中 `拼1次` 规则（防 contains 式错配）。"""
        assert build_route_v2({**self.BASE, "special_options": ["拼1次加强版"]}) == \
            build_route_v2(self.BASE)

    def test_unknown_craft_yields_mainline_only(self):
        """未知工艺 ⇒ 只有主线（不静默套用别的工艺规则、也不再有「适用性」那一层）。"""
        assert build_route_v2({"curtain_type": "纱帘", "craft": "罗马帘"}) == MAINLINE


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 7：注入式自证（每条判据都要能红）
# ══════════════════════════════════════════════════════════════════════════════════

class TestInjectedDrift:
    """「不会红的断言 = 空断言」：逐条注入漂移，证明上面的比对**真能**照出来。"""

    def _rebuild(self, key):
        return build_route_v2({"curtain_type": key[0], "craft": key[1]})

    def test_missing_rule_is_detected(self, monkeypatch):
        """少一条规则（`韩褶 + insert 上车布`）⇒ 韩褶 少一道。"""
        import app.production.routing as routing
        pruned = [r for r in ROUTE_RULES
                  if not (r["trigger_value"] == "韩褶" and r["operation"] == "上车布")]
        assert len(pruned) == 25
        monkeypatch.setattr(routing, "ROUTE_RULES", pruned)
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_BY_CRAFT["韩褶"]

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
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_BY_CRAFT["韩褶"]

    def test_wrong_operation_name_is_detected(self, monkeypatch):
        """规则工序名写错（`韩褶` → 另一个**存在但不对**的逻辑工序 `打孔`）⇒ 重建序列不等。"""
        import app.production.routing as routing
        drifted = [dict(r) for r in ROUTE_RULES]
        for rule in drifted:
            if rule["trigger_value"] == "韩褶" and rule["operation"] == "韩褶":
                rule["operation"] = "打孔"
        monkeypatch.setattr(routing, "ROUTE_RULES", drifted)
        assert self._rebuild(("布帘", "韩褶")) != EXPECTED_BY_CRAFT["韩褶"]

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

    def test_dropping_the_position_limit_is_detected(self, monkeypatch):
        """🔴 **部位限定的红证**（issue #4962）：把那唯一一条 `position` 删掉 ⇒ 纱帘路线多出 `上车布`。

        这是 `test_position_limited_rule_fires_only_on_its_own_position` 的**判别力证明**：
        证明那条断言真的在测「部位限定」，而不是恰好恒真（**改前实测**就是本条注入后的形态：
        筛选不存在 ⇒ 规则对所有部位都生效）。
        """
        import app.production.routing as routing
        drifted = [{k: v for k, v in r.items() if k != "position"} for r in ROUTE_RULES]
        assert not any("position" in r for r in drifted), "注入没生效 ⇒ 本条红证是空断言"
        monkeypatch.setattr(routing, "ROUTE_RULES", drifted)
        sheer = routing.build_route_v2({"curtain_type": "纱帘", "craft": "韩褶"})
        assert "上车布" in sheer, (
            "去掉 `position` 后纱帘路线仍没有 `上车布` ⇒ 本条注入没有再现实测形态")
        assert list(EXPECTED_REBUILT[("纱帘", "韩褶")]) != sheer, (
            "注入后与冻结期望相同 ⇒ 冻结期望本身没有把「少一道」判出来")

    def test_logical_name_mapping_drift_is_detected(self):
        """映射漂移（`纱三边` → `三边-纱`）⇒ 与冻结映射不等。"""
        drifted = dict(EXPECTED_LOGICAL_NAMES)
        drifted["纱三边"] = "三边-纱"
        assert drifted != EXPECTED_LOGICAL_NAMES
        assert drifted["纱三边"] != OPERATION_LOGICAL_NAMES["纱三边"]

    def test_extra_price_row_is_detected(self):
        """价目表多一行 ⇒ 行数判据红（`len(...) == 30` 不是装饰）。"""
        extra = dict(OPERATION_POSITION_PRICES)
        extra["不存在的工序"] = {"unit_price": 1.0, "applicable": True}
        assert len(extra) != 30

    def test_widening_the_position_limit_is_detected(self, monkeypatch):
        """反向红证：把那条规则的 `position` 从 `布帘` 改成 `帘头` ⇒ 布帘路线**少** `上车布`。

        证明部位值是**逐字相等**判据（不是「有 position 就生效」这种恒真写法）。
        """
        import app.production.routing as routing
        drifted = [dict(r, position="帘头") if "position" in r else dict(r) for r in ROUTE_RULES]
        monkeypatch.setattr(routing, "ROUTE_RULES", drifted)
        cloth = routing.build_route_v2({"curtain_type": "布帘", "craft": "韩褶"})
        assert "上车布" not in cloth, "改了部位值布帘路线仍带 `上车布` ⇒ 判据不是逐字相等"
        assert "上车布" in routing.build_route_v2({"curtain_type": "帘头", "craft": "韩褶"})
