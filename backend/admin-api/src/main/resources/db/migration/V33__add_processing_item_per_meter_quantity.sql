-- V33: 加工项「每米数量」密度（issue #2986）
-- per_piece 计价加工项按个计价但数量随面料米数线性变化（打孔 ~6 个/米、四爪钩 ~10 个/米），
-- 配置密度后订单数量自动推导 = ceil(面料米数 × 每米数量)，用户零感知。

ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS per_meter_quantity DECIMAL(6,2);
COMMENT ON COLUMN processing_items.per_meter_quantity
    IS '每米数量（密度）：per_piece 计价加工项每米布料的加工个数（打孔约 6 个/米、四爪钩约 10 个/米），NULL=不适用/未配置';

ALTER TABLE product_processing_items ADD COLUMN IF NOT EXISTS custom_per_meter_quantity DECIMAL(6,2);
COMMENT ON COLUMN product_processing_items.custom_per_meter_quantity
    IS '商品专属每米数量（密度覆盖）：NULL=用加工项默认密度，非空=商品级覆盖';
