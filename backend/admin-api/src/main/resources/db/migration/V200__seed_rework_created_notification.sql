-- 返工单**新增即通知**（issue #7860 用户追加要求：「新增返工单需要产生通知消息」）
--
-- ## 一句话
-- 改前：返工单落在 `rework_orders` 里，但没有任何站内信 —— 车间报的返工没人被叫醒，PC「返工单」页全靠人主动看。
--
-- ## 本段范围
-- - ✅ 事件 `rework_order_created` 的系统模板（tenant_id = 0）+ 规则（收件人 = 租户管理员 `employee`）
-- - ✅ 两个来源**同一句**话，只在 `{{sourceText}}` 上区分（售后判定 / 车间报返工）
-- - ❌ 不改通知派发实现（`NotificationService.triggerForTenantAdmins` 既有口径），不加新通道
--
-- ## 幂等
-- `ON CONFLICT (id) DO NOTHING`：迁移重跑 / 建库脚本重复执行都不会长出第二份模板或规则。
-- 通知本身另有一层去重（`eventType:bizId:recipientId` 去重键）⇒ 同一张返工单不会发两条。
--
-- ## 回滚
-- `DELETE FROM notification_rules WHERE id = 'rule-sys-0007';`
-- `DELETE FROM notification_templates WHERE id = 'tpl-sys-rework-created';`
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO notification_templates
    (id, tenant_id, name, title_template, type, channel, template_content, variables, status, created_at, updated_at)
VALUES
    ('tpl-sys-rework-created', 0, '返工单通知', '返工单 {{reworkNo}} 待处理', 'rework', 'internal',
     '加工单 {{processingOrderNo}} · 工序 {{operationName}} · {{qtyText}}；原因：{{reason}}；来源：{{sourceText}}',
     'reworkNo,processingOrderNo,operationName,qtyText,reason,sourceText', 'active', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO notification_rules
    (id, tenant_id, event_type, recipient_type, channels, enabled, template_id, created_at, updated_at)
VALUES
    ('rule-sys-0007', 0, 'rework_order_created', 'employee', 'internal', TRUE, 'tpl-sys-rework-created', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

COMMIT;
