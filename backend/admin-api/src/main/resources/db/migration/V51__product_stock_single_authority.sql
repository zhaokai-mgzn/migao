-- 商品库存「单一权威」收口（issue #4038）
--
-- 权威 = **SKU 级**（`product_skus.stock`）。依据：
--   ① 仓库既有真值 `.github/templates/product-sku-stock.yml`：
--      「商品库存 = 所有 SKU 库存求和（products.stock 常为 0，以 SKU 汇总为准）」；
--   ② DB 实测（2026-09-18，云 dev）：`products.stock` 与 SKU 汇总在 **311/497** 个商品上不一致，
--      有 SKU 的 351 个商品里 **299 个商品级恒为 0**（实测 `2699系列雪尼尔窗帘面料`：
--      商品级 0 / SKU 合计 9599）；
--   ③ 扣减（订单流程）、低库存口径、列表排序、详情/列表返回的 `stock` **全部已按 SKU 级**。
--
-- 本迁移做两件事（**只订正数据 + 加注释，不改表结构**）：
--   A. 把「有 SKU 的商品」的商品级列收敛为 SKU 汇总 —— 消除「同一商品两个数字」；
--   B. 给 4 个无消费/无写入的库存列打上显式标注，消灭「声明了却没人用」的静默形态。
--
-- 幂等：A 只命中 `IS DISTINCT FROM` 的行，重跑命中 0 行；B 的 COMMENT 可重复执行。

-- ── A. 存量收敛：商品级 stock := 该商品 SKU 库存汇总 ──────────────────────────
-- 只处理**有 SKU 记录**的商品：无 SKU 的商品其商品级列是唯一现存信息，
-- 不参与任何读路径（`getTotalStock` 对无 SKU 商品返回 0），保持原值不抹。
UPDATE products p
SET stock = agg.sku_sum
FROM (
    SELECT product_id, SUM(stock) AS sku_sum
    FROM product_skus
    GROUP BY product_id
) agg
WHERE p.id = agg.product_id
  AND p.stock IS DISTINCT FROM agg.sku_sum;

-- ── B. 标注（DB 内可读的「谁权威 / 谁没人用」） ──────────────────────────────
COMMENT ON COLUMN products.stock IS
    '派生冗余（非权威）：= 该商品 SKU 库存汇总（product_skus.stock 求和）。权威口径 = SKU 级；'
    '无 SKU 记录的商品本列不参与任何读路径。见 issue #4038（V51 已把存量收敛为 SKU 汇总）';

COMMENT ON COLUMN products.stock_warning_threshold IS
    '⚠️ 当前**无消费方**：低库存口径实际是 SKU 级 `product_skus.stock <= 100`'
    '（ai-agent-service app/tools/stock_semantics.py），本列不参与任何查询。见 issue #4056';

COMMENT ON COLUMN products.stock_deduction_mode IS
    '⚠️ 当前**无消费方**：全仓无任何 service/mapper 读取该列，实际扣减在订单流程按 SKU 级执行'
    '（ProductService.updateProductForAgent 亦明确「不支持通过 update 修改，忽略」）。见 issue #4056';

COMMENT ON COLUMN orders.stock_deducted IS
    '⚠️ **无写入方**：全仓无任何写路径（实测 0/954 恒 false），不可作为「已扣库存」的判据；'
    '写入点在 OrderService（实现 or 删列待裁定）。见 issue #4056 / #4038';