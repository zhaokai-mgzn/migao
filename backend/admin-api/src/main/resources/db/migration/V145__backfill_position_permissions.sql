-- 岗位默认权限的**存量回填**：四个岗位各补一个「本职码」（issue #5979 / #5988）
--
-- ## 一句话
--   人类 2026-10-02 逐条裁定「应允许」：客服 +`order:refund`、销售 +`order:create`、
--   财务 +`customer:view`、知识编辑 +`knowledge:view` + `knowledge:manage`。
--   本迁移把这批码**幂等**地补给**已有租户**的内置岗位（新租户由 `RegistrationService` 的种子路径落库）。
--
-- ## 🔴 回填口径（PR body 必须复述的一条）
--   本迁移**无租户过滤** —— `roles` 表按租户各存一行岗位，语句以 `r.code = '<码>'` 为谓词、
--   `JOIN permissions p ON p.tenant_id = r.tenant_id` 取该租户自己的码行 ⇒
--   **对数据库中每一个存在该岗位的租户生效（存量租户一起回填）**。
--   `roles` / `permissions` 均带 `deleted = 0` 过滤 ⇒ 不复活软删行。
--
-- ## 为什么必须回填（不能只改种子）
--   岗位默认权限有**四处真值源**（回退 switch / 清单 `roles.seed` / 注册种子 / 存量迁移）：
--   只改前三处 ⇒ **存量租户**的内置岗位拿不到新码 = 「新租户有、老租户没有」的经典漂移。
--   本迁移是第 ④ 处的物化；四处**逐值一致**由
--   `tests/unit_ci_workflows/test_position_default_permissions.py` 逐码穷举守着。
--
-- ## 幂等（`MigrationRunner` 硬要求）
--   `ON CONFLICT (role_id, permission_id) DO NOTHING`（与 V124 / V125 / V137 同款）——
--   只 INSERT，不改 / 不删既有行 ⇒ **第二遍 0 行**。
--   🔴 「不清空后重加」是**有意**的：岗位权限页允许管理员按租户手工增减（`Deleted` 软删），
--   删了再加会把租户的手工配置**静默复位**（设计 §2.9：快照是最终权限，回填 = 静默改授权）。
--
-- ## 停止条件（fail-closed）
--   终态对账：每一对 `(岗位, 码)` 在本迁移跑完后都必须有 `role_permissions` 行，否则
--   `RAISE EXCEPTION` 回滚（不硬推「部分回填」的库）。
--
-- ## 边界（照实登记）
--   ① **不**回填 `users.permissions` 快照（设计 §2.9：员工级快照按设计与岗位脱钩，
--      回填 = 静默改授权）⇒ 持快照的存量员工**不受本迁移影响**，需租户在员工页手工调整；
--   ② **不**改 `roles` 行（四个岗位在 V29 / V137 已建行，本迁移只补授权）⇒
--      没有 `roles` 行的租户**不**被本迁移波及（缺岗位行是另一件事，不在此处静默补）；
--   ③ 权限目录里缺该码的租户（JOIN 空集）⇒ 该对**不会**被授，终态对账会**报红回滚**
--      （不静默放过 —— 「码在目录里不存在」需要人来判断是目录漏补还是本迁移写错）。

BEGIN;

-- ── 客服（customer_service）：补本职写码 `order:refund`（处理售后工单）──
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'customer_service' AND r.deleted = 0
  AND p.code IN ('order:refund')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ── 销售（sales）：补本职写码 `order:create`（下单）──
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'sales' AND r.deleted = 0
  AND p.code IN ('order:create')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ── 财务（finance）：补读码 `customer:view`（对账要读客户列表）──
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'finance' AND r.deleted = 0
  AND p.code IN ('customer:view')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ── 知识编辑（knowledge_editor）：补读 + 写码（issue #5979 的原始形态 = 一个 knowledge 码都没有）──
--   读码决定「知识库」菜单节点可见性（节点码 = `knowledge:view`，三处菜单源一致）；
--   写码把守创建 / 编辑 / 删除 / 发布 / 归档（`KnowledgeCardController` 等）。
--   两个一起给，否则该岗位要么看不见菜单、要么看得见却一个动作都做不了。
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'knowledge_editor' AND r.deleted = 0
  AND p.code IN ('knowledge:view', 'knowledge:manage')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（缺授权行 ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_links INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id AND p.deleted = 0
      JOIN (VALUES
        ('customer_service', 'order:refund'),
        ('sales', 'order:create'),
        ('finance', 'customer:view'),
        ('knowledge_editor', 'knowledge:view'),
        ('knowledge_editor', 'knowledge:manage')
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V145 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V145 终态对账通过：四个岗位的本职码已回填（存量租户）';
END $$;

COMMIT;
