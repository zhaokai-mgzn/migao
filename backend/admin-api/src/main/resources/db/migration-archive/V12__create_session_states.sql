-- V12: 会话工作状态表（会话管理重构 P1）
-- 单一事实源：跨轮工作状态（实体/pending_skill/stage/vision/last_skill）从
-- sessions.metadata 与多套 Redis key 迁出，统一存于此表，随会话生命周期清理。
CREATE TABLE IF NOT EXISTS session_states (
    session_id VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
    state JSONB NOT NULL DEFAULT '{}',        -- SessionState 序列化（见 app.memory.session_state_store）
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
