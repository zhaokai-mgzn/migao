-- V20260903: 商品表增加 recommended 推荐标记（商家端显式打标）
-- 背景：C 端「新品推荐」需商家主动控制展示哪些商品，
-- 而非按创建时间自动取（商家无控制权，且最新创建≠值得推荐）。
-- 商家在商品管理页打标/取消 → admin-api 落库 → C 端 /chat/products/new-arrivals 只查 recommended=true。
ALTER TABLE products ADD COLUMN IF NOT EXISTS recommended BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_products_recommended ON products(tenant_id, recommended, status);

COMMENT ON COLUMN products.recommended IS '是否商家推荐（C 端新品推荐位展示依据，商家显式打标）';
