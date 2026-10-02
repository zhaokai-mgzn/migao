-- 存量租户内置岗位的权限收敛到清单（issue #5699 的 **P5**；设计真值源 `docs/design/rbac-single-source.md` §4 的 P5 行 / §2.7）
--
-- ## 一句话
--   把「**清单声明里有、迁移链上没给**」的 `(岗位, 码)` **逐条幂等补齐** ——
--   收敛「存量租户的 `role_permissions` = 该租户历史跑过的迁移之并集」这条**路径依赖**。
--
-- ## 🔴 本文件是**生成物**，不是手写真值（用户裁定逐字：「不要打补丁了」）
--   文件头与语句的**值**全部由 `rbac/generate_migration.py` 从 `rbac/manifest.json` + 迁移链推演渲染：
--   `python3 rbac/generate_migration.py`（手改本文件 ⇒ `rbac` 判据判红；清单改了没重渲染 ⇒ 亦判红）。
--   ⇒ 「存量岗位该有哪些码」这件事**仍然只有一处真值**（清单），迁移只是它的一次**物化**（设计 §2.7）。
--
-- ## 现取差集（渲染时刻的读数，由推演给出而不是手抄）
--   · `admin` ← `after_sales:view`、`agent:session:manage`、`customer:create`、`finance:create`、`inbound:create`、`inbound:view`、`knowledge:view`、`order:create`、`order:update`、`processing:update`、`processing:view`
--   逐角色逐码读数（可复算）：
--   `python3 -c "import sys;sys.path.insert(0,'rbac');import derive,json;print(derive.convergence_diff(derive.load_manifest()))"`
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService.initializeDefaultRolesAndPermissions` 全量 seed；存量租户的
--   **目录**由 `PermissionService.ensureFullPermissionCatalog` 懒补种，而 **`role_permissions`
--   没有任何 Java 路径会给既有岗位补码** ⇒ 上面这批 `(岗位, 码)` 在老租户上**永久缺失**
--   （`V43`/`V111`/`V124`/`V125` 四条迁移引入新码时都**没给** `admin` 授码，实测 `grep -c "r.code = 'admin'"`
--   对这四个文件 = 0 —— 这就是本迁移要治的存量差距，见设计 §3.1）。
--   **运行时零影响**（`RoleService.getUserPermissions` 对 `admin` 首行短路返回 `["*"]`），
--   受影响的是**岗位权限页的回填**与**员工弹窗按岗位预填**（UI 可见、授权面可见）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 每条语句都是 `INSERT … SELECT … WHERE NOT EXISTS` 形态的**授权补齐**，
--     冲突由唯一索引 `uq_role_permissions (role_id, permission_id)` 兜住：`ON CONFLICT … DO NOTHING`；
--   · 本文件**只 INSERT**，不改/不删任何既有行 ⇒ 第二遍的每条语句都是 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：每个**已有权限目录**的租户里，上表每一对 `(岗位, 码)` 都必须有
--   `role_permissions` 行；缺任何一对 ⇒ `RAISE EXCEPTION` 并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条 autocommit**
--   ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。两条执行路径必须同语义。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- V136__rollback.sql（本单只登记，不落码）：只删本迁移**补出来**的那些行
--   DELETE FROM role_permissions rp USING roles r, permissions p
--    WHERE rp.role_id = r.id AND rp.permission_id = p.id
--      AND (r.code, p.code) IN (VALUES
--        ('admin', 'after_sales:view'),
--        ('admin', 'agent:session:manage'),
--        ('admin', 'customer:create'),
--        ('admin', 'finance:create'),
--        ('admin', 'inbound:create'),
--        ('admin', 'inbound:view'),
--        ('admin', 'knowledge:view'),
--        ('admin', 'order:create'),
--        ('admin', 'order:update'),
--        ('admin', 'processing:update'),
--        ('admin', 'processing:view'));
--   ```
--   **回滚是收窄**：会把管理员岗位在这批码上的勾选一并删掉（岗位权限页的勾选与岗位默认权限同表）⇒
--   属**有意**（宁可回到「缺码」，也不要留下指向不存在权限的悬空授权）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql`（新建库路径**不跑迁移链**）
--   不含任何 `role_permissions` 种子行（`INSERT INTO role_permissions` 在该文件 **0 命中**）⇒ 本迁移无需同步它。

BEGIN;

-- ── admin：链上缺 11 个码 ──
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'admin' AND r.deleted = 0
  AND p.code IN ('after_sales:view', 'agent:session:manage', 'customer:create', 'finance:create', 'inbound:create', 'inbound:view', 'knowledge:view', 'order:create', 'order:update', 'processing:update', 'processing:view')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「差集没补齐」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    scoped_tenants INTEGER;
    missing_links  INTEGER;
BEGIN
    -- 射程 = 「已有权限目录」的租户（不以 tenants 为全集：尚未初始化的租户不在本迁移射程内，同 V124 口径）
    SELECT COUNT(*) INTO scoped_tenants
      FROM tenants t WHERE EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id);
    IF scoped_tenants = 0 THEN
        RAISE NOTICE 'V136：没有任何租户持有权限目录 ⇒ 本迁移为空操作（全新库）';
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        ('admin', 'after_sales:view'),
        ('admin', 'agent:session:manage'),
        ('admin', 'customer:create'),
        ('admin', 'finance:create'),
        ('admin', 'inbound:create'),
        ('admin', 'inbound:view'),
        ('admin', 'knowledge:view'),
        ('admin', 'order:create'),
        ('admin', 'order:update'),
        ('admin', 'processing:update'),
        ('admin', 'processing:view')
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V136 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V136 终态对账通过：存量内置岗位的清单差集已补齐（射程内租户 % 个）', scoped_tenants;
END $$;

COMMIT;
