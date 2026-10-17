-- V159 — `processing_orders` 增列 `order_kind`：同一实体上分出「加工单 / 出库作业单」两型（issue #7079）
--
-- ## 一句话
-- 卖布单（订单行 `processing_info.saleForm='布料'`）今天会生成一张**真正的加工单**（只有
-- `裁剪`/`打包` 两道工序）。用户裁定（2026-10-17）：卖布单**不该叫加工单**，应该是**出库作业单**。
-- 本轮**不做全仓改名**（表名 / 端点 / `JG-` 单号 / 权限码一字不动），只在同一实体上加**单据类型**
-- 这一列，让成品帘与卖布在同一个 `processing_orders` 上分成两型。
--
-- ## 取值与语义（`processing` / `outbound`）
-- | 值 | 含义 | 谁写 |
-- |---|---|---|
-- | `processing` | 加工（成品帘；**混合单**也在这一档） | 生成加工单时按快照判定 |
-- | `outbound` | 出库（卖布单：快照**每一行** `saleForm='布料'`） | 同上 |
--
-- ## 判定规则（**生成时冻结**；单一出处 = `ProcessingOrderService.deriveOrderKind`）
-- 快照非空**且每一行** `saleForm == '布料'` ⇒ `outbound`；否则 `processing`
-- （**混合单 = 有加工 ⇒ `processing`**）。快照行里的 `saleForm` 由
-- `ProcessingOrderService.CRAFT_SPEC_SNAPSHOT_KEYS` 从 `order_items.processing_info` **透传**
-- ⇒ **缺键就是缺**：缺 `saleForm` 的行按**非布料**处理，Java **不造值**。
--
-- ## 存量行 = `processing`（`DEFAULT` 兜底，**不回填**、不改历史 —— **有意**，如实登记）
-- 该列 `NOT NULL DEFAULT 'processing'` ⇒ 存量行与「未判定的写入方」自动落加工。卖布单是**新口径**；
-- 历史加工单当时就是**按加工单**做的（工序 / 计件 / 纸面都已发生）⇒ 事后改型只会**改写已发生的
-- 作业史**。要改口径就往前修，不回头改历史。
--
-- ## 与 `db/init/schema.sql` 的关系（**必须同步**）
-- 新建库走**基线**（`backend/admin-api/src/main/resources/db/init/schema.sql`，由
-- `docker-entrypoint-initdb.d` 执行，**迁移链不在该栈运行**）⇒ 只写迁移 = 新建库缺列 ⇒ 读面 500
-- （同 #3270 形态）。本迁移已同步该文件的 `CREATE TABLE`（列**追加在末位**，与
-- `ALTER … ADD COLUMN` 的追加位一致 ⇒ bootstrap 与存量库列序逐位相同）+ 约束 + 列注释。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` ⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）：无损失（本列由本迁移新增，取值可由 `items_snapshot` 重算）
-- -- ALTER TABLE processing_orders DROP CONSTRAINT IF EXISTS ck_processing_orders_order_kind;
-- -- ALTER TABLE processing_orders DROP COLUMN IF EXISTS order_kind;

BEGIN;

-- ① 单据类型两态（存量行由 DEFAULT 兜底 ⇒ processing；**不回填**）
ALTER TABLE processing_orders
    ADD COLUMN IF NOT EXISTS order_kind VARCHAR(16) NOT NULL DEFAULT 'processing';

-- ② 取值白名单（与服务端 `ProcessingOrderService.ORDER_KIND_PROCESSING` / `ORDER_KIND_OUTBOUND` 逐值同源）
ALTER TABLE processing_orders DROP CONSTRAINT IF EXISTS ck_processing_orders_order_kind;
ALTER TABLE processing_orders
    ADD CONSTRAINT ck_processing_orders_order_kind
    CHECK (order_kind IN ('processing', 'outbound'));

COMMENT ON COLUMN processing_orders.order_kind IS
    '单据类型（V159，issue #7079）：processing 加工（成品帘；**混合单**也在这一档）/ outbound 出库（卖布单的裁剪/打包作业 —— 快照每一行 saleForm=布料）。判定在**生成那一刻冻结**（ProcessingOrderService.deriveOrderKind，与 items_snapshot 同批落库）⇒ 事后改订单行不回改、历史单不改型。存量行 = processing（DEFAULT 兜底，不回填）';

-- ③ 终态对账：列 / NOT NULL / 默认值 / 约束**任一写错必须当场停**
--    （本仓迁移写错了**不会重跑**，而 `MigrationRunner` 对非连接类失败是「记日志、跳过继续」
--     ⇒ 静默半成品；静态/自检判据是唯一出口）
DO $$
DECLARE
    col_type TEXT;
    col_nullable TEXT;
    col_default TEXT;
    ck_def TEXT;
BEGIN
    SELECT data_type, is_nullable, column_default
      INTO col_type, col_nullable, col_default
      FROM information_schema.columns
     WHERE table_name = 'processing_orders' AND column_name = 'order_kind';
    IF col_type IS NULL THEN
        RAISE EXCEPTION 'V159 终态对账失败：processing_orders.order_kind 列不存在 —— 回滚本迁移';
    END IF;
    IF col_nullable <> 'NO' THEN
        RAISE EXCEPTION 'V159 终态对账失败：order_kind 必须 NOT NULL（实际 is_nullable=%）', col_nullable;
    END IF;
    IF col_default IS NULL OR col_default NOT LIKE '%processing%' THEN
        RAISE EXCEPTION 'V159 终态对账失败：order_kind 默认值不是 processing（实际 = %）', col_default;
    END IF;

    SELECT pg_get_constraintdef(oid) INTO ck_def
      FROM pg_constraint
     WHERE conname = 'ck_processing_orders_order_kind'
       AND conrelid = 'processing_orders'::regclass;
    IF ck_def IS NULL THEN
        RAISE EXCEPTION 'V159 终态对账失败：ck_processing_orders_order_kind 不存在 —— 回滚本迁移';
    END IF;
    IF ck_def NOT LIKE '%processing%' OR ck_def NOT LIKE '%outbound%' THEN
        RAISE EXCEPTION 'V159 终态对账失败：取值约束没钉住两态（实际 = %）', ck_def;
    END IF;
END $$;

COMMIT;
