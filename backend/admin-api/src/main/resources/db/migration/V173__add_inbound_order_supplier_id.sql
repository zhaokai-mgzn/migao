-- 入库单 → 供应商档案的引用（issue #7369，P0-1 段 2 之引用面）
--
-- ## 一句话
-- 段 1 把供应商做成了**档案**（`suppliers`），但入库单上仍只有一段自由文本。
-- 本迁移给单据加**引用列** `supplier_id`，并按**用户 2026-10-20 裁定的 A 口径**回填历史行：
--
--   > 「按名称**精确匹配**自动填 `supplier_id`，匹配不上的留 NULL 并出一张「待指派」清单给人处理，
--   >  **不改任何历史字段值**。」
--
-- ⇒ 本文件**只新增一列并填它自己**；`inbound_orders` 的任何既有列（尤其 `supplier` 文本）
--   **一个字节都不动** —— 那是历史留痕，改它就是篡改。
--
-- ## 为什么不直接改 `supplier` 文本列 / 为什么不删
-- ① 文本是**单据快照**（当时收货写的是什么就是什么），档案是**主数据**（可改名、可停用）；
-- ② 供应商改名后，历史单据不该跟着变（那是留痕）；要「按供应商聚合」就按 `supplier_id` 聚，
--    要「当时开的是什么单」就看文本 —— 两者各司其职。
--
-- ## 回填口径（精确匹配；其余留 NULL）
--   `btrim(o.supplier) = btrim(s.name)` **且** 同租户 **且** 双方未软删 ⇒ 填 `supplier_id`；
--   - 多家档案同名 ⇒ 不填（歧义即人工，不由迁移猜）；
--   - 文本为空 / 匹配不上 ⇒ 留 NULL（由「待指派」清单出口给人建档或手工指派）。
--   ⚠️ 只在**本列首次引入**的这次迁移里跑一次；后续新单据的匹配在服务层（`InboundOrderService`）。
--
-- ## 终态同步与回滚
-- - 建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 已同步本列与索引（新建库路径不跑迁移链）。
-- - 回滚（**新迁移，不删本文件**）：
--   ```sql
--   -- V173__rollback_inbound_supplier_id.sql（只登记，不落码）
--   -- DROP INDEX IF EXISTS idx_inbound_orders_supplier_id;
--   -- ALTER TABLE inbound_orders DROP COLUMN IF EXISTS supplier_id;
--   ```
--   回滚**有损**（丢的是「这张单是哪个档案」的关联，不丢任何业务数据；文本供应商仍在）。
--
-- ## 显式事务
-- 两条执行路径（`MigrationRunner` 整份 execute / `psql -f` 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE inbound_orders
    ADD COLUMN IF NOT EXISTS supplier_id VARCHAR(64) REFERENCES suppliers(id);

COMMENT ON COLUMN inbound_orders.supplier_id IS
    '供应商档案引用（issue #7369 段 2）：NULL = 未建档 / 待指派；历史行按**名称精确匹配**回填（用户 2026-10-20 裁定 A 口径），既有 supplier 文本列一字未改';

-- 「某供应商的单据」是本列唯一的读法；部分索引避开空值与软删（deleted 在该表是 0/1）
CREATE INDEX IF NOT EXISTS idx_inbound_orders_supplier_id
    ON inbound_orders (tenant_id, supplier_id)
    WHERE supplier_id IS NOT NULL AND deleted = 0;

-- A 口径回填：只按名称精确匹配；歧义（同名多档）与空值一律留 NULL，交由「待指派」清单人工处理
UPDATE inbound_orders o
   SET supplier_id = s.id
  FROM suppliers s
 WHERE o.supplier_id IS NULL
   AND o.deleted = 0
   AND o.supplier IS NOT NULL
   AND btrim(o.supplier) <> ''
   AND s.deleted = FALSE
   AND s.tenant_id = o.tenant_id
   AND btrim(s.name) = btrim(o.supplier)
   -- 同名多档 ⇒ 不猜（子查询计数 = 1 才匹配）
   AND (SELECT count(*) FROM suppliers s2
         WHERE s2.deleted = FALSE AND s2.tenant_id = o.tenant_id
           AND btrim(s2.name) = btrim(o.supplier)) = 1;

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_column BOOLEAN;
    has_index BOOLEAN;
    has_fk BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'inbound_orders' AND column_name = 'supplier_id'
    ) INTO has_column;
    IF NOT has_column THEN
        RAISE EXCEPTION 'inbound_orders.supplier_id 列缺失（issue #7369 迁移未生效）';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
         WHERE tablename = 'inbound_orders' AND indexname = 'idx_inbound_orders_supplier_id'
    ) INTO has_index;
    IF NOT has_index THEN
        RAISE EXCEPTION 'idx_inbound_orders_supplier_id 索引缺失';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage k
            ON tc.constraint_name = k.constraint_name
         WHERE tc.table_name = 'inbound_orders'
           AND tc.constraint_type = 'FOREIGN KEY'
           AND k.column_name = 'supplier_id'
    ) INTO has_fk;
    IF NOT has_fk THEN
        RAISE EXCEPTION 'inbound_orders.supplier_id 缺外键（回填可能指向不存在的档案）';
    END IF;
END $$;

COMMIT;
