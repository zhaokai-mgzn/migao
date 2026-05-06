-- ============================================================
-- 002_complete_tables.sql - 补充缺失的数据库表结构
-- 版本: v8.1
-- 日期: 2026-04-12
-- 说明: 补充 21 张缺失或需要扩展的表（含 CRM 客户管理）
-- 依赖: 需先执行 001_init.sql
-- ============================================================

-- ============================================================
-- P0: 核心缺失表（必须补充）
-- ============================================================

-- 1. session_messages: AI 对话消息持久化表
CREATE TABLE IF NOT EXISTS session_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    role VARCHAR(32) NOT NULL,  -- user / assistant / system / tool
    content_type VARCHAR(32) DEFAULT 'text',  -- text / image / card / order / quick_actions
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',  -- 消息元数据（推荐商品列表、订单卡片数据等）
    token_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX idx_session_messages_tenant ON session_messages(tenant_id);
CREATE INDEX idx_session_messages_role ON session_messages(role);

-- 2. tenant_ai_configs: AI 客服配置表（已有 schema 但不在迁移脚本中）
CREATE TABLE IF NOT EXISTS tenant_ai_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) UNIQUE,
    greeting_template VARCHAR(1024) DEFAULT '您好，我是 {company_name} 的 AI 客服助手，有什么可以帮您？',
    business_hours JSONB DEFAULT '{"workdays": "09:00-18:00", "weekend": "10:00-16:00"}',
    timezone VARCHAR(64) DEFAULT 'Asia/Shanghai',
    auto_handoff_keywords JSONB DEFAULT '["人工", "投诉", "退款", "找客服"]',
    emotion_handoff BOOLEAN DEFAULT true,
    ai_fallback_handoff BOOLEAN DEFAULT true,
    ai_fallback_threshold INTEGER DEFAULT 3,
    after_hours_mode VARCHAR(32) DEFAULT 'collect_message',  -- collect_message / ai_only / handoff_if_online
    after_hours_message VARCHAR(512) DEFAULT '当前非营业时间，请留言，我们会在营业时间回复您。',
    recommend_strategy VARCHAR(32) DEFAULT 'sales_based',  -- sales_based / random / category_match / none
    recommend_count INTEGER DEFAULT 3,
    recommend_trigger VARCHAR(32) DEFAULT 'on_query',  -- on_query / on_conversation_end
    quick_replies JSONB DEFAULT '[{"id": "q1", "label": "查订单", "prompt": "我想查订单"}, {"id": "q2", "label": "找产品", "prompt": "推荐产品"}, {"id": "q3", "label": "退换货", "prompt": "我要退换货"}]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_tenant_ai_configs_tenant ON tenant_ai_configs(tenant_id);

-- 3. categories: 商品分类表
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_categories_tenant ON categories(tenant_id);
CREATE INDEX idx_categories_parent ON categories(parent_id);

-- 4. processing_items: 加工项表（布艺行业核心）
CREATE TABLE IF NOT EXISTS processing_items (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    category_id VARCHAR(64) NOT NULL,  -- 关联 processing_categories
    pricing_method VARCHAR(32) NOT NULL,  -- per_meter / per_piece / fixed / per_area
    unit_price DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(16) DEFAULT '元',
    min_quantity INTEGER DEFAULT 1,
    max_quantity INTEGER DEFAULT 999,
    description TEXT,
    options JSONB DEFAULT '[]',  -- 加工选项（如打孔：纳米圈/四爪钩/韩式S钩）
    processing_days INTEGER DEFAULT 1,
    ai_recommended BOOLEAN DEFAULT true,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_processing_items_tenant ON processing_items(tenant_id);
CREATE INDEX idx_processing_items_category ON processing_items(category_id);

-- 5. processing_categories: 加工分类表
CREATE TABLE IF NOT EXISTS processing_categories (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,  -- 窗帘加工/窗帘配件/纱窗加工/卷帘加工
    sort_order INTEGER DEFAULT 0,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_processing_categories_tenant ON processing_categories(tenant_id);

-- 6. processing_rules: 加工组合规则表
CREATE TABLE IF NOT EXISTS processing_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(32) NOT NULL,  -- mutually_exclusive / required / optional / stackable
    applicable_category_id VARCHAR(64),  -- 适用的商品分类
    processing_item_ids JSONB NOT NULL,  -- 涉及的加工项 ID 列表
    description TEXT,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_processing_rules_tenant ON processing_rules(tenant_id);
CREATE INDEX idx_processing_rules_category ON processing_rules(applicable_category_id);

-- 7. tenant_apps: 租户前端应用配置表
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
    UNIQUE(tenant_id, app_type)
);

CREATE INDEX idx_tenant_apps_tenant ON tenant_apps(tenant_id);

-- 8. customer_profiles: 客户档案表（CRM 核心）
CREATE TABLE IF NOT EXISTS customer_profiles (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    
    -- 基础信息
    wechat_openid VARCHAR(128),
    wechat_unionid VARCHAR(128),
    wechat_nickname VARCHAR(128),
    phone VARCHAR(32),
    gender VARCHAR(8) DEFAULT 'unknown',  -- male / female / unknown
    region_province VARCHAR(64),
    region_city VARCHAR(64),
    region_district VARCHAR(64),
    avatar_url VARCHAR(512),
    
    -- 客户等级与状态
    vip_level VARCHAR(16) DEFAULT 'normal',  -- normal / vip1 / vip2 / vip3
    customer_status VARCHAR(32) DEFAULT 'active',  -- active / silent / churn_warning / churned
    source_channel VARCHAR(32) DEFAULT 'wechat_mini',  -- wechat_mini / h5 / web
    
    -- RFM 评分
    r_score INTEGER DEFAULT 0,  -- 1-5 分
    f_score INTEGER DEFAULT 0,
    m_score INTEGER DEFAULT 0,
    rfm_total_score INTEGER DEFAULT 0,  -- 3-15 分
    
    -- 统计数据
    total_orders INTEGER DEFAULT 0,
    total_consumption DECIMAL(12, 2) DEFAULT 0.00,
    total_refund_amount DECIMAL(12, 2) DEFAULT 0.00,
    avg_order_value DECIMAL(10, 2) DEFAULT 0.00,  -- 客单价
    repurchase_rate DECIMAL(5, 4) DEFAULT 0.0000,  -- 复购率
    
    -- 时间字段
    first_order_at TIMESTAMP WITH TIME ZONE,
    last_order_at TIMESTAMP WITH TIME ZONE,
    last_active_at TIMESTAMP WITH TIME ZONE,
    registered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 备注与标签
    agent_notes TEXT,  -- 客服备注
    tags JSONB DEFAULT '[]',  -- 客户标签 ID 列表
    custom_fields JSONB DEFAULT '{}',  -- 自定义字段
    
    -- 生命周期
    lifecycle_stage VARCHAR(32) DEFAULT 'new',  -- new / growing / mature / declining / churned
    churn_risk_score DECIMAL(5, 4) DEFAULT 0.0000,  -- 流失风险评分 0-1
    next_purchase_prediction_days INTEGER DEFAULT 30,  -- 预计下次购买天数
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_customer_profiles_tenant ON customer_profiles(tenant_id);
CREATE INDEX idx_customer_profiles_phone ON customer_profiles(phone);
CREATE INDEX idx_customer_profiles_wechat ON customer_profiles(wechat_openid);
CREATE INDEX idx_customer_profiles_status ON customer_profiles(customer_status);
CREATE INDEX idx_customer_profiles_vip ON customer_profiles(vip_level);
CREATE INDEX idx_customer_profiles_rfm ON customer_profiles(rfm_total_score DESC);
CREATE INDEX idx_customer_profiles_last_order ON customer_profiles(last_order_at);

-- ============================================================
-- P1: 扩展售后工单表 + 新增时间线表
-- ============================================================

-- 9. 扩展 after_sales_tickets 表字段
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS ticket_no VARCHAR(64) UNIQUE;
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'customer';  -- customer / agent
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'normal';  -- normal / urgent / critical
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS handler_id VARCHAR(64) REFERENCES agent_employees(id);
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS refund_amount DECIMAL(10, 2);
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS refund_method VARCHAR(32);  -- original_route / bank_transfer / balance
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS evidence_images JSONB DEFAULT '[]';
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS internal_notes TEXT;
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS deadline TIMESTAMP WITH TIME ZONE;
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS close_reason TEXT;

-- 9. ticket_timeline: 工单处理时间线表
CREATE TABLE IF NOT EXISTS ticket_timeline (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    action VARCHAR(32) NOT NULL,  -- created / assigned / processed / notified / confirmed / closed / rejected
    actor_id VARCHAR(64),
    actor_type VARCHAR(32) NOT NULL,  -- agent / system / customer
    content JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_ticket_timeline_ticket ON ticket_timeline(ticket_id, created_at);
CREATE INDEX idx_ticket_timeline_tenant ON ticket_timeline(tenant_id);

-- 10. ticket_notes: 工单备注表（支持多条内部备注）
CREATE TABLE IF NOT EXISTS ticket_notes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    author_id VARCHAR(64) NOT NULL REFERENCES agent_employees(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_ticket_notes_ticket ON ticket_notes(ticket_id, created_at);
CREATE INDEX idx_ticket_notes_tenant ON ticket_notes(tenant_id);

-- ============================================================
-- P1: 审计日志表
-- ============================================================

-- 11. audit_logs: 操作审计日志表
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL,
    user_name VARCHAR(128),
    action VARCHAR(64) NOT NULL,  -- create / update / delete / login / logout / assign / etc.
    resource_type VARCHAR(64),  -- product / order / ticket / ai_config / employee / etc.
    resource_id VARCHAR(64),
    resource_name VARCHAR(255),
    action_details JSONB DEFAULT '{}',  -- 操作详情（修改前后的值）
    ip_address VARCHAR(64),
    user_agent VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at DESC);

-- ============================================================
-- P2: 通知系统相关表
-- ============================================================

-- 12. notification_templates: 通知模板表
CREATE TABLE IF NOT EXISTS notification_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    type VARCHAR(64) NOT NULL,  -- ticket_assigned / ticket_status_changed / refund_success / shipment / etc.
    channel VARCHAR(32) NOT NULL,  -- wechat / sms / email / internal
    template_content TEXT NOT NULL,
    variables JSONB DEFAULT '[]',  -- 可用变量列表
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_notification_templates_tenant ON notification_templates(tenant_id);
CREATE INDEX idx_notification_templates_type ON notification_templates(type);

-- 13. notification_rules: 通知规则表
CREATE TABLE IF NOT EXISTS notification_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    event_type VARCHAR(64) NOT NULL,  -- ticket_assigned / ticket_status_changed / refund_success / etc.
    recipient_type VARCHAR(32) NOT NULL,  -- customer / handler / supervisor / manager
    channels JSONB NOT NULL DEFAULT '[]',  -- ["wechat", "sms"]
    enabled BOOLEAN DEFAULT true,
    template_id VARCHAR(64) REFERENCES notification_templates(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_notification_rules_tenant ON notification_rules(tenant_id);
CREATE INDEX idx_notification_rules_event ON notification_rules(event_type);

-- 14. notifications: 通知发送记录表
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    rule_id VARCHAR(64) REFERENCES notification_rules(id),
    template_id VARCHAR(64) REFERENCES notification_templates(id),
    recipient_id VARCHAR(64) NOT NULL,
    recipient_type VARCHAR(32) NOT NULL,  -- user / employee
    channel VARCHAR(32) NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',  -- pending / sent / failed / read
    sent_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_notifications_tenant ON notifications(tenant_id);
CREATE INDEX idx_notifications_recipient ON notifications(recipient_id);
CREATE INDEX idx_notifications_status ON notifications(status);
CREATE INDEX idx_notifications_created ON notifications(created_at DESC);

-- ============================================================
-- P1: 客户标签与分群表
-- ============================================================

-- 15. customer_tags: 客户标签定义表
CREATE TABLE IF NOT EXISTS customer_tags (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    color VARCHAR(16) DEFAULT '#1890ff',  -- 标签颜色
    tag_type VARCHAR(32) NOT NULL DEFAULT 'manual',  -- auto / manual
    description TEXT,
    
    -- 自动标签配置
    rule_type VARCHAR(64),  -- total_consumption / rfm_score / last_order_days / monthly_orders / repurchase_rate / custom
    rule_condition JSONB,  -- 打标条件配置
    auto_update_frequency VARCHAR(32) DEFAULT 'daily',  -- daily / weekly / realtime / manual
    
    -- 使用统计
    hit_count INTEGER DEFAULT 0,  -- 命中客户数
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

CREATE INDEX idx_customer_tags_tenant ON customer_tags(tenant_id);
CREATE INDEX idx_customer_tags_type ON customer_tags(tag_type);

-- 16. customer_segments: 客户分群规则表
CREATE TABLE IF NOT EXISTS customer_segments (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    segment_type VARCHAR(32) NOT NULL,  -- value_tier / behavior / custom
    description TEXT,
    
    -- 分群条件
    conditions JSONB NOT NULL,  -- 多条件组合
    update_frequency VARCHAR(32) DEFAULT 'daily',  -- daily / weekly / manual
    
    -- 统计
    customer_count INTEGER DEFAULT 0,
    last_calculated_at TIMESTAMP WITH TIME ZONE,
    
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_customer_segments_tenant ON customer_segments(tenant_id);
CREATE INDEX idx_customer_segments_type ON customer_segments(segment_type);

-- 17. customer_segment_members: 分群成员关联表
CREATE TABLE IF NOT EXISTS customer_segment_members (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    segment_id VARCHAR(64) NOT NULL REFERENCES customer_segments(id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customer_profiles(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(segment_id, customer_id)
);

CREATE INDEX idx_segment_members_segment ON customer_segment_members(segment_id);
CREATE INDEX idx_segment_members_customer ON customer_segment_members(customer_id);
CREATE INDEX idx_segment_members_tenant ON customer_segment_members(tenant_id);

-- ============================================================
-- P2: 知识库同步历史表
-- ============================================================

-- 16. knowledge_sync_history: 知识库批量同步历史记录
CREATE TABLE IF NOT EXISTS knowledge_sync_history (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    sync_type VARCHAR(32) NOT NULL,  -- single / batch / full
    source_type VARCHAR(32) NOT NULL,  -- product / manual
    source_ids JSONB DEFAULT '[]',
    status VARCHAR(32) DEFAULT 'pending',  -- pending / processing / completed / failed
    total_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_knowledge_sync_history_tenant ON knowledge_sync_history(tenant_id);
CREATE INDEX idx_knowledge_sync_history_status ON knowledge_sync_history(status);

-- ============================================================
-- 补充 RLS 策略（多租户隔离）
-- ============================================================

-- session_messages RLS
ALTER TABLE session_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_session_messages ON session_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- tenant_ai_configs RLS
ALTER TABLE tenant_ai_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_ai_configs ON tenant_ai_configs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- categories RLS
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_categories ON categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- processing_items RLS
ALTER TABLE processing_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_items ON processing_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- processing_categories RLS
ALTER TABLE processing_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_categories ON processing_categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- processing_rules RLS
ALTER TABLE processing_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_rules ON processing_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- tenant_apps RLS
ALTER TABLE tenant_apps ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_apps ON tenant_apps
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- customer_profiles RLS
ALTER TABLE customer_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_profiles ON customer_profiles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- ticket_timeline RLS
ALTER TABLE ticket_timeline ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ticket_timeline ON ticket_timeline
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- ticket_notes RLS
ALTER TABLE ticket_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ticket_notes ON ticket_notes
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- audit_logs RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- notification_templates RLS
ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_templates ON notification_templates
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- notification_rules RLS
ALTER TABLE notification_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_rules ON notification_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- notifications RLS
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notifications ON notifications
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- customer_tags RLS
ALTER TABLE customer_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_tags ON customer_tags
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- customer_segments RLS
ALTER TABLE customer_segments ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_segments ON customer_segments
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- customer_segment_members RLS
ALTER TABLE customer_segment_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_segment_members ON customer_segment_members
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- knowledge_sync_history RLS
ALTER TABLE knowledge_sync_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_knowledge_sync_history ON knowledge_sync_history
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- ============================================================
-- 初始化默认数据
-- ============================================================

-- 初始化默认加工分类（模板数据，部署时替换 tenant_id）
INSERT INTO processing_categories (id, tenant_id, name, sort_order) VALUES
    ('PC-CURTAIN', 1, '窗帘加工', 1),
    ('PC-ACCESSORIES', 1, '窗帘配件', 2),
    ('PC-SHEER', 1, '纱窗加工', 3),
    ('PC-ROLLER', 1, '卷帘加工', 4)
ON CONFLICT DO NOTHING;

-- 初始化默认通知模板
INSERT INTO notification_templates (id, tenant_id, name, type, channel, template_content, variables) VALUES
    ('NT-001', 1, '新工单分配通知', 'ticket_assigned', 'wechat',
     '您有一个新的售后工单 {ticket_no}，请及时处理。',
     '["ticket_no", "customer_name", "order_no"]'),
    ('NT-002', 1, '工单状态变更通知', 'ticket_status_changed', 'wechat',
     '尊敬的 {customer_name}，您的售后工单 {ticket_no} 状态已更新为 {new_status}。处理人：{handler_name}。如有疑问，请联系客服。',
     '["customer_name", "ticket_no", "new_status", "handler_name", "company_name"]'),
    ('NT-003', 1, '退款成功通知', 'refund_success', 'wechat',
     '您的退款 {amount} 元已成功，预计 1-3 个工作日到账。工单号：{ticket_no}。',
     '["amount", "ticket_no", "customer_name"]'),
    ('NT-004', 1, '发货通知', 'shipment', 'sms',
     '您的订单 {order_no} 已发货，快递公司：{logistics_company}，运单号：{tracking_no}。',
     '["order_no", "logistics_company", "tracking_no", "customer_name"]'),
    ('NT-005', 1, '工单超时预警', 'ticket_timeout', 'internal',
     '工单 {ticket_no} 已超过 24 小时未处理，请及时跟进。',
     '["ticket_no", "handler_name", "elapsed_hours"]')
ON CONFLICT DO NOTHING;

-- 初始化默认通知规则
INSERT INTO notification_rules (id, tenant_id, event_type, recipient_type, channels) VALUES
    ('NR-001', 1, 'ticket_assigned', 'handler', '["wechat", "internal"]'),
    ('NR-002', 1, 'ticket_status_changed', 'customer', '["wechat", "sms"]'),
    ('NR-003', 1, 'refund_success', 'customer', '["wechat"]'),
    ('NR-004', 1, 'shipment', 'customer', '["wechat", "sms"]'),
    ('NR-005', 1, 'ticket_timeout', 'supervisor', '["internal", "sms"]'),
    ('NR-006', 1, 'inventory_warning', 'manager', '["internal"]'),
    ('NR-007', 1, 'ai_error', 'manager', '["internal", "sms"]')
ON CONFLICT DO NOTHING;

-- 初始化默认客户标签（模板数据，部署时替换 tenant_id）
INSERT INTO customer_tags (id, tenant_id, name, color, tag_type, rule_type, rule_condition, hit_count) VALUES
    -- 自动标签
    ('TAG-VIP', 1, 'VIP 客户', '#faad14', 'auto', 'total_consumption',
     '{"operator": ">=", "value": 10000}', 0),
    ('TAG-HIGH-VALUE', 1, '高价值', '#ff4d4f', 'auto', 'rfm_score',
     '{"operator": ">=", "value": 80}', 0),
    ('TAG-ACTIVE', 1, '活跃客户', '#52c41a', 'auto', 'last_order_days',
     '{"operator": "<=", "value": 30}', 0),
    ('TAG-SILENT', 1, '沉默客户', '#faad14', 'auto', 'last_order_days',
     '{"operator": "between", "min": 30, "max": 90}', 0),
    ('TAG-CHURN-WARNING', 1, '流失预警', '#fa8c16', 'auto', 'last_order_days',
     '{"operator": "between", "min": 90, "max": 180}', 0),
    ('TAG-CHURNED', 1, '已流失', '#d9d9d9', 'auto', 'last_order_days',
     '{"operator": ">", "value": 180}', 0),
    ('TAG-REPURCHASE', 1, '复购率高', '#52c41a', 'auto', 'repurchase_rate',
     '{"operator": ">=", "value": 0.5}', 0),
    ('TAG-WHOLESALE', 1, '批发商', '#1890ff', 'auto', 'monthly_orders',
     '{"operator": ">=", "value": 10}', 0)
ON CONFLICT DO NOTHING;
