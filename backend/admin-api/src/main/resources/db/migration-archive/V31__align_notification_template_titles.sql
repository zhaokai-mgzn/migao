-- =====================================================================
-- V31: 系统模板/规则种子校准（中文业务标题，upsert 幂等）
--
-- 背景（生产实证，issue #2972）：V29 重建表 + V30 播种期间，MigrationRunner
-- 的 getResources 返回逆序（V30 先于 V29 执行），V29 的 DROP 把 V30 中文种子
-- 清空，最终库内残留 V28 的英文名种子（order_created 等），铃铛/通知中心
-- 展示为英文事件名。本迁移把模板名称/文案统一为中文业务标题。
--
-- 幂等：ON CONFLICT (id) DO UPDATE——全新库直接插入，已有行更新名称/文案，
-- 重复执行结果一致；对既有 rules（template_id 引用）无破坏。
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
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    template_content = EXCLUDED.template_content,
    variables = EXCLUDED.variables,
    status = EXCLUDED.status,
    updated_at = NOW();