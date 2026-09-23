-- V8: 售后工单增强 — 内部备注、处理时间线、备注表
-- 幂等迁移：所有 DDL 使用 IF NOT EXISTS

-- 1. 售后工单表增加 internal_notes 字段
ALTER TABLE after_sales_tickets ADD COLUMN IF NOT EXISTS internal_notes TEXT;

-- 2. 工单处理时间线表
CREATE TABLE IF NOT EXISTS ticket_timeline (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    action VARCHAR(32) NOT NULL,
    actor_id VARCHAR(64),
    actor_type VARCHAR(32) NOT NULL DEFAULT 'system',
    content JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. 工单备注表
CREATE TABLE IF NOT EXISTS ticket_notes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    ticket_id VARCHAR(64) NOT NULL REFERENCES after_sales_tickets(id),
    author_id VARCHAR(64) NOT NULL REFERENCES agent_employees(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. 索引（幂等，重复创建自动跳过）
CREATE INDEX IF NOT EXISTS idx_ticket_timeline_ticket ON ticket_timeline(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_timeline_tenant ON ticket_timeline(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket ON ticket_notes(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_tenant ON ticket_notes(tenant_id);
