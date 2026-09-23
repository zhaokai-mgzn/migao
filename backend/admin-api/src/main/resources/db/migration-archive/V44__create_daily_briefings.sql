-- =====================================================================
-- V44: 智能每日经营简报（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
-- =====================================================================
-- 企业级开关 + 每日定时生成 + 四区块简报（昨日回顾/今日必办/风险预警/优化建议）。
-- 数据安全四红线：PII 不进 prompt / RLS 隔离 / 开关即熔断 / 校验兜底。
-- content 由 LLM 生成（含数字回填校验后的条目），source_snapshot 固化聚合 SQL 快照
-- （指标 key → value），供校验层对账与证据链回溯；两者均不含客户 PII。
-- =====================================================================

-- 1) tenants 表加简报开关与生成时刻（幂等，MigrationRunner 约定）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS briefing_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS briefing_generate_time VARCHAR(5) DEFAULT '06:00';

-- 2) 每日简报表
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

-- 3) RLS 策略（多租户行级安全隔离，与全库同构）
ALTER TABLE daily_briefings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_daily_briefings ON daily_briefings
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
