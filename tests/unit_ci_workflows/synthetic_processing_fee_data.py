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
    """`tests/e2e/fixtures/processing-list.json` 的 `data.items`（**L2 特征词典**，设计 §7）。

    设计 §7 的现状段：现 fixture 的 13 条（`魔术贴安装` / `铅坠安装` / `高温定型`…）**全是编造数据、
    与 ERP 零对应** ⇒ 换成本方案的**真实特征名**：组合价目用到的 12 个特征（§1.5）
    + `缎带` / `换货`（§7 的 L2 行）。
    ⚠️ 单价**不进** fixture（R10：下单页不展示加工项单价；L2 特征词典无价）—— 但 e2e 的
    `cross-page-consistency` 判据读 `unitPrice` 键存在性，故保留键并置 `0`（= 无价，不是价 0 元）。
    """
    features = []
    for name in BASE_FEATURES + MODIFIERS + DICTIONARY_EXTRA + STANDALONE + ("换货",):
        if name not in features:
            features.append(name)
    items = []
    for index, name in enumerate(sorted(features), start=1):
        items.append({
            "id": f"pi-feature-{index:02d}",
            "name": name,
            "categoryId": "pc-feature-dict",
            "categoryName": "特征词典",
            "pricingMethod": "per_meter",
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
    print(f"✅ 已写入 {target}（{len(fixture_items())} 条特征词典行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
