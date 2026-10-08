-- V150__rename_brand_display_names.sql
--
-- 背景（issue #6525，用户 2026-10-08 逐字）：对外称呼改名 ——
--   产品「米高」→「观星台」；B 端商家助手「米宝」→「黄金策」；C 端顾客客服「小布」→「元元」。
--
-- 本迁移只回填**存量数据里的展示名**；代码侧（Java 权限目录 / Python 默认值 / 前端文案）
-- 与本迁移**同批发布**。不可变历史迁移（V132 等）一字未改 —— 改 DB 一律新增迁移。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · ①② 两条 `UPDATE` 都带**旧值谓词** ⇒ 第二遍匹配 0 行，结果与第一遍逐值相同；
--   · 只 `UPDATE`，不 `INSERT` / 不 `DELETE` ⇒ 无新增行、无删除行。
--
-- ## 停止条件（fail-closed）
--   ① `tenant_ai_configs` 里不再有 `bot_name = '小布'` 的行；
--   ② 不再有 `agent:chat` 行挂着旧展示名（`米宝对话` / `唤出米宝对话%`）。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   UPDATE tenant_ai_configs SET bot_name = '小布' WHERE bot_name = '元元';
--   UPDATE permissions SET name = '米宝对话', description = '唤出米宝对话（管理员默认/员工需授权）'
--    WHERE code = 'agent:chat' AND name = '黄金策对话';
--   ⚠️ 回滚**必然覆盖**「改成元元之后、又被商户自己改过」的行 ⇒ 只在确认无商户自定义改动时执行。
--
-- ## 边界（照实登记）
--   · **只改仍是系统默认值的行**：商户自定义过客服名的（`bot_name` 既非 '小布' 也非空）一个字都不动；
--   · 活环境**租户名**（如「米高测试环境」/「米高POC演示布艺」）属商户自有数据，**不在本迁移范围**。

BEGIN;

-- ① 租户客服名：系统默认值 '小布' → '元元'（商户自定义名不动）
UPDATE tenant_ai_configs
   SET bot_name   = '元元',
       updated_at = NOW()
 WHERE bot_name = '小布';

-- ② 权限目录展示名：`agent:chat` 两处真值（`RegistrationService.defaultPermissions` 与
--    `PermissionService.ensureFullPermissionCatalog`）已随本批改名，存量租户那一行不会被 Java 侧改写
UPDATE permissions
   SET name        = '黄金策对话',
       description = '唤出黄金策对话（管理员默认/员工需授权）',
       updated_at  = NOW()
 WHERE code = 'agent:chat'
   AND (name = '米宝对话' OR description LIKE '唤出米宝对话%');

-- ③ 新租户的**列默认值**：`db/init/schema.sql` 的 `DEFAULT '小布'` 属**已发布内容**
--    （`tests/unit_ci_workflows/migration_fingerprints.json` 按 sha256 冻结 ⇒ 改一个字符即红），
--    故不回改 schema.sql，改由本迁移把列默认值推到 '元元' —— 存量库与全新库都生效（init 先跑、迁移随后）。
ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '元元';

COMMIT;
