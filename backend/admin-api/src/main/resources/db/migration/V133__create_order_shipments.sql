-- 发货单 + 发货明细（实发套/件/卷）—— issue #5648 **服务端半边**
--
-- ## 一句话
-- 给「工人拍照生成发货单 + 订单发货状态闭环」建它自己的**可查留痕载体**：
-- 一张发货单头表（谁 / 何时 / 哪张单 / 照片引用 / 识别留痕）+ 一张逐行实发明细表
-- （这一单实际发了几套 / 几件 / 几卷）。
--
-- ## 为什么不复用 order_logistics（不得复用）
-- `order_logistics` 只有公司 / 单号 / 发货人 / 类型 / 状态 / 轨迹 / 时间 —— **无数量列**
-- （本单实测：`^CREATE TABLE.*(ship|deliver|pack|logistic)` 只命中它）。
-- 「少发 / 错发」今天**不可核**，正因为「发了多少」根本没有落点。往 `order_logistics`
-- 塞数量列 = 让「物流记录」承担「发货单」的语义，而两者基数不同（一次发货一条物流，
-- 一张发货单 N 条明细）⇒ 必须有自己的行表。
--
-- ## 为什么留痕不能落在 audit_logs
-- `audit_logs` 是**有界 fail-open**（3s 超时即丢行，丢行是**允许**的，issue #4071）⇒
-- 拿它当「谁在何时拍的这张照片、照它发了哪些货」的依据 = 依据会**静默**丢失
-- （依据丢了不会有任何东西变红）。同 V127 的裁定口径。
--
-- ## 冻结契约（本单 PR body 逐字列出）
-- | 表 | 列 |
-- |---|---|
-- | `order_shipments` | `id, tenant_id, order_id, order_no, shipment_no, source, photo_refs, recognition, packed_by_worker_id, packed_by_worker_name, packed_at, shipped_by_worker_id, shipped_by_worker_name, shipped_at, tracking_no, logistics_company, client_request_id, unpacked_at, unpacked_by_worker_id, unpacked_by_worker_name, unpack_reason, created_at, updated_at, deleted` |
-- | `order_shipment_items` | `id, tenant_id, shipment_id, order_id, order_item_id, product_name, shipped_quantity, unit, set_count, roll_count, created_at, updated_at, deleted` |
--
-- ⚠️ **契约之外的两列**：两张表的 `tenant_id`。本仓
-- `MybatisPlusConfig.TenantLineInnerInterceptor` 会给**每张非忽略表**注入 `tenant_id` 谓词
-- （`selectById`/`insert` 都注入）⇒ 缺该列 = 每次查询/插入 SQL 报错（同 V127 的实测）。
--
-- ## 🔴 单一 owner 声明（与 #5651 的边界）
-- 「发货明细（实发套/件/卷）」这个真值的唯一 owner = **本表**
-- （`order_shipment_items.shipped_quantity` / `unit` / `set_count` / `roll_count`）。
-- issue #5651（A4 加工单 / 销售单三联纸）只**消费**，不得另建第二份投影。
--
-- ## 停止条件（fail-closed）
--   ① `orders` 表不存在 ⇒ 迁移失败并停下（不兜底建表 —— 会造出无外键的影子表）；
--   ② 终态对账报「表缺失」/「契约列缺失」/「两列租户 RLS 策略缺失」⇒ 回滚本迁移。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116/V119/V122/V127 纪律）
--   新建库路径**不跑历史迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql`
--   已同步本文件终态（两张表 + 两条行级租户隔离策略）。只改一处 ⇒ 新建库缺表 / 存量库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V133__rollback_order_shipments.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS order_shipment_items;
-- -- DROP TABLE IF EXISTS order_shipments;
-- ```
--   **回滚是有损的**：已经发生的「谁在何时照哪张照片、发了多少」**回不来** ——
--   而那份留痕正是「少发/错发可核」的依据（丢了就再也核不了）。属**有意**。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V116/V119/V121/V122/V127 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--   两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'orders') THEN
        RAISE EXCEPTION 'order_shipments 迁移前置缺失：orders 表不存在';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 发货单（头）：服务端留痕 —— 谁 / 何时 / 哪张单 / 照片引用 / 识别结果
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS order_shipments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    order_id VARCHAR(36) NOT NULL,
    order_no VARCHAR(64),
    shipment_no VARCHAR(64) NOT NULL,
    -- 来源：worker_photo（工人拍照）/ worker（工人手工）/ admin（商家侧）
    source VARCHAR(32) NOT NULL,
    -- 照片引用（已上传图片的 URL 列表）—— JSONB 数组；缺照片 ⇒ 空数组（不编造）
    photo_refs JSONB,
    -- 识别留痕：vision 返回的**原样**字段表（含逐格 source/reason/置信度）。
    -- 只在「识别不确定 ⇒ 不预填 ⇒ 工人手输」之后仍留原样，供事后对账「当时机器说了什么」。
    recognition JSONB,
    packed_by_worker_id VARCHAR(64),
    packed_by_worker_name VARCHAR(64),
    packed_at TIMESTAMPTZ,
    shipped_by_worker_id VARCHAR(64),
    shipped_by_worker_name VARCHAR(64),
    shipped_at TIMESTAMPTZ,
    tracking_no VARCHAR(64),
    logistics_company VARCHAR(128),
    -- 幂等键（X-Client-Request-Id）：同键重放不重复记明细、状态不重复流转
    client_request_id VARCHAR(128),
    -- 撤销打包留痕（issue #5648：打包打错了可撤销，但**必须留痕 + 带理由**）
    unpacked_at TIMESTAMPTZ,
    unpacked_by_worker_id VARCHAR(64),
    unpacked_by_worker_name VARCHAR(64),
    unpack_reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted SMALLINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE order_shipments IS
    '发货单（issue #5648）：服务端留痕载体 —— 谁 / 何时 / 哪张单 / 照片引用 / 识别结果。与 order_logistics 分开：后者是物流面，本表是发货事实面。';
COMMENT ON COLUMN order_shipments.source IS
    '发货单来源：worker_photo（工人拍照识别生成）/ worker（工人手工录入）/ admin（商家侧）';
COMMENT ON COLUMN order_shipments.photo_refs IS
    '照片引用（上传后的图片 URL 列表，JSONB 数组）；无照片 ⇒ 空数组，绝不编造路径';
COMMENT ON COLUMN order_shipments.recognition IS
    '识别留痕（vision 原样字段表：逐格 value/source/reason）；识别不确定时工人手输，本列仍保留「当时机器说了什么」';
COMMENT ON COLUMN order_shipments.client_request_id IS
    '幂等键（X-Client-Request-Id）：同键重放不再记明细、不再流转状态（唯一索引见下）';
COMMENT ON COLUMN order_shipments.unpack_reason IS
    '撤销打包理由（必填）：打包是工人在车间的物理动作，撤销必须说清为什么，否则责任不可追';

CREATE UNIQUE INDEX IF NOT EXISTS uk_order_shipments_idem
    ON order_shipments (tenant_id, client_request_id)
    WHERE client_request_id IS NOT NULL AND deleted = 0;

CREATE INDEX IF NOT EXISTS idx_order_shipments_order
    ON order_shipments (tenant_id, order_id, created_at DESC);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 发货明细：**实发**套 / 件 / 卷（本单拥有这个真值，#5651 只消费）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS order_shipment_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    shipment_id VARCHAR(36) NOT NULL REFERENCES order_shipments(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL,
    -- 订单行 id：发货明细挂在**订单行**上（不是商品上）—— 同一商品两行（不同尺寸）必须分得开
    order_item_id VARCHAR(36),
    -- 商品名快照（订单行改名/删除后纸面仍可复原）
    product_name VARCHAR(255),
    -- 🔴 实发数量（与 order_items.quantity 同口径：米 / 套 / 件），**不是**下单数量
    shipped_quantity NUMERIC(10,2) NOT NULL,
    -- 计量单位：米 / 套 / 件（与订单行计价方式同口径）
    unit VARCHAR(16) NOT NULL,
    -- 实发套数（per_set 计价时 = shipped_quantity；散剪/按米时可为空 —— 缺值不填 0）
    set_count INTEGER,
    -- 实发卷数（整卷发货时用；不是整卷 ⇒ 空，绝不推算）
    roll_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted SMALLINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE order_shipment_items IS
    '发货明细（issue #5648）：这一单**实际发了多少**。真值唯一 owner = 本表；#5651（纸面）只消费。';
COMMENT ON COLUMN order_shipment_items.shipped_quantity IS
    '实发数量（米/套/件，与 order_items.quantity 同口径）—— 与「下单数量」分开，少发/错发由此可核';
COMMENT ON COLUMN order_shipment_items.unit IS
    '计量单位：米 / 套 / 件（与订单行计价方式同口径，不从订单行推算）';
COMMENT ON COLUMN order_shipment_items.set_count IS
    '实发套数；仅在按套发货时有值，其余为 NULL（缺值不填 0 —— 0 是「一件都没发」的另一个意思）';
COMMENT ON COLUMN order_shipment_items.roll_count IS
    '实发卷数；仅整卷发货时有值，其余为 NULL（禁止由米数推算卷数）';

CREATE INDEX IF NOT EXISTS idx_order_shipment_items_shipment
    ON order_shipment_items (shipment_id, id);

CREATE INDEX IF NOT EXISTS idx_order_shipment_items_order
    ON order_shipment_items (tenant_id, order_id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 行级租户隔离（与全库同构；`CREATE POLICY` 无 IF NOT EXISTS ⇒ DO 块幂等包裹）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE order_shipments ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname = 'public' AND tablename = 'order_shipments'
                     AND policyname = 'tenant_isolation_order_shipments') THEN
        CREATE POLICY tenant_isolation_order_shipments ON order_shipments
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

ALTER TABLE order_shipment_items ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname = 'public' AND tablename = 'order_shipment_items'
                     AND policyname = 'tenant_isolation_order_shipment_items') THEN
        CREATE POLICY tenant_isolation_order_shipment_items ON order_shipment_items
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 终态对账（fail-closed：缺表 / 缺契约列 / 缺策略 ⇒ 整份迁移失败）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'order_shipments') THEN
        RAISE EXCEPTION '终态对账失败：order_shipments 不存在';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'order_shipment_items') THEN
        RAISE EXCEPTION '终态对账失败：order_shipment_items 不存在';
    END IF;

    SELECT string_agg(c, ', ') INTO missing
    FROM (VALUES
        ('order_shipments.photo_refs'), ('order_shipments.recognition'),
        ('order_shipments.packed_at'), ('order_shipments.shipped_at'),
        ('order_shipments.client_request_id'), ('order_shipments.unpack_reason'),
        ('order_shipment_items.shipped_quantity'), ('order_shipment_items.unit'),
        ('order_shipment_items.set_count'), ('order_shipment_items.roll_count'),
        ('order_shipment_items.tenant_id'), ('order_shipments.tenant_id')
    ) AS t(c)
    WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.columns col
        WHERE col.table_schema = 'public'
          AND col.table_name = split_part(t.c, '.', 1)
          AND col.column_name = split_part(t.c, '.', 2));
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '终态对账失败：契约列缺失 → %', missing;
    END IF;

    SELECT string_agg(p, ', ') INTO missing
    FROM (VALUES ('order_shipments'), ('order_shipment_items')) AS t(p)
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_policies pol
        WHERE pol.schemaname = 'public' AND pol.tablename = t.p
          AND pol.policyname = 'tenant_isolation_' || t.p);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '终态对账失败：行级租户隔离策略缺失 → %', missing;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE schemaname = 'public' AND indexname = 'uk_order_shipments_idem') THEN
        RAISE EXCEPTION '终态对账失败：幂等唯一索引 uk_order_shipments_idem 缺失';
    END IF;
END $$;

COMMIT;
