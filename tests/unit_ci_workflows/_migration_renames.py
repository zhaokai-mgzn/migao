# case_ids: MC-012
"""加工项目录 / 加工费组合的**改名迁移**读取器（单一实现点）。

2026-09-28 用户裁定（逐字）：「**把加工项和加工费组合里面叫韩折的都改成韩褶**」
⇒ 存量库由增量迁移
`backend/admin-api/src/main/resources/db/migration/V139__rename_hanzhe_item_and_fee_keys.sql`
改名（加工项目录名 + 加工费组合成员名 + 组合键重算）；**新建库**由唯一建库脚本
`backend/admin-api/src/main/resources/db/init/schema.sql` 的基线直接种「韩褶」。

## 为什么从迁移里读、不在守卫里另抄一份映射

三处消费者都要把各自的**冻结面**按这次改名带到「今天」（映射的读取**只此一处**，谁都不另抄一份）：

| 守卫 | 它读的冻结面 | 冻结面里的写法 |
|---|---|---|
| `test_processing_catalog_seed.py` | `db/migration-archive/V83__seed_processing_item_catalog.sql`（加工项目录，逐字节冻结） | 名字「韩折」 |
| `test_option_fee_seed.py` | `db/migration-archive/V77__customer_option_unit_price.sql`（91 条合成组合价目，逐字节冻结） | 组合键里含「韩折」 |
| `test_eval_seed_catalog.py` | `db/migration-archive/V83__…sql`（同一份目录）**＋评测种子** `tests/agent_eval/fixtures/{mibao,xiaobu}_eval_seed.sql` | 种子里那 3 条带价夹具的名字要与改名后的目录一致 |

冻结面**不能改**（`migration_fingerprints.json` 逐字节冻结）⇒ 两边都必须「按 V139 的净效果」比较。
若各自抄一份映射，改 V139 时两处会静默漂移；⇒ 映射的读取**只此一处**（同 `_migration_paths.py` 的纪律）。

## 两种「改名」的语义差别（照实登记）

* **真实键**（存量库里的 `processing_fee_combinations.composition_key`）：V139 做的是**规范化重算**
  （去重 + **码点升序** + `+` 连接，与 Java `compositionKey()` 逐字同源）；
* **冻结面里的合成键**（V77 的 91 条 + 生成器）：键序是「基础项 + 叠加特征」，**不是**码点序
  （例：`韩折+超高`）。本模块对它们做的是**逐字替换旧名**（`rename_key`），
  与 V139 在「键里含旧名」这一等价类上对判据等价；两者不混用。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: 包不在路径上时（被 pytest 以包名导入 / 直接脚本运行）显式补一次 —— 同 `_migration_paths.py`。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_ci_workflows._migration_paths import migration_files  # noqa: E402

#: 「韩折」→「韩褶」统一那条**增量迁移**的文件名。
V139_NAME = "V139__rename_hanzhe_item_and_fee_keys.sql"

#: V139 里那条改名语句的形态：`UPDATE processing_items … SET name = '新' … WHERE name = '旧'`
_RENAME_RE = re.compile(
    r"UPDATE\s+processing_items[\s\S]*?SET\s+name\s*=\s*'([^']+)'[\s\S]*?WHERE\s+name\s*=\s*'([^']+)'")


def processing_item_renames() -> dict:
    """从 V139 的 SQL 里读「旧名 → 新名」映射 —— **单一真值 = 迁移本身**。

    缺失 / 读不出 ⇒ `AssertionError`（fail-closed：映射读不到时，依赖它的比对会变成空断言）。
    """
    hits = sorted(migration_files(V139_NAME))
    assert hits, (
        f"未找到增量迁移 {V139_NAME}（应在 `db/migration/`）—— 2026-09-28 的改名裁定没有落码载体")
    pairs = _RENAME_RE.findall(hits[0].read_text(encoding="utf-8"))
    assert pairs, f"{V139_NAME} 里读不出 `SET name = '新' … WHERE name = '旧'` 形态的改名对"
    return {old: new for new, old in pairs}


def rename_name(name: str, renames: dict) -> str:
    """单个名字按映射改名（不在映射里 ⇒ 原样返回）。"""
    return renames.get(name, name)


def rename_names(names, renames: dict) -> tuple:
    """名字列表按映射改名（保持原顺序：合成组合的 `items` 顺序是生成器口径的一部分）。"""
    return tuple(rename_name(n, renames) for n in names)


def rename_key(key: str, renames: dict) -> str:
    """组合键按映射改名（**逐字替换**，不重排 —— 见模块 docstring 的语义差别一节）。"""
    for old, new in renames.items():
        key = key.replace(old, new)
    return key
