-- ============================================================
-- 003_orders.sql - 订单管理模块表结构
-- 版本: v1.0
-- 日期: 2026-04-18
-- 说明: 创建订单表和订单明细表
-- ============================================================

-- ============================================================
-- 1. 订单表 (orders)
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_no VARCHAR(64) NOT NULL UNIQUE,          -- 订单号
    customer_name VARCHAR(100),                     -- 客户姓名
    customer_phone VARCHAR(20),                     -- 客户电话
    customer_address TEXT,                          -- 客户地址
    total_amount DECIMAL(12,2) DEFAULT 0,           -- 总金额
    status VARCHAR(20) DEFAULT 'pending',           -- 状态: pending/confirmed/producing/completed/cancelled
    remark TEXT,                                     -- 备注
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_orders_tenant ON orders(tenant_id);
CREATE INDEX idx_orders_order_no ON orders(order_no);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_deleted ON orders(deleted);

-- ============================================================
-- 2. 订单明细表 (order_items)
-- ============================================================
CREATE TABLE IF NOT EXISTS order_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    product_id VARCHAR(36),                         -- 关联商品
    product_name VARCHAR(200),                      -- 商品名称
    quantity INTEGER DEFAULT 1,                     -- 数量
    unit_price DECIMAL(12,2),                       -- 单价
    width DECIMAL(8,2),                             -- 宽度(米)
    height DECIMAL(8,2),                            -- 高度(米)
    processing_info JSONB,                          -- 加工项详情JSON
    subtotal DECIMAL(12,2),                         -- 小计
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_order_items_tenant ON order_items(tenant_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_order_items_deleted ON order_items(deleted);

-- ============================================================
-- 3. 物流跟踪记录表 (order_logistics)
-- ============================================================
CREATE TABLE IF NOT EXISTS order_logistics (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(64) NOT NULL REFERENCES orders(id),
    logistics_company VARCHAR(128) NOT NULL,
    tracking_no VARCHAR(128) NOT NULL,
    status VARCHAR(32) DEFAULT 'in_transit',  -- in_transit / delivered / returned
    tracking_info JSONB DEFAULT '[]',  -- 物流轨迹
    shipped_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_order_logistics_tenant ON order_logistics(tenant_id);
CREATE INDEX idx_order_logistics_order ON order_logistics(order_id);
CREATE INDEX idx_order_logistics_tracking ON order_logistics(tracking_no);
CREATE INDEX idx_order_logistics_deleted ON order_logistics(deleted);

-- ============================================================
-- RLS 策略（多租户隔离）
-- ============================================================

-- orders RLS
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_orders ON orders
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- order_items RLS
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_items ON order_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- order_logistics RLS
ALTER TABLE order_logistics ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_logistics ON order_logistics
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
