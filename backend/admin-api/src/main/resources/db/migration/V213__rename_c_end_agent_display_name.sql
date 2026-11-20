-- V213__rename_c_end_agent_display_name.sql
--
-- 背景（issue #8881，用户 2026-11-09）：C 端顾客客服对外称呼「元元」→「米宝」。
--
-- 本迁移只回填**存量数据里的展示名**；代码侧（Python 默认值 / 提示词 / 前端文案）
-- 与本迁移**同批发布**。不可变历史迁移（V150 等）一字未改 —— 改 DB 一律新增迁移。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `UPDATE ... WHERE bot_name = '元元'` 带**旧值谓词** ⇒ 第二遍匹配 0 行，结果与第一遍逐值相同；
--   · 只 `UPDATE`，不 `INSERT` / 不 `DELETE` ⇒ 无新增行、无删除行；
--   · `ALTER COLUMN ... SET DEFAULT` 可重复执行。
--
-- ## 停止条件（fail-closed）
--   `tenant_ai_configs` 里不再有 `bot_name = '元元'` 的**系统默认值**行。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   UPDATE tenant_ai_configs SET bot_name = '元元' WHERE bot_name = '米宝';
--   ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '元元';
--   ⚠️ 回滚**必然覆盖**「改成米宝之后、又被商户自己改过」的行 ⇒ 只在确认无商户自定义改动时执行。
--
-- ## 边界（照实登记）
--   · **只改仍是系统默认值的行**：商户自定义过客服名的（`bot_name` 既非 '元元' 也非空）一个字都不动；
--   · `greeting_template` 里可能写着「元元」的**商户自定义欢迎语**属商户数据，不在本迁移范围；
--   · 新租户列默认值由本迁移推到 '米宝'：`db/init/schema.sql` 的 `DEFAULT '小布'` 属**已发布内容**
--     （`tests/unit_ci_workflows/migration_fingerprints.json` 按 sha256 冻结），故不回改 schema.sql
--     —— 存量库与全新库都生效（init 先跑、迁移随后）。

BEGIN;

-- 租户客服名：系统默认值 '元元' → '米宝'（商户自定义名不动）
UPDATE tenant_ai_configs
   SET bot_name   = '米宝',
       updated_at = NOW()
 WHERE bot_name = '元元';

-- 新租户的**列默认值**
ALTER TABLE tenant_ai_configs ALTER COLUMN bot_name SET DEFAULT '米宝';

COMMIT;
