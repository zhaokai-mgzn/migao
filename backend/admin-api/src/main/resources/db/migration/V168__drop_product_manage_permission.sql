-- issue #7282：删除死码 `product:manage`（用户 2026-10-18 裁定「可以删」）
--
-- ## 为什么删
--   它是商品域的**旧粗码**：issue #5236 删掉「第四处菜单源」后，没有任何端点 / Agent 工具 /
--   菜单节点 / 页面判断 / 种子岗位消费它 ⇒ 岗位权限页里勾了**不生效**（全目录普查 33 码里的最后一个
--   这类死码；同批的另一条 `agent:chat` 已核实是**活的手写门**（`AdminGate.MIBAO_CHAT_GRANT_CODE`
--   → `/api/auth/me` 的 `capabilities.mibaoChat`），故**不删**）。
--   判据 = `tests/unit_ci_workflows/test_rbac_derived_pages.py`
--   `test_every_grantable_code_has_a_server_side_enforcement_point`（归零后该台账为空）。
--
-- ## 删什么（三处，顺序有讲究）
--   ① `role_permissions`：指向该码的岗位授权行（物理删 —— 留着就是指向不存在权限的悬空授权）；
--   ② `users.permissions` **快照**（text 存 JSON 数组）：把该码从快照里摘掉。
--      🔴 `RoleService.getUserPermissions` 对**有快照**的账号**提前返回快照** ⇒ 不清快照等于
--      这个码永久留在授权面里（与 V138 给快照**加**码是同一处口径的反向动作）；
--   ③ `permissions` 目录行本身。
--
-- ## 幂等（`MigrationRunner` 要求所有迁移可重复执行）
--   三处都以「该码还在 / 该快照里还有它」为条件 ⇒ 第二遍全部 0 行，结果与第一遍相同。
--
-- ## 显式事务（V97 / V124 的既有口径）
--   `MigrationRunner` 走 `jdbc.execute(整份文件)`（PG 隐式包一个事务），而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 BEGIN/COMMIT 时中间步骤已提交、DO 块才抛 ⇒ 留下**半完成态**。
--
-- ## 回滚（**登记，不落码**）
--   本迁移**有损**：删掉的岗位勾选与快照成员无法区分「本迁移删的」与「本来就该没有的」。
--   回滚 = 让 `PermissionService.ensureFullPermissionCatalog` 重新补种目录行，再由管理员按需勾选。
--   属**有意** —— 权限码消失后残留的 role_permissions 是悬空授权，比丢勾选更危险（同 V124 口径）。
--
-- ## bootstrap 终态同步
--   `docs/sql/schema.sql` / `db/init/schema.sql` **不含任何 permissions / role_permissions 种子行**
--   （权限种子恒由 Java seed + 迁移链产出）⇒ 本迁移无需同步建库脚本。
--
-- ## 终态对账（fail-closed）
--   三处残留数必须为 0，否则 `RAISE EXCEPTION` 回滚整个迁移（不硬推）。

BEGIN;

-- ① 岗位授权行（含已逻辑删除的历史行 —— 物理删，避免悬空引用）
DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'product:manage');

-- ② 员工权限快照：从 JSON 数组里摘掉该码（空数组回落 '[]'）
UPDATE users
SET permissions = COALESCE((
        SELECT jsonb_agg(elem)::text
        FROM jsonb_array_elements(users.permissions::jsonb) AS elem
        WHERE elem #>> '{}' <> 'product:manage'
    ), '[]')
WHERE users.permissions IS NOT NULL
  AND users.permissions LIKE '%"product:manage"%';

-- ③ 目录行
DELETE FROM permissions WHERE code = 'product:manage';

-- 终态对账
DO $$
DECLARE
    n_perms INTEGER;
    n_links INTEGER;
    n_users INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_perms FROM permissions WHERE code = 'product:manage';
    SELECT COUNT(*) INTO n_links FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'product:manage');
    SELECT COUNT(*) INTO n_users FROM users WHERE permissions LIKE '%"product:manage"%';
    IF n_perms <> 0 OR n_links <> 0 OR n_users <> 0 THEN
        RAISE EXCEPTION 'product:manage 删除后仍有残留：permissions=% / role_permissions=% / users 快照=%',
            n_perms, n_links, n_users;
    END IF;
END $$;

COMMIT;
