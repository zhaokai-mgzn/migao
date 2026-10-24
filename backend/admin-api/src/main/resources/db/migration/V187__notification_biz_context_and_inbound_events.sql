-- 通知补结构化业务信息 + 入库单过账/作废必发站内信（issue #7524）
--
-- ## 一句话
-- 改前：`triggerByEvent` 只把模板渲染成 `title + content` 两段**文本** ⇒ 铃铛里点不进任何单据、
-- 通知中心只能按已读态筛；而且入库链路（全仓唯一改库存/成本/台账的地方）**一条通知都不发**。
--
-- ## 本迁移做四件事
-- ① `notifications` 增 7 列：业务对象（biz_type/biz_id/biz_no）、落地页（target_path）、
--    严重级（severity）、业务时间（occurred_at）、幂等键（dedupe_key）。
-- ② 幂等：`uk_notifications_dedupe (tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL`
--    —— 同一事件 × 同一业务对象 × 同一收件人只落一条（先查一次是常规路径，索引是最终保证）。
-- ③ `notification_templates` 增 `title_template`：标题也能带单号（如「入库单 {{inboundNo}} 已过账」）；
--    为空回落 `name`，**老模板零改动**。
-- ④ 入库两条系统规则/模板（tenant_id=0）：`inbound_posted` / `inbound_cancelled`。
--    触发点在 `InboundOrderService#post` / `#cancel`（工人拍照入库走同一个 `post()`，因此一并覆盖）。
--
-- ## 有意不做（如实登记）
-- - payload 业务快照 / group_key 聚合 / 静默时段：本段不写没有消费方的列（YAGNI）。
-- - 短信/微信/邮件渠道：`triggerByEvent` 仍只发 internal（渠道实现不在本段）。
-- - 按角色路由：收件人仍 = 租户 admin（与 `order_created` 同口径）。
--
-- ## 回滚
-- 停用规则即可停发（`enabled=false`）；删列会丢历史通知的业务关联，**不要**在存量库上回收。
--
-- ## 显式事务
-- 迁移链与 `psql -f` 逐条 autocommit 两条执行路径必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE notifications ADD COLUMN IF NOT EXISTS biz_type VARCHAR(32);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS biz_id VARCHAR(64);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS biz_no VARCHAR(64);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS target_path VARCHAR(255);
-- 严重级：info（默认）/ warn / urgent —— 不给库里已存在的行造假严重级：存量行留 NULL，
-- 前端按 info 渲染（`severity` 只在结构化事件写入时才落值）。
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS severity VARCHAR(16);
-- 业务发生时间（与 created_at 区分）：补发/重放时业务时间不变。
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(160);

COMMENT ON COLUMN notifications.biz_type IS '业务对象类型：order / after_sales / inbound_order（issue #7524）';
COMMENT ON COLUMN notifications.biz_id IS '业务对象主键（跳转与幂等的挂载点，不是展示值）';
COMMENT ON COLUMN notifications.biz_no IS '业务对象单号（展示用，如 RK-20261023-0001）';
COMMENT ON COLUMN notifications.target_path IS '前端落地页（含 query）；空 = 无可跳转页面';
COMMENT ON COLUMN notifications.severity IS 'info / warn / urgent；存量行 NULL 按 info 渲染';
COMMENT ON COLUMN notifications.dedupe_key IS '幂等键 eventType:bizId:recipientId；唯一索引兜底';

-- 幂等：同一租户下 dedupe_key 唯一（NULL 不参与 —— 老调用方不传 key，行为逐字不变）
CREATE UNIQUE INDEX IF NOT EXISTS uk_notifications_dedupe
    ON notifications (tenant_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- 通知中心「按业务类型筛」的热路径（列表恒带 recipient_id + 时间倒序）
CREATE INDEX IF NOT EXISTS idx_notifications_biz
    ON notifications (recipient_id, biz_type, created_at DESC)
    WHERE biz_type IS NOT NULL;

ALTER TABLE notification_templates ADD COLUMN IF NOT EXISTS title_template VARCHAR(255);

COMMENT ON COLUMN notification_templates.title_template IS '标题模板（支持 {{var}}）；空 = 回落 name（issue #7524）';

-- 入库过账：供应商 / 行数 / 米数 / 金额 / 操作人 —— 一句话说清「库存为什么变了」
INSERT INTO notification_templates
    (id, tenant_id, name, title_template, type, channel, template_content, variables, status, created_at, updated_at)
VALUES
    ('tpl-sys-inbound-posted', 0, '入库过账通知', '入库单 {{inboundNo}} 已过账', 'inbound', 'internal',
     '供应商 {{supplier}}，共 {{lineCount}} 行、入库 {{totalMeters}} 米，金额 {{amount}} 元；操作人 {{operator}}。',
     'inboundNo,supplier,lineCount,totalMeters,amount,operator', 'active', NOW(), NOW()),
    ('tpl-sys-inbound-cancelled', 0, '入库单作废通知', '入库单 {{inboundNo}} 已作废', 'inbound', 'internal',
     '作废原因：{{reason}}；操作人 {{operator}}。该单未进库存，无需冲销。',
     'inboundNo,reason,operator', 'active', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO notification_rules
    (id, tenant_id, event_type, recipient_type, channels, enabled, template_id, created_at, updated_at)
VALUES
    ('rule-sys-0005', 0, 'inbound_posted', 'employee', 'internal', TRUE, 'tpl-sys-inbound-posted', NOW(), NOW()),
    ('rule-sys-0006', 0, 'inbound_cancelled', 'employee', 'internal', TRUE, 'tpl-sys-inbound-cancelled', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

COMMIT;
