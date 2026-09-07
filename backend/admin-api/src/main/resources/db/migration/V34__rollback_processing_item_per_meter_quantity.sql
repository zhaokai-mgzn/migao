-- V34: 回滚加工项「每米数量」密度（issue #3005，撤销 #2986）
-- 背景：行业加工费按米计价、辅料（罗马圈/四爪钩等）成本含在按米单价中。
-- per_piece 计价与「每米数量」密度推导不符合实际（数量对不上车间工艺、B 端无法对账），
-- 已与业务确认回滚：加工项计价方式仅保留 per_meter / per_set / fixed / per_area。

-- 1. 清理存量 per_piece 加工项（行业上「按个」的罗马圈/四爪钩是辅料，应含在按米加工费里；
--    其正确形态是 per_meter 加工项，如「打孔 8 元/米」。删除前级联清理商品关联，订单快照不受影响）
DELETE FROM product_processing_items
WHERE processing_item_id IN (SELECT id FROM processing_items WHERE pricing_method = 'per_piece');

DELETE FROM processing_items WHERE pricing_method = 'per_piece';

-- 2. 删除密度列（加工项默认密度 + 商品级覆盖密度）
ALTER TABLE processing_items DROP COLUMN IF EXISTS per_meter_quantity;
ALTER TABLE product_processing_items DROP COLUMN IF EXISTS custom_per_meter_quantity;