-- 采购单 + 收货（issue #7369，P0-1 段 4）—— 按常见做法：**一张采购单可分多次收货**（用户 2026-10-20 裁定「根据常见做法来裁定」）
--
-- ## 一句话
-- 采购前的「我要买什么、多少钱」要能落单、能被收货跟踪；采购单与入库单是**一对多**
-- （分批到货很常见），所以收货进度是**派生值**（Σ receipts），不在采购单头上存冗余计数。
--
-- ## 三张表的分工
-- 1. `purchase_orders` —— 单据头：供应商 / 下单日 / 预计到货日 / 状态 / 金额（明细之和，落库时冻结）；
-- 2. `purchase_order_items` —— 明细：sku + 数量 + 单价 + 金额；**不是**库存，收货才进库存；
-- 3. `purchase_order_receipts` —— 收货记录：一次到货一行（可挂到生成的那张入库单 `inbound_order_id`）。
--
-- ## 状态机（常见做法 + 提前关闭）
--   `ordered` → `partially_received` → `received`
--   任意未完成态可用 `close`（**必须写原因**）→ `closed`：货到不齐 / 供应商断货 / 采购取消都走这条，
--   而不是删单（删了就没有「当初为什么买、后来为什么没到」的痕迹）。
--   🔴 状态**不由客户端指定**：`receive` / `close` 之后由服务层按 Σ收货数量重算（派生而非可写，防两面口径）。
--
-- ## 为什么收货数量不在明细行上直接累加
-- 「已收多少」是 Σ receipts 的派生值：若在 `purchase_order_items` 上再加一列累加计数，
-- 撤销/更正一笔收货就要同时改两处，任何一处漏改就永久对不上。派生值只有一处真值。
--
-- ## 终态同步与回滚
-- - 建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 已同步三张表（新建库路径不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：按 `receipts → items → orders` 顺序 DROP；**有损**（丢采购单据）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS purchase_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    po_no VARCHAR(32) NOT NULL,                      -- CG-yyyyMMdd-NNNN（租户内唯一）
    supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id),
    order_date DATE NOT NULL,
    expected_date DATE,                              -- 预计到货日（可空：没约定就不写）
    status VARCHAR(24) NOT NULL DEFAULT 'ordered' CONSTRAINT ck_purchase_orders_status
        CHECK (status IN ('ordered', 'partially_received', 'received', 'closed')),
    total_amount NUMERIC(16,4) NOT NULL DEFAULT 0,   -- 明细金额之和（落单时冻结，不随后改）
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by VARCHAR(64),
    closed_reason TEXT,                              -- 提前关闭 / 断货 / 取消的原因（必填，服务层裁）
    remark TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE purchase_orders IS '采购单（issue #7369 段 4）：一张单可多次收货；状态由 Σ收货派生，客户端不可写';

CREATE UNIQUE INDEX IF NOT EXISTS uk_purchase_orders_no
    ON purchase_orders (tenant_id, po_no)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant_supplier
    ON purchase_orders (tenant_id, supplier_id, order_date DESC)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant_status
    ON purchase_orders (tenant_id, status, order_date DESC)
    WHERE deleted = FALSE;

ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'purchase_orders' AND policyname = 'tenant_isolation_purchase_orders'
    ) THEN
        CREATE POLICY tenant_isolation_purchase_orders ON purchase_orders
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    purchase_order_id VARCHAR(64) NOT NULL REFERENCES purchase_orders(id),
    line_no INT NOT NULL DEFAULT 1,
    product_id VARCHAR(64),
    sku_id VARCHAR(64) NOT NULL,
    quantity NUMERIC(16,4) NOT NULL CONSTRAINT ck_purchase_order_items_qty CHECK (quantity > 0),
    unit_price NUMERIC(16,4) NOT NULL DEFAULT 0 CONSTRAINT ck_purchase_order_items_price CHECK (unit_price >= 0),
    amount NUMERIC(16,4) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE purchase_order_items IS '采购单明细（非库存）：收货才进库存；「已收多少」= Σ receipts（派生，不在此累加）';

CREATE INDEX IF NOT EXISTS idx_purchase_order_items_po
    ON purchase_order_items (tenant_id, purchase_order_id)
    WHERE deleted = FALSE;

ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'purchase_order_items' AND policyname = 'tenant_isolation_purchase_order_items'
    ) THEN
        CREATE POLICY tenant_isolation_purchase_order_items ON purchase_order_items
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS purchase_order_receipts (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    purchase_order_id VARCHAR(64) NOT NULL REFERENCES purchase_orders(id),
    purchase_order_item_id VARCHAR(64) NOT NULL REFERENCES purchase_order_items(id),
    -- 挂到自动生成的那张入库单（手工登记收货时为空）：两张单据各自留痕，不互相顶替
    inbound_order_id VARCHAR(64) REFERENCES inbound_orders(id),
    quantity NUMERIC(16,4) NOT NULL CONSTRAINT ck_purchase_order_receipts_qty CHECK (quantity > 0),
    received_at DATE NOT NULL,
    remark TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE purchase_order_receipts IS '采购收货记录（issue #7369 段 4）：一次到货一行；数量上限由服务层按剩余量判';

CREATE INDEX IF NOT EXISTS idx_purchase_order_receipts_po
    ON purchase_order_receipts (tenant_id, purchase_order_id)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_purchase_order_receipts_item
    ON purchase_order_receipts (tenant_id, purchase_order_item_id)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_purchase_order_receipts_inbound
    ON purchase_order_receipts (tenant_id, inbound_order_id)
    WHERE inbound_order_id IS NOT NULL AND deleted = FALSE;

ALTER TABLE purchase_order_receipts ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'purchase_order_receipts' AND policyname = 'tenant_isolation_purchase_order_receipts'
    ) THEN
        CREATE POLICY tenant_isolation_purchase_order_receipts ON purchase_order_receipts
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing FROM (
        SELECT t FROM unnest(ARRAY['purchase_orders', 'purchase_order_items', 'purchase_order_receipts']) AS t
         WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t)
    ) x;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '采购单三表缺失：%（issue #7369 段 4 迁移未生效）', missing;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'purchase_orders' AND relrowsecurity IS TRUE
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'purchase_order_receipts' AND relrowsecurity IS TRUE
    ) THEN
        RAISE EXCEPTION '采购单表必须开启 RLS（跨租户读采购价 = 商业数据泄漏）';
    END IF;
END $$;

COMMIT;
