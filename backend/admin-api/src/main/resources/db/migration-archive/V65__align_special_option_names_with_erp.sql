-- 特殊选项名**以 ERP 为准**对齐（issue #4389，用户裁定 R-e「以 ERP 为准改」，2026-09-19）
--
-- ## 病根（静默失效，无任何东西变红）
-- 特殊选项名是「**订单选配 → 车间工序 / 计件系数**」的 **join key**：订单侧
-- `processingInfo.specialOptions: string[]` 的取值要与本表 / `production_option_routings`
-- 的 `option_name` **逐字相等**才会命中。错一个字 ⇒ `.get(opt) → None` ⇒
-- 条件工序不加、计件系数静默退回 1.0 ⇒ **少发工人钱**，而库里/页面上看不出缺什么。
--
-- 真值源 = 用户提供的行业 ERP **订单录入页**截图（2026-09-19，与 `docs/curtain-production-rules.md`
-- §1 同源系统）。截图与我们的既有写法有两处不一致：
--
-- | 我们的旧写法 | ERP 名（本迁移的目标态） | 后果 |
-- |---|---|---|
-- | `一分二`（`OPTION_FACTOR_SCOPES` 里唯一的实证档 ×1.7） | `一分为二` | ×1.7 静默不生效 |
-- | `余料带回(布)` / `余料带回(纱)` | `余料带回-布` / `余料带回-纱` | 落进静默黑洞 |
--
-- ## 为什么是**新迁移**而不是改 V56 / V59（本仓已诊断过的形态）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的迁移**整份跳过**
-- （`applied.contains(filename) ⇒ continue`）⇒ 改 V59 只对**全新库**生效，**存量环境永远拿不到**，
-- 而静态守卫反而会因此转绿（=「CI 全绿、功能静默缺失」，issue #4235）。
-- ⇒ 已发布迁移（含 `V56__seed_special_option_operations.sql` /
-- `V59__create_production_option_tables.sql`）**一个字都不许改**，改名走本迁移。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 判据 = 每条语句都带 `WHERE option_name = '旧名'`：重跑时旧名已不存在 ⇒ **空转**（0 行），
-- 不产生第二行、不撞唯一索引（`production_option_factors` 的唯一性是表达式索引
-- `(tenant_id, option_name, COALESCE(operation_name,'')) WHERE deleted = 0`；
-- `production_option_routings` 是 `(tenant_id, option_name, operation_name) WHERE deleted = 0`）。
-- 不带 `deleted` 过滤是**有意**的：软删行也一并改名，让「旧名」在库里**彻底消失**
-- （残留软删行会让「库里还有旧名」这种排查结论失真）；软删行不在部分唯一索引的射程内 ⇒ 不会冲突。
--
-- ## 两张表都过一遍同一张改名表（不是「只改系数表」）
-- 本单改名的三个选项里，今天**只有 `一分二` 有落表行**（在系数表；它只加系数、不加工序），
-- `余料带回-布/-纱` 是**不计件**项，按 V59 的口径**不落**这两张表（落表会把「不计件」变成
-- 「有映射但系数 1」，两种语义又混成一种）⇒ 条件工序表那三条语句今日是**空转**。
-- 仍然写上，是因为「改名」这件事必须**穷尽**持有该 join key 的表：将来（商家配置面 v1b）
-- 若真有按旧名写进条件工序表的行，漏掉它 = 又一条静默黑洞。空转语句无副作用。
--
-- ## 三源收敛（防第二份口径漂移）
-- 本文件是 Python 常量 `app/production/routing.py` 的**一次改名补丁**，不是第二份真值源。
-- 防漂移由测试守（改名后三源必须**逐行逐字**一致，改一处不改另两处即红）：
--   · Java 侧 `ProductionOptionRoutingMigrationTest`（V59 ∪ 本文件的改名 ↔ `routing.py` ↔
--     `docs/sql/schema.sql` 三源逐行逐值 + 「改名补丁真被读到」的注入式自证）；
--   · Python 侧 `tests/unit_ci_workflows/test_production_catalog_seed.py` 的「特殊选项名三源收敛」段
--     （按**内容**发现含 `UPDATE ... SET option_name` 的迁移 ⇒ 将来的改名迁移无需改守卫）。
--
-- ## 不在本迁移范围（如实登记，见 PR）
-- 存量**订单**里已落库的 `processingInfo.specialOptions` / `processing_orders.items_snapshot[].specialOptions`
-- 仍可能带旧名（它们是订单快照，不是配置表）—— 本迁移**不动**它们（JSONB 数组元素改写风险高、
-- 且需先确认存量数据实况）。残余影响与后续动作登记在 PR 的「未做/待确认」段。

-- ── ① 系数表（今日有实效应：`opt-fa-01` 一行 `一分二` → `一分为二`）──
UPDATE production_option_factors SET option_name = '一分为二',   updated_at = NOW() WHERE option_name = '一分二';
UPDATE production_option_factors SET option_name = '余料带回-布', updated_at = NOW() WHERE option_name = '余料带回(布)';
UPDATE production_option_factors SET option_name = '余料带回-纱', updated_at = NOW() WHERE option_name = '余料带回(纱)';

-- ── ② 条件工序表（今日空转：三个改名选项都不在该表里 —— 见上方「两张表都过一遍」）──
UPDATE production_option_routings SET option_name = '一分为二',   updated_at = NOW() WHERE option_name = '一分二';
UPDATE production_option_routings SET option_name = '余料带回-布', updated_at = NOW() WHERE option_name = '余料带回(布)';
UPDATE production_option_routings SET option_name = '余料带回-纱', updated_at = NOW() WHERE option_name = '余料带回(纱)';
