-- 工序「作用域」列 scope（issue #4384 **A1**，2026-09-19 用户裁定）
--
-- ## 病根（取证事实，不是推测）
-- 真值源 `docs/curtain-production-rules.md` §8 明写「**外帘**是加工单打印行部位，**不是**路线键」，
-- 但 V54/V58 种子里 `外帘打卷` / `外帘装袋` / `外帘发货` 的 `position='外帘'`
-- 却**逐条出现在每一条部位路线**里（含纱帘路线：`rt-v54-05` / `rt-v58-01..03`）
-- ⇒ 一樘「布 + 纱」时这 3 道各实例化 **2 次**（`unit='套'`、`qty=1`）
-- ⇒ 打卷/装袋/发货 **各 ¥1.0 双付**。
--
-- 用户裁定（2026-09-19）：**套级工序先按「每樘窗一次」实现**，打卷是否每帘一次**留成可配**。
-- 本列就是把「部位级 / 套级」这件事**落到数据上**（而不是继续只活在注释与路线数组里）——
-- 否则「留成可配」没有可配的载体。
--
-- ## 语义（冻结）
-- | 取值 | 含义 | 实例化口径（消费方 = A2） |
-- |---|---|---|
-- | `position`（**默认**） | 部位级 | 每部位一次（今天的行为） |
-- | `set` | 套级 | **每樘窗一次**（一樘「布 + 纱」= 1 次，不是 2 次） |
--
-- ## ⚠️ 本迁移**不改行为**（如实登记，别把半截当完整交付）
-- 本迁移只加列 + 标数据。**套级去重本身（A2）不在本包**：`ProcessingOrderService.buildPositionPayload`
-- 的按 `craftLineId` 组去重**等包 D（#4387，布行与纱行同组）先合**再单独做（同文件，本就要串行）。
-- ⇒ **本包不交付「套级去重生效」** —— A2 未落地时去重无从谈起，硬写会变成**空断言**。
--
-- ## 为什么是**新迁移 V67**（不改 V54/V58）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的文件**整份跳过**
-- （`applied.contains(filename)` ⇒ `continue`）⇒ 往 V54/V58 里加列会「CI 绿、存量环境永远拿不到」
-- = **绿了但没生效**（本仓库最忌讳的形态）。故 V54/V58/V59/V60/V62 **一字不动**。
-- ⚠️ 版本号 **V67**：V64/V65/V66 已被另外三个并行包占用；`MigrationRunner` 复核**无乱序守卫**
-- （`Arrays.sort` 后只 `if (applied.contains(filename)) continue;`），
-- 且 `MigrationRunnerOrderingTest` 只断言**文件列表版本号严格递增** ⇒ 乱序合并安全。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- ① `ADD COLUMN IF NOT EXISTS`（第二次执行影响 0 行）；
-- ② 回填只把三道外帘工序**设成** `'set'`（第二次执行写同样的值 = 语义空操作）；
--    不落 `ELSE`、不动其它行 ⇒ 商家自建的套级工序不会被本迁移改写。
--
-- ## 与写面/读面的收敛判据（防第二份口径漂移）
-- 合法取值 = 闭词表 `{position, set}`，三处同口径：
-- ① 本迁移的列注释；② 写面 `ProductionOperationCommandService` 的取值校验（非法值 422 可读理由）；
-- ③ 前端 `production/operations/page.tsx` 的两档下拉。由测试守：
-- `ProductionOperationScopeMigrationTest`（迁移文本 + 终态推演）+ `ProductionOperationCommandServiceTest`
-- （可配 + 校验）+ `frontend/admin-web/tests/unit/components/OperationsScopeColumn.test.tsx`（可见可改）。

-- ── ① 加列（幂等；默认 position = 部位级 ⇒ 存量 35 道工序保持今天的行为）──
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'position';

COMMENT ON COLUMN production_operations.scope IS
    '工序作用域（V67，issue #4384 A1）：position = 部位级（默认，每部位一次）/ '
    'set = 套级（每樘窗一次）。真值源 docs/curtain-production-rules.md §8：外帘是加工单打印行部位、'
    '不是路线键 ⇒ 外帘打卷/外帘装袋/外帘发货 这三道是套级（一樘「布 + 纱」只做一次，'
    '此前因逐条出现在布帘与纱帘两条路线里而各实例化 2 次、各 ¥1.0 双付）。'
    '用户裁定 2026-09-19：套级先按「每樘窗一次」实现，打卷是否每帘一次留成可配。'
    '⚠️ 去重消费方（A2，ProcessingOrderService.buildPositionPayload）不在 #4384 A1 包内，'
    '本列当前只是标记 + 可配口径。';

-- ── ② 回填：三道外帘工序标成套级（幂等；不动其它行）──
UPDATE production_operations
SET scope = 'set'
WHERE name IN ('外帘打卷', '外帘装袋', '外帘发货');
