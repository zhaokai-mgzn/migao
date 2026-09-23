-- V20260907-ROLLBACK: 加工项「每米数量」密度回滚（issue #3005，撤销 V20260907 / #2986）
-- 背景：行业加工费按米计价、辅料（罗马圈/四爪钩等）成本含在按米单价中（如「打孔式 8 元」即含圈含工）。
-- per_piece 计价与「每米数量」密度推导不符合实际（数量与车间工艺对不上、B 端订单无法对账），已回滚：
--   加工项计价方式仅 per_meter / per_set / fixed / per_area；无 per_piece、无「每米数量」密度；
--   订单数量 = 面料米数（per_meter）/ 1（per_set/fixed/per_area）。
-- 实际执行位见 backend/admin-api/src/main/resources/db/migration/V34__rollback_processing_item_per_meter_quantity.sql
-- （本文件为设计文档记录）。

-- 1. 清理存量 per_piece 加工项（行业上「按个」的罗马圈/四爪钩是辅料，应含在按米加工费里）
-- DELETE FROM product_processing_items
-- WHERE processing_item_id IN (SELECT id FROM processing_items WHERE pricing_method = 'per_piece');
-- DELETE FROM processing_items WHERE pricing_method = 'per_piece';

-- 2. 删除密度列（加工项默认密度 + 商品级覆盖密度）
-- ALTER TABLE processing_items DROP COLUMN IF EXISTS per_meter_quantity;
-- ALTER TABLE product_processing_items DROP COLUMN IF EXISTS custom_per_meter_quantity;