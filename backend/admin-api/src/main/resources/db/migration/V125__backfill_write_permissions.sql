-- 5 个**写**码的存量租户权限补齐（issue #5246 追加单）
--
-- ## 一句话
--   给**已存在**的租户补两件事：
--   ① `permissions` 目录补 5 个写码 —— `order:update`、`order:create`、`customer:create`、
--      `finance:create`、`agent:session:manage`；
--   ② 按岗位授权（授权矩阵见下），与 `RegistrationService.initializeDefaultRolesAndPermissions`
--      的**新租户种子同源同码**，一个不多、一个不少。
--
-- ## 🔴 为什么是**新文件**，而不是往 V124 里加（本仓铁律，逐条给判据）
--   追加单最初按「扩展 V124」执行，但 **V124 在本批到达之前已被提交发布**
--   （commit `9c5d757ce`，`git cat-file -e HEAD:…/V124__backfill_read_permissions.sql` ⇒ 存在）。
--   已发布迁移**只增不改**，三条独立理由：
--   ① **功能会静默失效**：`MigrationRunner` 的台账 `schema_migrations` 按**文件名**判
--      （`if (applied.contains(filename)) continue;`）⇒ 往已应用的 V124 里加语句，**整份被跳过**
--      ⇒ 凡是已经跑过 V124 的环境**永远拿不到**这 5 个写码，而部署显示 success。
--   ② **静态守卫会因此转绿**：`tests/unit_ci_workflows/test_migration_immutability.py` 的账本
--      只冻结「已登记」文件，`--write-ledger` 对**已登记的改动**是 fail-closed
--      （实测：`❌ 拒绝重生成账本` + exit 1 + 点名文件）。
--   ③ **合并会被 required 检查拦下**：`.github/danger_scan.py` 把「改迁移」判为 danger，
--      放行需要**仓库 owner** 的评论 `/danger-ack rewrite-migration V124`
--      （`MIGRATION_ACK_MARKER`，只有 owner 的评论算数）—— 那是**人工**步骤，agent 范围内不可达。
--   ⇒ 增量写成新文件 `V125`；**V124 保持逐字节不变**（本轮未改它，可复算：其 sha256 仍是
--      `sha256:05204e9b…5120`，与账本条目一致）。
--
-- ## 与 V124 的分工（同源、互补、都幂等）
--   V124 = 2 个**读**码（`after_sales:view` / `knowledge:view`）+ 其岗位授权；
--   本文件 = 5 个**写**码 + 其岗位授权。两者互不依赖，**顺序无关**（各自 `WHERE NOT EXISTS` /
--   `ON CONFLICT DO NOTHING`），且可各自重复执行。权限目录的**唯一真值源**仍是
--   `RegistrationService.defaultPermissions`（两处目录的码列必须逐值相等，守卫见
--   `tests/unit_ci_workflows/test_agent_permission_parity.py` 的判据 9）。
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService` 全量 seed；存量租户的**目录**只在
--   `PermissionService.ensureFullPermissionCatalog` 被懒调用时补种，而 **role_permissions 没有任何
--   Java 路径会给既有岗位补** ⇒ 只改 Java 的话，端点已改用写码 ⇒ 老租户的运营岗位**改不了单、
--   建不了单、记不了账**，客服**转接不了会话**（全是「新租户能、老租户不能」的经典半成品形态）。
--
-- ## 授权矩阵（**有意收窄**：写码只给职责本来就包含它的岗位）
--   | 码 | 授予岗位 | 理由 |
--   |---|---|---|
--   | `order:update` | operator | 改单（状态/物流/备注/跟进/取消/删除）是运营本职 |
--   | `order:create` | operator | 建单是运营本职 |
--   | `customer:create` | operator | 维护客户档案与标签 |
--   | `finance:create` | operator, finance | 登记收支流水（财务本职；运营兼办线下收款） |
--   | `agent:session:manage` | operator, customer_service | 转接/结束会话/发言 = 客服本职（此前靠**读**码就能做） |
--   `sales` **一个写码都不给**（销售动线是看）；`admin` 恒为 `["*"]`（无需补）。
--   ⚠️ 与 `RoleService.getPermissionCodesForRole` 的硬编码回退的一致性：该 switch **只有
--   operator** 一个命中岗位（finance / customer_service 落 `default ⇒ 空表`，本单未新增 case，
--   如实登记）⇒ operator 的回退列表已同步这 5 个码，另两个岗位的写码只在种子矩阵与本文件落地。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`
--     （与 V43 / V111 / V124 的既有写法逐字同款）；
--   · 本文件**只 INSERT，不改既有行** ⇒ 第二遍的所有 INSERT 均为 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（见文末 `DO` 块，由一张 `VALUES` 矩阵驱动，与上方 ①/② 同源）：
--   ① 5 个码在**每个已有权限目录的租户**里都存在；
--   ② 7 条 `码 × 岗位` 的 `role_permissions` 链接数等于应有条数；
--   ③ 幂等自证：每个码的目录行数 = 有权限目录的租户数。任一不满足即 `RAISE EXCEPTION`
--   并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--   两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V126__rollback_write_permissions.sql（本单只登记，不落码）
-- DELETE FROM role_permissions WHERE permission_id IN
--     (SELECT id FROM permissions WHERE code IN
--        ('order:update','order:create','customer:create','finance:create','agent:session:manage'));
-- DELETE FROM permissions WHERE code IN
--        ('order:update','order:create','customer:create','finance:create','agent:session:manage');
-- ```
-- **回滚是有损的**：若已有人在「岗位权限」页手工勾选过这 5 个码，回滚会把那些勾选一并删除
-- （岗位权限页的勾选与岗位默认权限同表）。属**有意** —— 权限码消失后残留的 role_permissions
-- 会指向不存在的权限（悬空授权），比丢勾选更危险。
--
-- ## bootstrap 终态同步（如实登记）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）**不含任何 permissions / role_permissions 种子行**
--   （该文件只建表结构，权限种子恒由 Java seed + 迁移链产出）⇒ 本迁移**无需**同步 schema.sql。
--   判据（可复算）：`grep -c "INSERT INTO permissions" docs/sql/schema.sql` ⇒ 0。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：5 个**写**码（同租户同码已存在即跳过）
--    名称/资源类型/动作/描述与 RegistrationService.defaultPermissions **逐字一致**
--    （那条守卫按码列比对两处目录 ⇒ 这里写错一个字，老租户的角色管理页就会显示另一个名字）。
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '订单操作', 'order:update', 'order', 'update', '改订单状态/物流/备注/跟进/取消', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'order:update');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '新增订单', 'order:create', 'order', 'create', '创建订单', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'order:create');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '客户维护', 'customer:create', 'customer', 'create', '编辑/删除客户与标签', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'customer:create');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '财务操作', 'finance:create', 'finance', 'create', '登记收支流水', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'finance:create');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '会话操作', 'agent:session:manage', 'agent', 'manage', '转接/结束会话/发消息', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'agent:session:manage');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权（与 RegistrationService 的岗位默认列表**逐项一致**；与上方「授权矩阵」表同源）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'operator' AND r.deleted = 0 AND p.code = 'order:update'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'operator' AND r.deleted = 0 AND p.code = 'order:create'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'operator' AND r.deleted = 0 AND p.code = 'customer:create'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('operator', 'finance') AND r.deleted = 0 AND p.code = 'finance:create'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('operator', 'customer_service') AND r.deleted = 0 AND p.code = 'agent:session:manage'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
--    判据由一张 `VALUES` 矩阵驱动（与上方 ①/② 同源）：加码/加岗位时只改这一处，
--    不会出现「INSERT 加了、对账忘了」的静默漏检。
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    r           RECORD;
    missing     INTEGER;
    row_count   INTEGER;
    link_count  INTEGER;
    expected    INTEGER;
BEGIN
    -- ① 5 个码必须在**每个已有权限目录的租户**里各存在一行
    --    （不以 tenants 为全集：没有任何 permissions 行的租户 = 尚未初始化，不在本迁移射程内）
    SELECT COUNT(*) INTO missing
      FROM tenants t
      CROSS JOIN (VALUES ('order:update'), ('order:create'), ('customer:create'),
                         ('finance:create'), ('agent:session:manage')) AS v(code)
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = v.code);
    IF missing > 0 THEN
        RAISE EXCEPTION 'V125 终态对账失败：% 个「租户 × 码」组合缺 permissions 行 —— 回滚本迁移', missing;
    END IF;

    -- ② 授权矩阵逐条对账：每个 (码 × 岗位) 的 role_permissions 链接数 = 应有条数
    FOR r IN
        SELECT * FROM (VALUES
            ('order:update',         'operator'),
            ('order:create',         'operator'),
            ('customer:create',      'operator'),
            ('finance:create',       'operator'),
            ('finance:create',       'finance'),
            ('agent:session:manage', 'operator'),
            ('agent:session:manage', 'customer_service')
        ) AS x(code, role_code)
    LOOP
        SELECT COUNT(*) INTO expected
          FROM roles rl
          JOIN permissions p ON p.tenant_id = rl.tenant_id
         WHERE rl.code = r.role_code AND rl.deleted = 0 AND p.code = r.code;
        SELECT COUNT(*) INTO link_count
          FROM role_permissions rp
          JOIN roles rl ON rl.id = rp.role_id
          JOIN permissions p ON p.id = rp.permission_id
         WHERE rl.code = r.role_code AND p.code = r.code AND rp.deleted = 0;
        IF link_count <> expected THEN
            RAISE EXCEPTION 'V125 终态对账失败：% × % 的 role_permissions 链接数 % ≠ 应有 % —— 回滚本迁移',
                r.code, r.role_code, link_count, expected;
        END IF;
    END LOOP;

    -- ③ 幂等自证：每个码的目录行数 = 有权限目录的租户数（重复执行不得产生副本行）
    FOR r IN
        SELECT * FROM (VALUES ('order:update'), ('order:create'), ('customer:create'),
                              ('finance:create'), ('agent:session:manage')) AS v(code)
    LOOP
        SELECT COUNT(*) INTO row_count FROM permissions WHERE code = r.code;
        IF row_count <> (SELECT COUNT(DISTINCT tenant_id) FROM permissions) THEN
            RAISE EXCEPTION 'V125 终态对账失败：% 的目录行数 % ≠ 有权限目录的租户数 % —— 可能产生了重复行',
                r.code, row_count, (SELECT COUNT(DISTINCT tenant_id) FROM permissions);
        END IF;
    END LOOP;

    RAISE NOTICE 'V125 终态对账通过：5 个写码的目录 + 授权矩阵（7 条 码×岗位）齐备';
END $$;

COMMIT;