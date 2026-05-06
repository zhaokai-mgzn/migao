-- 为 products 表添加库存字段
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_warning_threshold INTEGER DEFAULT 10;

-- 添加库存索引（用于低库存查询）
CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock);

COMMENT ON COLUMN products.stock IS '库存数量';
COMMENT ON COLUMN products.stock_warning_threshold IS '库存预警阈值';
