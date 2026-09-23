# 未来的增量迁移放这里（issue #5243）

本目录**只放未来的增量迁移**。历史迁移链（`V1` … 归档时的最后一条）已**整链归档**到：

```
backend/admin-api/src/main/resources/db/migration-archive/
```

## 新迁移怎么写

1. **文件名**：`V<下一个空闲号>__简短英文描述.sql`（版本号必须可解析 —— `MigrationRunner`
   按**数值**排序，不是字典序；`V5` 排在 `V40` 之后是历史事故）。空闲号**别抄数字**，算：

   ```bash
   ls backend/admin-api/src/main/resources/db/migration{,-archive} \
     | sed -n 's/^V\([0-9]*\)__.*/\1/p' | sort -n | tail -1   # 最大号；下一个空闲 = +1
   ```

2. **必须幂等**：`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `ON CONFLICT DO NOTHING`。
   全新空库上跑的第一份 SQL 是**建库脚本**（`db/init/schema.sql`，见
   `MigrationRunner.applyBaseline`）；但空库建完之后本目录的迁移链会**照常跑一遍**，
   所以每条语句都可能在「对象已经存在」的库上再执行一次。
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
  `db/init/schema.sql` 这条基线路径。

规范正文：`docs/wiki/Database.md`。判据面（历史链 ∪ 活目录两个载体）的单一事实源：
`tests/unit_ci_workflows/_migration_paths.py`。