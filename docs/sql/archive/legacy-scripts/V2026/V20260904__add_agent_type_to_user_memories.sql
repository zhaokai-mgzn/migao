-- V20260904: 用户记忆表增加 agent_type 维度（C 端长期记忆专项，issue #2815）
--
-- 背景：user_memories 表此前由小布（C 端）与米宝（B 端）共用，无 agent 维度，
-- 且存量含 PII / dev-test 噪音（见 docs/design/memory-system-assessment.md §3.2）。
-- 本期决策：C 端（小布）启用长期记忆；B 端（米宝）暂不落库。
-- agent_type 标识记忆归属的 Agent：xiaobu（C 端消费者画像）/ mibao（B 端商家习惯，预留）。
--
-- 存量行按清理脚本 scripts/cleanup_user_memories.py 处理后，剩余行默认归 xiaobu。
-- 幂等：IF NOT EXISTS。
ALTER TABLE user_memories
    ADD COLUMN IF NOT EXISTS agent_type VARCHAR(20) NOT NULL DEFAULT 'xiaobu';

-- 查询路径：注入时 WHERE tenant_id + user_id + agent_type='xiaobu' + importance >= 阈值 ORDER BY importance DESC
-- 现有索引 (tenant_id, user_id, importance DESC) 已覆盖该路径；补 agent_type 前缀索引便于按 Agent 全量扫描（清理/对账）。
CREATE INDEX IF NOT EXISTS idx_user_memories_agent
    ON user_memories (agent_type, tenant_id, user_id);
