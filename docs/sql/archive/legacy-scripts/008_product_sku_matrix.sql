-- ============================================================
-- 008_product_sku_matrix.sql - 商品SKU矩阵功能
-- 版本: v1.0
-- 日期: 2026-05-29
-- 说明: 创建商品颜色、SKU矩阵、商品属性、商品加工项关联表，
--       并扩展 products 和 orders 表字段
-- 依赖: 001_init.sql (products, processing_items)
--        003_orders.sql (orders)
-- ============================================================

-- ============================================================
-- 1. 商品颜色分类表 (product_colors)
-- ============================================================
CREATE TABLE IF NOT EXISTS product_colors (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    color_name VARCHAR(30) NOT NULL,           -- 主色名称（如"红色"、"米白"）
    main_color_hex VARCHAR(7),                 -- 色值 #FFFFFF
    color_image_url TEXT NOT NULL,             -- 颜色图片URL（必填）
    remark VARCHAR(30),                        -- 备注（选填）
    sort_order INTEGER DEFAULT 0,              -- 排序
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引：按租户+商品查询
CREATE INDEX IF NOT EXISTS idx_product_colors_tenant_product ON product_colors(tenant_id, product_id);

COMMENT ON TABLE product_colors IS '商品颜色分类表，每商品最多200种颜色（应用层校验）';

-- ============================================================
-- 2. SKU矩阵表 (product_skus)
-- ============================================================
CREATE TABLE IF NOT EXISTS product_skus (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    color_id BIGINT REFERENCES product_colors(id) ON DELETE CASCADE,
    selling_method VARCHAR(20) NOT NULL,       -- 售卖方式: bulk_cut(散剪) / full_roll(整卷)
    door_width VARCHAR(20) NOT NULL,           -- 规格尺寸: 2.8m / 3.2m / 3.4m
    price DECIMAL(10,2) NOT NULL DEFAULT 0,    -- 价格
    stock INTEGER NOT NULL DEFAULT 0,          -- 库存
    sku_code VARCHAR(50),                      -- SKU编码（自动生成）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引：按租户+商品查询
CREATE INDEX IF NOT EXISTS idx_product_skus_tenant_product ON product_skus(tenant_id, product_id);

-- 唯一约束：防止重复SKU（同商品+颜色+售卖方式+门幅）
ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination
    UNIQUE (product_id, color_id, selling_method, door_width);

COMMENT ON TABLE product_skus IS 'SKU矩阵表，颜色×售卖方式×门幅 组合';

-- ============================================================
-- 3. 商品属性表 (product_attributes)
-- ============================================================
CREATE TABLE IF NOT EXISTS product_attributes (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    attr_key VARCHAR(30) NOT NULL,             -- 属性名: brand/material/weight/function/style/craft/pattern
    attr_value VARCHAR(100) NOT NULL,          -- 属性值
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引：按租户+商品查询
CREATE INDEX IF NOT EXISTS idx_product_attributes_tenant_product ON product_attributes(tenant_id, product_id);

-- 唯一约束：每商品每属性唯一
ALTER TABLE product_attributes ADD CONSTRAINT uq_product_attributes_key
    UNIQUE (product_id, attr_key);

COMMENT ON TABLE product_attributes IS '商品属性表，支持 brand/material/weight/function/style/craft/pattern 等属性';

-- ============================================================
-- 4. products 表扩展字段
-- ============================================================
ALTER TABLE products ADD COLUMN IF NOT EXISTS sku_code VARCHAR(30);
COMMENT ON COLUMN products.sku_code IS '商品货号';

ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_deduction_mode VARCHAR(20) DEFAULT 'on_order';
COMMENT ON COLUMN products.stock_deduction_mode IS '库存扣减模式: on_order(拍下减) / on_payment(付款减)';

ALTER TABLE products ADD COLUMN IF NOT EXISTS sales_count INTEGER DEFAULT 0;
COMMENT ON COLUMN products.sales_count IS '累计销量';

ALTER TABLE products ADD COLUMN IF NOT EXISTS sales_amount DECIMAL(12,2) DEFAULT 0;
COMMENT ON COLUMN products.sales_amount IS '累计销售额';

ALTER TABLE products ADD COLUMN IF NOT EXISTS edited_by VARCHAR(50);
COMMENT ON COLUMN products.edited_by IS '最后编辑人';

ALTER TABLE products ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP WITH TIME ZONE;
COMMENT ON COLUMN products.edited_at IS '最后编辑时间';

-- 注意: 现有 status 字段为 VARCHAR(32)，可直接存储新状态值 'in_warehouse' / 'under_review'
-- 无需修改约束（VARCHAR 类型无枚举限制，状态校验在应用层实现）

-- ============================================================
-- 5. 商品-加工项关联表 (product_processing_items)
-- ============================================================
CREATE TABLE IF NOT EXISTS product_processing_items (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    processing_item_id VARCHAR(64) NOT NULL REFERENCES processing_items(id) ON DELETE CASCADE,
    custom_price DECIMAL(10,2),               -- 商品专属加工价格（null则用默认价）
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引：按租户+商品查询
CREATE INDEX IF NOT EXISTS idx_product_processing_items_tenant_product ON product_processing_items(tenant_id, product_id);

-- 唯一约束：防止重复关联
ALTER TABLE product_processing_items ADD CONSTRAINT uq_product_processing_items_relation
    UNIQUE (product_id, processing_item_id);

COMMENT ON TABLE product_processing_items IS '商品-加工项关联表，支持自定义加工价格';

-- ============================================================
-- 6. orders 表扩展字段
-- ============================================================
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'unpaid';
COMMENT ON COLUMN orders.payment_status IS '支付状态: unpaid/paid/refunded';

ALTER TABLE orders ADD COLUMN IF NOT EXISTS stock_deducted BOOLEAN DEFAULT FALSE;
COMMENT ON COLUMN orders.stock_deducted IS '是否已扣库存';

ALTER TABLE orders ADD COLUMN IF NOT EXISTS follow_status VARCHAR(20) DEFAULT 'pending';
COMMENT ON COLUMN orders.follow_status IS '跟进状态: pending/following/completed';

-- ============================================================
-- RLS 策略（多租户隔离）
-- ============================================================

-- product_colors RLS
ALTER TABLE product_colors ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_product_colors ON product_colors
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- product_skus RLS
ALTER TABLE product_skus ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_product_skus ON product_skus
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- product_attributes RLS
ALTER TABLE product_attributes ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_product_attributes ON product_attributes
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- product_processing_items RLS
ALTER TABLE product_processing_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_product_processing_items ON product_processing_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
