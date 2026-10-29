-- 把「入库单查看」`inbound:view` 上背着的三类负载拆成三把独立读码（issue #8087，用户 2026-10-29 裁定 C）
--
-- ## 一句话
--   ① `permissions` 目录每个**已有目录**的租户补三行：`supplier:view` / `purchase:view` / `stock:view`；
--   ② 岗位授权**只给 `admin` 与 `operator`**（有意收窄，裁定 C：「只管理员/运营保留三把」）——
--      客服 / 销售 / 财务 / 商品管理员**不回填**，他们的「供应商 / 采购单 / 盘点单 / 出库单」入口随之消失；
--   ③ 终态对账：每个有目录的租户都有三码；三码的授权链接**只**落在 admin/operator 上。
--
-- ## 为什么必须有这条迁移（只改 Java 不够）
--   新租户走 `RegistrationService` 全量 seed；存量租户的目录只在 `PermissionService.ensureFullPermissionCatalog`
--   被懒调用时补种，而 **role_permissions 没有任何 Java 路径会给既有岗位补** ⇒ 存量租户的运营岗位
--   上线当天会**看不见**供应商/采购/库存单证（`inbound:view` 已不再为它们开门）。
--
-- ## 授权矩阵（裁定 C，**有意收窄**）
--   | 码 | 授予岗位 | 理由 |
--   |---|---|---|
--   | `supplier:view` / `purchase:view` / `stock:view` | **admin + operator** | 运营是这批动线的执行方（采购、对账、盘点、出库）；其余岗位按裁定 C 一律不回填 |
--   ⚠️ `admin` 恒为 `["*"]` ⇒ 给它补 `role_permissions` 行只是让「新老租户逐值一致」
--   （与 V129 / V132 的同款处理），不是它生效的必要条件。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`；
--   · 本文件只 INSERT ⇒ 第二遍结果与第一遍相同。
--
-- ## 回滚 SQL（登记，不落码）
--   DELETE FROM role_permissions rp USING permissions p
--     WHERE p.id = rp.permission_id AND p.code IN ('supplier:view','purchase:view','stock:view');
--   DELETE FROM permissions WHERE code IN ('supplier:view','purchase:view','stock:view');
--   ⚠️ 回滚前必须先回滚 admin-api 的可执行文件（代码把端点改回 `inbound:view`），否则这些页面对所有
--   非 admin 岗位都会 403。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：三行（同租户同码已存在即跳过）
--    名称/资源/动作/描述逐字取自 `RegistrationService.defaultPermissions` 与
--    `PermissionService.ensureFullPermissionCatalog` 的同码条目（两处目录必须逐值相等）。
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, v.name, v.code, v.resource_type, v.action, v.description,
       'active', NOW(), NOW(), 0
FROM tenants t
CROSS JOIN (VALUES
    ('供应商查看', 'supplier:view', 'supplier', 'view', '查看供应商档案（联系人与账期）'),
    ('采购单查看', 'purchase:view', 'purchase-order', 'view', '查看采购单与到货进度'),
    ('库存单证查看', 'stock:view', 'stock-document', 'view', '查看盘点单与出库单')
) AS v(name, code, resource_type, action, description)
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = v.code);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：**只 admin + operator**（裁定 C；其余岗位有意不回填）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
     AND p.code IN ('supplier:view', 'purchase:view', 'stock:view')
WHERE r.deleted = 0
  AND r.code IN ('admin', 'operator')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（两遍都必须成立 ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_tenants INTEGER;
    missing_grants  INTEGER;
    stray_grants    INTEGER;
BEGIN
    -- ① 三码必须在每个已有权限目录的租户里都存在
    SELECT COUNT(*) INTO missing_tenants
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND EXISTS (
           SELECT 1 FROM (VALUES ('supplier:view'), ('purchase:view'), ('stock:view')) AS v(code)
            WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = v.code)
       );
    IF missing_tenants > 0 THEN
        RAISE EXCEPTION 'V203 终态对账失败：% 个租户缺 supplier:view/purchase:view/stock:view —— 回滚本迁移', missing_tenants;
    END IF;

    -- ② admin 与 operator 必须各拿到三码（存量租户的运营岗位上线当天要能用）
    SELECT COUNT(*) INTO missing_grants
      FROM roles r
     WHERE r.deleted = 0 AND r.code IN ('admin', 'operator')
       AND (SELECT COUNT(*) FROM role_permissions rp
              JOIN permissions p ON p.id = rp.permission_id
             WHERE rp.role_id = r.id AND rp.deleted = 0
               AND p.code IN ('supplier:view', 'purchase:view', 'stock:view')) < 3;
    IF missing_grants > 0 THEN
        RAISE EXCEPTION 'V203 终态对账失败：% 个 admin/operator 岗位未拿满三码 —— 回滚本迁移', missing_grants;
    END IF;

    -- ③ 收窄断言：三码的授权链接**只**允许落在 admin / operator（多一个岗位 = 有人放宽了裁定 C）
    SELECT COUNT(*) INTO stray_grants
      FROM role_permissions rp
      JOIN roles r ON r.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE p.code IN ('supplier:view', 'purchase:view', 'stock:view')
       AND rp.deleted = 0
       AND r.code NOT IN ('admin', 'operator');
    IF stray_grants > 0 THEN
        RAISE EXCEPTION 'V203 终态对账失败：三码被授给了 % 个非 admin/operator 角色 —— 违反裁定 C', stray_grants;
    END IF;
END $$;

COMMIT;
