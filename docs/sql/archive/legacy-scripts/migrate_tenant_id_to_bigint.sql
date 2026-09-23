-- ============================================================
-- 迁移脚本：将 tenants.id 和所有表的 tenant_id 从 VARCHAR 改为 BIGINT
-- ============================================================

BEGIN;

-- ============================================================
-- Step 1: 删除所有 tenant_id 外键约束
-- ============================================================
ALTER TABLE after_sales_tickets DROP CONSTRAINT after_sales_tickets_tenant_id_fkey;
ALTER TABLE agent_employees DROP CONSTRAINT agent_employees_tenant_id_fkey;
ALTER TABLE audit_logs DROP CONSTRAINT audit_logs_tenant_id_fkey;
ALTER TABLE categories DROP CONSTRAINT categories_tenant_id_fkey;
ALTER TABLE customer_profiles DROP CONSTRAINT customer_profiles_tenant_id_fkey;
ALTER TABLE customer_segment_members DROP CONSTRAINT customer_segment_members_tenant_id_fkey;
ALTER TABLE customer_segments DROP CONSTRAINT customer_segments_tenant_id_fkey;
ALTER TABLE customer_tags DROP CONSTRAINT customer_tags_tenant_id_fkey;
ALTER TABLE knowledge_documents DROP CONSTRAINT knowledge_documents_tenant_id_fkey;
ALTER TABLE knowledge_sync_history DROP CONSTRAINT knowledge_sync_history_tenant_id_fkey;
ALTER TABLE notification_rules DROP CONSTRAINT notification_rules_tenant_id_fkey;
ALTER TABLE notification_templates DROP CONSTRAINT notification_templates_tenant_id_fkey;
ALTER TABLE notifications DROP CONSTRAINT notifications_tenant_id_fkey;
ALTER TABLE order_items DROP CONSTRAINT order_items_tenant_id_fkey;
ALTER TABLE order_logistics DROP CONSTRAINT order_logistics_tenant_id_fkey;
ALTER TABLE orders DROP CONSTRAINT orders_tenant_id_fkey;
ALTER TABLE permissions DROP CONSTRAINT permissions_tenant_id_fkey;
ALTER TABLE processing_categories DROP CONSTRAINT processing_categories_tenant_id_fkey;
ALTER TABLE processing_items DROP CONSTRAINT processing_items_tenant_id_fkey;
ALTER TABLE processing_rules DROP CONSTRAINT processing_rules_tenant_id_fkey;
ALTER TABLE products DROP CONSTRAINT products_tenant_id_fkey;
ALTER TABLE rag_chunks DROP CONSTRAINT rag_chunks_tenant_id_fkey;
ALTER TABLE roles DROP CONSTRAINT roles_tenant_id_fkey;
ALTER TABLE session_messages DROP CONSTRAINT session_messages_tenant_id_fkey;
ALTER TABLE sessions DROP CONSTRAINT sessions_tenant_id_fkey;
ALTER TABLE tenant_ai_configs DROP CONSTRAINT tenant_ai_configs_tenant_id_fkey;
ALTER TABLE tenant_apps DROP CONSTRAINT tenant_apps_tenant_id_fkey;
ALTER TABLE ticket_notes DROP CONSTRAINT ticket_notes_tenant_id_fkey;
ALTER TABLE ticket_timeline DROP CONSTRAINT ticket_timeline_tenant_id_fkey;
ALTER TABLE user_identities DROP CONSTRAINT user_identities_tenant_id_fkey;
ALTER TABLE user_roles DROP CONSTRAINT user_roles_tenant_id_fkey;
ALTER TABLE users DROP CONSTRAINT users_tenant_id_fkey;

-- ============================================================
-- Step 2: 删除所有 RLS 策略
-- ============================================================
DROP POLICY IF EXISTS tenant_isolation_tenants ON tenants;
DROP POLICY IF EXISTS tenant_isolation_after_sales_tickets ON after_sales_tickets;
DROP POLICY IF EXISTS tenant_isolation_agent_employees ON agent_employees;
DROP POLICY IF EXISTS tenant_isolation_audit_logs ON audit_logs;
DROP POLICY IF EXISTS tenant_isolation_categories ON categories;
DROP POLICY IF EXISTS tenant_isolation_customer_profiles ON customer_profiles;
DROP POLICY IF EXISTS tenant_isolation_customer_segment_members ON customer_segment_members;
DROP POLICY IF EXISTS tenant_isolation_customer_segments ON customer_segments;
DROP POLICY IF EXISTS tenant_isolation_customer_tags ON customer_tags;
DROP POLICY IF EXISTS tenant_isolation_knowledge_documents ON knowledge_documents;
DROP POLICY IF EXISTS tenant_isolation_knowledge_sync_history ON knowledge_sync_history;
DROP POLICY IF EXISTS tenant_isolation_notification_rules ON notification_rules;
DROP POLICY IF EXISTS tenant_isolation_notification_templates ON notification_templates;
DROP POLICY IF EXISTS tenant_isolation_notifications ON notifications;
DROP POLICY IF EXISTS tenant_isolation_order_items ON order_items;
DROP POLICY IF EXISTS tenant_isolation_order_logistics ON order_logistics;
DROP POLICY IF EXISTS tenant_isolation_orders ON orders;
DROP POLICY IF EXISTS tenant_isolation_permissions ON permissions;
DROP POLICY IF EXISTS tenant_isolation_processing_categories ON processing_categories;
DROP POLICY IF EXISTS tenant_isolation_processing_items ON processing_items;
DROP POLICY IF EXISTS tenant_isolation_processing_rules ON processing_rules;
DROP POLICY IF EXISTS tenant_isolation_products ON products;
DROP POLICY IF EXISTS tenant_isolation_rag_chunks ON rag_chunks;
DROP POLICY IF EXISTS tenant_isolation_roles ON roles;
DROP POLICY IF EXISTS tenant_isolation_session_messages ON session_messages;
DROP POLICY IF EXISTS tenant_isolation_sessions ON sessions;
DROP POLICY IF EXISTS tenant_isolation_tenant_ai_configs ON tenant_ai_configs;
DROP POLICY IF EXISTS tenant_isolation_tenant_apps ON tenant_apps;
DROP POLICY IF EXISTS tenant_isolation_ticket_notes ON ticket_notes;
DROP POLICY IF EXISTS tenant_isolation_ticket_timeline ON ticket_timeline;
DROP POLICY IF EXISTS tenant_isolation_user_identities ON user_identities;
DROP POLICY IF EXISTS tenant_isolation_user_roles ON user_roles;
DROP POLICY IF EXISTS tenant_isolation_users ON users;

-- ============================================================
-- Step 3: 更新数据 - 将字符串 tenant_id 值替换为数字
-- ============================================================
-- 先更新所有引用表的 tenant_id
UPDATE after_sales_tickets SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE agent_employees SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE audit_logs SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE categories SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE customer_profiles SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE customer_segment_members SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE customer_segments SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE customer_tags SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE knowledge_documents SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE knowledge_sync_history SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE notification_rules SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE notification_templates SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE notifications SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE order_items SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE order_logistics SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE orders SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE permissions SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE processing_categories SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE processing_items SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE processing_rules SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE products SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE rag_chunks SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE roles SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE session_messages SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE sessions SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE tenant_ai_configs SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE tenant_apps SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE ticket_notes SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE ticket_timeline SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE user_identities SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE user_roles SET tenant_id = '1' WHERE tenant_id = 'tenant_default';
UPDATE users SET tenant_id = '1' WHERE tenant_id = 'tenant_default';

-- 也处理 __TEMPLATE__ 值
UPDATE after_sales_tickets SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE agent_employees SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE audit_logs SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE categories SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE customer_profiles SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE customer_segment_members SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE customer_segments SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE customer_tags SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE knowledge_documents SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE knowledge_sync_history SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE notification_rules SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE notification_templates SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE notifications SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE order_items SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE order_logistics SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE orders SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE permissions SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE processing_categories SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE processing_items SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE processing_rules SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE products SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE rag_chunks SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE roles SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE session_messages SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE sessions SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE tenant_ai_configs SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE tenant_apps SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE ticket_notes SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE ticket_timeline SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE user_identities SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE user_roles SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';
UPDATE users SET tenant_id = '1' WHERE tenant_id = '__TEMPLATE__';

-- 更新 tenants 表的 id
UPDATE tenants SET id = '1' WHERE id = 'tenant_default';

-- ============================================================
-- Step 4: 修改列类型为 BIGINT
-- ============================================================
-- 先改 tenants.id
ALTER TABLE tenants ALTER COLUMN id TYPE BIGINT USING id::bigint;

-- 再改所有引用表的 tenant_id
ALTER TABLE after_sales_tickets ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE agent_employees ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE audit_logs ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE categories ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE customer_profiles ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE customer_segment_members ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE customer_segments ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE customer_tags ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE knowledge_documents ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE knowledge_sync_history ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE notification_rules ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE notification_templates ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE notifications ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE order_items ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE order_logistics ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE orders ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE permissions ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE processing_categories ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE processing_items ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE processing_rules ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE products ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE rag_chunks ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE roles ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE session_messages ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE sessions ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE tenant_ai_configs ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE tenant_apps ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE ticket_notes ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE ticket_timeline ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE user_identities ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE user_roles ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;
ALTER TABLE users ALTER COLUMN tenant_id TYPE BIGINT USING tenant_id::bigint;

-- ============================================================
-- Step 5: 重建外键约束
-- ============================================================
ALTER TABLE after_sales_tickets ADD CONSTRAINT after_sales_tickets_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE agent_employees ADD CONSTRAINT agent_employees_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE categories ADD CONSTRAINT categories_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE customer_profiles ADD CONSTRAINT customer_profiles_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE customer_segment_members ADD CONSTRAINT customer_segment_members_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE customer_segments ADD CONSTRAINT customer_segments_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE customer_tags ADD CONSTRAINT customer_tags_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE knowledge_documents ADD CONSTRAINT knowledge_documents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE knowledge_sync_history ADD CONSTRAINT knowledge_sync_history_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE notification_rules ADD CONSTRAINT notification_rules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE notification_templates ADD CONSTRAINT notification_templates_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE notifications ADD CONSTRAINT notifications_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE order_items ADD CONSTRAINT order_items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE order_logistics ADD CONSTRAINT order_logistics_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE orders ADD CONSTRAINT orders_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE permissions ADD CONSTRAINT permissions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE processing_categories ADD CONSTRAINT processing_categories_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE processing_items ADD CONSTRAINT processing_items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE processing_rules ADD CONSTRAINT processing_rules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE products ADD CONSTRAINT products_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE rag_chunks ADD CONSTRAINT rag_chunks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE roles ADD CONSTRAINT roles_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE session_messages ADD CONSTRAINT session_messages_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE sessions ADD CONSTRAINT sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE tenant_ai_configs ADD CONSTRAINT tenant_ai_configs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE tenant_apps ADD CONSTRAINT tenant_apps_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE ticket_notes ADD CONSTRAINT ticket_notes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE ticket_timeline ADD CONSTRAINT ticket_timeline_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE user_identities ADD CONSTRAINT user_identities_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE user_roles ADD CONSTRAINT user_roles_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE users ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);

-- ============================================================
-- Step 6: 重建 RLS 策略（使用 ::text 转换以兼容 current_setting 返回的文本）
-- ============================================================
CREATE POLICY tenant_isolation_tenants ON tenants
    USING (id::text = current_setting('app.current_tenant_id') OR current_setting('app.current_tenant_id') = '');

CREATE POLICY tenant_isolation_after_sales_tickets ON after_sales_tickets
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_agent_employees ON agent_employees
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_categories ON categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_customer_profiles ON customer_profiles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_customer_segment_members ON customer_segment_members
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_customer_segments ON customer_segments
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_customer_tags ON customer_tags
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_knowledge_documents ON knowledge_documents
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_knowledge_sync_history ON knowledge_sync_history
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_notification_rules ON notification_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_notification_templates ON notification_templates
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_notifications ON notifications
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_order_items ON order_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_order_logistics ON order_logistics
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_orders ON orders
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_permissions ON permissions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_processing_categories ON processing_categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_processing_items ON processing_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_processing_rules ON processing_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_products ON products
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_rag_chunks ON rag_chunks
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_roles ON roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_session_messages ON session_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_sessions ON sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_tenant_ai_configs ON tenant_ai_configs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_tenant_apps ON tenant_apps
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_ticket_notes ON ticket_notes
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_ticket_timeline ON ticket_timeline
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_user_identities ON user_identities
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_user_roles ON user_roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

COMMIT;
