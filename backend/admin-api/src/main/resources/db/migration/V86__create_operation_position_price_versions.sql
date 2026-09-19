-- 部位价目矩阵格的**计件单价**版本账（issue #4587 ② = 母单 #4586 包A）
--
-- ## 为什么需要这张表（矩阵价此前**没有账**）
-- 本仓既有契约是「**改价必须留痕**」：工序价 `production_operation_price_versions`（V55）、
-- 路线 `production_routing_versions`（V60/V85）、选项对客价 `production_route_rules.customer_unit_price`（V77）。
-- 而 `production_operation_positions.unit_price`（V71 的部位价目矩阵）自建表起**只有读面**、
-- 零写面零账 —— 本单开写面（`PUT /api/admin/production/operation-positions/{id}`）必须同时补账，
-- 否则「这格价什么时候被谁改过」永远答不出来（与 V55 同一个病）。
--
-- ## 口径（与 V55 同范式，唯一差别 = `unit_price` **可空**）
--   · 一行 = 一次**真的变了**的单价变更（同价重复提交是幂等空操作，不记账）；
--   · `unit_price` **可空**：NULL = 改回**未定价**（`≠ 0 元`），或「明确不做 ⇒ 不报价」把价强制清空
--     —— 这两态在 V71 的列口径里都是 NULL，账本如实记 NULL（**不填 0**：0 是「定价为 0 元」，两件事）；
--   · 行挂在 `production_operation_positions.id` 上（外键 ⇒ 不会留下指向不存在格子的孤儿版本行）。
--
-- ## 为什么是新增 V86 而不是改 V71
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改 V71 只对全新库生效、存量环境永远拿不到（issue #4235「CI 全绿、功能静默缺失」），
-- 且 V71 已被 `tests/unit_ci_workflows/migration_fingerprints.json` 逐字节冻结。一切增量走新文件。
--
-- ## 幂等（MigrationRunner 硬要求所有迁移可重复执行）
-- `CREATE TABLE/INDEX IF NOT EXISTS` + `COMMENT ON` 天然幂等；本表**不回填**任何存量行 ——
-- 矩阵格的当前价是 `production_operation_positions.unit_price` 本身（不派生自账本），
-- 账本只记**变更**，故无回填必要（与 V55 的差别：V55 要回填是因为「当前价 = 最新版本行」）。
CREATE TABLE IF NOT EXISTS production_operation_position_price_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    position_row_id VARCHAR(64) NOT NULL REFERENCES production_operation_positions(id),
    unit_price NUMERIC(10,2),                        -- 该次变更后的计件单价（元/单位）；NULL = 未定价 / 不做
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_position_price_versions_row
    ON production_operation_position_price_versions (position_row_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_operation_position_price_versions IS
    '部位价目矩阵格的计件单价版本（V86，issue #4587）：每次**真变价**一行；当前价 = production_operation_positions.unit_price 本身，本表只记变更';
COMMENT ON COLUMN production_operation_position_price_versions.unit_price IS
    '本次变更后的**计件**单价（元/单位，付工人）；NULL = 未定价或明确不做（≠ 0 元，0 是定价为 0 元）';
