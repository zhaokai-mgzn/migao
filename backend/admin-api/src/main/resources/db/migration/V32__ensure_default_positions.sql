-- =====================================================================
-- V32: 五岗默认岗位兜底补齐（#2982 修复 V29 覆盖缺口）
--
-- 背景：V29 只对 sales/finance 做 INSERT 兜底，对 customer_service 仅
-- UPDATE 改名 + role_permissions 关联——若存量租户根本没有该角色行
-- （早期种子缺失 / 曾被逻辑删除 deleted=1），角色永久缺失，员工弹窗
-- 岗位下拉缺「客服」等岗位。
--
-- 本迁移（幂等，可重复执行）对五岗统一采用 ON CONFLICT (tenant_id, code)
-- DO UPDATE 语义：
--   • 无该 code 行          → INSERT 新建（gen_random_uuid 生成 id）
--   • 有 deleted=1 旧行     → 复活为 deleted=0 并对齐 name（撞唯一键兜底）
--   • 有 deleted=0 行       → 对齐 name/description（幂等）
-- role_permissions 全量 ON CONFLICT (role_id, permission_id) DO NOTHING 补齐。
-- =====================================================================

-- ── ① 五岗角色存在性兜底（管理员/客服/运营/销售/财务）──────────────
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '管理员', 'admin', '拥有全部管理权限', 'active', NOW(), NOW(), 0
FROM tenants t
ON CONFLICT (tenant_id, code) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = 'active',
  deleted = 0;

INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '客服', 'customer_service', '负责客户服务与咨询', 'active', NOW(), NOW(), 0
FROM tenants t
ON CONFLICT (tenant_id, code) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = 'active',
  deleted = 0;

INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '运营', 'operator', '负责日常运营管理', 'active', NOW(), NOW(), 0
FROM tenants t
ON CONFLICT (tenant_id, code) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = 'active',
  deleted = 0;

INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '销售', 'sales', '负责销售业务', 'active', NOW(), NOW(), 0
FROM tenants t
ON CONFLICT (tenant_id, code) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = 'active',
  deleted = 0;

INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '财务', 'finance', '负责财务对账', 'active', NOW(), NOW(), 0
FROM tenants t
ON CONFLICT (tenant_id, code) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = 'active',
  deleted = 0;

-- ── ② 五岗默认权限 role_permissions（幂等：UNIQUE(role_id, permission_id)）──
-- 管理员：全部权限码
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

-- 运营：看板/订单/商品/加工/客户/财务/会话/员工列表
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