-- 入库标签短码与打印留痕（issue #5052 P2；设计真值源 docs/design/inbound-photo-and-label.md §7.1 / §7.3）
--
-- ## 一句话
--   工人拍照入库**过账**后，每一行（= 一个 SKU = 一个批次）出一张 50×30mm 标签；
--   标签上的码 = `https://app.migaozn.com/i/<8 位短码>`（§7.1 **一次定死**：码一旦打印就是 URL，
--   换域名 / 改路径会让已打印的码全部失效）⇒ 需要「入库侧自己的码表 + 打印计数 + 撤销位」。
--
-- ## 为什么不复用 processing_set_part_tokens（#5052 边界逐字：「照其范式、不复用其表」）
--   `/s/`（工人报工短链，302 → `/w/?t=<token>`）与 `/i/`（入库标签）是**两个码空间**：
--   语义不同、扫出来去哪一页不同，混用会把「扫标签」变成「进报工页」。
--   本表**照**其范式（8 位 Crockford Base32 / 部分唯一索引 / 原子自增计数），**不复用其表**。
--   ⇒ 本表**没有** token 列：`/i/` 不需要「换发凭据」这一跳，它的载荷就是**这张标签指向哪一行单据**。
--
-- ## 撤销语义（§7.3「撤销标签 ⇒ 短码置 NULL ⇒ 扫码 410」）
--   撤销 = `short_code` 置 NULL，同时把原码原样留档到 `revoked_code`
--   ⇒ ① 满足「短码置 NULL」的字面口径；② 扫码仍能**分辨**「这张纸已作废（410）」与
--   「没这个码（404）」—— 只置 NULL 会让撤销被读成「不存在」（同款教训见
--   `ProcessingSetPartTokenMapper.selectByShortCode` 的注释：静默回落成 404 就是把撤销说成「没这个码」）。
--   `ck_inbound_labels_code_exactly_one` 把「两者恰有一个非空」钉成**结构不变量**（不靠调用方记得）；
--   `uk_inbound_labels_code` 建在**有效码**（`COALESCE(short_code, revoked_code)`）上
--   ⇒ 一条索引同时兜住三件事：活码全局唯一、留档码全局唯一、**两者之间也不许撞**
--   （= 已撤销的码永不复发，老纸不会指到新单上）。⚠️ 为什么不是两条分列索引：PG 里
--   `NULL` 从不与 `NULL` 冲突 ⇒ 「short_code 唯一」那条对**撤销后**的码（在 revoked_code 列）
--   没有任何约束力，新标签可以把同一个码再发一次（本包真库判据实测抓到过这一形态）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 建表 / 索引 / 约束全带 IF NOT EXISTS 或 pg_constraint 判据守卫；
--   · 本文件**不写任何数据行** ⇒ 第二遍结果与第一遍相同。
--
-- ## 停止条件（fail-closed，见文末 DO 块）
--   表在 / 三个部分唯一索引在 / 两条 CHECK 在。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   DROP TABLE IF EXISTS inbound_labels;
--   ⚠️ 回滚会让**已打印的标签全部失效**（扫 `/i/<码>` ⇒ 404）⇒ 只在「标签从未印出」的环境可回滚。

BEGIN;

CREATE TABLE IF NOT EXISTS inbound_labels (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id),
    inbound_item_id BIGINT NOT NULL,                 -- 入库单明细行（一行 = 一个 SKU = 一个批次 = 一张标签）
    -- 当前**有效**短码：8 位 Crockford Base32（去掉 I/L/O/U，人可读可抄）。撤销 ⇒ 置 NULL（§7.3 逐字）
    short_code CHAR(8),
    -- 撤销那一刻留档的原码：保证撤销后 `/i/<码>` 仍能判 **410**（而不是 404「没这个码」）。
    -- 与 short_code 恰有一个非空（见 ck_inbound_labels_code_exactly_one）
    revoked_code CHAR(8),
    -- 打印次数：**原子自增**（COALESCE(print_count,0)+1），多人同时打印不丢计数；重打同样计数（§7.3）
    print_count INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(64),
    revoked_at TIMESTAMP WITH TIME ZONE,
    revoked_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,
    -- 活码与留档码**恰有一个**非空（撤销 = 前者置 NULL + 后者留档）
    CONSTRAINT ck_inbound_labels_code_exactly_one
        CHECK ((short_code IS NULL) <> (revoked_code IS NULL)),
    -- 码形状由 DB 兜底：字母表外任何一个字符（尤其 I/L/O/U）都写不进来 —— 生成面写错也进不了库
    CONSTRAINT ck_inbound_labels_code_shape
        CHECK ((short_code IS NULL OR short_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$')
           AND (revoked_code IS NULL OR revoked_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$'))
);

-- 码**全局唯一**（`/i/<短码>` 那一跳没有租户上下文 ⇒ 跨租户也必须唯一，照 uk_set_part_tokens_short_code 范式）：
-- 建在「有效码」= COALESCE(short_code, revoked_code) 上（CHECK 保证恰有一个非空）
-- ⇒ 活码、留档码、以及两者的**交叉**都在同一条唯一约束下 ⇒ 已撤销的码永不复发
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_labels_code
    ON inbound_labels (COALESCE(short_code, revoked_code))
    WHERE deleted = 0;
-- 一行一标签（重复请求复用同一短码，不换码 —— 已打印的纸不作废，照 uk_set_part_tokens_part 范式）
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_labels_item
    ON inbound_labels (tenant_id, inbound_item_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_inbound_labels_order ON inbound_labels (inbound_order_id);

COMMENT ON TABLE inbound_labels IS
    '入库标签（V133，issue #5052 P2）：一行 = 一个入库单明细行 = 一张 50×30mm 标签。短码 = 8 位 Crockford Base32、随机、全局唯一；撤销 = short_code 置 NULL（原码留档 revoked_code）⇒ 扫码 410；print_count 原子自增（设备侧打印前必须先调 POST /api/worker/inbound/labels/{短码}/print）';
COMMENT ON COLUMN inbound_labels.short_code IS
    '当前有效短码（印刷品写 https://app.migaozn.com/i/<短码>）。撤销 ⇒ 置 NULL（§7.3），原码留档到 revoked_code ⇒ 扫码仍判 410 而不是 404';
COMMENT ON COLUMN inbound_labels.revoked_code IS
    '撤销时留档的原短码：撤销后仍能分辨「已作废（410）」与「不存在（404）」；与 short_code 一起受 uk_inbound_labels_code（有效码唯一）约束 ⇒ 已撤销的码永不复发';
COMMENT ON COLUMN inbound_labels.print_count IS
    '打印次数（原子自增 COALESCE(print_count,0)+1；多人同时打印不丢计数；重打同样计数）';

-- 停止条件（fail-closed）：迁移"跑了"不等于"跑对了" —— 缺一个索引就等于码空间没有兜底
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = current_schema() AND table_name = 'inbound_labels') THEN
        RAISE EXCEPTION 'inbound_labels 表未建立 —— 入库标签短码无从落库（/i/<短码> 会恒 404）';
    END IF;
    IF (SELECT count(*) FROM pg_indexes
         WHERE schemaname = current_schema() AND tablename = 'inbound_labels'
           AND indexname IN ('uk_inbound_labels_code', 'uk_inbound_labels_item')) <> 2 THEN
        RAISE EXCEPTION 'inbound_labels 的部分唯一索引未齐 —— 码空间可能撞码 / 一行出两张标签';
    END IF;
    IF (SELECT count(*) FROM pg_constraint
         WHERE conname IN ('ck_inbound_labels_code_exactly_one', 'ck_inbound_labels_code_shape')) <> 2 THEN
        RAISE EXCEPTION 'inbound_labels 的两条 CHECK 未齐 —— 撤销语义与码形状会退化';
    END IF;
END $$;

COMMIT;
