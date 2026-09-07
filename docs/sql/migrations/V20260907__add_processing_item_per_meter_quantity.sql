-- V20260907: 加工项增加「每米数量」密度字段（issue #2986）
-- 背景：per_piece 计价的加工项（打孔/四爪钩/罗马圈）按个计价但数量随面料米数线性变化。
-- 行业标准密度（打孔 6 个/米、四爪钩 10 个/米等）配置后，订单/报价数量自动推导
-- = ceil(面料米数 × 每米数量)，用户零感知。per_meter / per_set / fixed 不适用（留空）。

-- 1. 加工项默认每米数量（仅 per_piece 计价有意义）
ALTER TABLE processing_items ADD COLUMN per_meter_quantity DECIMAL(6,2);
COMMENT ON COLUMN processing_items.per_meter_quantity
    IS '每米数量（密度）：per_piece 计价加工项每米布料的加工个数（打孔约 6 个/米、四爪钩约 10 个/米），NULL=不适用/未配置';

-- 2. 商品级覆盖每米数量（语义同 custom_price：覆盖则用商品专属密度，否则用加工项默认）
ALTER TABLE product_processing_items ADD COLUMN custom_per_meter_quantity DECIMAL(6,2);
COMMENT ON COLUMN product_processing_items.custom_per_meter_quantity
    IS '商品专属每米数量（密度覆盖）：NULL=用加工项默认密度，非空=商品级覆盖（如某款帘孔距偏好 5 个/米）';
