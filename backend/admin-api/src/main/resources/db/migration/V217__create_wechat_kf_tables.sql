-- 微信客服 AI 智能客服：通道 / 会话镜像 / 预算 / 发件箱（issue #9161）
--
-- ## 一句话
-- 只落表结构与约束，不含回调/发送/LLM。设计见 docs/design/wechat-kf-ai-customer-service.md。
--
-- ## 为什么复用 sessions / session_messages
-- 仓库已有 `sessions`（channel 列）与 `session_messages`，转人工已有 `agent_sessions`。
-- 本迁移只加「远端镜像 + kf 专属」表，不另起一套会话真相。
--
-- ## 为什么不启用 FORCE RLS
-- 本仓从未设置 `app.current_tenant_id`（全仓 0 处），现有 RLS 实际未生效（owner 绕过）。
-- 若对新表 FORCE，policy 里的 `current_setting('app.current_tenant_id')` 会直接报错
-- （未带 missing_ok），owner 查询也会挂。隔离靠 MyBatis TenantLineInnerInterceptor
-- + 显式 tenant_id；RLS 待单独 PR 引入 GUC 后再开。
--
-- ## 回滚
-- 代码回滚后这些表无消费方；如需回收：DROP TABLE（按依赖逆序）kf_handoff, kf_customer_link,
-- kf_media, kf_agents, kf_policies, kf_outbox, kf_send_budget, kf_session_remote,
-- kf_sync_cursor, kf_inbox, kf_channels, kf_suites。
--
-- ## 显式事务（与 V187/V215 同款）
BEGIN;

CREATE TABLE IF NOT EXISTS kf_suites (
    suite_id VARCHAR(128) PRIMARY KEY,
    token VARCHAR(128) NOT NULL,
    encoding_aes_key VARCHAR(128) NOT NULL,
    suite_secret_enc TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE kf_suites IS '第三方应用套件级凭证（Token/AESKey 是 suite 级，不是租户级）';

CREATE TABLE IF NOT EXISTS kf_channels (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    corp_id VARCHAR(128) NOT NULL,
    open_kfid VARCHAR(128) NOT NULL,
    auth_mode VARCHAR(16) NOT NULL,
    suite_id VARCHAR(128) REFERENCES kf_suites(suite_id),
    callback_token VARCHAR(128),
    encoding_aes_key VARCHAR(128),
    secret_enc TEXT,
    secret_key_id VARCHAR(32),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_channels_auth_mode CHECK (auth_mode IN ('third_party', 'self_built')),
    CONSTRAINT ck_kf_channels_status CHECK (status IN ('active', 'expired', 'revoked', 'unauthorized'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_channels_corp_open_kfid
    ON kf_channels (corp_id, open_kfid);
CREATE INDEX IF NOT EXISTS idx_kf_channels_tenant_status
    ON kf_channels (tenant_id, status);
COMMENT ON TABLE kf_channels IS '租户 × 企微客服账号；corp_id+open_kfid 唯一';

CREATE TABLE IF NOT EXISTS kf_inbox (
    id BIGSERIAL PRIMARY KEY,
    msg_signature VARCHAR(256) NOT NULL,
    corp_id VARCHAR(128) NOT NULL,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    open_kfid VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_inbox_status CHECK (status IN ('pending', 'processing', 'done', 'failed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_inbox_msg_signature
    ON kf_inbox (msg_signature);
CREATE INDEX IF NOT EXISTS idx_kf_inbox_tenant_created
    ON kf_inbox (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kf_inbox_open_kfid_created
    ON kf_inbox (open_kfid, created_at);
COMMENT ON TABLE kf_inbox IS '回调收件箱：只做入站事件，不当消息表；msg_signature 去重';

CREATE TABLE IF NOT EXISTS kf_sync_cursor (
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    open_kfid VARCHAR(128) NOT NULL,
    cursor VARCHAR(128),
    dirty_at TIMESTAMP WITH TIME ZONE,
    last_success_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, open_kfid)
);
CREATE INDEX IF NOT EXISTS idx_kf_sync_cursor_dirty
    ON kf_sync_cursor (dirty_at)
    WHERE dirty_at IS NOT NULL;
COMMENT ON TABLE kf_sync_cursor IS 'sync_msg 游标 + 新鲜度；回调无论是否重复都置 dirty_at';

CREATE TABLE IF NOT EXISTS kf_session_remote (
    session_id VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    open_kfid VARCHAR(128) NOT NULL,
    external_userid VARCHAR(128) NOT NULL,
    state SMALLINT NOT NULL DEFAULT 4,
    servicer_userid VARCHAR(128),
    version INTEGER NOT NULL DEFAULT 0,
    epoch INTEGER NOT NULL DEFAULT 1,
    last_msg_at TIMESTAMP WITH TIME ZONE,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    close_reason VARCHAR(32),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_session_remote_state CHECK (state BETWEEN 0 AND 4),
    CONSTRAINT ck_kf_session_remote_close_reason CHECK (
        close_reason IS NULL OR close_reason IN ('human_end', 'api_end', 'expired_48h')
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_session_remote_epoch
    ON kf_session_remote (open_kfid, external_userid, epoch);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_session_remote_current
    ON kf_session_remote (open_kfid, external_userid)
    WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_kf_session_remote_tenant_open_kfid
    ON kf_session_remote (tenant_id, open_kfid);
COMMENT ON TABLE kf_session_remote IS 'sessions 的 1:1 远端镜像：state/servicer/version CAS/epoch 分段';

CREATE TABLE IF NOT EXISTS kf_send_budget (
    session_id VARCHAR(64) PRIMARY KEY REFERENCES sessions(id),
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_send_budget_used CHECK (used >= 0 AND used <= 5)
);
COMMENT ON TABLE kf_send_budget IS '48h/5 条预算；发送前原子扣减 used<5 且 window_start>now()-48h';

CREATE TABLE IF NOT EXISTS kf_outbox (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    msgid VARCHAR(32) NOT NULL,
    parts JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_msgid VARCHAR(128),
    fail_type INTEGER,
    sending_at TIMESTAMP WITH TIME ZONE,
    lease_owner VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_outbox_status CHECK (
        status IN ('pending', 'sending', 'accepted', 'failed', 'unknown')
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_outbox_msgid ON kf_outbox (msgid);
CREATE INDEX IF NOT EXISTS idx_kf_outbox_tenant_status_created
    ON kf_outbox (tenant_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_kf_outbox_sent_msgid
    ON kf_outbox (sent_msgid)
    WHERE sent_msgid IS NOT NULL;
COMMENT ON TABLE kf_outbox IS '发件箱：msgid 幂等键（≤32B）；accepted ≠ 送达，等 msg_send_fail 定终态';

CREATE TABLE IF NOT EXISTS kf_policies (
    tenant_id BIGINT PRIMARY KEY REFERENCES tenants(id),
    mode VARCHAR(16) NOT NULL DEFAULT 'shadow',
    risk_threshold INTEGER NOT NULL DEFAULT 70,
    emotion_threshold INTEGER NOT NULL DEFAULT 80,
    confidence_threshold NUMERIC(3,2) NOT NULL DEFAULT 0.40,
    human_cooldown_sec INTEGER NOT NULL DEFAULT 600,
    keywords JSONB,
    business_hours JSONB,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_policies_mode CHECK (mode IN ('shadow', 'suggest', 'auto', 'off'))
);
COMMENT ON TABLE kf_policies IS '租户级介入策略：模式/阈值/关键词/时段';

CREATE TABLE IF NOT EXISTS kf_agents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    corp_id VARCHAR(128) NOT NULL,
    wecom_userid VARCHAR(128),
    open_userid VARCHAR(128),
    display_name VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'offline',
    stop_type SMALLINT,
    skills JSONB,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_agents_status CHECK (status IN ('online', 'busy', 'offline'))
);
CREATE INDEX IF NOT EXISTS idx_kf_agents_tenant_status
    ON kf_agents (tenant_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_agents_wecom_userid
    ON kf_agents (tenant_id, corp_id, wecom_userid)
    WHERE wecom_userid IS NOT NULL;
COMMENT ON TABLE kf_agents IS '坐席 ↔ 企微 userid/open_userid 映射；trans(3) 需要 open_userid';

CREATE TABLE IF NOT EXISTS kf_media (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    open_kfid VARCHAR(128),
    media_id VARCHAR(256) NOT NULL,
    direction VARCHAR(8) NOT NULL,
    mime VARCHAR(64),
    size_bytes BIGINT,
    storage_key VARCHAR(512),
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_media_direction CHECK (direction IN ('in', 'out'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_media_direction_media_id
    ON kf_media (direction, media_id);
CREATE INDEX IF NOT EXISTS idx_kf_media_expires_at
    ON kf_media (expires_at)
    WHERE expires_at IS NOT NULL;
COMMENT ON TABLE kf_media IS '媒体缓存：入站下载/出站上传；media_id 3 天过期';

CREATE TABLE IF NOT EXISTS kf_customer_link (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    corp_id VARCHAR(128) NOT NULL,
    external_userid VARCHAR(128) NOT NULL,
    customer_id VARCHAR(64),
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_customer_link_external
    ON kf_customer_link (tenant_id, corp_id, external_userid);
CREATE INDEX IF NOT EXISTS idx_kf_customer_link_customer
    ON kf_customer_link (tenant_id, customer_id);
COMMENT ON TABLE kf_customer_link IS 'external_userid → customer_id 解析；不跨租户';

CREATE TABLE IF NOT EXISTS kf_handoff (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(id),
    epoch INTEGER NOT NULL DEFAULT 1,
    handoff_key VARCHAR(160) NOT NULL,
    agent_session_id VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_kf_handoff_status CHECK (status IN ('pending', 'created', 'failed', 'cancelled'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kf_handoff_key ON kf_handoff (handoff_key);
CREATE INDEX IF NOT EXISTS idx_kf_handoff_session ON kf_handoff (session_id, epoch);
COMMENT ON TABLE kf_handoff IS '转人工幂等：handoff_key = session_id:epoch 唯一，防重复建 waiting';

COMMIT;
