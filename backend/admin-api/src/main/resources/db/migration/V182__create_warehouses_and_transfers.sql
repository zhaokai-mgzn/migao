-- 多仓 + 调拨（issue #7373，P1-1 段 1）—— 仓库成为实体、调拨成为单据
--
-- ## 一句话
-- 现状：`warehouse` 只是若干表上的**文本字段**（`stock_batches.warehouse` …），不是实体 ——
-- 没有编码、没有类型、没有默认仓，调拨只能改文本（改错了没人留痕、也没有单据）。
-- 本迁移立两件事：① 仓库实体（编码/名称/类型/默认仓）；② 调拨单（调出/调入两端 + 逐批次明细）。
--
-- ## 段 1 的范围（写清才好评审）
-- - ✅ **仓库实体** + 同租户内**唯一编码** + **默认仓唯一**（部分唯一索引兜住，不靠服务层自觉）。
-- - ✅ **调拨单**：`stock_transfers`（单头）+ `stock_transfer_items`（逐批次明细），
--   一次性完成（同事务两端一起变），**数量守恒**（同一批次行只改归属仓，不拆行）。
-- - ✅ **缸号不因调拨丢失**：明细直接引用 `batch_id`（同一行改仓）⇒ `dye_lot` 原样保留，可追溯。
-- - ❌ **调拨中不可售（两阶段：在途状态）」本段不做**：段 1 是**即时调拨**（确认即两端到位），
--   没有「在途」窗口 ⇒ 也不存在「在途可售」的问题。两阶段在途 + 负库存拦截见段 2。
-- - ❌ **盘点单**（段 2，与 P1-2 的 `stocktake_diff` 审批同批）、**仓位/库位**（非目标，issue 明列）。
--
-- ## 为什么明细引用 batch_id 而不是 sku_id
-- 调拨的对象是**这一缸布**（可追溯单元），不是「这个 SKU 随便几米」—— 按 SKU 调拨会让缸号在仓间丢失，
-- 而缸号是色差追溯的唯一依据（V118/#5153）。成本同理：批次进价跟着行一起走，不重算。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步两张表 + 一张明细（新建库不跑迁移链）。
-- - 回滚：`DROP TABLE stock_transfer_items, stock_transfers, warehouses;` **无数据损失**
--   （`stock_batches.warehouse` 文本列仍在，只是回到「没有仓库实体」的形态）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS warehouses (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    code VARCHAR(32) NOT NULL,                    -- 仓编码（同租户唯一；单据与对账都认它）
    name VARCHAR(128) NOT NULL,
    warehouse_type VARCHAR(32) NOT NULL DEFAULT 'store',   -- store 门店仓 / processing 加工仓
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_warehouses_type CHECK (warehouse_type IN ('store', 'processing')),
    CONSTRAINT ck_warehouses_status CHECK (status IN ('active', 'inactive'))
);

-- 同租户编码唯一（软删的不占位）
CREATE UNIQUE INDEX IF NOT EXISTS uk_warehouses_code
    ON warehouses (tenant_id, code) WHERE deleted = 0;
-- 同租户**只能有一个默认仓**：靠索引兜住，不靠服务层自觉（并发建两个默认仓是真实会发生的）
CREATE UNIQUE INDEX IF NOT EXISTS uk_warehouses_single_default
    ON warehouses (tenant_id) WHERE is_default AND deleted = 0;

CREATE TABLE IF NOT EXISTS stock_transfers (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    transfer_no VARCHAR(32) NOT NULL,
    from_warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    to_warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    status VARCHAR(16) NOT NULL DEFAULT 'completed',
    note VARCHAR(255),
    created_by VARCHAR(64),
    created_by_name VARCHAR(64),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_stock_transfers_not_same CHECK (from_warehouse_id <> to_warehouse_id),
    CONSTRAINT ck_stock_transfers_status CHECK (status IN ('draft', 'in_transit', 'completed', 'cancelled'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_stock_transfers_no
    ON stock_transfers (tenant_id, transfer_no) WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS stock_transfer_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    transfer_id VARCHAR(64) NOT NULL REFERENCES stock_transfers(id),
    batch_id BIGINT NOT NULL REFERENCES stock_batches(id),   -- 调拨的是**这一缸布**（缸号随行）
    batch_no VARCHAR(32) NOT NULL,                           -- 单据快照（批次软删后仍可追溯）
    sku_id BIGINT,
    sku_code VARCHAR(64),
    qty NUMERIC(12,1) NOT NULL CHECK (qty > 0),              -- 本次调拨数量（米，1 位小数 = V115 口径）
    unit_cost NUMERIC(12,4),                                 -- 成本随行转移的快照（NULL = 未知，不猜 0）
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_transfer
    ON stock_transfer_items (tenant_id, transfer_id);

-- RLS：三张表都按租户隔离（跨租户读别人的仓与调拨单 = 越权面）
ALTER TABLE warehouses ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfers ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfer_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'warehouses'
                   AND policyname = 'tenant_isolation_warehouses') THEN
        CREATE POLICY tenant_isolation_warehouses ON warehouses
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stock_transfers'
                   AND policyname = 'tenant_isolation_stock_transfers') THEN
        CREATE POLICY tenant_isolation_stock_transfers ON stock_transfers
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stock_transfer_items'
                   AND policyname = 'tenant_isolation_stock_transfer_items') THEN
        CREATE POLICY tenant_isolation_stock_transfer_items ON stock_transfer_items
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM unnest(ARRAY['warehouses', 'stock_transfers', 'stock_transfer_items']) AS t
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_name = t AND table_schema = 'public');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '多仓/调拨表族缺表：%（issue #7373 段 1 迁移未生效）', missing;
    END IF;
END $$;

COMMIT;
