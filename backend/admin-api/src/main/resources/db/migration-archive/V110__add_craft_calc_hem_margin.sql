-- 算料配置追加「上下卷边」列 `hem_margin`（issue #4976 包 1b；母单 #4976，来源 = #4940 裁定 B）
--
-- ## 一句话
-- 用户 2026-09-21 对 #4940 的两条路选了 **B**：**让上下卷边可配**。
-- 此前 `HEM_MARGIN = 0.3`（定宽布上下卷边合计，脚位+止口）是**硬编码常量**，商家没有任何入口；
-- 它在引擎里有 **5 处**消费点，且横跨两条公式 —— 定高可行性（决定走定高买宽还是回落定宽买高，
-- **米数会变**）、定宽买高每幅长、折数法两支、罗马帘、以及自动特征「超高」的判据。
--
-- ## 为什么是新迁移（而不是改 V80）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记、已应用的文件**整份跳过**
-- ⇒ 改 V80 只对全新库生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）。
-- **一切增量都走新文件。**
--
-- ## 迁移号（**现取**，不写死）
-- 落码时 `backend/admin-api/src/main/resources/db/migration/` 的最大号为 `V109`
-- ⇒ 本单取 `V110`。（守卫与文档一律**现取**，别照抄这个数字。）
--
-- ## 缺省 0.3 = **与今天逐值一致**（回归不变量）
-- 列默认 = 引擎常量 `curtain_calc.HEM_MARGIN`（0.3）。**存量行**由 `DEFAULT` 直接补齐，
-- 不需要 `UPDATE` 回填：`ADD COLUMN … NOT NULL DEFAULT 0.3` 会让既有行立刻取到 0.3
-- （PostgreSQL 11+ 是元数据级操作，不重写表）。
-- ⇒ 本迁移**不改任何既有算料结果**：没配置过的租户读到的仍是 0.3。
--
-- ## 为什么不做开租播种（与 V80 同一口径）
-- 默认值的唯一来源是引擎 `DEFAULT_CRAFT_CALC_CONFIG`；在库里再种一份 = **第二份会漂的默认值**
-- （引擎改默认、库里还是旧值 ⇒ 两条路径算不同米数）。读面在**无活跃行**时返回引擎默认值。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + 覆盖式 `COMMENT ON COLUMN` ⇒ 重复执行净效果相同。
--
-- ## 停止条件（fail-closed）
-- `craft_calc_configs` 表不存在 ⇒ 迁移失败并停下（**不** CREATE TABLE 兜底 ——
-- 那会造出一张缺唯一索引/缺注释的影子配置表，比失败更危险）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V111__rollback_craft_calc_hem_margin.sql（本单只登记，不落码）
-- -- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS hem_margin;
-- ```
--
-- ## 跨源收敛判据（五处同源）
-- 键集必须逐字一致：引擎 `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（**真值源**）/
-- 本迁移 / `docs/sql/schema.sql`（bootstrap 终态）/ Java 实体 `CraftCalcConfig` /
-- Java 写面 `CraftCalcConfigService.CONFIG_KEYS` + `NUMERIC_KEYS`。
-- 守卫 = `tests/unit_ci_workflows/test_craft_calc_config_contract.py`（按内容**聚合**本表的
-- `CREATE TABLE` 与后续 `ALTER TABLE … ADD COLUMN`，不写死某一个迁移文件名）。

ALTER TABLE craft_calc_configs
    ADD COLUMN IF NOT EXISTS hem_margin NUMERIC(6,3) NOT NULL DEFAULT 0.3;

COMMENT ON COLUMN craft_calc_configs.hem_margin IS
    '高方向**上下卷边**合计（米；脚位+止口），引擎默认 0.3（= 常量 HEM_MARGIN）。'
    '护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。'
    '消费点：定高可行性 / 定宽买高每幅长 / 折数法 / 罗马帘 / 自动特征「超高」的判据。'
    '⚠️ 与 side_margin（**宽方向**左右覆盖余量）是两个量，不得混用。';
