-- 工人登录态（issue #4733，P1·计件归属）
--
-- ## 一句话
-- 报工身份今天**从 body 取**（`ProductionService.doReport` 的 `.workerId(str(body.get("worker_id")))`）
-- ⇒ 谁都能填 ⇒ **工人可冒领**（或前端 bug 记错人）⇒ **发错工资**。本迁移为「**服务端解身份**」
-- 提供唯一根：工人 session（工号 + PIN 登录后签发）。
--
-- ## 三张增量（全部**只加不改**）
-- ① `users.worker_no`（工号，租户内唯一）+ 部分唯一索引；
-- ② `worker_sessions`（登录态载体：闲置超时 / 快速切换 / 设备快照）；
-- ③ `worker_report_audits`（**只追加**旁路表：一次报工动作 1:1，留「由哪个会话报的」+ 身份来源）。
--
-- ## 为什么不给 `production_work_logs` 加列（红线）
-- `docs/design/worker-h5-scan-and-report.md` §3.4 与 `docs/design/worker-scan-terminal.md` §7 逐字
-- 「不改 `production_work_logs`」；`production_work_logs.unit_price` / `factor` 是**工资凭证快照**
-- （V61 / #4351），本单**一字不动**（反向护栏断言）。「由哪个设备会话报的」走旁路表。
--
-- ## 为什么复用 `users` 而不新造 `workers` 表
-- 设计 §2.3 硬约束：`user_identities.user_id NOT NULL REFERENCES users(id)` ⇒ 本来就必须有 `users` 行；
-- PIN 直接落既有 `users.password_hash`（BCrypt）⇒ **零新列**。工人的**权限分层**不靠新表，
-- 靠 `roles=["worker"]` + `permissions=[]` + `/api/admin/**` 拒绝集合（见 SecurityConfig）。
--
-- ## 幂等
-- `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` /
-- `COMMENT ON` 天然幂等；**不回填任何存量行**（谁是工人由商家建号决定，不是迁移的默认行为 ——
-- 迁移静默把商家用户标成工人 = 本 issue 要治的「无人知道」形态）。
--
-- ## 停止条件（fail-closed，不静默降级）
-- 外键（`tenants` / `users` / `processing_orders`）是「账本不会留下孤儿行」的保证 ⇒
-- 任一被引用表缺失时**建表失败并停下**（Flyway 事务回滚），不为了通过而摘掉外键。

-- ① 工号（租户内唯一；`worker_no IS NOT NULL` 是部分索引谓词 ⇒ 商家用户不受影响）
ALTER TABLE users ADD COLUMN IF NOT EXISTS worker_no VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uk_users_tenant_worker_no
    ON users (tenant_id, worker_no)
    WHERE worker_no IS NOT NULL AND deleted = 0;
COMMENT ON COLUMN users.worker_no IS
    '工人工号（V98，issue #4733）：租户内唯一（部分唯一索引 uk_users_tenant_worker_no）。'
    '非 NULL = 该 users 行是**工人档案**（role=worker）；NULL = 商家用户（本列引入前的全部存量行）';

-- ② 工人登录态（session 载体 = 不可猜的 id；闲置超时 / 快速切换 / 设备快照都在本表）
CREATE TABLE IF NOT EXISTS worker_sessions (
    id VARCHAR(64) PRIMARY KEY,                      -- 会话 id（32 位 UUID 去横线）：前端存本地并以 X-Worker-Session-Id 回传
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    worker_id VARCHAR(64) NOT NULL REFERENCES users(id),
    worker_no VARCHAR(64),                           -- 工号快照（报工/展示不再回查 users）
    worker_name VARCHAR(64),                         -- 姓名快照（= users.nickname）
    device_label VARCHAR(64),                        -- 设备标签（PAD-车间-01 之类；登录时登记）
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- 闲置过期时刻：每次成功请求顺延（服务端算，前端定时器只是可见面）
    idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,               -- 结束时刻；NULL = 仍活跃
    -- logout 主动登出 / idle 闲置超时 / switched 快速切换工人 / revoked 停用撤销
    end_reason VARCHAR(16),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_worker_sessions_worker
    ON worker_sessions (tenant_id, worker_id, started_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE worker_sessions IS
    '工人登录态（V98，issue #4733）：**服务端**是身份的权威 —— 报工只带 X-Worker-Session-Id，'
    'worker_id/worker_name 一律由本表解出，body 里的同名字段被忽略';
COMMENT ON COLUMN worker_sessions.idle_expires_at IS
    '闲置过期时刻（默认 15 分钟，租户可配 5~60）：每次成功请求由服务端顺延；过期 session 报工 ⇒ 401（不静默续期）';
COMMENT ON COLUMN worker_sessions.end_reason IS
    '结束原因：logout 主动登出 / idle 闲置超时 / switched 快速切换工人（旧 session 立即失效）/ revoked 停用撤销';

-- ③ 报工身份旁路账（只追加；1:1 挂一次报工动作）
CREATE TABLE IF NOT EXISTS worker_report_audits (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    work_log_id VARCHAR(64),                         -- 指向 production_work_logs.id（**不加外键**：账本不得拖累报工写入）
    operation_id VARCHAR(64),
    worker_id VARCHAR(64),
    worker_name VARCHAR(64),
    worker_session_id VARCHAR(64),                   -- 由哪个会话报的；NULL = 无工人 session
    -- server_session = 身份来自工人 session（权威）；client_body = 无 session 时显式沿用既有 body 口径
    identity_source VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_worker_report_audits_log
    ON worker_report_audits (tenant_id, work_log_id)
    WHERE deleted = 0;
COMMENT ON TABLE worker_report_audits IS
    '报工身份旁路账（V98，issue #4733，**只追加**）：一行 = 一次报工动作。'
    '存在的唯一理由：`production_work_logs` 是冻结契约（红线：不加列）⇒「由哪个设备会话报的」只能走旁路';
COMMENT ON COLUMN worker_report_audits.identity_source IS
    'server_session = worker_id/worker_name 由服务端从工人 session 解出（**权威**，忽略 body 同名字段）；'
    'client_body = 无工人 session 时的显式降级（商家侧报工），来源被**显式标注**而不是静默沿用「谁都能填」';
