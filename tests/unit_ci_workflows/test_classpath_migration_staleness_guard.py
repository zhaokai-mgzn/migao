# case_ids: MC-012, API-013
"""陈旧构建产物（classpath 上有、源码树没有）的**类级元守卫**（issue #5981）。

## 为什么要有这一条（与实例判据的分工）

实例判据 = `backend/admin-api/src/test/java/com/migao/admin/config/MigrationRunnerStaleArtifactTest.java`
（跑真实 `MigrationRunner.run()`：陈旧产物 ⇒ 拒启动 + 点名 + 不执行）。
它只证明**当前这一轮**的产物干净 —— 下一次构建产物又脏了，它不会再知道。

本条是**类级元守卫**，判的是**形态**：Maven 构建产物里的 `db/migration/*.sql`
（= `classpath:db/migration/*.sql` 的现取面，`target/classes` 与 `target/test-classes` 都会被
`mvn test` 的 test classpath 扫到）必须**逐名**落在**活目录** `db/migration/`
（见 `tests/unit_ci_workflows/_migration_paths.py`）里。
⇒ 「构建产物里多出一条活目录没有的迁移」**当场红**（= issue #5981 的形态：
已退休迁移的陈旧产物被 classpath 扫到并重跑），而不是等它在启动日志里以 5 条 SQL 失败的样子
冒充产品故障。

⚠️ 参照面**不含**归档目录（`db/migration-archive/`）：架构上归档链**本就不该在 classpath 上**
（`migrationPattern` 只扫 `classpath:db/migration/*.sql`）⇒ 拿整条链当参照面会把 116 条归档文件
全判成"漏拷"（假红）。同一口径写在 `MigrationRunner.assertNoStaleMigrations` 里。

## 口径（三面都要成立，缺一即本条退化成空断言）

1. **非空**：活目录 / 归档目录两份**源码**名单都不得为空（空语料 ⇒ 后面的相等判据恒真）；
2. **产物 ⊆ 源码树**：构建产物里的每个迁移名都必须在源码树里存在 —— 多一条就是陈旧产物（#5981）；
   且**当产物目录存在时**，产物名单不得为空（空产物 = 取名单的实现坏了，不许静默当通过）；
3. **判别力自证**：把一条源码树没有的文件名喂进判据函数 ⇒ 必须在**内存里**当场红并点名，
   喂干净输入 ⇒ 必须绿（对照臂）。

## 边界（照实登记，不粉饰）

- **产物目录是 Maven 的**：本地未跑过 `mvn test` 时 `target/classes|test-classes` 不存在 ⇒
  本判据**显式记为「未跑」并跳过**（打印原因），不假装通过、也不自行触发 Maven 构建
  （那会把 CI 门禁变成"再跑一遍全量套件"，见 `migao-dev-flow` §27 的机器级重活准入）。
  CI 的 `admin-api` 腿在 `mvn test` 之后运行 ⇒ 这一步在那里是真实生效的。
- **只比文件名集合，不比内容**：同名文件的内容漂移不在本条射程；已发布迁移**内容**由
  `tests/unit_ci_workflows/test_migration_immutability.py` 的指纹账本冻结。
- **`target/test-classes` 可能残留**上一轮拷贝、现已删除的 `db/migration/*.sql`（正在跑的
  `mvn test` 会把 test resources 拷进去）⇒ 命中时**先 `mvn clean` 再判**，不要靠改判据消红。
- **本条不跑 Maven、不起 JVM**：纯文件面，秒级、零依赖。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 同目录兄弟模块（`_migration_paths` 等）—— 本目录不是包（无 `__init__.py`），
# 显式把自己加进 `sys.path`（与 `tests/unit_ci_workflows/test_admin_web_devserver_identity.py` 同法）。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _migration_paths import ARCHIVE_DIR, LIVE_DIR, migration_files  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_ADMIN_API = _REPO / "backend" / "admin-api"

#: Maven 构建产物里会被 test classpath 扫到的那两份 `db/migration`（issue #5981 的现场）。
BUILD_MIGRATION_DIRS = (
    _ADMIN_API / "target" / "classes" / "db" / "migration",
    _ADMIN_API / "target" / "test-classes" / "db" / "migration",
)

#: 实例判据（跑真实 `MigrationRunner.run()`）—— 本守卫必须与它成对存在。
INSTANCE_JUDGEMENT = (
    _ADMIN_API / "src" / "test" / "java" / "com" / "migao" / "admin" / "config"
    / "MigrationRunnerStaleArtifactTest.java"
)


def find_classpath_only(build_names: set[str], source_tree: set[str]) -> list[str]:
    """构建产物有、源码树没有 ⇒ 陈旧构建产物（issue #5981 的**形态判据**，唯一实现点）。

    ⚠️ `source_tree` 传**活目录**（`db/migration/`）—— 归档目录（`db/migration-archive/`）
    **本来就不在 classpath 上**（`migrationPattern` 只扫 `classpath:db/migration/*.sql`），
    拿整条链当参照面会把 116 条归档文件全判成"漏拷"（假红）。
    """
    return sorted(build_names - source_tree)


def build_migration_names() -> set[str]:
    """现取构建产物里的迁移名（只认 `*.sql`；目录不存在 ⇒ 空集，由调用方显式记「未跑」）。"""
    names: set[str] = set()
    for d in BUILD_MIGRATION_DIRS:
        if d.is_dir():
            names |= {p.name for p in d.glob("*.sql")}
    return names


def _build_dirs_present() -> list[Path]:
    return [d for d in BUILD_MIGRATION_DIRS if d.is_dir()]


class TestBuildArtifactsCoveredBySourceTree:
    """构建产物 ⇄ 源码树（活目录 ∪ 归档目录）的**形态守卫**（issue #5981）。"""

    def test_source_tree_enumerators_are_not_empty(self):
        """判据 1：两份源码名单都不得为空（空语料 ⇒ 后面的相等判据恒真 = 空断言）。"""
        live = {p.name for p in migration_files() if p.parent == LIVE_DIR}
        archive = {p.name for p in migration_files() if p.parent == ARCHIVE_DIR}
        assert live, (
            f"活目录 {LIVE_DIR} 扫不到任何迁移 —— 「源码树名单」会退化成空集（判据空转）"
        )
        assert archive, (
            f"归档目录 {ARCHIVE_DIR} 扫不到任何迁移 —— issue #5981 的病灶（已退休迁移被重跑）"
            "正是从这份名单来的，空集 = 判据不可能再发现它"
        )
        assert INSTANCE_JUDGEMENT.is_file(), (
            f"实例判据不存在：{INSTANCE_JUDGEMENT}\n"
            "  ⇒ 类级元守卫必须与「跑真实 run() 的会红判据」成对存在（铁律 8），"
            "只有元守卫 = 只判形态、不判行为。"
        )

    def test_build_artifacts_are_covered_by_the_source_tree(self):
        """判据 2：构建产物里的每个迁移名都必须存在于**活目录**（多一条 = #5981 的陈旧产物）。

        参照面 = `db/migration/`（**不含**归档目录）：`migrationPattern` 只扫
        `classpath:db/migration/*.sql`，归档链本来就不该在 classpath 上 ——
        见 `MigrationRunner.assertNoStaleMigrations` 的同一口径。
        """
        dirs = _build_dirs_present()
        if not dirs:
            # 未跑过 Maven ⇒ 显式记「未跑」（不假装通过）：本判据读的就是构建产物
            print(
                "[SKIP] 未发现 Maven 构建产物目录（"
                + " / ".join(str(d) for d in BUILD_MIGRATION_DIRS)
                + "）⇒ 本判据未跑（先跑 `cd backend/admin-api && ./mvnw test` 再判）"
            )
            return

        build = build_migration_names()
        live = {p.name for p in migration_files() if p.parent == LIVE_DIR}

        assert build, (
            f"构建产物目录存在（{[str(d) for d in dirs]}）但扫不到任何 `*.sql` —— "
            "取名单的实现坏了；空集会让下面的断言恒真（假绿），故这里 fail-closed"
        )
        stale = find_classpath_only(build, live)
        assert not stale, (
            "构建产物里有、活目录（源码树）里没有的迁移文件"
            "（= 陈旧产物 / 已退休迁移残留，issue #5981）：\n"
            f"  {stale}\n"
            "  ⇒ 它们会被 `MigrationRunner` 当新迁移重跑，启动日志表现为一堆 SQL 失败（"
            "`column ... does not exist` / `relation ... does not exist` / 唯一键冲突），"
            "看着像产品故障，并污染同一 JVM 的后续请求。\n"
            "  ⇒ 处置：`cd backend/admin-api && ./mvnw clean`（清掉陈旧产物后重跑本判据）。"
        )

    def test_guard_has_discriminating_power_in_memory(self):
        """判据 3：判别力自证 —— 喂一条源码树没有的文件名 ⇒ 当场红且点名；干净输入 ⇒ 绿。"""
        build = {"V1__probe.sql", "V108__restore_route_rule_positions.sql"}
        source_tree = {"V1__probe.sql"}

        assert find_classpath_only(build, source_tree) == [
            "V108__restore_route_rule_positions.sql"
        ], "判据 2 的核心函数对陈旧产物必须报红并点名（否则它只是「看起来在守」）"
        assert find_classpath_only(source_tree, source_tree) == [], (
            "干净输入必须绿（对照臂）—— 否则判据 2 是恒红，不具判别力"
        )
