-- =====================================================================
-- V29: 存量租户岗位权限体系补齐（#2969 岗位=角色体系）
--
-- 背景：角色权限页改名「岗位权限」，岗位即 roles 表记录，role_permissions
-- 即岗位默认权限。存量租户注册时仅初始化 3 角色（企业管理员/运营人员/客服人员）
-- 且无 role_permissions 关联。本迁移（幂等）为每个存量租户：
--   ① 补齐缺省的 销售(sales) / 财务(finance) 岗位；
--   ② 统一五岗岗位名（管理员/客服/运营/销售/财务，与注册种子口径一致）；
--   ③ 为五岗预置默认权限（role_permissions 关联，缺失的细粒度权限码自动跳过，
--      与 RegistrationService 种子权限目录同源：dashboard:view 等 17 条）。
-- 新租户注册走 RegistrationService.initializeDefaultRolesAndPermissions，
-- 本迁移仅服务存量库，二者职责不重叠（迁移幂等，重复执行无副作用）。
-- =====================================================================

-- ── ① 补齐缺省岗位（幂等：按 (tenant_id, code) 去重）──────────────
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '销售', 'sales', '负责销售业务', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'sales' AND r.deleted = 0);

INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '财务', 'finance', '负责财务对账', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'finance' AND r.deleted = 0);

-- ── ② 统一五岗岗位名（历史种子名 → 岗位权限口径）───────────────────
UPDATE roles SET name = '管理员' WHERE code = 'admin' AND deleted = 0 AND name <> '管理员';
UPDATE roles SET name = '客服' WHERE code = 'customer_service' AND deleted = 0 AND name <> '客服';
UPDATE roles SET name = '运营' WHERE code = 'operator' AND deleted = 0 AND name <> '运营';

-- ── ③ 五岗默认权限 role_permissions（幂等：UNIQUE(role_id, permission_id)）──
-- 管理员：全部权限码（岗位权限页回显「全部权限」；运行时 getUserPermissions 对 admin 仍特判 ["*"]）
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'admin' AND r.deleted = 0
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 客服：会话 + 客户 + 订单查看
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
  AND p.code IN ('dashboard:view', 'order:list', 'order:detail', 'customer:view', 'agent:session', 'agent:quickreply')
WHERE r.code = 'customer_service' AND r.deleted = 0
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 运营：看板/订单/商品/加工/客户/财务/会话/员工列表（与原 operator 硬编码集对齐，不含 system:manage）
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
  AND p.code IN ('dashboard:view', 'order:list', 'order:detail', 'order:refund',
                 'product:list', 'product:create', 'product:category', 'processing:manage',
                 'customer:view', 'finance:view', 'agent:session', 'agent:quickreply', 'employee:list')
WHERE r.code = 'operator' AND r.deleted = 0
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 销售：看板/商品/订单查看/客户
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
  AND p.code IN ('dashboard:view', 'product:list', 'order:list', 'order:detail', 'customer:view')
WHERE r.code = 'sales' AND r.deleted = 0
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- 财务：看板/订单查看/财务
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
  AND p.code IN ('dashboard:view', 'order:list', 'order:detail', 'finance:view')
WHERE r.code = 'finance' AND r.deleted = 0
ON CONFLICT (role_id, permission_id) DO NOTHING;