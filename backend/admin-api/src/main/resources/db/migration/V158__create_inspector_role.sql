-- 新岗位 `inspector`（质检员）的**正式定义**（issue #5652：质检记录 / 返工报废）
--
-- ## 一句话
--   成品帘质检的**录入者 = 独立质检员**（用户 2026-10 裁定「B 独立质检员」）⇒ 本迁移把
--   `inspector` 正式定义为一个**新租户岗位**：**建 `roles` 行**（幂等）＋**按清单授权**（幂等）＋终态对账。
--   本迁移**不改**任何既有岗位的授权（新岗位只持有 `production:inspect` / `production:view` 两个码）。
--
-- ## 🔴 为什么是这两个码，且**必须新增一个目录码**
--   · `production:view` —— 看得到「生产看板 / 工序」等生产面（读码，复用既有码）；
--   · `production:inspect` —— 质检录入是**写**动作（`QualityCheckController` 的两个端点带
--     `@RequirePermission("production:inspect")`），**新码**：复用既有的 `production:execute`
--     会把质检录入权顺带发给持该码的四个岗位（客服 / 运营 / 销售 / 财务），
--     而用户裁定的录入者是「**独立**质检员」⇒ 复用即**放宽**（实测：权限判据当场判红）。
--     新码只授 `inspector`（+ 运行时恒 `["*"]` 的 `admin`）。
--     代价（照实登记）：目录码要同步三处声明面（`RegistrationService` / `PermissionService` /
--     `rbac/manifest.json` 的 `codes.*`）—— 三处逐值相等由 `rbac` 判据守着。
--   ⇒ 逐对真值：('inspector', 'production:inspect'), ('inspector', 'production:view')
--   （值逐字取自 `rbac/manifest.json` 的 `roles.seed.inspector`，与 `roles.fallback.inspector` **逐值相等**。）
--
-- ## 🔴 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService.initializeDefaultRolesAndPermissions`（同批加第 8 个岗位种子）；
--   而**存量租户没有任何 Java 路径**会给他们建这个岗位行、也不会授权（`PermissionService`
--   的懒补种只管**权限目录**、不管 `roles` / `role_permissions`）⇒ 不补这条迁移，
--   「新租户有质检员岗位、老租户没有」——正是设计真值源 §3.1 登记的那条**路径依赖**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `roles`：`WHERE NOT EXISTS (同租户同 code 有效行)`（与 V29/V32/V137 的既有写法同款）；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`
--     （唯一索引 `uq_role_permissions` 兜住）；
--   · **只 INSERT**，不改/不删任何既有行 ⇒ 第二遍每条语句 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：每个租户都必须有 `inspector` 的 `roles` 行，且上表每一对 `(岗位, 码)`
--   都必须有 `role_permissions` 行；缺任何一项 ⇒ `RAISE EXCEPTION` 并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 / V136 / V137 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` 默认逐条
--   autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 本文件是**生成物**（不是手写真值）
--   由 `rbac/generate_migration.py` 从 `rbac/manifest.json` 渲染（`python3 rbac/generate_migration.py`）
--   ⇒ 手改本文件、或改了清单没重渲染，都会被新鲜度判据判红（`test_rbac_migration_convergence.py`）。
--   ⚠️ 与 `V136` / `V137` 的**有意差异**：那两份是**已发布**迁移 ⇒ 渲染输入钉在发布时刻的清单快照上
--   （`FROZEN_SNAPSHOTS`，改活清单**不会**动它们）；本迁移尚未发布 ⇒ 输入 = **活清单**。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- V158__rollback.sql（本单只登记，不落码）：只删本迁移**建出来**的行
--   DELETE FROM role_permissions rp USING roles r, permissions p
--    WHERE rp.role_id = r.id AND rp.permission_id = p.id
--      AND (r.code, p.code) IN (VALUES
--        ('inspector', 'production:inspect'),
--        ('inspector', 'production:view'));
--   DELETE FROM roles WHERE code = 'inspector';
--   ```
--   **回滚是收窄**：会把租户在岗位权限页给该岗位的手工勾选一并删掉 ⇒ 属**有意**（宁可回到
--   「没有这个岗位」，也不要留下指向不存在岗位的悬空授权）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql`（新建库路径**不跑迁移链**）
--   不含任何 `role_permissions` / `permissions` 种子行（两份 `INSERT INTO …` 在该文件 **0 命中**）
--   ⇒ 本迁移**无需**同步它。

BEGIN;

-- ── inspector（质检员）：2 个码 ──
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '质检员', 'inspector', '成品帘质检录入（issue #5652：独立质检员，持 production:view / production:inspect）', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'inspector' AND r.deleted = 0);

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'inspector' AND r.deleted = 0
  AND p.code IN ('production:inspect', 'production:view')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（缺角色行 / 缺授权行 ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_roles INTEGER;
    missing_links INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_roles
      FROM tenants t
      CROSS JOIN (VALUES ('inspector')) AS want(role_code)
     WHERE NOT EXISTS (
            SELECT 1 FROM roles r
             WHERE r.tenant_id = t.id AND r.code = want.role_code AND r.deleted = 0
       );
    IF missing_roles > 0 THEN
        RAISE EXCEPTION 'V158 终态对账失败：% 个岗位码没有 roles 行 —— 回滚本迁移', missing_roles;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        ('inspector', 'production:inspect'),
        ('inspector', 'production:view')
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V158 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V158 终态对账通过：1 个岗位已正式定义（roles 行 + 授权）';
END $$;

COMMIT;
