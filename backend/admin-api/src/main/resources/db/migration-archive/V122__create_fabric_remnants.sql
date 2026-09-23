-- ══════════════════════════════════════════════════════════════════════════════
-- V122 — 余料成本回收（issue #5146）：**非资产**余料台账 + 小件用料尺寸表（可配参数）
--
-- ## 一句话
--   两张新表：`fabric_remnants`（**一行 = 一块实物余料**：尺寸 / 来源订单 / 来源批次 / 缸号 / 状态）
--   + `remnant_small_item_specs`（**一行 = 一个小件的用料尺寸**，企业可配）。
--
-- ## 🔴 口径：余料**不是资产**（用户裁定「这个废布不算在企业资产了」）
--   本迁移**有意不落任何计价列到余料行上**（没有 `unit_cost` / `amount` / `cost_amount`）——
--   台账只记**实物可用性**（尺寸 / 位置 / 状态），不计价、不进库存金额。
--   机械判据（`RemnantNonAssetRealDbTest`）：
--     ① 加余料登记前后 `Σ product_skus.cost_amount` 与 `Σ product_skus.stock` **逐值不变**；
--     ② 余料两表**不出现在任何库存/资产读面**（`StockBatchController` / `StockLedgerMapper` /
--        `ProductSkuMapper` 的 SQL 里零引用，静态判据 `RemnantNonAssetGuardTest`）。
--   回收金额**不是余料的价值**，而是「这块布当初已随计价口径被客户付过钱、现在被用掉多少米」的
--   **内部成本冲减量** ⇒ 它落在**用它的那张单**上（`used_by_order_no`），不是余料的资产属性。
--
-- ## 🔴 与「客户带走」（行业做法 1）的关系
--   `余料带回-布` / `余料带回-纱`（特殊选项，不计件）⇒ 余料归客户。
--   **仍然登记**（账要平：这块布离开车间这件事必须有行），但状态 = `customer_taken` ——
--   **不进"可用"池、不参与匹配、不计回收**（判据 7；红证：把它混进 available 池 ⇒ 匹配命中 ⇒ 红）。
--
-- ## 为什么是**两张表**而不是三张（回收记账不单独建表）
--   一块余料**只能被用掉一次**（用掉后状态即 `used`，尺寸不再可切）⇒ 余料 ↔ 回收是 **1:1**。
--   1:1 的关系用**同一行的列**表达（`recovered_*`）比新开一张表少一层 join、少一个「两表不一致」
--   的失效形态，且**回收额随行不可变**（改价后历史读数不变 —— 判据 6）天然成立。
--   报废同理（`scrapped_*` 列），且与回收**互斥**（由 `ck_fabric_remnant_lifecycle` 钉住）。
--   ⇒ 代价照实登记：将来若要「一块余料分多次用掉」（部分使用），本形态需扩表，不是改列。
--   **本单不做部分使用**：余料的定义就是「已经小到只能整块做一个小件」，按块用尽。
--
-- ## 余料尺寸怎么来（#5158 的排料块清单）
--   排料结果（`CuttingPlanCalculator.CuttingPlan`）逐行给出「行长度」与行内各块的「占门幅宽」，
--   两种余料都能算出矩形：
--     · `width` = **门幅余料**：行内 `Σ 占门幅宽 < 门幅` 时剩下的那条竖带
--       ⇒ `长（沿卷长）= 行长度`、`宽（门幅方向）= 门幅 − Σ 占门幅宽`；
--     · `end` = **端部余料**：行内某块比该行最长块短时，它尾部剩下的那条横带
--       ⇒ `长 = 行长度 − 该块沿卷长`、`宽 = 该块占门幅宽`。
--   两者都是「**这一行的布已经按行长度整段领下来了**」的那段里的空处 ⇒ 其米数**确实已被计价**
--   （计价口径 `M = P × 每幅长` 每幅按整门幅算，门幅余料的钱客户已经付过）。
--   尺寸口径与本仓排料器**同一套**（沿卷长 × 占门幅宽，单位米，矩形不旋转不重切）。
--
-- ## 幂等闸（`MigrationRunner` + 重跑 accrual 两条都要幂等）
--   · 迁移本身：`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` /
--     `DROP CONSTRAINT IF EXISTS` + 「不存在才 ADD」/ `COMMENT ON` 覆盖式；文末 `DO` 块两遍都成立。
--   · 业务侧：`uk_fabric_remnants_piece (tenant_id, source_processing_order_no, piece_seq)`
--     ⇒ 同一张加工单的排料结果**重复登记**撞唯一键（`piece_seq` = 排料清单里的确定序，
--     同一份排料结果两遍得到同一组序号）。
--   · 回收侧：`uk_fabric_remnants_recovery (tenant_id, used_by_order_item_id, used_by_item_key)`
--     ⇒ 同一张单的同一行明细、同一个**小件**只能消耗一块余料（不重复回收）。
--
-- ## 停止条件（fail-closed）
--   ① `tenants` / `products` / `stock_batches` 任一不存在 ⇒ 迁移失败并停下
--      （不兜底建表 —— 会造出无外键的影子表）；
--   ② 终态对账报「表缺失」/「列缺失」/「状态约束未放行某取值」/「生命周期约束缺失」/
--      「体积约束缺失」/「唯一索引缺失」/「查询索引缺失」⇒ 判据漂移或被部分回滚 ⇒ 回滚本迁移。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116/V119 纪律）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V123__rollback_fabric_remnants.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS fabric_remnants;
-- -- DROP TABLE IF EXISTS remnant_small_item_specs;
-- ```
--   **回滚是有损的**：已经发生的「哪块布被用在哪张单上、冲减了多少」**回不来**
--   （余料尺寸随排料结果产生，事后重排会随算料配置漂移 ⇒ 与本仓 #5159「落库不重算」同因）。属**有意**。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V116/V119/V121 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--   两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('tenants'), ('products'), ('stock_batches')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 前置表缺失：% —— 迁移停下（不兜底建表）', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 小件用料尺寸表（**可配参数**，用户裁定「小件用料尺寸表，可以整个参数配置，未来让企业自定义」）
--    「缺行 = 未配置」= 本仓既有口径（缺行用默认值；本参数的默认值 = **空**，不编业务数值）
--    ⇒ 未配置 ⇒ 匹配**不产生任何推荐**且读面显式说明（判据 4，不许静默）。
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS remnant_small_item_specs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 小件配置键 = **它对应的工序名**（逐字同 production_operations.name / 真值源
    -- routing.py::SPECIAL_OPTION_ROUTINGS 的 operation，如 绑带-布 / 帘头制作 / 抱枕）。
    -- 🔴 用工序名当键而不是另造一套「小件名」：工序名是本仓既有的唯一真值
    --    （特殊选项 → 工序的那张表已经在用它），另造一套就是第二份会漂移的口径。
    item_key VARCHAR(64) NOT NULL,
    -- 这一块布需要多大：沿卷长方向（米）
    length_m NUMERIC(8,2) NOT NULL,
    -- 这一块布需要多大：门幅方向（米）
    width_m NUMERIC(8,2) NOT NULL,
    note VARCHAR(255),
    operator VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);

-- 一租户一小件一行（改尺寸 ⇒ 更新该行，不新增行 ⇒ 读面不会出现「同一小件两个尺寸」的歧义）
CREATE UNIQUE INDEX IF NOT EXISTS uk_remnant_spec_item
    ON remnant_small_item_specs (tenant_id, item_key) WHERE deleted = 0;

ALTER TABLE remnant_small_item_specs DROP CONSTRAINT IF EXISTS ck_remnant_spec_size;
ALTER TABLE remnant_small_item_specs
    ADD CONSTRAINT ck_remnant_spec_size CHECK (length_m > 0 AND width_m > 0);

COMMENT ON TABLE remnant_small_item_specs IS
    '小件用料尺寸表（V122，issue #5146）：一行 = 一个小件需要的一块布有多大。**企业可配参数**；'
    '缺行 = 未配置（不编默认数值）⇒ 余料匹配不产生任何推荐且读面显式说明，不静默';
COMMENT ON COLUMN remnant_small_item_specs.item_key IS
    '小件配置键 = 该小件对应的**工序名**（逐字同 production_operations.name 与 '
    'routing.py::SPECIAL_OPTION_ROUTINGS 的 operation，如 绑带-布 / 帘头制作 / 抱枕）—— '
    '不另造「小件名」，避免第二份会漂移的口径';
COMMENT ON COLUMN remnant_small_item_specs.length_m IS '这一块布沿**卷长**方向需要的长度（米）；匹配时须 ≤ 余料 length_m';
COMMENT ON COLUMN remnant_small_item_specs.width_m IS '这一块布沿**门幅**方向需要的宽度（米）；匹配时须 ≤ 余料 width_m';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 余料台账（**非资产**：只记实物可用性，不计价、不进库存金额）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS fabric_remnants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 排料清单里这一块余料的**确定序号**（同一份排料结果两遍得到同一组序号 ⇒ 幂等闸的键之一）
    piece_seq INTEGER NOT NULL,
    -- 来源：订单 / 加工单 / 批次 / 缸号（判据「按订单、按批次、按缸号查回来」）
    source_order_no VARCHAR(32) NOT NULL,
    source_processing_order_no VARCHAR(32) NOT NULL,
    source_batch_id BIGINT REFERENCES stock_batches(id),
    source_batch_no VARCHAR(32) NOT NULL,
    -- 缸号快照（源 stock_batches.dye_lot，**随行固化**）：同缸号优先匹配防色差要靠它，
    -- 而批次行的缸号可能事后被订正 ⇒ 不 join 回批次（与 V119 的 unit_cost 快照同一条纪律）
    dye_lot VARCHAR(64),
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    -- 余料形态：width = 门幅余料（行内没占满门幅剩下的竖带）/ end = 端部余料（行内短块尾部剩下的横带）
    piece_kind VARCHAR(16) NOT NULL,
    -- 尺寸（米）：length_m = 沿**卷长**方向、width_m = 沿**门幅**方向
    length_m NUMERIC(12,2) NOT NULL,
    width_m NUMERIC(12,2) NOT NULL,
    -- 状态机：customer_taken（客户带走）/ available（可用）/ used（已用）/ scrapped（已报废）
    status VARCHAR(16) NOT NULL,
    -- ── 回收记账（status='used' 时全非空；**只**在此时非空）──
    -- 🔴 这四列记的是「这块布被**哪张单**用掉、冲减多少」—— 是**用它的那张单**的内部成本口径，
    --    不是余料的资产属性（本表**没有** unit_cost / amount 这类「余料值多少钱」的列）。
    used_by_order_no VARCHAR(32),
    used_by_order_item_id VARCHAR(36),
    used_by_item_key VARCHAR(64),
    -- 用掉米数 = 该余料沿卷长方向的长度（这一段的钱当初已随计价口径被客户付过）
    recovered_meters NUMERIC(12,2),
    -- **当时**该批次均价快照（源 stock_batches.unit_cost，NUMERIC(12,4) 与 V119 逐字同型）
    -- ⇒ 事后改批次均价**不会**改掉历史读数（判据 6）
    recovered_unit_cost NUMERIC(12,4),
    -- = recovered_meters × recovered_unit_cost（由 ck_fabric_remnant_amount 钉住，不是读面现算）。
    -- 精度 6 位 = NUMERIC(12,2) × NUMERIC(12,4) 的**精确**积的位数 ⇒ 约束可以写「逐值相等」
    -- （写 4 位会让存储时的舍入把等式打破 —— 那约束就成了永远红或永远被绕过）
    recovered_amount NUMERIC(20,6),
    recovered_at TIMESTAMP WITH TIME ZONE,
    recovered_by VARCHAR(64),
    -- ── 报废留痕（status='scrapped' 时全非空；与回收**互斥**）──
    scrap_reason VARCHAR(255),
    scrapped_at TIMESTAMP WITH TIME ZONE,
    scrapped_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);

-- 幂等闸①：同一张加工单的排料结果只能登记一次（piece_seq 由排料清单的确定序给出）
CREATE UNIQUE INDEX IF NOT EXISTS uk_fabric_remnants_piece
    ON fabric_remnants (tenant_id, source_processing_order_no, piece_seq) WHERE deleted = 0;

-- 幂等闸②：同一张单的同一行明细、同一个**小件**只能消耗一块余料（不重复回收）
CREATE UNIQUE INDEX IF NOT EXISTS uk_fabric_remnants_recovery
    ON fabric_remnants (tenant_id, used_by_order_item_id, used_by_item_key)
    WHERE deleted = 0 AND status = 'used';

-- 查询维度：状态池（匹配只扫 available）/ 批次 / 缸号 / 来源订单
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_status
    ON fabric_remnants (tenant_id, status, id);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_batch
    ON fabric_remnants (tenant_id, source_batch_no, id);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_dye_lot
    ON fabric_remnants (tenant_id, dye_lot);
CREATE INDEX IF NOT EXISTS idx_fabric_remnants_tenant_order
    ON fabric_remnants (tenant_id, source_order_no, id);

-- 状态取值集合（同 V111/V116 对 reason 的纪律：写进约束，不只写在 Java 常量里）
ALTER TABLE fabric_remnants DROP CONSTRAINT IF EXISTS ck_fabric_remnant_status;
ALTER TABLE fabric_remnants
    ADD CONSTRAINT ck_fabric_remnant_status
    CHECK (status IN ('customer_taken', 'available', 'used', 'scrapped'));

ALTER TABLE fabric_remnants DROP CONSTRAINT IF EXISTS ck_fabric_remnant_piece_kind;
ALTER TABLE fabric_remnants
    ADD CONSTRAINT ck_fabric_remnant_piece_kind
    CHECK (piece_kind IN ('width', 'end'));

-- 尺寸必须为正（0 面积的行不是余料，是脏数据）
ALTER TABLE fabric_remnants DROP CONSTRAINT IF EXISTS ck_fabric_remnant_size;
ALTER TABLE fabric_remnants
    ADD CONSTRAINT ck_fabric_remnant_size CHECK (length_m > 0 AND width_m > 0);

-- 回收额 = 用掉米数 × 当时均价（**账实一致**的算术判据：写错任一列当场失败，而不是读面各算各的）
ALTER TABLE fabric_remnants DROP CONSTRAINT IF EXISTS ck_fabric_remnant_amount;
ALTER TABLE fabric_remnants
    ADD CONSTRAINT ck_fabric_remnant_amount
    CHECK (recovered_amount IS NULL
           OR (recovered_meters IS NOT NULL AND recovered_unit_cost IS NOT NULL
               AND recovered_meters > 0 AND recovered_unit_cost >= 0
               AND recovered_amount = recovered_meters * recovered_unit_cost));

-- 生命周期一致性（**判据 8「报废留痕」的机械落点**）：状态与留痕列必须互相解释得通
--   · used      ⇒ 回收五列 + 用它的那张单全非空
--   · scrapped  ⇒ 报废三列全非空
--   · available / customer_taken ⇒ 回收与报废列**全空**（没发生过的事不许有痕迹）
--   · 回收与报废**互斥**（同一块布不可能既被用掉又报废）
ALTER TABLE fabric_remnants DROP CONSTRAINT IF EXISTS ck_fabric_remnant_lifecycle;
ALTER TABLE fabric_remnants
    ADD CONSTRAINT ck_fabric_remnant_lifecycle
    CHECK (
        (status = 'used'
            AND used_by_order_no IS NOT NULL
            AND recovered_meters IS NOT NULL AND recovered_unit_cost IS NOT NULL
            AND recovered_amount IS NOT NULL AND recovered_at IS NOT NULL
            AND scrapped_at IS NULL AND scrap_reason IS NULL)
        OR (status = 'scrapped'
            AND scrap_reason IS NOT NULL AND scrapped_at IS NOT NULL
            AND recovered_meters IS NULL AND recovered_unit_cost IS NULL
            AND recovered_amount IS NULL AND recovered_at IS NULL
            AND used_by_order_no IS NULL)
        OR (status IN ('available', 'customer_taken')
            AND recovered_meters IS NULL AND recovered_unit_cost IS NULL
            AND recovered_amount IS NULL AND recovered_at IS NULL
            AND used_by_order_no IS NULL
            AND scrap_reason IS NULL AND scrapped_at IS NULL)
    );

COMMENT ON TABLE fabric_remnants IS
    '余料台账（V122，issue #5146）—— **非资产**：一行 = 一块实物余料，只记实物可用性'
    '（尺寸 / 来源订单 / 来源批次 / 缸号 / 状态），**不计价、不进库存金额**（本表没有任何「余料值多少钱」的列）。'
    '余料 = 门幅余料（piece_kind=width）+ 端部余料（piece_kind=end），随排料/派工结果自动产生。'
    '状态机：customer_taken 客户带走 / available 可用 / used 已用 / scrapped 已报废';
COMMENT ON COLUMN fabric_remnants.piece_seq IS
    '排料清单里这一块余料的**确定序号**（同一份排料结果两遍得到同一组序号）—— '
    '幂等闸 uk_fabric_remnants_piece 的键之一：同一张加工单重复登记撞唯一键';
COMMENT ON COLUMN fabric_remnants.dye_lot IS
    '缸号**快照**（源 stock_batches.dye_lot）—— 同缸号优先匹配防色差靠它；'
    '不 join 回批次（批次行的缸号可能事后被订正，与 V119 的 unit_cost 快照同一条纪律）';
COMMENT ON COLUMN fabric_remnants.length_m IS '余料沿**卷长**方向的长度（米）= 这一块被领下来时算的米数方向';
COMMENT ON COLUMN fabric_remnants.width_m IS '余料沿**门幅**方向可用的宽度（米）';
COMMENT ON COLUMN fabric_remnants.status IS
    '状态机：customer_taken 客户带走（余料带回-布/-纱）**不进可用池、不参与匹配、不计回收** / '
    'available 可用（匹配只在它里面找）/ used 已用（回收记账落在这里）/ scrapped 已报废（留痕）';
COMMENT ON COLUMN fabric_remnants.recovered_meters IS
    '用掉米数 = 该余料沿卷长方向的长度（这一段的钱当初已随计价口径 M = P × 每幅长 被客户付过 ⇒ '
    '回收不是向客户再要一次钱，是把已计过价的东西从「丢掉」改成「用起来」）';
COMMENT ON COLUMN fabric_remnants.recovered_unit_cost IS
    '**当时**该批次均价（元/米）快照（源 stock_batches.unit_cost，与 V119 逐字同型）。'
    '回收额随行快照 ⇒ 事后改批次均价**不会**改掉历史读数（判据 6）';
COMMENT ON COLUMN fabric_remnants.recovered_amount IS
    '= recovered_meters × recovered_unit_cost（由 ck_fabric_remnant_amount 钉住）。'
    '它**只进入内部成本口径**（冲减 used_by_order_no 那张单的面料成本），'
    '**不进**对客售价 / 加工费 / 成品尺寸（判据 2「不损失客户」）';
COMMENT ON COLUMN fabric_remnants.used_by_item_key IS
    '这块余料被用在哪个小件上（= remnant_small_item_specs.item_key = 工序名）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n              INTEGER;
    missing        TEXT;
    constraint_def TEXT;
BEGIN
    -- ① 两张表必须在
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('fabric_remnants'), ('remnant_small_item_specs')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：表缺失 % —— 回滚本迁移', missing;
    END IF;

    -- ② fabric_remnants 的列必须在（缺一列即功能静默缺失）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('id'), ('tenant_id'), ('piece_seq'), ('source_order_no'),
                   ('source_processing_order_no'), ('source_batch_id'), ('source_batch_no'),
                   ('dye_lot'), ('product_id'), ('sku_id'), ('sku_code'), ('piece_kind'),
                   ('length_m'), ('width_m'), ('status'),
                   ('used_by_order_no'), ('used_by_order_item_id'), ('used_by_item_key'),
                   ('recovered_meters'), ('recovered_unit_cost'), ('recovered_amount'),
                   ('recovered_at'), ('recovered_by'),
                   ('scrap_reason'), ('scrapped_at'), ('scrapped_by'),
                   ('created_at'), ('deleted')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'fabric_remnants'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：fabric_remnants 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ③ 小件尺寸表的列必须在
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('id'), ('tenant_id'), ('item_key'), ('length_m'), ('width_m'),
                   ('note'), ('operator'), ('created_at'), ('updated_at'), ('deleted')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'remnant_small_item_specs'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：remnant_small_item_specs 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ④ 状态约束必须**同时放行四个取值**（漏一个 ⇒ 该状态永远落不了库，且没有任何东西会变红）
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_fabric_remnant_status' AND conrelid = 'fabric_remnants'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：ck_fabric_remnant_status 不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%customer_taken%' OR constraint_def NOT LIKE '%available%'
       OR constraint_def NOT LIKE '%used%' OR constraint_def NOT LIKE '%scrapped%' THEN
        RAISE EXCEPTION 'V122 终态对账失败：状态约束未同时放行四个取值，实际 = % —— 回滚本迁移',
            constraint_def;
    END IF;

    -- ⑤ 生命周期一致性约束必须在，且必须**同时**钉住回收与报废两侧（少一侧 ⇒ 账实不一致能落库）
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_fabric_remnant_lifecycle' AND conrelid = 'fabric_remnants'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：ck_fabric_remnant_lifecycle 不存在 '
            '（报废不留痕 / 回收与报废可同时有 —— 账实不一致能静默落库）—— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%scrap_reason%' OR constraint_def NOT LIKE '%recovered_amount%' THEN
        RAISE EXCEPTION 'V122 终态对账失败：生命周期约束未同时钉住报废与回收两侧，实际 = %'
            ' —— 回滚本迁移', constraint_def;
    END IF;

    -- ⑥ 回收额算术约束必须在（写错列 ⇒ 当场失败，而不是读面各算各的）
    SELECT count(*) INTO n
      FROM pg_constraint
     WHERE conname = 'ck_fabric_remnant_amount' AND conrelid = 'fabric_remnants'::regclass;
    IF n = 0 THEN
        RAISE EXCEPTION 'V122 终态对账失败：ck_fabric_remnant_amount 不存在 —— 回滚本迁移';
    END IF;

    -- ⑦ 三个唯一/幂等索引必须在（漏了 ⇒ 重复登记 / 重复回收静默发生）
    SELECT string_agg(i, ', ') INTO missing
      FROM (VALUES ('uk_fabric_remnants_piece'), ('uk_fabric_remnants_recovery'),
                   ('uk_remnant_spec_item')) AS v(i)
     WHERE NOT EXISTS (SELECT 1 FROM pg_indexes
                        WHERE schemaname = 'public' AND indexname = v.i);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：唯一索引缺失 % —— 重复登记 / 重复回收不会被拦住 '
            '—— 回滚本迁移', missing;
    END IF;

    -- ⑧ 查询索引必须在（判据「按状态池 / 按批次 / 按缸号 / 按订单查回来」）
    SELECT string_agg(i, ', ') INTO missing
      FROM (VALUES ('idx_fabric_remnants_tenant_status'), ('idx_fabric_remnants_tenant_batch'),
                   ('idx_fabric_remnants_tenant_dye_lot'), ('idx_fabric_remnants_tenant_order')) AS v(i)
     WHERE NOT EXISTS (SELECT 1 FROM pg_indexes
                        WHERE schemaname = 'public' AND indexname = v.i);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V122 终态对账失败：查询索引缺失 % —— 回滚本迁移', missing;
    END IF;

    -- ⑨ 非资产的自证：余料台账**不得**出现任何计价列名（有人「顺手」加一列 unit_cost 就红）
    SELECT count(*) INTO n
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'fabric_remnants'
       AND column_name IN ('unit_cost', 'amount', 'cost_amount', 'avg_cost', 'price');
    IF n <> 0 THEN
        RAISE EXCEPTION 'V122 终态对账失败：fabric_remnants 出现计价列（% 个）—— 余料不是资产，'
            '不进库存金额（用户裁定「这个废布不算在企业资产了」）—— 回滚本迁移', n;
    END IF;
END $$;

COMMIT;
