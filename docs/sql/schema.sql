-- ================================================
-- AI 客服系统 - 完整建库脚本 (PostgreSQL)
-- ================================================
-- 本文件由迁移脚本 001_init ~ 007_agent_workspace 合并生成
-- 适用于在空数据库上一次性执行，创建全部表结构、索引和 RLS 策略
-- 不包含任何 DML（INSERT/UPDATE/DELETE）数据操作
-- 数据库: PostgreSQL 14+
-- 编码: UTF-8
-- ================================================

-- ================================================
-- 0. 启用必要的扩展
-- ================================================
CREATE EXTENSION "uuid-ossp";

-- ================================================
-- 1. 基础表
-- ================================================

-- 租户表：多租户系统核心，所有业务表通过 tenant_id 关联
CREATE TABLE tenants (
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
CREATE TABLE users (
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

-- 角色表：RBAC 角色定义
CREATE TABLE roles (
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
CREATE TABLE permissions (
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
CREATE TABLE user_roles (
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
CREATE TABLE user_identities (
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

-- ================================================
-- 2. 商品与加工相关表
-- ================================================

-- 商品分类表：支持多级分类
CREATE TABLE categories (
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
CREATE TABLE products (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    category_id VARCHAR(64) REFERENCES categories(id),
    base_price DECIMAL(10, 2) DEFAULT 0.00,
    description TEXT,
    main_image VARCHAR(512),
    images JSONB DEFAULT '[]',
    detail_images JSONB DEFAULT '[]',
    knowledge_base_id VARCHAR(64),
    stock INTEGER DEFAULT 0,
    stock_warning_threshold INTEGER DEFAULT 10,
    status VARCHAR(32) DEFAULT 'active',
    -- 计价单位（来自 011_product_unit.sql）
    unit VARCHAR(32) DEFAULT '件',
    -- 计价方式：per_meter / per_piece / fixed / per_area
    pricing_type VARCHAR(30) DEFAULT 'per_meter',
    -- SKU 矩阵相关字段（来自 008_product_sku_matrix.sql）
    sku_code VARCHAR(30),
    stock_deduction_mode VARCHAR(20) DEFAULT 'on_order',  -- on_order(拍下减) / on_payment(付款减)
    sales_count INTEGER DEFAULT 0,                         -- 累计销量
    sales_amount DECIMAL(12,2) DEFAULT 0,                  -- 累计销售额
    edited_by VARCHAR(50),                                  -- 最后编辑人
    edited_at TIMESTAMP WITH TIME ZONE,                     -- 最后编辑时间
    -- 加工项关联（来自 009_processing_item_price.sql）
    has_processing BOOLEAN DEFAULT FALSE,                   -- 是否含加工项
    -- 商家推荐标记（来自 V20260903__add_product_recommended.sql）
    recommended BOOLEAN DEFAULT FALSE,                       -- 是否商家推荐（C 端新品推荐位展示依据）
    -- 退货回补库存开关（来自 V33__add_allow_return_restock.sql）
    allow_return_restock BOOLEAN DEFAULT FALSE,              -- 是否允许退货回补库存（窗帘行业定制退货不可再售，默认不回补）
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
COMMENT ON COLUMN products.allow_return_restock IS '是否允许退货回补库存（窗帘行业定制退货不可再售，默认不回补）';
COMMENT ON COLUMN products.detail_images IS '商品详情图URL列表（JSONB数组）';

-- ================================================
-- 商品 SKU 矩阵相关表 (来自 008_product_sku_matrix.sql)
-- 注意：product_id 类型为 VARCHAR(64)，与 products.id 保持一致
-- ================================================

-- 商品颜色分类表
CREATE TABLE product_colors (
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
CREATE INDEX idx_product_colors_tenant_product ON product_colors(tenant_id, product_id);
COMMENT ON TABLE product_colors IS '商品颜色分类表，每商品最多200种颜色（应用层校验）';

-- 商品 SKU 矩阵表
CREATE TABLE product_skus (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    color_id BIGINT REFERENCES product_colors(id) ON DELETE CASCADE,
    selling_method VARCHAR(20) NOT NULL,                  -- bulk_cut(散剪) / full_roll(整卷)
    door_width VARCHAR(20) NOT NULL,                      -- 规格尺寸: 2.8m / 3.2m / 3.4m
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    sku_code VARCHAR(50),
    sales_count INTEGER NOT NULL DEFAULT 0,                -- SKU 累计销量（来自 011）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_product_skus_tenant_product ON product_skus(tenant_id, product_id);
ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination
    UNIQUE (product_id, color_id, selling_method, door_width);
COMMENT ON TABLE product_skus IS 'SKU矩阵表，颜色×售卖方式×门幅 组合';

-- 商品属性表
CREATE TABLE product_attributes (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    attr_key VARCHAR(30) NOT NULL,                        -- brand/material/weight/function/style/craft/pattern
    attr_value VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_product_attributes_tenant_product ON product_attributes(tenant_id, product_id);
ALTER TABLE product_attributes ADD CONSTRAINT uq_product_attributes_key
    UNIQUE (product_id, attr_key);
COMMENT ON TABLE product_attributes IS '商品属性表';


-- 加工分类表：窗帘加工/配件/纱窗/卷帘等
CREATE TABLE processing_categories (
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
CREATE TABLE processing_items (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    category_id VARCHAR(64) NOT NULL REFERENCES processing_categories(id),
    pricing_method VARCHAR(32) NOT NULL,  -- per_meter / per_set / fixed / per_area（issue #3005 回滚：无 per_piece）
    unit_price DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(16) DEFAULT '元',
    min_quantity INTEGER DEFAULT 1,
    max_quantity INTEGER DEFAULT 999,
    description TEXT,
    options JSONB DEFAULT '[]',  -- 加工选项（如打孔：纳米圈/四爪钩/韩式S钩）
    applicable_product_categories JSONB DEFAULT '[]',  -- 适用商品分类ID列表
    processing_days INTEGER DEFAULT 1,
    ai_recommended BOOLEAN DEFAULT true,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 商品-加工项关联表
CREATE TABLE product_processing_items (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    processing_item_id VARCHAR(64) NOT NULL REFERENCES processing_items(id) ON DELETE CASCADE,
    custom_price DECIMAL(10,2),                           -- 商品专属加工价格（NULL 则用默认价）
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_product_processing_items_tenant_product ON product_processing_items(tenant_id, product_id);
ALTER TABLE product_processing_items ADD CONSTRAINT uq_product_processing_items_relation
    UNIQUE (product_id, processing_item_id);
COMMENT ON TABLE product_processing_items IS '商品-加工项关联表，支持自定义加工价格（issue #3005 回滚：无每米数量密度覆盖）';

-- 加工组合规则表：定义加工项之间的互斥、必选等关系
CREATE TABLE processing_rules (
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

-- ================================================
-- 3. 知识库相关表
-- ================================================

-- 知识卡片表（LLM WIKI 板块，issue #3051，V35 建表 + V37 重命名）
-- 知识单元从 RAG chunk 升级为结构化知识卡片：AI 客服直接读词条回答，检索用结构化过滤 + 关键词，不引入向量库。
CREATE TABLE IF NOT EXISTS knowledge_cards (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(64),
    industry VARCHAR(64) DEFAULT 'curtain',
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(128),
    question TEXT,
    answer TEXT NOT NULL,
    keywords TEXT,
    apply_products JSONB DEFAULT '[]',
    variables JSONB DEFAULT '{}',
    status VARCHAR(32) DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    review_note TEXT,
    created_by VARCHAR(64),
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_knowledge_cards_tenant ON knowledge_cards(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_status ON knowledge_cards(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_category ON knowledge_cards(category);

-- 知识提炼候选表（LLM WIKI 板块，issue #3051，V35 迁移）
-- AI 提炼（会话/文档/商品）→ 商家待采纳队列；AI 只产生候选，发布权在商家。
CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(128),
    suggested_title VARCHAR(255) NOT NULL,
    suggested_answer TEXT NOT NULL,
    suggested_category VARCHAR(64),
    suggested_keywords TEXT,
    confidence NUMERIC(4,3),
    evidence TEXT,
    status VARCHAR(32) DEFAULT 'pending',
    status_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_tenant ON knowledge_candidates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_status ON knowledge_candidates(status);

-- ================================================
-- 4. 租户配置相关表
-- ================================================

-- 租户应用配置表：微信小程序/H5/Web 等应用接入配置
CREATE TABLE tenant_apps (
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

-- 租户 AI 配置表：AI 客服行为、推荐策略等（#3081 快捷回复已下线）
CREATE TABLE tenant_ai_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) UNIQUE,
    greeting_template VARCHAR(1024) DEFAULT '您好，我是 AI 客服助手，有什么可以帮您？',
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
    quick_replies JSONB DEFAULT '[{"id": "q1", "label": "查订单", "prompt": "我想查订单"}]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================
-- 5. 客服员工与会话相关表
-- ================================================

-- 客服员工表：企业内部客服人员信息
CREATE TABLE agent_employees (
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

-- AI 客服会话表：C端消费者与 AI 客服的对话会话
CREATE TABLE sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),
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

-- AI 对话消息持久化表
CREATE TABLE session_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    role VARCHAR(32) NOT NULL,  -- user / assistant / system / tool
    content_type VARCHAR(32) DEFAULT 'text',  -- text / image / card / order / quick_actions
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',  -- 消息元数据（推荐商品列表、订单卡片数据等）
    token_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================
-- 6. 客服工作台相关表（人工客服）
-- ================================================

-- 人工客服会话表：AI 转人工后的服务会话，含排队、分配、服务全流程
CREATE TABLE agent_sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),  -- 客户ID
    employee_id VARCHAR(64) REFERENCES agent_employees(id),  -- 分配的客服员工
    ai_session_id VARCHAR(64) REFERENCES sessions(id),  -- 关联原始 AI 会话
    status VARCHAR(32) DEFAULT 'waiting',  -- waiting / active / ended / transferred
    priority INTEGER DEFAULT 0,  -- 优先级
    reason TEXT,  -- 转人工原因
    ai_context_summary TEXT,  -- 转人工时点 AI 会话上下文摘要（客服可见；GB/T 47746-2026，V26）
    ai_context_messages JSONB NOT NULL DEFAULT '[]',  -- 转人工时点 AI 会话最近 N 轮消息快照（V26）
    queue_position INTEGER,  -- 排队位置
    started_at TIMESTAMP WITH TIME ZONE,  -- 开始服务时间
    ended_at TIMESTAMP WITH TIME ZONE,  -- 结束时间
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 人工会话消息表：人工客服会话中的消息记录
CREATE TABLE agent_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES agent_sessions(id),  -- 关联会话
    sender_type VARCHAR(32) NOT NULL,  -- customer / agent / system
    sender_id VARCHAR(64),  -- 发送者ID
    content_type VARCHAR(32) DEFAULT 'text',  -- text / image / file / system
    content TEXT NOT NULL,  -- 消息内容
    is_internal BOOLEAN DEFAULT false,  -- 是否内部备注
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 快捷回复模板表已随 #3081 功能下线移除（被知识卡片替代，见 V38 迁移）

-- ================================================
-- 7. CRM 客户管理相关表
-- ================================================

-- 客户档案表：CRM 核心，含 RFM 评分、生命周期管理
CREATE TABLE customer_profiles (
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

-- 客户标签定义表：支持手动标签和自动规则标签
CREATE TABLE customer_tags (
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

-- 客户分群规则表：基于多条件组合的客户分群
CREATE TABLE customer_segments (
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

-- 分群成员关联表
CREATE TABLE customer_segment_members (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    segment_id VARCHAR(64) NOT NULL REFERENCES customer_segments(id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customer_profiles(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(segment_id, customer_id)
);

-- ================================================
-- 8. 售后工单相关表
-- ================================================

-- 售后工单表：退换货/维修/投诉全流程管理
CREATE TABLE after_sales_tickets (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_no VARCHAR(64),
    order_id VARCHAR(64),  -- 关联订单
    customer_id VARCHAR(64),  -- 关联客户
    ticket_type VARCHAR(32) NOT NULL,  -- return / exchange / repair / complaint
    status VARCHAR(32) DEFAULT 'pending',  -- pending / processing / resolved / rejected / closed
    source VARCHAR(32) DEFAULT 'customer',  -- customer / agent
    priority VARCHAR(16) DEFAULT 'normal',  -- normal / urgent / critical
    handler_id VARCHAR(64) REFERENCES agent_employees(id),
    assigned_at TIMESTAMP WITH TIME ZONE,
    description TEXT,
    images JSONB DEFAULT '[]',
    refund_amount DECIMAL(10, 2),
    refund_method VARCHAR(32),  -- original_route / bank_transfer / balance
    evidence_images JSONB DEFAULT '[]',
    internal_notes TEXT,
    deadline TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    close_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0,
    -- 工单号租户内唯一（多租户隔离；全局唯一会让新租户从 0001 起号撞老租户，见 V25 迁移）
    CONSTRAINT uq_after_sales_tickets_tenant_no UNIQUE (tenant_id, ticket_no)
);

-- 工单处理时间线表
CREATE TABLE ticket_timeline (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    action VARCHAR(32) NOT NULL,  -- created / assigned / processed / notified / confirmed / closed / rejected
    actor_id VARCHAR(64),
    actor_type VARCHAR(32) NOT NULL,  -- agent / system / customer
    content JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 工单备注表：支持多条内部备注
CREATE TABLE ticket_notes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    author_id VARCHAR(64) NOT NULL REFERENCES agent_employees(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================
-- 9. 订单相关表
-- ================================================

-- 订单表
CREATE TABLE orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_no VARCHAR(64) NOT NULL UNIQUE,          -- 订单号
    customer_name VARCHAR(100),                     -- 客户姓名
    customer_phone VARCHAR(20),                     -- 客户电话
    customer_address TEXT,                          -- 客户地址
    total_amount DECIMAL(12,2) DEFAULT 0,           -- 总金额
    status VARCHAR(20) DEFAULT 'pending',           -- 状态: pending/confirmed/producing/completed/cancelled
    -- 来自 008_product_sku_matrix.sql
    payment_status VARCHAR(20) DEFAULT 'unpaid',    -- 支付状态: unpaid/paid/refunded
    stock_deducted BOOLEAN DEFAULT FALSE,           -- 是否已扣库存
    -- 来自 010_order_follow_status.sql
    follow_status VARCHAR(20) DEFAULT 'pending',    -- 跟进状态: pending/following/completed
    -- 来自 V20260901__add_order_user_id.sql
    user_id VARCHAR(64),                            -- 下单用户ID（users.id，C 端数据隔离依据）
    remark TEXT,                                     -- 备注
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 订单明细表
CREATE TABLE order_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    product_id VARCHAR(36),                         -- 关联商品
    product_name VARCHAR(200),                      -- 商品名称
    quantity INTEGER DEFAULT 1,                     -- 数量
    unit_price DECIMAL(12,2),                       -- 单价
    width DECIMAL(8,2),                             -- 宽度(米)
    height DECIMAL(8,2),                            -- 高度(米)
    processing_info JSONB,                          -- 加工项详情JSON
    subtotal DECIMAL(12,2),                         -- 小计
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- 物流跟踪记录表
CREATE TABLE order_logistics (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(64) NOT NULL REFERENCES orders(id),
    logistics_company VARCHAR(128) NOT NULL,
    tracking_no VARCHAR(128) NOT NULL,
    status VARCHAR(32) DEFAULT 'in_transit',  -- in_transit / delivered / returned
    tracking_info JSONB DEFAULT '[]',  -- 物流轨迹
    shipped_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================
-- 9.5 加工单表（issue #3340，V43 迁移；订单 producing 阶段子进度）
-- ================================================
CREATE TABLE IF NOT EXISTS processing_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    processing_order_no VARCHAR(32) NOT NULL,
    processor VARCHAR(128),
    expected_delivery_date DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'generated',  -- generated/issued/in_processing/completed/cancelled
    items_snapshot JSONB NOT NULL DEFAULT '[]',
    remark TEXT,
    template_version INT DEFAULT 1,
    generated_by VARCHAR(64),
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    issued_at TIMESTAMP WITH TIME ZONE,
    in_processing_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_reason TEXT,
    print_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_active
    ON processing_orders (order_id)
    WHERE deleted = 0 AND status IN ('generated', 'issued', 'in_processing', 'completed');
CREATE INDEX IF NOT EXISTS idx_processing_orders_tenant_status
    ON processing_orders (tenant_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_no
    ON processing_orders (processing_order_no);

-- ================================================
-- 10. 审计日志表
-- ================================================

-- 操作审计日志表：记录所有关键业务操作
CREATE TABLE audit_logs (
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ================================================
-- 11. 通知系统相关表
-- ================================================

-- 通知模板表
CREATE TABLE notification_templates (
    id VARCHAR(64) PRIMARY KEY,
    -- ⚠️ 不加 FK：迁移链 V27 建的是 `tenant_id BIGINT NOT NULL DEFAULT 0`，**系统内置
    -- 模板/规则用 tenant_id=0**（"系统内置，只读"），而 tenants 表没有 id=0 的行 →
    -- 加 FK 会让 V28 种子插不进去（实测：违反外键约束），**迁移链从 V28 起整条中断**。
    tenant_id BIGINT NOT NULL DEFAULT 0,
    name VARCHAR(128) NOT NULL,
    type VARCHAR(64) NOT NULL,  -- ticket_assigned / ticket_status_changed / refund_success / shipment / etc.
    channel VARCHAR(32) NOT NULL,  -- wechat / sms / email / internal
    template_content TEXT NOT NULL,
    -- ⚠️ TEXT 而非 JSONB：迁移链 V27 建的是 `variables TEXT`，实体 NotificationTemplate
    -- 也是 `String variables` —— 只有本文件曾写成 JSONB，导致 V28 种子（插入
    -- 'orderNo,amount' 这种逗号分隔串）在 bootstrap 库上直接
    -- `invalid input syntax for type json` → **迁移链从 V28 起整条中断**
    -- （V29–V41、V5–V9 全部未执行，schema 与代码长期脱节；CI 实证 run 34626024229）。
    variables TEXT,  -- 可用变量列表（逗号分隔）
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 通知规则表
CREATE TABLE notification_rules (
    id VARCHAR(64) PRIMARY KEY,
    -- ⚠️ 不加 FK：迁移链 V27 建的是 `tenant_id BIGINT NOT NULL DEFAULT 0`，**系统内置
    -- 模板/规则用 tenant_id=0**（"系统内置，只读"），而 tenants 表没有 id=0 的行 →
    -- 加 FK 会让 V28 种子插不进去（实测：违反外键约束），**迁移链从 V28 起整条中断**。
    tenant_id BIGINT NOT NULL DEFAULT 0,
    event_type VARCHAR(64) NOT NULL,  -- ticket_assigned / ticket_status_changed / refund_success / etc.
    recipient_type VARCHAR(32) NOT NULL,  -- customer / handler / supervisor / manager
    -- 同上：迁移链 V27 与实体 NotificationRule 都用字符串（VARCHAR(100)），非 JSONB
    channels VARCHAR(100),  -- 逗号分隔渠道，如 "wechat,sms"
    enabled BOOLEAN DEFAULT true,
    template_id VARCHAR(64) REFERENCES notification_templates(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 通知发送记录表
CREATE TABLE notifications (
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

-- ================================================
-- 12. 企业入驻申请表（平台级，无 tenant_id）
-- ================================================

-- 企业入驻申请表：企业申请入驻平台的审批流程
CREATE TABLE tenant_applications (
    id BIGSERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    contact_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    business_license_url VARCHAR(500),
    industry VARCHAR(100),
    address TEXT,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    reject_reason TEXT,
    reviewed_by VARCHAR(64) REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ================================================
-- 13. 索引
-- ================================================

-- tenants 索引
CREATE INDEX idx_tenants_code ON tenants(code);
CREATE INDEX idx_tenants_status ON tenants(status);
CREATE INDEX idx_tenants_deleted ON tenants(deleted);

-- users 索引
CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_phone ON users(phone);
CREATE INDEX idx_users_status ON users(status);
CREATE INDEX idx_users_deleted ON users(deleted);

-- roles 索引
CREATE INDEX idx_roles_tenant ON roles(tenant_id);
CREATE INDEX idx_roles_code ON roles(code);
CREATE INDEX idx_roles_status ON roles(status);
CREATE INDEX idx_roles_deleted ON roles(deleted);

-- permissions 索引
CREATE INDEX idx_permissions_tenant ON permissions(tenant_id);
CREATE INDEX idx_permissions_code ON permissions(code);
CREATE INDEX idx_permissions_resource ON permissions(resource_type, resource_id);
CREATE INDEX idx_permissions_status ON permissions(status);
CREATE INDEX idx_permissions_deleted ON permissions(deleted);

-- user_roles 索引
CREATE INDEX idx_user_roles_tenant ON user_roles(tenant_id);
CREATE INDEX idx_user_roles_user ON user_roles(user_id);
CREATE INDEX idx_user_roles_role ON user_roles(role_id);
CREATE INDEX idx_user_roles_deleted ON user_roles(deleted);

-- user_identities 索引
CREATE INDEX idx_user_identities_tenant ON user_identities(tenant_id);
CREATE INDEX idx_user_identities_user ON user_identities(user_id);
CREATE INDEX idx_user_identities_openid ON user_identities(openid);
CREATE INDEX idx_user_identities_unionid ON user_identities(unionid);
CREATE INDEX idx_user_identities_deleted ON user_identities(deleted);

-- categories 索引
CREATE INDEX idx_categories_tenant ON categories(tenant_id);
CREATE INDEX idx_categories_parent ON categories(parent_id);
CREATE INDEX idx_categories_status ON categories(status);
CREATE INDEX idx_categories_deleted ON categories(deleted);

-- products 索引
CREATE INDEX idx_products_tenant ON products(tenant_id);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_products_deleted ON products(deleted);
CREATE INDEX idx_products_stock ON products(stock);

-- processing_categories 索引
CREATE INDEX idx_processing_categories_tenant ON processing_categories(tenant_id);
CREATE INDEX idx_processing_categories_status ON processing_categories(status);
CREATE INDEX idx_processing_categories_deleted ON processing_categories(deleted);

-- processing_items 索引
CREATE INDEX idx_processing_items_tenant ON processing_items(tenant_id);
CREATE INDEX idx_processing_items_category ON processing_items(category_id);
CREATE INDEX idx_processing_items_status ON processing_items(status);
CREATE INDEX idx_processing_items_deleted ON processing_items(deleted);

-- processing_rules 索引
CREATE INDEX idx_processing_rules_tenant ON processing_rules(tenant_id);
CREATE INDEX idx_processing_rules_category ON processing_rules(applicable_category_id);




-- tenant_apps 索引
CREATE INDEX idx_tenant_apps_tenant ON tenant_apps(tenant_id);
CREATE INDEX idx_tenant_apps_status ON tenant_apps(status);
CREATE INDEX idx_tenant_apps_deleted ON tenant_apps(deleted);

-- tenant_ai_configs 索引
CREATE INDEX idx_tenant_ai_configs_tenant ON tenant_ai_configs(tenant_id);
CREATE INDEX idx_tenant_ai_configs_deleted ON tenant_ai_configs(deleted);

-- agent_employees 索引
CREATE INDEX idx_agent_employees_tenant ON agent_employees(tenant_id);
CREATE INDEX idx_agent_employees_user ON agent_employees(user_id);
CREATE INDEX idx_agent_employees_status ON agent_employees(status);
CREATE INDEX idx_agent_employees_deleted ON agent_employees(deleted);

-- sessions 索引
CREATE INDEX idx_sessions_tenant ON sessions(tenant_id);
CREATE INDEX idx_sessions_customer ON sessions(customer_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_agent ON sessions(assigned_agent_id);
CREATE INDEX idx_sessions_deleted ON sessions(deleted);

-- session_messages 索引
CREATE INDEX idx_session_messages_session ON session_messages(session_id, created_at);
CREATE INDEX idx_session_messages_tenant ON session_messages(tenant_id);
CREATE INDEX idx_session_messages_role ON session_messages(role);
CREATE INDEX idx_session_messages_deleted ON session_messages(deleted);

-- agent_sessions 索引
CREATE INDEX idx_agent_sessions_tenant ON agent_sessions(tenant_id);
CREATE INDEX idx_agent_sessions_employee ON agent_sessions(employee_id);
CREATE INDEX idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX idx_agent_sessions_customer ON agent_sessions(customer_id);
CREATE INDEX idx_agent_sessions_ai_session ON agent_sessions(ai_session_id);

-- agent_messages 索引
CREATE INDEX idx_agent_messages_session ON agent_messages(session_id, created_at);
CREATE INDEX idx_agent_messages_tenant ON agent_messages(tenant_id);

-- customer_profiles 索引
CREATE INDEX idx_customer_profiles_tenant ON customer_profiles(tenant_id);
CREATE INDEX idx_customer_profiles_phone ON customer_profiles(phone);
CREATE INDEX idx_customer_profiles_wechat ON customer_profiles(wechat_openid);
CREATE INDEX idx_customer_profiles_status ON customer_profiles(customer_status);
CREATE INDEX idx_customer_profiles_vip ON customer_profiles(vip_level);
CREATE INDEX idx_customer_profiles_rfm ON customer_profiles(rfm_total_score DESC);
CREATE INDEX idx_customer_profiles_last_order ON customer_profiles(last_order_at);

-- customer_tags 索引
CREATE INDEX idx_customer_tags_tenant ON customer_tags(tenant_id);
CREATE INDEX idx_customer_tags_type ON customer_tags(tag_type);

-- customer_segments 索引
CREATE INDEX idx_customer_segments_tenant ON customer_segments(tenant_id);
CREATE INDEX idx_customer_segments_type ON customer_segments(segment_type);

-- customer_segment_members 索引
CREATE INDEX idx_segment_members_segment ON customer_segment_members(segment_id);
CREATE INDEX idx_segment_members_customer ON customer_segment_members(customer_id);
CREATE INDEX idx_segment_members_tenant ON customer_segment_members(tenant_id);

-- after_sales_tickets 索引
CREATE INDEX idx_after_sales_tickets_tenant ON after_sales_tickets(tenant_id);
CREATE INDEX idx_after_sales_tickets_order ON after_sales_tickets(order_id);
CREATE INDEX idx_after_sales_tickets_status ON after_sales_tickets(status);
CREATE INDEX idx_after_sales_tickets_deleted ON after_sales_tickets(deleted);

-- ticket_timeline 索引
CREATE INDEX idx_ticket_timeline_ticket ON ticket_timeline(ticket_id, created_at);
CREATE INDEX idx_ticket_timeline_tenant ON ticket_timeline(tenant_id);

-- ticket_notes 索引
CREATE INDEX idx_ticket_notes_ticket ON ticket_notes(ticket_id, created_at);
CREATE INDEX idx_ticket_notes_tenant ON ticket_notes(tenant_id);

-- orders 索引
CREATE INDEX idx_orders_tenant ON orders(tenant_id);
CREATE INDEX idx_orders_order_no ON orders(order_no);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_deleted ON orders(deleted);

-- order_items 索引
CREATE INDEX idx_order_items_tenant ON order_items(tenant_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_order_items_deleted ON order_items(deleted);

-- order_logistics 索引
CREATE INDEX idx_order_logistics_tenant ON order_logistics(tenant_id);
CREATE INDEX idx_order_logistics_order ON order_logistics(order_id);
CREATE INDEX idx_order_logistics_tracking ON order_logistics(tracking_no);
CREATE INDEX idx_order_logistics_deleted ON order_logistics(deleted);

-- audit_logs 索引
CREATE INDEX idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at DESC);

-- notification_templates 索引
CREATE INDEX idx_notification_templates_tenant ON notification_templates(tenant_id);
CREATE INDEX idx_notification_templates_type ON notification_templates(type);

-- notification_rules 索引
CREATE INDEX idx_notification_rules_tenant ON notification_rules(tenant_id);
CREATE INDEX idx_notification_rules_event ON notification_rules(event_type);

-- notifications 索引
CREATE INDEX idx_notifications_tenant ON notifications(tenant_id);
CREATE INDEX idx_notifications_recipient ON notifications(recipient_id);
CREATE INDEX idx_notifications_status ON notifications(status);
CREATE INDEX idx_notifications_created ON notifications(created_at DESC);

-- tenant_applications 索引
CREATE INDEX idx_tenant_applications_phone ON tenant_applications(phone);
CREATE INDEX idx_tenant_applications_status ON tenant_applications(status);

-- ================================================
-- 14. 字段注释补充
-- ================================================

COMMENT ON COLUMN user_roles.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN user_identities.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN session_messages.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN ticket_timeline.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN ticket_notes.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN audit_logs.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN order_items.updated_at IS '更新时间（大数据分析补充字段）';
COMMENT ON COLUMN customer_segment_members.updated_at IS '更新时间（大数据分析补充字段）';

-- ================================================
-- 15. RLS 策略（多租户行级安全隔离）
-- ================================================

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenants ON tenants
    USING (id::text = current_setting('app.current_tenant_id') OR current_setting('app.current_tenant_id') = '');

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_users ON users
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_roles ON roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE permissions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_permissions ON permissions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_user_roles ON user_roles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_user_identities ON user_identities
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_categories ON categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE products ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_products ON products
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE processing_categories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_categories ON processing_categories
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE processing_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_items ON processing_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE processing_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_processing_rules ON processing_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE tenant_apps ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_apps ON tenant_apps
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE tenant_ai_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_ai_configs ON tenant_ai_configs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE agent_employees ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_employees ON agent_employees
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sessions ON sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE session_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_session_messages ON session_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_sessions ON agent_sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_messages ON agent_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE customer_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_profiles ON customer_profiles
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE customer_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_tags ON customer_tags
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE customer_segments ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_segments ON customer_segments
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE customer_segment_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_customer_segment_members ON customer_segment_members
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE after_sales_tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_after_sales_tickets ON after_sales_tickets
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE ticket_timeline ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ticket_timeline ON ticket_timeline
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE ticket_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ticket_notes ON ticket_notes
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_orders ON orders
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_items ON order_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE order_logistics ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_logistics ON order_logistics
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_templates ON notification_templates
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE notification_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notification_rules ON notification_rules
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notifications ON notifications
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- ================================================
-- 补齐迁移链曾创建但 bootstrap 缺失的表（issue #3270）
-- 背景：schema.sql 与 db/migration 双源漂移 —— 迁移链含 5 张 schema.sql 没有的表
-- （platform_admins / session_states / user_suggestion_prefs / finance_transactions /
--  role_permissions）。docker bootstrap 只跑 schema.sql → 这些表缺失 → 迁移链再跑
-- 又因「表已存在/顺序依赖」炸掉 → admin-api/ai-agent 运行时缺表 500。
-- 收敛方向：schema.sql = 完整最终态（含全部表），docker bootstrap 跳过迁移链。
-- ================================================

-- 平台管理员（超管），平台级账号，无租户归属（V7）
CREATE TABLE IF NOT EXISTS platform_admins (
    id VARCHAR(64) PRIMARY KEY,
    phone VARCHAR(32) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    nickname VARCHAR(128),
    avatar VARCHAR(512),
    status VARCHAR(32) DEFAULT 'active',
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 会话工作状态表（V12，会话管理重构 P1）：跨轮工作状态单一事实源
CREATE TABLE IF NOT EXISTS session_states (
    session_id VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
    state JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 建议偏好表（V9）
CREATE TABLE IF NOT EXISTS user_suggestion_prefs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    intent_type VARCHAR(64) NOT NULL,
    click_count INTEGER DEFAULT 1,
    last_clicked_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, intent_type)
);
CREATE INDEX IF NOT EXISTS idx_usp_tenant_user ON user_suggestion_prefs(tenant_id, user_id);

-- 资金流水表（V11）：现金流单一事实来源
CREATE TABLE IF NOT EXISTS finance_transactions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    transaction_no VARCHAR(64) NOT NULL,
    order_id VARCHAR(36),
    order_no VARCHAR(64),
    type VARCHAR(20) NOT NULL,
    amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    payment_method VARCHAR(32),
    status VARCHAR(20) NOT NULL DEFAULT 'success',
    operator VARCHAR(64),
    occurred_at TIMESTAMPTZ,
    remark VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_finance_txn_no ON finance_transactions(tenant_id, transaction_no);
CREATE INDEX IF NOT EXISTS idx_finance_txn_order ON finance_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_finance_txn_occurred ON finance_transactions(tenant_id, occurred_at);

-- 角色权限表（V16）
CREATE TABLE IF NOT EXISTS role_permissions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_role_permissions ON role_permissions(role_id, permission_id);

-- ================================================
-- 种子数据（与 schema_full.sql 对齐；bootstrap 必需 —— issue #3270 实测）
-- ================================================
-- 背景：ai-agent 的 DEBUG customer 身份固定 tenant_id=1（app/utils/auth.py），
-- 而 schema.sql 只建表不插种子 → 全新库上 sessions 插入违反
-- `sessions_tenant_id_fkey`（tenant 1 不存在）→ 会话创建 HTTP 500 →
-- 本地/CI docker 栈的 C 端评测全部失败（9/9，2026-08-31 起）。
-- schema_full.sql 一直有这段种子，schema.sql 却缺失（两份 schema 漂移）。

-- 默认租户（id=1）
INSERT INTO tenants (id, name, code, industry, status)
  OVERRIDING SYSTEM VALUE
  VALUES (1, '米高智能', 'migao', '布艺窗帘', 'active')
  ON CONFLICT (id) DO NOTHING;

-- 默认角色（五岗：管理员/运营/客服 + 超管；角色码与 HR 用例对齐）
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
  ('role_admin', 1, '管理员', 'admin', '租户管理权限', 'active'),
  ('role_operator', 1, '运营', 'operator', '商品与订单运营', 'active'),
  ('role_customer_service', 1, '客服', 'customer_service', '客服工作台权限', 'active'),
  ('role_super_admin', 1, '超级管理员', 'super_admin', '平台级超管权限', 'active')
  ON CONFLICT (id) DO NOTHING;

-- ================================================
-- 11. bootstrap 对齐：迁移链/java 实体已要求、本文件此前缺失的列与表（issue #3270）
-- ================================================
-- 为什么放在最后、且用 ALTER：本文件是**全新库的一次性 bootstrap**（CI/本地 docker 栈
-- 由 docker-entrypoint-initdb.d 执行），而 **Flyway 不在该栈运行** —— 只存在于迁移链
-- 的列在建库后并不存在，于是 admin-api 查询 500 → ai-agent 工具返回
-- "服务暂时不可用"（CIRCUIT_OPEN）→ 熔断打开 → **整轮 C 端评测被污染**。
-- CI 实证（run 34617597854，postgres 日志原文）：
--   column "color_name" does not exist    (product_skus) → 商品详情 500
--   column "actual_amount" does not exist (orders)       → /agent/orders/mine 500
--   column "position" does not exist      (users)        → 用户查询 500
--   column "bot_name" does not exist      (tenant_ai_configs) → 租户配置 500
--   relation "user_memories" does not exist             → 长期记忆查询失败
-- 报错现象是「agent 不会下单」，真因是**后端 500 + 熔断**（五层归因的基础设施层）。
--
-- 幂等：全部 IF NOT EXISTS。与迁移链重复执行无害（迁移链仍是结构变更事实源，
-- 本段只保证 bootstrap 后状态与迁移链终态一致）。
-- 守卫：tests/unit_ci_workflows/test_schema_integrity.py 双重断言
--       （迁移链覆盖 + 代码必需列覆盖），漂移即 CI block。

-- 订单实收/优惠/退款（V5 / V14）
ALTER TABLE orders ADD COLUMN IF NOT EXISTS actual_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS close_reason VARCHAR(500);

-- 员工岗位/权限点（docs/sql/migrations/V20260614、V1）
ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;

-- SKU 颜色标识（ProductSku.colorName —— 两条 SQL 链都没有，仅 java 实体声明）
ALTER TABLE product_skus ADD COLUMN IF NOT EXISTS color_name VARCHAR(64);

-- 租户 AI 配置：机器人名称（docs/sql/009）+ 渠道配置（V10）
ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS bot_name VARCHAR(64) DEFAULT '小布';
ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS channel_configs JSONB;

-- 会话最后活动时间（V13）
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;

-- 加工项每米数量密度（V33）
ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS per_meter_quantity DECIMAL(6,2);
ALTER TABLE product_processing_items ADD COLUMN IF NOT EXISTS custom_per_meter_quantity DECIMAL(6,2);

-- 租户品牌/通知设置（V15）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo VARCHAR(512);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_email VARCHAR(128);

-- 入驻申请 AI 甄别字段（V18）
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS company_name_norm VARCHAR(255);
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS review_source VARCHAR(20);
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS risk_flags TEXT;
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS review_summary TEXT;
CREATE INDEX IF NOT EXISTS idx_tenant_applications_company_norm
    ON tenant_applications(company_name_norm);

-- C 端长期记忆表（docs/sql/migrations/V20260608 + V20260904）
CREATE TABLE IF NOT EXISTS user_memories (
    id          VARCHAR(32) PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    user_id     VARCHAR(64) NOT NULL,
    type        VARCHAR(20) NOT NULL,
    key         VARCHAR(128) NOT NULL,
    value       TEXT NOT NULL,
    importance  FLOAT DEFAULT 0.5,
    context     TEXT,
    related_to  TEXT[],
    agent_type  VARCHAR(20) NOT NULL DEFAULT 'xiaobu',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, key)
);
ALTER TABLE user_memories
    ADD COLUMN IF NOT EXISTS agent_type VARCHAR(20) NOT NULL DEFAULT 'xiaobu';
CREATE INDEX IF NOT EXISTS idx_user_memories_tenant_user
    ON user_memories(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_memories_importance
    ON user_memories(tenant_id, user_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_user_memories_agent
    ON user_memories(agent_type, tenant_id, user_id);

-- ================================================
-- END OF SCHEMA
-- ================================================
