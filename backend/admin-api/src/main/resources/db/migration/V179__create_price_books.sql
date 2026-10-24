-- 价格本（issue #7375，P1-3 段 1）—— 协议价 / 等级价 / 阶梯价
--
-- ## 一句话
-- 现在下单价格**只来自前端传值**，服务端不解析：同一件货，三个客户等级可以拿到同一个价，
-- 「给老客户便宜 5%」只能靠业务员手动改数字，改错了没人留痕。
--
-- ## 三张表（各自一义，不混一张）
-- 1. `customer_sku_prices`：**协议价**（客户 × SKU 的议定价）—— 优先级最高。
-- 2. `vip_level_prices`：**等级价**（`customer_profiles.vip_level` × SKU）。
-- 3. `sku_tier_prices`：**阶梯价**（SKU + 数量区间），只在没有前两级时生效。
--
-- ## 口径（写清楚才不会被拍脑袋解释）
-- - 解析优先级：**协议价 > 等级价 > 阶梯价 > SKU 标准价（`product_skus.price`）**。
-- - **未定价 ≠ ¥0.00**：四层都没有 ⇒ 解析结果 `source = 'unpriced'`、`price = null`
--   （SKU 标准价 `price` 有值才算「有价」；不会因为列 DEFAULT 0 就把 0 当成价格 —— 那等于白送）。
-- - 阶梯区间：`[min_qty, max_qty]` **闭区间**，`max_qty IS NULL` = 无上限；同一 SKU 的区间**不允许重叠**
--   （重叠就没法判「该用哪一档」）⇒ 用唯一索引 + 服务层复核兜住。
-- - 价格 `NUMERIC(12,2)`：与 `product_skus.price` 同精度（售价分位，绝不给「半分钱」留口子）。
--
-- ## 非目标（照实登记）
-- 促销引擎 / 优惠券 / 满减 / 客户分组价 / 币种 —— 都不在本表族范围（issue #7375 已明列）。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步三张表（新建库不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：`DROP TABLE sku_tier_prices, vip_level_prices, customer_sku_prices;`
--   **无数据损失**（表是新增的配置面，既有订单价格不受影响）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ① 协议价：客户 × SKU
CREATE TABLE IF NOT EXISTS customer_sku_prices (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customer_profiles(id),
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    price NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    note VARCHAR(255),
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);
-- 同一客户同一 SKU 只有**一个生效协议价**（软删不算）
CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_sku_prices_pair
    ON customer_sku_prices (tenant_id, customer_id, sku_id) WHERE deleted = 0;

-- ② 等级价：VIP 等级 × SKU
CREATE TABLE IF NOT EXISTS vip_level_prices (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    vip_level VARCHAR(16) NOT NULL,
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    price NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_vip_level_prices_pair
    ON vip_level_prices (tenant_id, vip_level, sku_id) WHERE deleted = 0;

-- ③ 阶梯价：SKU + 数量区间（闭区间；max_qty NULL = 无上限）
CREATE TABLE IF NOT EXISTS sku_tier_prices (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    sku_id BIGINT NOT NULL REFERENCES product_skus(id),
    min_qty NUMERIC(12,1) NOT NULL CHECK (min_qty > 0),
    max_qty NUMERIC(12,1),
    price NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    CONSTRAINT ck_sku_tier_range CHECK (max_qty IS NULL OR max_qty >= min_qty)
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_sku_tier_prices_edge
    ON sku_tier_prices (tenant_id, sku_id, min_qty) WHERE deleted = 0;

-- RLS：三张表都按租户隔离（与其余租户域表同款；缺口 = 跨租户读别人的价格本）
ALTER TABLE customer_sku_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE vip_level_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sku_tier_prices ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'customer_sku_prices'
                   AND policyname = 'tenant_isolation_customer_sku_prices') THEN
        CREATE POLICY tenant_isolation_customer_sku_prices ON customer_sku_prices
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'vip_level_prices'
                   AND policyname = 'tenant_isolation_vip_level_prices') THEN
        CREATE POLICY tenant_isolation_vip_level_prices ON vip_level_prices
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'sku_tier_prices'
                   AND policyname = 'tenant_isolation_sku_tier_prices') THEN
        CREATE POLICY tenant_isolation_sku_tier_prices ON sku_tier_prices
            USING (tenant_id = current_setting('app.current_tenant', true)::BIGINT);
    END IF;
END $$;

-- 终态对账（fail-closed）：三张表缺任一张就报错，不许「迁移跑了一半」
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM unnest(ARRAY['customer_sku_prices', 'vip_level_prices', 'sku_tier_prices']) AS t
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_name = t AND table_schema = 'public');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '价格本表族缺表：%（issue #7375 段 1 迁移未生效）', missing;
    END IF;
END $$;

COMMIT;
