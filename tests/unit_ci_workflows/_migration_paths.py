# case_ids: MC-012
"""迁移文件的**两个载体目录**（issue #5243）—— 全仓的单一事实源。

## 形状（改前有四代 SQL 资产，现在只剩一份建库脚本 + 一条归档链）

| 载体 | 路径 | 性质 |
|---|---|---|
| 建库脚本（基线） | `backend/admin-api/src/main/resources/db/init/schema.sql` | **唯一**的一份建库脚本，由 `MigrationRunner` 按基线语义应用（见 `applyBaseline`） |
| 归档链 | `backend/admin-api/src/main/resources/db/migration-archive/` | 历史迁移链（`V1` … 归档时的最后一条），**逐字节冻结**（`test_migration_immutability.py` 的账本） |
| 活目录 | `backend/admin-api/src/main/resources/db/migration/` | **只放未来的增量迁移**（发文时为空，只有 README） |

## ⚠️ 判据面必须**两个目录一起扫**

- 只看归档 ⇒ 新迁移不在射程（门禁对**将来**失效 = 前向防护消失）；
- 只看活目录 ⇒ 今天扫不到任何文件（判据**空转** = 假绿，本仓最忌讳的形态）。

本模块是那条口径的**唯一实现点** —— 下一次搬目录只需改这里。
`schema.sql`（基线）不进迁移扫描：它不是迁移（台账键是文件名 `schema.sql`，见 runner 的
`applyBaseline`），但它的内容由 `test_migration_immutability.py` 的账本**逐字节冻结**。
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 唯一的一份建库脚本（基线；`migao.migration.init-script` 的默认值）
INIT_SCRIPT = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
#: 历史链的归档目录（只读、逐字节冻结）
ARCHIVE_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"
#: 活目录（只放未来的增量迁移）
LIVE_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
#: 兼容既有命名 —— 绝大多数守卫的 `MIGRATION_DIR` 语义就是「历史链所在处」
MIGRATION_DIR = ARCHIVE_DIR
#: 两个载体目录（顺序无关；同名冲突 fail-closed）
MIGRATION_DIRS = (ARCHIVE_DIR, LIVE_DIR)


def migration_files(pattern: str = "*.sql"):
    """两个载体目录里的迁移文件（按文件名排序；同名出现在两处 ⇒ fail-closed）。"""
    found: dict[str, Path] = {}
    for d in MIGRATION_DIRS:
        if not d.is_dir():
            continue
        for p in d.glob(pattern):
            assert p.name not in found, (
                f"迁移文件名在两个载体目录里重复：{p.name}（{found[p.name]} / {p}）")
            found[p.name] = p
    return [found[k] for k in sorted(found)]

def find_migration(filename: str) -> Path:
    """按**文件名**在「归档 ∪ 活目录」里找一个迁移文件；两处都没有 ⇒ **fail-loud**。

    给「判据要读某一条**具体**迁移」的测试用（issue #5243）：那些判据的**意图**
    （这份迁移真的建了/回填了那个东西）在新制度下**一字不变**，只有**定位方式**变了 ——
    绝不允许「路径不存在 ⇒ 静默跳过」（那会让判据变成空断言）。
    """
    for d in MIGRATION_DIRS:
        p = d / filename
        if p.is_file():
            return p
    raise AssertionError(
        f"迁移文件不存在（归档 ∪ 活目录都找不到）：{filename}\n"
        f"  已查：{', '.join(str(d) for d in MIGRATION_DIRS)}\n"
        f"  ⇒ 若它确实被删了，请把判据改成断言它的**效果**（而不是删掉判据）。")
