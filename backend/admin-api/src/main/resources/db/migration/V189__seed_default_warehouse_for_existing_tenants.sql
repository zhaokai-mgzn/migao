-- 默认主仓回填（issue #7592）—— 存量租户也开箱有仓可选
--
-- ## 一句话
-- `warehouses` 表在现网是 0 行（段 1 有意「不自动建仓」，商家面又没有建仓入口）⇒
-- 盘点单「出盘点任务」的仓库下拉为空，一张盘点单也出不了。
-- V189 之后：开租由 `WarehouseSeedService.seedDefaultWarehouse` 种（新租户），**本迁移补存量租户**。
--
-- ## 范围（写清才好评审）
-- - ✅ 只补**一个仓都没有**的租户：`NOT EXISTS (… deleted = 0)` ⇒ 幂等，重跑不种出第二行。
-- - ✅ 种的仓 = 默认主仓（`code` = `OnboardingInitialData.DEFAULT_WAREHOUSE_CODE`、`name` = `…_NAME`，
--       `store` 类型，`is_default = TRUE`）—— 与开租播种同值，两处由用例 WH-002 对账。
-- - ❌ **不动**已有仓档案的租户（不碰 `uk_warehouses_single_default` / 商家自建的默认仓）。
-- - ❌ **不改写** `stock_batches.warehouse` 的历史自由文本（那是多仓建档页的归属；
--       空文本在出任务时按「未指定仓 = 默认仓」计入，见 `StocktakeService.open`）。
--
-- ## 回滚
-- `DELETE FROM warehouses WHERE code = 'MAIN' AND tenant_id IN (…本迁移新增的租户…)；`
-- 无数据损失（仓档案是主数据，批次与库存量都不变）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO warehouses (tenant_id, code, name, warehouse_type, is_default, status, created_at, updated_at, deleted)
SELECT t.id, 'MAIN', '主仓', 'store', TRUE, 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (
    SELECT 1 FROM warehouses w WHERE w.tenant_id = t.id AND w.deleted = 0
);

COMMENT ON COLUMN warehouses.is_default IS
    '默认仓（同租户唯一）：V189 起每个租户至少有一个 —— 开租播种，存量租户由本迁移补齐（issue #7592）';

COMMIT;
