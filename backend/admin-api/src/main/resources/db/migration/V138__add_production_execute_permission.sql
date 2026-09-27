-- 新写码 `production:execute`（issue #5699 的 **I4**；设计真值源 §3.4 问题 2 / §4 的 P4 行）
--
-- ## 一句话
--   四个**真写**端点此前**只由读码 `order:list` 把守**（`ProductionController` 的类级注解）：
--   · `POST /api/admin/production/orders/{}/instantiate`
--   · `POST /api/admin/production/orders/{}/operations/{}/report`
--   · `POST /api/admin/production/orders/{}/print`
--   · `POST /api/admin/production/orders/{}/ship`
--   ⇒ 现在改挂**写码** `production:execute`（注解改动在 `ProductionController`，本迁移只补**存量数据面**）：
--   ① 目录里加 `production:execute`；② 授予**今日持 `order:list` 的四个岗位**（`admin` 恒 `*`，无需补行）；
--   ③ **快照等价回填**（见下节）。
--
-- ## 🔴 为什么 (2) 是「自洽」而不是「放宽」
--   改前这四个端点的**生效码**就是四个人人可读的 `order:list`（它授给 `admin` · 客服 · 运营 · 销售 · 财务）
--   ⇒ 这四岗**今天就能**建加工单 / 报工 / 打任务卡 / 发货。改挂写码后若不补授权，它们会**当场 403**
--   （现场停线）⇒ 补授权 = 让**有效权限集合逐值不变**；新码**只把守这 4 个端点**（别处一律不挂）
--   ⇒ 不存在「多开了哪扇门」。逐端点的「改前能过 / 改后能过」读数见 PR body 与
--   `tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py` 的 I4 台账。
--
-- ## 🔴 快照等价回填（设计 §2.9 的**具名窄例外**，逐字条件见下）
--   `RoleService.getUserPermissions` 对**有 `users.permissions` 快照**的账号**提前返回快照**
--   ⇒ 只补 `role_permissions` **不够**：快照里没有新码的账号照样 403。回填的**谓词**必须**逐字**是：
--     ① 快照是**严格 JSON 字符串数组**（`AdminUserController` 的 `writeValueAsString(list)` 形态）；
--     ② 含**旧守卫码** `"order:list"`（该账号今天本来就过得了这 4 个端点）；
--     ③ 不含新码（幂等）。
--   **不含旧码的账号一个字节都不动**（它今天也过不去 ⇒ 不补 = 不放宽）。
--   ⇒ 有效权限集合**逐值不变**：这不是「给更多人开门」，是「守卫码改名时把有效集合钉住」。
--   ⚠️ 这条是 §2.9「不回填快照」的**窄例外**（理由 / 谓词 / 边界 / 判据见设计 §2.9 的同批补记），
--   **不是**放宽该原则：例外只覆盖「旧码在场」的快照，且迁移末尾有 fail-closed 断言**证明**没有越界。
--
-- ## 只读的事前 / 事后核对 SQL（接上真库后人工复核用；本迁移**不**执行它们）
--   ```sql
--   -- 事前：受影响的账号数（快照含旧码、不含新码）—— 本机无真库 ⇒ 报告里必须写「未知 + 本 SQL」
--   SELECT COUNT(*) FROM users
--    WHERE permissions LIKE '%"order:list"%' AND permissions NOT LIKE '%"production:execute"%';
--   -- 事前：按岗位分布（受影响面到底是哪些岗位）
--   SELECT role, COUNT(*) FROM users
--    WHERE permissions LIKE '%"order:list"%' AND permissions NOT LIKE '%"production:execute"%' GROUP BY role ORDER BY 2 DESC;
--   -- 事后：应当逐值等于事前（每行 +1 个码，行数不变）；且**没有任何**行是「有新码、无旧码」
--   SELECT COUNT(*) FROM users WHERE permissions LIKE '%"production:execute"%';
--   SELECT COUNT(*) FROM users
--    WHERE permissions LIKE '%"production:execute"%' AND permissions NOT LIKE '%"order:list"%';   -- 必须 = 0
--   ```
--
-- ## 幂等（`MigrationRunner` 硬要求）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`；
--   · 快照 `UPDATE`：带**「不含新码」谓词** ⇒ 第二遍匹配 0 行；
--   · 只 INSERT + 一条定值 `UPDATE`，不删任何行 ⇒ 第二遍结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：① 每个已有权限目录的租户都有 `production:execute` 行；
--   ② 四个岗位对它的 `role_permissions` 链接齐备；③ **没有**任何快照「有新码、无旧码」（越界即回滚）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql` 不含 `permissions` 种子行
--   （`INSERT INTO permissions` 在该文件 **0 命中**）⇒ 本迁移无需同步它；新库的目录由 Java seed 产出。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：一个新**写**码（同租户同码已存在即跳过）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '生产执行', 'production:execute', 'production', 'execute', '建加工单/报工/打任务卡/发货', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'production:execute');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：今日持 `order:list` 的四个岗位（有效权限集合逐值不变）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('admin', 'customer_service', 'operator', 'sales', 'finance') AND r.deleted = 0
  AND p.code IN ('production:execute')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 快照等价回填：**只**动「含旧码、不含新码」的严格 JSON 数组快照（逐字条件见文件头）
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE users
   SET permissions = (permissions::jsonb || '["production:execute"]'::jsonb)::text
 WHERE permissions ~ '^\[(\"[^\"]*\")(,\"[^\"]*\")*\]$'
   AND permissions LIKE '%"order:list"%'
   AND permissions NOT LIKE '%"production:execute"%';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（缺目录行 / 缺授权行 / **快照越界** ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_codes INTEGER;
    missing_links INTEGER;
    widened      INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_codes
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'production:execute');
    IF missing_codes > 0 THEN
        RAISE EXCEPTION 'V138 终态对账失败：% 个租户缺 production:execute 目录行 —— 回滚本迁移', missing_codes;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id AND p.code = 'production:execute'
      JOIN (VALUES ('customer_service'), ('operator'), ('sales'), ('finance')) AS want(role_code)
        ON want.role_code = r.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V138 终态对账失败：% 个岗位没有 production:execute 授权行 —— 回滚本迁移', missing_links;
    END IF;

    SELECT COUNT(*) INTO widened
      FROM users
     WHERE permissions LIKE '%"production:execute"%' AND permissions NOT LIKE '%"order:list"%';
    IF widened > 0 THEN
        RAISE EXCEPTION 'V138 终态对账失败：% 个快照「有新码、无旧码」= 越界放宽 —— 回滚本迁移', widened;
    END IF;
    RAISE NOTICE 'V138 终态对账通过：写码目录 + 岗位授权 + 快照等价回填齐备';
END $$;

COMMIT;
