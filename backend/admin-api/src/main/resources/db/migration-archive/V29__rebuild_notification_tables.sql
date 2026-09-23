-- =====================================================================
-- V29: 重建通知三表，校准与实体一致（issue #2965 修复）
--
-- 背景（生产实证，2026-09-06）：
-- V27 的 CREATE TABLE IF NOT EXISTS 在既有环境静默跳过——数据库早已存在
-- 一套「旧版设计」的空壳表（从未被业务使用），其结构与本仓库实体不一致：
--   * notification_templates.variables  旧: jsonb     实体: String（变量说明文本）
--   * notification_rules.channels       旧: jsonb     实体: String（渠道文本）
--   * notifications.status 默认值       旧: 'pending' 业务: sent/read
--   * 若干 NOT NULL 约束（type/title/content）与实体可空语义冲突
-- 后果：种子插入报 "invalid input syntax for type json"（被 MigrationRunner 吞掉），
-- 模板/规则 insert 500，通知功能仍不可用。
--
-- 本迁移：显式 DROP 旧表（三张均为空壳，无业务数据）后按实体结构重建。
-- 幂等：DROP IF EXISTS + CREATE，重启安全。
-- =====================================================================

DROP TABLE IF EXISTS notifications, notification_rules, notification_templates;

-- 1. 通知记录表（站内信落库）
CREATE TABLE notifications (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    rule_id VARCHAR(64),
    template_id VARCHAR(64),
    recipient_id VARCHAR(64) NOT NULL,
    recipient_type VARCHAR(20) DEFAULT 'user',
    channel VARCHAR(20) DEFAULT 'internal',
    title VARCHAR(255),
    content TEXT,
    status VARCHAR(20) DEFAULT 'sent',
    sent_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_notifications_recipient_created
    ON notifications(recipient_id, created_at DESC);
CREATE INDEX idx_notifications_status
    ON notifications(status);

-- 2. 通知模板表（tenant_id=0 为系统内置模板，只读）
CREATE TABLE notification_templates (
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

CREATE INDEX idx_notification_templates_tenant
    ON notification_templates(tenant_id, name);

-- 3. 通知规则表（事件 → 模板 映射，tenant_id=0 为系统内置规则，只读）
CREATE TABLE notification_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL DEFAULT 0,
    event_type VARCHAR(50) NOT NULL,
    recipient_type VARCHAR(20) DEFAULT 'user',
    channels VARCHAR(100),
    enabled BOOLEAN DEFAULT TRUE,
    template_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_notification_rules_tenant_event
    ON notification_rules(tenant_id, event_type);