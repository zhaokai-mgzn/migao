-- ============================================================
-- 001_init.sql - 数据库初始化脚本
-- 版本: v1.0
-- 日期: 2026-04-18
-- 说明: 创建基础表结构（18个核心实体表）
-- 注意: 此脚本需在 002_complete_tables.sql 之前执行
-- ============================================================

-- ============================================================
-- 1. 租户表 (tenants) - 多租户系统的核心
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) UNIQUE NOT NULL,
    industry VARCHAR(64),
    status VARCHAR(32) DEFAULT 'active',
    auth_config JSONB DEFAULT '{}',
    bailian_config JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_tenants_code ON tenants(code);
CREATE INDEX idx_tenants_status ON tenants(status);
CREATE INDEX idx_tenants_deleted ON tenants(deleted);

-- ============================================================
-- 2. 用户表 (users)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    phone VARCHAR(32),
    password_hash VARCHAR(255),
    nickname VARCHAR(128),
    avatar VARCHAR(512),
    role VARCHAR(64),
    session_ttl INTEGER DEFAULT 3600,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_phone ON users(phone);
CREATE INDEX idx_users_status ON users(status);
CREATE INDEX idx_users_deleted ON users(deleted);

-- ============================================================
-- 3. 角色表 (roles)
-- ============================================================
CREATE TABLE IF NOT EXISTS roles (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) NOT NULL,
    description TEXT,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(tenant_id, code)
);

CREATE INDEX idx_roles_tenant ON roles(tenant_id);
CREATE INDEX idx_roles_code ON roles(code);
CREATE INDEX idx_roles_status ON roles(status);
CREATE INDEX idx_roles_deleted ON roles(deleted);

-- ============================================================
-- 4. 权限表 (permissions)
-- ============================================================
CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    action VARCHAR(64),
    description TEXT,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(tenant_id, code)
);

CREATE INDEX idx_permissions_tenant ON permissions(tenant_id);
CREATE INDEX idx_permissions_code ON permissions(code);
CREATE INDEX idx_permissions_resource ON permissions(resource_type, resource_id);
CREATE INDEX idx_permissions_status ON permissions(status);
CREATE INDEX idx_permissions_deleted ON permissions(deleted);

-- ============================================================
-- 5. 用户角色关联表 (user_roles)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_roles (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    role_id VARCHAR(64) NOT NULL REFERENCES roles(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(user_id, role_id)
);

CREATE INDEX idx_user_roles_tenant ON user_roles(tenant_id);
CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);
CREATE INDEX idx_user_roles_deleted ON user_roles(deleted);

-- ============================================================
-- 6. 用户身份表 (user_identities)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_identities (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    identity_type VARCHAR(32) NOT NULL,  -- wechat_mini / wechat_mp / password
    app_id VARCHAR(128),
    openid VARCHAR(128),
    unionid VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_user_identities_tenant ON user_identities(tenant_id);
CREATE INDEX idx_user_identities_user ON user_identities(user_id);
CREATE INDEX idx_user_identities_openid ON user_identities(openid);
CREATE INDEX idx_user_identities_unionid ON user_identities(unionid);
CREATE INDEX idx_user_identities_deleted ON user_identities(deleted);

-- ============================================================
-- 7. 商品分类表 (categories)
-- 注意: 002_complete_tables.sql 中也有此表定义，但这里先创建基础版本
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    parent_id VARCHAR(64) REFERENCES categories(id),
    level INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    icon VARCHAR(512),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_categories_tenant ON categories(tenant_id);
CREATE INDEX idx_categories_parent ON categories(parent_id);
CREATE INDEX idx_categories_status ON categories(status);
CREATE INDEX idx_categories_deleted ON categories(deleted);

-- ============================================================
-- 8. 商品表 (products)
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    category_id VARCHAR(64) REFERENCES categories(id),
    base_price DECIMAL(10, 2) DEFAULT 0.00,
    description TEXT,
    main_image VARCHAR(512),
    images JSONB DEFAULT '[]',
    knowledge_base_id VARCHAR(64),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_products_tenant ON products(tenant_id);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_deleted ON products(deleted);

-- ============================================================
-- 9. 加工分类表 (processing_categories)
-- ============================================================
CREATE TABLE IF NOT EXISTS processing_categories (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    sort_order INTEGER DEFAULT 0,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_processing_categories_tenant ON processing_categories(tenant_id);
CREATE INDEX idx_processing_categories_status ON processing_categories(status);
CREATE INDEX idx_processing_categories_deleted ON processing_categories(deleted);

-- ============================================================
-- 10. 加工项表 (processing_items)
-- ============================================================
CREATE TABLE IF NOT EXISTS processing_items (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    category_id VARCHAR(64) NOT NULL REFERENCES processing_categories(id),
    pricing_method VARCHAR(32) NOT NULL,  -- per_meter / per_piece / fixed / per_area
    unit_price DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(16) DEFAULT '元',
    min_quantity INTEGER DEFAULT 1,
    max_quantity INTEGER DEFAULT 999,
    description TEXT,
    options JSONB DEFAULT '[]',
    processing_days INTEGER DEFAULT 1,
    ai_recommended BOOLEAN DEFAULT true,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_processing_items_tenant ON processing_items(tenant_id);
CREATE INDEX idx_processing_items_category ON processing_items(category_id);
CREATE INDEX idx_processing_items_status ON processing_items(status);
CREATE INDEX idx_processing_items_deleted ON processing_items(deleted);

-- ============================================================
-- 11. 知识库文档表 (knowledge_documents)
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    title VARCHAR(255) NOT NULL,
    doc_type VARCHAR(64),
    category VARCHAR(128),
    file_type VARCHAR(32),
    file_url VARCHAR(512),
    content TEXT,
    product_id VARCHAR(64) REFERENCES products(id),
    embedding_status VARCHAR(32) DEFAULT 'pending',
    chunk_count INTEGER DEFAULT 0,
    dashvector_collection VARCHAR(128),
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_knowledge_documents_tenant ON knowledge_documents(tenant_id);
CREATE INDEX idx_knowledge_documents_product ON knowledge_documents(product_id);
CREATE INDEX idx_knowledge_documents_status ON knowledge_documents(embedding_status);
CREATE INDEX idx_knowledge_documents_active ON knowledge_documents(is_active);
CREATE INDEX idx_knowledge_documents_deleted ON knowledge_documents(deleted);

-- ============================================================
-- 12. 知识库文档分块表 (rag_chunks)
-- ============================================================
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    document_id VARCHAR(64) NOT NULL REFERENCES knowledge_documents(id),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    chunk_index INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_rag_chunks_tenant ON rag_chunks(tenant_id);
CREATE INDEX idx_rag_chunks_document ON rag_chunks(document_id);
CREATE INDEX idx_rag_chunks_deleted ON rag_chunks(deleted);

-- ============================================================
-- 13. 租户应用配置表 (tenant_apps)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_apps (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    app_type VARCHAR(32) NOT NULL,  -- wechat_mini / wechat_h5 / web
    app_id VARCHAR(128) NOT NULL,
    app_secret VARCHAR(255),
    token VARCHAR(255),
    encoding_aes_key VARCHAR(255),
    msg_encrypt_mode VARCHAR(32) DEFAULT 'safe',  -- plaintext / compatible / safe
    server_url VARCHAR(512),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(tenant_id, app_type)
);

CREATE INDEX idx_tenant_apps_tenant ON tenant_apps(tenant_id);
CREATE INDEX idx_tenant_apps_status ON tenant_apps(status);
CREATE INDEX idx_tenant_apps_deleted ON tenant_apps(deleted);

-- ============================================================
-- 14. 客服员工表 (agent_employees)
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_employees (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) REFERENCES users(id),
    name VARCHAR(128) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(32),
    avatar_url VARCHAR(512),
    status VARCHAR(32) DEFAULT 'offline',  -- online / offline / busy
    max_concurrent_sessions INTEGER DEFAULT 5,
    skills JSONB DEFAULT '[]',  -- 技能标签
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_agent_employees_tenant ON agent_employees(tenant_id);
CREATE INDEX idx_agent_employees_user ON agent_employees(user_id);
CREATE INDEX idx_agent_employees_status ON agent_employees(status);
CREATE INDEX idx_agent_employees_deleted ON agent_employees(deleted);

-- ============================================================
-- 15. 会话表 (sessions)
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),  -- 关联客户（customer_profiles 在 002 中创建，此处不加 FK）
    channel VARCHAR(32) NOT NULL DEFAULT 'wechat_mini',  -- wechat_mini / wechat_h5 / web
    status VARCHAR(32) DEFAULT 'active',  -- active / closed / waiting
    assigned_agent_id VARCHAR(64) REFERENCES agent_employees(id),
    ai_enabled BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_sessions_tenant ON sessions(tenant_id);
CREATE INDEX idx_sessions_customer ON sessions(customer_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_agent ON sessions(assigned_agent_id);
CREATE INDEX idx_sessions_deleted ON sessions(deleted);

-- ============================================================
-- 16. 会话消息表 (session_messages)
-- 注意: 002_complete_tables.sql 中也有此表定义，这里创建基础版本
-- ============================================================
CREATE TABLE IF NOT EXISTS session_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    role VARCHAR(32) NOT NULL,  -- user / assistant / system / tool
    content_type VARCHAR(32) DEFAULT 'text',
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    token_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX idx_session_messages_tenant ON session_messages(tenant_id);
CREATE INDEX idx_session_messages_role ON session_messages(role);
CREATE INDEX idx_session_messages_deleted ON session_messages(deleted);

-- ============================================================
-- 17. 售后工单表 (after_sales_tickets) - 基础版本
-- 注意: 002_complete_tables.sql 中会扩展此表字段
-- ============================================================
CREATE TABLE IF NOT EXISTS after_sales_tickets (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(64),  -- 关联订单（orders 在 003 中创建，此处不加 FK）
    customer_id VARCHAR(64),  -- 关联客户
    ticket_type VARCHAR(32) NOT NULL,  -- return / exchange / repair / complaint
    status VARCHAR(32) DEFAULT 'pending',  -- pending / processing / resolved / rejected / closed
    description TEXT,
    images JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_after_sales_tickets_tenant ON after_sales_tickets(tenant_id);
CREATE INDEX idx_after_sales_tickets_order ON after_sales_tickets(order_id);
CREATE INDEX idx_after_sales_tickets_status ON after_sales_tickets(status);
CREATE INDEX idx_after_sales_tickets_deleted ON after_sales_tickets(deleted);

-- ============================================================
-- 18. 租户AI配置表 (tenant_ai_configs)
-- 注意: 002_complete_tables.sql 中也有此表定义，这里创建基础版本
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_ai_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) UNIQUE,
    greeting_template VARCHAR(1024) DEFAULT '您好，我是 AI 客服助手，有什么可以帮您？',
    business_hours JSONB DEFAULT '{"workdays": "09:00-18:00", "weekend": "10:00-16:00"}',
    timezone VARCHAR(64) DEFAULT 'Asia/Shanghai',
    auto_handoff_keywords JSONB DEFAULT '["人工", "投诉", "退款", "找客服"]',
    emotion_handoff BOOLEAN DEFAULT true,
    ai_fallback_handoff BOOLEAN DEFAULT true,
    ai_fallback_threshold INTEGER DEFAULT 3,
    after_hours_mode VARCHAR(32) DEFAULT 'collect_message',
    after_hours_message VARCHAR(512) DEFAULT '当前非营业时间，请留言，我们会在营业时间回复您。',
    recommend_strategy VARCHAR(32) DEFAULT 'sales_based',
    recommend_count INTEGER DEFAULT 3,
    recommend_trigger VARCHAR(32) DEFAULT 'on_query',
    quick_replies JSONB DEFAULT '[{"id": "q1", "label": "查订单", "prompt": "我想查订单"}]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_tenant_ai_configs_tenant ON tenant_ai_configs(tenant_id);
CREATE INDEX idx_tenant_ai_configs_deleted ON tenant_ai_configs(deleted);

-- ============================================================
-- RLS 策略（多租户隔离）
-- ============================================================

-- tenants RLS (租户表通常不需要 RLS，因为租户 ID 本身就是隔离键)
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenants ON tenants
    USING (id::text = current_setting('app.current_tenant_id') OR current_setting('app.current_tenant_id') = '');

-- users RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- roles RLS
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_roles ON roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- permissions RLS
ALTER TABLE permissions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_permissions ON permissions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- user_roles RLS
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_user_roles ON user_roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- user_identities RLS
ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_user_identities ON user_identities
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- categories RLS
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_categories ON categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- products RLS
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_products ON products
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- processing_categories RLS
ALTER TABLE processing_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_categories ON processing_categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- processing_items RLS
ALTER TABLE processing_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_items ON processing_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- knowledge_documents RLS
ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_knowledge_documents ON knowledge_documents
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- rag_chunks RLS
ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_rag_chunks ON rag_chunks
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- tenant_apps RLS
ALTER TABLE tenant_apps ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_apps ON tenant_apps
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- agent_employees RLS
ALTER TABLE agent_employees ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_employees ON agent_employees
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- sessions RLS
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sessions ON sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- session_messages RLS
ALTER TABLE session_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_session_messages ON session_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- after_sales_tickets RLS
ALTER TABLE after_sales_tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_after_sales_tickets ON after_sales_tickets
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- tenant_ai_configs RLS
ALTER TABLE tenant_ai_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_ai_configs ON tenant_ai_configs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- ============================================================
-- 初始化默认数据
-- ============================================================

-- 创建默认租户
INSERT INTO tenants (id, name, code, industry, status) OVERRIDING SYSTEM VALUE VALUES
    (1, '默认租户', 'default', 'other', 'active')
ON CONFLICT (code) DO NOTHING;

-- 创建默认角色
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
    ('role_admin', 1, '管理员', 'admin', '系统管理员，拥有所有权限', 'active'),
    ('role_operator', 1, '运营人员', 'operator', '日常运营人员', 'active'),
    ('role_customer_service', 1, '客服人员', 'customer_service', '客服人员', 'active')
ON CONFLICT DO NOTHING;

-- 创建默认权限
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status) VALUES
    ('perm_user_read', 1, '用户查看', 'user:read', 'user', 'read', '查看用户信息', 'active'),
    ('perm_user_write', 1, '用户管理', 'user:write', 'user', 'write', '创建/修改/删除用户', 'active'),
    ('perm_product_read', 1, '商品查看', 'product:read', 'product', 'read', '查看商品信息', 'active'),
    ('perm_product_write', 1, '商品管理', 'product:write', 'product', 'write', '创建/修改/删除商品', 'active'),
    ('perm_order_read', 1, '订单查看', 'order:read', 'order', 'read', '查看订单信息', 'active'),
    ('perm_order_write', 1, '订单管理', 'order:write', 'order', 'write', '管理订单', 'active'),
    ('perm_knowledge_read', 1, '知识库查看', 'knowledge:read', 'knowledge', 'read', '查看知识库', 'active'),
    ('perm_knowledge_write', 1, '知识库管理', 'knowledge:write', 'knowledge', 'write', '管理知识库', 'active'),
    ('perm_ai_config_read', 1, 'AI配置查看', 'ai_config:read', 'ai_config', 'read', '查看AI配置', 'active'),
    ('perm_ai_config_write', 1, 'AI配置管理', 'ai_config:write', 'ai_config', 'write', '管理AI配置', 'active')
ON CONFLICT DO NOTHING;
