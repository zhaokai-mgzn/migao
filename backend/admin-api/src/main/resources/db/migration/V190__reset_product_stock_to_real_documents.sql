-- 商品档案不再持有库存数值：按真实单据重算（issue #7597）
--
-- ## 用户裁定（原文，2026-10-24）
--   「我们现在商品中设置了库存数值，这个要移除了，要根据真实库存数据来」
--   同日两问的选择：**移除范围 = A**（表单不再录入，库存只由真实单据产生）；
--                   **存量数据 = C**（清零，只认真实入库）。
--
-- ## 一句话
-- 每个 SKU 的 `product_skus.stock` 重算为 **真实单据台账净额**：
--   `reason` ∈ {`inbound`, `order`, `aftersales`}                 （入库 / 订单 / 售后回补）
--   或 `reason = 'manual'` 且 `note` 以「库存盘点：」开头           （批次盘点，见 BatchStocktakeService）
-- 手工基线（建品直接写 stock）/ 表单改库存 / Agent 手工调整 **一律不计**；
-- 结果 clamp 到 ≥ 0（历史「先手工建库、后卖货」的组合会算出负数 —— 不制造负库存）。
-- ⇒ 从未用过真实单据的商品：库存 **0**（用户选择的「清零」）；
--    用过入库 / 出库的商品：等于其真实单据净额（**不被误清零**）。
--
-- ## 为什么不是一条无脑 `UPDATE product_skus SET stock = 0`
-- 「清零」的对象是**在商品里手工设置的数值**，不是真实入库形成的库存。
-- 无脑置 0 会让「入库 60 米」的商品一夜变成 0，而 `stock_batches` 里仍有 60 米
-- —— 两本账当场互相矛盾（`BatchStockViews.ReconcileRow` 的 `diff = batchRemaining − skuStock`
-- 恒等式也会破，页面开始报「差额无法解释」）。
--
-- ## 台账（issue #4157 / #5950 纪律：改库存必须落账）
-- 有变化的 SKU 各落一条 `manual` 台账行（`before_qty` = 改前、`after_qty` = 重算值），
-- 「库存为什么从 X 变成 Y」仍能在库存明细里答出来；不落行 = 审计缺口。
--
-- ## 性能
-- 三个子查询都带 `e.tenant_id = s.tenant_id`：台账索引是 `(tenant_id, sku_id, id)`，
-- 少了 tenant 这一维就用不上索引 ⇒ 大台账上逐 SKU 顺序扫 = O(N²)。
--
-- ## 幂等（`MigrationRunner` 硬要求）
-- 重算值只由 `stock_ledger_entries` 的**真实单据**行决定；本文件自己写入的行
-- （`note` = '商品不再设置库存：按真实单据重算（issue #7597）'）**不匹配**上面的真实单据谓词
-- ⇒ 第二遍 `old == new`、0 行变化、0 行新增。
--
-- ## 边界（如实登记）
-- - 只动 `product_skus.stock` 与 `products.stock`（后者是派生冗余列，按 SKU 汇总回写，唯一写入口
--   在 `ProductService.syncProductStockFromSkus`，本迁移与它同口径）；
-- - **不动** `stock_batches`（真实入库批次是另一本账，批次行不可改 —— V111 的口径）；
-- - **不动** 任何订单 / 入库单 / 盘点单 / 退货单；
-- - 在**所有租户**上生效（用户已裁定：一次性、破坏性数据迁移）。
--
-- 迁移后的可见后果（如实登记）：商品详情「批次账」对账里的 `unbatchedMeters`
-- （= 台账外存量，即「建品直接写 stock」的那部分）对纯手工库存的商品归 0 —— 那是**目标**，不是回归。
--
-- ⚠️ 写法约束：本文件**不使用** `WITH … AS (…) … FROM <cte>` 形态 ——
-- `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py` 的 `_referenced_tables`
-- 会把 `FROM <cte>` 读成「引用了不存在的表」。⇒ 统一用**派生表 / 标量子查询**（`FROM (` 不匹配该正则）。

-- ① 先落账（用改前的值算 before/after），再改数 —— 顺序不可颠倒。
INSERT INTO stock_ledger_entries
    (tenant_id, product_id, sku_id, sku_code, delta, before_qty, after_qty, reason, ref_no, note, operator)
SELECT d.tenant_id,
       d.product_id,
       d.sku_id,
       d.sku_code,
       d.new_stock - d.old_stock,
       d.old_stock,
       d.new_stock,
       'manual',
       NULL,
       '商品不再设置库存：按真实单据重算（issue #7597）',
       'system'
FROM (
    SELECT s.tenant_id,
           s.product_id,
           s.id                        AS sku_id,
           s.sku_code,
           COALESCE(s.stock, 0)        AS old_stock,
           GREATEST(0::numeric, COALESCE((
               SELECT SUM(e.delta)
               FROM stock_ledger_entries e
               WHERE e.deleted = 0
                 AND e.tenant_id = s.tenant_id
                 AND e.sku_id = s.id
                 AND (
                       e.reason IN ('inbound', 'order', 'aftersales')
                       OR (e.reason = 'manual' AND e.note LIKE '库存盘点：%')
                     )
           ), 0))                        AS new_stock
    FROM product_skus s
) d
WHERE d.old_stock <> d.new_stock;

-- ② SKU 库存 = 真实单据净额（clamp ≥ 0）
UPDATE product_skus s
SET stock = GREATEST(0::numeric, COALESCE((
        SELECT SUM(e.delta)
        FROM stock_ledger_entries e
        WHERE e.deleted = 0
          AND e.tenant_id = s.tenant_id
          AND e.sku_id = s.id
          AND (
                e.reason IN ('inbound', 'order', 'aftersales')
                OR (e.reason = 'manual' AND e.note LIKE '库存盘点：%')
              )
    ), 0))
WHERE s.stock IS DISTINCT FROM GREATEST(0::numeric, COALESCE((
        SELECT SUM(e.delta)
        FROM stock_ledger_entries e
        WHERE e.deleted = 0
          AND e.tenant_id = s.tenant_id
          AND e.sku_id = s.id
          AND (
                e.reason IN ('inbound', 'order', 'aftersales')
                OR (e.reason = 'manual' AND e.note LIKE '库存盘点：%')
              )
    ), 0));

-- ③ 派生冗余列 `products.stock` 回写为 SKU 汇总（含「没有 SKU 的商品 ⇒ 0」）
UPDATE products p
SET stock = COALESCE((SELECT SUM(s.stock) FROM product_skus s WHERE s.product_id = p.id), 0)
WHERE p.stock IS DISTINCT FROM
      COALESCE((SELECT SUM(s.stock) FROM product_skus s WHERE s.product_id = p.id), 0);
