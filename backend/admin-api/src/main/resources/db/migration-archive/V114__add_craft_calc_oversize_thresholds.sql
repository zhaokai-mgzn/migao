-- 算料配置追加两个**企业参数**列：`oversize_width_threshold` / `oversize_height_threshold`
-- （issue #5130；用户 2026-09-22 裁定 D1 / D2 / D3 / D7）
--
-- ## 一句话
-- 用户裁定 **D2**：客户给的「宽 > 6 / 高 > 4」（**净窗宽 / 净窗高**，米）不是行业通用定义
-- ⇒ 做成**企业参数**；裁定 **D3**：**替换**原判定公式（「超高 / 超宽」不再与**门幅**比）；
-- 裁定 **D7**：默认 `6 / 4`、**对所有租户立即生效**（用户已知会改存量租户的加工费组合键，明确接受）。
--
-- ## 这两个键管什么（**与几何层严格分开**）
-- 它们只决定**特征名**（`超宽` / `超高`）—— 而特征名**进加工费组合键**
-- （`processingInfo.processingItems[]` → `ProcessingFeeQueryService.featureNames()` → 匹配商家配的组合价），
-- 即用户裁定 **D1** 的「**工艺分档**：超阈值时加工费与标准档不同」。
-- **用料米数、加工类型、门幅规则面一字未动**（走引擎 `resolve_fabric_plan` 的**几何**判据，
-- 与特征名无关）—— 见 `docs/design/oversize-threshold-and-enterprise-params.md` §4.4。
--
-- ## 为什么是新迁移（而不是改 V80 / V110）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记、已应用的文件**整份跳过**
-- ⇒ 改旧文件只对全新库生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）。
-- **一切增量走新文件。**
--
-- ## 迁移号（**现取**，不写死）
-- 落码时本单取 `V114`（`ls …/db/migration | sort -V | tail -1` 现场读出的最大号是 `V113`）。
-- ⚠️ 教训（本仓既有纪律）：**迁移号必须现取**，且**长尾 PR 要在合并前再取一次** ——
-- 号被别人占用时只能改号，改已发布迁移的内容是禁止的（issue #4235）。
--
-- ## 默认 6 / 4 = **客户口径立刻生效**（D7，**不是**零回归）
-- 与 V110（`hem_margin` 默认 = 既有常量 ⇒ 逐值不变）**性质不同**：本次是**有意的行为变更**。
-- 存量租户的判定结果会变（家用常见窗不再判超高 / 超宽），这正是用户裁定 D7 与 D9 明确接受的。
-- `ADD COLUMN … NOT NULL DEFAULT` 会让既有行立刻取到该默认值（PostgreSQL 11+ 元数据级操作，不重写表）。
--
-- ## 为什么不做开租播种（与 V80 / V110 同一口径）
-- 默认值的唯一来源是引擎 `DEFAULT_CRAFT_CALC_CONFIG`（常量 `OVERSIZE_WIDTH_THRESHOLD` /
-- `OVERSIZE_HEIGHT_THRESHOLD`）；在库里再种一份 = **第二份会漂的默认值**。读面在**无活跃行**时返回引擎默认值。
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
-- -- V115__rollback_craft_calc_oversize_thresholds.sql（本单只登记，不落码）
-- -- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS oversize_width_threshold;
-- -- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS oversize_height_threshold;
-- ```
-- ⚠️ 回滚**只删列、不回滚口径**：判据替换的留档见引擎 `detect_auto_features` 的 docstring
-- （#4661 / #4662 / #4877 三条退役，用户裁定 D10）。
--
-- ## 跨源收敛判据（五处同源）
-- 键集必须逐字一致：引擎 `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（**真值源**）/
-- 本迁移 / `docs/sql/schema.sql`（bootstrap 终态）/ Java 实体 `CraftCalcConfig` /
-- Java 写面 `CraftCalcConfigService.CONFIG_KEYS` + `NUMERIC_KEYS`；
-- 第六处 = 前端说明键集 `frontend/admin-web/src/lib/craft-calc-glossary.ts`
-- （`CALC_SCALAR_KEYS` + `CALC_PARAM_COPY`）。
-- 守卫 = `tests/unit_ci_workflows/test_craft_calc_config_contract.py`（少一处 ⇒ 红）。

ALTER TABLE craft_calc_configs
    ADD COLUMN IF NOT EXISTS oversize_width_threshold NUMERIC(6,3) NOT NULL DEFAULT 6;

ALTER TABLE craft_calc_configs
    ADD COLUMN IF NOT EXISTS oversize_height_threshold NUMERIC(6,3) NOT NULL DEFAULT 4;

COMMENT ON COLUMN craft_calc_configs.oversize_width_threshold IS
    '**超宽**阈值（净窗宽，米），引擎默认 6（= 常量 OVERSIZE_WIDTH_THRESHOLD，issue #5130）。'
    '判据：净窗宽 > 本值 ⇒ 特征名「超宽」（进加工费组合键 = 工艺分档，用户裁定 D1）。'
    '护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。'
    '⚠️ 与**几何层**（门幅 / 褶倍 ⇒ 分幅与用料）是两件事，不得混用。';

COMMENT ON COLUMN craft_calc_configs.oversize_height_threshold IS
    '**超高**阈值（净窗高，米），引擎默认 4（= 常量 OVERSIZE_HEIGHT_THRESHOLD，issue #5130）。'
    '判据：净窗高 > 本值 ⇒ 特征名「超高」（进加工费组合键）。'
    '护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。'
    '⚠️ issue #5130 起「超高」**不再**由「成品高 + 上下卷边 > 门幅」判定（那条门幅判据已退役）；'
    'hem_margin 仍管几何层（定高可行性 / 定宽买高每幅长 / 罗马帘）。';
