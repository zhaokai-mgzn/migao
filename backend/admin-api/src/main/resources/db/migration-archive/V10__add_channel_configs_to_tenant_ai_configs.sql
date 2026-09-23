-- V10: 添加 channel_configs 列到 tenant_ai_configs 表
-- 对应 TenantAiConfig 实体 channelConfigs 字段 (JSON)

ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS channel_configs JSONB;
