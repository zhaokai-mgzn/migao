-- V33: 商品表增加 allow_return_restock（是否允许退货回补库存）开关
-- 背景（issue #2991）：窗帘行业为定制产业，商品按客户尺寸裁剪后一旦退货
-- 无法再次出售。行业通用做法：商品主数据带「退货策略」（可再售/报废），
-- 售后退回时按商品策略决定是否回补库存。
-- 本开关默认 FALSE（关闭）：售后工单退款/退货完成后不回补库存、不引导重新上架；
-- 标准件/配件（窗帘杆、挂钩、成品帘等可再售商品）商家可显式开启，恢复行业通用
-- 「退货可再售」行为。
ALTER TABLE products ADD COLUMN IF NOT EXISTS allow_return_restock BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN products.allow_return_restock IS '是否允许退货回补库存（窗帘行业定制退货不可再售，默认不回补；可再售商品商家显式开启）';