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
    briefing_enabled BOOLEAN DEFAULT FALSE,
    briefing_generate_time VARCHAR(5) DEFAULT '06:00',
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

    -- 工艺画像与常用物流（issue #3984，V47 迁移；M2-D）
    craft_mode VARCHAR(16) DEFAULT 'standard',  -- standard 跟随企业固定工艺 / economy 主动省料 / self_quoted 自报用料
    craft_profile JSONB DEFAULT '{}',  -- 工艺偏好 JSON：开数/定型/档位等默认（M3-F 报价协商读取）
    default_logistics_type VARCHAR(16) DEFAULT 'express',  -- 常用物流类型：express 快递 / logistics 物流专线
    default_logistics_company VARCHAR(128),  -- 客户常用物流/快递公司（下单自动带出）

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
    quantity DECIMAL(10,2) DEFAULT 1,               -- 数量（计价方式口径：per_meter=米数/per_set=1/per_area=宽×高㎡，issue #3666）
    unit_price DECIMAL(12,2),                       -- 单价
    width DECIMAL(8,2),                             -- 宽度(米)
    height DECIMAL(8,2),                            -- 高度(米)
    processing_info JSONB,                          -- 加工项详情JSON
    subtotal DECIMAL(12,2),                         -- 小计
    -- 下单行要素（V63，issue #4362，S1；用户裁定「部位不是必填的」）—— **全部 nullable、不设校验**。
    -- 逐列语义见 V63__structure_order_line_craft_spec.sql；本处只落 bootstrap 终态
    -- （bootstrap 路径**不跑迁移链**的部署形态下，缺列 ⇒ 加工单查询/落库 500，形态见 #3270）。
    curtain_type VARCHAR(16),                       -- 部位/帘种（布帘/纱帘/帘头）；工序库路线按它索引
    craft VARCHAR(16),                              -- 安装工艺＝打褶/悬挂方式（韩褶/打孔/穿杆/平幔）；**单值**；四爪钩是加工项不是工艺
    open_count INTEGER,                             -- 打开方式（**开数**，正整数：1 单开 / 2 对开 / 3 三开 / 4 四开 …，不是固定枚举；V64 / issue #4387）
    cutting_mode VARCHAR(16),                       -- 加工类型（定高买宽 / 定宽买高）
    is_shaped BOOLEAN,                              -- 是否定型（部位级开关）
    fullness DECIMAL(6,2),                          -- 理论褶倍（与 fullness_actual 分开存 —— 实证 1.86 ≠ 2.00，不是冗余）
    fullness_actual DECIMAL(6,2),                   -- 实际褶倍（由实际用料反算）
    pleat_spacing DECIMAL(6,3),                     -- 褶距（米，韩褶默认 0.1）
    pleat_count INTEGER,                            -- 总褶数（与工序应做数量口径对齐）
    has_pattern BOOLEAN,                            -- 是否对花
    corner VARCHAR(32),                             -- 转角（取自澄清清单窗型；影响开数与片数）
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
    shipper_name VARCHAR(64),                 -- 发货人（发货单纸面「经手人」，V46 迁移；存量 NULL）
    logistics_type VARCHAR(16) DEFAULT 'express',  -- 物流类型：express 快递 / logistics 物流专线（四季安等，V47 迁移；issue #3984）
    status VARCHAR(32) DEFAULT 'in_transit',  -- in_transit / delivered / returned
    tracking_info JSONB DEFAULT '[]',  -- 物流轨迹
    shipped_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ================================================
-- 9.4b 企业收款二维码（issue #3990，V48 迁移；M3-F-2）
-- ================================================
CREATE TABLE IF NOT EXISTS tenant_payment_qrcodes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    payment_type VARCHAR(16) NOT NULL,           -- wechat 微信 / alipay 支付宝
    image_url VARCHAR(512) NOT NULL,             -- 收款码图片地址
    payee_name VARCHAR(128),                     -- 收款主体名称（展示用）
    remark VARCHAR(255),
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_payment_qrcode_tenant_type
    ON tenant_payment_qrcodes (tenant_id, payment_type)
    WHERE deleted = 0;
COMMENT ON TABLE tenant_payment_qrcodes IS '企业收款二维码（微信/支付宝）：顾客扫码直接付给商家，平台不经手资金（二清规避，issue #3990）';

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
    qr_token VARCHAR(64),                             -- 加工单二维码 token（V49，扫码报工入口）
    route_key VARCHAR(32),                            -- 实际使用的路线键「帘种×工艺」（V60，issue #4308）
    route_requested_key VARCHAR(32),                  -- 派生出来想用的路线键（V60）；两维全不命中时 NULL
    route_source VARCHAR(16),                         -- 路线键来源（V60）：derived / partial / missing_route / default
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
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_qr_token
    ON processing_orders (qr_token)
    WHERE deleted = 0 AND qr_token IS NOT NULL;

-- ================================================
-- 9.5.1 生产报工（issue #3995，V49 迁移；M4-G-2）
-- 工序库 / 工艺路线模板 / 工序实例 / 报工记录；真值源 docs/curtain-production-rules.md
-- ================================================
CREATE TABLE IF NOT EXISTS production_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,                       -- 工序名（按部位分设：韩褶-布 / 韩褶-纱）
    group_name VARCHAR(16) NOT NULL DEFAULT '其他',  -- 车间工位分组：裁剪/车位/后道/其他
    position VARCHAR(16),                            -- 部位：布帘/纱帘/帘头/外帘（空=通用）
    unit VARCHAR(16) NOT NULL DEFAULT '米',           -- 计件单位：米/折/幅/孔/套/个
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 计件单价（元/单位）
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,   -- 必完工序：全绿才可打包 → 订单自动完工
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,  -- 生产开始标记
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operations_tenant_name
    ON production_operations (tenant_id, name)
    WHERE deleted = 0;
-- provenance 口径来源（V62，issue #4361）：实证 / 推算 / 占位待确认；NULL = 来源未知。
-- 存在的理由：单价是占位值/行业推算值这件事必须**在数据与界面上可见**（用户裁定 2026-09-19
-- 「照铺，但 provenance 必须可见，不许静默」）；#4343 已证明 布帘×韩褶 与客户真实加工单不符。
-- 本段是 bootstrap 终态（本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无该列 ⇒ 读面 500，同 #3270 形态）。
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS source VARCHAR(16);
ALTER TABLE production_operations DROP CONSTRAINT IF EXISTS production_operations_source_check;
ALTER TABLE production_operations
    ADD CONSTRAINT production_operations_source_check
    CHECK (source IS NULL OR source IN ('占位待确认', '推算', '实证'));
COMMENT ON COLUMN production_operations.source IS
    'provenance 口径来源（V62，issue #4361）：实证 / 推算 / 占位待确认。'
    '占位待确认 = 单价是占位值（V54 的 30 道）；推算 = 单价为行业推算（V56 的 5 道）；'
    '实证 = 当前空集（客户确认 #4261/#4343 后才会有）。NULL = 来源未知（商家自建/历史行）。';

CREATE TABLE IF NOT EXISTS production_routings (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    curtain_type VARCHAR(16) NOT NULL,               -- 部位/帘种：布帘/纱帘/帘头
    craft VARCHAR(16) NOT NULL,                      -- 工艺：韩褶/打孔/四爪钩/穿杆/平幔
    operations JSONB NOT NULL DEFAULT '[]',          -- 工序名序列（有序数组）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_routings_tenant_type_craft
    ON production_routings (tenant_id, curtain_type, craft)
    WHERE deleted = 0;
-- provenance 口径来源（V62，issue #4361）：rt-v54-* = 占位待确认（含 布帘×韩褶 —— #4343 已证明
-- 与客户真实加工单 CSO260915-02615 不符）/ rt-v58-* = 推算（3 条纱帘，镜像布帘同工艺推导）/
-- 实证 = 当前空集；NULL = 来源未知。回填见本文件种子段之后的 UPDATE。
ALTER TABLE production_routings ADD COLUMN IF NOT EXISTS source VARCHAR(16);
ALTER TABLE production_routings DROP CONSTRAINT IF EXISTS production_routings_source_check;
ALTER TABLE production_routings
    ADD CONSTRAINT production_routings_source_check
    CHECK (source IS NULL OR source IN ('占位待确认', '推算', '实证'));
COMMENT ON COLUMN production_routings.source IS
    'provenance 口径来源（V62，issue #4361）：实证 / 推算 / 占位待确认。'
    '占位待确认 = V54 的 6 条（含 布帘×韩褶）；推算 = V58 的 3 条纱帘；实证 = 当前空集。';

CREATE TABLE IF NOT EXISTS processing_position_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    position_name VARCHAR(32) NOT NULL,              -- 部位：布帘/纱帘/帘头/外帘
    seq INT NOT NULL DEFAULT 0,                      -- 部位内工序顺序
    operation_name VARCHAR(64) NOT NULL,
    group_name VARCHAR(16),
    unit VARCHAR(16),
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,            -- 应做数量（算料引擎输出）
    qty_source VARCHAR(32),                          -- 应做数量的口径来源（V57，issue #4208）：键名=算料输出 / <键名>_x6=每米6孔估算 / fallback=真兜底1
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 实例快照单价
    factor NUMERIC(6,2) NOT NULL DEFAULT 1,          -- 特殊选项计件系数（一分为二 ×1.7，ERP 名；issue #4389）
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending 待做 / done 已报工
    done_qty NUMERIC(12,2) NOT NULL DEFAULT 0,       -- 合格累计数量（返工/报废不累加）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_position_operations_po
    ON processing_position_operations (processing_order_id, position_name, seq)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_position_operations_tenant
    ON processing_position_operations (tenant_id, status);

CREATE TABLE IF NOT EXISTS production_work_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    operation_id VARCHAR(64) NOT NULL,               -- 工序实例 id
    operation_name VARCHAR(64) NOT NULL,
    worker_id VARCHAR(64),
    worker_name VARCHAR(64),
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,            -- 报工数量
    qualified_qty NUMERIC(12,2) NOT NULL DEFAULT 0,  -- 合格数量（计件按合格数量）
    -- 计件单价/系数快照（V61，issue #4351）：报工那一刻从工序实例写入 ⇒ 聚合只读本行，
    -- 永不回查实例（重新实例化会软删旧实例并重插 ⇒ 回查会让历史报工的钱静默消失）。
    -- NULL = 本列引入之前的存量报工（聚合按实例回查兜底）。
    unit_price NUMERIC(10,2),
    factor NUMERIC(10,2),
    work_type VARCHAR(16) NOT NULL DEFAULT 'normal', -- 报工三态：normal/rework/scrap
    work_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_work_logs_po
    ON production_work_logs (processing_order_id, operation_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_work_logs_worker_date
    ON production_work_logs (tenant_id, worker_name, work_date)
    WHERE deleted = 0;

COMMENT ON TABLE production_operations IS '生产工序库：分组（裁剪/车位/后道/其他）+ 按部位分设 + 计件单价（V49，issue #3995）';
COMMENT ON TABLE production_routings IS '工艺路线模板：部位×工艺 → 基准工序序列（V49，issue #3995）';
COMMENT ON TABLE processing_position_operations IS '工序实例：加工单×部位×工序（应做数量/单价/系数/必完标记/报工进度），扫码报工的推进单元';
COMMENT ON TABLE production_work_logs IS '报工记录（明细不可变）：报工三态 normal/rework/scrap；计件 = Σ(合格数量×**报工自己的单价快照**×**系数快照**)，排除返工/报废；单工序一人制；快照见 V61（issue #4351）';
COMMENT ON COLUMN production_work_logs.unit_price IS '计件单价快照（元/单位，V61，issue #4351）：报工那一刻从工序实例写入；聚合只读本列 ⇒ 重新实例化软删旧实例不影响历史报工的钱；NULL=本列引入前的存量行（按实例回查兜底）';
COMMENT ON COLUMN production_work_logs.factor IS '计件系数快照（V61，issue #4351）：与 unit_price 同一次报工写入、同一口径；NULL=存量行';

-- 工序计件单价版本（V55，issue #4204）：当前价 = 最新版本行；实例单价仍是生成时快照。
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V55__create_production_operation_price_versions.sql
CREATE TABLE IF NOT EXISTS production_operation_price_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    operation_id VARCHAR(64) NOT NULL REFERENCES production_operations(id),
    unit_price NUMERIC(10,2) NOT NULL,               -- 该次变更后的单价（元/单位）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_price_versions_operation
    ON production_operation_price_versions (operation_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_operation_price_versions IS '工序计件单价版本（V55，issue #4204）：当前价 = 最新版本行；实例单价仍是生成时快照，改价不影响既有实例与历史报工';

-- 特殊选项 → 条件工序 / 计件系数（V59，issue #4230 Java 侧 v1a）
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V59__create_production_option_tables.sql
-- 为什么两处都要：本文件是**全新库的一次性 bootstrap**（docker-entrypoint-initdb.d 执行），
-- 而 **Flyway/MigrationRunner 不在该栈运行** —— 只存在于迁移链的表在建库后并不存在（#3270 形态）。
-- 真值源 = ai-agent app/production/routing.py 的 SPECIAL_OPTION_ROUTINGS / OPTION_FACTOR_SCOPES
-- （NON_PIECEWORK_OPTIONS 那两项是**显式登记的「不计件」**，两张表都**不**种 —— 种进来会把它
-- 变成「有映射但系数 1」，两种语义又混成一种）。
CREATE TABLE IF NOT EXISTS production_option_routings (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    option_name VARCHAR(32) NOT NULL,                -- 特殊选项名（真值源 §1 的 19 项之一）
    operation_name VARCHAR(64) NOT NULL,             -- 条件工序名（production_operations.name）
    after_operation VARCHAR(64) NOT NULL,            -- 插在它之后（不在路线中 ⇒ 追加到末尾）
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_option_routings_tenant_option_op
    ON production_option_routings (tenant_id, option_name, operation_name)
    WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS production_option_factors (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    option_name VARCHAR(32) NOT NULL,
    operation_name VARCHAR(64),                      -- NULL = 该部位全部工序（平摊档）；非空 = 逐工序例外档
    factor NUMERIC(6,2) NOT NULL DEFAULT 1,          -- 乘在工序实例 factor 上
    source VARCHAR(16) NOT NULL DEFAULT '推算',       -- 实证 / 推算
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
-- 唯一性用**表达式索引**（COALESCE(operation_name,'')）：NULL 在普通唯一索引里互不相等，
-- 不加 COALESCE 就能插进多行「同选项同平摊档」⇒ 系数取值不确定（静默失真）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_option_factors_tenant_option_op
    ON production_option_factors (tenant_id, option_name, COALESCE(operation_name, ''))
    WHERE deleted = 0;

COMMENT ON TABLE production_option_routings IS '特殊选项 → 条件工序（V59，issue #4230）：实例化时把 operation_name 插到 after_operation 之后';
COMMENT ON TABLE production_option_factors IS '特殊选项 → 计件系数（V59，issue #4230）：operation_name NULL = 该部位全部工序（平摊档），非空 = 逐工序例外档（例外档盖住平摊档）';

-- 信号 → 路线键 + 路线版本账（V60，issue #4308「工艺路线商家可配」）
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql
-- （为什么两处都要：本文件是**全新库的一次性 bootstrap**，bootstrap 路径**不跑迁移链** ⇒
--  只存在于迁移里的表在建库后并不存在，admin-api 查询 500，见 issue #3270 形态。）
-- 唯一性**按用途拆**（帘种行 / 工艺行各一条唯一索引）：迁移前的常量表里「帘头」出现两次且
-- 位次相反（帘种表最前、工艺表最后），单列 priority 无法同时表达 ⇒ 一行一个用途、各用途内唯一。
CREATE TABLE IF NOT EXISTS production_route_signals (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    signal VARCHAR(64) NOT NULL,                     -- 信号关键字（命中方式 = 文本 contains）
    curtain_type VARCHAR(16),                        -- 命中后给出的帘种（NULL = 本行不参与帘种扫描）
    craft VARCHAR(16),                               -- 命中后给出的工艺（NULL = 本行不参与工艺扫描）
    priority INT NOT NULL DEFAULT 0,                 -- **用途内**扫描序（越小越先）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_production_route_signals_has_target
        CHECK (curtain_type IS NOT NULL OR craft IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_signals_tenant_signal_curtain
    ON production_route_signals (tenant_id, signal)
    WHERE deleted = 0 AND curtain_type IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_signals_tenant_signal_craft
    ON production_route_signals (tenant_id, signal)
    WHERE deleted = 0 AND craft IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_production_route_signals_tenant_priority
    ON production_route_signals (tenant_id, priority)
    WHERE deleted = 0;
COMMENT ON TABLE production_route_signals IS
    '信号 → 路线键映射（V60，issue #4308）：派生加工单路线时按 priority 扫描本表；种子 = 迁移前的常量关键字表；商家可增删改';

CREATE TABLE IF NOT EXISTS production_routing_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    routing_id VARCHAR(64) NOT NULL REFERENCES production_routings(id),
    curtain_type VARCHAR(16) NOT NULL,
    craft VARCHAR(16) NOT NULL,
    operations JSONB NOT NULL DEFAULT '[]',          -- 本次变更后的工序名有序序列（seq = 下标+1）
    operation_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_routing_versions_routing
    ON production_routing_versions (routing_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_routing_versions IS
    '工艺路线版本账（V60，issue #4308）：每次改序列追加一行；路线是计件工资与完工判定的唯一输入，改动必须留痕';

-- 信号种子（tenant_id=1；**逐条**抄自迁移前的 ProcessingOrderService 两张常量关键字表：
-- 3 帘种 + 7 工艺 = 10 行。顺序即语义：「帘头」在帘种表最前（防「帘头纱」被判纱帘）、
-- 在工艺表最后（工艺侧兜底）⇒ 不得为好看重排。）
INSERT INTO production_route_signals
    (id, tenant_id, signal, curtain_type, craft, priority, status)
VALUES
  ('sig-v60-01', 1, '帘头', '帘头', NULL,   1, 'active'),
  ('sig-v60-02', 1, '纱',   '纱帘', NULL,   2, 'active'),
  ('sig-v60-03', 1, '布',   '布帘', NULL,   3, 'active'),
  ('sig-v60-04', 1, '韩褶', NULL,   '韩褶',  1, 'active'),
  ('sig-v60-05', 1, '打孔', NULL,   '打孔',  2, 'active'),
  ('sig-v60-06', 1, '四爪钩', NULL, '四爪钩', 3, 'active'),
  ('sig-v60-07', 1, '四叉钩', NULL, '四爪钩', 4, 'active'),
  ('sig-v60-08', 1, '穿杆', NULL,   '穿杆',  5, 'active'),
  ('sig-v60-09', 1, '平幔', NULL,   '平幔',  6, 'active'),
  ('sig-v60-10', 1, '帘头', NULL,   '平幔',  7, 'active')
ON CONFLICT DO NOTHING;

-- 信号映射层的终态修正（V63，issue #4362 阶段 1 ② / issue #4365 裁定）：
-- 「四爪钩/四叉钩」是**加工项（配件）**，工艺（安装工艺＝打褶/悬挂方式）**单值** ⇒ 这两行指向
-- **主线工艺**（韩褶），不再是独立路线键。上面那段 V60 种子**一字不动**（它是迁移前的常量表快照，
-- 由 ProductionRouteSignalMigrationTest 判据 1 钉住）⇒ 终态 = 「V60 种子 + 本 UPDATE」，
-- 与迁移链在存量库上的结果**逐行等价**（bootstrap 只写 schema.sql 的部署形态也拿到同一终态）。
UPDATE production_route_signals
   SET craft = '韩褶'
 WHERE signal IN ('四爪钩', '四叉钩')
   AND craft = '四爪钩'
   AND deleted = 0;

-- ================================================
-- 9.6 智能每日经营简报（issue #3468，V44 迁移）
-- ================================================
CREATE TABLE IF NOT EXISTS daily_briefings (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    biz_date DATE NOT NULL,
    content JSONB NOT NULL DEFAULT '{}',
    source_snapshot JSONB NOT NULL DEFAULT '{}',
    verify_status VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending / verified / partial / failed
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0,
    CONSTRAINT uk_daily_briefings_tenant_date UNIQUE (tenant_id, biz_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_briefings_tenant_date
    ON daily_briefings (tenant_id, biz_date);

-- ================================================
-- 9.7 库存流水/台账（issue #4055，V53 迁移）
-- ================================================
-- SKU 级库存变更事实账（粒度 = SKU 级，#4038：product_skus.stock 是权威、products.stock 是派生）。
-- 每行 = 一次变更（before_qty → after_qty），同 SKU 相邻两行必须首尾相接才可对账。
-- 保留期：不设 TTL，随订单生命周期软删（deleted）。与 orders.stock_deducted 死列的关系见 V53 头注释。
CREATE TABLE IF NOT EXISTS stock_ledger_entries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,                                   -- 无 FK：SKU 会被硬删重建（追溯优先用 sku_code）
    sku_code VARCHAR(64),
    delta INT NOT NULL,                              -- 正=入库/回补，负=出库/扣减（恒等于 after_qty - before_qty）
    before_qty INT NOT NULL,
    after_qty INT NOT NULL,
    reason VARCHAR(16) NOT NULL,                     -- order / aftersales / manual
    ref_no VARCHAR(64),                              -- 订单号 / 工单号；manual 为空
    note VARCHAR(255),                               -- 人类可读原因（如「盘点」「报损」）
    operator VARCHAR(64) NOT NULL,                   -- 登录用户名；内部服务 = internal-service；无认证 = system
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_sku
    ON stock_ledger_entries (tenant_id, sku_id, id);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_product
    ON stock_ledger_entries (tenant_id, product_id, id);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_ref
    ON stock_ledger_entries (tenant_id, ref_no, id);

-- ================================================
-- 10. 审计日志表
-- ================================================

-- 操作审计日志表：记录所有关键业务操作
CREATE TABLE audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL,
    user_name VARCHAR(128),
    action VARCHAR(64) NOT NULL,  -- 动作**动词**：create / update / delete / toggle_status / confirm_payment / etc.
    resource_type VARCHAR(64),  -- product / order / ticket / ai_config / employee / agent_tool / etc.
    tool_name VARCHAR(64),  -- AI 工具名（仅 resource_type=agent_tool 有值；见迁移 V52 / issue #4071）
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

ALTER TABLE daily_briefings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_daily_briefings ON daily_briefings
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
-- industry 用**受控 code**（issue #4361 词表 v1：curtain / other）——「开租按行业套用生产模板」
-- 要求它当模板键，自由文本取不到模板（静默落空库）。迁移 V62 会把存量自由文本按同口径归一。
INSERT INTO tenants (id, name, code, industry, status)
  OVERRIDING SYSTEM VALUE
  VALUES (1, '米高智能', 'migao', 'curtain', 'active')
  ON CONFLICT (id) DO NOTHING;

-- 默认角色（五岗：管理员/运营/客服 + 超管；角色码与 HR 用例对齐）
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
  ('role_admin', 1, '管理员', 'admin', '租户管理权限', 'active'),
  ('role_operator', 1, '运营', 'operator', '商品与订单运营', 'active'),
  ('role_customer_service', 1, '客服', 'customer_service', '客服工作台权限', 'active'),
  ('role_super_admin', 1, '超级管理员', 'super_admin', '平台级超管权限', 'active')
  ON CONFLICT (id) DO NOTHING;

-- ================================================
-- 工序库 / 工艺路线模板种子（V54，issue #4116 P0-2）
-- ================================================
-- 为什么 schema.sql 里也要有：本文件是**全新库的一次性 bootstrap**（CI/本地 docker 栈由
-- docker-entrypoint-initdb.d 执行），而 **MigrationRunner/Flyway 不在该栈运行** —— 只存在于
-- 迁移链的种子在新建库上并不存在（同第 11 节 bootstrap 对齐段的既有教训）。
-- 内容与 V54__seed_production_operations.sql 逐字同口径；三源漂移由测试守
-- （tests/unit_ci_workflows/test_production_catalog_seed.py：V54 ∪ V56 ↔ 本文件 ↔ routing.py 比对）。
-- 末 5 行（op-v56-*）来自 V56__seed_special_option_operations.sql（issue #4230 特殊选项 A′ 类新增工序）；
-- 本文件是**终态**（全新库一次性 bootstrap）⇒ 两个迁移的内容在此合并且**按 sort_order 连续**，
-- 迁移侧则由 V54（1..30）+ V56（31..35）两段拼成 —— 守卫按**名称 → 值**比对，不依赖行序。
-- 幂等：ON CONFLICT DO NOTHING（冲突目标 = V49 的部分唯一索引，均带 WHERE deleted = 0）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
VALUES
  ('op-v54-01', 1, '精裁-布', '裁剪', '布帘', '米', 0.4, FALSE, TRUE, 1, 'active'),
  ('op-v54-02', 1, '精裁-纱', '裁剪', '纱帘', '米', 0.4, FALSE, TRUE, 2, 'active'),
  ('op-v54-03', 1, '裁剪-布', '裁剪', '布帘', '米', 0.4, FALSE, FALSE, 3, 'active'),
  ('op-v54-04', 1, '裁剪-纱', '裁剪', '纱帘', '米', 0.4, FALSE, FALSE, 4, 'active'),
  ('op-v54-05', 1, '布三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 5, 'active'),
  ('op-v54-06', 1, '纱三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 6, 'active'),
  ('op-v54-07', 1, '韩褶-布', '车位', '布帘', '折', 0.4, FALSE, FALSE, 7, 'active'),
  ('op-v54-08', 1, '韩褶-纱', '车位', '纱帘', '折', 0.4, FALSE, FALSE, 8, 'active'),
  ('op-v54-09', 1, '上车布-布', '车位', '布帘', '米', 0.5, FALSE, FALSE, 9, 'active'),
  ('op-v54-10', 1, '上车布-纱', '车位', '纱帘', '米', 0.5, FALSE, FALSE, 10, 'active'),
  ('op-v54-11', 1, '打孔-布', '车位', '布帘', '孔', 0.15, FALSE, FALSE, 11, 'active'),
  ('op-v54-12', 1, '打孔-纱', '车位', '纱帘', '孔', 0.15, FALSE, FALSE, 12, 'active'),
  ('op-v54-13', 1, '拼1次-布', '车位', '布帘', '幅', 0.8, FALSE, FALSE, 13, 'active'),
  ('op-v54-14', 1, '拼2次-布', '车位', '布帘', '幅', 1.2, FALSE, FALSE, 14, 'active'),
  ('op-v54-15', 1, '拼3次-布', '车位', '布帘', '幅', 1.6, FALSE, FALSE, 15, 'active'),
  ('op-v54-16', 1, '花边-布', '车位', '布帘', '米', 0.6, FALSE, FALSE, 16, 'active'),
  ('op-v54-17', 1, '铅坠-布', '车位', '布帘', '米', 0.3, FALSE, FALSE, 17, 'active'),
  ('op-v54-18', 1, '接高-布', '车位', '布帘', '幅', 1.0, FALSE, FALSE, 18, 'active'),
  ('op-v54-19', 1, '帘头制作', '车位', '帘头', '个', 2.0, FALSE, FALSE, 19, 'active'),
  ('op-v54-20', 1, '熨烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 20, 'active'),
  ('op-v54-21', 1, '定型-布', '后道', '布帘', '米', 0.4, FALSE, FALSE, 21, 'active'),
  ('op-v54-22', 1, '复烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 22, 'active'),
  ('op-v54-23', 1, '布帘车被', '后道', NULL, '米', 0.4, FALSE, FALSE, 23, 'active'),
  ('op-v54-24', 1, '外帘打卷', '后道', '外帘', '套', 1.0, FALSE, FALSE, 24, 'active'),
  ('op-v54-25', 1, '外帘装袋', '后道', '外帘', '套', 1.0, TRUE, FALSE, 25, 'active'),
  ('op-v54-26', 1, '质检', '后道', NULL, '套', 1.5, FALSE, FALSE, 26, 'active'),
  ('op-v54-27', 1, '外帘发货', '后道', '外帘', '套', 1.0, FALSE, FALSE, 27, 'active'),
  ('op-v54-28', 1, '绑带-布', '其他', '布帘', '套', 0.5, FALSE, FALSE, 28, 'active'),
  ('op-v54-29', 1, '抱枕', '其他', NULL, '个', 2.0, FALSE, FALSE, 29, 'active'),
  ('op-v54-30', 1, '腰靠垫', '其他', NULL, '个', 2.0, FALSE, FALSE, 30, 'active'),
  ('op-v56-01', 1, '绑带-纱', '其他', NULL, '套', 0.5, FALSE, FALSE, 31, 'active'),
  ('op-v56-02', 1, 'logo条-布', '车位', NULL, '米', 0.6, FALSE, FALSE, 32, 'active'),
  ('op-v56-03', 1, '立边-布', '车位', NULL, '米', 0.5, FALSE, FALSE, 33, 'active'),
  ('op-v56-04', 1, '扣环-布', '车位', NULL, '个', 0.3, FALSE, FALSE, 34, 'active'),
  ('op-v56-05', 1, '防翘扣-布', '车位', NULL, '个', 0.2, FALSE, FALSE, 35, 'active')
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- 工艺路线模板种子（V54 的 6 条 + V58 的 3 条，issue #4246 的纱帘路线补齐）。
-- 守卫逐行比对口径：本文件 == V54 ∪ V58（见 tests/unit_ci_workflows/test_production_catalog_seed.py）。
INSERT INTO production_routings
    (id, tenant_id, curtain_type, craft, operations, status)
VALUES
  ('rt-v54-01', 1, '布帘', '韩褶',
   '["精裁-布","布三边","韩褶-布","上车布-布","熨烫-布","定型-布","复烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-02', 1, '布帘', '打孔',
   '["精裁-布","布三边","打孔-布","熨烫-布","定型-布","复烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-03', 1, '布帘', '四爪钩',
   '["精裁-布","布三边","上车布-布","熨烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-04', 1, '布帘', '穿杆',
   '["精裁-布","布三边","熨烫-布","布帘车被","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-05', 1, '纱帘', '韩褶',
   '["精裁-纱","纱三边","韩褶-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v54-06', 1, '帘头', '平幔',
   '["精裁-布","布三边","帘头制作","定型-布","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  -- 末 3 行（rt-v58-*）来自 V58__seed_sheer_curtain_routings.sql（issue #4246 补的 3 条纱帘路线，
  -- **零新造工序**：只消费库里早已存在、有价、零消费的 上车布-纱 / 打孔-纱）。本文件是终态 ⇒
  -- 与 V54 的 6 行写同一条 INSERT（V54 行在前、V58 行在后），守卫逐行比对时可依赖该行序。
  ('rt-v58-01', 1, '纱帘', '打孔',
   '["精裁-纱","纱三边","打孔-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v58-02', 1, '纱帘', '四爪钩',
   '["精裁-纱","纱三边","上车布-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v58-03', 1, '纱帘', '穿杆',
   '["精裁-纱","纱三边","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active')
ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING;

-- provenance 回填（V62，issue #4361）：与迁移 V62 逐条同口径 —— 按 **id 前缀**认领
-- （不是按名字列表，名字列表会随改名漂移），只动 `source IS NULL` 的行（幂等），
-- 其余行保持 NULL（未知来源 = 未知，不许冒充「占位待确认」）。
-- bootstrap 的种子 INSERT 不带 source 列 ⇒ 必须在此显式回填，否则新建库的 provenance 全为 NULL。
UPDATE production_operations
SET source = CASE
        WHEN id LIKE 'op-v54-%' THEN '占位待确认'
        WHEN id LIKE 'op-v56-%' THEN '推算'
    END
WHERE source IS NULL
  AND (id LIKE 'op-v54-%' OR id LIKE 'op-v56-%');

UPDATE production_routings
SET source = CASE
        WHEN id LIKE 'rt-v54-%' THEN '占位待确认'
        WHEN id LIKE 'rt-v58-%' THEN '推算'
    END
WHERE source IS NULL
  AND (id LIKE 'rt-v54-%' OR id LIKE 'rt-v58-%');

-- 单价版本回填（V55，issue #4204）：每条活跃工序一行初始版本 ⇒ 「当前价 = 最新版本行」对存量数据成立。
-- 必须放在工序库种子**之后**；幂等（已有版本行的工序跳过 + ON CONFLICT 兜底）。
INSERT INTO production_operation_price_versions (id, tenant_id, operation_id, unit_price, created_at)
SELECT 'pv-' || o.id, o.tenant_id, o.id, o.unit_price, NOW()
FROM production_operations o
WHERE o.deleted = 0
  AND NOT EXISTS (
      SELECT 1 FROM production_operation_price_versions v
      WHERE v.operation_id = o.id AND v.deleted = 0
  )
ON CONFLICT (id) DO NOTHING;

-- 特殊选项 → 条件工序 / 计件系数种子（V59，issue #4230 Java 侧 v1a）
-- 逐字抄自真值源 backend/ai-agent-service/app/production/routing.py 的 SPECIAL_OPTION_ROUTINGS
-- （16 项，sort_order 与真值源字典序一致）与 OPTION_FACTOR_SCOPES（v1 只种「一分为二 ⇒ ×1.7」这个
-- **实证**档；§2.4 的逐工序细算档是纯推算，不拿推算值覆盖实证值 ⇒ 不种）。
-- NON_PIECEWORK_OPTIONS（余料带回-布/-纱）**不种**：它们是显式登记的「不计件」。
-- ⚠️ 选项名 = **ERP 名**（issue #4389 裁定 R-e）：本文件是 bootstrap **终态**，直接写目标态
-- （bootstrap 路径不跑迁移链 ⇒ 不经过 V65 的改名）；存量库由
-- V65__align_special_option_names_with_erp.sql 改名对齐。
-- 防漂移：backend/admin-api/src/test/java/com/migao/admin/migration/ProductionOptionRoutingMigrationTest.java
-- 逐行比对本文件 / V59 ∪ V65 / routing.py 三源（改名/改值/加减选项即红）。
INSERT INTO production_option_routings
    (id, tenant_id, option_name, operation_name, after_operation, sort_order, status)
VALUES
  ('opt-rt-01', 1, '拼1次',      '拼1次-布',  '布三边',   1, 'active'),
  ('opt-rt-02', 1, '拼2次',      '拼2次-布',  '布三边',   2, 'active'),
  ('opt-rt-03', 1, '拼3次',      '拼3次-布',  '布三边',   3, 'active'),
  ('opt-rt-04', 1, '加花边',     '花边-布',   '布三边',   4, 'active'),
  ('opt-rt-05', 1, '加铅块',     '铅坠-布',   '布三边',   5, 'active'),
  ('opt-rt-06', 1, '接高',       '接高-布',   '精裁-布',  6, 'active'),
  ('opt-rt-07', 1, '双眼皮接高', '接高-布',   '精裁-布',  7, 'active'),
  ('opt-rt-08', 1, '余料做绑带', '绑带-布',   '布帘车被', 8, 'active'),
  ('opt-rt-09', 1, '布绑带',     '绑带-布',   '布帘车被', 9, 'active'),
  ('opt-rt-10', 1, '余料做帘头', '帘头制作',  '布三边',  10, 'active'),
  ('opt-rt-11', 1, '抱枕',       '抱枕',      '外帘打卷', 11, 'active'),
  ('opt-rt-12', 1, '纱绑带',     '绑带-纱',   '布帘车被', 12, 'active'),
  ('opt-rt-13', 1, '加logo条',   'logo条-布', '布三边',  13, 'active'),
  ('opt-rt-14', 1, '加立边',     '立边-布',   '布三边',  14, 'active'),
  ('opt-rt-15', 1, '扣环',       '扣环-布',   '布三边',  15, 'active'),
  ('opt-rt-16', 1, '防翘扣',     '防翘扣-布', '布三边',  16, 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_option_factors
    (id, tenant_id, option_name, operation_name, factor, source)
VALUES
  ('opt-fa-01', 1, '一分为二', NULL, 1.7, '实证')
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

-- AI 工具写审计的工具名（V52 / issue #4071：`action` 收敛为动词，工具名另置本列）。
-- 这里用 ADD COLUMN 而非写进上面 CREATE TABLE 的列清单，理由与本段其它条目一致 ——
-- 迁移链是结构变更的**事实源**，bootstrap 段只负责「终态对齐」（漂移即 CI block）。
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS tool_name VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tool_name ON audit_logs(tool_name);

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

-- 写请求幂等键表（V50，issue #4037 / F19）
-- ai-agent 的写请求带 X-Client-Request-Id，服务端按 (tenant_id, client_request_id) 去重：
-- 首次执行并把结果快照落库，同键重放不再执行（HTTP 客户端超时 25s < 工具超时 30s ⇒
-- 「已落库但报失败」的窗口客观存在，LLM 一重试就是重复下单 = 直接资金损失）。
-- 逐列与 V50__create_client_request_keys.sql 一致（含内联唯一约束与同款诊断索引）。
CREATE TABLE IF NOT EXISTS client_request_keys (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,               -- 租户隔离维度：去重键 = (tenant_id, client_request_id)
    client_request_id VARCHAR(128) NOT NULL, -- 幂等键，取自请求头 X-Client-Request-Id
    endpoint VARCHAR(128) NOT NULL,          -- 受理端点（如 POST /api/admin/agent/orders），诊断用
    response_payload JSONB,                  -- 首次执行成功后的响应快照；NULL = 已占位但尚无结果
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- 去重判据：同租户同键只允许一行。并发同键时第二个写入者被它挡住
    -- （INSERT ... ON CONFLICT DO NOTHING → 影响行数 0 ⇒ 判为「重复请求」）。
    UNIQUE (tenant_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS idx_client_request_keys_tenant_created
    ON client_request_keys (tenant_id, created_at DESC);

-- ================================================
-- END OF SCHEMA
-- ================================================
