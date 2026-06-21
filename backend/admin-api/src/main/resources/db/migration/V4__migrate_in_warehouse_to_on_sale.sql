-- 一次性迁移：in_warehouse → on_sale
-- 幂等：WHERE 已过滤，重复执行不影响已迁移数据
UPDATE products SET status = 'on_sale' WHERE status = 'in_warehouse';
