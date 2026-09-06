-- =====================================================================
-- V27: 通知/站内信三表建表（issue #2965）
-- 背景：Notification* 实体/Mapper/Service/Controller 代码早已存在，
-- 但数据库中从未创建这三张表（历史遗漏迁移），通知接口一调用即 500，
-- 功能处于「纸面完成、实际不可用」状态。本迁移补齐基础设施。
--
-- 多租户约定：notification_templates / notification_rules 的 tenant_id
-- 为 0 时表示系统内置（预置模板/规则，多租户共享、只读），
-- 查询时 `(tenant_id = 当前租户 OR tenant_id = 0)`，租户级优先。
-- =====================================================================

-- 1. 通知记录表（站内信落库）
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    rule_id VARCHAR(64),
    template_id VARCHAR(64),
    recipient_id VARCHAR(64) NOT NULL,
    recipient_type VARCHAR(20) DEFAULT 'user',
    channel VARCHAR(20) DEFAULT 'internal',
    title VARCHAR(255) NOT NULL,
    content TEXT,
    status VARCHAR(20) DEFAULT 'sent',
    sent_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_created
    ON notifications(recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_status
    ON notifications(status);

-- 2. 通知模板表（tenant_id=0 为系统内置模板，只读）
CREATE TABLE IF NOT EXISTS notification_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL DEFAULT 0,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50),
    channel VARCHAR(20) DEFAULT 'internal',
    template_content TEXT NOT NULL,
    variables TEXT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_templates_tenant
    ON notification_templates(tenant_id, name);

-- 3. 通知规则表（事件 → 模板 映射，tenant_id=0 为系统内置规则，只读）
CREATE TABLE IF NOT EXISTS notification_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL DEFAULT 0,
    event_type VARCHAR(50) NOT NULL,
    recipient_type VARCHAR(20),
    channels VARCHAR(100),
    enabled BOOLEAN DEFAULT TRUE,
    template_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_rules_tenant_event
    ON notification_rules(tenant_id, event_type);