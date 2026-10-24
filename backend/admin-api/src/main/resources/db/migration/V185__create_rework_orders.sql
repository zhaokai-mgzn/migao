-- 返工单（issue #7377，P1-5 段 2）—— 售后 → 返工 → 回写，闭环唯一
--
-- ## 一句话
-- 改前：售后工单与生产返工是**两条线**（售后在 `after_sales_tickets`，返工只体现为报工的
-- `work_type='rework'`）⇒ 「这张售后单到底有没有在修、修完没有」没有任何载体，质量成本也无法归到这个单上。
--
-- ## 本段范围
-- - ✅ 返工单实体：`rework_orders`（单头）+ 与售后单的**一对多**关联（`after_sales_ticket_id`）。
-- - ✅ 状态机四态：`draft → in_progress → done | cancelled`（**闭环唯一**：同一售后单同时只能有一个未完结返工单）。
-- - ✅ 完成时**回写售后状态**：仅当售后单当前是 `processing` 时推进到 `resolved`；
--   其它状态（pending / closed / rejected）不动 —— 回写不得把已闭环的工单拉回处理中。
-- - ❌ 不做：返工工序明细（沿用报工的 `work_type='rework'`）、返工的**成本归集到单据**
--   （段 3，需 join 报工）、缺陷原因字典（段 4）。
--
-- ## 为什么「同时只能一个未完结」
-- 一张售后单开两张返工单时：「修完没有」由哪张回答？成本算几次？—— 两个答案都合理，所以必须由系统禁掉。
-- 用**部分唯一索引**兜住（`WHERE status IN ('draft','in_progress')`），不靠服务层先查一遍。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步本表（新建库不跑迁移链）。
-- - 回滚：`DROP TABLE rework_orders;` **无数据损失**（返工单是过程数据；报工与售后单不受影响）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS rework_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    rework_no VARCHAR(32) NOT NULL,
    after_sales_ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    order_id VARCHAR(36),
    processing_order_id VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    reason VARCHAR(500),
    created_by VARCHAR(64),
    created_by_name VARCHAR(64),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_rework_orders_status CHECK (status IN ('draft', 'in_progress', 'done', 'cancelled'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_rework_orders_no
    ON rework_orders (tenant_id, rework_no) WHERE deleted = 0;

-- 🔴 同一售后单**同时只能有一个未完结返工单**（问「修完没有」不能有两个答案）
CREATE UNIQUE INDEX IF NOT EXISTS uk_rework_orders_open_per_ticket
    ON rework_orders (tenant_id, after_sales_ticket_id)
    WHERE status IN ('draft', 'in_progress') AND deleted = 0;

CREATE INDEX IF NOT EXISTS idx_rework_orders_ticket
    ON rework_orders (tenant_id, after_sales_ticket_id) WHERE deleted = 0;

COMMENT ON COLUMN rework_orders.after_sales_ticket_id IS
    '售后工单（issue #7377 段 2）：同一售后单同时只能有一个未完结返工单（部分唯一索引兜住）';
COMMENT ON COLUMN rework_orders.status IS
    '四态：draft → in_progress → done | cancelled；完成时仅当售后单为 processing 才回写 resolved';

ALTER TABLE rework_orders ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'rework_orders'
                   AND policyname = 'tenant_isolation_rework_orders') THEN
        CREATE POLICY tenant_isolation_rework_orders ON rework_orders
            USING (tenant_id::text = current_setting('app.current_tenant_id', true));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'rework_orders' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'rework_orders 缺表（issue #7377 段 2 迁移未生效）';
    END IF;
END $$;

COMMIT;
