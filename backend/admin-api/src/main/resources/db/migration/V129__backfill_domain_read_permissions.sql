-- 三个域**读**码的存量租户补齐（issue #5291，用户 2026-09-25 裁定「方案①：新增读码」）
--
-- ## 一句话
--   给**已存在**的租户补三件事：
--   ① `permissions` 目录加 `product:category:view`（商品分类读码）/ `production:view`（生产域读码）
--      / `system:view`（岗位权限读码）；
--   ② 把每个读码授给**原本就持有对应管理码**的岗位 —— 与
--      `RegistrationService.initializeDefaultRolesAndPermissions` 的**新租户种子同源同码**；
--   ③ 终态对账（幂等 + fail-closed）。
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService` 全量 seed；存量租户的**目录**只在
--   `PermissionService.ensureFullPermissionCatalog` 被懒调用时补种，而 **role_permissions 没有任何
--   Java 路径会给既有岗位补** ⇒ 只改 Java 的话，老租户的运营岗位拿不到读码，而侧边栏节点
--   （`config/menu.ts` 的「生产看板 / 工艺配置 / 计件工资 / 加工项管理 / 岗位权限」）与读端点都已
--   改用读码 ⇒ 菜单对老租户**永久不可见**（同 V124 对 after_sales:view / knowledge:view 的理由）。
--
-- ## 授权口径（**只收窄不放宽**，逐条可复算）
--   本迁移授出的码**全部是读码**，且只授给「原本已持管理码」的岗位：
--     · `product:category:view` → 持 `product:category` 的岗位（分类读写原同码）；
--     · `production:view`       → 持 `processing:manage` 的岗位（生产域读面原挂管理码）；
--     · `system:view`           → 持 `system:manage` 的岗位（权限目录读面原挂管理码）。
--   ⇒ 这些岗位**本来**就能读那些端点的数据、也**本来**就看得见那些菜单 ⇒ 迁移前后的**可见面逐值相同**
--   （`admin` 恒为 `["*"]`，一并补 `role_permissions` 行以保持「新老租户逐值一致」）。
--   **不授**给只持旧读码 `processing:view` 的岗位（客服/销售/财务）—— 那才是放宽（#5246 已裁定
--   「客服/销售/财务不再经米宝查生产看板与计件数据」），本迁移**一个都不多授**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`（同 V43 / V111 / V124 写法）；
--   · 本文件**只 INSERT，不改既有行** ⇒ 第二遍的三条 INSERT 均为 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（见文末 `DO` 块）：① 三码在**每个已有权限目录的租户**里都存在；② 每个读码的
--   `role_permissions` 链接数等于「按同一谓词数出来的应有条数」—— 任一不满足即 `RAISE EXCEPTION`
--   并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V129__rollback_domain_read_permissions.sql（本单只登记，不落码）
-- DELETE FROM role_permissions WHERE permission_id IN
--     (SELECT id FROM permissions WHERE code IN ('product:category:view', 'production:view', 'system:view'));
-- DELETE FROM permissions WHERE code IN ('product:category:view', 'production:view', 'system:view');
-- ```
-- **回滚是有损的**：若已有人在「岗位权限」页手工勾选过这三个码，回滚会把那些勾选一并删除
-- （勾选与岗位默认权限同表）。属**有意** —— 权限码消失后残留的 role_permissions 会指向不存在的
-- 权限（悬空授权），比丢勾选更危险。
--
-- ## bootstrap 终态同步（如实登记）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）**不含任何 permissions / role_permissions 种子行**
--   （该文件只建表结构，权限种子恒由 Java seed + 迁移链产出）⇒ 本迁移**无需**同步 schema.sql。
--   判据（可复算）：`grep -c "INSERT INTO permissions" docs/sql/schema.sql` ⇒ 0。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：三个**读**码（同租户同码已存在即跳过）
--    ⚠️ 名称/资源/动作/描述逐字取自 `RegistrationService.defaultPermissions` 与
--       `PermissionService.ensureFullPermissionCatalog` 的同码条目（两处目录必须逐值相等，
--       判据见 tests/unit_ci_workflows/test_agent_permission_parity.py 判据 9②）。
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '商品分类查看', 'product:category:view', 'product', 'view', '查看商品分类', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'product:category:view');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '生产查看', 'production:view', 'production', 'view', '查看生产看板/加工项/工艺配置/计件', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'production:view');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '岗位权限查看', 'system:view', 'system', 'view', '查看岗位与权限目录', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'system:view');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：授给「原本就持有对应**管理码**」的岗位 + admin（恒为全部权限）
--     谓词 = `admin` ∨ 「该岗位已有 legacy 码的 role_permissions 行」
--     ⇒ 可见面与迁移前逐值相同（只收窄不放宽），且新老租户同口径。
-- ══════════════════════════════════════════════════════════════════════════════════════

-- ②-a 商品分类读码 ← 原持 product:category 的岗位
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'product:category:view'
WHERE r.deleted = 0
  AND (
        r.code = 'admin'
     OR EXISTS (
            SELECT 1 FROM role_permissions rp0
            JOIN permissions p0 ON p0.id = rp0.permission_id
            WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'product:category'
        )
      )
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ②-b 生产域读码 ← 原持 processing:manage 的岗位
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'production:view'
WHERE r.deleted = 0
  AND (
        r.code = 'admin'
     OR EXISTS (
            SELECT 1 FROM role_permissions rp0
            JOIN permissions p0 ON p0.id = rp0.permission_id
            WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'processing:manage'
        )
      )
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ②-c 岗位权限读码 ← 原持 system:manage 的岗位（内置岗位里只有 admin 持它）
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'system:view'
WHERE r.deleted = 0
  AND (
        r.code = 'admin'
     OR EXISTS (
            SELECT 1 FROM role_permissions rp0
            JOIN permissions p0 ON p0.id = rp0.permission_id
            WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'system:manage'
        )
      )
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_tenants INTEGER;
    expected        INTEGER;
    link_count      INTEGER;
    duplicated      INTEGER;
BEGIN
    -- ① 三码必须在**每个已有权限目录的租户**里各存在一行
    --    （不以 tenants 为全集：没有任何 permissions 行的租户 = 尚未初始化，不在本迁移射程内）
    SELECT COUNT(*) INTO missing_tenants
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND (
            NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'product:category:view')
         OR NOT EXISTS (SELECT 1 FROM permissions p2 WHERE p2.tenant_id = t.id AND p2.code = 'production:view')
         OR NOT EXISTS (SELECT 1 FROM permissions p3 WHERE p3.tenant_id = t.id AND p3.code = 'system:view')
       );
    IF missing_tenants > 0 THEN
        RAISE EXCEPTION 'V129 终态对账失败：% 个租户缺 product:category:view / production:view / system:view —— 回滚本迁移', missing_tenants;
    END IF;

    -- ② 三个读码的链接数 = 按②的同一谓词数出来的应有条数（逐码独立核对）
    SELECT COUNT(*) INTO expected
      FROM roles r
      JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'production:view'
     WHERE r.deleted = 0
       AND (r.code = 'admin' OR EXISTS (
                SELECT 1 FROM role_permissions rp0 JOIN permissions p0 ON p0.id = rp0.permission_id
                WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'processing:manage'));
    SELECT COUNT(*) INTO link_count
      FROM role_permissions rp
      JOIN roles rl ON rl.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE p.code = 'production:view' AND rp.deleted = 0;
    IF link_count <> expected THEN
        RAISE EXCEPTION 'V129 终态对账失败：production:view 链接数 % ≠ 应有 % —— 回滚本迁移', link_count, expected;
    END IF;

    SELECT COUNT(*) INTO expected
      FROM roles r
      JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'product:category:view'
     WHERE r.deleted = 0
       AND (r.code = 'admin' OR EXISTS (
                SELECT 1 FROM role_permissions rp0 JOIN permissions p0 ON p0.id = rp0.permission_id
                WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'product:category'));
    SELECT COUNT(*) INTO link_count
      FROM role_permissions rp
      JOIN roles rl ON rl.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE p.code = 'product:category:view' AND rp.deleted = 0;
    IF link_count <> expected THEN
        RAISE EXCEPTION 'V129 终态对账失败：product:category:view 链接数 % ≠ 应有 % —— 回滚本迁移', link_count, expected;
    END IF;

    SELECT COUNT(*) INTO expected
      FROM roles r
      JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'system:view'
     WHERE r.deleted = 0
       AND (r.code = 'admin' OR EXISTS (
                SELECT 1 FROM role_permissions rp0 JOIN permissions p0 ON p0.id = rp0.permission_id
                WHERE rp0.role_id = r.id AND rp0.deleted = 0 AND p0.code = 'system:manage'));
    SELECT COUNT(*) INTO link_count
      FROM role_permissions rp
      JOIN roles rl ON rl.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE p.code = 'system:view' AND rp.deleted = 0;
    IF link_count <> expected THEN
        RAISE EXCEPTION 'V129 终态对账失败：system:view 链接数 % ≠ 应有 % —— 回滚本迁移', link_count, expected;
    END IF;

    -- ③ 幂等自证：每个码的目录行数 = 有权限目录的租户数（重复执行不得产生副本）
    SELECT COUNT(*) INTO duplicated
      FROM permissions
     WHERE code IN ('product:category:view', 'production:view', 'system:view')
       AND tenant_id IN (
            SELECT tenant_id FROM permissions
             WHERE code IN ('product:category:view', 'production:view', 'system:view')
             GROUP BY tenant_id, code HAVING COUNT(*) > 1
       );
    IF duplicated > 0 THEN
        RAISE EXCEPTION 'V129 终态对账失败：读码目录出现 % 行重复（同租户同码多行）—— 回滚本迁移', duplicated;
    END IF;

    RAISE NOTICE 'V129 终态对账通过：三个域读码目录 + 岗位授权齐备';
END $$;

COMMIT;