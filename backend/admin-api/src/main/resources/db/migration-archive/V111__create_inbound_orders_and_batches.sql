-- 入库单 / 批次（issue #5034）—— 商品布料入库的标准能力
--
-- ## 一句话
--   ① 新表 `inbound_orders` + `inbound_order_items` + `stock_batches`：一次收货 = 一张入库单，
--      **一个 SKU 行 = 一个批次**（批次号由服务端自动生成，格式 `PC-yyyyMMdd-NNNN`）；
--   ② `product_skus` 追加 `avg_cost` / `cost_amount`（**移动加权平均成本**，用户裁定：成本核算一起做）
--      与 `latest_batch_no`（最近入库批次号）；
--   ③ `stock_ledger_entries` 追加成本快照列 + `reason` 放行 `inbound`
--      ⇒ 「库存为什么从 X 变成 Y、当时成本是多少」在**同一张事实账**上可对账。
--
-- ## 为什么批次粒度 = 入库单行（用户裁定 2026-09-23）
--   行业里缸号（dye lot）的本质是「同一染色机、同一天、同一缸染液染出的一批布」
--   （`docs/curtain-selling-method-industry-research.md` §1 逐字引文，S6）——
--   它的**天然粒度是一批，不是一卷**。AHFA 要求「每卷卷标带 Lot number」（同文件 S10）说的是
--   **卷标要显示缸号**，不是「每卷一个缸号」。故本单取「行级批次 + 批次号回写到 SKU」：
--   既满足「有值时话术必须引用它」（同文件 §8.2 对 `dye_lot` 的缺省策略），
--   又不引入「库存 = 卷集合求和」的模型升级（卷长是**区间值**，硬折算会向顾客报错数，同文件 §8.2 末）。
--
-- ## 为什么系统批次号 ≠ 缸号（两列并存，不合并）
--   `stock_batches.batch_no` 是**系统自动生成**的内部批次标识（唯一、可追溯、可打印卷标）；
--   `stock_batches.dye_lot` 是**供应商给的缸号**（外部事实，可空）。
--   合并成一列会逼系统在「商家没填缸号」时**编一个缸号**——那正是 #8.2「可空；有值时话术必须引用它」
--   要防的假真值。⇒ 两列并存：`dye_lot` 为 NULL 时只是「这批没记缸号」，不伪造。
--
-- ## 成本口径（移动加权平均，只做入库侧）
--   `after_avg = (before_qty * before_avg + in_qty * unit_cost) / (before_qty + in_qty)`
--   `before_qty = 0`（或 `before_avg IS NULL`，= 建品以来的首次入库）⇒ `after_avg = unit_cost`。
--   出库**不改**均价（只减 `cost_amount`），这是移动加权平均的标准语义。
--   存量 `avg_cost` 回填**一律留 NULL**（= 未知），**不猜**：存量库存的成本没有任何真值来源，
--   编一个 0 会让「库存金额 = 0」看起来像真数据（同 V108 对 `roll_length_m` 的 NULL 口径）。
--
-- ## 数量单位（如实登记本单的边界）
--   `quantity` / `delta` / `before_qty` / `after_qty` 均为 **INTEGER** —— 与既有
--   `product_skus.stock` / `stock_ledger_entries` 的粒度**逐字一致**。布料按米入库时
--   非整数米（如 60.5 米）**本单不支持**，需要「库存米数小数化」这条独立改动（未在本单内，
--   因为它要动订单扣减/售后回补/台账三条既有链路）。⇒ 服务端对非整数入库量**显式拒绝**，
--   不静默取整（静默取整 = 账面与实物不符且无人发现）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 列：`ADD COLUMN IF NOT EXISTS`；表：`CREATE TABLE IF NOT EXISTS`；
--   · 约束：`DROP CONSTRAINT IF EXISTS` + 「不存在才 ADD」（`pg_constraint` 判据）；
--   · 索引：`CREATE INDEX IF NOT EXISTS`；权限种子：`WHERE NOT EXISTS` + `ON CONFLICT DO NOTHING`；
--   · 文末 `DO` 块**终态对账**两遍都成立（既是幂等自证，也是判据漂移的停止条件）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V112__rollback_inbound_orders.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS stock_batches;
-- -- DROP TABLE IF EXISTS inbound_order_items;
-- -- DROP TABLE IF EXISTS inbound_orders;
-- -- ALTER TABLE stock_ledger_entries DROP COLUMN IF EXISTS unit_cost;
-- -- ALTER TABLE stock_ledger_entries DROP COLUMN IF EXISTS cost_amount;
-- -- ALTER TABLE stock_ledger_entries DROP COLUMN IF EXISTS avg_cost_before;
-- -- ALTER TABLE stock_ledger_entries DROP COLUMN IF EXISTS avg_cost_after;
-- -- ALTER TABLE product_skus DROP COLUMN IF EXISTS avg_cost;
-- -- ALTER TABLE product_skus DROP COLUMN IF EXISTS cost_amount;
-- -- ALTER TABLE product_skus DROP COLUMN IF EXISTS latest_batch_no;
-- ```
-- **回滚是有损的**：`inbound_orders` / `stock_batches` 的行**回不来**（入库事实与批次号一并丢弃），
-- 而 `product_skus.stock` 已加上去的数量**不会自动回退** ⇒ 回滚后必须人工盘点。
-- 属**有意**（回滚一个已过账的库存单据本就不该静默复原数量）。
--
-- ## bootstrap 终态同步（同 V99/V100/V108 纪律）
-- `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `products` / `product_skus` / `stock_ledger_entries` 任一不存在 ⇒ 迁移失败并停下
--      （不 CREATE TABLE 兜底 —— 会造出无外键/无索引的影子表）；
--   ② 终态对账报「表缺失」/「列缺失」/「唯一索引缺失」/「`reason` 约束未放行 inbound」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 的实测口径）
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
      FROM (VALUES ('products'), ('product_skus'), ('stock_ledger_entries'), ('tenants')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V111 前置表缺失：% —— 不兜底建表（会造出无外键/无索引的影子表），迁移停下', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② `product_skus`：移动加权平均成本 + 最近入库批次号
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE product_skus
    ADD COLUMN IF NOT EXISTS avg_cost NUMERIC(12,4);

ALTER TABLE product_skus
    ADD COLUMN IF NOT EXISTS cost_amount NUMERIC(16,4);

ALTER TABLE product_skus
    ADD COLUMN IF NOT EXISTS latest_batch_no VARCHAR(32);

COMMENT ON COLUMN product_skus.avg_cost IS
    '移动加权平均单位成本（元/单位，V111）。NULL = **未知**（存量库存无成本真值来源，一律不回填、不猜 0）。入库时 after=(before_qty*before_avg+in_qty*unit_cost)/(before_qty+in_qty)，before_qty=0 或 before_avg 为 NULL ⇒ after=unit_cost；出库不改均价（只减 cost_amount）';

COMMENT ON COLUMN product_skus.cost_amount IS
    '库存成本金额 = stock * avg_cost（V111，派生冗余列，便于「库存金额」直接汇总）。NULL = 成本未知（与 avg_cost 同源；不得用 0 冒充「成本为零」）';

COMMENT ON COLUMN product_skus.latest_batch_no IS
    '最近一次入库的批次号（V111，系统生成的 PC-yyyyMMdd-NNNN）。给「同一批次一致性」话术提供可引用真值（docs/curtain-selling-method-industry-research.md §8.2 对 dye_lot 的缺省策略：有值时话术必须引用它）；NULL = 从未入库过';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ `stock_ledger_entries`：成本快照列 + 放行 `reason='inbound'`
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE stock_ledger_entries
    ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,4);

ALTER TABLE stock_ledger_entries
    ADD COLUMN IF NOT EXISTS cost_amount NUMERIC(16,4);

ALTER TABLE stock_ledger_entries
    ADD COLUMN IF NOT EXISTS avg_cost_before NUMERIC(12,4);

ALTER TABLE stock_ledger_entries
    ADD COLUMN IF NOT EXISTS avg_cost_after NUMERIC(12,4);

COMMENT ON COLUMN stock_ledger_entries.unit_cost IS
    '本次变更的单位成本（V111）：入库 = 入库行单价；出库/回补 = 变更时的 SKU 移动加权均价（出库按均价结转成本）。NULL = 该次变更发生时成本未知（存量行全部为 NULL，不伪造）';

COMMENT ON COLUMN stock_ledger_entries.cost_amount IS
    '本次变更的成本金额 = |delta| * unit_cost（V111，出库为结转成本、入库为采购金额）。NULL = 成本未知';

COMMENT ON COLUMN stock_ledger_entries.avg_cost_before IS
    '变更前该 SKU 的移动加权平均成本（V111）。NULL = 变更前成本未知（含首次入库）。与 before_qty/after_qty 同族：**变更前后的完整快照**，使「成本为什么变了」可逐行对账';

COMMENT ON COLUMN stock_ledger_entries.avg_cost_after IS
    '变更后该 SKU 的移动加权平均成本（V111）。出库不变（= avg_cost_before）；入库按移动加权平均公式重算。NULL = 变更后成本仍未知（未记单价的入库）';

COMMENT ON COLUMN stock_ledger_entries.reason IS
    '变更来源（V111 起四类）：order 订单扣减 / aftersales 售后回补 / manual 手工调整 / **inbound 入库单过账**（ref_no = 入库单号 RK-yyyyMMdd-NNNN，或批次号）';

-- reason 放行 inbound：先 DROP 旧的（若存在）再建，保证两遍执行同一终态。
-- 存量行只可能是三类旧值 ⇒ 新约束对存量**恒成立**，故可直接 VALIDATE（无需 NOT VALID 两段式）。
ALTER TABLE stock_ledger_entries DROP CONSTRAINT IF EXISTS ck_stock_ledger_reason;

ALTER TABLE stock_ledger_entries
    ADD CONSTRAINT ck_stock_ledger_reason
    CHECK (reason IN ('order', 'aftersales', 'manual', 'inbound'));

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 入库单主表
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS inbound_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 业务单号 RK-yyyyMMdd-NNNN（DB 唯一约束防重号；租户内唯一）
    inbound_no VARCHAR(32) NOT NULL,
    -- 供应商（文本，MVP 不建主数据 —— 同 processing_orders.processor 口径）
    supplier VARCHAR(128),
    -- 供应商送货单号（对账用，可空）
    supplier_doc_no VARCHAR(64),
    -- 仓库/仓位（文本，可空；单仓商家不填）
    warehouse VARCHAR(64),
    -- 入库日期（业务日期，可回填历史单；与 created_at 的「录入时间」区分）
    inbound_date DATE NOT NULL DEFAULT CURRENT_DATE,
    -- draft 草稿（不动库存）/ posted 已过账（加库存 + 落台账 + 算成本）/ cancelled 已作废（仅 draft 可作废）
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    -- 单据总额 = Σ 行金额（过账时冻结；草稿态随行变动重算）
    total_amount NUMERIC(16,4) NOT NULL DEFAULT 0,
    remark TEXT,
    -- 过账/作废留痕（谁在何时把库存改了 —— 库存是资金级数据，必须可追责）
    posted_at TIMESTAMP WITH TIME ZONE,
    posted_by VARCHAR(64),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_by VARCHAR(64),
    cancelled_reason TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_no
    ON inbound_orders (inbound_no);

CREATE INDEX IF NOT EXISTS idx_inbound_orders_tenant_status_date
    ON inbound_orders (tenant_id, status, inbound_date DESC);

CREATE INDEX IF NOT EXISTS idx_inbound_orders_tenant_supplier
    ON inbound_orders (tenant_id, supplier);

COMMENT ON TABLE inbound_orders IS
    '入库单（V111，issue #5034）：一次布料收货 = 一张单。draft 不动库存，posted 才加库存（幂等闸：只允许 draft→posted 一次），cancelled 仅 draft 可作废（已过账的单不得作废 —— 库存已进台账，冲销要另开单）';

COMMENT ON COLUMN inbound_orders.inbound_no IS
    '入库单号 RK-yyyyMMdd-NNNN（V111）。与订单号（17 位数字）、加工单号 JG-yyyyMMdd-NNNN、售后单号 AS-* 同族：前缀 + 日期 + 序号，序号由服务端原子计数器生成，DB 唯一索引兜底防重号';

COMMENT ON COLUMN inbound_orders.status IS
    '状态机（V111）：draft → posted（过账，加库存+落台账+算移动加权成本）；draft → cancelled（作废，未动库存）。**posted 是终态**（不可改不可删）：库存已进台账，冲销须另开入库/出库单，不原地改历史';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 入库单明细（**一个 SKU 行 = 一个批次**）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS inbound_order_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id) ON DELETE CASCADE,
    -- SKU 主键（无 FK：同 stock_ledger_entries.sku_id —— SKU 会被「删旧行+插新行」硬删重建）
    sku_id BIGINT,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    -- 快照：入库时点的货号/颜色/门幅，事后改商品不影响历史单（同 processing_orders.items_snapshot 口径）
    sku_code VARCHAR(64),
    color_name VARCHAR(64),
    door_width VARCHAR(32),
    -- 入库数量（**单位 = 该 SKU 的库存单位**；整数 —— 与 product_skus.stock 粒度逐字一致）
    quantity INT NOT NULL,
    -- 入库单价（元/单位）。NULL = 未记单价 ⇒ 只加数量、不算成本（avg_cost 保持原值/仍为 NULL）
    unit_cost NUMERIC(12,4),
    -- 行金额 = quantity * unit_cost（NULL 单价 ⇒ NULL，不用 0 冒充）
    amount NUMERIC(16,4),
    -- 本行生成的批次号（**过账时才写**；草稿态为 NULL —— 批次号代表「真的收货了」）
    batch_no VARCHAR(32),
    -- 供应商给的缸号（外部事实，可空；与系统批次号是两件事，见文件头注释）
    dye_lot VARCHAR(64),
    -- 每卷米数（可空，卷长为区间值 ⇒ 不参与任何换算，仅记录/打印卷标）
    roll_length_m NUMERIC(8,2),
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_inbound_items_order
    ON inbound_order_items (inbound_order_id);

CREATE INDEX IF NOT EXISTS idx_inbound_items_tenant_sku
    ON inbound_order_items (tenant_id, sku_id);

COMMENT ON TABLE inbound_order_items IS
    '入库单明细（V111）：**一个 SKU 行 = 一个批次**（用户裁定 2026-09-23）。批次粒度取行级而非卷级：缸号的行业粒度本就是「一批布」（docs/curtain-selling-method-industry-research.md §1），卷级会要求「库存 = 卷集合求和」的模型升级，而卷长是区间值（同文件 §8.2 末明确不建议硬折算）';

COMMENT ON COLUMN inbound_order_items.batch_no IS
    '本行批次号 PC-yyyyMMdd-NNNN（V111，服务端自动生成）。**过账时才写**：草稿态 NULL（批次号 = 「真的收货了」的标识，草稿尚未收货）';

COMMENT ON COLUMN inbound_order_items.dye_lot IS
    '供应商缸号（V111，可空）。与 batch_no 是**两件事**：batch_no 是系统内部批次标识，dye_lot 是外部事实（同缸染出的布）。NULL = 未记录缸号 —— **不得**用 batch_no 冒充缸号（假真值）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑥ 批次台账（卷标/追溯的读面）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS stock_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    -- 来源入库单（批次只能由入库产生；回滚/冲销走新单据，不删批次行）
    inbound_order_id VARCHAR(64) REFERENCES inbound_orders(id),
    inbound_item_id BIGINT,
    inbound_no VARCHAR(32),
    quantity INT NOT NULL,
    unit_cost NUMERIC(12,4),
    amount NUMERIC(16,4),
    dye_lot VARCHAR(64),
    roll_length_m NUMERIC(8,2),
    supplier VARCHAR(128),
    warehouse VARCHAR(64),
    -- 收货日期（= 入库单 inbound_date，**不是** created_at）
    received_date DATE,
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);

-- 批次号在**租户内唯一**（不是全局唯一：多租户各自的序号空间独立）
CREATE UNIQUE INDEX IF NOT EXISTS uk_stock_batches_no
    ON stock_batches (tenant_id, batch_no);

CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_sku
    ON stock_batches (tenant_id, sku_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_dye_lot
    ON stock_batches (tenant_id, dye_lot);

CREATE INDEX IF NOT EXISTS idx_stock_batches_inbound
    ON stock_batches (inbound_order_id);

COMMENT ON TABLE stock_batches IS
    '批次台账（V111）：一行 = 一个入库批次（= 一条入库单明细行）。缸号（dye_lot）随批次可见 —— 对应 AHFA 卷标须带 Lot number 的行业要求（docs/curtain-selling-method-industry-research.md §1/S10）。批次行**不可改**：冲销走新单据，不原地改历史';

COMMENT ON COLUMN stock_batches.batch_no IS
    '批次号 PC-yyyyMMdd-NNNN（V111，服务端自动生成，租户内唯一）。格式与入库单号 RK-* 同族；`PC` = 批次拼音首字母，与 JG（加工）/AS（售后）/FIN（财务）不撞前缀';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑦ 存量租户权限补齐（幂等，与 RegistrationService 种子目录同源）
--   inbound:view   → 客服/运营/销售/财务（与 processing:view 同一批岗位）
--   inbound:create → 运营（管理员运行时特判 ["*"]，无需显式关联）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '入库单查看', 'inbound:view', 'inbound-order', 'view', '查看入库单/批次', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'inbound:view');

INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '入库单操作', 'inbound:create', 'inbound-order', 'create', '建单/过账/作废入库单', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = 'inbound:create');

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code IN ('customer_service', 'operator', 'sales', 'finance') AND r.deleted = 0 AND p.code = 'inbound:view'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)
SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0
FROM roles r
JOIN permissions p ON p.tenant_id = r.tenant_id
WHERE r.code = 'operator' AND r.deleted = 0 AND p.code = 'inbound:create'
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑧ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n          INTEGER;
    missing    TEXT;
    constraint_def TEXT;
BEGIN
    -- ① 三张新表必须在
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('inbound_orders'), ('inbound_order_items'), ('stock_batches')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V111 终态对账失败：新表缺失 % —— 回滚本迁移', missing;
    END IF;

    -- ② product_skus 三列必须在（成本列是「成本核算一起做」的落点，缺一列即功能静默缺失）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('avg_cost'), ('cost_amount'), ('latest_batch_no')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'product_skus'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V111 终态对账失败：product_skus 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ③ stock_ledger_entries 四列必须在（成本快照列）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('unit_cost'), ('cost_amount'), ('avg_cost_before'), ('avg_cost_after')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'stock_ledger_entries'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V111 终态对账失败：stock_ledger_entries 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ④ reason 约束必须**放行 inbound**（漏了它 ⇒ 入库落台账当场 23514 违反约束，功能全断）
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_stock_ledger_reason'
       AND conrelid = 'stock_ledger_entries'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V111 终态对账失败：ck_stock_ledger_reason 约束不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%inbound%' THEN
        RAISE EXCEPTION 'V111 终态对账失败：reason 约束未放行 inbound，实际 = % —— 回滚本迁移', constraint_def;
    END IF;

    -- ⑤ 批次号租户内唯一索引必须在（防重号是「自动生成批次号」的安全网）
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'stock_batches'
       AND indexname = 'uk_stock_batches_no';
    IF n = 0 THEN
        RAISE EXCEPTION 'V111 终态对账失败：uk_stock_batches_no 唯一索引缺失 —— 批次号会重号 —— 回滚本迁移';
    END IF;

    -- ⑥ 入库单号唯一索引必须在
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'inbound_orders'
       AND indexname = 'uk_inbound_orders_no';
    IF n = 0 THEN
        RAISE EXCEPTION 'V111 终态对账失败：uk_inbound_orders_no 唯一索引缺失 —— 入库单号会重号 —— 回滚本迁移';
    END IF;

    -- ⑦ 权限种子必须在（缺了它 ⇒ 岗位权限页勾不动、侧边栏看不到入库菜单）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('inbound:view'), ('inbound:create')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM permissions
                        WHERE code = v.c AND deleted = 0);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V111 终态对账失败：权限码缺失 % —— 回滚本迁移', missing;
    END IF;
END $$;

COMMIT;
