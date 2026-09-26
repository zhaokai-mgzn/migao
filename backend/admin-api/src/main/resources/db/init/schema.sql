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
    -- 员工登录用户名（V128，issue #5485）：员工用「<username>@<tenants.code> + 密码」登录。
    -- NULL = 存量行 / 管理员尚未补设（**不自动迁移、不自动生成**；补设前无法登录是预期行为）。
    username VARCHAR(64),
    -- 工人工号（V98，issue #4733）：非 NULL = 该行是**工人档案**（role=worker）；
    -- NULL = 商家用户（本列引入前的全部存量行）。租户内唯一（部分唯一索引见下）。
    worker_no VARCHAR(64),
    session_ttl INTEGER DEFAULT 3600,
    status VARCHAR(32) DEFAULT 'active',
    -- 首登强制改密（V128，issue #5485）：管理员设的初始密码必须首登改掉。
    -- 默认 FALSE ⇒ 存量行与「未设密码」的账号不受影响。
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_users_tenant_worker_no
    ON users (tenant_id, worker_no)
    WHERE worker_no IS NOT NULL AND deleted = 0;
-- 员工用户名唯一性**只到租户内**（issue #5485 不变式 I3）：不同企业可同名；跨企业不串号靠
-- 登录时的「tenantCode → tenant_id → WHERE tenant_id=? AND username=?」定位，绝不跨租户兜底（I1）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_users_tenant_username
    ON users (tenant_id, username)
    WHERE username IS NOT NULL AND deleted = 0;

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
    stock NUMERIC(12,1) DEFAULT 0,                         -- 库存数量（米，V115/#5063：1 位小数 = 0.1 米粒度）；派生冗余列，权威是 product_skus.stock 汇总
    stock_warning_threshold INTEGER DEFAULT 10,
    status VARCHAR(32) DEFAULT 'active',
    -- 计价单位（来自 011_product_unit.sql）
    unit VARCHAR(32) DEFAULT '件',
    -- 计价方式：per_meter / per_piece / fixed / per_area
    pricing_type VARCHAR(30) DEFAULT 'per_meter',
    -- SKU 矩阵相关字段（来自 008_product_sku_matrix.sql）
    sku_code VARCHAR(30),
    stock_deduction_mode VARCHAR(20) DEFAULT 'on_order',  -- on_order(拍下减) / on_payment(付款减)
    sales_count NUMERIC(12,1) DEFAULT 0,                   -- 累计销量（V115/#5063）
    sales_amount DECIMAL(12,2) DEFAULT 0,                  -- 累计销售额
    edited_by VARCHAR(50),                                  -- 最后编辑人
    edited_at TIMESTAMP WITH TIME ZONE,                     -- 最后编辑时间
    -- 商家推荐标记（来自 V20260903__add_product_recommended.sql）
    recommended BOOLEAN DEFAULT FALSE,                       -- 是否商家推荐（C 端新品推荐位展示依据）
    -- 退货回补库存开关（来自 V33__add_allow_return_restock.sql）
    allow_return_restock BOOLEAN DEFAULT FALSE,              -- 是否允许退货回补库存（窗帘行业定制退货不可再售，默认不回补）
    -- 售卖方式基础属性（商品级，**非** SKU 组合维度）+ 1 卷多少米（来自 V113，用户裁定 2026-09-21）
    selling_methods JSONB DEFAULT '["bulk_cut", "full_roll"]'::jsonb,  -- 该货号支持哪些售卖方式（bulk_cut 散剪 / full_roll 整卷）
    roll_length_m NUMERIC(8,2),                              -- 1 卷 = 多少米（货号级基础参数）；NULL = 未配置 ⇒ 禁止推算整卷分配
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

COMMENT ON COLUMN products.stock IS '库存数量';
-- 🔴 issue #5245 C1：V51 的注释称这两列「无消费方」—— **与代码事实相反**，两列都被
-- admin-web 商品页真实读取（见 V126 的 COMMENT 纠正，两条路径同文案）。
COMMENT ON COLUMN products.stock_warning_threshold IS '库存预警阈值';
COMMENT ON COLUMN products.sku_code IS '商品货号';
COMMENT ON COLUMN products.stock_deduction_mode IS '库存扣减模式: on_order / on_payment';
COMMENT ON COLUMN products.sales_count IS '累计销量';
COMMENT ON COLUMN products.sales_amount IS '累计销售额';
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
    door_width VARCHAR(20) NOT NULL,                      -- 规格尺寸: 2.8m / 3.2m / 3.4m
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    stock NUMERIC(12,1) NOT NULL DEFAULT 0,                -- 库存数量（米，V115/#5063：1 位小数 = 0.1 米粒度）—— SKU 级是唯一权威（#4038）
    sku_code VARCHAR(50),
    sales_count NUMERIC(12,1) NOT NULL DEFAULT 0,          -- SKU 累计销量（V115/#5063：与 stock 同源，同笔单据口径必须一致）
    -- 成本（来自 V111，issue #5034「成本核算一起做」）：移动加权平均
    avg_cost NUMERIC(12,4),                                -- 移动加权平均单位成本；NULL = 未知（存量不回填、不猜 0）
    cost_amount NUMERIC(16,4),                             -- 库存成本金额 = stock * avg_cost；NULL = 成本未知
    latest_batch_no VARCHAR(32),                           -- 最近一次入库的批次号 PC-yyyyMMdd-NNNN；NULL = 从未入库
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_product_skus_tenant_product ON product_skus(tenant_id, product_id);
-- 组合只有 颜色 × 门幅（V113：售卖方式已上移为商品级基础属性 products.selling_methods）
ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination
    UNIQUE (product_id, color_id, door_width);
COMMENT ON TABLE product_skus IS 'SKU矩阵表，组合 = 颜色 × 门幅（仅此二维）';
COMMENT ON COLUMN product_skus.avg_cost IS '移动加权平均单位成本（元/单位，V111）。NULL = 未知（存量库存无成本真值来源，一律不回填、不猜 0）';
COMMENT ON COLUMN product_skus.cost_amount IS '库存成本金额 = stock * avg_cost（V111，派生冗余列）。NULL = 成本未知（不得用 0 冒充「成本为零」）';
COMMENT ON COLUMN product_skus.latest_batch_no IS '最近一次入库的批次号（V111，系统生成的 PC-yyyyMMdd-NNNN）；NULL = 从未入库过';

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
    -- issue #4882（用户裁定）：`pricing_method` / `unit_price` 两列已删除（V101 落迁移链；
    -- 本文件是全新库 bootstrap，故直接是**终态**，不写这两列）。
    unit VARCHAR(16) DEFAULT '米',   -- 加工数量单位（不再是「计价单位」）
    min_quantity INTEGER DEFAULT 1,
    max_quantity INTEGER DEFAULT 999,
    description TEXT,
    options JSONB DEFAULT '[]',  -- 加工选项（如打孔：纳米圈/四爪钩/韩式S钩）
    processing_days INTEGER DEFAULT 1,
    ai_recommended BOOLEAN DEFAULT true,
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

-- ⚠️ 原 `processing_rules`（「加工组合规则表：互斥/必选/可选/可叠加」）已**删表**
-- （issue #5245 A5，2026-09-23 用户裁定「删表」）：全仓零代码引用（Java 实体/Mapper/DTO/Service
-- 与 Python/前端 types 全无；V68 头注释早已登记 KNOWN-03「表在、全仓 0 代码引用」）——
-- 保留它 = 让「加工项可组合性」看起来已经实现。存量库由 `V126__drop_zombie_db_objects.sql`
-- 幂等 DROP TABLE（含索引与 RLS 策略）；新建库由本文件不再建表。
-- 「加工费组合」的真值源是 `processing_fee_combinations`（V68）——它把「组合」做成了**计价**口径，
-- 与这张从未落码的「组合校验」表不是同一个概念（勿混为一谈）。

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

    -- 默认收货信息（issue #4419，V70 迁移；客户管理「收货信息」卡片）
    default_receiver_name VARCHAR(100),  -- 默认收货人姓名（新增订单选客户自动带出）
    default_receiver_phone VARCHAR(20),  -- 默认收货人电话（新增订单选客户自动带出）
    default_receiver_address TEXT,  -- 默认收货详细地址（单字段文本，与 orders.customer_address 同口径）

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
    -- ⚠️ 原 `payment_status` / `stock_deducted`（来自 008_product_sku_matrix.sql）已**删列**
    -- （issue #5245 A2/A3，2026-09-23 用户裁定）：全仓零读取点（Java 实体无映射、两条 SQL 链无写点）
    -- ⇒ 「列在但无人读」= 第二份会漂移的真相。存量库由 `V126__drop_zombie_db_objects.sql` 幂等
    -- DROP COLUMN；新建库由本文件不再建列。
    -- 支付与扣库存的真值源不在 orders 上（支付走 tenant_payment_qrcodes + 订单状态机，
    -- 库存走 stock_ledger / stock_batch_consumptions）。
    -- 来自 010_order_follow_status.sql
    follow_status VARCHAR(20) DEFAULT 'pending',    -- 跟进状态: pending/following/completed
    -- 来自 V20260901__add_order_user_id.sql
    user_id VARCHAR(64),                            -- 下单用户ID（users.id，C 端数据隔离依据）
    -- 来自 V100__add_order_logistics_columns.sql（issue #4872）
    logistics_type VARCHAR(16),                     -- 收货物流类型：express 快递 / logistics 物流专线（与 order_logistics.logistics_type 同词表）；NULL = 建单未传（不猜，与下单页「未指定」同口径）
    logistics_company VARCHAR(128),                 -- 收货物流/快递公司；NULL = 建单未传（不猜）
    -- 来自 V120__order_urgency_and_required_delivery_date.sql（issue #5177）
    is_urgent BOOLEAN NOT NULL DEFAULT FALSE,       -- 订单级加急标记：true = 插队、不进池、立刻单派（pooled=false）；与售后工单 priority 不共享来源、不联动（用户裁定「加急不能跟售后工单绑定」）。NOT NULL ⇒ 无第三态，「未标加急」与「明确不加急」同值
    required_delivery_date DATE,                    -- 客户要求到货日；NULL = 未指定（不猜、不回填）。DATE 而非 TIMESTAMP —— 只有日期精度的事实不该带时刻。消费者 = 池看板排序（到货日升序、NULL 排最后）
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
    -- 售卖方式偏好 + 优先整卷发货的分配结果（V113，用户裁定 2026-09-21；
    -- 例：买 100 米、一卷 60 米 ⇒ roll_count=1、整卷 60 米 + 散剪 40 米）
    selling_method VARCHAR(20),                     -- 本行售卖方式：bulk_cut(散剪) / full_roll(整卷)；NULL = 下单未指定（不猜）
    roll_count INTEGER,                             -- 发出的整卷数（= floor(quantity / roll_length_m)）；NULL = 未要求整卷或货号未配卷长
    roll_length_m NUMERIC(8,2),                     -- 下单时货号「1 卷 = 多少米」的快照（订单是快照不是视图）
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
    route_source VARCHAR(16),                         -- 路线键来源（V60 issue #4308 + V130 补齐第 5 态）：direct 帘种与工艺直读订单显式列 order_items.curtain_type/craft（issue #4354/#4362，不查信号映射表，与 derived 同档）/ derived 两维均由库中信号命中且路线存在 / partial 只命中一维（补信号）/ missing_route 派生键库中无路线（建路线）/ default 两维全不命中（补信号）
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
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,   -- 历史载体：必完概念已退场（#4961：完工 = 全部工序全绿），值恒 FALSE
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
-- 工序作用域（V67，issue #4384 A1）：position = 部位级（默认，每部位一次）/ set = 套级（**每樘窗一次**）。
-- 真值源 docs/curtain-production-rules.md §8：**外帘**是加工单打印行部位、**不是**路线键；
-- 但 V54/V58 种子把 外帘打卷/外帘装袋/外帘发货 逐条写进每一条部位路线（含纱帘）⇒ 一樘「布 + 纱」
-- 时这 3 道各实例化 2 次（unit='套'、qty=1）⇒ 各 ¥1.0 双付。用户裁定 2026-09-19：
-- 套级先按「每樘窗一次」实现，打卷是否每帘一次留成可配。
-- 本段是 bootstrap 终态（本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无该列 ⇒ 读面 500，同 #3270 形态）。
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'position';
COMMENT ON COLUMN production_operations.scope IS
    '工序作用域（V67，issue #4384 A1）：position = 部位级（默认，每部位一次）/ '
    'set = 套级（每樘窗一次）。真值源 docs/curtain-production-rules.md §8：外帘是加工单打印行部位、'
    '不是路线键 ⇒ 外帘打卷/外帘装袋/外帘发货 这三道是套级（一樘「布 + 纱」只做一次，'
    '此前因逐条出现在布帘与纱帘两条路线里而各实例化 2 次、各 ¥1.0 双付）。'
    '用户裁定 2026-09-19：套级先按「每樘窗一次」实现，打卷是否每帘一次留成可配。'
    '⚠️ 去重消费方（A2，ProcessingOrderService.buildPositionPayload）不在 #4384 A1 包内，'
    '本列当前只是标记 + 可配口径。';

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

-- ── 工序路线模型重构 P1 的三张新表（V71，issue #4427 = 母单 #4423 P1/3）──
-- 角色：9 条「(部位 × 工艺) 展开路线」收敛为「1 条具名主线 + 规则表 + 部位价目」。
-- ⚠️ **纯增量**：旧表 production_operations / production_routings 的列、行、索引**一字不动**
--    （新路线不能写进 production_routings：它的 curtain_type/craft 是 NOT NULL，且唯一索引
--    uk_production_routings_tenant_type_craft 会与既有 布帘×韩褶 行直接冲突）。
-- 本段是 bootstrap 终态（本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无这三张表 ⇒ P2 切换后读面直接 500，同 #3270 形态）。
-- 逐列与 V71__normalize_routing_model_structure.sql 一致；种子见本文件末尾的种子段。
CREATE TABLE IF NOT EXISTS production_operation_positions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL,                -- 逻辑工序名（去部位后缀：精裁/三边/韩褶…）
    position VARCHAR(16) NOT NULL,                    -- 部位：布帘/纱帘/帘头/布料（第 4 个部位，V79 / #4529）
    unit_price NUMERIC(10,2),                         -- 计件单价（元/单位）；NULL = 该部位明确不做（不报价）
    applicable BOOLEAN NOT NULL DEFAULT TRUE,         -- 该部位是否做这道工序；false = 明确不做（≠「没定价」）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position)
    WHERE deleted = 0;

CREATE TABLE IF NOT EXISTS production_route_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,                       -- 路线总名（用户可命名；M3：只改总名，工序名不能改）
    is_default BOOLEAN NOT NULL DEFAULT FALSE,        -- 回落链终点；每租户活跃路线中恰好一条
    positions JSONB NOT NULL DEFAULT '[]'::jsonb,     -- 适用帘种集合，如 ["布帘","纱帘","帘头"]
    mainline JSONB NOT NULL DEFAULT '[]'::jsonb,      -- 主线有序工序名（逻辑名，不展开工艺变体）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_name
    ON production_route_templates (tenant_id, name)
    WHERE deleted = 0;
-- 不变式 I2：每租户活跃路线中恰好一条 is_default（部分唯一索引 ⇒ 第二条默认插不进来）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_default
    ON production_route_templates (tenant_id)
    WHERE is_default AND deleted = 0;

CREATE TABLE IF NOT EXISTS production_route_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(24) NOT NULL CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item', 'position')),
    trigger_value VARCHAR(64) NOT NULL,               -- 工艺名 / 特殊选项名（逐字 = ERP 写法；它是 join key）
    position VARCHAR(16),                             -- 部位限定；NULL = 不限
    action VARCHAR(16) NOT NULL CHECK (action IN ('insert', 'remove', 'factor')),
    operation VARCHAR(64),                            -- 逻辑工序名（增/删/覆盖系数的那一道）；factor 平摊档 = NULL
    after_operation VARCHAR(64),                      -- insert 锚点（逻辑工序名）；NULL = 追加末尾
    priority INTEGER NOT NULL DEFAULT 100,            -- 升序生效（同序按声明顺序）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                              COALESCE(position, ''), action, COALESCE(operation, ''))
    WHERE deleted = 0;

-- ── 工序路线模型重构 P2（V72，issue #4432 = 母单 #4423 P2/3）──
-- ① 规则表补 `factor`（计件系数档：旧 OPTION_FACTOR_SCOPES 的「一分为二 → ×1.7」必须有地方存；
--    **不允许**把系数留在旧 production_option_factors —— 那就是第二份口径）；
-- ② `action` CHECK 放宽为含 'factor'；`operation` 改为可空（平摊档 = operation IS NULL）；
-- ③ insert/remove 的 operation 仍必填（兜底 CHECK）；
-- ④ `production_crafts` = 商户级**默认工艺**：重构后路线模板**没有工艺维** ⇒ 缺 `craft` 时
--    「从默认路线取对应维」**在实现上不成立**（母单 #4423 评论「🔴 规格订正」）⇒ 改为
--    一次配置、全局确定的商户级默认工艺（不依赖每单的字符串匹配，不写死常量 韩褶）。
-- 本段是 bootstrap 终态（本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无该列/表 ⇒ 读面 500，同 #3270 形态）。
ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS factor NUMERIC(6,3);
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_action_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_action_check
    CHECK (action IN ('insert', 'remove', 'factor'));
ALTER TABLE production_route_rules ALTER COLUMN operation DROP NOT NULL;
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_operation_required_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_operation_required_check
    CHECK (action = 'factor' OR operation IS NOT NULL);
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_factor_present_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_factor_present_check
    CHECK (action <> 'factor' OR factor IS NOT NULL);
COMMENT ON COLUMN production_route_rules.factor IS
    '计件系数档的系数值（V72，issue #4432 = 母单 #4423 P2 搬入）。'
    '⚠️ 自 issue #4589（用户裁定 2026-09-19「计件工资 = 数量 × 计件单价，不需要考虑系数」）起'
    '**已无消费者**：算法侧 factor_for / applyFactors 已删除，本表 action = ''factor'' 的活跃行'
    '由 V87 软删（deleted = 1，留痕不物理删）。列**保留**：历史工序实例快照'
    '（processing_position_operations.factor）与历史报工（production_work_logs.factor）上的值是'
    '当时工资的证据 ⇒ 历史不回溯、不重算（本列**不**参与任何计算）。';
COMMENT ON COLUMN production_route_rules.operation IS
    '要增/删/覆盖系数的**逻辑工序名**（与 OPERATION_LOGICAL_NAMES 值域一致）。'
    'V72 起**可空**：action = ''factor'' 且 operation IS NULL = **平摊档**（该触发对该部位全部工序生效）。'
    'action = ''insert''/''remove'' 时仍必填（由 production_route_rules_operation_required_check 保证）。';

-- ── 特殊选项**对客按套单价**（V77，issue #4525；设计 docs/design/processing-fee-and-option-pricing.md §4.1）──
-- bootstrap 终态：本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无该列 ⇒ 取价读不到 ⇒ 所有特殊选项静默按 0 收（同 #3270 形态）。
ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS customer_unit_price NUMERIC(12,2);
COMMENT ON COLUMN production_route_rules.customer_unit_price IS
    '特殊选项（trigger_kind=''option'' 行）对**顾客**的**元/套**单价 —— **对客售价账**（L3②）。'
    'NULL = **未定价**（≠ 0）：取价侧必须显式可见（special_options[].priced=false + 可行动 hint），'
    '不得静默按 0 收。非 option 行一律 NULL（工艺变体不按套收费）。'
    '⚠️ **计件路径绝不读本列**：ProductionService / piecework 与 production_operations.unit_price '
    '是给工人付的成本账，与本列（对客售价）两套账不互读；列名的 customer_ 前缀即为让该纪律在 grep 层可判。'
    'issue #4525（设计 docs/design/processing-fee-and-option-pricing.md §4.1）。';

CREATE TABLE IF NOT EXISTS production_crafts (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,                       -- 工艺名（逐字 = ERP 写法；与规则表 trigger_value 同词表）
    is_default BOOLEAN NOT NULL DEFAULT FALSE,       -- 商户级默认工艺；每租户活跃行中**恰好一条**
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_crafts_tenant_name
    ON production_crafts (tenant_id, name)
    WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_crafts_tenant_default
    ON production_crafts (tenant_id)
    WHERE is_default AND deleted = 0;
COMMENT ON TABLE production_crafts IS
    '工艺词表 + **商户级默认工艺**（V72，issue #4432 = 母单 #4423 P2）。'
    '存在的理由（规格订正）：重构后路线模板**没有工艺维**（工艺已降为 production_route_rules 的触发键）'
    '⇒ 缺 `craft` 时「从默认路线取对应维」**在实现上不成立**。而工艺决定「插入哪道工序 + 计件系数」'
    '⇒ 猜错 = 算错工人工资。⇒ 改为**一次配置、全局确定**的商户级默认工艺。';
COMMENT ON COLUMN production_crafts.is_default IS
    '商户级默认工艺标记（V72，issue #4432）：缺 `craft` 时的兜底来源。'
    '不变式：每租户活跃工艺中**恰好一条**（部分唯一索引 uk_production_crafts_tenant_default 保证 ≤1）。'
    '⚠️ 缺默认工艺时**不得静默取常量**：要么 fail-closed，要么取种子默认值 + 在 route_source 上显式标记。';

-- ── 算料公式**租户级配置**（V80，issue #4528 = 包 E；设计 docs/design/craft-calc-and-fabric-routing.md §4.2）──
-- bootstrap 终态：本文件由 docker-entrypoint-initdb.d 执行，**迁移链不在该栈运行**
-- ⇒ 只写迁移 = 新建库无该表 ⇒ 配置读写端点 500（同 #3270 形态，不是账面问题）。
-- ⚠️ **不插种子行**：缺行 = 用引擎默认值（`source='default'`）—— 默认值唯一来源是算料引擎
-- `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`，库里再种一份 = 第二份会漂的默认值。
-- ⚠️ 列名与引擎配置键**逐字同名**（读写零映射）；**没有** `default_fabric_width`
-- （设计文档 §4.2 的提案键，包 D 实现里不存在 ⇒ 以实现为准，见迁移 V80 头注释）。
CREATE TABLE IF NOT EXISTS craft_calc_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    per_fold_single NUMERIC(6,3) NOT NULL DEFAULT 0.25,
    per_fold_mixed_times JSONB NOT NULL DEFAULT '{"1": 0.65, "2": 1.2}'::jsonb,
    margin_single NUMERIC(6,3) NOT NULL DEFAULT 0.2,
    margin_multi NUMERIC(6,3) NOT NULL DEFAULT 0.3,
    min_fullness NUMERIC(6,3) NOT NULL DEFAULT 1.5,
    tiers JSONB NOT NULL DEFAULT
        '{"standard": {"fullness": 2.0, "label": "标准工艺"}, "economy": {"fullness": 1.8, "label": "经济工艺"}}'::jsonb,
    default_formula VARCHAR(16) NOT NULL DEFAULT 'pleat',
    hem_margin NUMERIC(6,3) NOT NULL DEFAULT 0.3,
    meters_rounding_step NUMERIC(6,3) NOT NULL DEFAULT 0.1,
    oversize_width_threshold NUMERIC(6,3) NOT NULL DEFAULT 6,
    oversize_height_threshold NUMERIC(6,3) NOT NULL DEFAULT 4,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
-- 租户级**单行**（部分唯一索引：软删行不占位）
CREATE UNIQUE INDEX IF NOT EXISTS uk_craft_calc_configs_tenant
    ON craft_calc_configs (tenant_id)
    WHERE deleted = 0;
COMMENT ON TABLE craft_calc_configs IS
    '算料公式**租户级配置**（V80，issue #4528 = 包 E）。单行/租户，**缺行 = 用引擎默认值**'
    '（source=''default''）—— 不做开租播种：默认值唯一来源是算料引擎 '
    'curtain_calc.DEFAULT_CRAFT_CALC_CONFIG（GET /api/internal/production/craft-calc-config）。';
COMMENT ON COLUMN craft_calc_configs.per_fold_single IS
    '单色每折吃布（米）。引擎默认 0.25。护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。';
COMMENT ON COLUMN craft_calc_configs.per_fold_mixed_times IS
    '拼色「拼次 → 每折吃布（米）」映射（JSONB，键 = 正整数拼次的**字符串形态**）。'
    '护栏：非空、键为正整数、值 > 0；未登记拼次不得静默退回单色系数（少算用料）。';
COMMENT ON COLUMN craft_calc_configs.min_fullness IS
    '褶倍下限（护栏，行业美学红线）。引擎默认 1.5。**可配但不可关**：写面护栏要求 >= 引擎默认值。';
COMMENT ON COLUMN craft_calc_configs.tiers IS
    '工艺档位（JSONB：{档位名: {fullness, label}}）。护栏：非空、每档 fullness > 0 且 >= min_fullness。';
COMMENT ON COLUMN craft_calc_configs.default_formula IS
    '兜底用料公式：pleat（韩褶公式＝褶数法，默认）/ fullness（褶倍数公式＝倍数法）。'
    '⚠️ 只是**工艺推导表缺失时的兜底**（韩褶/打孔由 craft 推导），不是恒定生效的默认值。';
COMMENT ON COLUMN craft_calc_configs.hem_margin IS
    '高方向**上下卷边**合计（米；脚位+止口），引擎默认 0.3（V110，issue #4976 包 1b）。'
    '护栏：必须 > 0。消费点：定高可行性 / 定宽买高每幅长 / 折数法 / 罗马帘（**几何层**）。'
    '⚠️ issue #5130 起它**不再**参与自动特征「超高」的判定（那条门幅判据已退役）；'
    '⚠️ 宽方向**没有**余量（订单宽 = 净窗宽 ⇒ 成品宽 = 净窗宽；`side_margin` 已随 issue #5030 退场）。';
COMMENT ON COLUMN craft_calc_configs.meters_rounding_step IS
    '用料米数**向上进位**步长（米），引擎默认 0.1。护栏：必须 > 0（截断/四舍五入 = 抹零）。';
COMMENT ON COLUMN craft_calc_configs.oversize_width_threshold IS
    '**超宽**阈值（净窗宽，米），引擎默认 6（V114，issue #5130；= 常量 OVERSIZE_WIDTH_THRESHOLD）。'
    '判据：净窗宽 > 本值 ⇒ 特征名「超宽」（进加工费组合键 = 工艺分档，用户裁定 D1）。'
    '护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。'
    '⚠️ 与**几何层**（门幅 / 褶倍 ⇒ 分幅与用料）是两件事，不得混用。';
COMMENT ON COLUMN craft_calc_configs.oversize_height_threshold IS
    '**超高**阈值（净窗高，米），引擎默认 4（V114，issue #5130；= 常量 OVERSIZE_HEIGHT_THRESHOLD）。'
    '判据：净窗高 > 本值 ⇒ 特征名「超高」（进加工费组合键）。'
    '护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。'
    '⚠️ issue #5130 起「超高」**不再**由「成品高 + 上下卷边 > 门幅」判定（该门幅判据已退役）。';
COMMENT ON COLUMN craft_calc_configs.status IS
    '配置行状态（范式同 production_crafts，V72）。读面按 deleted = 0 取行，不按 status 过滤。';

-- ── 企业参数**变更留痕**（V131，issue #5131 §22 P6；设计 docs/design/tenant-params-center.md §6.3）──
-- bootstrap 终态同步（同 V127 纪律）：新建库由本文件建表、**不跑迁移链** ⇒ 只写迁移 = 新建库缺表。
-- **只追加**：一行 = 一个参数键的一次变更（谁 / 何时 / 哪个域哪个键 / 改前 → 改后 / 属于哪一次保存）。
-- 口径 = **best-effort**（用户 2026-09-26 裁定）：审计写失败只记日志 + 计数，**不让配置保存失败**
-- ⇒ 本表**不在**配置写入的事务里（残留「改了钱、查不到谁改的」由日志行 PARAM_AUDIT_WRITE_FAILED
-- 与指标 migao.tenant_param_audit.write_failed 兜可观测性）。
CREATE TABLE IF NOT EXISTS tenant_param_audit (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    param_domain VARCHAR(32) NOT NULL,               -- craft_calc（算料，当前唯一写面）；增量 2 的六域按同名列追加取值
    param_key VARCHAR(64) NOT NULL,                  -- 引擎配置键（如 hem_margin）；不做白名单（键集随引擎演进）
    old_value TEXT,                                  -- NULL = 该键此前**没有**存储值（本租户当时在用引擎默认值）
    new_value TEXT,
    actor_id VARCHAR(64),                            -- 取不到认证上下文 ⇒ NULL + actor_source='unknown' + 原因（不编用户）
    actor_name VARCHAR(64),
    actor_source VARCHAR(16) NOT NULL,               -- security_context（权威）/ unknown
    actor_unknown_reason VARCHAR(64),
    operation VARCHAR(32) NOT NULL,                  -- put（全量替换）
    operation_id VARCHAR(64) NOT NULL,               -- 一次保存的身份：同一次 PUT 的多行共享（日志行里也打它）
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    -- 一行 = 一次变更：两个值不得相同（同值行 = 噪音，且会让「改过没有」判错）
    CONSTRAINT ck_tenant_param_audit_changed CHECK (old_value IS DISTINCT FROM new_value),
    CONSTRAINT ck_tenant_param_audit_source CHECK (actor_source IN ('security_context', 'unknown')),
    -- 🔴 「不知道是谁」必须带原因：两个条件同真同假
    CONSTRAINT ck_tenant_param_audit_unknown
        CHECK ((actor_source = 'unknown') = (actor_unknown_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_tenant_param_audit_key
    ON tenant_param_audit (tenant_id, param_domain, param_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_param_audit_operation
    ON tenant_param_audit (tenant_id, operation_id);
COMMENT ON TABLE tenant_param_audit IS
    '企业参数变更留痕（V131，issue #5131 P6，**只追加**）：一行 = 一个参数键的一次变更'
    '（谁 / 何时 / 哪个域哪个键 / 改前→改后 / 属于哪一次保存）。口径 = **best-effort**'
    '（用户 2026-09-26 裁定）：审计写失败只记日志 + 计数，**不让配置保存失败**';
COMMENT ON COLUMN tenant_param_audit.old_value IS
    '改前值。NULL = 该键此前**没有**存储值（本租户当时在用引擎默认值）—— 不是「值是空」；'
    '配置行本身不存在时（首次保存）本列全为 NULL';
COMMENT ON COLUMN tenant_param_audit.actor_source IS
    '身份**是怎么确定的**（同 worker_report_audits.identity_source 的口径）：'
    'security_context = 取自 SecurityContext 的 SecurityUser（权威，body 伪造不了）；'
    'unknown = 无认证上下文（服务令牌 / 定时任务 / 测试），此时 actor_id/actor_name 为 NULL 且 actor_unknown_reason 必非空';
COMMENT ON COLUMN tenant_param_audit.actor_unknown_reason IS
    '为什么归因不了（仅 actor_source=''unknown'' 时非空）：如 no_authentication_context —— '
    '如实记「未知 + 原因」，**不得**编一个用户或写成 system 冒充归属';
COMMENT ON COLUMN tenant_param_audit.operation_id IS
    '一次保存的身份：同一次 PUT 写下的多行共享它（应用侧同时把该 id 打进配置写入的日志行 ⇒ 日志 ↔ 账本可对账）';

CREATE TABLE IF NOT EXISTS processing_position_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    position_name VARCHAR(32) NOT NULL,              -- 部位：布帘/纱帘/帘头/外帘
    order_item_id VARCHAR(36),                       -- 主定位键（V69，issue #4388）：指向 order_items.id；NULL = 存量行（无法可靠回填）⇒ 读面按 position_name 兜底分组
    position_kind VARCHAR(16),                       -- 部位种类（V69）：布帘/纱帘/帘头（= 快照 curtainType）；NULL = 存量行
    seq INT NOT NULL DEFAULT 0,                      -- 部位内工序顺序
    operation_name VARCHAR(64) NOT NULL,
    group_name VARCHAR(16),
    unit VARCHAR(16),
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,            -- 应做数量（算料引擎输出）
    qty_source VARCHAR(32),                          -- 应做数量的口径来源（V57，issue #4208）：键名=算料输出 / <键名>_x6=每米6孔估算 / fallback=真兜底1
    -- 实例快照单价（V90，issue #4696）：NULL = **未定价**（≠ 0 元，0 是显式定价为 0 元）。
    -- 实例化侧**不得**回落工序库行价（production_operations.unit_price 是 NOT NULL DEFAULT 0
    -- ⇒ 回落会把「未定价」变成「真 0 元」，工人白干且无人知道）。
    unit_price NUMERIC(10,2),
    factor NUMERIC(6,2) NOT NULL DEFAULT 1,          -- 特殊选项计件系数（一分为二 ×1.7，ERP 名；issue #4389）
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,   -- 历史载体：必完概念已退场（#4961）；实例快照一律不写该列
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending 待做 / in_progress 进行中（C 模式预留，V92）/ done 已报工
    done_qty NUMERIC(12,2) NOT NULL DEFAULT 0,       -- 合格累计数量（返工/报废不累加）
    -- 套归属 + A/C 模式时序（V92，issue #4698）：全部可空，存量行留空（与 V69 的 order_item_id 同款「不猜」）
    set_id VARCHAR(64),                              -- 指向 processing_order_sets.id；NULL = 本列引入前的存量行
    set_no VARCHAR(64),                              -- 套号快照 = {processing_order_no}-{pad3(set_index)}；NULL = 存量行
    done_at TIMESTAMP WITH TIME ZONE,                -- 完成时刻（A 模式唯一必需的新增时序列；不得用 updated_at 冒充）
    worker_id VARCHAR(64),                           -- 报工人 id（C 模式预留，A 模式默认路径不读不写）
    worker_name VARCHAR(64),                         -- 报工人姓名（C 模式预留）
    started_at TIMESTAMP WITH TIME ZONE,             -- 开工时刻（C 模式预留）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_position_operations_po
    ON processing_position_operations (processing_order_id, position_name, seq)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_position_operations_order_item
    ON processing_position_operations (processing_order_id, order_item_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_position_operations_tenant
    ON processing_position_operations (tenant_id, status);
-- 卡点报表索引（V92，issue #4698 设计 §11.2 ⑥）：A 模式「没开工」判据 = pending + 立即前道 done + 等待时长
CREATE INDEX IF NOT EXISTS idx_position_operations_status_done
    ON processing_position_operations (tenant_id, status, done_at);

-- 套号载体（V92，issue #4698 / 设计 §2.2）：一个加工单 × 一套 = 一行；一套 = 一樘窗（craftLineId 组）
CREATE TABLE IF NOT EXISTS processing_order_sets (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    set_index INT NOT NULL,                          -- 一樘窗在本加工单里的次序（1 起，只增不复用：软删行仍占号）
    set_no VARCHAR(64) NOT NULL,                     -- {processing_order_no}-{pad3(set_index)}（落库冗余：码里印的是它）
    craft_line_id VARCHAR(64),                       -- 樘窗组键（= 快照 craftLineId，缺省 = 主布行 itemId）；可空
    position_item_ids JSONB NOT NULL DEFAULT '[]',   -- 本套的部位行 order_items.id 数组（有序）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_order_sets_index
    ON processing_order_sets (tenant_id, processing_order_id, set_index)
    WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_order_sets_no
    ON processing_order_sets (tenant_id, set_no)
    WHERE deleted = 0;

-- 部位码载体（V92，issue #4698 / 设计 §2.3）：一部位一码（一樘窗 ≤3~4 码）；载体是 token，工序不进码
CREATE TABLE IF NOT EXISTS processing_set_part_tokens (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    set_id VARCHAR(64) NOT NULL REFERENCES processing_order_sets(id),
    order_item_id VARCHAR(36) NOT NULL,              -- 部位行（一部位一码）
    position_kind VARCHAR(16),
    token VARCHAR(64),                               -- 32 位 UUID 去横线；撤销 = 置 NULL（不换新 token）
    short_code CHAR(8),                              -- 人可读短码（V99，issue #4802）：8 位 Crockford Base32、随机、全局唯一；印刷品写 /s/<短码>
    print_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_token
    ON processing_set_part_tokens (token)
    WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_part
    ON processing_set_part_tokens (tenant_id, set_id, order_item_id)
    WHERE deleted = 0;
-- 短码全局唯一（V99，issue #4802）：`/s/<短码>` 那一跳**没有**租户上下文 ⇒ 跨租户也必须唯一
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_short_code
    ON processing_set_part_tokens (short_code)
    WHERE deleted = 0;

-- 工人登录态（V98，issue #4733）：报工身份的**唯一根** —— 服务端从本表解 worker_id/worker_name，
-- 报工请求体里的同名字段被忽略（迁移链同款见 db/migration/V98__create_worker_sessions_and_worker_no.sql）
CREATE TABLE IF NOT EXISTS worker_sessions (
    id VARCHAR(64) PRIMARY KEY,                      -- 会话 id（32 位 UUID 去横线）：前端以 X-Worker-Session-Id 回传
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    worker_id VARCHAR(64) NOT NULL REFERENCES users(id),
    worker_no VARCHAR(64),
    worker_name VARCHAR(64),
    device_label VARCHAR(64),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,  -- 闲置过期（默认 15 分钟，租户可配 5~60）
    ended_at TIMESTAMP WITH TIME ZONE,               -- NULL = 仍活跃
    end_reason VARCHAR(16),                          -- logout / idle / switched / revoked
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_worker_sessions_worker
    ON worker_sessions (tenant_id, worker_id, started_at DESC)
    WHERE deleted = 0;

-- 报工身份旁路账（V98，issue #4733，**只追加**）：一行 = 一次报工动作。
-- 为什么不给 production_work_logs 加列：那是冻结契约 + 红线（设计 §3.4 / worker-scan-terminal.md §7）
CREATE TABLE IF NOT EXISTS worker_report_audits (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    work_log_id VARCHAR(64),
    operation_id VARCHAR(64),
    worker_id VARCHAR(64),
    worker_name VARCHAR(64),
    worker_session_id VARCHAR(64),
    identity_source VARCHAR(16) NOT NULL,            -- server_session（权威）/ client_body（显式降级）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_worker_report_audits_log
    ON worker_report_audits (tenant_id, work_log_id)
    WHERE deleted = 0;

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
    -- 计件单价三态标记（V90，issue #4696）：priced=有价（含显式定价 0 元）；
    -- unpriced=**未定价**（unit_price 为 NULL）⇒ 聚合**不得**按 0 计件，报表必须显式可见 + 给定价入口；
    -- NULL = 本列引入之前的存量行（V61 口径按实例回查兜底，历史金额一字不动）。
    price_state VARCHAR(16),
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
COMMENT ON COLUMN users.worker_no IS '工人工号（V98，issue #4733）：非 NULL = 工人档案（role=worker）；租户内唯一（uk_users_tenant_worker_no）';
COMMENT ON TABLE worker_sessions IS '工人登录态（V98，issue #4733）：服务端是身份的权威 —— 报工只带 X-Worker-Session-Id，worker_id/worker_name 一律由本表解出，body 同名字段被忽略';
COMMENT ON COLUMN worker_sessions.idle_expires_at IS '闲置过期时刻（默认 15 分钟，租户可配 5~60）：每次成功请求由服务端顺延；过期 session 报工 ⇒ 401（不静默续期）';
COMMENT ON COLUMN worker_sessions.end_reason IS '结束原因：logout 主动登出 / idle 闲置超时 / switched 快速切换工人 / revoked 停用撤销';
COMMENT ON TABLE worker_report_audits IS '报工身份旁路账（V98，issue #4733，只追加）：一行 = 一次报工动作；production_work_logs 是冻结契约（不加列）⇒「由哪个设备会话报的」走旁路';
COMMENT ON COLUMN worker_report_audits.identity_source IS 'server_session = 服务端从工人 session 解出（权威，忽略 body）；client_body = 无工人 session 的显式降级（商家侧报工），来源被标注而非静默';
COMMENT ON COLUMN production_work_logs.unit_price IS '计件单价快照（元/单位，V61，issue #4351）：报工那一刻从工序实例写入；聚合只读本列 ⇒ 重新实例化软删旧实例不影响历史报工的钱；NULL=本列引入前的存量行（按实例回查兜底）';
COMMENT ON COLUMN production_work_logs.factor IS '计件系数快照（V61，issue #4351）：与 unit_price 同一次报工写入、同一口径；NULL=存量行';
COMMENT ON COLUMN production_work_logs.price_state IS '计件单价三态标记（V90，issue #4696）：priced=有价（含显式定价 0 元）；unpriced=未定价（unit_price 为 NULL，聚合不得按 0 计件）；NULL=本列引入前的存量行';
COMMENT ON COLUMN processing_position_operations.unit_price IS '实例快照单价（元/单位）：NULL=未定价（≠ 0 元，0 是显式定价为 0 元）；实例化侧不得回落工序库行价（V90，issue #4696）';
-- 套号 + 扫码闭环数据层（V92，issue #4698）：迁移链同款见 backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql
COMMENT ON TABLE processing_order_sets IS '套号载体（V92，issue #4698 / 设计 §2.2）：一个加工单 × 一套 = 一行。一套 = 一樘窗（= 一个 craftLineId 组 / 一个窗的全部部位合计一套，用户裁定 2026-09-20）';
COMMENT ON COLUMN processing_order_sets.set_index IS '一樘窗在本加工单里的次序（1 起，3 位零填充进 set_no）。只增不复用：软删行仍占号（MAX 查询不带 deleted=0）⇒ 重排/改名/删窗都不改已有套号';
COMMENT ON COLUMN processing_order_sets.set_no IS '可读套号 = {processing_order_no}-{pad3(set_index)}（落库冗余）：码里印的是它，扫码解析按文本查唯一索引；冗余不漂移的条件 = 单号与 set_index 一经分配不变';
COMMENT ON COLUMN processing_order_sets.craft_line_id IS '樘窗组键（= 快照 craftLineId，缺省 = 该组主布行的 itemId）；可空（存量/脏快照，与 ProcessingOrderService.craftGroupKey 同口径）';
COMMENT ON COLUMN processing_order_sets.position_item_ids IS '本套包含的部位行 order_items.id 数组（有序）⇒「这套有哪几个部位」不靠反查，也是回填时认领已有套行的指纹';
COMMENT ON COLUMN processing_order_sets.deleted IS '软删（软删 ≠ 释放号）：被删的窗不回收序号，新窗取 MAX(set_index)+1（设计 §2.4 规则 1）';
COMMENT ON TABLE processing_set_part_tokens IS '部位码载体（V92，issue #4698 / 设计 §2.3）：一部位一码（一樘窗 ≤3~4 码）。载体是 token（与 processing_orders.qr_token 同格式），工序不进码';
COMMENT ON COLUMN processing_set_part_tokens.token IS '码 token（32 位 UUID 去横线）。撤销 = 置 NULL（与 ProcessingOrderMapper.revokeQrToken 逐字同语义：这张纸作废，不换新 token）';
COMMENT ON COLUMN processing_set_part_tokens.short_code IS '人可读短码（V99，issue #4802）：8 位 Crockford Base32（0-9 + A-Z 去掉 I/L/O/U），随机、全局唯一。印刷品写 https://<稳定域名>/s/<短码>，服务端 302 换回 token（同一行的两种表示）。NULL = 尚未分配（存量行）';
COMMENT ON COLUMN processing_set_part_tokens.print_count IS '打印次数（原子自增 COALESCE(print_count,0)+1；多人同时打印不丢计数）';
COMMENT ON COLUMN processing_position_operations.set_id IS '套归属（V92，issue #4698）：指向 processing_order_sets.id。可空 = 存量行（与 V69 的 order_item_id 同款「留空不猜」）';
COMMENT ON COLUMN processing_position_operations.set_no IS '套号快照（V92，issue #4698）：与 set_id 同一次回填写入；可空（存量行）。用途：扫码归属校验 + 计件按套下钻（零改动 production_work_logs）';
COMMENT ON COLUMN processing_position_operations.done_at IS '完成时刻（V92，issue #4698）：A 模式唯一必需的新增时序列（做完扫一次 = 完工）。不得用 updated_at 冒充（会被任何更新污染）';
COMMENT ON COLUMN processing_position_operations.worker_id IS '报工人 id（V92，issue #4698）：C 模式预留（A 模式默认路径不读不写）';
COMMENT ON COLUMN processing_position_operations.worker_name IS '报工人姓名（V92，issue #4698）：C 模式预留（A 模式默认路径不读不写）';
COMMENT ON COLUMN processing_position_operations.started_at IS '开工时刻（V92，issue #4698）：C 模式预留（A 模式默认路径不读不写）';
COMMENT ON COLUMN processing_position_operations.status IS 'pending 待做 / in_progress 进行中（C 模式预留，V92 只扩取值域、零行为变化）/ done 已报工';

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

-- 部位价目矩阵格的计件单价版本（V86，issue #4587 = 母单 #4586 包A）
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V86__create_operation_position_price_versions.sql
-- 为什么两处都要：本文件是**全新库的一次性 bootstrap**（docker-entrypoint-initdb.d 执行），
-- 而 **Flyway/MigrationRunner 不在该栈运行** —— 只存在于迁移链的表在建库后并不存在（#3270 形态）。
-- 口径（与 V55 同范式，唯一差别 = unit_price **可空**）：一行 = 一次**真的变了**的矩阵格单价变更；
-- NULL = 改回**未定价**或「明确不做 ⇒ 不报价」（**≠ 0 元**：0 是「定价为 0 元」，两件事）。
-- 本表**不回填**：矩阵格当前价 = production_operation_positions.unit_price 本身（不派生自账本）。
CREATE TABLE IF NOT EXISTS production_operation_position_price_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    position_row_id VARCHAR(64) NOT NULL REFERENCES production_operation_positions(id),
    unit_price NUMERIC(10,2),                        -- 该次变更后的计件单价（元/单位）；NULL = 未定价 / 不做
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_op_position_price_versions_row
    ON production_operation_position_price_versions (position_row_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_operation_position_price_versions IS '部位价目矩阵格的计件单价版本（V86，issue #4587）：每次**真变价**一行；当前价 = production_operation_positions.unit_price 本身，本表只记变更';
COMMENT ON COLUMN production_operation_position_price_versions.unit_price IS '本次变更后的**计件**单价（元/单位，付工人）；NULL = 未定价或明确不做（≠ 0 元，0 是定价为 0 元）';

-- 未定价实例的**显式补价**动作账（V94，issue #4709 C）
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V94__create_instance_repricing_logs.sql
-- 为什么两处都要：本文件是**全新库的一次性 bootstrap**（docker-entrypoint-initdb.d 执行），
-- 而 **Flyway/MigrationRunner 不在该栈运行** —— 只存在于迁移链的表在建库后并不存在（#3270 形态）。
-- 用途：商家事后在部位价目矩阵补价时，把**已实例化**的 `unit_price IS NULL` 行补成当前矩阵价
-- （只补 NULL，已有价含 0 一律不动），并留痕（batch_id = 一次动作）+ 可回滚（rolled_back_at）。
-- 不记 old_unit_price：本表只由「NULL ⇒ 有价」写入（服务层 CAS 谓词机械保证）⇒ 旧值恒 NULL。
CREATE TABLE IF NOT EXISTS production_instance_repricing_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_id VARCHAR(64) NOT NULL,                   -- 一次补价动作 = 一个批次（回滚粒度）
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    position_operation_id VARCHAR(64) NOT NULL REFERENCES processing_position_operations(id),
    new_unit_price NUMERIC(10,2) NOT NULL,           -- 本次补上的单价 = 补价那一刻矩阵格的当前价
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    rolled_back_at TIMESTAMP WITH TIME ZONE,         -- 回滚时刻；NULL = 未回滚
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_instance_repricing_batch
    ON production_instance_repricing_logs (tenant_id, batch_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_instance_repricing_operation
    ON production_instance_repricing_logs (position_operation_id)
    WHERE deleted = 0;
COMMENT ON TABLE production_instance_repricing_logs IS '未定价实例的**显式补价**动作账（V94，issue #4709）：一行 = 一个被补价的实例行；只由「unit_price IS NULL ⇒ 当前矩阵价」写入（已有价的行永远不产生账行）；batch_id = 一次动作，回滚按批（rolled_back_at 留痕）';
COMMENT ON COLUMN production_instance_repricing_logs.new_unit_price IS '本次补上的计件单价（元/单位）= 补价那一刻部位价目矩阵的当前价；回滚只在实例行当前值仍等于本值时才还原（CAS），不覆盖后续改动';
COMMENT ON COLUMN production_instance_repricing_logs.rolled_back_at IS '回滚时刻（NULL = 未回滚）；回滚只还原 unit_price → NULL，不碰 factor / done_qty / status / 报工历史';

-- ⚠️ 原 `production_option_routings` / `production_option_factors`（V59，issue #4230）已**删表**
-- （issue #5245 A4，2026-09-23 用户裁定）：V73 只把活跃行软删、表仍在 ⇒ 那是「历史行 + 零消费者」
-- 的僵尸表（`RemnantService` 是最后一个读点，本单已把它改读 `production_route_rules`）。
-- 存量库由 `V126__drop_zombie_db_objects.sql` 幂等 DROP TABLE（两表 + 全部索引）；
-- 新建库由本文件不再建表、不再种子。
-- 规则真值源 = `production_route_rules`（V71 建表 / V72 扩列）—— 选项→条件工序与计件系数档
-- 都已搬进该表（`trigger_kind='option'`；系数档 `action='factor'`，且自 #4589 起已软删退场）。
-- 归档载体（逐字节冻结的历史证据）= `db/migration-archive/V59__create_production_option_tables.sql`
-- 与 V65（ERP 改名）—— 判据改指归档文件，不删断言。

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

-- ⚠️ 形状修订（issue #4581，P0）：本表 V60 时是**旧模型**形状（routing_id → production_routings、
--    curtain_type/craft NOT NULL），而写面自 P2b（#4459）起落在 production_route_templates ⇒
--    新建路线 / 改主线**恒 500**（not-null violation + FK 指向已退役的旧表）。
--    修法 = 迁移 V85__fix_routing_version_ledger_shape.sql；**两处必须同口径**（本文件是
--    bootstrap 路径，它**不跑迁移链**，只存在于迁移里的修法在新库上等于没修，形态见 #3270）。
--    curtain_type / craft **保留但可空**：只为历史行（新模型没有「部位 × 工艺」这一维）；
--    routing_id 保持 NOT NULL，新模型下它恒有值（= production_route_templates.id）。
--    外键的 NOT VALID 语义：存量行可能引用旧表 id ⇒ 不做全量校验，**新写入照旧强制**。
CREATE TABLE IF NOT EXISTS production_routing_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    routing_id VARCHAR(64) NOT NULL REFERENCES production_route_templates(id),
    curtain_type VARCHAR(16),                        -- 旧模型遗留（历史行）；新行恒 NULL
    craft VARCHAR(16),                               -- 旧模型遗留（历史行）；新行恒 NULL
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

-- 加工费组合定价 + 版本账（V68，issue #4386「加工费管理模块」）
-- 迁移链同款见 backend/admin-api/src/main/resources/db/migration/V68__create_processing_fee_combinations.sql
-- （为什么两处都要：本文件是**全新库的一次性 bootstrap**，该路径**不跑迁移链** ⇒ 只存在于迁移里的表
--  在建库后并不存在，admin-api 查询 500，形态见 issue #3270。）
-- 用户裁定（2026-09-19）：「不是每个加工项收取一个费用，而且通常是组合」「选配完的一个商品
--  **只会收取一种加工费**，然后根据米算出这个商品的加工费」⇒ 一行 = 一组选配特征 → 一个单价（元/米）。
-- composition_key 归一化口径（冻结）：trim → 丢空 → 去重 → 按 Unicode 码点升序 → `+` 连接
--   ⇒ `韩褶+打孔+定型` ≡ `定型+打孔+韩褶`（与书写顺序无关；否则同一笔钱建出两行，取价不可复现）。
-- 不是穷举幂集：只维护实际会卖的组合，未定价组合由 GET /production/processing-fee-gaps 暴露为缺口。
CREATE TABLE IF NOT EXISTS processing_fee_combinations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    composition_key VARCHAR(256) NOT NULL,           -- 归一化后的选配特征集合（取价的匹配键）
    items JSONB NOT NULL DEFAULT '[]',               -- 归一化后的特征名有序列表（与 key 同源，展示用）
    unit_price DECIMAL(10, 2) NOT NULL,              -- 加工费单价（**元/米**）
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- active / disabled（停用 = 保留行）
    sort_order INT NOT NULL DEFAULT 0,
    source VARCHAR(16),                              -- 实证 / 推算 / 占位待确认（与 V62 同词表）；NULL = 未知
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_processing_fee_combinations_unit_price CHECK (unit_price >= 0),
    CONSTRAINT ck_processing_fee_combinations_key_not_blank CHECK (btrim(composition_key) <> '')
);
-- 唯一键 = (tenant_id, composition_key) WHERE deleted = 0 —— 同一组合不重复定价。
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_fee_combinations_tenant_key
    ON processing_fee_combinations (tenant_id, composition_key)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_processing_fee_combinations_tenant_status
    ON processing_fee_combinations (tenant_id, status, sort_order)
    WHERE deleted = 0;
COMMENT ON TABLE processing_fee_combinations IS
    '加工费组合定价（V68，issue #4386）：一行 = 一组选配特征 → 一个加工费单价（元/米）；下单侧按选配结果匹配本表取价，× 加工费米数 = 一个数';
COMMENT ON COLUMN processing_fee_combinations.composition_key IS
    '归一化后的选配特征集合（trim → 丢空 → 去重 → 按 Unicode 码点升序 → `+` 连接）；与书写顺序无关：`韩褶+打孔+定型` ≡ `定型+打孔+韩褶`';
COMMENT ON COLUMN processing_fee_combinations.unit_price IS
    '加工费单价（元/米）：组合价 × 加工费米数 = 该商品这一个数。CHECK >= 0 —— 负单价会把订单金额算成负数';

CREATE TABLE IF NOT EXISTS processing_fee_combination_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    combination_id VARCHAR(64) NOT NULL REFERENCES processing_fee_combinations(id),
    composition_key VARCHAR(256) NOT NULL,           -- 冗余存键（组合行停用/改名后仍答得出「当时是哪一组」）
    unit_price DECIMAL(10, 2) NOT NULL,              -- 本次变更后的单价（元/米）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_processing_fee_combination_versions_combination
    ON processing_fee_combination_versions (combination_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE processing_fee_combination_versions IS
    '加工费组合定价版本账（V68，issue #4386）：单价真的变了才追加一行（同值重复提交是幂等空操作）；当前价 = 最新版本行';

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
-- 保留期：不设 TTL，随订单生命周期软删（deleted）。`orders.stock_deducted` 已于
-- issue #5245 A2 删列（原「死列」表述见 V53 头注释 —— 那是历史记录，列本身现在不存在了）。
CREATE TABLE IF NOT EXISTS stock_ledger_entries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,                                   -- 无 FK：SKU 会被硬删重建（追溯优先用 sku_code）
    sku_code VARCHAR(64),
    delta NUMERIC(12,1) NOT NULL,                    -- 正=入库/回补，负=出库/扣减（恒等于 after_qty - before_qty；V115/#5063）
    before_qty NUMERIC(12,1) NOT NULL,
    after_qty NUMERIC(12,1) NOT NULL,
    reason VARCHAR(16) NOT NULL,                     -- order / aftersales / manual / inbound（V111）
    ref_no VARCHAR(64),                              -- 订单号 / 工单号 / 入库单号 / 批次号；manual 为空
    note VARCHAR(255),                               -- 人类可读原因（如「盘点」「报损」）
    operator VARCHAR(64) NOT NULL,                   -- 登录用户名；内部服务 = internal-service；无认证 = system
    -- 成本快照（来自 V111，issue #5034）：让「成本为什么变了」与「库存为什么变了」在同一张账上对账
    unit_cost NUMERIC(12,4),                         -- 本次变更单位成本（入库=行单价；出库=当时移动加权均价）；NULL = 成本未知
    cost_amount NUMERIC(16,4),                       -- 本次变更成本金额 = |delta| * unit_cost；NULL = 成本未知
    avg_cost_before NUMERIC(12,4),                   -- 变更前移动加权均价；NULL = 变更前成本未知
    avg_cost_after NUMERIC(12,4),                    -- 变更后移动加权均价；出库不变、入库重算
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    -- V111：放行 inbound（入库单过账）
    CONSTRAINT ck_stock_ledger_reason CHECK (reason IN ('order', 'aftersales', 'manual', 'inbound'))
);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_sku
    ON stock_ledger_entries (tenant_id, sku_id, id);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_product
    ON stock_ledger_entries (tenant_id, product_id, id);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_tenant_ref
    ON stock_ledger_entries (tenant_id, ref_no, id);

-- ================================================
-- 9.8 入库单 / 批次（issue #5034，V111 迁移；#5148，V117 幂等/口径）
-- ================================================
-- 一次布料收货 = 一张入库单；**一个 SKU 行 = 一个批次**（用户裁定 2026-09-23）。
-- 批次号 PC-yyyyMMdd-NNNN 由服务端自动生成（租户内唯一索引兜底防重号）。
-- draft 不动库存，posted 才加库存 + 落台账 + 算移动加权平均成本；posted 是终态。
-- 单号 RK-yyyyMMdd-NNNN **租户内唯一**（V117 统一口径：改前是全局唯一索引，与建表注释矛盾）；
-- import_run_id + source 见 V117（建单幂等键 / 单据来源）。
-- 行业依据（缸号/批次）见 docs/curtain-selling-method-industry-research.md §1/§8.2。
CREATE TABLE IF NOT EXISTS inbound_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_no VARCHAR(32) NOT NULL,                 -- RK-yyyyMMdd-NNNN（租户内唯一）
    supplier VARCHAR(128),
    supplier_doc_no VARCHAR(64),
    warehouse VARCHAR(64),
    inbound_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',     -- draft / posted / cancelled
    total_amount NUMERIC(16,4) NOT NULL DEFAULT 0,
    remark TEXT,
    -- 单据来源（V117）：purchase 采购收货 / opening 期初建账（迁移导入）
    source VARCHAR(16) NOT NULL DEFAULT 'purchase' CONSTRAINT ck_inbound_orders_source
        CHECK (source IN ('purchase', 'opening')),
    -- 建单运行级幂等键（V117）：同一 (tenant_id, import_run_id) 至多一张未软删的单
    import_run_id VARCHAR(128),
    posted_at TIMESTAMP WITH TIME ZONE,
    posted_by VARCHAR(64),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_by VARCHAR(64),
    cancelled_reason TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
-- 单号**租户内唯一**（V117 起；列 = (tenant_id, inbound_no)、谓词 deleted = 0，与 @TableLogic 查询口径同界）
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_no
    ON inbound_orders (tenant_id, inbound_no)
    WHERE deleted = 0;
-- 建单幂等键的部分唯一索引（V117）：不带运行标识的普通建单不受影响
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_tenant_import_run
    ON inbound_orders (tenant_id, import_run_id)
    WHERE import_run_id IS NOT NULL AND deleted = 0;
CREATE INDEX IF NOT EXISTS idx_inbound_orders_tenant_status_date
    ON inbound_orders (tenant_id, status, inbound_date DESC);
CREATE INDEX IF NOT EXISTS idx_inbound_orders_tenant_supplier
    ON inbound_orders (tenant_id, supplier);
COMMENT ON TABLE inbound_orders IS
    '入库单（V111，issue #5034）：一次布料收货 = 一张单。draft 不动库存，posted 才加库存（只允许 draft→posted 一次），cancelled 仅 draft 可作废（已过账不得作废，冲销另开单）';
COMMENT ON COLUMN inbound_orders.inbound_no IS
    '入库单号 RK-yyyyMMdd-NNNN（V111；V117 起**租户内唯一**）。唯一索引 = uk_inbound_orders_no (tenant_id, inbound_no) WHERE deleted = 0（V111 建的是全局唯一索引，与建表注释「租户内唯一」矛盾，issue #5148 统一口径）';
COMMENT ON COLUMN inbound_orders.import_run_id IS
    '建单**运行级**幂等键（V117，issue #5148）：同一 (tenant_id, import_run_id) 至多一张未软删的单 ⇒ 同一份导入重跑不会建出第二张单。NULL = 普通建单';
COMMENT ON COLUMN inbound_orders.source IS
    '单据来源（V117，issue #5148）：purchase 采购收货 / opening 期初建账；CHECK ck_inbound_orders_source 限定取值，存量行一律 purchase';

CREATE TABLE IF NOT EXISTS inbound_order_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id) ON DELETE CASCADE,
    sku_id BIGINT,                                   -- 无 FK：SKU 会被硬删重建（同 stock_ledger_entries.sku_id）
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_code VARCHAR(64),
    color_name VARCHAR(64),
    door_width VARCHAR(32),
    quantity NUMERIC(12,1) NOT NULL,                 -- 入库数量（米）：与 product_skus.stock 粒度逐字一致（V115/#5063）
    unit_cost NUMERIC(12,4),                         -- NULL = 未记单价 ⇒ 只加数量不算成本
    amount NUMERIC(16,4),                            -- quantity * unit_cost；NULL 单价 ⇒ NULL（不用 0 冒充）
    batch_no VARCHAR(32),                            -- 过账时才写（草稿为 NULL）
    legacy_batch_no VARCHAR(64),                     -- 旧系统批次号（V118/#5153）：仅 source='opening' 的期初单可填，过账时透传到 stock_batches
    dye_lot VARCHAR(64),                             -- 供应商缸号（外部事实，可空）
    roll_length_m NUMERIC(8,2),                      -- 每卷米数（仅记录/打印，不参与换算）
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inbound_items_order ON inbound_order_items (inbound_order_id);
CREATE INDEX IF NOT EXISTS idx_inbound_items_tenant_sku ON inbound_order_items (tenant_id, sku_id);
COMMENT ON TABLE inbound_order_items IS
    '入库单明细（V111）：一个 SKU 行 = 一个批次。批次粒度取行级而非卷级（缸号的行业粒度本就是「一批布」，卷长是区间值不宜硬折算，见 docs/curtain-selling-method-industry-research.md §8.2 末）';

-- 入库标签（V134，issue #5052 P2；设计 docs/design/inbound-photo-and-label.md §7.1 / §7.3）：
-- 一行 = 一个入库单明细行 = 一张 50×30mm 标签；标签上的码 = `https://app.migaozn.com/i/<8 位短码>`。
-- 🔴 与 processing_set_part_tokens（工人报工短链 `/s/`）是**两个码空间**（#5052 边界逐字：
-- 「照其范式、不复用其表」）—— 本表照其范式（8 位 Crockford Base32 / 部分唯一索引 /
-- 原子自增计数），但**不复用其表**：混用会把「扫标签」变成「进报工页」。
-- 撤销 = `short_code` 置 NULL、原码留档 `revoked_code` ⇒ 扫码 **410**（与 404「没这个码」可分辨；
-- 只置 NULL 会把撤销说成「不存在」）；`uk_inbound_labels_code`（有效码唯一）⇒ 已撤销的码永不复发。
CREATE TABLE IF NOT EXISTS inbound_labels (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id),
    inbound_item_id BIGINT NOT NULL,                 -- 入库单明细行（一行 = 一个 SKU = 一个批次 = 一张标签）
    short_code CHAR(8),                              -- 当前有效短码；撤销 ⇒ 置 NULL（§7.3 逐字）
    revoked_code CHAR(8),                            -- 撤销时留档的原码 ⇒ 撤销后仍判 410 而不是 404
    print_count INTEGER NOT NULL DEFAULT 0,          -- 原子自增（COALESCE(print_count,0)+1），重打同样计数
    created_by VARCHAR(64),
    revoked_at TIMESTAMP WITH TIME ZONE,
    revoked_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_inbound_labels_code_exactly_one
        CHECK ((short_code IS NULL) <> (revoked_code IS NULL)),
    CONSTRAINT ck_inbound_labels_code_shape
        CHECK ((short_code IS NULL OR short_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$')
           AND (revoked_code IS NULL OR revoked_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$'))
);
-- 码全局唯一（跨租户：/i/ 那一跳没有租户上下文）：建在**有效码** COALESCE(short_code, revoked_code) 上
-- ⇒ 活码 / 留档码 / 两者交叉都在同一条约束下（已撤销的码永不复发）
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_labels_code
    ON inbound_labels (COALESCE(short_code, revoked_code))
    WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_labels_item
    ON inbound_labels (tenant_id, inbound_item_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_inbound_labels_order ON inbound_labels (inbound_order_id);
COMMENT ON TABLE inbound_labels IS
    '入库标签（V134，issue #5052 P2）：一行 = 一个入库单明细行 = 一张 50×30mm 标签。短码 = 8 位 Crockford Base32、随机、全局唯一；撤销 = short_code 置 NULL（原码留档 revoked_code）⇒ 扫码 410；print_count 原子自增（设备侧打印前必须先调 POST /api/worker/inbound/labels/{短码}/print）';
COMMENT ON COLUMN inbound_labels.short_code IS
    '当前有效短码（印刷品写 https://app.migaozn.com/i/<短码>）。撤销 ⇒ 置 NULL（§7.3），原码留档到 revoked_code ⇒ 扫码仍判 410 而不是 404';
COMMENT ON COLUMN inbound_labels.revoked_code IS
    '撤销时留档的原短码：撤销后仍能分辨「已作废（410）」与「不存在（404）」；与 short_code 一起受 uk_inbound_labels_code（有效码唯一）约束 ⇒ 已撤销的码永不复发';
COMMENT ON COLUMN inbound_labels.print_count IS
    '打印次数（原子自增 COALESCE(print_count,0)+1；多人同时打印不丢计数；重打同样计数）';

CREATE TABLE IF NOT EXISTS stock_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_no VARCHAR(32) NOT NULL,                   -- 服务端生成的系统批次号 PC-yyyyMMdd-NNNN（**不得**被旧系统批次号冒充，V111）
    legacy_batch_no VARCHAR(64),                     -- 旧系统批次号（V118/#5153）：外部事实，与 batch_no / dye_lot 各是一义
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    inbound_order_id VARCHAR(64) REFERENCES inbound_orders(id),
    inbound_item_id BIGINT,
    inbound_no VARCHAR(32),
    quantity NUMERIC(12,1) NOT NULL,                 -- 批次数量（米）：与 product_skus.stock 粒度逐字一致（V115/#5063）
    unit_cost NUMERIC(12,4),
    amount NUMERIC(16,4),
    dye_lot VARCHAR(64),
    roll_length_m NUMERIC(8,2),
    supplier VARCHAR(128),
    warehouse VARCHAR(64),
    received_date DATE,
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_stock_batches_no ON stock_batches (tenant_id, batch_no);
CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_sku ON stock_batches (tenant_id, sku_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_dye_lot ON stock_batches (tenant_id, dye_lot);
CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_legacy_no ON stock_batches (tenant_id, legacy_batch_no);
CREATE INDEX IF NOT EXISTS idx_stock_batches_inbound ON stock_batches (inbound_order_id);
COMMENT ON TABLE stock_batches IS
    '批次台账（V111）：一行 = 一个入库批次（= 一条入库单明细行）。缸号随批次可见 —— 对应 AHFA 卷标须带 Lot number 的行业要求（docs/curtain-selling-method-industry-research.md §1/S10）。批次行不可改：冲销走新单据';

-- 批次消耗台账（V116，issue #5145 阶段 1）：一行 = 一次批次余量变更（负 = 派工扣减、正 = 作废回补）。
-- 余量派生 = stock_batches.quantity + Σ(delta)（**不原地改** stock_batches.quantity）；
-- 与 stock_ledger_entries（SKU 级销售账）是**两本账**：本表是批次级实物账，随加工单生成而扣、随作废而回补。
CREATE TABLE IF NOT EXISTS stock_batch_consumptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_id BIGINT NOT NULL REFERENCES stock_batches(id),
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    delta NUMERIC(12,1) NOT NULL,                    -- 变化量（正 = 回补，负 = 扣减）；V115/#5063 精度
    before_qty NUMERIC(12,1) NOT NULL,               -- 变更前**该批次余量**（不是 SKU 库存）
    after_qty NUMERIC(12,1) NOT NULL,                -- 变更后**该批次余量**
    -- V119（issue #5158）：两个米数 + 「当时」均价快照 —— #5159 L1「逐单反事实」的载体。
    -- 带符号（与 delta 同向：扣减行为正、回补行为负）；约束保证 planned <= formula（只多不少）。
    formula_meters NUMERIC(12,1) NOT NULL,           -- 行业公式口径（= 改前的扣减口径，与销售账同源同函数）
    planned_meters NUMERIC(12,1) NOT NULL,           -- 排料口径（= 改后的扣减口径，恒等于 -delta）
    unit_cost NUMERIC(12,4),                         -- **当时**该批次均价快照（NULL = 历史行未知，不回填不猜）
    reason VARCHAR(32) NOT NULL,                     -- processing_order / processing_order_cancelled
    processing_order_no VARCHAR(32) NOT NULL,
    order_no VARCHAR(32),
    order_item_id VARCHAR(36) NOT NULL,              -- = order_items.id（ASSIGN_UUID 主键，VARCHAR(36)）
    operator VARCHAR(64) NOT NULL,
    note VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);
-- 幂等闸：同一加工单的同一明细行 × 同一批次 × 同一 reason 只允许一行
CREATE UNIQUE INDEX IF NOT EXISTS uk_batch_consumption_line
    ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason)
    WHERE deleted = 0;
-- V119（issue #5158）不变式：排料口径**只多不少**且两列**同号**
-- （扣减行都正 / 回补行都负 —— 少了后半句，(+6, −3) 这种符号打架的行也能落库）。
-- ⚠️ V121（issue #5182）修正：前半句必须是**绝对值**口径 —— 回补行两列都负，
-- 原来的 `planned_meters <= formula_meters` 在负行上方向翻转（−3 <= −6 = 假）
-- ⇒ 「省过料的行」的回补行必然违反本约束（真库 23514，作废/取消回补直接失败）。
-- 绝对值形式对扣减行与旧式**逐字等价**，对回补行才是真正的「只多不少」。
ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_plan_meters;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_plan_meters
    CHECK (abs(planned_meters) <= abs(formula_meters) AND formula_meters * planned_meters >= 0);
ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_unit_cost;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_unit_cost
    CHECK (unit_cost IS NULL OR unit_cost >= 0);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_batch
    ON stock_batch_consumptions (tenant_id, batch_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_po
    ON stock_batch_consumptions (tenant_id, processing_order_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_order
    ON stock_batch_consumptions (tenant_id, order_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_sku
    ON stock_batch_consumptions (tenant_id, sku_id, id);
COMMENT ON TABLE stock_batch_consumptions IS
    '批次消耗台账（V116，issue #5145 阶段 1）：一行 = 一次批次余量变更。余量 = stock_batches.quantity + Σ(delta)；批次行不可改（V111）⇒ 冲销走新单据（新增一行反向 delta）';

-- ── 余料成本回收（V122，issue #5146）：**非资产**余料台账 + 小件用料尺寸表（可配参数）──
-- 🔴 余料不是资产（用户裁定「这个废布不算在企业资产了」）：fabric_remnants **没有任何计价列**，
--    不计价、不进库存金额、不出现在任何库存/资产读面。
--    判据 = 加余料登记前后 Σ product_skus.cost_amount 与 Σ product_skus.stock **逐值不变**（真库）
--    + 两张表在库存/资产读面里的引用数为零（静态守卫）。
-- 小件用料尺寸表 = **企业可配参数**（用户裁定「可以整个参数配置，未来让企业自定义」）；
--    缺行 = 未配置 = 未启用（默认值为空，不编业务数值）⇒ 匹配不产生任何推荐且读面显式说明。
-- 回收与报废为什么是同一行的列：一块余料只能被用掉一次（1:1）⇒ 用列比新开一张表少一层 join、
--    少一个「两表不一致」的失效形态；代价 = 将来做「部分使用」需扩表（本单不做）。

-- 小件用料尺寸表（一行 = 一个小件需要多大一块布）
-- 「缺行 = 用默认值」而本参数的默认值**就是空** ⇒ 没配就是没启用。
CREATE TABLE IF NOT EXISTS remnant_small_item_specs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 小件配置键 = 该小件对应的**工序名**（逐字同 production_operations.name 与
    -- routing.py::SPECIAL_OPTION_ROUTINGS 的 operation，如 绑带-布 / 帘头制作 / 抱枕）；
    -- 不另造「小件名」= 不造第二份会漂移的口径。
    item_key VARCHAR(64) NOT NULL,
    length_m NUMERIC(8,2) NOT NULL,                  -- 这块布沿**卷长**方向需要的长度（米）
    width_m NUMERIC(8,2) NOT NULL,                   -- 这块布沿**门幅**方向需要的宽度（米）
    note VARCHAR(255),
    operator VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_remnant_spec_size CHECK (length_m > 0 AND width_m > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_remnant_spec_item
    ON remnant_small_item_specs (tenant_id, item_key) WHERE deleted = 0;

-- 余料台账（一行 = 一块实物余料；**非资产**：只记实物可用性）
CREATE TABLE IF NOT EXISTS fabric_remnants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    piece_seq INTEGER NOT NULL,                      -- 排料清单里的确定序号（幂等闸的键之一）
    source_order_no VARCHAR(32) NOT NULL,
    source_processing_order_no VARCHAR(32) NOT NULL,
    source_batch_id BIGINT REFERENCES stock_batches(id),
    source_batch_no VARCHAR(32) NOT NULL,
    dye_lot VARCHAR(64),                             -- 缸号**快照**（源 stock_batches.dye_lot；同缸号优先匹配防色差）
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    piece_kind VARCHAR(16) NOT NULL,                 -- width 门幅余料 / end 端部余料
    length_m NUMERIC(12,2) NOT NULL,                 -- 沿**卷长**方向（米）
    width_m NUMERIC(12,2) NOT NULL,                  -- 沿**门幅**方向可用宽度（米）
    -- 状态机：customer_taken 客户带走（不进可用池、不参与匹配、不计回收）
    --        / available 可用 / used 已用 / scrapped 已报废
    status VARCHAR(16) NOT NULL,
    -- ── 回收记账（status='used' 时全非空；**只**在此时非空）──
    -- 这四列记的是「这块布被哪张单用掉、冲减多少」= **用它的那张单**的内部成本口径，
    -- 不是余料的资产属性（本表**没有**「余料值多少钱」的列）。
    used_by_order_no VARCHAR(32),
    used_by_order_item_id VARCHAR(36),
    used_by_item_key VARCHAR(64),
    recovered_meters NUMERIC(12,2),                  -- 用掉米数 = 该余料沿卷长方向的长度
    recovered_unit_cost NUMERIC(12,4),               -- **当时**该批次均价快照（源 stock_batches.unit_cost）
    -- 精度 6 位 = NUMERIC(12,2) × NUMERIC(12,4) 的**精确**积 ⇒ 约束可以写「逐值相等」
    recovered_amount NUMERIC(20,6),
    recovered_at TIMESTAMP WITH TIME ZONE,
    recovered_by VARCHAR(64),
    -- ── 报废留痕（status='scrapped' 时全非空；与回收**互斥**）──
    scrap_reason VARCHAR(255),
    scrapped_at TIMESTAMP WITH TIME ZONE,
    scrapped_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_fabric_remnant_status
        CHECK (status IN ('customer_taken', 'available', 'used', 'scrapped')),
    CONSTRAINT ck_fabric_remnant_piece_kind CHECK (piece_kind IN ('width', 'end')),
    CONSTRAINT ck_fabric_remnant_size CHECK (length_m > 0 AND width_m > 0),
    CONSTRAINT ck_fabric_remnant_amount
        CHECK (recovered_amount IS NULL
               OR (recovered_meters IS NOT NULL AND recovered_unit_cost IS NOT NULL
                   AND recovered_meters > 0 AND recovered_unit_cost >= 0
                   AND recovered_amount = recovered_meters * recovered_unit_cost)),
    -- 生命周期一致性（判据「报废留痕 / 账实一致」的机械落点）：状态与留痕列必须互相解释得通
    CONSTRAINT ck_fabric_remnant_lifecycle
        CHECK (
            (status = 'used'
                AND used_by_order_no IS NOT NULL
                AND recovered_meters IS NOT NULL AND recovered_unit_cost IS NOT NULL
                AND recovered_amount IS NOT NULL AND recovered_at IS NOT NULL
                AND scrapped_at IS NULL AND scrap_reason IS NULL)
            OR (status = 'scrapped'
                AND scrap_reason IS NOT NULL AND scrapped_at IS NOT NULL
                AND recovered_meters IS NULL AND recovered_unit_cost IS NULL
                AND recovered_amount IS NULL AND recovered_at IS NULL
                AND used_by_order_no IS NULL)
            OR (status IN ('available', 'customer_taken')
                AND recovered_meters IS NULL AND recovered_unit_cost IS NULL
                AND recovered_amount IS NULL AND recovered_at IS NULL
                AND used_by_order_no IS NULL
                AND scrap_reason IS NULL AND scrapped_at IS NULL)
        )
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_fabric_remnants_piece
    ON fabric_remnants (tenant_id, source_processing_order_no, piece_seq) WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_fabric_remnants_recovery
    ON fabric_remnants (tenant_id, used_by_order_item_id, used_by_item_key)
    WHERE deleted = 0 AND status = 'used';
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_status
    ON fabric_remnants (tenant_id, status, id);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_batch
    ON fabric_remnants (tenant_id, source_batch_no, id);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_dye_lot
    ON fabric_remnants (tenant_id, dye_lot);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_order
    ON fabric_remnants (tenant_id, source_order_no, id);
COMMENT ON TABLE fabric_remnants IS
    '余料台账（V122，issue #5146）—— **非资产**：一行 = 一块实物余料，只记实物可用性（尺寸 / 来源订单 / 来源批次 / 缸号 / 状态），不计价、不进库存金额。余料 = 门幅余料（piece_kind=width）+ 端部余料（end），随排料/派工结果自动产生。状态机：customer_taken / available / used / scrapped';
COMMENT ON TABLE remnant_small_item_specs IS
    '小件用料尺寸表（V122，issue #5146）：一行 = 一个小件需要的一块布有多大。**企业可配参数**；缺行 = 未配置（不编默认数值）⇒ 余料匹配不产生任何推荐且读面显式说明，不静默';

-- ================================================
-- 9b. 批量更新的批次资源（V127，issue #5314 服务端包）
-- 一行批次 + 逐条明细；明细的 old_value 是**撤销的唯一依据**（预览阶段就落库）。
-- ⚠️ 不得改用 audit_logs：审计是有界 fail-open（3s 丢行允许），当撤销依据会静默失去依据。
-- ================================================

CREATE TABLE IF NOT EXISTS agent_batches (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_type VARCHAR(32) NOT NULL,                 -- product_price / product_status（白名单）
    status VARCHAR(16) NOT NULL DEFAULT 'preview',   -- preview → executing → done | partial → reverted | revert_partial
    item_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(64),                          -- 发起人 userId（认证上下文；批量 = 盲签，必须留痕）
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE,
    reverted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_agent_batch_type
        CHECK (batch_type IN ('product_price', 'product_status')),
    CONSTRAINT ck_agent_batch_status
        CHECK (status IN ('preview', 'executing', 'done', 'partial', 'reverted', 'revert_partial')),
    CONSTRAINT ck_agent_batch_counts
        CHECK (item_count >= 0 AND success_count >= 0 AND fail_count >= 0
               AND success_count + fail_count <= item_count)
);
CREATE INDEX IF NOT EXISTS idx_agent_batches_tenant_created
    ON agent_batches (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_batch_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL REFERENCES agent_batches(id) ON DELETE CASCADE,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),  -- 契约之外追加：租户插件会注入该列谓词
    resource_id VARCHAR(64) NOT NULL,                  -- 商品 ID（逐字定位，不做名称解析）
    field VARCHAR(32) NOT NULL,                        -- basePrice / status
    old_value TEXT,                                    -- 🔴 撤销的唯一依据（DB 当前值，预览阶段采集）
    new_value TEXT,                                    -- 执行时写入的值
    status VARCHAR(16) NOT NULL DEFAULT 'pending',     -- pending/success/failed/reverted/revert_failed/skipped
    error VARCHAR(500),                                -- 逐条失败原因（部分失败逐条报告的载体）
    CONSTRAINT ck_agent_batch_item_field
        CHECK (field IN ('basePrice', 'status')),
    CONSTRAINT ck_agent_batch_item_status
        CHECK (status IN ('pending', 'success', 'failed', 'reverted', 'revert_failed', 'skipped'))
);
CREATE INDEX IF NOT EXISTS idx_agent_batch_items_batch
    ON agent_batch_items (batch_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_batch_items_tenant
    ON agent_batch_items (tenant_id, batch_id);

COMMENT ON TABLE agent_batches IS
    '批量更新的批次（V127，issue #5314）—— 状态机 preview → executing → done | partial → reverted | revert_partial；不可撤销 = 状态非 done/partial 或已 reverted';
COMMENT ON TABLE agent_batch_items IS
    '批量更新的逐条明细（V127，issue #5314）—— old_value = 撤销的唯一依据；逐条 status/error = 部分失败逐条报告的载体，不做整体回滚';

-- 发货单 + 发货明细（V132，issue #5648）—— 工人拍照生成发货单 + 订单发货状态闭环
-- 「发货明细（实发套/件/卷）」这个真值的**唯一 owner = 这两张表**；issue #5651（纸面）只消费。
CREATE TABLE IF NOT EXISTS order_shipments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL,
    order_no VARCHAR(64),
    shipment_no VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL,                     -- worker_photo / worker / admin
    photo_refs JSONB,                                -- 照片引用（URL 列表）；无照片 ⇒ 空数组，不编造
    recognition JSONB,                               -- 识别留痕（vision 原样字段表：逐格 value/source/reason）
    packed_by_worker_id VARCHAR(64),
    packed_by_worker_name VARCHAR(64),
    packed_at TIMESTAMP WITH TIME ZONE,
    shipped_by_worker_id VARCHAR(64),
    shipped_by_worker_name VARCHAR(64),
    shipped_at TIMESTAMP WITH TIME ZONE,
    tracking_no VARCHAR(64),
    logistics_company VARCHAR(128),
    client_request_id VARCHAR(128),                  -- 幂等键（X-Client-Request-Id）
    unpacked_at TIMESTAMP WITH TIME ZONE,            -- 撤销打包留痕（必带理由）
    unpacked_by_worker_id VARCHAR(64),
    unpacked_by_worker_name VARCHAR(64),
    unpack_reason VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted SMALLINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_order_shipments_idem
    ON order_shipments (tenant_id, client_request_id)
    WHERE client_request_id IS NOT NULL AND deleted = 0;
CREATE INDEX IF NOT EXISTS idx_order_shipments_order
    ON order_shipments (tenant_id, order_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_shipment_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    shipment_id VARCHAR(36) NOT NULL REFERENCES order_shipments(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL,
    order_item_id VARCHAR(36),                       -- 挂在**订单行**上（同商品两行必须分得开）
    product_name VARCHAR(255),
    shipped_quantity NUMERIC(10,2) NOT NULL,         -- 🔴 实发数量（与 order_items.quantity 同口径）
    unit VARCHAR(16) NOT NULL,                       -- 米 / 套 / 件（不从订单行推算）
    set_count INTEGER,                               -- 实发套数；不适用 ⇒ NULL（缺值不填 0）
    roll_count INTEGER,                              -- 实发卷数；非整卷 ⇒ NULL（禁止由米数推算）
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted SMALLINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_order_shipment_items_shipment
    ON order_shipment_items (shipment_id, id);
CREATE INDEX IF NOT EXISTS idx_order_shipment_items_order
    ON order_shipment_items (tenant_id, order_id);

COMMENT ON TABLE order_shipments IS
    '发货单（V132，issue #5648）—— 服务端留痕：谁/何时/哪张单/照片引用/识别结果；与 order_logistics 分开（后者是物流面）';
COMMENT ON TABLE order_shipment_items IS
    '发货明细（V132，issue #5648）—— 这一单**实际发了多少**；真值唯一 owner = 本表，#5651（纸面）只消费';

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

-- （原 `processing_rules` 的两条索引随该表一并删除，issue #5245 A5）



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

-- （原 `processing_rules` 的 RLS + 策略随该表一并删除，issue #5245 A5）

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

-- 批量更新的批次资源（V127，issue #5314）—— 跨租户不可见是契约判据之一
ALTER TABLE agent_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_batches ON agent_batches
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE agent_batch_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_batch_items ON agent_batch_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- 发货单 + 发货明细（V132，issue #5648）—— 跨租户不可见是契约判据之一
ALTER TABLE order_shipments ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_shipments ON order_shipments
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

ALTER TABLE order_shipment_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_order_shipment_items ON order_shipment_items
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- 企业参数变更留痕（V131，issue #5131 §22 P6）—— 跨租户不可见
ALTER TABLE tenant_param_audit ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tenant_param_audit ON tenant_param_audit
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

-- ⚠️ 本段（V60 信号种子 + V63 终态修正）**必须排在租户种子之后**（issue #4762）。
-- 它引用 `production_route_signals_tenant_id_fkey → tenants(id)`；本文件曾把它放在第 9 节
-- （`processing_fee_combination_versions` 之后），那时租户种子还没跑 ⇒ `ON_ERROR_STOP=1`
-- 下建库**在这里中止**（`docker-entrypoint-initdb.d/001_schema.sql` 正是该模式：entrypoint 带
-- `-v ON_ERROR_STOP=1`，而 `deploy/docker-compose.yml` 把本文件挂成该 initdb 脚本）
-- ⇒ 本地/CI docker 栈建库中止。守卫：tests/unit_ci_workflows/test_schema_bootstrap_order.py
-- （机械判据 = `ON_ERROR_STOP=1` 跑全文 exit 0 + 零 ERROR + 本段落真跑到）。
-- ⚠️ 本段**只调顺序、内容一字未改**；`UPDATE` 必须紧随 `INSERT`（它的 WHERE 命中的正是
-- `INSERT` 刚种下的 `四爪钩/四叉钩` 两行，分开 = 终态漂移）。

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
-- 工序库 / 工艺路线模板种子（V54，issue #4116 P0-2）
-- ================================================
-- 为什么 schema.sql 里也要有：本文件是**全新库的一次性 bootstrap**（CI/本地 docker 栈由
-- docker-entrypoint-initdb.d 执行），而 **MigrationRunner/Flyway 不在该栈运行** —— 只存在于
-- 迁移链的种子在新建库上并不存在（同第 11 节 bootstrap 对齐段的既有教训）。
-- 内容与 V54__seed_production_operations.sql 逐字同口径；三源漂移由测试守
-- （tests/unit_ci_workflows/test_production_catalog_seed.py：V54 ∪ V56 ↔ 本文件 ↔ routing.py 比对）。
-- 🔴 **`is_must_finish` 是唯一的有意分歧列**（issue #4961「必完概念退场」）：冻结的 V54 种子仍留着
-- 历史的 `外帘装袋 = TRUE`（已发布迁移不可改），而**本文件是终态** ⇒ 该列一律 `FALSE`
-- （与迁移链终态一致：存量库由 V107__retire_must_finish_flag.sql 收敛为 FALSE）。
-- 该列已退出跨源逐值比对，改由两条显式判据钉住（冻结种子的历史值 / 终态三源一律 FALSE），
-- 见 tests/unit_ci_workflows/test_production_catalog_seed.py
-- 的 `test_frozen_seed_must_finish_is_the_recorded_history` 与
-- `test_must_finish_is_false_in_every_terminal_source`。
-- 末 5 行（op-v56-*）来自 V56__seed_special_option_operations.sql（issue #4230 特殊选项 A′ 类新增工序）；
-- 本文件是**终态**（全新库一次性 bootstrap）⇒ 两个迁移的内容在此合并且**按 sort_order 连续**，
-- 迁移侧则由 V54（1..30）+ V56（31..35）两段拼成 —— 守卫按**名称 → 值**比对，不依赖行序。
-- 幂等：ON CONFLICT DO NOTHING（冲突目标 = V49 的部分唯一索引，均带 WHERE deleted = 0）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status, deleted)
VALUES
  ('op-v54-01', 1, '精裁-布', '裁剪', '布帘', '米', 0.4, FALSE, TRUE, 1, 'active', 0),
  ('op-v54-02', 1, '精裁-纱', '裁剪', '纱帘', '米', 0.4, FALSE, TRUE, 2, 'active', 0),
  ('op-v54-03', 1, '裁剪-布', '裁剪', '布帘', '米', 0.4, FALSE, FALSE, 3, 'active', 0),
  ('op-v54-04', 1, '裁剪-纱', '裁剪', '纱帘', '米', 0.4, FALSE, FALSE, 4, 'active', 0),
  ('op-v54-05', 1, '布三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 5, 'active', 0),
  ('op-v54-06', 1, '纱三边', '车位', NULL, '米', 0.4, FALSE, FALSE, 6, 'active', 0),
  ('op-v54-07', 1, '韩褶-布', '车位', '布帘', '折', 0.4, FALSE, FALSE, 7, 'active', 0),
  ('op-v54-08', 1, '韩褶-纱', '车位', '纱帘', '折', 0.4, FALSE, FALSE, 8, 'active', 0),
  ('op-v54-09', 1, '上车布-布', '车位', '布帘', '米', 0.5, FALSE, FALSE, 9, 'active', 0),
  ('op-v54-10', 1, '上车布-纱', '车位', '纱帘', '米', 0.5, FALSE, FALSE, 10, 'active', 0),
  ('op-v54-11', 1, '打孔-布', '车位', '布帘', '孔', 0.15, FALSE, FALSE, 11, 'active', 0),
  ('op-v54-12', 1, '打孔-纱', '车位', '纱帘', '孔', 0.15, FALSE, FALSE, 12, 'active', 0),
  ('op-v54-13', 1, '拼1次-布', '车位', '布帘', '幅', 0.8, FALSE, FALSE, 13, 'active', 0),
  ('op-v54-14', 1, '拼2次-布', '车位', '布帘', '幅', 1.2, FALSE, FALSE, 14, 'active', 0),
  ('op-v54-15', 1, '拼3次-布', '车位', '布帘', '幅', 1.6, FALSE, FALSE, 15, 'active', 0),
  ('op-v54-16', 1, '花边-布', '车位', '布帘', '米', 0.6, FALSE, FALSE, 16, 'active', 0),
  ('op-v54-17', 1, '铅坠-布', '车位', '布帘', '米', 0.3, FALSE, FALSE, 17, 'active', 0),
  ('op-v54-18', 1, '接高-布', '车位', '布帘', '幅', 1.0, FALSE, FALSE, 18, 'active', 0),
  ('op-v54-19', 1, '帘头制作', '车位', '帘头', '个', 2.0, FALSE, FALSE, 19, 'active', 0),
  ('op-v54-20', 1, '熨烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 20, 'active', 0),
  ('op-v54-21', 1, '定型-布', '后道', '布帘', '米', 0.4, FALSE, FALSE, 21, 'active', 0),
  ('op-v54-22', 1, '复烫-布', '后道', '布帘', '米', 0.35, FALSE, FALSE, 22, 'active', 0),
  ('op-v54-23', 1, '布帘车被', '后道', NULL, '米', 0.4, FALSE, FALSE, 23, 'active', 0),
  ('op-v54-24', 1, '外帘打卷', '后道', '外帘', '套', 1.0, FALSE, FALSE, 24, 'active', 0),
  ('op-v54-25', 1, '外帘装袋', '后道', '外帘', '套', 1.0, FALSE, FALSE, 25, 'active', 0),
  ('op-v54-26', 1, '质检', '后道', NULL, '套', 1.5, FALSE, FALSE, 26, 'active', 0),
  ('op-v54-27', 1, '外帘发货', '后道', '外帘', '套', 1.0, FALSE, FALSE, 27, 'active', 0),
  ('op-v54-28', 1, '绑带-布', '其他', '布帘', '套', 0.5, FALSE, FALSE, 28, 'active', 0),
  ('op-v54-29', 1, '抱枕', '其他', NULL, '个', 2.0, FALSE, FALSE, 29, 'active', 0),
  ('op-v54-30', 1, '腰靠垫', '其他', NULL, '个', 2.0, FALSE, FALSE, 30, 'active', 0),
  ('op-v56-01', 1, '绑带-纱', '其他', NULL, '套', 0.5, FALSE, FALSE, 31, 'active', 0),
  ('op-v56-02', 1, 'logo条-布', '车位', NULL, '米', 0.6, FALSE, FALSE, 32, 'active', 0),
  ('op-v56-03', 1, '立边-布', '车位', NULL, '米', 0.5, FALSE, FALSE, 33, 'active', 0),
  ('op-v56-04', 1, '扣环-布', '车位', NULL, '个', 0.3, FALSE, FALSE, 34, 'active', 0),
  ('op-v56-05', 1, '防翘扣-布', '车位', NULL, '个', 0.2, FALSE, FALSE, 35, 'active', 0),
  -- 末 2 行（op-v79-*）来自 V79__seed_fabric_route_and_packing_operation.sql（issue #4529 包 F）：
  -- `配料`（布料单前道，单位 = 米）/ `打包`（跨产品形态的**套级**工序，单位 = 套）。
  -- ⚠️ 单价 0 是 `production_operations.unit_price NOT NULL DEFAULT 0` 的产物，**不是定价 0**：
  -- 「未定价」由部位价目行的 `unit_price = NULL + applicable = TRUE` 承载（见下方 120 行种子）。
  -- 🔴 `配料` 行**直接种成软删态**（`deleted = 1`）：V88（issue #4676）在迁移链上把它软删 ⇒ 本文件
  -- 是**终态**（全新库不跑迁移链），必须与迁移链终态**逐项一致**，否则新建库与迁移库口径分裂
  -- （`配料` 会出现在新单实例里 = 设计 S6）。行**保留**（不删行）⇒ 留痕可审计、回滚可认领
  -- （同下方 `production_route_rules` 的系数档软删口径）。
  ('op-v79-01', 1, '配料', '后道', NULL, '米', 0, FALSE, FALSE, 36, 'active', 1),
  ('op-v79-02', 1, '打包', '后道', NULL, '套', 0, FALSE, FALSE, 37, 'active', 0),
  -- ── issue #4937（去部位化彻底版）：补 **4 道纱帘变体**（`deleted = 0`）──
  -- 病根：`buildRoute` 原来靠 `applicable` 过滤把 `熨烫/定型/复烫/车被` 从**纱帘**路线上滤掉；
  -- 该过滤退场后，这 4 道会进入纱帘主线的实例化路径 —— 而工序库里**没有**它们的纱帘变体
  -- ⇒ `variantNameOf` 返回 `null` ⇒ **整张纱帘单 fail-closed**（一张也建不出来）。
  -- ⇒ 补齐变体行（单价逐字与对应 `-布` 变体相同 —— **不发明单价**；
  --    分组/单位取对应 `-布` 变体的值：后道 / 米）。
  -- ⚠️ 这 4 行**只**进 `production_operations`（工序库 = 「这道工序在哪个帘种上有变体」）——
  --    **不进** `production_operation_positions` 的价目矩阵：矩阵已按 O4 塌缩为「一道逻辑工序一行」，
  --    且价目行的键是**逻辑工序**（`熨烫`/`定型`/`复烫`/`车被` 都已有那一行）。
  -- 核验 = `RoutingModelFixture`（Java 测试夹具的工序库行）与
  -- `tests/test_production/test_route_model_v2.py`（Python 侧的实例化路径）两侧同口径。
  ('op-v54-31', 1, '熨烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 38, 'active', 0),
  ('op-v54-32', 1, '定型-纱', '后道', '纱帘', '米', 0.4, FALSE, FALSE, 39, 'active', 0),
  ('op-v54-33', 1, '复烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 40, 'active', 0),
  ('op-v54-34', 1, '车被-纱', '后道', '纱帘', '米', 0.4, FALSE, FALSE, 41, 'active', 0)
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
        WHEN id LIKE 'op-v79-%' THEN '占位待确认'
    END
WHERE source IS NULL
  AND (id LIKE 'op-v54-%' OR id LIKE 'op-v56-%' OR id LIKE 'op-v79-%');

-- 工序作用域回填（V67，issue #4384 A1；`打包` 由 V79 / issue #4529 追加）：与迁移
-- **逐字同集合** —— 三道外帘工序 + `打包` 是套级（每樘窗一次），其余全部由列默认值 'position'
-- 兜住。幂等（重复执行写同样的值 = 语义空操作）。
-- bootstrap 的种子 INSERT 不带 scope 列 ⇒ 必须在此显式回填，否则新建库这几道会被当成部位级
-- （= 双付病根在全新库里原样复活）。
UPDATE production_operations
SET scope = 'set'
WHERE name IN ('外帘打卷', '外帘装袋', '外帘发货', '打包');

UPDATE production_routings
SET source = CASE
        WHEN id LIKE 'rt-v54-%' THEN '占位待确认'
        WHEN id LIKE 'rt-v58-%' THEN '推算'
    END
WHERE source IS NULL
  AND (id LIKE 'rt-v54-%' OR id LIKE 'rt-v58-%');

-- 单价版本回填（V55，issue #4204）：每条活跃工序一行初始版本 ⇒ 「当前价 = 最新版本行」对存量数据成立。
-- 必须放在工序库种子**之后**；幂等（已有版本行的工序跳过 + ON CONFLICT 兜底）。
-- ⚠️ **本段必须留在所有 `production_operations` 写语句之后**（issue #4741）：迁移链上
-- V55 派生**之后**才进库的工序（V79/V89 的 `打包`、V91 的 36 道基线工序）在迁移侧由
-- `V96__backfill_operation_price_versions.sql` 补账；本文件是 bootstrap **终态**（不跑迁移链）
-- ⇒ 只要本段在最后，bootstrap 建出的库就**已经是终态**，**不再复制一份派生语句**
-- （复制 = 多一份会漂移的口径）。守卫 = tests/unit_ci_workflows/test_v96_operation_price_versions_backfill.py
-- （顺序判据 + 真跑本文件核「活跃工序缺账 = 0」）。
INSERT INTO production_operation_price_versions (id, tenant_id, operation_id, unit_price, created_at)
SELECT 'pv-' || o.id, o.tenant_id, o.id, o.unit_price, NOW()
FROM production_operations o
WHERE o.deleted = 0
  AND NOT EXISTS (
      SELECT 1 FROM production_operation_price_versions v
      WHERE v.operation_id = o.id AND v.deleted = 0
  )
ON CONFLICT (id) DO NOTHING;

-- ── 工序路线模型重构 P1 的三张新表种子（V71，issue #4427 = 母单 #4423 P1/3；V79 / #4529 扩到 120 行 + 2 条路线）──
-- 与 V71__normalize_routing_model_structure.sql / V79__seed_fabric_route_and_packing_operation.sql
-- **逐行逐值**同口径（三源收敛守卫：tests/unit_ci_workflows/test_production_catalog_seed.py 按内容发现种子源）。
-- 内容 = **120 行部位价目**（30 道逻辑工序 × 4 部位，逐行显式 applicable；第 4 部位 = `布料`）
-- + **2 行具名路线**（窗帘默认 + 布料）+ 26 行规则（工艺变体 10 + 特殊选项 16）。
-- 幂等：ON CONFLICT (id) DO NOTHING。
-- ⚠️ 与旧种子段的关系：**纯增量** —— production_operations / production_routings 的种子只**追加**。
--
-- 🔴🔴 **本段的 `position` / `applicable` / `deleted` 列写的是「去部位化彻底版」之后的终态**
-- （issue #4937 = 母单 #4936；用户裁定 2026-09-21「我们移除了部位的设计，**不计成本的改**」）🔴🔴
-- 本文件是**全新库的一次性 bootstrap**（docker-entrypoint-initdb.d），而该栈**不跑迁移链**
-- ⇒ 本文件必须**一次给全终态**。逐项对齐三条新迁移：
--   · `V102__retire_applicability_flag.sql`  → 「已是 `TRUE`」的存活行写全 `updated_at`
--     （⚠️ 它**不**把 `FALSE` 一刀切置 TRUE：那会抹掉 V104 选行所需的信号 ⇒
--      `帘头制作` 的 ¥2.00 会被判成未定价，工人白干，见该文件头的「口径陷阱」）；
--   · `V103__clear_route_rule_positions.sql` → 存活规则的 `position` 清空为 `NULL`
--     （本段 `rr-v70-*` 的 26 行**字面量已写 NULL**；`rr-v93-*` 的 VALUES 段仍是 V71 口径的
--      `'布帘'`，由 V103 在运行时清空 —— 那里保持与 V71 逐字同款，供三源收敛守卫比对）；
--     🔴 **事实订正（issue #4962，2026-09-21）**：上一句只是 **V103 当时**的口径，**保留不删**（历史）。
--     V103 之后新增 `V108__restore_route_rule_positions.sql`，它把**唯一**那条部位限定写回
--     ——即本段 `rr-v70-02` 那一行的 `position` 字面量已同步为 `'布帘'`⇒
--     **本段 26 行里有且只有 1 行非 `NULL`**（`rr-v70-02`；其余 25 行仍 `NULL`），以本行为准。
--     两条路径的终态由 `tests/unit_ci_workflows/test_restore_route_rule_positions_migration.py` 逐值比对。
--   · `V104__deposition_matrix_collapse.sql` → 每个 `(tenant_id, logical_name)` **只留一行**：
--       幸存行 = 四档选行规则（适用行 → **布帘**列 → `position` 字典序 → `id` 升序）；
--       幸存行写 `position = '通用'`（中性值；该列**仅作历史载体**）+ `applicable = TRUE`；
--       其余 **90 行** `deleted = 1`（**软删**，不物理删 —— V86 的调价账仍按 `row_id` 指向它们）。
--   ⇒ **存活 30 行**（每逻辑工序一行，部位维退场）+ **退场 90 行**；120 = 30 + 90（可机械核验）。
-- ⚠️ **行数一字未减**（仍是 V71 ∪ V79 的 120 行字面量）：退场只靠显式 `deleted` 表达
--    —— 直接删行会让「bootstrap ↔ 迁移链」的行集合不可比对（守卫只能退化成「只比对存活行」，
--    漏掉「行整个消失」这一形态）。守卫 = `tests/unit_ci_workflows/test_deposition_total_migration.py`
--    的 `test_bootstrap_matches_migration_chain_terminal_state`（真库跑三迁移 + 解析本文件逐值比对，
--    红证见同文件 `test_v102_claim_is_observable_…`）。
-- ⚠️ 若只改迁移不改本文件 ⇒ **新建库仍是旧口径**（120 行全活 / `position` 还是部位名）
--    ⇒ 迁移库与新库**两套口径**（本仓最忌）。

INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status, deleted)
VALUES
  ('opp-v70-01', 1, '精裁', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-02', 1, '精裁', '纱帘', 0.4, TRUE, 'active', 1),
  ('opp-v70-03', 1, '精裁', '帘头', 0.4, TRUE, 'active', 1),
  ('opp-v70-04', 1, '裁剪', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-05', 1, '裁剪', '纱帘', 0.4, TRUE, 'active', 1),
  ('opp-v70-06', 1, '裁剪', '帘头', 0.4, TRUE, 'active', 1),
  ('opp-v70-07', 1, '三边', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-08', 1, '三边', '纱帘', 0.4, TRUE, 'active', 1),
  ('opp-v70-09', 1, '三边', '帘头', 0.4, TRUE, 'active', 1),
  ('opp-v70-10', 1, '韩褶', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-11', 1, '韩褶', '纱帘', 0.4, TRUE, 'active', 1),
  ('opp-v70-12', 1, '韩褶', '帘头', 0.4, TRUE, 'active', 1),
  ('opp-v70-13', 1, '上车布', '通用', 0.5, TRUE, 'active', 0),
  ('opp-v70-14', 1, '上车布', '纱帘', 0.5, TRUE, 'active', 1),
  ('opp-v70-15', 1, '上车布', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-16', 1, '打孔', '通用', 0.15, TRUE, 'active', 0),
  ('opp-v70-17', 1, '打孔', '纱帘', 0.15, TRUE, 'active', 1),
  ('opp-v70-18', 1, '打孔', '帘头', 0.15, TRUE, 'active', 1),
  ('opp-v70-19', 1, '拼1次', '通用', 0.8, TRUE, 'active', 0),
  ('opp-v70-20', 1, '拼1次', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-21', 1, '拼1次', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-22', 1, '拼2次', '通用', 1.2, TRUE, 'active', 0),
  ('opp-v70-23', 1, '拼2次', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-24', 1, '拼2次', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-25', 1, '拼3次', '通用', 1.6, TRUE, 'active', 0),
  ('opp-v70-26', 1, '拼3次', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-27', 1, '拼3次', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-28', 1, '花边', '通用', 0.6, TRUE, 'active', 0),
  ('opp-v70-29', 1, '花边', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-30', 1, '花边', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-31', 1, '铅坠', '通用', 0.3, TRUE, 'active', 0),
  ('opp-v70-32', 1, '铅坠', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-33', 1, '铅坠', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-34', 1, '接高', '通用', 1.0, TRUE, 'active', 0),
  ('opp-v70-35', 1, '接高', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-36', 1, '接高', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-37', 1, '帘头制作', '布帘', NULL, FALSE, 'active', 1),
  ('opp-v70-38', 1, '帘头制作', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-39', 1, '帘头制作', '通用', 2.0, TRUE, 'active', 0),
  ('opp-v70-40', 1, '熨烫', '通用', 0.35, TRUE, 'active', 0),
  ('opp-v70-41', 1, '熨烫', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-42', 1, '熨烫', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-43', 1, '定型', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-44', 1, '定型', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-45', 1, '定型', '帘头', 0.4, TRUE, 'active', 1),
  ('opp-v70-46', 1, '复烫', '通用', 0.35, TRUE, 'active', 0),
  ('opp-v70-47', 1, '复烫', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-48', 1, '复烫', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-49', 1, '车被', '通用', 0.4, TRUE, 'active', 0),
  ('opp-v70-50', 1, '车被', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-51', 1, '车被', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-52', 1, '外帘打卷', '通用', 1.0, TRUE, 'active', 0),
  ('opp-v70-53', 1, '外帘打卷', '纱帘', 1.0, TRUE, 'active', 1),
  ('opp-v70-54', 1, '外帘打卷', '帘头', 1.0, TRUE, 'active', 1),
  ('opp-v70-55', 1, '外帘装袋', '通用', 1.0, TRUE, 'active', 0),
  ('opp-v70-56', 1, '外帘装袋', '纱帘', 1.0, TRUE, 'active', 1),
  ('opp-v70-57', 1, '外帘装袋', '帘头', 1.0, TRUE, 'active', 1),
  ('opp-v70-58', 1, '质检', '通用', 1.5, TRUE, 'active', 0),
  ('opp-v70-59', 1, '质检', '纱帘', 1.5, TRUE, 'active', 1),
  ('opp-v70-60', 1, '质检', '帘头', 1.5, TRUE, 'active', 1),
  ('opp-v70-61', 1, '外帘发货', '通用', 1.0, TRUE, 'active', 0),
  ('opp-v70-62', 1, '外帘发货', '纱帘', 1.0, TRUE, 'active', 1),
  ('opp-v70-63', 1, '外帘发货', '帘头', 1.0, TRUE, 'active', 1),
  ('opp-v70-64', 1, '绑带', '通用', 0.5, TRUE, 'active', 0),
  ('opp-v70-65', 1, '绑带', '纱帘', 0.5, TRUE, 'active', 1),
  ('opp-v70-66', 1, '绑带', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-67', 1, '抱枕', '通用', 2.0, TRUE, 'active', 0),
  ('opp-v70-68', 1, '抱枕', '纱帘', 2.0, TRUE, 'active', 1),
  ('opp-v70-69', 1, '抱枕', '帘头', 2.0, TRUE, 'active', 1),
  ('opp-v70-70', 1, '腰靠垫', '通用', 2.0, TRUE, 'active', 0),
  ('opp-v70-71', 1, '腰靠垫', '纱帘', 2.0, TRUE, 'active', 1),
  ('opp-v70-72', 1, '腰靠垫', '帘头', 2.0, TRUE, 'active', 1),
  ('opp-v70-73', 1, 'logo条', '通用', 0.6, TRUE, 'active', 0),
  ('opp-v70-74', 1, 'logo条', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-75', 1, 'logo条', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-76', 1, '立边', '通用', 0.5, TRUE, 'active', 0),
  ('opp-v70-77', 1, '立边', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-78', 1, '立边', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-79', 1, '扣环', '通用', 0.3, TRUE, 'active', 0),
  ('opp-v70-80', 1, '扣环', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-81', 1, '扣环', '帘头', NULL, FALSE, 'active', 1),
  ('opp-v70-82', 1, '防翘扣', '通用', 0.2, TRUE, 'active', 0),
  ('opp-v70-83', 1, '防翘扣', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v70-84', 1, '防翘扣', '帘头', NULL, FALSE, 'active', 1),
  -- ── issue #4529（包 F）：第 4 个部位 `布料` 的 28 行（逐行显式 FALSE）+ 新增两道工序 ──
  -- 84 + 36 = **120 行**（30 逻辑工序 × 4 部位）。与 V79 逐行逐值同口径。
  ('opp-v79-01', 1, '精裁', '布料', NULL, FALSE, 'active', 1),
  -- 🔴 **保命格**（V88 ④ / 设计 F3）：`裁剪 × 布料` 的 `applicable` 必须是 **TRUE**。
  -- 依据：**未实例化**的存量布料单走「补生成工序」时会按**当前配置**重算 ⇒ 这一格退场会让
  -- 存量单静默少一道（`buildRoute` 查不到键 ⇒ 静默 `continue`，不报错）。
  -- 单价仍是 `NULL`（「适用但未定价」）⇒ 实例化时回落 `production_operations.unit_price`（`裁剪-布` = 0.4）。
  ('opp-v79-02', 1, '裁剪', '布料', NULL, TRUE, 'active', 1),
  ('opp-v79-03', 1, '三边', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-04', 1, '韩褶', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-05', 1, '上车布', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-06', 1, '打孔', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-07', 1, '拼1次', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-08', 1, '拼2次', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-09', 1, '拼3次', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-10', 1, '花边', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-11', 1, '铅坠', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-12', 1, '接高', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-13', 1, '帘头制作', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-14', 1, '熨烫', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-15', 1, '定型', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-16', 1, '复烫', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-17', 1, '车被', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-18', 1, '外帘打卷', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-19', 1, '外帘装袋', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-20', 1, '质检', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-21', 1, '外帘发货', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-22', 1, '绑带', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-23', 1, '抱枕', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-24', 1, '腰靠垫', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-25', 1, 'logo条', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-26', 1, '立边', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-27', 1, '扣环', '布料', NULL, FALSE, 'active', 1),
  ('opp-v79-28', 1, '防翘扣', '布料', NULL, FALSE, 'active', 1),
  -- 🔴 `配料 × 4 部位` 直接种成**软删态**（`deleted = 1`）：V88 ②（issue #4676）在迁移链上把
  -- `logical_name = '配料'` 的 4 格一并软删 ⇒ 本文件是终态（新建库不跑迁移链），必须与之一致。
  -- 行**保留**（不删行）= 留痕可审计 + 回滚可认领（同 `production_operations` 的 `配料` 行口径）。
  ('opp-v79-29', 1, '配料', '通用', NULL, TRUE, 'active', 0),
  ('opp-v79-30', 1, '配料', '布帘', NULL, FALSE, 'active', 1),
  ('opp-v79-31', 1, '配料', '纱帘', NULL, FALSE, 'active', 1),
  ('opp-v79-32', 1, '配料', '帘头', NULL, FALSE, 'active', 1),
  -- `打包` 4 格（V88 ⑦ 一字不动：交付工序的格**绝不能用「删格」实现**）—— `deleted = 0` 显式写全。
  ('opp-v79-33', 1, '打包', '通用', NULL, TRUE, 'active', 0),
  ('opp-v79-34', 1, '打包', '纱帘', NULL, TRUE, 'active', 1),
  ('opp-v79-35', 1, '打包', '帘头', NULL, TRUE, 'active', 1),
  ('opp-v79-36', 1, '打包', '布料', NULL, TRUE, 'active', 1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
VALUES
  ('rt-v70-01', 1, '窗帘工序路线（默认）', TRUE,
   '["布帘", "纱帘", "帘头"]'::jsonb,
   '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"]'::jsonb,
   'active'),
  -- 第 2 条基础路线（V79，issue #4529 包 F）：布料单专用，`is_default=FALSE`
  -- （每租户**恰好一条**默认 —— 部分唯一索引 uk_production_route_templates_tenant_default 保证）。
  -- 🔴 主线是 **V88 ③ 之后的终态** `["裁剪", "打包"]`（V88 在迁移链上把 `配料` 手术式替换成 `裁剪`；
  -- 用户裁定逐字「布料单该用 **裁剪**」）—— 本文件是终态，必须与迁移链终态**逐项一致**。
  -- ⚠️ 模板本身**必须保留**（`positions = ["布料"]`）：删它会让 `routeTemplateFor` 返回 null
  -- ⇒ T2 回落默认路线（窗帘 10 道）⇒ 布料单**多出**一堆窗帘工序（更糟）。
  ('rt-v79-01', 1, '布料工序路线', FALSE,
   '["布料"]'::jsonb,
   '["裁剪", "打包"]'::jsonb,
   'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
VALUES
  ('rr-v70-01', 1, 'craft', '韩褶', NULL, 'insert', '韩褶', '三边', 10, 'active'),
  ('rr-v70-02', 1, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, 'active'),
  ('rr-v70-03', 1, 'craft', '打孔', NULL, 'insert', '打孔', '三边', 30, 'active'),
  ('rr-v70-04', 1, 'craft', '四爪钩', NULL, 'insert', '上车布', '三边', 40, 'active'),
  ('rr-v70-05', 1, 'craft', '四爪钩', NULL, 'remove', '定型', NULL, 50, 'active'),
  ('rr-v70-06', 1, 'craft', '四爪钩', NULL, 'remove', '复烫', NULL, 60, 'active'),
  ('rr-v70-07', 1, 'craft', '穿杆', NULL, 'remove', '定型', NULL, 70, 'active'),
  ('rr-v70-08', 1, 'craft', '穿杆', NULL, 'remove', '复烫', NULL, 80, 'active'),
  ('rr-v70-09', 1, 'craft', '平幔', NULL, 'insert', '帘头制作', '三边', 90, 'active'),
  ('rr-v70-10', 1, 'craft', '平幔', NULL, 'remove', '复烫', NULL, 100, 'active'),
  ('rr-v70-11', 1, 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110, 'active'),
  ('rr-v70-12', 1, 'option', '拼2次', NULL, 'insert', '拼2次', '三边', 120, 'active'),
  ('rr-v70-13', 1, 'option', '拼3次', NULL, 'insert', '拼3次', '三边', 130, 'active'),
  ('rr-v70-14', 1, 'option', '加花边', NULL, 'insert', '花边', '三边', 140, 'active'),
  ('rr-v70-15', 1, 'option', '加铅块', NULL, 'insert', '铅坠', '三边', 150, 'active'),
  ('rr-v70-16', 1, 'option', '接高', NULL, 'insert', '接高', '精裁', 160, 'active'),
  ('rr-v70-17', 1, 'option', '双眼皮接高', NULL, 'insert', '接高', '精裁', 170, 'active'),
  ('rr-v70-18', 1, 'option', '余料做绑带', NULL, 'insert', '绑带', '车被', 180, 'active'),
  ('rr-v70-19', 1, 'option', '布绑带', NULL, 'insert', '绑带', '车被', 190, 'active'),
  ('rr-v70-20', 1, 'option', '余料做帘头', NULL, 'insert', '帘头制作', '三边', 200, 'active'),
  ('rr-v70-21', 1, 'option', '抱枕', NULL, 'insert', '抱枕', '外帘打卷', 210, 'active'),
  ('rr-v70-22', 1, 'option', '纱绑带', NULL, 'insert', '绑带', '车被', 220, 'active'),
  ('rr-v70-23', 1, 'option', '加logo条', NULL, 'insert', 'logo条', '三边', 230, 'active'),
  ('rr-v70-24', 1, 'option', '加立边', NULL, 'insert', '立边', '三边', 240, 'active'),
  ('rr-v70-25', 1, 'option', '扣环', NULL, 'insert', '扣环', '三边', 250, 'active'),
  ('rr-v70-26', 1, 'option', '防翘扣', NULL, 'insert', '防翘扣', '三边', 260, 'active')
ON CONFLICT (id) DO NOTHING;

-- ── 工序路线模型重构 P2 的终态种子（V72，issue #4432 = 母单 #4423 P2/3）──
-- 与 V72__switch_routing_model_consumers.sql **同口径**：按租户循环（`FROM tenants`）为**每一个**
-- 活跃租户补齐三张新表 + 默认工艺 —— 不做 ⇒ 切换消费路径那一刻，非 1 号租户
-- `defaultRouteTemplate=null` ⇒ `resolveRoute` T3 fail-closed ⇒ 一张加工单也生成不了（#4316 同族）。
-- 幂等：`ON CONFLICT DO NOTHING` + `NOT EXISTS` 按业务唯一键去重（1 号租户 V71 已种过 ⇒ 跳过）。
-- 口径：价目/适用性 ← V71 的规范矩阵（84 行）；主线/规则/默认工艺 ← **该租户自己的**
-- `production_operations`（判据 17：不是从 1 号租户复制 —— 那会把客户改过的价复刻给别人）。
INSERT INTO production_crafts (id, tenant_id, name, is_default, status)
SELECT 'pc-v72-' || t.id, t.id,
       COALESCE(
           (SELECT c.name
              FROM unnest(ARRAY['韩褶', '打孔', '四爪钩', '穿杆', '平幔']) WITH ORDINALITY AS c(name, ord)
             WHERE EXISTS (
                 SELECT 1 FROM production_operations o
                  WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active'
                    AND (CASE
                             WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                             WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                             WHEN o.name = '布三边' THEN '三边'
                             WHEN o.name = '纱三边' THEN '三边'
                             WHEN o.name = '布帘车被' THEN '车被'
                             WHEN o.name = '帘头制作' THEN '帘头制作'
                             WHEN o.name = '上车布-布' THEN '上车布'
                             WHEN o.name = '上车布-纱' THEN '上车布'
                             ELSE o.name END) = c.name)
             ORDER BY c.ord LIMIT 1),
           '韩褶'),
       TRUE, 'active'
  FROM tenants t
 WHERE t.deleted = 0
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
SELECT 'opp-v72-' || t.id || '-' || p.logical_name || '-' || p.position,
       t.id, p.logical_name, p.position, p.unit_price, p.applicable, 'active'
  FROM tenants t
  JOIN production_operation_positions p
    ON p.tenant_id = 1 AND p.deleted = 0 AND p.id LIKE 'opp-v70-%'
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_positions e
        WHERE e.tenant_id = t.id AND e.logical_name = p.logical_name
          AND e.position = p.position AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
SELECT 'rt-v72-' || t.id, t.id, '窗帘工序路线（默认）', TRUE,
       '["布帘", "纱帘", "帘头"]'::jsonb,
       COALESCE(
           (SELECT jsonb_agg(s.step ORDER BY s.ord)
              FROM unnest(ARRAY['精裁', '三边', '熨烫', '定型', '复烫', '车被',
                                '外帘打卷', '外帘装袋', '外帘发货']) WITH ORDINALITY AS s(step, ord)
             WHERE s.step IN (
                 SELECT CASE
                     WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name = '布三边' THEN '三边'
                     WHEN o.name = '纱三边' THEN '三边'
                     WHEN o.name = '布帘车被' THEN '车被'
                     WHEN o.name = '帘头制作' THEN '帘头制作'
                     WHEN o.name = '上车布-布' THEN '上车布'
                     WHEN o.name = '上车布-纱' THEN '上车布'
                     ELSE o.name END
                   FROM production_operations o
                  WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active')),
           '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]'::jsonb),
       'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_route_templates e
        WHERE e.tenant_id = t.id AND e.name = '窗帘工序路线（默认）' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status)
SELECT 'rr-v72-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       r.position, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'craft', '韩褶', NULL, 'insert', '韩褶', '三边', 10),
      ('02', 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20),
      ('03', 'craft', '打孔', NULL, 'insert', '打孔', '三边', 30),
      ('04', 'craft', '四爪钩', NULL, 'insert', '上车布', '三边', 40),
      ('05', 'craft', '四爪钩', NULL, 'remove', '定型', NULL, 50),
      ('06', 'craft', '四爪钩', NULL, 'remove', '复烫', NULL, 60),
      ('07', 'craft', '穿杆', NULL, 'remove', '定型', NULL, 70),
      ('08', 'craft', '穿杆', NULL, 'remove', '复烫', NULL, 80),
      ('09', 'craft', '平幔', NULL, 'insert', '帘头制作', '三边', 90),
      ('10', 'craft', '平幔', NULL, 'remove', '复烫', NULL, 100),
      ('11', 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110),
      ('12', 'option', '拼2次', NULL, 'insert', '拼2次', '三边', 120),
      ('13', 'option', '拼3次', NULL, 'insert', '拼3次', '三边', 130),
      ('14', 'option', '加花边', NULL, 'insert', '花边', '三边', 140),
      ('15', 'option', '加铅块', NULL, 'insert', '铅坠', '三边', 150),
      ('16', 'option', '接高', NULL, 'insert', '接高', '精裁', 160),
      ('17', 'option', '双眼皮接高', NULL, 'insert', '接高', '精裁', 170),
      ('18', 'option', '余料做绑带', NULL, 'insert', '绑带', '车被', 180),
      ('19', 'option', '布绑带', NULL, 'insert', '绑带', '车被', 190),
      ('20', 'option', '余料做帘头', NULL, 'insert', '帘头制作', '三边', 200),
      ('21', 'option', '抱枕', NULL, 'insert', '抱枕', '外帘打卷', 210),
      ('22', 'option', '纱绑带', NULL, 'insert', '绑带', '车被', 220),
      ('23', 'option', '加logo条', NULL, 'insert', 'logo条', '三边', 230),
      ('24', 'option', '加立边', NULL, 'insert', '立边', '三边', 240),
      ('25', 'option', '扣环', NULL, 'insert', '扣环', '三边', 250),
      ('26', 'option', '防翘扣', NULL, 'insert', '防翘扣', '三边', 260)
  ) AS r(rid, trigger_kind, trigger_value, position, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   AND EXISTS (
       SELECT 1 FROM production_operations o
        WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active'
          AND (CASE
                   WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name = '布三边' THEN '三边'
                   WHEN o.name = '纱三边' THEN '三边'
                   WHEN o.name = '布帘车被' THEN '车被'
                   WHEN o.name = '帘头制作' THEN '帘头制作'
                   WHEN o.name = '上车布-布' THEN '上车布'
                   WHEN o.name = '上车布-纱' THEN '上车布'
                   ELSE o.name END) = r.operation)
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND COALESCE(e.position, '') = COALESCE(r.position, '')
          AND e.action = r.action AND e.operation = r.operation)
ON CONFLICT (id) DO NOTHING;

-- ── 特殊选项**对客按套单价**的初始价目（V82，issue #4567；用户裁定 2026-09-19）──
-- 与 `V82__seed_option_customer_unit_price.sql` ① 段**同源同值**（16 项，逐字 trigger_value → 元/套）：
--   · 用户裁定「特殊选项缺乏单价，通常按套收费」「随便初始化一份价格数据，单价是元/套」
--     ⇒ 推翻 V77 的「该列恒 NULL」口径；
--   · ⚠️ 这 16 个值是**占位初始值**且**会真的参与对客取价**（该列无 status 可门控）——**不是测试资产**；
--   · 幂等 + 不覆盖商家改动：只在 `customer_unit_price IS NULL` 时写 ⇒ 重跑空转、商家改过的价不刷回；
--   · 非 `option` 行（工艺变体 / 定型 / 计件系数档 `action='factor'`）一律保持 NULL；
--   · 按租户循环（`FROM tenants`）：只覆盖 1 号租户 ⇒ 其它租户永远没价。
-- bootstrap 路径（docker-entrypoint-initdb.d）**不跑迁移链** ⇒ 此处必须自带终态（否则新建库选项无价，#3270）。
UPDATE production_route_rules
   SET customer_unit_price = v.unit_price,
       updated_at = NOW()
  FROM tenants t,
       (VALUES
           ('拼1次', 3.00),
           ('拼2次', 5.00),
           ('拼3次', 7.00),
           ('加花边', 4.00),
           ('加铅块', 6.00),
           ('接高', 2.50),
           ('双眼皮接高', 5.00),
           ('余料做绑带', 2.00),
           ('布绑带', 3.00),
           ('余料做帘头', 8.00),
           ('抱枕', 12.00),
           ('纱绑带', 3.00),
           ('加logo条', 2.00),
           ('加立边', 4.00),
           ('扣环', 1.50),
           ('防翘扣', 1.50)
       ) AS v(trigger_value, unit_price)
 WHERE t.deleted = 0
   AND production_route_rules.tenant_id = t.id
   AND production_route_rules.deleted = 0
   AND production_route_rules.trigger_kind = 'option'
   AND production_route_rules.action <> 'factor'
   AND production_route_rules.trigger_value = v.trigger_value
   AND production_route_rules.customer_unit_price IS NULL;

-- ⚠️ 原「V72 计件系数档搬进规则表」（`action='factor'`，源 = 旧 `production_option_factors`）
-- 已随删表退场（issue #5245 A4）：源表本体已 DROP（V126），这条 INSERT…SELECT 在**建库时**
-- 必然报 `relation "production_option_factors" does not exist` —— `docker-entrypoint-initdb.d`
-- 的 psql 带 `ON_ERROR_STOP=1` ⇒ **整份建库中止**（#3270 形态）。
-- 终态也不需要它：系数档自 #4589（用户裁定「计件工资 = 数量 × 计件单价，不需要系数」）起
-- **已退场**，下面的软删语句就是把它清零的收口 —— 新建库从此**没有** `action='factor'` 行，
-- 与存量库（V72/V76 搬入 → V87/V89 软删）终态一致。

-- 计件系数档**退场**（V87，issue #4589：用户裁定「计件工资 = 数量 × 计件单价，不考虑系数」）。
-- bootstrap 终态与 `V87__retire_factor_route_rules.sql` **同源同值**：把上面那条 V72 搬进来的
-- `action='factor'` 档**软删**（留痕，不物理删）。**必须写进本文件**：bootstrap 路径
-- （docker-entrypoint-initdb.d）**不跑迁移链** ⇒ 只写迁移 = 新建库仍留着活跃系数档
-- （形状同 #3270：迁移链不在该栈运行）。
-- 列 `production_route_rules.factor` 与历史快照列**保留**（那是当时工资的证据）—— 只是不再参与计算。
UPDATE production_route_rules
   SET deleted = 1,
       updated_at = NOW()
 WHERE action = 'factor'
   AND deleted = 0;

-- 加工项 → 条件工序种子（V84，issue #4577：用户裁定「加工项也触发工序」）。
-- 3 条 `trigger_kind='processing_item'` 规则：花边(270)/扣环(280)/接高(290) —— 触发键 = 订单行
-- `processingInfo.processingItems[].name`，**精确相等**；priority 落在 option 段（110–260）之后、
-- 计件系数档（300）之前。`拼接` / `双眼皮` **刻意不建行**（拼几次由特殊选项表达，理由见 issue #4577）。
-- 本文件是 bootstrap **终态**（该路径不跑迁移链）⇒ 与
-- `V84__seed_processing_item_route_rules.sql` 逐值同款；防漂移 =
-- tests/unit_ci_workflows/test_processing_item_route_rules_seed.py（迁移 ↔ 本文件 ↔ Java 种子服务三源）。
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status)
SELECT 'rr-v84-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       NULL, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'processing_item', '花边', 'insert', '花边', '三边', 270),
      ('02', 'processing_item', '扣环', 'insert', '扣环', '三边', 280),
      ('03', 'processing_item', '接高', 'insert', '接高', '精裁', 290)
  ) AS r(rid, trigger_kind, trigger_value, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   AND EXISTS (
       SELECT 1 FROM production_operations o
        WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active'
          AND (CASE
                   WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name = '布三边' THEN '三边'
                   WHEN o.name = '纱三边' THEN '三边'
                   WHEN o.name = '布帘车被' THEN '车被'
                   WHEN o.name = '帘头制作' THEN '帘头制作'
                   WHEN o.name = '上车布-布' THEN '上车布'
                   WHEN o.name = '上车布-纱' THEN '上车布'
                   ELSE o.name END) = r.operation)
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND e.position IS NULL
          AND e.action = r.action AND e.operation = r.operation)
ON CONFLICT (id) DO NOTHING;

-- ⚠️ 原「特殊选项 → 条件工序 / 计件系数」种子（V59 ∪ V65 改名后的终态形态：16 行条件工序
-- + 1 行计件系数）已随删表退场（issue #5245 A4）—— 两张表本体已 DROP（V126），种子无处可落。
-- 终态形态：`production_route_rules` 的 `trigger_kind='option'` 行（由上面的 V72/V76 等价回填
-- 段按租户生成），真值源仍是 backend/ai-agent-service/app/production/routing.py 的
-- SPECIAL_OPTION_ROUTINGS；判据改指**归档载体**（V59 ∪ V65，逐字节冻结）与真值源逐行逐值比对
-- （见 tests/unit_ci_workflows/test_production_catalog_seed.py 的「已退场收敛面」段），
-- 终态「表已不存在 + 零读取点」由 tests/unit_ci_workflows/test_dropped_db_objects.py 守。

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

-- ⚠️ 原 `processing_items.per_meter_quantity`（V33 加列 / V34 删列 / V41 又加回）已**删列**
-- （issue #5245 A1，2026-09-23 用户裁定）：僵尸列 —— 列在、生产零消费者（DTO / 前端 TS /
-- Agent Python 已全删，无读无写），而建库脚本一直把它建出来 ⇒ 「库里有那一列」本身在
-- 暗示「每米数量」这个已回滚的口径仍然成立（issue #3005 的裁决被列定义推翻）。
-- 存量库由 `V126__drop_zombie_db_objects.sql` 幂等 DROP COLUMN；新建库由本文件不再加列。

-- 加工项**显式声明**的工艺（V78，issue #4452）：路线键「工艺」维的受控来源。
-- NULL = 商家没声明（不是「工艺=空」）⇒ 该维按缺维处理、route_source 显式标注，不猜。
-- 迁移 V78 只加列、**不回填**（按加工项名回填本身就是猜；存量单由 production_route_signals 兜底）。
-- 本行是 bootstrap 终态对齐（bootstrap 路径不跑迁移链；缺列 ⇒ 加工单查询 500，形态见 #3270）。
ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS craft_hint VARCHAR(16);

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

-- ── 加工项目录按 ERP 附件重建的终态种子（V83，用户裁定 2026-09-19）──
-- 与 `V83__seed_processing_item_catalog.sql` **同口径**：按租户循环种「加工费」分类 + 16 项目录
-- （工艺项 5 / 手选特征·单项 8 / 自动推导特征 3）。
-- issue #4882（用户裁定）后目录**已无** `pricing_method` / `unit_price` 两列（V101 删列）⇒
-- 本文件作为**终态** bootstrap 不再写这两列（V83 的历史 INSERT 一字不动，它在迁移链里早于 V101）。
-- 为什么必须同步（不是可选项）：本文件是**全新库的一次性 bootstrap**（该路径**不跑迁移链**）
-- ⇒ 漏同步 ⇒ bootstrap 建库后下单页拿不到加工项目录（形态见 #3270）。
-- 幂等：`NOT EXISTS` 按业务键去重（`processing_items` 无 `(tenant_id, name)` 唯一索引），
-- 已存在同名项（含商家自建/改过的行）⇒ 整行跳过，不 UPDATE、不覆盖。
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-v83-' || t.id || '-fee', t.id, '加工费', 10, 'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM processing_categories e
        WHERE e.tenant_id = t.id AND e.name = '加工费' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

INSERT INTO processing_items
    (id, tenant_id, name, category_id, unit,
     description, craft_hint, status)
SELECT 'pi-v83-' || t.id || '-' || v.seq,
       t.id,
       v.name,
       'pc-v83-' || t.id || '-fee',
       '米',
       v.description,
       v.craft_hint,
       'active'
  FROM tenants t
  JOIN (VALUES
      ('01'::text, '打孔'::text,      '打孔'::varchar(16), 'ERP 加工费项（工艺声明：打孔）'::text),
      ('02'::text, '韩折'::text,      '韩褶'::varchar(16), 'ERP 加工费项（工艺声明：韩褶；名字按 ERP 写「韩折」）'::text),
      ('03'::text, '韩定+S钩'::text,  '韩褶'::varchar(16), 'ERP 加工费项（工艺声明：韩褶）'::text),
      ('04'::text, '穿杆'::text,      '穿杆'::varchar(16), 'ERP 加工费项（工艺声明：穿杆）'::text),
      ('05'::text, '平幔'::text,      '平幔'::varchar(16), 'ERP 加工费项（工艺声明：平幔）'::text),
      ('06'::text, '定型'::text,      NULL::varchar(16),   'ERP 加工费特征（手选；不再由「工艺规格」录入）'::text),
      ('07'::text, '花边'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('08'::text, '扣环'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('09'::text, '接高'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('10'::text, '拼接'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('11'::text, '双眼皮'::text,    NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('12'::text, '缎带'::text,      NULL::varchar(16),   'ERP 加工费单项（独立一行，不成组合）'::text),
      ('13'::text, '换货'::text,      NULL::varchar(16),   'ERP 加工费单项'::text),
      ('14'::text, '超高'::text,      NULL::varchar(16),   '自动推导特征（成品高+卷边 > 门幅）—— 不得手选'::text),
      ('15'::text, '超宽'::text,      NULL::varchar(16),   '自动推导特征（成品宽+卷边 > 门幅）—— 不得手选'::text),
      ('16'::text, '倒幅'::text,      NULL::varchar(16),   '自动推导特征（加工类型=定宽买高）—— 不得手选'::text)
  ) AS v(seq, name, craft_hint, description)
   ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM processing_items e
        WHERE e.tenant_id = t.id AND e.name = v.name AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ── 出厂规则**不带工序库护栏**的按租户重放（V93，issue #4714）──
-- 上面 V72 ⑤ / V84 两条回填都带 `EXISTS (production_operations …)` 护栏 ⇒ 工序库为空的租户
-- **整批规则被静默跳过**（真库实测：租户 20/21 = 0 行）⇒ 韩褶/打孔/四爪钩/穿杆/平幔/特殊选项的
-- 工序静默不出现 = 少一道活、少一笔计件钱且不报错。本段 = 那 29 条出厂规则（V71 的 26 + V84 的 3）
-- 的**按租户重放**，**不带护栏**；工序库由 V91（issue #4707）补。
-- 本文件是 bootstrap **终态**（该路径**不跑迁移链**）⇒ 必须自带这一段，否则 bootstrap 建库后
-- 空工序库租户仍然一条规则都没有（形状同 #3270：迁移链不在该栈运行）。
-- 与 `V93__backfill_route_rules_for_empty_catalogs.sql` 逐值同款；防漂移 =
-- tests/unit_ci_workflows/test_v93_route_rules_backfill.py（迁移 ↔ 本文件 ↔ V71∪V84 三处逐值）。
-- ⚠️ `position` **必须显式落**（`韩褶 × 布帘` 那条是 `布帘`，其余 NULL）—— 本表唯一键含
-- `COALESCE(position,'')`，丢掉它会让 1 号租户（V71 已种 `布帘` 版）**多出一条重复规则**（实测 30 ≠ 29）。
-- 幂等：`NOT EXISTS` 业务键去重（1 号租户已被 V71/V84 种过 ⇒ 整块跳过）+ `ON CONFLICT (id) DO NOTHING`。
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
SELECT 'rr-v93-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       r.position, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'craft', '韩褶',   NULL::varchar, 'insert', '韩褶',     '三边',  10::integer),
      ('02', 'craft', '韩褶',   '布帘'::varchar, 'insert', '上车布', '韩褶',  20::integer),
      ('03', 'craft', '打孔',   NULL::varchar, 'insert', '打孔',     '三边',  30::integer),
      ('04', 'craft', '四爪钩', NULL::varchar, 'insert', '上车布',   '三边',  40::integer),
      ('05', 'craft', '四爪钩', NULL::varchar, 'remove', '定型',     NULL::varchar, 50::integer),
      ('06', 'craft', '四爪钩', NULL::varchar, 'remove', '复烫',     NULL::varchar, 60::integer),
      ('07', 'craft', '穿杆',   NULL::varchar, 'remove', '定型',     NULL::varchar, 70::integer),
      ('08', 'craft', '穿杆',   NULL::varchar, 'remove', '复烫',     NULL::varchar, 80::integer),
      ('09', 'craft', '平幔',   NULL::varchar, 'insert', '帘头制作', '三边',  90::integer),
      ('10', 'craft', '平幔',   NULL::varchar, 'remove', '复烫',     NULL::varchar, 100::integer),
      ('11', 'option', '拼1次',      NULL::varchar, 'insert', '拼1次',     '三边', 110::integer),
      ('12', 'option', '拼2次',      NULL::varchar, 'insert', '拼2次',     '三边', 120::integer),
      ('13', 'option', '拼3次',      NULL::varchar, 'insert', '拼3次',     '三边', 130::integer),
      ('14', 'option', '加花边',     NULL::varchar, 'insert', '花边',      '三边', 140::integer),
      ('15', 'option', '加铅块',     NULL::varchar, 'insert', '铅坠',      '三边', 150::integer),
      ('16', 'option', '接高',       NULL::varchar, 'insert', '接高',      '精裁', 160::integer),
      ('17', 'option', '双眼皮接高', NULL::varchar, 'insert', '接高',      '精裁', 170::integer),
      ('18', 'option', '余料做绑带', NULL::varchar, 'insert', '绑带',      '车被', 180::integer),
      ('19', 'option', '布绑带',     NULL::varchar, 'insert', '绑带',      '车被', 190::integer),
      ('20', 'option', '余料做帘头', NULL::varchar, 'insert', '帘头制作',  '三边', 200::integer),
      ('21', 'option', '抱枕',       NULL::varchar, 'insert', '抱枕',      '外帘打卷', 210::integer),
      ('22', 'option', '纱绑带',     NULL::varchar, 'insert', '绑带',      '车被', 220::integer),
      ('23', 'option', '加logo条',   NULL::varchar, 'insert', 'logo条',    '三边', 230::integer),
      ('24', 'option', '加立边',     NULL::varchar, 'insert', '立边',      '三边', 240::integer),
      ('25', 'option', '扣环',       NULL::varchar, 'insert', '扣环',      '三边', 250::integer),
      ('26', 'option', '防翘扣',     NULL::varchar, 'insert', '防翘扣',    '三边', 260::integer),
      ('27', 'processing_item', '花边', NULL::varchar, 'insert', '花边', '三边', 270::integer),
      ('28', 'processing_item', '扣环', NULL::varchar, 'insert', '扣环', '三边', 280::integer),
      ('29', 'processing_item', '接高', NULL::varchar, 'insert', '接高', '精裁', 290::integer)
  ) AS r(rid, trigger_kind, trigger_value, position, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND COALESCE(e.position, '') = COALESCE(r.position, '')
          AND e.action = r.action
          AND COALESCE(e.operation, '') = COALESCE(r.operation, ''))
ON CONFLICT (id) DO NOTHING;

-- ================================================
-- END OF SCHEMA
-- ================================================
