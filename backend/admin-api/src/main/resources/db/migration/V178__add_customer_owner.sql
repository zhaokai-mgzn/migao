-- 客户负责人（issue #7372，P0-4 段 2）—— 客户域「只看本人的客户」的真值载体
--
-- ## 一句话
-- 订单域能按 `orders.created_by` 判「本人的单」；客户域**没有对应列** —— 客户是从微信/H5 自助注册来的，
-- 表里没有「谁负责这个客户」。没有载体，客户域的数据范围就只能靠猜，所以本迁移补上这一列。
--
-- ## 口径（用户在 2026-10-21 亲自裁定，逐字）
-- 「加『客户负责人』字段，未指派的按『有单的客户』兜底」。落地形态：
--   本人范围可见 = `owner_user_id = 我` **或**（`owner_user_id IS NULL` 且「我有过这个客户的单」）。
-- 兜底不是偷懒：存量客户全部 `owner_user_id IS NULL`，若不给兜底，业务员上线当天会**看不见任何客户**
-- （看起来像数据丢了）。有了兜底，历史客户按「谁出过单」自动可见，之后逐步指派负责人即可收紧。
--
-- ## 为什么可空 + 无外键到 users
-- `NULL` 是**有意义的业务态**（未指派），不能被默认值抹掉；且客户可能先于员工建立而存在，
-- 强外键会在删员工时挡路（与 `orders.created_by` 同款处理：语义引用、不建外键）。
--
-- ## 一处踩坑（实测）
-- `customer_profiles` **没有** `deleted` 软删列（与 orders 不同）⇒ 索引**不能**带 `WHERE deleted = 0`，
-- 带上就是 `字段 "deleted" 不存在`（真库建库直接报错）。本文件已按无谓词建索引。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步同一列 + 索引（新建库不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：`DROP INDEX …; ALTER TABLE customer_profiles DROP COLUMN owner_user_id;`
--   **无数据损失** ⇒ 客户域退回租户级可见（= 改前行为）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64);

COMMENT ON COLUMN customer_profiles.owner_user_id IS
    '客户负责人（issue #7372）：NULL = 未指派；数据范围 self 时本人可见 = 自己是负责人，或未指派但自己有该客户的单';

CREATE INDEX IF NOT EXISTS idx_customer_profiles_owner
    ON customer_profiles (tenant_id, owner_user_id);

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_col BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'customer_profiles' AND column_name = 'owner_user_id'
    ) INTO has_col;
    IF NOT has_col THEN
        RAISE EXCEPTION 'customer_profiles.owner_user_id 缺列（issue #7372 段 2 迁移未生效）';
    END IF;
END $$;

COMMIT;
