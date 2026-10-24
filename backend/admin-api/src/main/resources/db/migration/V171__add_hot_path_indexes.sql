-- 热点查询索引补齐（2026-10-20 索引审查第一刀）
--
-- ## 一句话
--
-- 老表（init 那批）的索引是「**单列拼盘**」：`(tenant_id)` / `(status)` / `(deleted)` 各自一条，
-- 而真实读面是 `WHERE tenant_id = ? AND deleted = 0 [AND 过滤列] ORDER BY <时间列> DESC LIMIT n`。
-- 这种形态下规划器只有两条坏路：取本租户**全部**行再 Sort，或从全库时间索引往回扫、逐行丢掉他租户。
-- 两条都随**全库总量**增长，而不是随本租户行数 ⇒ 商家一多、单商家历史一长就慢。
--
-- ★ 本迁移只**增索引**（外加删一条与 UNIQUE 约束完全重复的索引）。**不改任何查询、不改任何列**。
-- ★ 新表（`inbound_orders` / `fabric_remnants` / `stock_batch_consumptions` 等）本来就是
--   `(tenant_id, …) WHERE deleted = 0` 的部分复合索引 —— 本条是把老表补到同一形态，**不是新规范**。
--
-- ## 判据（会红）
--
-- · `tests/unit_ci_workflows/test_db_hot_path_indexes.py`：
--   ① 本文件的每条索引都必须在 `db/init/schema.sql` 里**逐字存在**（结构变更同步契约）；
--   ② schema.sql 里的同名索引列/谓词必须与本文件**一致**（防两边漂移）；
--   ③ 红线用例：任选一条索引从 schema.sql 删掉 ⇒ ①必红（注入式自证）；
--   ④ 每条索引的**前导列必须是 tenant_id**（跨租户表除外：`inbound_labels` 是全局码空间）。
--
-- ## 幂等
--
-- 全部 `IF NOT EXISTS` / `IF EXISTS`；重复执行是空操作。整份文件 = 一个事务
-- （`MigrationRunner` 是 `jdbc.execute(整份文本)`），任一句失败即整份回滚且不记账。
--
-- ## 回滚 SQL（保留于注释；按需手工执行 —— 只回滚索引，不动数据）
--
-- ```sql
-- DROP INDEX IF EXISTS idx_orders_tenant_created;
-- DROP INDEX IF EXISTS idx_orders_tenant_status_created;
-- DROP INDEX IF EXISTS idx_orders_tenant_phone;
-- DROP INDEX IF EXISTS idx_orders_tenant_user_created;
-- DROP INDEX IF EXISTS idx_notifications_inbox;
-- DROP INDEX IF EXISTS idx_notifications_unread;
-- DROP INDEX IF EXISTS idx_audit_logs_tenant_created;
-- DROP INDEX IF EXISTS idx_audit_logs_tenant_action_created;
-- DROP INDEX IF EXISTS idx_consumptions_tenant_batch_id;
-- DROP INDEX IF EXISTS idx_ledger_tenant_sku_cover;
-- DROP INDEX IF EXISTS idx_work_logs_tenant_worker_id_date;
-- DROP INDEX IF EXISTS idx_work_logs_tenant_date;
-- DROP INDEX IF EXISTS idx_labels_short_code;
-- DROP INDEX IF EXISTS idx_labels_revoked_code;
-- DROP INDEX IF EXISTS idx_products_tenant_created;
-- DROP INDEX IF EXISTS idx_products_tenant_sku_code;
-- DROP INDEX IF EXISTS idx_skus_tenant_sku_code;
-- DROP INDEX IF EXISTS idx_customer_profiles_tenant_created;
-- DROP INDEX IF EXISTS idx_agent_sessions_tenant_created;
-- DROP INDEX IF EXISTS idx_agent_sessions_ended;
-- DROP INDEX IF EXISTS idx_quality_inspections_tenant_time;
-- DROP INDEX IF EXISTS idx_processing_orders_tenant_created;
-- DROP INDEX IF EXISTS idx_set_part_tokens_order;
-- DROP INDEX IF EXISTS idx_position_operations_tenant_set;
-- DROP INDEX IF EXISTS idx_shipments_tenant_list;
-- DROP INDEX IF EXISTS idx_knowledge_cards_tenant_status_updated;
-- DROP INDEX IF EXISTS idx_users_tenant_created;
-- DROP INDEX IF EXISTS idx_processing_items_tenant_created;
-- DROP INDEX IF EXISTS idx_sessions_tenant_updated;
-- DROP INDEX IF EXISTS idx_role_permissions_permission;
-- DROP INDEX IF EXISTS idx_inbound_items_tenant_order;
-- -- 被删掉的重复索引（回滚时按 constrain 名字重建即可，不建议重建）：
-- -- CREATE INDEX idx_orders_order_no ON orders(order_no);
-- ```
--
-- ⚠️ **起效形态**：`CREATE INDEX`（非 CONCURRENTLY）会**短暂阻塞写**。
-- 本仓 `MigrationRunner` 单文件单事务执行，**不支持** CONCURRENTLY（它不能在事务块内跑）。
-- 存量生产库若这些表已很大，应由运维在停机窗口或 `psql -f` 手工执行本文件（同样幂等），
-- 详见 `docs/wiki/Database.md` 的「索引上线口径」。

-- ── 1. 订单：列表 / 状态筛选 / 客户页 / C 端「我的订单」 ─────────────────────
-- 读面：OrderService#getOrderPage（tenant + [status] + ORDER BY created_at DESC）
--       / OrderService#getMyOrderPage（user_id 或 customer_phone）
--       / OrderMapper#selectOutstandingTotal（客户欠款：tenant + customer_phone）
CREATE INDEX IF NOT EXISTS idx_orders_tenant_created
    ON orders (tenant_id, created_at DESC, id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_orders_tenant_status_created
    ON orders (tenant_id, status, created_at DESC) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_orders_tenant_phone
    ON orders (tenant_id, customer_phone) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_orders_tenant_user_created
    ON orders (tenant_id, user_id, created_at DESC) WHERE deleted = 0;

-- 完全重复：`orders.order_no` 已有 UNIQUE 约束（约束自带索引），这条索引从未被单独选中。
DROP INDEX IF EXISTS idx_orders_order_no;

-- ── 2. 通知：收件箱分页 + 未读数（前端 30s 轮询） ────────────────────────────
-- 读面：NotificationMapper#selectByRecipientId / #countUnread
-- ⚠️ 未读数用 `status <> 'read'` 作**部分索引谓词**（`!=` 在普通索引上不可用）。
CREATE INDEX IF NOT EXISTS idx_notifications_inbox
    ON notifications (tenant_id, recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications (tenant_id, recipient_id) WHERE status <> 'read';

-- ── 3. 审计日志：列表 / 登录日志 ─────────────────────────────────────────────
-- 读面：AuditLogService#getAuditLogPage（[action] + created_at 区间 + ORDER BY created_at DESC）
--       / SettingsController 登录日志（action='login'）
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created
    ON audit_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_action_created
    ON audit_logs (tenant_id, action, created_at DESC);

-- ── 4. 库存：批次消耗按 batch_id / 台账对账按 sku 汇总 ──────────────────────
-- 读面：StockBatchConsumptionMapper#sumDeltaByBatchIds（**batch_id IN (…)**
--       —— 既有索引建在 batch_no 上，与读面错位）
--       / StockLedgerMapper#sumBySku（GROUP BY sku_id，读 reason + delta）
CREATE INDEX IF NOT EXISTS idx_consumptions_tenant_batch_id
    ON stock_batch_consumptions (tenant_id, batch_id) INCLUDE (delta) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_ledger_tenant_sku_cover
    ON stock_ledger_entries (tenant_id, sku_id) INCLUDE (reason, delta) WHERE deleted = 0;

-- ── 5. 生产：工人计件按 worker_id / 期间报表按 work_date ────────────────────
-- 读面：ProductionService#workerPieceworkLedger（tenant + **worker_id** + work_date 区间；
--       既有索引第二列是 worker_name ⇒ 用不上）/ #pieceworkSummary（tenant + work_date 区间）
CREATE INDEX IF NOT EXISTS idx_work_logs_tenant_worker_id_date
    ON production_work_logs (tenant_id, worker_id, work_date) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_work_logs_tenant_date
    ON production_work_logs (tenant_id, work_date) WHERE deleted = 0;

-- ── 6. 扫码：inbound_labels 的 OR 查询用不上 COALESCE 表达式唯一索引 ────────
-- 读面：InboundLabelMapper#selectByCode（`short_code = ? OR revoked_code = ?`，跨租户）
-- ⚠️ 唯一索引建在表达式 `COALESCE(short_code, revoked_code)` 上（有效码唯一性），
--    而 OR 的两支无法推成该表达式等值 ⇒ 只能全表扫。两条单列部分索引让规划器走 BitmapOr。
CREATE INDEX IF NOT EXISTS idx_labels_short_code
    ON inbound_labels (short_code) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_labels_revoked_code
    ON inbound_labels (revoked_code) WHERE deleted = 0;

-- ── 7. 商品：列表分页 / 导入幂等键 ──────────────────────────────────────────
-- 读面：ProductService 列表（tenant + ORDER BY created_at DESC，带 OFFSET）
--       / ProductMapper 按 sku_code 等值（批量导入逐行查）
CREATE INDEX IF NOT EXISTS idx_products_tenant_created
    ON products (tenant_id, created_at DESC, id DESC) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_products_tenant_sku_code
    ON products (tenant_id, sku_code, id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_skus_tenant_sku_code
    ON product_skus (tenant_id, sku_code);

-- ── 8. CRM / 客服会话 / 质检 / 加工单 ───────────────────────────────────────
-- 读面：CustomerService 客户分页（ORDER BY created_at DESC）
--       / AgentSessionService 会话分页 / KnowledgeDistillService 已结束会话扫描
--       / QualityCheckService 质检统计（全窗口 ORDER BY inspected_at）
--       / ProcessingOrderService 加工单列表（ORDER BY created_at DESC）
CREATE INDEX IF NOT EXISTS idx_customer_profiles_tenant_created
    ON customer_profiles (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_tenant_created
    ON agent_sessions (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_ended
    ON agent_sessions (tenant_id, ended_at DESC) WHERE status = 'ended';
CREATE INDEX IF NOT EXISTS idx_quality_inspections_tenant_time
    ON quality_inspections (tenant_id, inspected_at) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_processing_orders_tenant_created
    ON processing_orders (tenant_id, created_at DESC) WHERE deleted = 0;

-- ── 9. 部位码 / 部位工序 / 发货单 ───────────────────────────────────────────
-- 读面：ProductionService 部位码撤销补齐与详情（按 processing_order_id，表上无该索引）
--       / ProductionStuckPointService（按 set_id）
--       / OrderShipmentQueryMapper 列表（ORDER BY COALESCE(shipped_at, packed_at, created_at) DESC）
CREATE INDEX IF NOT EXISTS idx_set_part_tokens_order
    ON processing_set_part_tokens (tenant_id, processing_order_id) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_position_operations_tenant_set
    ON processing_position_operations (tenant_id, set_id)
    WHERE deleted = 0 AND set_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shipments_tenant_list
    ON order_shipments (tenant_id, (COALESCE(shipped_at, packed_at, created_at)) DESC, id DESC)
    WHERE deleted = 0;

-- ── 10. 知识卡片 / 员工 / 加工项 / 会话 ────────────────────────────────────
-- 读面：KnowledgeCardService 列表（tenant + status + ORDER BY updated_at DESC）
--       / UserService 员工分页（tenant + ORDER BY created_at DESC）
--       / ProcessingItemService 列表（ORDER BY created_at DESC）
--       / SessionMapper 会话统计（tenant + updated_at）
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_tenant_status_updated
    ON knowledge_cards (tenant_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_tenant_created
    ON users (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_processing_items_tenant_created
    ON processing_items (tenant_id, created_at DESC) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_updated
    ON sessions (tenant_id, updated_at DESC) WHERE deleted = 0;

-- ── 11. 权限判定 / 入库明细聚合 ─────────────────────────────────────────────
-- 读面：PermissionMapper 权限码判定（role_permissions ⋈ permissions ON permission_id）
--       / InboundOrderQueryMapper 列表聚合子查询（按 inbound_order_id 分组）
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission
    ON role_permissions (permission_id);
CREATE INDEX IF NOT EXISTS idx_inbound_items_tenant_order
    ON inbound_order_items (tenant_id, inbound_order_id) INCLUDE (quantity, batch_no)
    WHERE deleted = 0;
