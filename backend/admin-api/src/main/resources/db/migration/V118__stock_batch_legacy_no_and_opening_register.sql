-- 批次建账/初始化入口的缺口列（issue #5153）—— 旧系统批次号的**独立落点**
--
-- ## 一句话（本迁移只加两列 + 一个查询索引，不动任何既有列的口径）
--   ① `stock_batches.legacy_batch_no` —— **旧系统批次号**的落点。现有 `batch_no` 是**服务端生成**的
--      系统号（`PC-yyyyMMdd-NNNN`），V111 明令**不得互相冒充**（`dye_lot` 同理：那是**供应商缸号**，
--      又是另一个外部事实）⇒ 旧号必须有**自己的列**，否则只能挤进 `batch_no`（= 冒充）或
--      `dye_lot`（= 把批次号当缸号，追溯断链）；
--   ② `inbound_order_items.legacy_batch_no` —— 期初单**明细行**上的同一事实。
--      为什么明细行也要一列：**建单与过账是两次请求**（V111 的状态机：草稿不动库存、过账才生成批次）。
--      `post()` 是从库里**回读明细行**再写批次行的 ⇒ 明细行上不落这一列，建单时填的旧号
--      **在过账那一刻就丢了**（不是「可以不存」，是「存不下」）。
--   ③ `idx_stock_batches_tenant_legacy_no` —— 旧号的查询面（「这个旧号对应哪个批次/还有多少米」），
--      与 V111 的 `idx_stock_batches_tenant_dye_lot` 同族（按外部标识过滤）。
--
-- ## 复用了哪些既有件（**本迁移不新造**，这是最少代码的机械证据）
--   · **幂等键**：`inbound_orders.import_run_id` + 部分唯一索引 `uk_inbound_orders_tenant_import_run`
--     —— V117（issue #5148）已落好，本单**直接用**（同一份期初导入重跑 = 不建第二张单）；
--   · **来源**：`inbound_orders.source ∈ {purchase, opening}` + `ck_inbound_orders_source`
--     —— V117 已落好，本单**不改它的口径**（基线冻结点 = `posted_at` + `source='opening'`）；
--   · **精度/归一**：`StockQuantity.requireOneDecimal` 一族（V115/#5063）—— 本迁移**不引入任何
--     取整/进位列或默认值**，精度语义仍由应用层一处定夺。
--   ⇒ 本单**没有**新增幂等键、没有新增来源枚举、没有新增精度助手。
--
-- ## 🔴 两条实现禁令（#5149 §3.6.2 / §3.6.3 已写成显式禁令；本迁移的存在使它们**可被违反**）
--   ① **归一不得复用 `toStockScaleByCeiling`**：那是**订单侧**口径（向上进位，模拟裁床用料）。
--      期初/批次余量属**库存类输入** ⇒ 用它每条最多虚增 `+0.099m` = **系统性虚增资产**。
--      本迁移的 `quantity` 列语义**一字未改**（仍是 V115 的 `NUMERIC(12,1)`，仍按**登记值**落库）。
--   ② **导入必须走服务层**：见下面「为什么列精度不是闸门」——本迁移**不新增任何 DB 层精度校验**，
--      因为那会给出「DB 兜住了」的错觉，而真正兜住的只有应用层。
--
-- ## 为什么列精度不是闸门（**这是本迁移有意不做的事**，理由带实测）
--   `NUMERIC(12,1)` 对超 scale 的写入**按四舍五入落库且不报错**（`2.75` → `2.8`；V115 与
--   `StockQuantity` javadoc 都逐字登记过）。⇒ 想靠「加个 CHECK / 改列精度」来拦 2 位小数是
--   **行不通**的：CHECK 只能看到**已经落进来的 2.8**，看不到调用方原本传的 2.75。
--   fail-closed 只能在应用层（`StockQuantity.requireOneDecimal`）—— 本迁移**不加 CHECK 约束**，
--   不制造「DB 也会拦」的错觉。（本单的真库判据里有这一条的**可证伪**判据：
--   `tests/unit_ci_workflows/test_inbound_opening_register.py` 的
--   `test_decimal_precision_is_the_database_silent_rounding_trap`。）
--
-- ## 为什么**不**给 `legacy_batch_no` 加「不得形如系统号」的 CHECK 约束（如实登记取舍）
--   系统号形态是 `PC-yyyyMMdd-NNNN`（V111），看起来可以写成
--   `CHECK (legacy_batch_no NOT LIKE 'PC-%')`。**有意不加**：旧系统的号段**未知**（本单的前提就是
--   「旧系统能否按批次导出未取证」），一个形如 `PC-...` 的合法旧号会被这条约束**当场 23514 拒收**
--   —— 那是拿「防冒充」当理由去**挡真实数据**（用户裁定「不能损失客户」同族）。防冒充的判据放在
--   语义层：旧号只允许在 `source='opening'` 的期初单上填（应用层一处校验），
--   且**两列永不互相赋值**（`batch_no` 由服务端生成、`legacy_batch_no` 只从请求透传）。
--
-- ## ⚠️ 有损项（如实登记，不粉饰）
--   期初单明细行的 `quantity` 口径 = **登记时点的实物剩余量**，**不是**旧系统的原始入库量。
--   ⇒ 代价是**旧系统的原始入库量与入库日期有损**：本单不伪造一段不存在的消耗历史
--   （要用消耗台账去凑出「原始量 → 剩余量」的差额，就得凭空造出「什么时候、被哪张派工单用掉多少」
--   —— 那是**伪造事实账**，比丢两个字段坏得多）。旧号与缸号是**外部事实**，一律如实落列。
--   ⇒ 若日后需要原始入库量与日期，只能另开单据/另加列**显式**登记，不得从 `quantity` 反推。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V119__rollback_stock_batch_legacy_no.sql（本单只登记，不落码）
-- -- DROP INDEX IF EXISTS idx_stock_batches_tenant_legacy_no;
-- -- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS legacy_batch_no;
-- -- ALTER TABLE stock_batches DROP COLUMN IF EXISTS legacy_batch_no;
-- ```
-- **回滚是有损的**：旧系统批次号**回不来**（列被丢弃）⇒ 批次与旧系统的追溯链断掉，
-- 且此后重新导入时无法判「这个旧号是不是已经登记过」。属**有意**（回滚一个已登记的外部事实
-- 就不该静默复原）。注意回滚**不影响** `batch_no` / `quantity` / 库存 —— 那些列本迁移一字未动。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V115/V116/V117 纪律）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `tenants` / `inbound_orders` / `inbound_order_items` / `stock_batches` 任一不存在
--      ⇒ 迁移失败并停下（不 CREATE TABLE 兜底 —— 会造出无外键/无索引的影子表）；
--   ② 终态对账报「列缺失」/「列类型不符」/「查询索引缺失」⇒ 写语句判据漂移或被部分回滚
--      ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V115/V116/V117 的实测口径）
--   `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒
--   留下**半完成态**。两条执行路径（`MigrationRunner` 的 `jdbc.execute(整份文件)` 与 `psql -f`）
--   必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('tenants'), ('inbound_orders'), ('inbound_order_items'), ('stock_batches')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V118 前置表缺失：% —— 不兜底建表（会造出无外键/无索引的影子表），迁移停下', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 旧系统批次号：批次行 + 明细行各一列（幂等：IF NOT EXISTS）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE stock_batches
    ADD COLUMN IF NOT EXISTS legacy_batch_no VARCHAR(64);

ALTER TABLE inbound_order_items
    ADD COLUMN IF NOT EXISTS legacy_batch_no VARCHAR(64);

COMMENT ON COLUMN stock_batches.legacy_batch_no IS
    '旧系统批次号（V118，issue #5153）：期初建账时从旧系统带来的批次标识，**外部事实**。与 batch_no（服务端生成的系统号 PC-yyyyMMdd-NNNN）是**两列两义**，V111 明令不得互相冒充；与 dye_lot（供应商缸号）亦不同义。NULL = 非期初来源或旧系统无此号。允许在 source=''opening'' 的期初单上填写（应用层校验），采购入库不得填';

COMMENT ON COLUMN inbound_order_items.legacy_batch_no IS
    '本行登记的旧系统批次号（V118，issue #5153）：**过账时透传到 stock_batches.legacy_batch_no**。为什么明细行也要一列：建单（草稿）与过账是两次请求，post() 从库里回读明细行再写批次行 ⇒ 明细行不落这一列，建单时填的旧号在过账那一刻就丢了。仅 source=''opening'' 的期初单可填（应用层一处校验）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 旧号的查询面（同族先例 idx_stock_batches_tenant_dye_lot，V111）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_stock_batches_tenant_legacy_no
    ON stock_batches (tenant_id, legacy_batch_no);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n       INTEGER;
    missing TEXT;
BEGIN
    -- ① 两列必须在（列缺失 ⇒ 旧系统批次号无处可落，只能挤进 batch_no / dye_lot = 冒充）
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('stock_batches'), ('inbound_order_items')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = v.t
                          AND column_name = 'legacy_batch_no');
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V118 终态对账失败：% 缺列 legacy_batch_no —— 回滚本迁移', missing;
    END IF;

    -- ② 类型/长度必须一致（`VARCHAR(64)`）：两列不同宽会让「透传」在过账时被截断
    SELECT count(*) INTO n
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name IN ('stock_batches', 'inbound_order_items')
       AND column_name = 'legacy_batch_no'
       AND data_type = 'character varying'
       AND character_maximum_length = 64;
    IF n <> 2 THEN
        RAISE EXCEPTION 'V118 终态对账失败：legacy_batch_no 不是两处 VARCHAR(64)（实际命中 % 处）—— 回滚本迁移', n;
    END IF;

    -- ③ 查询索引必须在（缺它 ⇒ 按旧号找批次退化成全表扫；与 idx_stock_batches_tenant_dye_lot 同族）
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'stock_batches'
       AND indexname = 'idx_stock_batches_tenant_legacy_no'
       AND indexdef LIKE '%(tenant_id, legacy_batch_no)%';
    IF n = 0 THEN
        RAISE EXCEPTION 'V118 终态对账失败：idx_stock_batches_tenant_legacy_no 缺失或形态不符 —— 回滚本迁移';
    END IF;

    -- ④ 本迁移**不得**动到既有列的口径（`quantity` 仍是 NUMERIC(12,1) —— 精度语义只由应用层定夺）
    SELECT count(*) INTO n
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'stock_batches'
       AND column_name = 'quantity'
       AND data_type = 'numeric' AND numeric_precision = 12 AND numeric_scale = 1;
    IF n = 0 THEN
        RAISE EXCEPTION 'V118 终态对账失败：stock_batches.quantity 不再是 NUMERIC(12,1)（精度口径被动过）—— 回滚本迁移';
    END IF;
END $$;

COMMIT;
