-- =====================================================================
-- V28: 通知模板与规则种子数据（系统内置，tenant_id=0，只读）
-- 与 OrderService / AfterSalesTicketService 的事件触发代码配套：
--   order_created                → 新订单创建
--   order_status_changed         → 订单状态变更
--   after_sales_created          → 售后工单创建
--   after_sales_status_changed   → 售后工单状态变更
-- 模板变量以 {{var}} 占位，triggerByEvent 时按 contextData 替换。
-- =====================================================================

INSERT INTO notification_templates
    (id, tenant_id, name, type, channel, template_content, variables, status, created_at, updated_at)
VALUES
    ('tpl-sys-order-created', 0, 'order_created', 'order', 'internal',
     '订单 {{orderNo}} 已创建，待确认金额 {{amount}} 元。', 'orderNo,amount', 'active', NOW(), NOW()),
    ('tpl-sys-order-status', 0, 'order_status_changed', 'order', 'internal',
     '您的订单 {{orderNo}} 状态已更新为 {{status}}。', 'orderNo,status', 'active', NOW(), NOW()),
    ('tpl-sys-as-created', 0, 'after_sales_created', 'after_sales', 'internal',
     '您的售后工单 {{ticketNo}}（{{ticketType}}）已提交，我们将尽快处理。', 'ticketNo,ticketType', 'active', NOW(), NOW()),
    ('tpl-sys-as-status', 0, 'after_sales_status_changed', 'after_sales', 'internal',
     '您的售后工单 {{ticketNo}} 状态已更新为 {{status}}。', 'ticketNo,status', 'active', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO notification_rules
    (id, tenant_id, event_type, recipient_type, channels, enabled, template_id, created_at, updated_at)
VALUES
    ('rule-sys-0001', 0, 'order_created', 'user', 'internal', TRUE, 'tpl-sys-order-created', NOW(), NOW()),
    ('rule-sys-0002', 0, 'order_status_changed', 'user', 'internal', TRUE, 'tpl-sys-order-status', NOW(), NOW()),
    ('rule-sys-0003', 0, 'after_sales_created', 'user', 'internal', TRUE, 'tpl-sys-as-created', NOW(), NOW()),
    ('rule-sys-0004', 0, 'after_sales_status_changed', 'user', 'internal', TRUE, 'tpl-sys-as-status', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;