-- 盘点单（issue #7373，P1-1 段 2）—— 按仓库出盘点任务 → 录实盘 → 差异走审批后调整
--
-- ## 一句话
-- 改前只有「按批次最小回执」（V143 明示不做盘点单实体）：谁盘了哪个仓、账面多少、实盘多少、
-- 差异怎么调的，全在一张纸上。本迁移立两件事：① 盘点单（单头 + 逐批次明细）；② 差异的**审批出口**
-- 接 P1-2 的 `approvals`（`stocktake_diff`）。
--
-- ## 段 2 的范围（写清才好评审）
-- - ✅ 盘点单：`stocktakes`（单头：仓 / 状态 / 盘点人）+ `stocktake_items`（逐批次：账面 / 实盘 / 差异）。
-- - ✅ **差异必须经审批才调整**：`complete` 时若有差异 ⇒ 要求一条**已通过且未用掉**的
--   `stocktake_diff` 审批（对象 = 盘点单号，金额 = |差异总额|），否则拒绝 —— 判据「未审批的超阈动作
--   写面直接拒绝」在这里同样成立。
-- - ✅ **无差异直接完成**（没有任何库存变动，不需要审批）。这是有意的：把「盘点过、账实相符」
--   也逼去审批，只会让人绕过盘点。
-- - ❌ **不做**：周期盘点计划（定时生成任务）、库位级盘点、盘点差异的成本重估（成本随行不动）。
--
-- ## 恒等式（判据钉的就是它）
--   Σ账面 − Σ实盘 = Σ差异（逐批次），且调整后每个批次 `quantity >= 0`
--   —— 差异调整只改数量，不动成本快照（成本口径另有归属，见 P0-3）。
--
-- ## 为什么明细存账面快照
-- 实盘时写的那个「账面数」必须是**盘点当刻**的读数：事后再看 `stock_batches.quantity` 早就变了
-- （这期间可能有出库/调拨）⇒ 不留快照，差异就无法复算，也无法解释「为什么当时判它少了 3 米」。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步两张表（新建库不跑迁移链）。
-- - 回滚：`DROP TABLE stocktake_items, stocktakes;` **无数据损失**（盘点单是过程数据；库存量只被
--   `complete` 改过，回滚前请确认没有需要保留的调整记录）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS stocktakes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    stocktake_no VARCHAR(32) NOT NULL,
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    status VARCHAR(16) NOT NULL DEFAULT 'counting',
    note VARCHAR(255),
    counted_by VARCHAR(64),
    counted_by_name VARCHAR(64),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_stocktakes_status CHECK (status IN ('counting', 'completed', 'cancelled'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_stocktakes_no
    ON stocktakes (tenant_id, stocktake_no) WHERE deleted = 0;
-- 同一仓库**同时只能有一个进行中的盘点**（否则两个人各盘一遍，谁的结果算数说不清）
CREATE UNIQUE INDEX IF NOT EXISTS uk_stocktakes_one_open_per_warehouse
    ON stocktakes (tenant_id, warehouse_id) WHERE status = 'counting' AND deleted = 0;

CREATE TABLE IF NOT EXISTS stocktake_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    stocktake_id VARCHAR(64) NOT NULL REFERENCES stocktakes(id),
    batch_id BIGINT NOT NULL REFERENCES stock_batches(id),
    batch_no VARCHAR(32) NOT NULL,
    sku_code VARCHAR(64),
    -- 账面数是**盘点当刻的快照**（事后 stock_batches.quantity 早已变化 ⇒ 不留快照差异就无法复算）
    book_qty NUMERIC(12,1) NOT NULL,
    counted_qty NUMERIC(12,1),
    diff_qty NUMERIC(12,1),
    unit_cost NUMERIC(12,4),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_stocktake_items_batch
    ON stocktake_items (tenant_id, stocktake_id, batch_id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_stocktake_items_stocktake
    ON stocktake_items (tenant_id, stocktake_id) WHERE deleted = 0;

COMMENT ON COLUMN stocktake_items.book_qty IS
    '盘点当刻的账面量快照（issue #7373 段 2）：事后恒变的 stock_batches.quantity 不能替代它';
COMMENT ON COLUMN stocktake_items.diff_qty IS
    '差异 = 实盘 − 账面（未录实盘时为 NULL，不是 0：还没数 ≠ 数了正好一样）';

ALTER TABLE stocktakes ENABLE ROW LEVEL SECURITY;
ALTER TABLE stocktake_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stocktakes'
                   AND policyname = 'tenant_isolation_stocktakes') THEN
        CREATE POLICY tenant_isolation_stocktakes ON stocktakes
            USING (tenant_id::text = current_setting('app.current_tenant_id', true));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'stocktake_items'
                   AND policyname = 'tenant_isolation_stocktake_items') THEN
        CREATE POLICY tenant_isolation_stocktake_items ON stocktake_items
            USING (tenant_id::text = current_setting('app.current_tenant_id', true));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM unnest(ARRAY['stocktakes', 'stocktake_items']) AS t
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_name = t AND table_schema = 'public');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '盘点单表族缺表：%（issue #7373 段 2 迁移未生效）', missing;
    END IF;
END $$;

COMMIT;
