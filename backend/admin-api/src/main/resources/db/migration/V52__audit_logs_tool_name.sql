-- audit_logs.action 语义收敛为「动词」+ 工具名另置 tool_name（issue #4071 裁定 ①）
--
-- 病灶：`audit_logs.action` 里此前放的是**工具名**（`after_sales_manage` / `product_manage`…），
-- 靠 `resource_type = 'agent_tool'` 区分「agent 工具写」与既有的人工审计 ——
-- ⇒ **同一列两种语义**，查询/报表侧必须知道「action 的含义取决于 resource_type」这条
-- 隐式规则。这正是本仓库反复批判的「同一概念两个来源」形态。
--
-- 收敛后（本迁移 + `app/tools/registry.py` 同时生效）：
--   · `action`      = **动词**（create / update / delete / toggle_status / confirm_payment…），
--                     取自工具调用的 `action` 参数；无该参数的工具走 registry 里的
--                     **显式映射表** `_NO_ACTION_PARAM_TOOL_ACTION`（禁止用工具名当动词）；
--   · `tool_name`   = 工具名（本次迁移新增）；
--   · `resource_type` 保持 `agent_tool`（区分 AI 与人工审计的职责不变，是**另一个**维度）。
--
-- 幂等：`ADD COLUMN IF NOT EXISTS`；回填 UPDATE 只命中「action 仍是工具名且能从
-- action_details 派生出动词」的行 —— 重跑命中 0 行（终态确定）。
--
-- 表内数据量极小（audit_logs 当日才刚有写入方，见 #4039/#4066），无需分批。

-- ── A. 结构：新增 tool_name 列 ────────────────────────────────────────────────
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS tool_name VARCHAR(64);

COMMENT ON COLUMN audit_logs.tool_name IS
    'AI 工具写审计的工具名（如 after_sales_manage / product_manage）；'
    '仅 resource_type 为 agent_tool 的行有值。人工表单审计该列为 NULL。见 issue #4071';

COMMENT ON COLUMN audit_logs.action IS
    '动作**动词**（create/update/delete/toggle_status/confirm_payment…），不含工具名 —— '
    '工具名在 tool_name 列。人工审计沿用既有动词口径（DA-008 家族）。见 issue #4071';

-- 工具名分面查询（该列选择度低但表极小，仅服务于「按工具回溯」这一种取证诉求）
CREATE INDEX IF NOT EXISTS idx_audit_logs_tool_name ON audit_logs(tool_name);

-- ── B. 回填：把存量 agent_tool 行的工具名从 action 搬到 tool_name，action 换成动词 ──
--
-- 回填口径（两级，**必须顺序执行**）：
--   ① `tool_name := action`（该批行的 action 就是工具名），限定 `resource_type = 'agent_tool'`；
--   ② `action := action_details ->> 'action'` —— 从 JSON 的 `action` 字段派生。
--      该字段由 registry 的 `derive_audit_action()` 写入（唯一事实源），
--      即「工具调用的 action 参数」或「显式映射表的兜底动词」——
--      **不是**本迁移自己另写一份推导规则（那会是同一判据的第二份实现）。
UPDATE audit_logs
SET tool_name = action
WHERE resource_type = 'agent_tool'
  AND tool_name IS NULL;

UPDATE audit_logs
SET action = LEFT(action_details ->> 'action', 64)
WHERE resource_type = 'agent_tool'
  -- 只改「还是工具名」的行：entry ① 刚把工具名写进 tool_name ⇒ `action = tool_name` 即
  -- 「尚未换动词」。**只认这一条判据**，不额外断言 JSON 里是不是动词 ——
  -- 新写入方的 action 已经是动词、不满足本条件 ⇒ 重跑命中 0 行（幂等且无脏写）。
  AND tool_name IS NOT NULL
  AND action = tool_name
  AND action_details ->> 'action' IS NOT NULL
  AND btrim(action_details ->> 'action') <> ''
  -- 再拒收「JSON 里仍是工具名」的形态（历史行由旧版 registry 写入 ⇒ 那时 JSON 无该字段；
  -- 或 registry 遇到未登记工具时落的哨兵 `(unmapped)`）—— 一律**不猜**、保持原值。
  AND (action_details ->> 'action') NOT IN (
      -- 与本迁移同时存在的 21 个写工具（源码 `read_only = False`；判据见
      -- tests/test_write_audit_action_semantics.py，漏一个即红）
      'after_sales_manage', 'aftersale_create', 'category_manage', 'customer_manage',
      'employee_manage', 'finance_api', 'human_handoff', 'inventory_manage',
      'notification_manage', 'order_create', 'order_manage', 'processing_item_manage',
      'processing_order_generate', 'processing_order_update', 'product_manage',
      'product_processing_item_manage', 'product_update', 'role_manage', 'session_manage',
      'settings_manage', 'sku_update'
  );

-- ⚠️ **派生不出来的行：保持 `action` 原值（工具名），不猜**（issue #4071 明确要求）。
-- 命中该形态的只可能是：旧版 registry 写下的行（那时 JSON 里没有 `action` 字段）或
-- `[AUDIT] ACTION_UNMAPPED` 哨兵行。改名成任何「最可能的动词」都是**编造取证材料** ——
-- 审计表的价值恰恰在于它不编。
-- 这些行的可读性由 `tool_name` 列兜住（① 已把工具名搬列，语义不再丢），
-- 需要清理时按 `tool_name = action` 辨认：`SELECT id, action, tool_name FROM audit_logs
-- WHERE resource_type='agent_tool' AND tool_name IS NOT NULL AND action = tool_name;`