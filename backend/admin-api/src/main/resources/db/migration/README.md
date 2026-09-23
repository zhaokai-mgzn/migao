# 未来的增量迁移放这里（issue #5243）

本目录只放**晚于归档切点**的增量迁移。

## 切点是什么（别按「目录空不空」判，按这条判）

**切点 = 建库脚本（`../init/schema.sql`）已经体现其效果的那批迁移的集合。**

| 形态 | 脚本里体现得出来吗 | 归属 |
|---|---|---|
| 结构变更（建表/加列/索引/RLS…） | 能（契约要求建库脚本同步终态，有守卫钉住） | **归档** `../migration-archive/` |
| **纯数据迁移**（撤种子行 / 改存量数据，不动表结构） | **不能**（脚本里没有这一笔） | **留在本目录**，在新库上照常跑一遍 |

⇒ 「本目录非空」**不是**缺陷，也不是待办 —— 它是**设计路径**：新库先由基线脚本建出终态，
再在本目录的迁移上跑一遍。反过来，一条**编号 ≤ 切点**的迁移留在本目录才是缺陷：
`MigrationRunner` 会把本目录里的每一条都当「未来增量」执行，于是它会在**已建出终态的库**上
再跑一遍（且不在 `schema_migrations` 里）—— 正是 #5243 要消灭的「两份真相」。

**机械判据**（会红的，不靠人记得）：

```
min(本目录的版本号) > max(../migration-archive/ 的版本号)
```

判据落点 = `tests/unit_ci_workflows/test_migration_immutability.py::test_live_dir_holds_only_migrations_after_the_cut_point`
（纯函数 `cut_point_violations()`，带注入式自证：把归档里任一条复制回本目录 ⇒ 必红）。

### 当前为什么有一条留在这里（**显式登记，勿当遗漏「顺手归档」**）

`V123__retire_join_height_processing_item.sql`（#5230 / #5231 裁定的落地）是**纯数据迁移**：
它软删 + 停用仍然活跃的 `processing_items` 里名为「接高」的行，**不动任何表/列**，
而建库脚本里**没有**这一笔（复算：`grep -c join_height ../init/schema.sql` → `0`）。
⇒ 归档它会让**每个新建环境**上「接高」重新变成活跃项 —— 本仓称之为「CI 全绿、功能静默缺失」。
故它**有意留在活目录**，由基线上的正常迁移路径执行。

## 新迁移怎么写

1. **文件名**：`V<下一个空闲号>__简短英文描述.sql`（版本号必须可解析 —— `MigrationRunner`
   按**数值**排序，不是字典序；`V5` 排在 `V40` 之后是历史事故）。空闲号**别抄数字**，算：

   ```bash
   ls . ../migration-archive | sed -n 's/^V\([0-9]*\)__.*/\1/p' | sort -n | tail -1   # 最大号；下一个空闲 = +1
   ```

   ⚠️ 数字会随别的 PR 合入而变（写死在文档里必腐烂）；且**编号必须晚于切点**（见上）。

2. **必须幂等**：`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `ON CONFLICT DO NOTHING`。
   空库上第一份 SQL 是建库脚本，但脚本建完之后本目录的迁移链会**照常跑一遍** ⇒
   每条语句都可能在「对象已经存在」的库上再执行一次。
3. **一整份文件 = 一个事务**：`MigrationRunner` 是 `jdbc.execute(整份文本)`
   （PG 扩展查询下多语句走单一隐式事务），任一句失败即**整份回滚**且不记账 ⇒ 每次启动重跑。
4. **登记指纹**（发布即冻结）：

   ```bash
   python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger
   ```

   账本 = `tests/unit_ci_workflows/migration_fingerprints.json`。命令**只新增**条目；
   已登记文件被改会**非零退出**（那要回滚改动、改走新迁移，不是「刷新一下就好」）。

5. **不得破坏性 DDL / 不得重写已发布迁移**：`.github/danger_scan.py` 会拦；确需变更一条
   已发布迁移，走仓库 owner 的人工确认通道（评论 `/danger-ack rewrite-migration`）
   **并且**手工改账本条目（手改会出现在 PR diff 里，可被评审看见）。

## 别在这一层干的事

- **不要**改归档目录里的任何文件（那些历史文件逐字节冻结，见上）；
- **不要**把「存量库也要生效」的增量内容追加进**已发布**的迁移（台账按文件名跳过整份）；
- **不要**把「新建库要有的东西」只写进增量迁移而不写进建库脚本 —— 新建库走的是
  `../init/schema.sql` 这条基线路径；
- **不要**为了让本目录「看起来很干净」把纯数据迁移也归档掉（见上面的 V123 登记）。

规范正文：`docs/wiki/Database.md`。判据面（历史链 ∪ 活目录两个载体）的单一事实源：
`tests/unit_ci_workflows/_migration_paths.py`。