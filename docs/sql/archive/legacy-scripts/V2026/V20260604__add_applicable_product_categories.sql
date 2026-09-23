-- V20260604: 加工项增加适用商品分类关联
-- 记录哪些商品分类需要此加工项（JSONB 数组存储分类ID）
ALTER TABLE processing_items ADD COLUMN applicable_product_categories JSONB DEFAULT '[]';
