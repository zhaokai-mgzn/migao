# case_ids: PG-018
"""**退休台账**：工艺「四爪钩」的三条规则（issue #4365）—— 全仓的**单一真相源**。

## 裁定（用户原话）

2026-09-27：「**移除四爪钩这个场景**」。依据：真值源 §8 早已冻结「**四爪钩 / 四叉钩**是
**加工项（配件）**，工艺（安装工艺＝打褶/悬挂方式）**单值**」；信号层
（`production_route_signals`，`V63` 终态）也早已把这两个信号指向主线工艺「韩褶」。

## 三个载体各自的用法（为什么需要这份台账）

| 载体 | 现状 | 本台账的作用 |
|---|---|---|
| 真值源 `app/production/routing.py::ROUTE_RULES` | 那三条**已删** | 判据两侧都不许再出现它们 |
| 建库终态 `db/init/schema.sql` | 三个规则种子块各删掉那三行 | 同上 |
| **存量库** `db/migration/V135__retire_craft_sig_hook.sql` | **软删**（`deleted = 1`，留痕可回滚） | 台账 = 该迁移的**射程** |

## 为什么各判据是「显式扣除」而不是「放宽」

迁移侧的字面量（`V71`）与 `V93` 属**归档链**、**逐字节冻结**
（`migration_fingerprints.json`）⇒ **不能改**，它们仍有那 26 行；真正表达终态的是 `V135`。
⇒ 凡「迁移侧 ↔ 真值源 / bootstrap 终态」的逐值比对，都必须按本台账把那 3 行**显式扣除**，
**扣完仍逐条逐值比对**（不是「包含即可」、不是删断言）。

🔴 **扣除必须双向可红**：实际被扣掉的行**必须恰好等于**本台账 ——
多退（V71 里没有的行）/ 少退（漏扣）/ 只改台账不改 `V135` 与两侧终态，**都要让判据变红**。
各判据写法见 `test_production_catalog_seed.py`（`test_route_rules_converge_across_three_sources`）、
`test_v93_route_rules_backfill.py`（`_drop_retired`）、
`test_restore_route_rule_positions_migration.py`（`_retired_ids`）。

## ⚠️ 只许缩短

台账**只许缩短**（真的撤销某条退休时删一行，并让判据跟着收口）；**新增**退休必须同时改
`V135` 与两侧终态，否则上面的双向判据会红。条数一律**现取** `len(...)`，不写死数字。

键形 = `(触发类型, 触发值, 部位, 动作, 工序, 锚点)` —— 与 `route_rule_rows()` 的 6 元组同序
（`None` = SQL `NULL`；`锚点` = `after_operation`）。
"""
from __future__ import annotations

#: 退休的工艺规则行台账（**只许缩短**；条数**现取**，不写死数字）。
#: 键形 = `(触发类型, 触发值, 部位, 动作, 工序, 锚点)`（`None` = SQL `NULL`）。
RETIRED_CRAFT_RULE_KEYS = (
    ("craft", "四爪钩", None, "insert", "上车布", "三边"),
    ("craft", "四爪钩", None, "remove", "定型", None),
    ("craft", "四爪钩", None, "remove", "复烫", None),
)


def retired_rule_keys() -> frozenset:
    """退休台账（**现取**；判据与注入自证共用这一处，避免两套真相源）。"""
    return frozenset(RETIRED_CRAFT_RULE_KEYS)
