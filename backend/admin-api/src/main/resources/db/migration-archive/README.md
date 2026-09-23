# 归档的历史迁移链（只读，issue #5243）

本目录是 admin-api 的**历史迁移链**（`V1` … 归档时的最后一条）—— #5243 之前它们在
`backend/admin-api/src/main/resources/db/migration/`。

## 🔴 只读：逐字节冻结

这些文件的内容由 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 账本
**逐字节冻结**（判据 = `tests/unit_ci_workflows/test_migration_immutability.py`）。
改一个字符即红 —— 理由见 `docs/wiki/Database.md` 的「迁移不可变」（台账按**文件名**记，
已应用的迁移整份跳过 ⇒ 改已发布迁移在存量环境**永远不生效**，而静态守卫反而会因此转绿）。

确需变更其中一条，必须走：仓库 owner 的人工确认通道
（评论 `/danger-ack rewrite-migration`，见 `.github/danger_scan.py`）
+ **手工**改账本条目 + PR 里说明理由。

## 为什么整链归档（而不是删掉）

1. **新建库不再靠迁移链**：空库由基线脚本 `db/init/schema.sql` 一次建出终态
   （`MigrationRunner.applyBaseline`：空库 ⇒ 执行后记账；非空库 ⇒ **只记账不执行**）。
   归档链因此退出「建库」职责，但**仍是历史证据**：每一条「当初为什么这么改」都在文件注释里。
2. **判据面仍在射程内**：`tests/unit_ci_workflows/_migration_paths.py` 把「历史链 ∪ 活目录」
   定义成单一事实源，30+ 个守卫照旧按内容扫描本目录（引用存在性、幂等性、种子收敛、
   破坏性 DDL……）。**判据强度一字未改**，只是被扫的文件换了位置。
3. **文件名不许重写**：`schema_migrations` 台账按文件名记；已装库里的键就是这些文件名。

## ⚠️ 文档里引用旧位置的说明（有意为之，不是遗漏）

`docs/design/**` 等**历史设计文档**、`.github/cases/**` 用例文本、以及**建库脚本
`../init/schema.sql` 内部注释**里的 `backend/admin-api/src/main/resources/db/migration/V*.sql`
引用，指的是 **#5243 之前的旧位置** —— 内容是这些文件，逐字节未变
（建库脚本整份与 `origin/main:docs/sql/schema.sql` **逐字节相同**：「搬动不改内容」这条性质
要机械可验；其注释里的旧路径因此**有意**留在原样）。那些文档是**历史证据**，批量改写会把证据链改花，
故**有意保留**；新写的文档请指向本目录（`migration-archive/`）或建库脚本
（`db/init/schema.sql`）。