-- 下单行的定价依据（issue #7375，P1-3 段 2）—— 「这一行为什么按这个价卖」
--
-- ## 一句话
-- 段 1 已经能在服务端解析「协议价 / 等级价 / 阶梯价 / 标准价」，但**下单时没有 SKU 可解析**：
-- `OrderCreateRequest` 的明细行只有 `productId`，SKU 只能在落库后从 `processingInfo` 反推。
-- 本迁移落两件事：① 请求可以带 SKU（`sku_id` / `sku_code` 落到行上）；② 定价依据留痕
-- （`price_source` + `price_client_unit_price`）。
--
-- ## 为什么要落 `price_client_unit_price`
-- 「服务端以价格本为准改写了客户端价」这件事，事后必须能回答「改前是多少」。
-- 只写最终价 = 只说结果不说依据；客户拿截图来对账时会变成各说各话。
--
-- ## 为什么落 `sku_id` / `sku_code`（无外键）
-- SKU 会被硬删重建（与 `stock_ledger_entries.sku_id` / `inbound_order_items.sku_id` 同款处理）：
-- 追溯优先用 `sku_code`，外键会在重建时挡路。两列**可空**：存量行与「手工录入行」没有 SKU，
-- 缺就是缺 —— 不猜、不回填。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步四列（新建库不跑迁移链）。
-- - 回滚：`ALTER TABLE order_items DROP COLUMN ...` ×4 **无数据损失**（只是丢「定价依据」这一层证据，
--   最终金额仍在 `unit_price` / `subtotal` 上）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE order_items ADD COLUMN IF NOT EXISTS sku_id BIGINT;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS sku_code VARCHAR(64);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS price_source VARCHAR(32);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS price_client_unit_price NUMERIC(12,2);

COMMENT ON COLUMN order_items.sku_id IS
    '下单时指定的 SKU（V180，issue #7375 段 2）：无外键（SKU 会硬删重建），追溯优先用 sku_code；NULL = 未指定';
COMMENT ON COLUMN order_items.sku_code IS
    '下单时的 SKU 货号快照（V180）：与 sku_id 同源，SKU 重建后仍可追溯';
COMMENT ON COLUMN order_items.price_source IS
    '单价来源（V180）：price_book_protocol / price_book_vip_level / price_book_tier / sku_standard_price / no_price_book / client（未参与服务端解析）';
COMMENT ON COLUMN order_items.price_client_unit_price IS
    '客户端原本传的单价（V180）：仅当服务端按价格本改写时记录，用于事后对账「改前是多少」；NULL = 未改写';

-- 终态对账（fail-closed）
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(c, ', ') INTO missing
      FROM unnest(ARRAY['sku_id', 'sku_code', 'price_source', 'price_client_unit_price']) AS c
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'order_items' AND column_name = c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'order_items 缺列：%（issue #7375 段 2 迁移未生效）', missing;
    END IF;
END $$;

COMMIT;
