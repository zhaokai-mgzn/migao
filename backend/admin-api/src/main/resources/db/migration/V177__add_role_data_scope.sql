-- 数据范围 data scope（issue #7372，P0-4 段 1）—— 角色级「能看谁的数据」
--
-- ## 一句话
-- 权限码管「能不能进这个模块」，本列管「进去以后能看见谁的数据」。没有它，一个「业务员」角色
-- 只要拿到 `order:list` 就能看见全公司的订单 —— 授权到模块不等于授权到数据。
--
-- ## 本段范围（写清才好评审）
-- - 只做 **两态**：`tenant`（全租户，**默认**，存量角色零回归）/ `self`（只看**本人**创建的单据）。
-- - **门店 / 部门 / 指定人员**三个维度**本段不做**：门店与部门在仓里没有实体（新建就是另一张
--   需要人裁定的组织模型），指定人员是第三态（需要一张关联表）。它们留作后续段，判断依据写在这里，
--   不靠「记得」。
-- - 作用域先落**订单域**（列表 + 详情）；客户域、导出、黄金策工具查询是后续段（见 issue 验收判据
--   的「四处同一口径」—— 本段只先立**一处**并留元守卫，不允许悄悄只做列表）。
--
-- ## 语义（多角色取宽）
-- 一个用户可有多个角色 ⇒ 权限取**并集**，数据范围同样取**并集的最宽**：只要有一个角色是 `tenant`，
-- 该用户就是 `tenant`。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步同一列（新建库不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：`ALTER TABLE roles DROP COLUMN data_scope;` **无数据损失**
--   （该列只有配置态，历史行为 = 默认 `tenant`）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE roles ADD COLUMN IF NOT EXISTS data_scope VARCHAR(16) NOT NULL DEFAULT 'tenant';

-- 幂等：约束单独判存在（ADD CONSTRAINT 无 IF NOT EXISTS ⇒ 用 DO 块兜住重复执行）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_roles_data_scope'
    ) THEN
        ALTER TABLE roles ADD CONSTRAINT ck_roles_data_scope
            CHECK (data_scope IN ('tenant', 'self'));
    END IF;
END $$;

COMMENT ON COLUMN roles.data_scope IS
    '数据范围（issue #7372）：tenant = 全租户（默认，存量零回归）/ self = 只看本人创建的单据；多角色取最宽';

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_col BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'roles' AND column_name = 'data_scope'
    ) INTO has_col;
    IF NOT has_col THEN
        RAISE EXCEPTION 'roles.data_scope 缺列（issue #7372 段 1 迁移未生效）';
    END IF;
END $$;

COMMIT;
