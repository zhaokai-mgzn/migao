-- V7: 平台管理员独立表
-- 原因：超管是平台级账号，不属于任何租户，应从 users 表中拆分出来

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

COMMENT ON TABLE platform_admins IS '平台管理员（超管），平台级账号，无租户归属';
