-- 用户建议偏好表：记录用户点击建议的行为偏好，用于个性化推荐
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
