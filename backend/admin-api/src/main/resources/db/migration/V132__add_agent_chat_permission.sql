-- 米宝唤出授权码 `agent:chat` 的存量租户补齐 + 一条旧描述的更正（issue #5642，功能⑤）
--
-- ## 一句话
--   给**已存在**的租户补三件事：
--   ① `permissions` 目录补**一个**码 —— `agent:chat`（米宝唤出权，此前全仓 0 命中）；
--   ② 按岗位授权：**只授给 `admin` 角色**（有意收窄，见下），其余岗位**有意不回填**；
--   ③ 更正 `agent:session` 的**旧描述**（其「米宝对话」那截是 aspirational 的 ——
--      该码实测只管 `/api/admin/agent-sessions/*`，即「在线接待」，从不曾施加在对话入口上）。
--
-- ## 🔴 为什么是**新文件**，而不是往 V124/V125/V129 里加（本仓铁律，逐条给判据）
--   已发布迁移**只增不改**，三条独立理由（V125 头部原文）：
--   ① **功能会静默失效**：`MigrationRunner` 的台账 `schema_migrations` 按**文件名**判
--      （`if (applied.contains(filename)) continue;`）⇒ 往已应用的迁移里加语句，**整份被跳过**
--      ⇒ 凡是已经跑过的环境**永远拿不到** `agent:chat`，而部署显示 success。
--   ② **静态守卫会因此转绿**：`tests/unit_ci_workflows/test_migration_immutability.py` 的账本
--      只冻结「已登记」文件，`--write-ledger` 对**已登记的改动**是 fail-closed。
--   ③ **合并会被 required 检查拦下**：`.github/danger_scan.py` 把「改迁移」判为 danger，
--      放行需要仓库 owner 的评论（人工步骤，agent 范围内不可达）。
--   ⇒ 增量写成新文件 `V132`；V124 / V125 / V129 保持逐字节不变。
--
-- ## 授权矩阵（**有意收窄**，用户 2026-09-26 裁定⑧：只回填 `admin`）
--   | 码 | 授予岗位 | 理由 |
--   |---|---|---|
--   | `agent:chat` | **只 `admin`** | 改动前「人人可唤米宝」（无码在管）⇒ 按「迁移前后行为逐值相同」这把尺子，
--   五个内置岗位**都**合法可回填；但用户裁定⓪的产品意图就是**收窄**「人人可唤」
--   ⇒ 若把 5 个岗位全回填，改动上线当天**零行为变化**，等于没做。
--   🔴 **这是有意收窄，不是漏授**：除 `admin` 外所有员工的米宝入口从「可唤」变为「需授权」，
--   由企业管理员在「员工管理」中按需勾选（上线当天批量授权操作单见 PR body）。
--   ⚠️ `admin` 恒为 `["*"]`（`RoleService` 四处分支）⇒ 补 `role_permissions` 行只是让
--   「新老租户逐值一致」（与 V129 对 admin 的同款处理），**不是**它生效的必要条件。
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService` 全量 seed；存量租户的**目录**只在
--   `PermissionService.ensureFullPermissionCatalog` 被懒调用时补种，而 **role_permissions 没有任何
--   Java 路径会给既有岗位补**。描述列同理：`permissions.description` 是**落库列**
--   （`db/init/schema.sql` 的 `permissions` 表；`PermissionService` 只在**插入**时写它、
--   已存在则 `continue`）⇒ 只改 Java 的话，存量租户的目录里**仍是**旧描述
--   ⇒ 「两个都自称管米宝对话的码」这个评审疑点在老租户上依然存在。故 ③ 必须落一条 UPDATE。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`
--     （与 V43 / V111 / V124 / V125 / V129 的既有写法逐字同款）；
--   · ③ 的 `UPDATE` 带**旧值谓词** ⇒ 第二遍匹配 0 行；
--   · 本文件**只 INSERT + 一条定值 UPDATE**，不删任何行 ⇒ 第二遍结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（见文末 `DO` 块）：① 每个已有权限目录的租户都有 `agent:chat` 行；
--   ② `agent:chat` 的 `role_permissions` 链接**只**落在 `admin` 角色上（多一个岗位即断言失败）；
--   ③ 没有任何 `agent:session` 行还挂着旧描述。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   DELETE FROM role_permissions rp USING permissions p
--     WHERE p.id = rp.permission_id AND p.code = 'agent:chat';
--   DELETE FROM permissions WHERE code = 'agent:chat';
--   UPDATE permissions SET description = '米宝对话/会话监控/在线接待' WHERE code = 'agent:session';
--   ⚠️ 回滚会把「米宝唤出权」整体收回（含管理员）⇒ 前端按 `capabilities.mibaoChat=false` 全量
--   落到「需要管理员授权」态。回滚前必须先回滚 admin-api 的可执行文件（代码与迁移同批发布）。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：`agent:chat`（同租户同码已存在即跳过）
--    ⚠️ 名称/资源/动作/描述逐字取自 `RegistrationService.defaultPermissions` 与
--       `PermissionService.ensureFullPermissionCatalog` 的同码条目（两处目录必须逐值相等，
--       判据见 tests/unit_ci_workflows/test_agent_permission_parity.py 判据 9② 与
--       tests/unit_ci_workflows/test_mibao_chat_gate.py 判据 ③）。
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '米宝对话', 'agent:chat', 'agent', 'chat', '唤出米宝对话（管理员默认/员工需授权）', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'agent:chat');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：**只授给 `admin` 角色**（有意收窄；其余岗位由企业管理员按需勾）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code = 'agent:chat'
WHERE r.deleted = 0
  AND r.code = 'admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ `agent:session` 旧描述更正（存量租户的目录里那一行**不会**被 Java 侧改写 ⇒ 必须落 UPDATE）
--    旧值 = '米宝对话/会话监控/在线接待'（源自 `RegistrationService` 的历史描述）。
--    新值 = '在线接待/会话监控'（该码实测只管 `/api/admin/agent-sessions/*`；「会话监控」
--    菜单节点已在 #5271 删除，仅作历史别名保留在描述里）。
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE permissions
   SET description = '在线接待/会话监控',
       updated_at  = NOW()
 WHERE code = 'agent:session'
   AND description = '米宝对话/会话监控/在线接待';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_tenants   INTEGER;
    stray_grants      INTEGER;
    stale_descriptions INTEGER;
BEGIN
    -- ① `agent:chat` 必须在**每个已有权限目录的租户**里存在一行
    --    （不以 tenants 为全集：没有任何 permissions 行的租户 = 尚未初始化，不在本迁移射程内）
    SELECT COUNT(*) INTO missing_tenants
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'agent:chat');
    IF missing_tenants > 0 THEN
        RAISE EXCEPTION 'V132 终态对账失败：% 个租户缺 agent:chat —— 回滚本迁移', missing_tenants;
    END IF;

    -- ② 收窄断言：`agent:chat` 的授权链接**只**允许落在 `admin` 角色上
    --    （多一个岗位 = 有人偷偷放宽了裁定⑧ 的「只回填 admin」，必须当场红）
    SELECT COUNT(*) INTO stray_grants
      FROM role_permissions rp
      JOIN roles r ON r.id = rp.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE p.code = 'agent:chat' AND rp.deleted = 0 AND r.code <> 'admin';
    IF stray_grants > 0 THEN
        RAISE EXCEPTION 'V132 终态对账失败：agent:chat 被授给了 % 个非 admin 角色 —— 违反「只回填 admin」（裁定⑧）', stray_grants;
    END IF;

    -- ③ 旧描述必须清干净（否则「两个都自称管米宝对话的码」在老租户上依然存在）
    SELECT COUNT(*) INTO stale_descriptions
      FROM permissions
     WHERE code = 'agent:session' AND description = '米宝对话/会话监控/在线接待';
    IF stale_descriptions > 0 THEN
        RAISE EXCEPTION 'V132 终态对账失败：% 行 agent:session 仍是旧描述 —— 回滚本迁移', stale_descriptions;
    END IF;
END $$;

COMMIT;
