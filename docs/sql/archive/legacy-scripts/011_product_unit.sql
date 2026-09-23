-- ============================================================
-- 011_product_unit.sql
-- 为商品表添加计价单位字段
-- 修复商品表单"计价单位"(unit) 字段保存丢失问题（Task #1）
-- ============================================================

ALTER TABLE products ADD COLUMN IF NOT EXISTS unit VARCHAR(32) DEFAULT '件';
COMMENT ON COLUMN products.unit IS '计价单位（米/件/套等）';
