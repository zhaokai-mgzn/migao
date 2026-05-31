-- ============================================================
-- 012_product_pricing_type.sql
-- 为商品表添加计价方式字段（pricing_type）
-- 修复商品详情页计价方式无法展示的问题
-- 取值参考前端 PricingType: per_meter / per_piece / fixed / per_area
-- ============================================================

ALTER TABLE products ADD COLUMN IF NOT EXISTS pricing_type VARCHAR(30) DEFAULT 'per_meter';
COMMENT ON COLUMN products.pricing_type IS '计价方式：per_meter(按米) / per_piece(按片) / fixed(固定价) / per_area(按面积)';
