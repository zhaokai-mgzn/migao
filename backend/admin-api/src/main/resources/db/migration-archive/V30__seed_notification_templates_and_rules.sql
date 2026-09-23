-- =====================================================================
-- V30: 通知模板与规则种子数据（系统内置，tenant_id=0，只读）
--
-- 与业务触发代码配套的事件×模板映射（接收人由触发代码按角色路由）：
--   order_created               → 新订单待处理（租户管理员）
--   order_status_changed        → 订单进度告知（订单归属用户）
--   after_sales_created         → 新售后工单待处理（租户管理员，含投诉工单）
--   after_sales_status_changed  → 工单进度告知（订单归属用户）
--
-- 模板名称使用中文业务标题（通知中心/铃铛直接展示），事件匹配走规则表的
-- event_type，模板名不承担匹配职责。
-- 模板变量以 {{var}} 占位，triggerByEvent 时按 contextData 替换。
-- =====================================================================

INSERT INTO notification_templates
    (id, tenant_id, name, type, channel, template_content, variables, status, created_at, updated_at)
VALUES
    ('tpl-sys-order-created', 0, '新订单通知', 'order', 'internal',
     '新订单 {{orderNo}} 已创建，待确认金额 {{amount}} 元。', 'orderNo,amount', 'active', NOW(), NOW()),
    ('tpl-sys-order-status', 0, '订单状态变更', 'order', 'internal',
     '您的订单 {{orderNo}} 状态已更新为 {{status}}。', 'orderNo,status', 'active', NOW(), NOW()),
    ('tpl-sys-as-created', 0, '新售后工单通知', 'after_sales', 'internal',
     '收到售后申请：工单 {{ticketNo}}（{{ticketType}}），请及时处理。', 'ticketNo,ticketType', 'active', NOW(), NOW()),
    ('tpl-sys-as-status', 0, '售后工单状态变更', 'after_sales', 'internal',
     '您的售后工单 {{ticketNo}} 状态已更新为 {{status}}。', 'ticketNo,status', 'active', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO notification_rules
    (id, tenant_id, event_type, recipient_type, channels, enabled, template_id, created_at, updated_at)
VALUES
    ('rule-sys-0001', 0, 'order_created', 'employee', 'internal', TRUE, 'tpl-sys-order-created', NOW(), NOW()),
    ('rule-sys-0002', 0, 'order_status_changed', 'user', 'internal', TRUE, 'tpl-sys-order-status', NOW(), NOW()),
    ('rule-sys-0003', 0, 'after_sales_created', 'employee', 'internal', TRUE, 'tpl-sys-as-created', NOW(), NOW()),
    ('rule-sys-0004', 0, 'after_sales_status_changed', 'user', 'internal', TRUE, 'tpl-sys-as-status', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;