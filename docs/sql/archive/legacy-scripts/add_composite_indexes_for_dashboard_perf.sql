-- ================================================================
-- 仪表盘 + 列表页高频查询复合索引
-- 执行方式: psql -U <user> -d ai_customer_service -f this_file.sql
-- 幂等: 所有语句使用 IF NOT EXISTS，可重复执行
--
-- 背景: TenantLineInnerInterceptor 自动注入 AND tenant_id = <value>，
--       @TableLogic 自动追加 AND deleted = 0，
--       现有单列索引无法高效覆盖多条件组合查询。
-- ================================================================

-- 1. orders: 仪表盘订单趋势 + 状态分布 + COUNT
CREATE INDEX IF NOT EXISTS idx_orders_tenant_deleted_created
    ON orders(tenant_id, deleted, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_tenant_deleted_status
    ON orders(tenant_id, deleted, status);

-- 2. sessions: 仪表盘活跃会话统计
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_deleted_updated
    ON sessions(tenant_id, deleted, updated_at);

-- 3. notifications: 未读计数 (无 deleted 列)
CREATE INDEX IF NOT EXISTS idx_notifications_tenant_recipient_status
    ON notifications(tenant_id, recipient_id, status);

-- 4. after_sales_tickets: 售后工单 COUNT
CREATE INDEX IF NOT EXISTS idx_after_sales_tenant_deleted
    ON after_sales_tickets(tenant_id, deleted);

-- 5. product_skus: 低库存告警 (无 deleted 列)
CREATE INDEX IF NOT EXISTS idx_product_skus_tenant_stock
    ON product_skus(tenant_id, stock);
