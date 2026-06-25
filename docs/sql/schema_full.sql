-- ================================================================
-- 米高智能商家管理系统 - 全量建表脚本 (PostgreSQL 14+)
-- ================================================================
-- 生成时间: 2026-05-30
-- 用途: 在全新 PostgreSQL 数据库上一次性执行，创建全部表结构、索引、
--       RLS 策略及必要种子数据
-- 执行方式: psql -U <user> -d <database> -f schema_full.sql
-- 幂等性: 所有语句使用 IF NOT EXISTS / ON CONFLICT DO NOTHING，可重复执行
-- 编码: UTF-8
-- ================================================================

-- ================================================================
-- 0. 启用必要的扩展
-- ================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ================================================================
-- 1. 租户与用户系统
-- ================================================================

-- 租户表：多租户系统核心，所有业务表通过 tenant_id 关联
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

-- 用户表：系统登录用户，包含管理员、运营、客服等角色
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    phone VARCHAR(32),
    password_hash VARCHAR(255),
    nickname VARCHAR(128),
    avatar VARCHAR(512),
    position VARCHAR(128),
    role VARCHAR(64),
    permissions TEXT,
    session_ttl INTEGER DEFAULT 3600,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 平台管理员表：超管账号，平台级，无租户归属
CREATE TABLE IF NOT EXISTS platform_admins (
    id VARCHAR(64) PRIMARY KEY,
    phone VARCHAR(32) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    nickname VARCHAR(128),
    status VARCHAR(32) DEFAULT 'active',
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE platform_admins IS '平台管理员（超管），平台级账号，无租户归属';

-- 角色表：RBAC 角色定义
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

-- 权限表：RBAC 权限定义
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

-- 用户角色关联表
CREATE TABLE IF NOT EXISTS user_roles (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    role_id VARCHAR(64) NOT NULL REFERENCES roles(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(user_id, role_id)
);

-- 用户身份表：支持多种登录方式（微信小程序、公众号、密码等）
CREATE TABLE IF NOT EXISTS user_identities (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    identity_type VARCHAR(32) NOT NULL,  -- wechat_mini / wechat_mp / password
    app_id VARCHAR(128),
    openid VARCHAR(128),
    unionid VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================================
-- 2. 商品与分类
-- ================================================================

-- 商品分类表：支持多级分类
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

-- 商品表：含库存管理、SKU 矩阵相关字段
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
    stock INTEGER DEFAULT 0,
    stock_warning_threshold INTEGER DEFAULT 10,
    status VARCHAR(32) DEFAULT 'active',
    sku_code VARCHAR(30),
    stock_deduction_mode VARCHAR(20) DEFAULT 'on_order',
    sales_count INTEGER DEFAULT 0,
    sales_amount DECIMAL(12,2) DEFAULT 0,
    edited_by VARCHAR(50),
    edited_at TIMESTAMP WITH TIME ZONE,
    has_processing BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

COMMENT ON COLUMN products.stock IS '库存数量';
COMMENT ON COLUMN products.stock_warning_threshold IS '库存预警阈值';
COMMENT ON COLUMN products.sku_code IS '商品货号';
COMMENT ON COLUMN products.stock_deduction_mode IS '库存扣减模式: on_order / on_payment';
COMMENT ON COLUMN products.sales_count IS '累计销量';
COMMENT ON COLUMN products.sales_amount IS '累计销售额';
COMMENT ON COLUMN products.has_processing IS '是否含加工项';

-- 商品颜色分类表
CREATE TABLE IF NOT EXISTS product_colors (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    color_name VARCHAR(30) NOT NULL,
    main_color_hex VARCHAR(7),
    color_image_url TEXT,
    remark VARCHAR(30),
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
COMMENT ON TABLE product_colors IS '商品颜色分类表，每商品最多200种颜色（应用层校验）';

-- 商品 SKU 矩阵表
CREATE TABLE IF NOT EXISTS product_skus (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    color_id BIGINT REFERENCES product_colors(id) ON DELETE CASCADE,
    selling_method VARCHAR(20) NOT NULL,
    door_width VARCHAR(20) NOT NULL,
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    sku_code VARCHAR(50),
    sales_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_product_skus_combination UNIQUE (product_id, color_id, selling_method, door_width)
);
COMMENT ON TABLE product_skus IS 'SKU矩阵表，颜色×售卖方式×门幅 组合';

-- 商品属性表
CREATE TABLE IF NOT EXISTS product_attributes (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    attr_key VARCHAR(30) NOT NULL,
    attr_value VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_product_attributes_key UNIQUE (product_id, attr_key)
);
COMMENT ON TABLE product_attributes IS '商品属性表';

-- ================================================================
-- 3. 加工项管理
-- ================================================================

-- 加工分类表：窗帘加工/配件/纱窗/卷帘等
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

-- 加工项表：布艺行业核心，定义各加工服务的计价方式和选项
CREATE TABLE IF NOT EXISTS processing_items (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    category_id VARCHAR(64) NOT NULL REFERENCES processing_categories(id),
    pricing_method VARCHAR(32) NOT NULL,
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

-- 加工组合规则表：定义加工项之间的互斥、必选等关系
CREATE TABLE IF NOT EXISTS processing_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(32) NOT NULL,
    applicable_category_id VARCHAR(64),
    processing_item_ids JSONB NOT NULL,
    description TEXT,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 商品-加工项关联表
CREATE TABLE IF NOT EXISTS product_processing_items (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    processing_item_id VARCHAR(64) NOT NULL REFERENCES processing_items(id) ON DELETE CASCADE,
    custom_price DECIMAL(10,2),
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_product_processing_items_relation UNIQUE (product_id, processing_item_id)
);
COMMENT ON TABLE product_processing_items IS '商品-加工项关联表，支持自定义加工价格';

-- ================================================================
-- 4. 客户管理
-- ================================================================

-- 客户档案表：CRM 核心，含 RFM 评分、生命周期管理
CREATE TABLE IF NOT EXISTS customer_profiles (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    wechat_openid VARCHAR(128),
    wechat_unionid VARCHAR(128),
    wechat_nickname VARCHAR(128),
    phone VARCHAR(32),
    gender VARCHAR(8) DEFAULT 'unknown',
    region_province VARCHAR(64),
    region_city VARCHAR(64),
    region_district VARCHAR(64),
    avatar_url VARCHAR(512),
    vip_level VARCHAR(16) DEFAULT 'normal',
    customer_status VARCHAR(32) DEFAULT 'active',
    source_channel VARCHAR(32) DEFAULT 'wechat_mini',
    r_score INTEGER DEFAULT 0,
    f_score INTEGER DEFAULT 0,
    m_score INTEGER DEFAULT 0,
    rfm_total_score INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    total_consumption DECIMAL(12, 2) DEFAULT 0.00,
    total_refund_amount DECIMAL(12, 2) DEFAULT 0.00,
    avg_order_value DECIMAL(10, 2) DEFAULT 0.00,
    repurchase_rate DECIMAL(5, 4) DEFAULT 0.0000,
    first_order_at TIMESTAMP WITH TIME ZONE,
    last_order_at TIMESTAMP WITH TIME ZONE,
    last_active_at TIMESTAMP WITH TIME ZONE,
    registered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    agent_notes TEXT,
    tags JSONB DEFAULT '[]',
    custom_fields JSONB DEFAULT '{}',
    lifecycle_stage VARCHAR(32) DEFAULT 'new',
    churn_risk_score DECIMAL(5, 4) DEFAULT 0.0000,
    next_purchase_prediction_days INTEGER DEFAULT 30,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 客户标签定义表
CREATE TABLE IF NOT EXISTS customer_tags (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    color VARCHAR(16) DEFAULT '#1890ff',
    tag_type VARCHAR(32) NOT NULL DEFAULT 'manual',
    description TEXT,
    rule_type VARCHAR(64),
    rule_condition JSONB,
    auto_update_frequency VARCHAR(32) DEFAULT 'daily',
    hit_count INTEGER DEFAULT 0,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

-- 客户分群规则表
CREATE TABLE IF NOT EXISTS customer_segments (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    segment_type VARCHAR(32) NOT NULL,
    description TEXT,
    conditions JSONB NOT NULL,
    update_frequency VARCHAR(32) DEFAULT 'daily',
    customer_count INTEGER DEFAULT 0,
    last_calculated_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 分群成员关联表
CREATE TABLE IF NOT EXISTS customer_segment_members (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    segment_id VARCHAR(64) NOT NULL REFERENCES customer_segments(id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customer_profiles(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(segment_id, customer_id)
);

-- ================================================================
-- 5. 订单系统
-- ================================================================

-- 订单表
CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_no VARCHAR(64) NOT NULL UNIQUE,
    customer_name VARCHAR(100),
    customer_phone VARCHAR(20),
    customer_address TEXT,
    total_amount DECIMAL(12,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    payment_status VARCHAR(20) DEFAULT 'unpaid',
    stock_deducted BOOLEAN DEFAULT FALSE,
    follow_status VARCHAR(20) DEFAULT 'pending',
    remark TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 订单明细表
CREATE TABLE IF NOT EXISTS order_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    product_id VARCHAR(36),
    product_name VARCHAR(200),
    quantity INTEGER DEFAULT 1,
    unit_price DECIMAL(12,2),
    width DECIMAL(8,2),
    height DECIMAL(8,2),
    processing_info JSONB,
    subtotal DECIMAL(12,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 物流跟踪记录表
CREATE TABLE IF NOT EXISTS order_logistics (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(64) NOT NULL REFERENCES orders(id),
    logistics_company VARCHAR(128) NOT NULL,
    tracking_no VARCHAR(128) NOT NULL,
    status VARCHAR(32) DEFAULT 'in_transit',
    tracking_info JSONB DEFAULT '[]',
    shipped_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================================
-- 6. AI/客服相关
-- ================================================================

-- 客服员工表
CREATE TABLE IF NOT EXISTS agent_employees (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) REFERENCES users(id),
    name VARCHAR(128) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(32),
    avatar_url VARCHAR(512),
    status VARCHAR(32) DEFAULT 'offline',
    max_concurrent_sessions INTEGER DEFAULT 5,
    skills JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- AI 客服会话表
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),
    channel VARCHAR(32) NOT NULL DEFAULT 'wechat_mini',
    status VARCHAR(32) DEFAULT 'active',
    assigned_agent_id VARCHAR(64) REFERENCES agent_employees(id),
    ai_enabled BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- AI 对话消息持久化表
CREATE TABLE IF NOT EXISTS session_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    role VARCHAR(32) NOT NULL,
    content_type VARCHAR(32) DEFAULT 'text',
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    token_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 人工客服会话表
CREATE TABLE IF NOT EXISTS agent_sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),
    employee_id VARCHAR(64) REFERENCES agent_employees(id),
    ai_session_id VARCHAR(64) REFERENCES sessions(id),
    status VARCHAR(32) DEFAULT 'waiting',
    priority INTEGER DEFAULT 0,
    reason TEXT,
    queue_position INTEGER,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 人工会话消息表
CREATE TABLE IF NOT EXISTS agent_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES agent_sessions(id),
    sender_type VARCHAR(32) NOT NULL,
    sender_id VARCHAR(64),
    content_type VARCHAR(32) DEFAULT 'text',
    content TEXT NOT NULL,
    is_internal BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 快捷回复模板表
CREATE TABLE IF NOT EXISTS quick_reply_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    category VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    content TEXT NOT NULL,
    shortcut VARCHAR(32),
    usage_count INTEGER DEFAULT 0,
    is_public BOOLEAN DEFAULT true,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================================
-- 7. 知识库
-- ================================================================

-- 知识库文档表
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

-- 知识库文档分块表
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    document_id VARCHAR(64) NOT NULL REFERENCES knowledge_documents(id),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    chunk_index INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 知识库批量同步历史记录表
CREATE TABLE IF NOT EXISTS knowledge_sync_history (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    sync_type VARCHAR(32) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_ids JSONB DEFAULT '[]',
    status VARCHAR(32) DEFAULT 'pending',
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================================
-- 8. 售后工单
-- ================================================================

-- 售后工单表
CREATE TABLE IF NOT EXISTS after_sales_tickets (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_no VARCHAR(64) UNIQUE,
    order_id VARCHAR(64),
    customer_id VARCHAR(64),
    ticket_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    source VARCHAR(32) DEFAULT 'customer',
    priority VARCHAR(16) DEFAULT 'normal',
    handler_id VARCHAR(64) REFERENCES agent_employees(id),
    assigned_at TIMESTAMP WITH TIME ZONE,
    description TEXT,
    images JSONB DEFAULT '[]',
    refund_amount DECIMAL(10, 2),
    refund_method VARCHAR(32),
    evidence_images JSONB DEFAULT '[]',
    internal_notes TEXT,
    deadline TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    close_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 工单处理时间线表
CREATE TABLE IF NOT EXISTS ticket_timeline (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    action VARCHAR(32) NOT NULL,
    actor_id VARCHAR(64),
    actor_type VARCHAR(32) NOT NULL,
    content JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 工单备注表
CREATE TABLE IF NOT EXISTS ticket_notes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    author_id VARCHAR(64) NOT NULL REFERENCES agent_employees(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================================
-- 9. 租户配置
-- ================================================================

-- 租户应用配置表
CREATE TABLE IF NOT EXISTS tenant_apps (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    app_type VARCHAR(32) NOT NULL,
    app_id VARCHAR(128) NOT NULL,
    app_secret VARCHAR(255),
    token VARCHAR(255),
    encoding_aes_key VARCHAR(255),
    msg_encrypt_mode VARCHAR(32) DEFAULT 'safe',
    server_url VARCHAR(512),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    UNIQUE(tenant_id, app_type)
);

-- 租户 AI 配置表
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

-- ================================================================
-- 10. 通知系统
-- ================================================================

-- 通知模板表
CREATE TABLE IF NOT EXISTS notification_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    type VARCHAR(64) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    template_content TEXT NOT NULL,
    variables JSONB DEFAULT '[]',
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 通知规则表
CREATE TABLE IF NOT EXISTS notification_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    event_type VARCHAR(64) NOT NULL,
    recipient_type VARCHAR(32) NOT NULL,
    channels JSONB NOT NULL DEFAULT '[]',
    enabled BOOLEAN DEFAULT true,
    template_id VARCHAR(64) REFERENCES notification_templates(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 通知发送记录表
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    rule_id VARCHAR(64) REFERENCES notification_rules(id),
    template_id VARCHAR(64) REFERENCES notification_templates(id),
    recipient_id VARCHAR(64) NOT NULL,
    recipient_type VARCHAR(32) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    sent_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================================
-- 11. 审计日志
-- ================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL,
    user_name VARCHAR(128),
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    resource_name VARCHAR(255),
    action_details JSONB DEFAULT '{}',
    ip_address VARCHAR(64),
    user_agent VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================================
-- 12. 企业入驻申请
-- ================================================================

CREATE TABLE IF NOT EXISTS tenant_applications (
    id BIGSERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    contact_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    business_license_url VARCHAR(500),
    industry VARCHAR(100),
    address TEXT,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reject_reason TEXT,
    reviewed_by VARCHAR(64) REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


-- ================================================================
-- 13. 索引
-- ================================================================

-- tenants
CREATE INDEX IF NOT EXISTS idx_tenants_code ON tenants(code);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenants_deleted ON tenants(deleted);

-- users
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted);

-- platform_admins
CREATE INDEX IF NOT EXISTS idx_platform_admins_phone ON platform_admins(phone);
CREATE INDEX IF NOT EXISTS idx_platform_admins_status ON platform_admins(status);

-- roles
CREATE INDEX IF NOT EXISTS idx_roles_tenant ON roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_roles_code ON roles(code);
CREATE INDEX IF NOT EXISTS idx_roles_status ON roles(status);
CREATE INDEX IF NOT EXISTS idx_roles_deleted ON roles(deleted);

-- permissions
CREATE INDEX IF NOT EXISTS idx_permissions_tenant ON permissions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_permissions_code ON permissions(code);
CREATE INDEX IF NOT EXISTS idx_permissions_resource ON permissions(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status);
CREATE INDEX IF NOT EXISTS idx_permissions_deleted ON permissions(deleted);

-- user_roles
CREATE INDEX IF NOT EXISTS idx_user_roles_tenant ON user_roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_deleted ON user_roles(deleted);

-- user_identities
CREATE INDEX IF NOT EXISTS idx_user_identities_tenant ON user_identities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_openid ON user_identities(openid);
CREATE INDEX IF NOT EXISTS idx_user_identities_unionid ON user_identities(unionid);
CREATE INDEX IF NOT EXISTS idx_user_identities_deleted ON user_identities(deleted);

-- categories
CREATE INDEX IF NOT EXISTS idx_categories_tenant ON categories(tenant_id);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_categories_status ON categories(status);
CREATE INDEX IF NOT EXISTS idx_categories_deleted ON categories(deleted);

-- products
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_deleted ON products(deleted);
CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock);

-- product_colors
CREATE INDEX IF NOT EXISTS idx_product_colors_tenant_product ON product_colors(tenant_id, product_id);

-- product_skus
CREATE INDEX IF NOT EXISTS idx_product_skus_tenant_product ON product_skus(tenant_id, product_id);

-- product_attributes
CREATE INDEX IF NOT EXISTS idx_product_attributes_tenant_product ON product_attributes(tenant_id, product_id);

-- product_processing_items
CREATE INDEX IF NOT EXISTS idx_product_processing_items_tenant_product ON product_processing_items(tenant_id, product_id);

-- processing_categories
CREATE INDEX IF NOT EXISTS idx_processing_categories_tenant ON processing_categories(tenant_id);
CREATE INDEX IF NOT EXISTS idx_processing_categories_status ON processing_categories(status);
CREATE INDEX IF NOT EXISTS idx_processing_categories_deleted ON processing_categories(deleted);

-- processing_items
CREATE INDEX IF NOT EXISTS idx_processing_items_tenant ON processing_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_processing_items_category ON processing_items(category_id);
CREATE INDEX IF NOT EXISTS idx_processing_items_status ON processing_items(status);
CREATE INDEX IF NOT EXISTS idx_processing_items_deleted ON processing_items(deleted);

-- processing_rules
CREATE INDEX IF NOT EXISTS idx_processing_rules_tenant ON processing_rules(tenant_id);
CREATE INDEX IF NOT EXISTS idx_processing_rules_category ON processing_rules(applicable_category_id);

-- customer_profiles
CREATE INDEX IF NOT EXISTS idx_customer_profiles_tenant ON customer_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_phone ON customer_profiles(phone);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_wechat ON customer_profiles(wechat_openid);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_status ON customer_profiles(customer_status);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_vip ON customer_profiles(vip_level);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_rfm ON customer_profiles(rfm_total_score DESC);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_last_order ON customer_profiles(last_order_at);

-- customer_tags
CREATE INDEX IF NOT EXISTS idx_customer_tags_tenant ON customer_tags(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customer_tags_type ON customer_tags(tag_type);

-- customer_segments
CREATE INDEX IF NOT EXISTS idx_customer_segments_tenant ON customer_segments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customer_segments_type ON customer_segments(segment_type);

-- customer_segment_members
CREATE INDEX IF NOT EXISTS idx_segment_members_segment ON customer_segment_members(segment_id);
CREATE INDEX IF NOT EXISTS idx_segment_members_customer ON customer_segment_members(customer_id);
CREATE INDEX IF NOT EXISTS idx_segment_members_tenant ON customer_segment_members(tenant_id);

-- orders
CREATE INDEX IF NOT EXISTS idx_orders_tenant ON orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_no ON orders(order_no);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_deleted ON orders(deleted);

-- order_items
CREATE INDEX IF NOT EXISTS idx_order_items_tenant ON order_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_order_items_deleted ON order_items(deleted);

-- order_logistics
CREATE INDEX IF NOT EXISTS idx_order_logistics_tenant ON order_logistics(tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_logistics_order ON order_logistics(order_id);
CREATE INDEX IF NOT EXISTS idx_order_logistics_tracking ON order_logistics(tracking_no);
CREATE INDEX IF NOT EXISTS idx_order_logistics_deleted ON order_logistics(deleted);

-- agent_employees
CREATE INDEX IF NOT EXISTS idx_agent_employees_tenant ON agent_employees(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_employees_user ON agent_employees(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_employees_status ON agent_employees(status);
CREATE INDEX IF NOT EXISTS idx_agent_employees_deleted ON agent_employees(deleted);

-- sessions
CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(assigned_agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted ON sessions(deleted);

-- session_messages
CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_session_messages_tenant ON session_messages(tenant_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_role ON session_messages(role);
CREATE INDEX IF NOT EXISTS idx_session_messages_deleted ON session_messages(deleted);

-- agent_sessions
CREATE INDEX IF NOT EXISTS idx_agent_sessions_tenant ON agent_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_employee ON agent_sessions(employee_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_customer ON agent_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_ai_session ON agent_sessions(ai_session_id);

-- agent_messages
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_messages_tenant ON agent_messages(tenant_id);

-- quick_reply_templates
CREATE INDEX IF NOT EXISTS idx_quick_reply_templates_tenant_category ON quick_reply_templates(tenant_id, category);
CREATE INDEX IF NOT EXISTS idx_quick_reply_templates_is_public ON quick_reply_templates(is_public);

-- knowledge_documents
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tenant ON knowledge_documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_product ON knowledge_documents(product_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status ON knowledge_documents(embedding_status);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_active ON knowledge_documents(is_active);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_deleted ON knowledge_documents(deleted);

-- rag_chunks
CREATE INDEX IF NOT EXISTS idx_rag_chunks_tenant ON rag_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document ON rag_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_deleted ON rag_chunks(deleted);

-- knowledge_sync_history
CREATE INDEX IF NOT EXISTS idx_knowledge_sync_history_tenant ON knowledge_sync_history(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_sync_history_status ON knowledge_sync_history(status);

-- after_sales_tickets
CREATE INDEX IF NOT EXISTS idx_after_sales_tickets_tenant ON after_sales_tickets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_after_sales_tickets_order ON after_sales_tickets(order_id);
CREATE INDEX IF NOT EXISTS idx_after_sales_tickets_status ON after_sales_tickets(status);
CREATE INDEX IF NOT EXISTS idx_after_sales_tickets_deleted ON after_sales_tickets(deleted);

-- ticket_timeline
CREATE INDEX IF NOT EXISTS idx_ticket_timeline_ticket ON ticket_timeline(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_timeline_tenant ON ticket_timeline(tenant_id);

-- ticket_notes
CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket ON ticket_notes(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_tenant ON ticket_notes(tenant_id);

-- tenant_apps
CREATE INDEX IF NOT EXISTS idx_tenant_apps_tenant ON tenant_apps(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_apps_status ON tenant_apps(status);
CREATE INDEX IF NOT EXISTS idx_tenant_apps_deleted ON tenant_apps(deleted);

-- tenant_ai_configs
CREATE INDEX IF NOT EXISTS idx_tenant_ai_configs_tenant ON tenant_ai_configs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_ai_configs_deleted ON tenant_ai_configs(deleted);

-- notification_templates
CREATE INDEX IF NOT EXISTS idx_notification_templates_tenant ON notification_templates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notification_templates_type ON notification_templates(type);

-- notification_rules
CREATE INDEX IF NOT EXISTS idx_notification_rules_tenant ON notification_rules(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notification_rules_event ON notification_rules(event_type);

-- notifications
CREATE INDEX IF NOT EXISTS idx_notifications_tenant ON notifications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);

-- audit_logs
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);

-- tenant_applications
CREATE INDEX IF NOT EXISTS idx_tenant_applications_phone ON tenant_applications(phone);
CREATE INDEX IF NOT EXISTS idx_tenant_applications_status ON tenant_applications(status);

-- ================================================================
-- 14. RLS 策略（多租户行级安全隔离）
-- ================================================================

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_tenants') THEN
    CREATE POLICY tenant_isolation_tenants ON tenants
      USING (id::text = current_setting('app.current_tenant_id', true) OR current_setting('app.current_tenant_id', true) = '');
  END IF;
END $$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_users') THEN CREATE POLICY tenant_isolation_users ON users USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_roles') THEN CREATE POLICY tenant_isolation_roles ON roles USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE permissions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_permissions') THEN CREATE POLICY tenant_isolation_permissions ON permissions USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_user_roles') THEN CREATE POLICY tenant_isolation_user_roles ON user_roles USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_user_identities') THEN CREATE POLICY tenant_isolation_user_identities ON user_identities USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_categories') THEN CREATE POLICY tenant_isolation_categories ON categories USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE products ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_products') THEN CREATE POLICY tenant_isolation_products ON products USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE product_colors ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_product_colors') THEN CREATE POLICY tenant_isolation_product_colors ON product_colors USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE product_skus ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_product_skus') THEN CREATE POLICY tenant_isolation_product_skus ON product_skus USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE product_attributes ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_product_attributes') THEN CREATE POLICY tenant_isolation_product_attributes ON product_attributes USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE product_processing_items ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_product_processing_items') THEN CREATE POLICY tenant_isolation_product_processing_items ON product_processing_items USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE processing_categories ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_processing_categories') THEN CREATE POLICY tenant_isolation_processing_categories ON processing_categories USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE processing_items ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_processing_items') THEN CREATE POLICY tenant_isolation_processing_items ON processing_items USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE processing_rules ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_processing_rules') THEN CREATE POLICY tenant_isolation_processing_rules ON processing_rules USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE customer_profiles ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_profiles') THEN CREATE POLICY tenant_isolation_customer_profiles ON customer_profiles USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE customer_tags ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_tags') THEN CREATE POLICY tenant_isolation_customer_tags ON customer_tags USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE customer_segments ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_segments') THEN CREATE POLICY tenant_isolation_customer_segments ON customer_segments USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE customer_segment_members ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customer_segment_members') THEN CREATE POLICY tenant_isolation_customer_segment_members ON customer_segment_members USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_orders') THEN CREATE POLICY tenant_isolation_orders ON orders USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_order_items') THEN CREATE POLICY tenant_isolation_order_items ON order_items USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE order_logistics ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_order_logistics') THEN CREATE POLICY tenant_isolation_order_logistics ON order_logistics USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE agent_employees ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_agent_employees') THEN CREATE POLICY tenant_isolation_agent_employees ON agent_employees USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_sessions') THEN CREATE POLICY tenant_isolation_sessions ON sessions USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE session_messages ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_session_messages') THEN CREATE POLICY tenant_isolation_session_messages ON session_messages USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_agent_sessions') THEN CREATE POLICY tenant_isolation_agent_sessions ON agent_sessions USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_agent_messages') THEN CREATE POLICY tenant_isolation_agent_messages ON agent_messages USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE quick_reply_templates ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_quick_reply_templates') THEN CREATE POLICY tenant_isolation_quick_reply_templates ON quick_reply_templates USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_knowledge_documents') THEN CREATE POLICY tenant_isolation_knowledge_documents ON knowledge_documents USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_rag_chunks') THEN CREATE POLICY tenant_isolation_rag_chunks ON rag_chunks USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE knowledge_sync_history ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_knowledge_sync_history') THEN CREATE POLICY tenant_isolation_knowledge_sync_history ON knowledge_sync_history USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE after_sales_tickets ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_after_sales_tickets') THEN CREATE POLICY tenant_isolation_after_sales_tickets ON after_sales_tickets USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE ticket_timeline ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_ticket_timeline') THEN CREATE POLICY tenant_isolation_ticket_timeline ON ticket_timeline USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE ticket_notes ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_ticket_notes') THEN CREATE POLICY tenant_isolation_ticket_notes ON ticket_notes USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE tenant_apps ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_tenant_apps') THEN CREATE POLICY tenant_isolation_tenant_apps ON tenant_apps USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE tenant_ai_configs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_tenant_ai_configs') THEN CREATE POLICY tenant_isolation_tenant_ai_configs ON tenant_ai_configs USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_notification_templates') THEN CREATE POLICY tenant_isolation_notification_templates ON notification_templates USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE notification_rules ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_notification_rules') THEN CREATE POLICY tenant_isolation_notification_rules ON notification_rules USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_notifications') THEN CREATE POLICY tenant_isolation_notifications ON notifications USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_audit_logs') THEN CREATE POLICY tenant_isolation_audit_logs ON audit_logs USING (tenant_id::text = current_setting('app.current_tenant_id', true)); END IF; END $$;

-- ================================================================
-- 15. 种子数据（默认租户、角色）
-- ================================================================

-- 默认租户（id=1）
INSERT INTO tenants (id, name, code, industry, status)
  OVERRIDING SYSTEM VALUE
  VALUES (1, '米高智能', 'migao', '布艺窗帘', 'active')
  ON CONFLICT (id) DO NOTHING;

-- 默认角色
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
  ('role_admin', 1, '管理员', 'admin', '租户管理权限', 'active'),
  ('role_operator', 1, '运营', 'operator', '商品与订单运营', 'active'),
  ('role_customer_service', 1, '客服', 'customer_service', '客服工作台权限', 'active'),
  ('role_super_admin', 1, '超级管理员', 'super_admin', '平台级超管权限', 'active')
  ON CONFLICT DO NOTHING;

-- 默认平台管理员（密码: admin123，BCrypt 加密）
-- 实际使用时请修改密码或通过 SMS 登录
INSERT INTO platform_admins (id, phone, password_hash, nickname, status) VALUES
  ('platform-admin-001', '13800000000', '$2a$10$N/A_REPLACE_WITH_REAL_BCRYPT', '超级管理员', 'active')
ON CONFLICT (id) DO NOTHING;

-- ================================================================
-- END OF SCHEMA
-- ================================================================
