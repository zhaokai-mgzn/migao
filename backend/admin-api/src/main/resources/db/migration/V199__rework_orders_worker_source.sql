-- 返工单支持**车间报返工**（issue #7860，用户 2026-10-26 裁定）
--
-- ## 一句话
-- 改前：返工单只能从售后单开（`after_sales_ticket_id NOT NULL`）⇒ 车间工人扫码报的返工没有承载体，
-- PC「返工单」列表看不到；工人端也没有「报返工的加工单」读面。
--
-- ## 本段范围
-- - ✅ `source`（`after_sales` 售后开单 / `worker` 车间报返工）+ 车间来源的工序 / 数量 / 报工人 / 被改记的报工行；
-- - ✅ `after_sales_ticket_id` 改**可空**（车间返工没有售后单；部分唯一索引对 NULL 天然互不相等，语义不变）；
-- - ❌ 不改状态机四态、不改「完成回写售后状态」规则（无售后单 ⇒ 什么都不回写）。
--
-- ## 回滚
-- 不复原：新增列全部可空 / 有默认值 ⇒ 旧代码忽略它们即可；`DROP COLUMN` 会丢车间返工的责任留痕。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE rework_orders ALTER COLUMN after_sales_ticket_id DROP NOT NULL;
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'after_sales';
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS operation_id VARCHAR(64);
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS operation_name VARCHAR(64);
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS qty NUMERIC(12, 3);
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS worker_id VARCHAR(64);
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS worker_name VARCHAR(64);
ALTER TABLE rework_orders ADD COLUMN IF NOT EXISTS work_log_id VARCHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_rework_orders_source') THEN
        ALTER TABLE rework_orders ADD CONSTRAINT ck_rework_orders_source
            CHECK (source IN ('after_sales', 'worker'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_rework_orders_processing
    ON rework_orders (tenant_id, processing_order_id) WHERE deleted = 0;

COMMENT ON COLUMN rework_orders.source IS
    '来源（issue #7860）：after_sales = 售后开单；worker = 车间工人报返工（不挂售后单）';
COMMENT ON COLUMN rework_orders.operation_name IS
    '返工的工序名（worker 来源有值，与报工明细 production_work_logs.operation_name 同源）';
COMMENT ON COLUMN rework_orders.qty IS
    '返工数量（worker 来源有值；单位随工序，不参与计件）';
COMMENT ON COLUMN rework_orders.work_log_id IS
    '被改记为返工的那一笔报工明细（production_work_logs.id）：责任留痕，明细本身不删';

-- 终态对账（fail-closed：迁移没生效就让建库/迁移链当场红，不留给运行期）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'rework_orders' AND column_name = 'source') THEN
        RAISE EXCEPTION 'rework_orders.source 缺列（issue #7860 迁移未生效）';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'rework_orders' AND column_name = 'after_sales_ticket_id'
                  AND is_nullable = 'NO') THEN
        RAISE EXCEPTION 'rework_orders.after_sales_ticket_id 仍为 NOT NULL（issue #7860 迁移未生效）';
    END IF;
END $$;

COMMIT;
