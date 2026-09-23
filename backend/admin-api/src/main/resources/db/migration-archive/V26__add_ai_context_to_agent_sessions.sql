-- GB/T 47746-2026 转人工上下文同步（issue #2776）
-- 人工会话快照：转人工时点 AI 会话摘要 + 最近 N 轮 user/assistant 消息
ALTER TABLE agent_sessions
    ADD COLUMN IF NOT EXISTS ai_context_summary TEXT,
    ADD COLUMN IF NOT EXISTS ai_context_messages JSONB NOT NULL DEFAULT '[]';
