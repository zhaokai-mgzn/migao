-- 种子：默认租户 + 默认角色（issue #3270）
--
-- ## 背景
-- ai-agent 的 DEBUG customer 身份**固定 tenant_id=1**（app/utils/auth.py）。
-- `docs/sql/schema.sql` 是全新库 bootstrap 脚本，此前**只建表不插种子** →
-- 全新库上任何会话创建都违反 `sessions_tenant_id_fkey`（tenant 1 不存在）→
-- HTTP 500 → 本地/CI docker 栈的 C 端评测 9/9 全失败。
-- `schema_full.sql` 一直有这段种子，`schema.sql` 缺失（两份 schema 漂移）。
--
-- 本迁移把种子落进**迁移链**：既让 bootstrap（schema.sql 已同步同样种子）与
-- 迁移链收敛到同一状态，又兜住「已上线但缺种子」的存量库（幂等补齐）。
--
-- ## 幂等性
-- 全部 ON CONFLICT DO NOTHING；MigrationRunner 要求所有 SQL 文件幂等，可重复执行。

-- 默认租户（id=1）
INSERT INTO tenants (id, name, code, industry, status)
  OVERRIDING SYSTEM VALUE
  VALUES (1, '米高智能', 'migao', '布艺窗帘', 'active')
  ON CONFLICT (id) DO NOTHING;

-- 默认角色（五岗：管理员/运营/客服 + 超管；角色码与 HR 用例对齐）
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
  ('role_admin', 1, '管理员', 'admin', '租户管理权限', 'active'),
  ('role_operator', 1, '运营', 'operator', '商品与订单运营', 'active'),
  ('role_customer_service', 1, '客服', 'customer_service', '客服工作台权限', 'active'),
  ('role_super_admin', 1, '超级管理员', 'super_admin', '平台级超管权限', 'active')
  ON CONFLICT (id) DO NOTHING;
