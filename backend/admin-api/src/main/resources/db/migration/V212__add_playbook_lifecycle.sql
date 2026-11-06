-- V212 / issue #8175（P2）：口径卡生命周期（衰减 / 退役）+ 晋升数据面（复现证据）
--
-- ## 一句话
-- P1 把生命周期做成「人工 draft→active→retired」；P2 补三件**可判定**的事：
--   ① 衰减分的数据面（命中计数 + 最后一次命中时刻）；
--   ② 规则化退役的可审计原因（`lifecycle_reason`）；
--   ③ 晋升的数据面（**哪个员工**在**哪个会话**里复现过同一口径）。
--
-- ## 为什么 `hits` 需要 `last_hit_at`
-- 「连续 N 天 hits 不增长」不能只看 `hits` 的值 —— 没有时刻就不知道「不增长」从何时开始。
-- `last_hit_at` = 命中计数最后一次增长的时刻；NULL = 从未命中
-- （锚点回落到 `activated_at` → `created_at`，判定口径见
-- `backend/ai-agent-service/app/playbook/lifecycle.py::retirement_verdict`）。
--
-- ## 为什么复现证据要单独一张表
-- P1 的幂等语义是「同 key 同值 ⇒ 跳过第二张卡」⇒ 第二个员工的证据**不会落进 playbooks**。
-- 晋升判的是「几个**不同员工**说过同一件事」，不是「落了几张卡」；把证据塞进 playbooks
-- 会破坏 P1「一条口径一张卡」的语义。唯一索引按
-- `(tenant_id, playbook_key, value_key, employee_id)` ⇒ 同一员工重复出现只记一条
-- ⇒ `COUNT(DISTINCT employee_id)` 的语义成立（不是「说过几次」）。
--
-- ## 数据面（会话 → 员工）现状，照实登记
-- `sessions` **没有** `agent_type` 列 ⇒ 库里认不出「这条会话是黄金策（mibao）还是元元（C 端）」。
-- 现有链路 = `sessions.customer_id` → `users.id`，并按 `users.role NOT IN ('customer','agent')`
-- 排除 C 端身份（写入方见 `backend/ai-agent-service/app/api/chat.py`：
-- `customer_id = current_user.user_id`，B 端身份来自 admin-api 签发的 JWT）。
-- 这条链是**推导**而不是登记：`agent_type` 落 sessions 是 P1b 的重启条件（见 issue #8175）。
--
-- ## 默认不改变行为
-- 两个新列都可空；自动退役 / 晋升两个开关在 ai-agent 配置里**默认关**
-- （`PLAYBOOK_AUTO_RETIRE_ENABLED` / `PLAYBOOK_PROMOTION_ENABLED`，见 app/config.py）。

ALTER TABLE playbooks ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE playbooks ADD COLUMN IF NOT EXISTS lifecycle_reason TEXT;

COMMENT ON COLUMN playbooks.last_hit_at IS
    '命中计数最后一次增长的时刻（issue #8175 P2 衰减/退役的时间锚点）。NULL = 从未命中。';
COMMENT ON COLUMN playbooks.lifecycle_reason IS
    '最近一次**自动**生命周期动作的原因（规则化退役 / 晋升），可审计；人工动作走 audit_log。';

CREATE TABLE IF NOT EXISTS playbook_reproductions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    playbook_key VARCHAR(64) NOT NULL,
    value_key VARCHAR(64) NOT NULL,
    employee_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_playbook_reproductions_employee
        UNIQUE (tenant_id, playbook_key, value_key, employee_id)
);

CREATE INDEX IF NOT EXISTS idx_playbook_reproductions_tenant_key
    ON playbook_reproductions (tenant_id, playbook_key);

COMMENT ON TABLE playbook_reproductions IS
    '口径卡复现证据（issue #8175 P2）：哪个员工在哪个会话里复现过同一 (playbook_key, value_key)。'
    '员工 = sessions.customer_id → users.id，且排除 C 端角色；晋升判据 = '
    'COUNT(DISTINCT employee_id) >= PLAYBOOK_PROMOTION_MIN_EMPLOYEES。';
