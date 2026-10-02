-- 两个历史岗位码的**正式定义**（issue #5699 的 **P6**，出口 (i)；设计真值源 §2.6 / §4 的 P6 行）
--
-- ## 一句话
--   `product_manager`（商品管理员）/ `knowledge_editor`（知识编辑）此前**不是岗位**：
--   不在种子里、迁移链一条谓词都不提（⇒ **没有 `roles` 行**）、岗位权限页**无法编辑**，
--   只靠 `RoleService.getPermissionCodesForRole` 的 `switch` 一行 `case` 拿 8 / 4 个码。
--   本迁移把它们**正式定义**为岗位：**建 `roles` 行**（幂等）＋**按清单授权**（幂等）＋终态对账。
--
-- ## 🔴 为什么账号的**有效权限集合逐值不变**（本迁移的兼容性判据）
--   两个角色码的默认码集**一字未改**（值取自清单 `roles.seed`，与 `roles.fallback` **逐值相等**，
--   由 `rbac` 判据与 `test_agent_permission_parity.py` 判据 14 同时守着）⇒
--   · 走**回退路径**（无 `role_permissions` 记录）的账号：仍然是同一批码；
--   · 走 **`role_permissions` 路径**（本迁移之后）：拿到的是**同一批码**。
--   ⇒ 差别只在**可管理性**（岗位权限页首次能编辑它们）与**可分配性**（员工弹窗首次能选它们）——
--   两者都是产品面变化，归 P6 的人类裁定（2026-09-27 已裁定出口 (i)）。
--
-- ## 幂等（`MigrationRunner` 硬要求）
--   · `roles`：`WHERE NOT EXISTS (同租户同 code 有效行)`（与 V29/V32 的既有写法同款）；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`；
--   · 只 INSERT，不改/不删既有行 ⇒ 第二遍 0 行。
--
-- ## 停止条件（fail-closed）
--   终态对账：每个**已有权限目录**的租户里，两个岗位码都必须有 `roles` 行，且清单里的每一对
--   `(岗位, 码)` 都必须有 `role_permissions` 行；否则 `RAISE EXCEPTION`。
--
-- ## 边界（照实登记）
--   ① 本迁移**不**回填 `users.permissions` 快照（设计 §2.9：快照是最终权限，回填 = 静默改授权）——
--      但两角色的码集未变 ⇒ 快照面**本来就不需要**回填；
--   ② 米宝 `allowed_roles`（`backend/ai-agent-service/app/agents/agents/mibao.py`）与 bmini 角色名映射
--      （`frontend/bmini-app/src/pages/profile/index/index.tsx`）引用的是**角色名**：正式定义后仍逐字成立
--      （读数见 PR body），本迁移**不**动它们。

BEGIN;

-- ── knowledge_editor（知识编辑）：4 个码 ──
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '知识编辑', 'knowledge_editor', '知识库编辑（POC 期历史岗位，issue #5699 的 P6 正式定义）', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'knowledge_editor' AND r.deleted = 0);

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'knowledge_editor' AND r.deleted = 0
  AND p.code IN ('dashboard:view', 'knowledge:manage', 'knowledge:view', 'product:list')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ── product_manager（商品管理员）：8 个码 ──
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '商品管理员', 'product_manager', '商品与加工项管理（POC 期历史岗位，issue #5699 的 P6 正式定义）', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'product_manager' AND r.deleted = 0);

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'product_manager' AND r.deleted = 0
  AND p.code IN ('dashboard:view', 'processing:manage', 'processing:view', 'product:category', 'product:category:view', 'product:create', 'product:list', 'production:view')
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
      CROSS JOIN (VALUES ('knowledge_editor'), ('product_manager')) AS want(role_code)
     WHERE NOT EXISTS (
            SELECT 1 FROM roles r
             WHERE r.tenant_id = t.id AND r.code = want.role_code AND r.deleted = 0
       );
    IF missing_roles > 0 THEN
        RAISE EXCEPTION 'V137 终态对账失败：% 个历史岗位码没有 roles 行 —— 回滚本迁移', missing_roles;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        ('knowledge_editor', 'dashboard:view'),
        ('knowledge_editor', 'knowledge:manage'),
        ('knowledge_editor', 'knowledge:view'),
        ('knowledge_editor', 'product:list'),
        ('product_manager', 'dashboard:view'),
        ('product_manager', 'processing:manage'),
        ('product_manager', 'processing:view'),
        ('product_manager', 'product:category'),
        ('product_manager', 'product:category:view'),
        ('product_manager', 'product:create'),
        ('product_manager', 'product:list'),
        ('product_manager', 'production:view')
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V137 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V137 终态对账通过：两个历史岗位码已正式定义（roles 行 + 授权）';
END $$;

COMMIT;
