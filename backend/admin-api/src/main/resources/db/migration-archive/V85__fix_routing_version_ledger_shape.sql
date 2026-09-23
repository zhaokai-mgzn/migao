-- 路线变更账切新模型形状（issue #4581，P0）
--
-- ## 病灶（一句话）
-- `production_routing_versions` 仍是 V60 的**旧模型**形状，而写面自 P2b（#4459）起已落在新结构
-- `production_route_templates` ⇒ `ProductionRoutingCommandService.appendVersion()` 写的每一行
-- **都被 Postgres 拒**，事务回滚 ⇒ `POST /api/admin/production/routings`（新建路线）与
-- `PUT /api/admin/production/routings/{id}`（带 mainline 的改主线）**恒 500**，路线一条也建不出来
-- （商家面实测 2026-09-19，merchant.migaozn.com）。改名 / 设默认 / 删除不写版本账 ⇒ 那三条路径正常，
-- 这正是「只有新建和改主线炸」的原因。
--
-- 两条**互相独立**的违约（任一条都必 500）：
--   ① `curtain_type` / `craft` 是 `NOT NULL` 且无默认值，而新模型**没有「部位 × 工艺」这一维**
--      （工艺已降为 `production_route_rules` 的触发键）⇒ 写面只能传 null ⇒ not-null violation
--      （MyBatis-Plus 默认 NOT_NULL 策略只是把 null 字段从 INSERT 里**省掉**，省掉照样违约）；
--   ② `routing_id` 上那条外键指向 **`production_routings`（旧表）**，而写面传的是
--      `production_route_templates.id`（新表，ASSIGN_UUID）⇒ FK violation。旧表自 P2b（#4495）起
--      已退役（活跃行由 V73 软删，全仓 `productionRoutingMapper` 已无使用点）。
--
-- ## 为什么是**新增 V85** 而不是改 V60
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改 V60 只对**全新库**生效，存量环境永远拿不到修后的表形状 = 「CI 全绿、功能静默缺失」
-- （issue #4235；V60 另被 `tests/unit_ci_workflows/migration_fingerprints.json` 逐字节冻结）。
-- ⇒ 一切增量都走新文件。
--
-- ## 本迁移做什么
--   ① 摘掉 `routing_id` 上**所有**指向 `production_routings` 的外键 —— **不写死约束名**
--      （bootstrap 路径由 `docs/sql/schema.sql` 内联建约束、迁移路径由 V60 的 `REFERENCES` 建，
--       名字可能不同）；
--   ② 换成指向 `production_route_templates(id)` 的具名外键，且带 **`NOT VALID`**：
--      存量行可能引用旧表 id（历史账），全量校验会让**存量库**的迁移失败；
--      `NOT VALID` 只跳过对存量行的校验，**新写入照旧强制**（正是本单要的语义）；
--   ③ `curtain_type` / `craft` 放开 `NOT NULL`（**列保留**，承载历史行）；
--   ④ 三列各补 `COMMENT ON COLUMN`，把新口径写进库（否则下一个人还会按 V60 的形状读）。
--
-- ⚠️ `routing_id` 本身**保持 NOT NULL**：新模型下它恒有值（= `production_route_templates.id`），
--    放开只会削弱「版本账必须挂在一张路线行上」这条不变式。
--
-- ## 幂等（MigrationRunner 硬要求所有迁移可重复执行；整个文件被 `jdbc.execute(整份 SQL)` 一次执行）
--   · `DO $$ … $$` 块：`DROP CONSTRAINT IF EXISTS` + 存在性谓词 ⇒ 第二次是空操作；
--   · `DROP CONSTRAINT IF EXISTS fk_production_routing_versions_template` + `ADD CONSTRAINT`
--     重跑 = 先摘自己再加回 ⇒ 净效果相同；
--   · `ALTER COLUMN … DROP NOT NULL` 天然幂等（已是可空时 PG 不报错）；
--   · `COMMENT ON COLUMN` 是覆盖写 ⇒ 幂等。
--   ⚠️ `ADD CONSTRAINT` **不用** `IF NOT EXISTS`：PG 没有该语法（那会变成语法错误，
--      而内容类失败在 `MigrationRunner` 里是「跳过这一条、继续跑后面的」⇒ **静默不生效**）。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- ALTER TABLE production_routing_versions DROP CONSTRAINT IF EXISTS fk_production_routing_versions_template;
-- ALTER TABLE production_routing_versions
--     ADD CONSTRAINT production_routing_versions_routing_id_fkey
--     FOREIGN KEY (routing_id) REFERENCES production_routings(id);
-- -- ⚠️ 两列**不要**急着改回 NOT NULL：库里已有 curtain_type/craft 为 NULL 的新模型行。
-- ```
--
-- ## 与测试的关系（红证）
--   · `tests/unit_ci_workflows/test_routing_version_ledger_shape.py`（L0 静态，case_ids: MC-012）
--     判据 ①~⑤ 在本文件**存在之前**全红；
--   · `ProductionRoutingCommandServiceTest` 的 payload 钉桩只能证明「写面传了什么」，
--     **看不见 DB 约束拒绝**（admin-api 无 testcontainers/H2）—— 表形状由上面那条 L0 判据守。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① + ② 摘掉指向旧表 `production_routings` 的外键，换挂到新表 `production_route_templates`
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    con RECORD;
BEGIN
    -- 不写死约束名：bootstrap 路径（docs/sql/schema.sql 的内联 REFERENCES）与迁移路径
    -- （V60）建出的约束名可能不同 ⇒ 按「引用的是哪张表」现场找。
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.contype = 'f'
          AND c.conrelid = 'production_routing_versions'::regclass
          AND c.confrelid = 'production_routings'::regclass
    LOOP
        EXECUTE format('ALTER TABLE production_routing_versions DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE production_routing_versions
    DROP CONSTRAINT IF EXISTS fk_production_routing_versions_template;
ALTER TABLE production_routing_versions
    ADD CONSTRAINT fk_production_routing_versions_template
    FOREIGN KEY (routing_id) REFERENCES production_route_templates(id) NOT VALID;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 旧模型的两列放开 NOT NULL（**列保留**：历史行仍答得出「当时是哪条 部位×工艺」）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE production_routing_versions ALTER COLUMN curtain_type DROP NOT NULL;
ALTER TABLE production_routing_versions ALTER COLUMN craft DROP NOT NULL;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 把新口径写进库（否则下一个人还会按 V60 的形状读这张表）
-- ══════════════════════════════════════════════════════════════════════════════════════
COMMENT ON COLUMN production_routing_versions.routing_id IS
    'V60 = 旧模型形状（外键指向已退役的 production_routings）。#4581（V85）起：本列 = '
    'production_route_templates.id（新结构「一条具名主线」），外键已改指向该表且带 NOT VALID '
    '（存量行可能引用旧表 id，新写入照旧强制）。';
COMMENT ON COLUMN production_routing_versions.curtain_type IS
    'V60 = 旧模型形状（NOT NULL，路线键的一维）。#4581（V85）起允许 NULL：新模型没有「部位 × 工艺」'
    '这一维（工艺已降为 production_route_rules 的触发键）⇒ 本列**只为历史行保留**，新行恒为 NULL。';
COMMENT ON COLUMN production_routing_versions.craft IS
    'V60 = 旧模型形状（NOT NULL，路线键的另一维）。#4581（V85）起允许 NULL：新模型不写本列 ⇒ '
    '**只为历史行保留**，新行恒为 NULL（与 curtain_type 同口径）。';
