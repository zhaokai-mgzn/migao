-- 原料仓/成品仓 + 成品仓位 + 统一入出库单（issue #7750）
--
-- ## 一句话
-- ① 仓库类型补 `material`（原料仓）/ `finished`（成品仓）；
-- ② 仓位成为实体（`warehouse_locations`：区域 + 仓位号）；
-- ③ 成品帘有自己的在库行（`finished_goods_stock`：一行 = 一个打包后的成品行，带仓位号）；
-- ④ 出库也有单据（`outbound_orders` / `outbound_order_items`），与入库单同形；
-- ⑤ 入库单/明细补上「业务类别 / 仓库引用 / 仓位 / 订单行来源 / 单位」——成品入库单复用同一张单据表，
--    不再另造第二套单据（用户 2026-10-25 裁定：「可以统一做成入库出库单」）。
--
-- ## 为什么成品入库复用 `inbound_orders` 而不是新开一张「成品入库单」表
-- 单据的生命周期（建单 → 过账 → 作废、单号取号、明细、权限、列表/详情读面、站内信）只有一套；
-- 另开一张表 = 上面每一件都要写第二份，且「入库单」菜单里看不到成品。区别只在**过账语义**：
-- `biz_category='fabric'` 走批次 + SKU 库存 + 移动加权成本（V111 原路）；
-- `biz_category='finished'` 走 `finished_goods_stock`（分配仓位、不碰 SKU 米数库存、不算成本）。
--
-- ## 为什么仓位号是「租户内唯一」而不是「仓内唯一」
-- 仓位号的用途是**扫码 / 口头指位**（「A-03 那件」），跨仓同号会让这句话有歧义。
-- 成品仓今天是唯一的成品仓；将来多成品仓时，本唯一索引就是那条「先扩口径再上线」的闸门
-- （放宽 = 一条迁移，且会先撞上面这条理由）。
--
-- ## 一个仓位同时只放一个在库成品（核心不变式）
-- `uk_finished_goods_bin_in_stock (tenant_id, bin_code) WHERE status='in_stock'` ——
-- 分配逻辑（最小空闲号）是**服务层**的事，但「两个成品占了同一个仓位」这种账实不符必须由 DB 兜住：
-- 并发打包时两个请求会各自算出同一个「空闲号」，靠服务层判空是拦不住的。
--
-- ## 出库单**没有草稿态**（`status` 只有 `posted`）
-- 用户要求「入库即过账」；出库是对称的物理动作（货已经拉走了），留着草稿只会多一个「谁忘了过账」的坑。
-- 出库单的建单请求就是过账请求：扣库存 + 落台账 + 落单据一步完成；失败整笔回滚（不写半张单）。
--
-- ## bootstrap 终态同步（同 V99/V108/V127/V133/V170/V193 纪律）
-- 新建库**不跑历史迁移链** ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql` 已同步本文件终态
-- （4 张表 + 增量列 + 索引 + RLS + 注释）。只改一处 ⇒ 新建库缺表/缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- 回滚段是可执行 SQL（本文件末尾），按「后建的表先删」顺序；`inbound_orders/items` 的增量列
-- 与类型 CHECK 回滚会把 `source='packing'` / `biz_category='finished'` 的存量行暴露成非法值 ⇒
-- 回滚前必须先处置这些单据（本单上线即启用，属**已知不可逆面**，照实登记）。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════
-- ① 仓库类型：material（原料仓）/ finished（成品仓）
-- ══════════════════════════════════════════════════════════════════════════════════
ALTER TABLE warehouses DROP CONSTRAINT IF EXISTS ck_warehouses_type;
ALTER TABLE warehouses ADD CONSTRAINT ck_warehouses_type
    CHECK (warehouse_type IN ('store', 'processing', 'material', 'finished'));

-- 存量默认仓回填为原料仓：它装的就是布料（V189 种下的 MAIN 是唯一默认仓）。
-- 口径 = 「默认仓 = 原料仓」；非默认的 store/processing 仓一字不动（商家自建语义不明）。
UPDATE warehouses SET warehouse_type = 'material'
 WHERE warehouse_type = 'store' AND is_default AND deleted = 0;

COMMENT ON COLUMN warehouses.warehouse_type IS
    '仓库类型（V196 / issue #7750）：store 门店仓 / processing 加工仓 / material 原料仓（布料）/ finished 成品仓（成品帘）';

-- ══════════════════════════════════════════════════════════════════════════════════
-- ② 仓位（成品仓库位）
-- ══════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS warehouse_locations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    zone_code VARCHAR(16) NOT NULL DEFAULT 'A',        -- 区域编码（成品仓默认 A 区）
    zone_name VARCHAR(32) NOT NULL DEFAULT '成品区',    -- 区域名称（展示用；区域重命名不回写历史行）
    bin_code VARCHAR(32) NOT NULL,                     -- 仓位号（如 A-01）：租户内唯一（扫码/口头指位都认它）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_warehouse_locations_status CHECK (status IN ('active', 'inactive'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_warehouse_locations_bin
    ON warehouse_locations (tenant_id, bin_code) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_warehouse_locations_warehouse
    ON warehouse_locations (tenant_id, warehouse_id);

COMMENT ON TABLE warehouse_locations IS
    '仓位（V196 / issue #7750）：成品仓里的货位。bin_code = 仓位号（租户内唯一），zone_code/zone_name = 区域';
COMMENT ON COLUMN warehouse_locations.bin_code IS
    '仓位号（如 A-01）：同租户唯一 —— 扫码与口头指位都认它，跨仓同号会让这句话有歧义';

-- 库存台账的变更来源补 outbound（出库单过账；改前只有 order/aftersales/manual/inbound）
ALTER TABLE stock_ledger_entries DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason;
ALTER TABLE stock_ledger_entries ADD CONSTRAINT ck_stock_ledger_reason
    CHECK (reason IN ('order', 'aftersales', 'manual', 'inbound', 'outbound'));

-- ══════════════════════════════════════════════════════════════════════════════════
-- ③ 入库单：业务类别 + 仓库引用；明细：仓位 / 订单行来源 / 单位 / 品名快照
-- ══════════════════════════════════════════════════════════════════════════════════
ALTER TABLE inbound_orders ADD COLUMN IF NOT EXISTS biz_category VARCHAR(16) NOT NULL DEFAULT 'fabric';
ALTER TABLE inbound_orders ADD COLUMN IF NOT EXISTS warehouse_id BIGINT REFERENCES warehouses(id);
-- source 扩一个 packing（成品打包入库，由打包动作自动建单；至今没有第二个写方）
ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;
ALTER TABLE inbound_orders ADD CONSTRAINT ck_inbound_orders_source
    CHECK (source IN ('purchase', 'opening', 'photo', 'packing'));
ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_biz_category;
ALTER TABLE inbound_orders ADD CONSTRAINT ck_inbound_orders_biz_category
    CHECK (biz_category IN ('fabric', 'finished'));

CREATE INDEX IF NOT EXISTS idx_inbound_orders_tenant_warehouse
    ON inbound_orders (tenant_id, warehouse_id) WHERE warehouse_id IS NOT NULL AND deleted = 0;

COMMENT ON COLUMN inbound_orders.biz_category IS
    '业务类别（V196 / issue #7750）：fabric 布料（批次 + SKU 库存 + 移动加权成本）/ finished 成品（仓位，不碰米数库存）';
COMMENT ON COLUMN inbound_orders.warehouse_id IS
    '仓库引用（V196）：与 warehouse（文本快照）**不是同一件事** —— 文本是当时的单据快照，本列是主数据引用';
COMMENT ON COLUMN inbound_orders.source IS
    '单据来源：purchase 采购收货 / opening 期初建账 / photo 工人拍照入库 / packing 成品打包入库（V196 追加）';

ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS location_id BIGINT;
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS bin_code VARCHAR(32);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS order_id VARCHAR(64);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS order_item_id VARCHAR(64);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS order_no VARCHAR(64);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS unit VARCHAR(8) NOT NULL DEFAULT 'm';
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS product_name VARCHAR(255);

COMMENT ON COLUMN inbound_order_items.location_id IS
    '仓位引用（V196）：仅 biz_category=finished 的单据有值；过账时分配（同一事务内写）';
COMMENT ON COLUMN inbound_order_items.bin_code IS
    '仓位号快照（V196）：仓位行改号/软删后历史单据仍可追溯';
COMMENT ON COLUMN inbound_order_items.order_id IS
    '成品行来源订单（V196）：仅 biz_category=finished 有值，追溯「这件成品是哪张单的哪一行」';
COMMENT ON COLUMN inbound_order_items.order_item_id IS
    '成品行来源订单明细（V196）：与 finished_goods_stock.order_item_id 同键，一个订单行 = 一个仓位';
COMMENT ON COLUMN inbound_order_items.order_no IS
    '成品行来源订单号快照（V196）：成品在库行展示用（不必回表 orders）';
COMMENT ON COLUMN inbound_order_items.unit IS
    '计量单位（V196）：m = 米（布料行，恒为米）/ set = 套（成品行）';
COMMENT ON COLUMN inbound_order_items.product_name IS
    '品名快照（V196）：成品行没有 SKU 货号，展示要它';

-- ══════════════════════════════════════════════════════════════════════════════════
-- ④ 出库单（与入库单同形；只有 posted 一个状态 —— 建单即过账）
-- ══════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS outbound_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    outbound_no VARCHAR(32) NOT NULL,                  -- CK-yyyyMMdd-NNNN（租户内唯一）
    biz_category VARCHAR(16) NOT NULL DEFAULT 'fabric',
    source VARCHAR(16) NOT NULL DEFAULT 'manual',      -- manual 手工出库 / ship 成品发货出库
    warehouse_id BIGINT REFERENCES warehouses(id),
    warehouse VARCHAR(64),                             -- 仓库文本快照（与入库单同款）
    outbound_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'posted',
    total_amount NUMERIC(16,4) NOT NULL DEFAULT 0,
    order_id VARCHAR(64),
    order_no VARCHAR(64),
    remark VARCHAR(255),
    posted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    posted_by VARCHAR(64),
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_outbound_orders_biz_category CHECK (biz_category IN ('fabric', 'finished')),
    CONSTRAINT ck_outbound_orders_source CHECK (source IN ('manual', 'ship')),
    -- 出库单**没有草稿态**（V196 决定，见头注）：写别的状态被 DB 拒绝，不靠服务层自觉
    CONSTRAINT ck_outbound_orders_status CHECK (status = 'posted')
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_outbound_orders_no
    ON outbound_orders (tenant_id, outbound_no) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_outbound_orders_tenant_date
    ON outbound_orders (tenant_id, outbound_date DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_orders_order
    ON outbound_orders (tenant_id, order_id) WHERE order_id IS NOT NULL AND deleted = 0;

COMMENT ON TABLE outbound_orders IS
    '出库单（V196 / issue #7750）：布料手工出库 + 成品发货出库同形；建单即过账（无草稿态）';
COMMENT ON COLUMN outbound_orders.biz_category IS
    '业务类别：fabric 布料（扣 SKU 库存 + 台账）/ finished 成品（释放 finished_goods_stock）';
COMMENT ON COLUMN outbound_orders.source IS
    '来源：manual 手工出库（布料）/ ship 发货出库（成品，由发货动作自动建单）';

CREATE TABLE IF NOT EXISTS outbound_order_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    outbound_order_id VARCHAR(64) NOT NULL REFERENCES outbound_orders(id) ON DELETE CASCADE,
    sku_id BIGINT,                                    -- 布料行有值；成品行可空（成品按订单行，不按 SKU）
    product_id VARCHAR(64),
    sku_code VARCHAR(64),
    product_name VARCHAR(255),
    order_id VARCHAR(64),
    order_item_id VARCHAR(64),
    location_id BIGINT,                               -- 成品行：出库的仓位引用
    bin_code VARCHAR(32),                             -- 仓位号快照
    quantity NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(8) NOT NULL DEFAULT 'm',
    unit_cost NUMERIC(12,4),
    amount NUMERIC(16,4),
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_outbound_order_items_order
    ON outbound_order_items (tenant_id, outbound_order_id);
CREATE INDEX IF NOT EXISTS idx_outbound_order_items_sku
    ON outbound_order_items (tenant_id, sku_id) WHERE sku_id IS NOT NULL;

COMMENT ON TABLE outbound_order_items IS
    '出库单明细（V196）：布料行 = SKU + 米数；成品行 = 订单行 + 仓位 + 套数';

-- ══════════════════════════════════════════════════════════════════════════════════
-- ⑤ 成品在库（一行 = 一个打包后的成品订单行）
-- ══════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS finished_goods_stock (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
    location_id BIGINT NOT NULL REFERENCES warehouse_locations(id),
    bin_code VARCHAR(32) NOT NULL,                     -- 仓位号快照（分配那一刻写死）
    order_id VARCHAR(64) NOT NULL,
    order_no VARCHAR(64),
    order_item_id VARCHAR(64) NOT NULL,                -- 一个成品订单行 = 一行在库（不按套拆行）
    product_id VARCHAR(64),
    product_name VARCHAR(255),
    quantity NUMERIC(10,2) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(8) NOT NULL DEFAULT 'set',            -- set = 套
    status VARCHAR(16) NOT NULL DEFAULT 'in_stock',
    inbound_order_id VARCHAR(64),
    outbound_order_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_finished_goods_stock_status CHECK (status IN ('in_stock', 'shipped', 'unpacked'))
);

-- 🔴 核心不变式：一个仓位同一时刻只放一个在库成品（并发打包会各自算出同一个「空闲号」）
CREATE UNIQUE INDEX IF NOT EXISTS uk_finished_goods_bin_in_stock
    ON finished_goods_stock (tenant_id, bin_code)
    WHERE status = 'in_stock' AND deleted = 0;
-- 同一个订单行同时只能有一行在库（重复打包 = 重复入库）
CREATE UNIQUE INDEX IF NOT EXISTS uk_finished_goods_order_item_in_stock
    ON finished_goods_stock (tenant_id, order_item_id)
    WHERE status = 'in_stock' AND deleted = 0;
CREATE INDEX IF NOT EXISTS idx_finished_goods_order
    ON finished_goods_stock (tenant_id, order_id) WHERE deleted = 0;

COMMENT ON TABLE finished_goods_stock IS
    '成品在库（V196 / issue #7750）：一行 = 一个打包后的成品订单行（含仓位号）；status 三态 in_stock/shipped/unpacked';
COMMENT ON COLUMN finished_goods_stock.bin_code IS
    '仓位号快照：仓位行改号/软删后历史在库行仍可追溯；在库行的 (tenant, bin_code) 唯一 = 一仓一位';
COMMENT ON COLUMN finished_goods_stock.order_item_id IS
    '成品订单行：一个订单行 = 一个在库行（不按套拆）—— 与「一行 = 一个批次」的入库粒度口径同源';

-- ══════════════════════════════════════════════════════════════════════════════════
-- ⑥ 租户隔离（RLS）
-- ══════════════════════════════════════════════════════════════════════════════════
ALTER TABLE warehouse_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE finished_goods_stock ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'warehouse_locations'
                   AND policyname = 'tenant_isolation_warehouse_locations') THEN
        CREATE POLICY tenant_isolation_warehouse_locations ON warehouse_locations
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'outbound_orders'
                   AND policyname = 'tenant_isolation_outbound_orders') THEN
        CREATE POLICY tenant_isolation_outbound_orders ON outbound_orders
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'outbound_order_items'
                   AND policyname = 'tenant_isolation_outbound_order_items') THEN
        CREATE POLICY tenant_isolation_outbound_order_items ON outbound_order_items
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'finished_goods_stock'
                   AND policyname = 'tenant_isolation_finished_goods_stock') THEN
        CREATE POLICY tenant_isolation_finished_goods_stock ON finished_goods_stock
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════
-- 终态对账（fail-closed）：缺任一表/列 ⇒ 迁移失败，不许「部署 success 但没生效」
-- ══════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM unnest(ARRAY['warehouse_locations', 'outbound_orders', 'outbound_order_items',
                        'finished_goods_stock']) AS t
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_name = t AND table_schema = 'public');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '入出库单/仓位表族缺表：%（issue #7750 迁移未生效）', missing;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'inbound_orders' AND column_name = 'biz_category') THEN
        RAISE EXCEPTION 'inbound_orders 缺 biz_category 列（issue #7750）';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'inbound_order_items' AND column_name = 'bin_code') THEN
        RAISE EXCEPTION 'inbound_order_items 缺 bin_code 列（issue #7750）';
    END IF;
END $$;

COMMIT;

-- ══════════════════════════════════════════════════════════════════════════════════
-- 回滚（可执行；顺序 = 后建先删）
-- ⚠️ 回滚前先处置 biz_category='finished' / source='packing' 的单据与出库单，否则下面的 CHECK 加不回去。
-- ══════════════════════════════════════════════════════════════════════════════════
-- BEGIN;
-- DROP TABLE IF EXISTS finished_goods_stock;
-- DROP TABLE IF EXISTS outbound_order_items;
-- DROP TABLE IF EXISTS outbound_orders;
-- DROP TABLE IF EXISTS warehouse_locations;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS product_name;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS order_no;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS unit;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS order_item_id;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS order_id;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS bin_code;
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS location_id;
-- ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_biz_category;
-- ALTER TABLE inbound_orders DROP COLUMN IF EXISTS warehouse_id;
-- ALTER TABLE inbound_orders DROP COLUMN IF EXISTS biz_category;
-- ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;
-- ALTER TABLE inbound_orders ADD CONSTRAINT ck_inbound_orders_source
--     CHECK (source IN ('purchase', 'opening', 'photo'));
-- ALTER TABLE stock_ledger_entries DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason;
-- ALTER TABLE stock_ledger_entries ADD CONSTRAINT ck_stock_ledger_reason
--     CHECK (reason IN ('order', 'aftersales', 'manual', 'inbound'));
-- ALTER TABLE warehouses DROP CONSTRAINT IF EXISTS ck_warehouses_type;
-- ALTER TABLE warehouses ADD CONSTRAINT ck_warehouses_type
--     CHECK (warehouse_type IN ('store', 'processing'));
-- COMMIT;
