-- ============================================================
-- Migration: 010_product_detail_images
-- 添加商品详情图字段（products.detail_images）
-- 修复"商品属性"和"详情图"区块数据保存丢失问题。
-- 商品属性（brand/specifications）继续使用 product_attributes 表（attr_key/attr_value）。
-- 详情图因 URL 长度通常超过 product_attributes.attr_value 的 VARCHAR(100) 限制，
-- 采用 JSONB 列存储于 products 主表，与 products.images 字段保持一致风格。
-- ============================================================

-- 添加 detail_images 列（JSONB，默认空数组）
ALTER TABLE products ADD COLUMN IF NOT EXISTS detail_images JSONB DEFAULT '[]';

COMMENT ON COLUMN products.detail_images IS '商品详情图URL列表（JSONB数组）';
