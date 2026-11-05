-- V210 / issue #8175（一期最小闭环）：口径卡（Playbook）表
--
-- ## 一句话
-- 把 B 端「人工纠正一次」沉淀成**全企业可用**的工件：一条口径 = 触发条件（机器可判）
-- + 正解 + 反例（机器可判） + 来源（哪次会话、哪一轮） + 生命周期状态。
--
-- ## 为什么不是 user_memories 再加一行
-- `user_memories` 的主语是**个人顾客画像**（#2815 对 mibao 关闭），upsert 是「后写覆盖先写」
-- ⇒ 会把对的口径冲掉、也没有「谁审核过 / 什么时候退役」。本表的主语是**企业**，
-- 且状态机是**审核门禁**：`draft` 不进 prompt、`retired` 立即消失（读面**不缓存**）。
--
-- ## 为什么 trigger / counter 是结构化文本而不是自然语言
-- 本仓铁律：自然语义 `data_checks` 不许只写不判。`trigger` / `counter` 存的是
-- **条件语言 JSON 对象**（算子白名单见 app/playbook/condition.py 的 OPS 与
-- PlaybookConditionValidator.OPS，两处由 tests/unit_ci_workflows/test_playbook_condition_contract.py
-- 现取对账）。**自由文本一律不可执行** ⇒ 不出现任何出口（fail-closed）。
-- 用 TEXT 而不是 JSONB：写面已由 Java 校验器做结构校验，读面 Python 再 fail-closed 一次；
-- JSONB 会引入 PGobject ↔ String 的映射分支，换来的是同一件事的第二份实现。
--
-- ## 状态机（唯一合法迁移）
--   draft --activate--> active --retire--> retired
-- 迁移是 **CAS**（`WHERE state = <期望前态>`）⇒ 并发双审不会双激活。
--
-- ## 出口（同一源）
-- ① prompt 片段（本期）② 知识卡（P2 未做）③ 用例自动生成（本期）④ 工具默认参数（P2 未做）。
-- 读面唯一入口 = app/playbook/store.py（**不缓存**，否则「退役立即生效」判据会被缓存粘住）。

CREATE TABLE IF NOT EXISTS playbooks (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    -- tenant = 全企业；role = 某个岗位（scope_role 必填，见下方 CHECK）
    scope VARCHAR(16) NOT NULL DEFAULT 'tenant',
    scope_role VARCHAR(64),
    -- 条件语言 JSON 对象（**不是**自然语言；自由文本 ⇒ 所有出口 fail-closed）
    trigger_json TEXT NOT NULL,
    -- 正解：审核过的一句话口径（会作为 prompt 片段下发 ⇒ 读面必须消毒）
    correct_text TEXT NOT NULL,
    -- 反例：与 trigger 同一套条件语言，命中即「本卡不适用」
    counter_json TEXT,
    -- 来源：哪次会话、哪一轮（可追溯到原始纠正）
    source_session_id VARCHAR(128),
    source_turn INTEGER,
    -- 命中计数（P2 晋升/衰减的输入；本期只落列，不写）
    hits INTEGER NOT NULL DEFAULT 0,
    state VARCHAR(16) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    activated_at TIMESTAMP WITH TIME ZONE,
    retired_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(64),
    CONSTRAINT ck_playbooks_state CHECK (state IN ('draft', 'active', 'retired')),
    CONSTRAINT ck_playbooks_scope CHECK (scope IN ('tenant', 'role')),
    -- role 口径必须指名岗位：否则「按岗位生效」会静默退化成「全企业生效」
    CONSTRAINT ck_playbooks_scope_role CHECK (scope <> 'role' OR (scope_role IS NOT NULL AND scope_role <> '')),
    -- 空条件 = 无条件生效（最危险的形态）⇒ 库层直接拒收
    CONSTRAINT ck_playbooks_trigger_not_blank CHECK (length(btrim(trigger_json)) > 0),
    CONSTRAINT ck_playbooks_correct_not_blank CHECK (length(btrim(correct_text)) > 0)
);

-- 读面主查询：`WHERE tenant_id = ? AND state = 'active'`（每个 B 端回合一次，不缓存）
CREATE INDEX IF NOT EXISTS idx_playbooks_tenant_state ON playbooks (tenant_id, state);
-- 按岗位取（scope='role'）
CREATE INDEX IF NOT EXISTS idx_playbooks_tenant_scope ON playbooks (tenant_id, scope, scope_role);
-- 审核队列（draft 列表按时间倒序）
CREATE INDEX IF NOT EXISTS idx_playbooks_state_created ON playbooks (state, created_at DESC);

COMMENT ON TABLE playbooks IS
    'B 端口径卡（issue #8175 一期）：企业级可执行口径工件。'
    '状态机 draft→active→retired（CAS 迁移）；只有 active 进 prompt；退役立即生效（读面不缓存）。'
    'trigger/counter 是结构化条件语言 JSON（算子白名单 = app/playbook/condition.py::OPS ↔ '
    'PlaybookConditionValidator.OPS，由 tests/unit_ci_workflows/test_playbook_condition_contract.py 对账）。';

COMMENT ON COLUMN playbooks.trigger_json IS
    '触发条件（条件语言 JSON 对象）。自由文本 / 未知算子 / 空条件 ⇒ 不合法 ⇒ 所有出口 fail-closed。';

COMMENT ON COLUMN playbooks.counter_json IS
    '反例（同一套条件语言）。命中 ⇒ 本卡不适用。它不是注释：出口③的用例必须生成 '
    '「反例命中 ⇒ 本卡不得生效」这条负向断言。';

COMMENT ON COLUMN playbooks.state IS
    'draft = 未审核（绝不进 prompt）/ active = 已审核（唯一进 prompt 的状态）/ retired = 已退役（立即消失）。';
