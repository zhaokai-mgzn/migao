-- 售后查看 / 知识库查看 两个**读**码的存量租户补齐（issue #5246）
--
-- ## 一句话
--   给**已存在**的租户补两件事：
--   ① `permissions` 目录加 `after_sales:view`（售后工单读码）与 `knowledge:view`（知识库读码）；
--   ② 把这两个码授给内置岗位 `customer_service` 与 `operator`
--      —— 与 `RegistrationService.initializeDefaultRolesAndPermissions` 的**新租户种子同源同码**。
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService` 全量 seed；存量租户的**目录**只在
--   `PermissionService.ensureFullPermissionCatalog` 被懒调用时补种，而 **role_permissions 没有任何
--   Java 路径会给既有岗位补** ⇒ 只改 Java 的话，老租户的客服/运营永远拿不到这两个码，而侧边栏
--   节点（`config/menu.ts` 的「售后工单」/「知识库」）已改用读码 ⇒ 菜单对老租户**永久不可见**。
--   这正是「新租户有、老租户没有」的经典半成品形态（同 V111 对 inbound:* 的处理理由）。
--
-- ## 读/写拆码的由来（本迁移只加读码，**不动**写码）
--   此前售后工单与知识库的读面与写面共用 `order:refund` / `knowledge:manage`：
--   想看工单/知识卡片就必须被授予「处理退款」/「增删改发布」的写权。本单拆出读码后，
--   这两个岗位拿到的是**读**权限 —— **不新增任何写能力**（写码 `order:refund` / `knowledge:manage`
--   照旧只授予原本就有它的岗位：operator 有 order:refund，两岗位都没有 knowledge:manage）。
--
-- ## 为什么只授 customer_service / operator
--   与 `RegistrationService` 的岗位默认列表逐字一致（这两个岗位本就是售后与知识库的日常使用方）。
--   `admin` 恒为 `["*"]`（无需补）；`sales` / `finance` **不在本单的可见性变更范围内**（不扩权）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`
--     （与 V43 / V111 的既有写法逐字同款）；
--   · 本文件**只 INSERT，不改既有行** ⇒ 第二遍的两条 INSERT 均为 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（见文末 `DO` 块）：① 两码在**每个已有权限目录的租户**里都存在；
--   ② 两个岗位对两码的 `role_permissions` 链接数等于应有条数 —— 任一不满足即
--   `RAISE EXCEPTION` 并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--   两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V124__rollback_read_permissions.sql（本单只登记，不落码）
-- DELETE FROM role_permissions WHERE permission_id IN
--     (SELECT id FROM permissions WHERE code IN ('after_sales:view', 'knowledge:view'));
-- DELETE FROM permissions WHERE code IN ('after_sales:view', 'knowledge:view');
-- ```
-- **回滚是有损的**：若已有人在「岗位权限」页手工勾选过这两个码，回滚会把那些勾选一并删除
-- （岗位权限页的勾选与岗位默认权限同表）。属**有意** —— 权限码消失后残留的 role_permissions
-- 会指向不存在的权限（悬空授权），比丢勾选更危险。
--
-- ## bootstrap 终态同步（如实登记）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）**不含任何 permissions / role_permissions 种子行**
--   （该文件只建表结构，权限种子恒由 Java seed + 迁移链产出）⇒ 本迁移**无需**同步 schema.sql。
--   判据（可复算）：`grep -c "INSERT INTO permissions" docs/sql/schema.sql` ⇒ 0。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：两个**读**码（同租户同码已存在即跳过）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '售后查看', 'after_sales:view', 'after-sales', 'view', '查看售后工单', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'after_sales:view');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '知识库查看', 'knowledge:view', 'knowledge', 'view', '查看知识卡片', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'knowledge:view');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：customer_service / operator（与 RegistrationService 的岗位默认列表一致）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('customer_service', 'operator') AND r.deleted = 0 AND p.code = 'after_sales:view'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('customer_service', 'operator') AND r.deleted = 0 AND p.code = 'knowledge:view'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_codes INTEGER;
    tenant_codes  INTEGER;
    link_count    INTEGER;
    expected      INTEGER;
BEGIN
    -- ① 两码必须在**每个已有权限目录的租户**里各存在一行
    --    （不以 tenants 为全集：没有任何 permissions 行的租户 = 尚未初始化，不在本迁移射程内）
    SELECT COUNT(*) INTO missing_codes
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND (
            NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'after_sales:view')
         OR NOT EXISTS (SELECT 1 FROM permissions p2 WHERE p2.tenant_id = t.id AND p2.code = 'knowledge:view')
       );
    IF missing_codes > 0 THEN
        RAISE EXCEPTION 'V123 终态对账失败：% 个租户缺 after_sales:view / knowledge:view —— 回滚本迁移', missing_codes;
    END IF;

    -- ② 两个岗位 × 两个码 = 应有链接数（按「该租户里两个码都存在」的岗位行计数）
    SELECT COUNT(*) INTO expected
      FROM roles r
      JOIN permissions p ON p.tenant_id = r.tenant_id
     WHERE r.code IN ('customer_service', 'operator') AND r.deleted = 0
       AND p.code IN ('after_sales:view', 'knowledge:view');
    SELECT COUNT(*) INTO link_count
      FROM role_permissions rp
      JOIN roles rl ON rl.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE rl.code IN ('customer_service', 'operator')
       AND p.code IN ('after_sales:view', 'knowledge:view')
       AND rp.deleted = 0;
    IF link_count <> expected THEN
        RAISE EXCEPTION 'V123 终态对账失败：role_permissions 链接数 % ≠ 应有 % —— 回滚本迁移', link_count, expected;
    END IF;

    -- ③ 幂等自证：两码的目录行数 = 有权限目录的租户数（重复执行不得产生副本）
    SELECT COUNT(*) INTO tenant_codes FROM permissions WHERE code = 'after_sales:view';
    IF tenant_codes <> (SELECT COUNT(DISTINCT tenant_id) FROM permissions) THEN
        RAISE EXCEPTION 'V123 终态对账失败：after_sales:view 行数 % ≠ 有权限目录的租户数 % —— 可能产生了重复行',
            tenant_codes, (SELECT COUNT(DISTINCT tenant_id) FROM permissions);
    END IF;

    RAISE NOTICE 'V123 终态对账通过：读码目录 + 岗位授权齐备（expected=% ，link=%）', expected, link_count;
END $$;

COMMIT;