-- 为租户AI配置表添加bot_name字段
ALTER TABLE tenant_ai_configs ADD COLUMN IF NOT EXISTS bot_name VARCHAR(64) DEFAULT '小布';

COMMENT ON COLUMN tenant_ai_configs.bot_name IS 'AI助手自定义名称，面向客户显示';
