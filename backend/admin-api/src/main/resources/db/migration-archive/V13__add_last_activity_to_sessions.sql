-- V13: 会话最后活动时间列（会话管理重构 P2）
-- 空闲判定改用 last_activity_at（每轮 send 刷新），替代"最后消息时间 or created_at 回退"。
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;

-- 存量数据回填：以最后消息时间或创建时间作为初始活动时间
UPDATE sessions
SET last_activity_at = COALESCE(
    (SELECT MAX(created_at) FROM session_messages WHERE session_id = sessions.id),
    created_at
)
WHERE last_activity_at IS NULL;
