-- V214 / issue #9005（P1）：商品门幅清单落库（products.door_widths）
--
-- ## 病灶（2026-11-22 生产全字段冒烟，tenant 1 实测）
-- `POST /api/admin/products` 带 `doorWidths: ["2.8","3.2"]` ⇒ **200 创建成功**，但 `products` 表
-- **没有 door_widths 列**（只读 SQL 实测 `column "door_widths" does not exist`）⇒ 该入参只在
-- 「颜色 × 门幅 笛卡尔积自动建 SKU」这一条路径上被消费；没有颜色/SKU 时**无声丢弃**，
-- `GET /api/admin/products/{id}` 也读不回来（响应里的 `doorWidths` 是**从 SKU 派生**的，
-- 没有 SKU 时结构上就派生不出任何东西）。
--
-- ## 为什么是「商品级声明列」而不是「只靠 SKU 派生」（两个口径并存，主次分明）
-- SKU 组合 = 颜色 × 门幅（用户裁定 2026-09-21，见 V108/V113）⇒ 门幅**是** SKU 维度，
-- 派生值必须继续作为「有 SKU 时」的权威（`ProductService.getProductById` 里派生值覆盖本列）。
-- 但「商家声明了哪些门幅」这件事在**还没有 SKU 时**（先填门幅、后配颜色的草稿态）同样是事实，
-- 而派生值此时结构上不存在 ⇒ 需要一列把它存下来。**本列不替换派生口径、也不作为下单权威**。
-- 参照对象 = V113 的 `products.selling_methods`（同为 JSONB 数组属性列）；
-- 区别：售卖方式**不是** SKU 维度（已上移为商品属性），门幅**是** SKU 维度（故派生优先）。
--
-- ## 回填（存量 100% 可从既有数据推导，不编默认值、不改任何业务数字）
-- 只填**空数组**的行：从该货号既有的 `product_skus.door_width` 去重聚合（字典序）。
-- 已有值的行**一律不覆盖**（幂等：二次执行 0 行变更）。
-- 「一个 SKU 都没有」的货号保持 `[]`（承认真值缺失 —— 与 V113 对 `selling_methods` 的
-- 「回填不了就留默认值」不同：门幅**无法**从一个空集合推出任何东西，不猜）。
--
-- ## 回滚
--   ALTER TABLE products DROP COLUMN IF EXISTS door_widths;
-- 本列纯新增、无外键、无约束、不被别处引用 ⇒ 回滚即回到 V213 终态；
-- 回滚前写入的门幅清单只存在于该列，回滚 = 丢弃这份声明（`product_skus` 行不受任何影响，
-- 读面回到「只从 SKU 派生」的旧口径）。数据无损，无需反向迁移。
--
-- ## 幂等
-- `MigrationRunner` 会在「schema.sql 已建出终态」的库上**再跑一遍**迁移链（bootstrap-first，
-- issue #3615）⇒ 加列必须 `IF NOT EXISTS`；回填的 `WHERE` 自带「只填空行」判据 ⇒ 可重入。

ALTER TABLE products ADD COLUMN IF NOT EXISTS door_widths JSONB DEFAULT '[]'::jsonb;

-- 存量回填：取该货号既有 SKU 的门幅去重集合（只填空行，已有值不覆盖）
UPDATE products p
   SET door_widths = agg.widths
  FROM (
        SELECT product_id, jsonb_agg(dw ORDER BY dw) AS widths
          FROM (SELECT DISTINCT product_id, door_width AS dw
                  FROM product_skus
                 WHERE door_width IS NOT NULL AND btrim(door_width) <> '') d
         GROUP BY product_id
       ) agg
 WHERE p.id = agg.product_id
   -- 只填空数组行（NULL 与 [] 都算空）：已有值的行一律不覆盖
   AND COALESCE(jsonb_array_length(p.door_widths), 0) = 0;

COMMENT ON COLUMN products.door_widths IS
    '商家声明的门幅（规格尺寸）清单，JSONB 数组（V214 / issue #9005）。'
    '有 SKU 时读面仍以 product_skus.door_width 的派生值为准（SKU 组合 = 颜色 × 门幅，用户裁定 2026-09-21，'
    '故本列不是下单/算料权威）；本列承载「还没有 SKU 时」的同一份声明，'
    '避免建品收下的门幅被无声丢弃、且能在 GET /api/admin/products/{id} 回读。';
