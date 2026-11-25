-- 微信客服 PR3（issue #9176）：sync worker 的 claim 字段 + 消息幂等键
-- 1) kf_sync_cursor 增加 claimed_by/claimed_at：多实例用 FOR UPDATE SKIP LOCKED 抢占，
--    领取后写 fencing token，避免同一游标被两个实例同时 sync。
-- 2) session_messages 增加 external_msg_id：微信侧 msgid 作为幂等键（唯一索引部分）。
BEGIN;

ALTER TABLE kf_sync_cursor ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(128);
ALTER TABLE kf_sync_cursor ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS idx_kf_sync_cursor_claimed_at
    ON kf_sync_cursor (claimed_at)
    WHERE claimed_at IS NOT NULL;

ALTER TABLE session_messages ADD COLUMN IF NOT EXISTS external_msg_id VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_messages_external_msg_id
    ON session_messages (tenant_id, external_msg_id)
    WHERE external_msg_id IS NOT NULL AND deleted = 0;

COMMIT;
