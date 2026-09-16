-- =====================================================================
-- V41: 对齐 bootstrap schema 缺列/缺表（issue #3270 —— C 端评测被污染的根因）
-- =====================================================================
-- 为什么需要（CI 实证 run 34617597854，ai-agent + postgres 日志）：
--   C 端验收栈的库是 `docs/sql/schema.sql`（docker-entrypoint-initdb.d）建的，
--   而**Flyway 未在该栈运行** → 只存在于迁移链的列在评测库里**不存在** →
--   admin-api 相关查询 500 → ai-agent 工具拿到 "服务暂时不可用"（CIRCUIT_OPEN）
--   → 熔断器随即打开 → 后续所有同类工具调用全部失败 → **整轮评测被污染**：
--
--     ① column "color_name" does not exist   （product_skus）
--        → GET 商品详情拉 SKU 列表 500 → product_detail 失败
--     ② column "actual_amount" does not exist（orders，另缺 discount/refund）
--        → GET /api/admin/agent/orders/mine 500 → customer_order_query /
--          customer_address_query / aftersale_create 归属校验全部失败
--     ③ column "position" does not exist     （users）
--        → userMapper.selectById 500 → C 端订单查询链路报错
--     ④ column "bot_name" does not exist     （tenant_ai_configs）
--        → 租户 AI 配置读取 500
--     ⑤ relation "user_memories" does not exist
--        → 会话长期记忆查询失败
--
--   后果：报告长成「agent 不会下单/不会建售后单」，真因是**后端 500 + 熔断**。
--   这正是 issue #3270 五层归因里最容易被误读的一层（基础设施层）。
--
-- 本迁移做两件事：
--   (a) 补齐**迁移链已有、但 bootstrap schema.sql 漏掉**的列（重复 ALTER 幂等无害）；
--   (b) 补齐**只存在于 Java 实体、两条 SQL 链都没有**的列/表
--       （product_skus.color_name / tenant_ai_configs.bot_name / user_memories）。
--       这些列生产库显然存在（否则线上同类查询也 500），本迁移把它们纳入版本管理。
--
-- 幂等：全部 IF NOT EXISTS，可重复执行。
-- =====================================================================

-- ── 1. orders：实收/优惠/退款字段（对应 V5 / V14）──
ALTER TABLE orders ADD COLUMN IF NOT EXISTS actual_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS close_reason VARCHAR(500);  -- docs/sql/013

-- ── 2. users：岗位（展示用）+ 权限点（对应 docs/sql/migrations/V20260614、V1）──
ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;

-- ── 3. product_skus：颜色标识（ProductSku.colorName；两条 SQL 链都没有）──
-- 语义：色号（如 "2699-01"）或颜色名（如 "米白"）；color_id 为兼容旧数据保留。
ALTER TABLE product_skus ADD COLUMN IF NOT EXISTS color_name VARCHAR(64);
COMMENT ON COLUMN product_skus.color_name IS '颜色标识（色号如 2699-01 或颜色名如 米白）；兼容 color_id 旧数据';

-- ── 4. tenant_ai_configs：机器人名称（docs/sql/009_add_bot_name.sql）+ 渠道配置（V10）──
ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS bot_name VARCHAR(64) DEFAULT '小布';
ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS channel_configs JSONB;
COMMENT ON COLUMN tenant_ai_configs.bot_name IS 'AI 助手自定义名称，面向客户显示';

-- ── 5. sessions：最后活动时间（对应 V13）──
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;

-- ── 6. processing_items / product_processing_items：每米数量密度（对应 V33）──
ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS per_meter_quantity DECIMAL(6,2);
ALTER TABLE product_processing_items ADD COLUMN IF NOT EXISTS custom_per_meter_quantity DECIMAL(6,2);

-- ── 7. tenants：品牌与通知设置（对应 V15）──
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo VARCHAR(512);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_email VARCHAR(128);

-- ── 8. tenant_applications：AI 甄别字段（对应 V18）──
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS company_name_norm VARCHAR(255);
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS review_source VARCHAR(20);
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS risk_flags TEXT;
ALTER TABLE tenant_applications ADD COLUMN IF NOT EXISTS review_summary TEXT;
CREATE INDEX IF NOT EXISTS idx_tenant_applications_company_norm
    ON tenant_applications(company_name_norm);

-- ── 9. user_memories：C 端长期记忆（docs/sql/migrations/V20260608 + V20260904）──
CREATE TABLE IF NOT EXISTS user_memories (
    id          VARCHAR(32) PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    user_id     VARCHAR(64) NOT NULL,
    type        VARCHAR(20) NOT NULL,           -- preference | fact | feedback | reference
    key         VARCHAR(128) NOT NULL,          -- 记忆 key，如 "style_preference"
    value       TEXT NOT NULL,                  -- 记忆值，如 "简约风格"
    importance  FLOAT DEFAULT 0.5,              -- 重要性评分 (0-1)，高分优先注入
    context     TEXT,                           -- 记录该条记忆时的对话上下文
    related_to  TEXT[],                         -- 关联记忆 ID 列表
    agent_type  VARCHAR(20) NOT NULL DEFAULT 'xiaobu',  -- xiaobu | mibao（V20260904）
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, key)
);
-- 老库补列（表已存在但无 agent_type 的情形）
ALTER TABLE user_memories
    ADD COLUMN IF NOT EXISTS agent_type VARCHAR(20) NOT NULL DEFAULT 'xiaobu';
CREATE INDEX IF NOT EXISTS idx_user_memories_tenant_user
    ON user_memories(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_memories_importance
    ON user_memories(tenant_id, user_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_user_memories_agent
    ON user_memories(agent_type, tenant_id, user_id);
