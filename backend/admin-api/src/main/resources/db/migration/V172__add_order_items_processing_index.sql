-- `order_items` 的「含加工项」筛选用索引（2026-10-20 索引审查第二刀）
--
-- ## 读面
--
-- `OrderService#getOrderPage` 的 `hasProcessing` 过滤：先取本租户**有加工信息**的明细
-- （`processing_info IS NOT NULL`，投影 order_id + processing_info），在内存里按
-- `OrderShipGuard.extractProcessingItems` 做**精确**判定（空对象 / 空数组都不算），
-- 再把命中的 order_id 拼进订单查询的 `IN (…)`。
--
-- 该查询**已经有**粗过滤（`isNotNull`），不是无界全表 —— 但它没有任何索引支撑：
-- `order_items` 上的索引是 `(tenant_id)` / `(order_id)` / `(product_id)` / `(deleted)` 四条单列，
-- 本查询只能按 tenant 前缀取回**全部明细**再逐行判 `processing_info`（JSONB 宽行、TOAST 可能被解压）。
--
-- ## 为什么是这条形态
--
-- · 前导 `(tenant_id, order_id)`：租户内按订单定位，且 `order_id` 是后续 `IN (…)` 的键；
-- · **部分谓词** `deleted = 0 AND processing_info IS NOT NULL`：把索引体量压到「真有加工信息的明细」
--   （装配类目商家通常只占一小部分行），同时让扫描**只回这些行**；
-- · 不 `INCLUDE (processing_info)`：JSONB 可能很大，塞进索引会显著抬高写放大与索引体积
--   （本表是订单明细，写入频繁）。读面仍是 index → heap 的一跳，但**行数**已被压到很小。
--
-- ## 判据
--
-- · `tests/unit_ci_workflows/test_db_hot_path_indexes.py` 的
--   `test_every_live_migration_index_reaches_bootstrap`（本迁移的产成品必须与建库脚本逐字一致）；
-- · `backend/admin-api/src/test/java/com/migao/admin/service/ProductionPieceworkSummaryTest.java`
--   的 `pieceworkSummaryOnlyLoadsOperationInstancesOfTheLoggedOrders`（第二刀的代码侧判据）。
--
-- ## 幂等
--
-- `IF NOT EXISTS`；整份文件一个事务。回滚：`DROP INDEX IF EXISTS idx_order_items_tenant_processing;`

CREATE INDEX IF NOT EXISTS idx_order_items_tenant_processing
    ON order_items (tenant_id, order_id)
    WHERE deleted = 0 AND processing_info IS NOT NULL;
