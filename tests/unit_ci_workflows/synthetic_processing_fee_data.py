# case_ids: PG-043
"""特殊选项按套计价 / 组合价目的**固定种子合成数据**生成器（issue #4525，设计 §7 R12）。

## 为什么需要「确定性生成器」而不是「一堆写死的行」

设计 §7 的两条硬约束：**① 随机但确定性**（固定种子生成**一次**、把结果写死；运行期随机 ⇒
同一张单两次生成价不同 = 不可复现的定价，且三源收敛守卫会红）；**② 必须带 provenance**
（显式标 `source='synthetic'`，防止测试价被当成真实价目 —— 设计 §1 末：截图 OCR 单价**未采信**）。

⇒ 本模块 = 那个「固定种子」的**唯一实现**。它有两个消费者：
① `V77__customer_option_unit_price.sql`（写进迁移的种子行）；
② `test_option_fee_seed.py` 的守卫（**独立重算**一遍再与迁移/fixture 逐值比对 ⇒
   「两次生成逐值相同」这条判据才有可红性 —— 只把迁移里的数抄进测试是空断言）。

## ⚠️ 这些价格**不代表任何真实定价**（设计 §10.3 照实登记）

固定种子生成，只为让「组合价 × 米数 + Σ 选项价 × 套数」这条算式**逐分可核对**。
真实价目以商家在「加工费管理」里配的为准。

## 本模块现在有**两类**产物（别混读；issue #4566，用户裁定 2026-09-19）

| 产物 | 真值源 | 状态 |
|---|---|---|
| `PROCESSING_CATALOG` → `fixture_items()`（L2 加工项目录，**16 项**） | **ERP 附件**：壁达 ERP「窗帘货号资料」页的加工费 91 项列表（设计 §1 逐条实证） | ✅ **已重建**，与迁移 `V83__seed_processing_item_catalog.sql` 逐条同源 |
| `combination_names()` / `combination_rows()`（组合价目 91 + `缎带` = 92 行） | **确定性枚举的合成集**（`31+31+29`） | ⛔ **仍未重建**（用户裁定：组合价目等 ERP 导出后再做）⇒ 名字**不等于** ERP 真名，是**已知边界** |

⚠️ 读的人请注意：`fixture_items()` 的名字 / `craftHint` 是**照抄 ERP 附件的真实数据**；
而 `combination_names()` 的名字是**合成枚举**（形态像、但那份 91 项清单不是 ERP 的 91 项）
—— 两者**不要互相当真值**。

## 设计文档与代码事实的两处冲突（**以代码事实为准，显式登记**）

1. **特殊选项价 = 16 项，不是 19 项**。设计 §7 写「19 项」，但 §4.1 同时冻结
   「非 `option` 行一律 `NULL`（工艺变体不按套收费）」。而 19 项特殊选项里
   **只有 16 项**在 `production_route_rules` 里是 `trigger_kind='option'` 行：
   `余料带回-布` / `余料带回-纱` 属 `NON_PIECEWORK_OPTIONS`（不计件、**无规则行**），
   `一分为二` 只有 `action='factor'` 的计件系数档（计件语义，非对客价）。
   ⇒ 对客单价只落在**这 16 条 `option` 行**上；那 3 项**不造规则行**（造了就违反 §4.1 与 R11 的边界）。
   这是**事实优先**的取舍，不是漏做 —— 见 `test_option_fee_seed.py::test_priced_option_rows_are_exactly_the_option_rules`。
2. **组合价目 92 行的逐行内容**：设计 §1 明说截图 OCR **不可作为改钱的数据源**，
   §7 只冻结了「92 行（91 组合 + 缎带）」「3.00~15.00 元/米」两条。⇒ 91 个组合名由本模块
   按 §1.5 的 12 个特征 + `缎带` **确定性枚举**（基础项 1 项 / 两项组合 30 / 三项组合 60），
   价格按固定种子随机 —— 与 §10.3「测试价随机生成」一致，**不假装**是 ERP 原始清单。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

#: 固定种子（= issue 号，**不许改**：改它 ⇒ 全部价目漂移 ⇒ 守卫与迁移/fixture 同时红）
SEED = 4525

#: provenance 词表（V68 `processing_fee_combinations.source` / `production_operations.source` 同词表）。
#: 测试价**必须**显式标 synthetic —— 缺它 = 测试价可能被当成真实价目（设计 §7 硬约束 ②）。
SOURCE = "synthetic"

#: 加工费组合的定价区间（元/米）—— 设计 §7 冻结。
COMBO_MIN, COMBO_MAX = 300, 1500          # 单位：分（避开浮点，逐分可核对）

#: 特殊选项（对客）的定价区间（元/套）—— 设计 §7 冻结。
OPTION_MIN, OPTION_MAX = 100, 1000        # 单位：分

#: 基础加工特征（设计 §1.5「组合名里的特征集合」，逐字 ERP 写法）。
BASE_FEATURES = ("打孔", "韩折", "韩定+S钩")

#: 可叠加特征（同上；`花边` / `扣环` 与特殊选项 `加花边` / `扣环` **名字不同** ——
#: 设计 §6 已登记该相邻性，R11 的护栏按**名字**判交集 ⇒ 两侧不同名不触发 422，如实登记）。
MODIFIERS = ("超高", "超宽", "定型", "花边", "扣环")

#: 组合价目里「单独一行」的额外项（设计 §7：92 = 91 组合 + 缎带）。
STANDALONE = ("缎带",)

#: L2 特征词典里**不出现在组合价目枚举**、但设计 §1.5 逐字点名的特征（`倒幅` 由 `cuttingMode`
#: 唯一推导；`接高` / `拼接` / `双眼皮` 只出现在 ERP 的组合名里，见设计 §5.1/§6 的边界登记）。
#: ⇒ L2 词典 = 3 基础项 + 5 可叠加特征 + 4 本项 = **12**（设计 §1.5 的 12 个特征逐字）
#:   + `缎带` / `换货` = **14** 条（设计 §7 的 L2 行：14 个特征 + 缎带 / 换货）。
DICTIONARY_EXTRA = ("倒幅", "接高", "拼接", "双眼皮")

#: 16 条 `trigger_kind='option'` 规则行的 `trigger_value` → V71 的规则行 id（V78 的落点）。
#: ⚠️ 键 = ERP 逐字写法（真值源 §1 的 19 项里去掉无规则行的 3 项），
#: 错一个字 ⇒ 取价匹配不上 ⇒ **静默少收钱**（同族纪律：不得用 `contains`）。
OPTION_RULE_IDS = {
    "拼1次": "rr-v70-11",
    "拼2次": "rr-v70-12",
    "拼3次": "rr-v70-13",
    "加花边": "rr-v70-14",
    "加铅块": "rr-v70-15",
    "接高": "rr-v70-16",
    "双眼皮接高": "rr-v70-17",
    "余料做绑带": "rr-v70-18",
    "布绑带": "rr-v70-19",
    "余料做帘头": "rr-v70-20",
    "抱枕": "rr-v70-21",
    "纱绑带": "rr-v70-22",
    "加logo条": "rr-v70-23",
    "加立边": "rr-v70-24",
    "扣环": "rr-v70-25",
    "防翘扣": "rr-v70-26",
}

#: 19 项特殊选项里**没有** `trigger_kind='option'` 规则行的 3 项（见模块 docstring 冲突 1）。
UNPRICED_BY_DESIGN = ("余料带回-布", "余料带回-纱", "一分为二")

#: **加工项目录**（L2 特征词典）—— **按 ERP 附件重建**（issue #4566，用户裁定 2026-09-19
#: 「加工项以及加工项费用的数据没有根据这个附件重建，现在立刻重建」）。
#: 真值源 = 壁达 ERP「窗帘货号资料」页加工费 91 项列表的**加工项部分**（设计 §1 逐条实证）。
#: 逐条 `(name, craftHint)`：
#:   * `name` = ERP 逐字写法（**错一个字 ⇒ 与库/迁移对不上**，同族纪律：不得用 `contains`）；
#:   * `craftHint` = **工艺声明**（V78 的 `processing_items.craft_hint`，路线键「工艺」维的受控来源）；
#:     `None` = **商家没声明**（与 V78 的 `NULL` 同语义，**不是**「工艺 = 空」）。
#: ⚠️ `四爪钩` **不在**目录里：它是配件、不是打褶方式（归属 issue #4365 阶段 2）。
#: 唯一真值 = 本常量；`fixture_items()` 与守卫测试都从它派生（守卫另**独立重写**一份对照表）。
PROCESSING_CATALOG = (
    ("打孔", "打孔"),
    ("韩折", "韩褶"),          # 名字是「韩折」、工艺声明是「韩褶」—— **不同字**，别顺手"修"成一致
    ("韩定+S钩", "韩褶"),
    ("穿杆", "穿杆"),
    ("平幔", "平幔"),
    ("定型", None),
    ("花边", None),
    ("扣环", None),
    ("接高", None),
    ("拼接", None),
    ("双眼皮", None),
    ("缎带", None),
    ("换货", None),
    ("超高", None),
    ("超宽", None),
    ("倒幅", None),
)


def money(cents: int) -> str:
    """分 → `'3.00'` 形态的金额字面量（**字符串**，避免浮点尾数进 SQL/JSON）。"""
    return f"{cents // 100}.{cents % 100:02d}"


#: 前两个基础项**全量**取可叠加特征的幂集；第三个只取 ≤3 个的档（**不是**任意截断 ——
#: 见 `combination_names` 的算式：31 + 31 + 28 = 90，+ `缎带` = **91 组合 + 1 = 92 行**）。
_FULL_POWER_SET_BASES = 2


def _subsets(items):
    """`items` 的**非空**子集（按组合长度 → 书写序）—— 确定性枚举，`itertools` 标准库。"""
    from itertools import combinations
    return [combo for size in range(1, len(items) + 1)
            for combo in combinations(items, size)]


def combination_names() -> list:
    """91 个组合名（确定性枚举，**不含** `缎带`）—— 顺序 = 生成顺序，不是匹配键。

    形态（设计 §1.5 的 12 个特征里，12 = 3 基础项 + 5 可叠加特征 + `打孔/韩折/韩定+S钩`
    已计入基础项；余下的 `倒幅` / `接高` / `拼接` / `双眼皮` 只出现在 ERP 的组合名里、
    本方案的组合价目按**基础项 × 可叠加特征**枚举，如实登记）：

    * `打孔` / `韩折`：各自 + 可叠加特征的**全部非空子集** = 2⁵ − 1 = **31**（含基础项自身）；
    * `韩定+S钩`：同样 31 的枚举，去掉 4 项档的后 1 组与 5 项档 ⇒ 31 − 1 − 1 = **29**。

    ⇒ 31 + 31 + 29 = **91**，再加 `STANDALONE` 的 `缎带` = **92 行**（设计 §7 冻结的行数）。
    逐值以 `test_combination_names_are_exactly_91` 的判据为准（本函数是唯一实现）。

    ## ⚠️ 已知边界（issue #4566，**别把本清单当 ERP 真名**）
    本函数是**合成枚举**，**不重建** ERP 附件里的 91 个组合真名（用户裁定：组合价目等 ERP
    导出后再做 ⇒ 本函数**一字不动**）。ERP 真名里有的、本枚举没有的例：`打孔+拼接+倒幅+定型`、
    `韩折+超高+接高+定型`。⇒ 组合价目这一层仍是**测试资产**，不是真实价目。
    """
    names = []
    for index, base in enumerate(BASE_FEATURES):
        subsets = _subsets(MODIFIERS)
        if index >= _FULL_POWER_SET_BASES:
            # 只取 ≤3 个特征的档 + 4 项档的前 4 组 ⇒ 25 + 4 = 29（+1 单基础项 = 30）
            subsets = [c for c in subsets if len(c) <= 3] + \
                      [c for c in subsets if len(c) == 4][:4]
        for combo in subsets:
            names.append("+".join((base,) + combo))
    return names


def combination_rows() -> list:
    """92 行组合价目 → `[{id, name, composition_key, items, unit_price(元/米), source, sort_order}]`。

    顺序 = `combination_names()`（91）+ `STANDALONE`（缎带）⇒ **92 行**。

    ⚠️ **`composition_key` 与 `name` 逐字相同**（`韩定+S钩` 里的 `+` 是**特征名自身**的字符，
    与 `打孔+超高` 里的分隔符同形）⇒ 归一化**不做二次拆分**（拆了会把一个特征名劈成两个假特征，
    并让归一化键与 `ProcessingFeeCombinationCommandService.compositionKey` 的口径分叉）。
    本方案的组合名都是「特征名以 `+` 连接」的**规范形态**（trim 无空项、无重复）⇒ 归一化是恒等变换。
    价格 = 固定种子随机**一次**（`random.Random(SEED)`），结果由调用方**写死**进迁移。

    ⚠️ 已知边界（同 `combination_names`）：`name` 是**合成枚举**名，**不等于** ERP 附件的 91 项
    真名 —— 本方案只换数据、不动结构，真名单待客户导出（issue #4566）。
    """
    rng = random.Random(SEED)
    names = combination_names() + list(STANDALONE)
    rows = []
    for order, name in enumerate(names, start=1):
        rows.append({
            "id": f"pfc-synthetic-{order:03d}",
            "name": name,
            "composition_key": name,
            # `items` 与 `composition_key` **同源**：`韩定+S钩` 是一个特征名（含 `+` 字符）
            # ⇒ 这里按分隔符切出的 2 段是**展示用**的，取价只认 `composition_key`。
            "items": name.split("+"),
            "unit_price": money(rng.randint(COMBO_MIN, COMBO_MAX)),
            "source": SOURCE,
            "sort_order": order,
        })
    return rows


def option_rows() -> list:
    """16 条 `option` 规则行的对客单价 → `[{name, rule_id, unit_price(元/套), source}]`。

    价格 = 固定种子随机**一次**（**另一个** `Random` 实例，种子 `SEED + 1`）——
    与组合价共用同一个流会让「加一行组合」把所有选项价推移（两条序列互相耦合）。
    顺序 = 选项名 **Unicode 码点升序**（确定性；与 `special_options[]` 的排序口径同族）。
    """
    rng = random.Random(SEED + 1)
    rows = []
    for name in sorted(OPTION_RULE_IDS):
        rows.append({
            "name": name,
            "rule_id": OPTION_RULE_IDS[name],
            "unit_price": money(rng.randint(OPTION_MIN, OPTION_MAX)),
            "source": SOURCE,
        })
    return rows


def fixture_items() -> list:
    """`tests/e2e/fixtures/processing-list.json` 的 `data.items` = **按 ERP 附件重建的加工项目录**
    （**16 项，含工艺声明**），与迁移 `V83__seed_processing_item_catalog.sql` **逐条同源**；
    **组合价目仍未重建**（等 ERP 导出，见 `combination_names`）。

    ## 改判记录（issue #4566，用户裁定 2026-09-19「现在立刻重建」）
    本函数**曾经**生成的是「**合成特征名**」（`BASE_FEATURES + MODIFIERS + DICTIONARY_EXTRA`
    的并集 = 14 条、逐条**无工艺声明**）—— 那是 #4525 的形态，**不是** ERP 的加工项目录。
    现在改为照抄 ERP 附件（真值源 = 设计 §1 的 91 项列表里的加工项部分）：16 项 + 每项 `craftHint`。

    ## `craftHint` 缺失口径（**显式 `None`**，不是省略键）—— 二选一已选定
    每一条**都带** `craftHint` 键，无声明者落 `None`（JSON 里是 `null`）。为什么不省略键：
    ① 与 V78 的 `NULL = 商家没声明`（**不是**「工艺 = 空」）同语义 —— 键**存在**才能把「没声明」
    与「键缺失」分开；② 键集恒定 ⇒ e2e 断言 / 前端消费侧不必写「缺键兜底」，也不会某条有、
    某条没有而漂移。守卫 = `test_processing_catalog_seed.py`（缺键即红）。

    ## 为什么 `source` 仍是 `synthetic`
    名字 / `craftHint` 是**真实 ERP 数据**，但本**文档**（`id` / `unitPrice` / 时间戳）仍是
    生成的测试资产 ⇒ 沿用 #4525 的 provenance 纪律（设计 §7 硬约束 ②）。

    ⚠️ 单价**不进** fixture（R10：下单页不展示加工项单价；L2 特征词典无价）—— 但 e2e 的
    `cross-page-consistency` 判据读 `unitPrice` 键存在性，故保留键并置 `0`（= 无价，不是价 0 元）。
    """
    items = []
    for index, (name, craft_hint) in enumerate(sorted(PROCESSING_CATALOG), start=1):
        items.append({
            "id": f"pi-feature-{index:02d}",
            "name": name,
            "categoryId": "pc-feature-dict",
            "categoryName": "特征词典",
            "pricingMethod": "per_meter",
            # 工艺声明（V78）：`None` = 商家没声明（**显式键**，口径见上「craftHint 缺失口径」）
            "craftHint": craft_hint,
            # R10：特征词典**无价**（价格只在组合上存在）⇒ 0 + 下方 source 标 synthetic
            "unitPrice": 0,
            "unit": "米",
            "minQuantity": 1,
            "maxQuantity": 999,
            "description": f"{name}（特征词典条目；价格只在「加工费组合」上，见 R10）",
            "options": [],
            "applicableProductCategories": [],
            "processingDays": 0,
            "aiRecommended": False,
            "status": "active",
            "source": SOURCE,
            "createdAt": "2026-09-19 00:00:00",
            "updatedAt": "2026-09-19 00:00:00",
        })
    return items


def fixture_document() -> dict:
    """完整 fixture 文档（`success` / `data` / `requestId` / `timestamp` 四键，与既有 fixture 同形）。"""
    items = fixture_items()
    return {
        "success": True,
        "data": {
            "total": len(items),
            "page": 1,
            "size": 100,
            "items": items,
        },
        "requestId": "req_synthetic_4525",
        "timestamp": 1789000000,
    }


def main(argv=None) -> int:
    """`--write-fixture` 把 fixture 文档写回 `tests/e2e/fixtures/processing-list.json`。"""
    import sys
    repo = Path(__file__).resolve().parents[2]
    target = repo / "tests/e2e/fixtures/processing-list.json"
    if "--write-fixture" not in (argv or sys.argv[1:]):
        print(json.dumps(fixture_document(), ensure_ascii=False, indent=2)[:400])
        return 0
    target.write_text(
        json.dumps(fixture_document(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 已写入 {target}（{len(fixture_items())} 条加工项目录行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
