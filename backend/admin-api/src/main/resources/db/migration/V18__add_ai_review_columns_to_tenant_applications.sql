-- V18: 企业入驻申请 AI 自动甄别字段
-- 2026-08-30 新增（AI 自动入驻改造）：
--   company_name_norm — 企业名称规范化（去空格/括号/后缀，用于防重复提交精确匹配）
--   review_source     — 甄别来源：ai（大模型/规则层）/ system（降级）/ manual（人工兜底，仅 API）
--   risk_flags        — 风险标记 JSON 数组（如 [{"level":"high","code":"SENSITIVE_CONTENT","reason":"..."}]）
--   review_summary    — AI 审查摘要（面向运营/审计）
ALTER TABLE tenant_applications
    ADD COLUMN IF NOT EXISTS company_name_norm VARCHAR(255),
    ADD COLUMN IF NOT EXISTS review_source VARCHAR(20),
    ADD COLUMN IF NOT EXISTS risk_flags TEXT,
    ADD COLUMN IF NOT EXISTS review_summary TEXT;

CREATE INDEX IF NOT EXISTS idx_tenant_applications_company_norm
    ON tenant_applications(company_name_norm);
