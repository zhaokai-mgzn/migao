-- =====================================================================
-- V43: 加工单表（issue #3340，设计文档 docs/design/processing-order-design.md）
-- =====================================================================
-- 加工单 = 订单 producing 阶段的子进度（1 订单 : 1 加工单）。
-- 幂等约束：同一订单同时只允许一个非取消态的加工单（partial unique index）。
-- 快照 items_snapshot 在生成时固化（商品/颜色/门幅/宽/高/数量/加工项含 options），
-- 订单后续改价/改项不影响已发加工单；快照不含销售价（防暴露加价）。
-- =====================================================================

CREATE TABLE IF NOT EXISTS processing_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    processing_order_no VARCHAR(32) NOT NULL,
    processor VARCHAR(128),
    expected_delivery_date DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'generated',  -- generated/issued/in_processing/completed/cancelled
    items_snapshot JSONB NOT NULL DEFAULT '[]',
    remark TEXT,
    template_version INT DEFAULT 1,
    generated_by VARCHAR(64),
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    issued_at TIMESTAMP WITH TIME ZONE,
    in_processing_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_reason TEXT,
    print_count INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);

-- 幂等：同一订单最多一个非取消态加工单（取消后可重新生成）
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_active
    ON processing_orders (order_id)
    WHERE deleted = 0 AND status IN ('generated', 'issued', 'in_processing', 'completed');

CREATE INDEX IF NOT EXISTS idx_processing_orders_tenant_status
    ON processing_orders (tenant_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_no
    ON processing_orders (processing_order_no);

-- =====================================================================
-- 存量租户权限补齐（幂等，与 RegistrationService 种子目录同源）：
--   processing:view   → 客服/运营/销售/财务
--   processing:update → 运营（管理员运行时特判 ["*"]，无需显式关联）
-- =====================================================================
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '加工单查看', 'processing:view', 'processing-order', 'view', '查看加工单', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'processing:view');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '加工单操作', 'processing:update', 'processing-order', 'update', '生成/发加工/取消加工单', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'processing:update');

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('customer_service', 'operator', 'sales', 'finance') AND r.deleted = 0 AND p.code = 'processing:view'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'operator' AND r.deleted = 0 AND p.code = 'processing:update'
ON CONFLICT (role_id, permission_id) DO NOTHING;
