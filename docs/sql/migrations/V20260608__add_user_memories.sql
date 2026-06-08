-- 用户记忆表：跨会话持久化用户偏好、关键事实、反馈等
-- 每次对话后 LLM 自动提取，下次对话时注入 System Prompt
CREATE TABLE IF NOT EXISTS user_memories (
    id          VARCHAR(32) PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    user_id     VARCHAR(64) NOT NULL,
    type        VARCHAR(20) NOT NULL,           -- preference | fact | feedback | reference
    key         VARCHAR(128) NOT NULL,          -- 记忆 key，如 "style_preference"
    value       TEXT NOT NULL,                  -- 记忆值，如 "简约风格"
    importance  FLOAT DEFAULT 0.5,              -- 重要性评分 (0-1)，高分的优先注入
    context     TEXT,                           -- 记录该条记忆时的对话上下文（用于追溯）
    related_to  TEXT[],                         -- 关联记忆 ID 列表，如 {mem_abc123}
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, user_id, key)
);

CREATE INDEX idx_user_memories_tenant_user ON user_memories(tenant_id, user_id);
CREATE INDEX idx_user_memories_importance ON user_memories(tenant_id, user_id, importance DESC);
