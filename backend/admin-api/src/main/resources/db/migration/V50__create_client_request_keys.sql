-- =====================================================================
-- V50: 写请求幂等键 client_request_keys（issue #4037，F19）
-- =====================================================================
-- 现象：ai-agent 工具超时 30s / HTTP 客户端超时 25s ⇒「服务端已落库、客户端报失败」
-- 的窗口**客观存在**；LLM 见状重试同一写请求 ⇒ **重复下单 = 直接资金损失**。
--
-- 修法（已定）：ai-agent 在写请求上带 X-Client-Request-Id（幂等键），服务端按
-- (tenant_id, client_request_id) 去重：首次请求正常执行并把结果快照落库，
-- 同键再次到达 ⇒ 不再执行，直接回放上次成功结果（顾客/LLM 看到同一订单号/工单号）。
--
-- 安全要点（可在已有数据的库上重复执行）：
--   ① 幂等：MigrationRunner 的硬约定是「所有 SQL 文件必须幂等」——
--      bootstrap-first 栈上 docs/sql/schema.sql 先建终态、迁移链随后**再跑一遍**，
--      故全部语句带 IF NOT EXISTS 守卫；
--   ② 不用 CREATE POLICY / RENAME：这两类在新增迁移里有守卫测试要求与
--      pg_policies/目标对象存在性**同块**（tests/unit_ci_workflows/test_migration_idempotency.py）。
--      本表是基础设施表（不存业务数据），不建 RLS 策略，直接避开该类缺陷；
--   ③ 不用 DO 块：MigrationRunner 把整文件交给一次 jdbc.execute，
--      「一条 DDL 一个语义」最不易踩驱动解析坑（与 V45 同一取舍）；
--   ④ 唯一约束**内联在 CREATE TABLE 里**：守卫语句已经是 `IF NOT EXISTS`，
--      表已存在时整条（含约束）跳过 ⇒ 天然幂等，无需 `CREATE UNIQUE INDEX IF NOT EXISTS`
--      再建一份（ON CONFLICT 认唯一约束与唯一索引等价）。
-- =====================================================================

CREATE TABLE IF NOT EXISTS client_request_keys (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,               -- 租户隔离维度：去重键 = (tenant_id, client_request_id)
    client_request_id VARCHAR(128) NOT NULL, -- 幂等键，取自请求头 X-Client-Request-Id
    endpoint VARCHAR(128) NOT NULL,          -- 受理端点（如 POST /api/admin/agent/orders），诊断用
    response_payload JSONB,                  -- 首次执行成功后的响应快照；NULL = 已占位但尚无结果
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- 去重判据：同租户同键只允许一行。并发同键时第二个写入者被它挡住
    -- （INSERT ... ON CONFLICT DO NOTHING → 影响行数 0 ⇒ 判为「重复请求」）。
    UNIQUE (tenant_id, client_request_id)
);

-- 诊断索引：按租户 + 时间倒序看最近受理的写请求（排障「同一键跨端点被复用」用）
CREATE INDEX IF NOT EXISTS idx_client_request_keys_tenant_created
    ON client_request_keys (tenant_id, created_at DESC);

COMMENT ON TABLE client_request_keys IS
    '写请求幂等键（issue #4037）：(tenant_id, client_request_id) 唯一；response_payload 存首次成功结果快照，同键重放不再执行';
COMMENT ON COLUMN client_request_keys.client_request_id IS
    '幂等键：请求头 X-Client-Request-Id（缺省则该请求走原路径、不参与去重——向后兼容未升级的调用方）';
COMMENT ON COLUMN client_request_keys.response_payload IS
    '首次执行成功后的响应快照（JSONB）。为 NULL ⇒ 已占位但无结果（首次执行在飞/已失败）：重放方必须 fail-closed 报错，不得返回空结果';
COMMENT ON COLUMN client_request_keys.endpoint IS
    '受理端点标识：同一 client_request_id 出现在不同端点上说明调用方复用了键，可据此归因';