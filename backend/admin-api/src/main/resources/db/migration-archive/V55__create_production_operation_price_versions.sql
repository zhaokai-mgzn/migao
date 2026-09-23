-- 计件单价版本化（issue #4204，P1）
-- 真值源：docs/curtain-production-rules.md §2「工序属性：…计件单价（**版本化**）」
-- 与 §4「单价 = 工序 × 部位定价，**版本化**（调价只影响新报工，历史报工按当时价，逐笔可追溯）」。
--
-- 背景（2026-09-18 商家后台真实走查，SHA d5bca241）：production_operations 的**唯一写方**是
-- V54__seed_production_operations.sql 种子 SQL（全仓对 productionOperationMapper 零写调用），
-- 且没有单价版本表（grep price_version|unit_price_version 零命中）⇒ 商家改不了单价、
-- 也答不出「这条报工当时按什么价算的」。
--
-- 口径（冻结契约，与 PUT /api/admin/production/operations/{id} 一致）：
--   ① **当前价 = 最新版本行**（本表按 operation_id 取 created_at 最新的一行）；
--   ② production_operations.unit_price 与最新版本行由同一个事务维护（改价写两处，见
--      ProductionOperationCommandService）—— 本迁移为存量工序各回填一行初始版本，
--      使「当前价 = 最新版本行」对**迁移前就存在**的工序同样成立；
--   ③ processing_position_operations.unit_price 仍是**生成时的实例快照**（V49 注释）：
--      改价不回溯既有实例、不影响历史报工（报工明细不可变，计件按当时价可追溯）。
--
-- 幂等（bootstrap-first：docs/sql/schema.sql 先建终态，本迁移随后再跑一遍）：
-- CREATE TABLE/INDEX IF NOT EXISTS + 回填按 NOT EXISTS 守卫（已有版本行的工序不再插）。
CREATE TABLE IF NOT EXISTS production_operation_price_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    operation_id VARCHAR(64) NOT NULL REFERENCES production_operations(id),
    unit_price NUMERIC(10,2) NOT NULL,               -- 该次变更后的单价（元/单位）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_price_versions_operation
    ON production_operation_price_versions (operation_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_operation_price_versions IS '工序计件单价版本（V55，issue #4204）：当前价 = 最新版本行；实例单价仍是生成时快照，改价不影响既有实例与历史报工';
COMMENT ON COLUMN production_operation_price_versions.unit_price IS '本次变更后的计件单价（元/单位）；与 production_operations.unit_price 同事务写入';

-- 回填初始版本：每条活跃工序一行（幂等：已有版本行的工序跳过；ON CONFLICT 兜底重复执行）
INSERT INTO production_operation_price_versions (id, tenant_id, operation_id, unit_price, created_at)
SELECT 'pv-' || o.id, o.tenant_id, o.id, o.unit_price, NOW()
FROM production_operations o
WHERE o.deleted = 0
  AND NOT EXISTS (
      SELECT 1 FROM production_operation_price_versions v
      WHERE v.operation_id = o.id AND v.deleted = 0
  )
ON CONFLICT (id) DO NOTHING;
