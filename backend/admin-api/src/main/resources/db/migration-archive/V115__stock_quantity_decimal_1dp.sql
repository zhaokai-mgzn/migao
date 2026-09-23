-- 库存米数小数化（1 位小数，issue #5063）—— 三层 INTEGER 一并升级为 NUMERIC(12,1)
--
-- ## 用户裁定（本单最高口径，逐字）
--   「**库存米数是小数，1 位小数，必须改造**」+「**不能损失客户**」
--   ⇒ 精度 = `NUMERIC(12,1)`（**不是** issue 原建议的 `NUMERIC(12,2)`）：与用料口径一致 ——
--     真值源 `docs/curtain-fabric-quote-rules.md` §8「用料米数一律**向上进位到 0.1**」
--     （`ceil(x*10)/10`），库存粒度与裁床实际用料粒度对齐即可，多余精度只会制造
--     「账上有 0.05 米、裁床上不存在」的假精度。
--
-- ## 一句话
--   把库存链路**三层**的数量列从 `INTEGER` 升级为 `NUMERIC(12,1)`：
--     ① 库存权威 `product_skus.stock`；② 商品级派生 `products.stock`；
--     ③ 事实账 `stock_ledger_entries.{delta,before_qty,after_qty}`；
--     ④ 入库单 `inbound_order_items.quantity`；⑤ 批次台账 `stock_batches.quantity`；
--     ⑥ 销量 `product_skus.sales_count` / `products.sales_count`（见下「为什么销量也在本单」）。
--
-- ## 为什么必须三层一起（缺陷形态）
--   订单侧 `order_items.quantity` 早已是 `DECIMAL(10,2)`（issue #3666），库存侧却是 `INTEGER`
--   ⇒ 中间靠 `OrderService` 里四处 `item.getQuantity().intValue()` **取整数部分**接起来：
--     · 顾客买 2.7 米 ⇒ `deductStock(2)`、`increaseSalesCount(2)` ⇒ **0.7 米凭空消失**；
--     · 顾客买 0.5 米 ⇒ `needed = 0` ⇒ 库存前置校验**恒通过**、不减库存、不加销量
--       （成交但零变动，全程无告警）；
--     · 入库 60.5 米 ⇒ 服务端**显式拒绝**（V111 有意的 fail-closed，见下）。
--   只改其中一层（例如只把 `product_skus.stock` 放宽）会让取整点**搬家**而不是消失
--   —— 台账 delta 与库存权威仍会各说各话 ⇒ 本单三层一起改。
--
-- ## 为什么销量（`sales_count`）也在本单
--   `product_skus.sales_count` 与 `stock` **同源**（同一个 `item.getQuantity()`，
--   `OrderService.deductSkuStock` 一次调用两处写）。只改库存不改销量 ⇒ 出现
--   「2.7 米卖出、库存 -2.7、销量 +2」这种**单笔单据内部自相矛盾**的账。
--   列口径逐字一致（`NUMERIC(12,1)`），整数场景**逐值不变**。
--
-- ## 存量回填：无损（如实登记）
--   整数天然是 1 位小数（`60 :: numeric(12,1) = 60.0`）⇒ **无有损项**、无需回填 UPDATE
--   （`ALTER COLUMN TYPE ... USING <col>::numeric(12,1)` 本身就是全量转换）。
--   这与 V113 的 SKU 去重（有损）不同：本迁移**可逆且不丢任何值**。
--
-- ## 「禁止静默取整」的边界（如实登记，不粉饰）
--   列精度 `NUMERIC(12,1)` 本身**带舍入语义**：PG 对超出 scale 的写入按四舍五入落库
--   （例如 `2.75` 会变成 `2.8`，不报错）。⇒ 数据库层**拦不住**「调用方传了 2 位小数」。
--   本单的 fail-closed 落在**应用层**（Java `StockQuantity` 判据 + Python 工具 schema/校验）：
--   库存类**输入**（入库数量 / 库存调整量 / 商品建改的 stock）超过 1 位小数 ⇒ **显式拒绝**，
--   文案可行动；订单侧（顾客已下单的 `order_items.quantity`，`DECIMAL(10,2)`）按 §8 口径
--   **显式向上进位到 0.1** 后落库（扣减与回补同一口径 ⇒ 净变化为 0），**不拒绝**（不损失客户）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 列类型：**先问当前类型**（`information_schema.columns` 的 `data_type` / `numeric_scale`），
--     已是终态 ⇒ `CONTINUE`（第二遍 0 次 `ALTER`，不做无谓的表重写）；
--   · 前置表/列存在性 **fail-closed**（缺表 ⇒ 抛异常停下，不兜底建表）；
--   · `COMMENT ON COLUMN` 覆盖式（天然幂等）；
--   · 文末 `DO` 块**终态对账**两遍都成立（既是幂等自证，也是判据漂移的停止条件）。
--
-- ## 为什么用 `EXECUTE` 动态 SQL 做「类型不对才改」
--   `ALTER TABLE ... ALTER COLUMN ... TYPE` 在 PG 里对**已是同类型**的列是空操作但**仍会
--   取 `ACCESS EXCLUSIVE` 锁**（大表上是可观测的停写窗口）。⇒ 判据前置到 PL/pgSQL 里、
--   只在真的需要时 `EXECUTE`（同 V113 第 ② 段「先问列在不在，在才回填」的同族纪律）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V116__rollback_stock_quantity_decimal.sql（本单只登记，不落码）
-- -- ALTER TABLE product_skus          ALTER COLUMN stock      TYPE INTEGER USING ROUND(stock)::integer;
-- -- ALTER TABLE product_skus          ALTER COLUMN sales_count TYPE INTEGER USING ROUND(sales_count)::integer;
-- -- ALTER TABLE products              ALTER COLUMN stock      TYPE INTEGER USING ROUND(stock)::integer;
-- -- ALTER TABLE products              ALTER COLUMN sales_count TYPE INTEGER USING ROUND(sales_count)::integer;
-- -- ALTER TABLE stock_ledger_entries  ALTER COLUMN delta      TYPE INTEGER USING ROUND(delta)::integer;
-- -- ALTER TABLE stock_ledger_entries  ALTER COLUMN before_qty TYPE INTEGER USING ROUND(before_qty)::integer;
-- -- ALTER TABLE stock_ledger_entries  ALTER COLUMN after_qty  TYPE INTEGER USING ROUND(after_qty)::integer;
-- -- ALTER TABLE inbound_order_items   ALTER COLUMN quantity   TYPE INTEGER USING ROUND(quantity)::integer;
-- -- ALTER TABLE stock_batches         ALTER COLUMN quantity   TYPE INTEGER USING ROUND(quantity)::integer;
-- ```
-- **回滚是有损的**：已经落库的小数米数（如 60.5）被 `ROUND` 成整数 ⇒ 账实不符。故回滚前必须
-- 先把小数行清零或人工盘点（本迁移的「存量无损」只保证 **前向**，反向不保证）。
--
-- ## bootstrap 终态同步（同 V99/V100/V113 纪律）
-- `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① 六张表 / 九个列任一不存在 ⇒ 迁移失败并停下（不 CREATE TABLE 兜底）；
--   ② 文末终态对账报「列类型不是 numeric」或「precision/scale 不符」⇒ 写语句判据漂移或被
--      部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97 / V102 / V107 / V113 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('product_skus'), ('products'), ('stock_ledger_entries'),
                   ('inbound_order_items'), ('stock_batches')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V115 前置表缺失：% —— 不兜底建表（会造出无外键/无索引的影子表），迁移停下', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 数量列 INT → NUMERIC(12,1)（**幂等**：已是终态则跳过）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    target       RECORD;
    current_type TEXT;
    current_prec INT;
    current_scal INT;
BEGIN
    FOR target IN
        SELECT * FROM (VALUES
            ('product_skus',         'stock'),
            ('product_skus',         'sales_count'),
            ('products',             'stock'),
            ('products',             'sales_count'),
            ('stock_ledger_entries', 'delta'),
            ('stock_ledger_entries', 'before_qty'),
            ('stock_ledger_entries', 'after_qty'),
            ('inbound_order_items',  'quantity'),
            ('stock_batches',        'quantity')
        ) AS v(tbl, col)
    LOOP
        SELECT data_type,
               COALESCE(numeric_precision, 0),
               COALESCE(numeric_scale, 0)
          INTO current_type, current_prec, current_scal
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = target.tbl
           AND column_name  = target.col;

        IF current_type IS NULL THEN
            RAISE EXCEPTION 'V115 前置列缺失：%.% —— 迁移停下（不 ADD COLUMN 兜底：会造出无口径的列）',
                target.tbl, target.col;
        END IF;

        -- 已是终态 ⇒ 空操作（第二遍走这条路径；不做无谓的表重写 + ACCESS EXCLUSIVE 锁）
        IF current_type = 'numeric' AND current_prec = 12 AND current_scal = 1 THEN
            CONTINUE;
        END IF;

        -- 整数 → numeric(12,1) 是**无损**转换（60 :: numeric(12,1) = 60.0）；显式 USING 让
        -- 「按什么规则转换」写在迁移里，而不是依赖 PG 的隐式转换（隐式转换在跨精度时是舍入）
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE NUMERIC(12,1) USING %I::numeric(12,1)',
                       target.tbl, target.col, target.col);
    END LOOP;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 列口径注释（覆盖式，天然幂等）—— 让「为什么是 1 位」留在库内可查
-- ══════════════════════════════════════════════════════════════════════════════════════
COMMENT ON COLUMN product_skus.stock IS
    '库存数量（米，NUMERIC(12,1)，V115/#5063 起支持 1 位小数 = 0.1 米粒度；此前为 INTEGER）—— SKU 级是唯一权威（#4038）';
COMMENT ON COLUMN product_skus.sales_count IS
    'SKU 累计销量（NUMERIC(12,1)，V115/#5063：与 stock 同源，同一笔单据两者口径必须一致）';
COMMENT ON COLUMN products.stock IS
    '库存数量（NUMERIC(12,1)，V115/#5063；**派生冗余列**，权威是 product_skus.stock 汇总，见 #4038）';
COMMENT ON COLUMN products.sales_count IS
    '累计销量（NUMERIC(12,1)，V115/#5063）';
COMMENT ON COLUMN stock_ledger_entries.delta IS
    '变化量（正=入库/回补，负=出库/扣减），恒等于 after_qty - before_qty（NUMERIC(12,1)，V115/#5063）';
COMMENT ON COLUMN stock_ledger_entries.before_qty IS
    '变更前库存（NUMERIC(12,1)，V115/#5063；同 SKU 相邻两行必须首尾相接 = 上一行 after_qty）';
COMMENT ON COLUMN stock_ledger_entries.after_qty IS
    '变更后库存（NUMERIC(12,1)，V115/#5063）';
COMMENT ON COLUMN inbound_order_items.quantity IS
    '入库数量（米，NUMERIC(12,1)，V115/#5063；与 product_skus.stock 粒度逐字一致）';
COMMENT ON COLUMN stock_batches.quantity IS
    '批次数量（米，NUMERIC(12,1)，V115/#5063；与 product_skus.stock 粒度逐字一致）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 终态对账（fail-closed）：九个列必须都是 numeric(12,1)
--     —— 既是幂等自证（两遍都成立），也是「写语句判据漂移」的停止条件
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    bad       TEXT;
    bad_count INT;
    col_count INT;
BEGIN
    SELECT count(*) INTO col_count
      FROM (VALUES ('product_skus','stock'), ('product_skus','sales_count'),
                   ('products','stock'), ('products','sales_count'),
                   ('stock_ledger_entries','delta'), ('stock_ledger_entries','before_qty'),
                   ('stock_ledger_entries','after_qty'),
                   ('inbound_order_items','quantity'), ('stock_batches','quantity')) AS v(tbl, col)
      JOIN information_schema.columns c
        ON c.table_schema = 'public' AND c.table_name = v.tbl AND c.column_name = v.col;

    -- ① 九列必须都还在（缺列 = 前置判据漂移，不是「已经是终态」）
    IF col_count <> 9 THEN
        RAISE EXCEPTION 'V115 终态对账失败：目标列只找到 % / 9 —— 回滚本迁移', col_count;
    END IF;

    -- ② 逐列核对类型 + 精度（data_type 必须是 numeric，precision=12、scale=1）
    SELECT string_agg(format('%s.%s(type=%s,precision=%s,scale=%s)',
                             v.tbl, v.col, c.data_type,
                             COALESCE(c.numeric_precision::text, '-'),
                             COALESCE(c.numeric_scale::text, '-')), ', '),
           count(*)
      INTO bad, bad_count
      FROM (VALUES ('product_skus','stock'), ('product_skus','sales_count'),
                   ('products','stock'), ('products','sales_count'),
                   ('stock_ledger_entries','delta'), ('stock_ledger_entries','before_qty'),
                   ('stock_ledger_entries','after_qty'),
                   ('inbound_order_items','quantity'), ('stock_batches','quantity')) AS v(tbl, col)
      JOIN information_schema.columns c
        ON c.table_schema = 'public' AND c.table_name = v.tbl AND c.column_name = v.col
     WHERE NOT (c.data_type = 'numeric' AND c.numeric_precision = 12 AND c.numeric_scale = 1);

    IF bad_count > 0 THEN
        RAISE EXCEPTION 'V115 终态对账失败：以下列不是 numeric(12,1)：% —— 回滚本迁移', bad;
    END IF;
END $$;

COMMIT;
