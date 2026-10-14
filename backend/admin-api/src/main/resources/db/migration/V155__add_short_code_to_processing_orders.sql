-- V155 — 加工单纸面右上角那张码的**稳定短码**（加工单级）：加一列 + 一条部分唯一索引（issue #6867 / B1）
--
-- ## 一句话
-- `processing_orders` 加一列 `short_code CHAR(8)` + 部分唯一索引
-- `uk_processing_orders_short_code (short_code) WHERE deleted = 0 AND short_code IS NOT NULL`。
-- 印刷品写 `{稳定域名}/o/{短码}`，服务端 302 换回 `/w/?t=<qr_token>`（那一跳是 B2 的活）。
--
-- ## 为什么是**加一列**而不是新建 `processing_order_short_links` 表
-- 设计 `docs/design/worker-h5-scan-and-report.md` §11.4 已逐条比过（本迁移只落它的结论）：
-- ① `qr_token` 是**同一张表、同类列**（`uk_processing_orders_qr_token` 已在）⇒ 短码逐字照抄它；
-- ② 分配点（`ensureQrToken`）与读面（`selectActiveByOrderId`）**本来就拿到 `po`** ⇒ 零新增查询；
-- ③ 撤销与 `qr_token` **同表同行** ⇒ 「这张纸还能用吗」只有**一处**状态，不存在两处要同步；
-- ④ 一个订单至多一张活跃加工单（既有 `uk_processing_orders_active`）⇒ **列级唯一即一单一码**。
--
-- ## 码空间归属（设计 §11.6 裁定：新开 `/o/`，与 `/s/` 的部位码互不命中）
-- 三重互斥：① 前缀不同（`/o/` vs `/s/`）；② 承载表不同（`processing_orders` vs
-- `processing_set_part_tokens`）；③ 各自的部分唯一索引。⇒ **两边的短码空间可以重叠而不冲突**
-- （同一个 8 位串在两张表里各指各的，路径段把它分开）。
--
-- ## 撤销语义（逐字复用 §1.3.1 / #4946，**本迁移不改它**）
-- 撤销 = `qr_token` 置 NULL（**不换新 token、不碰 `short_code`**）⇒ `/o/{短码}` 410 Gone。
-- 已打印的纸因此**不作废** —— 这正是「把稳定性放在服务端」的全部意义（换域名 / 改路径段都不废纸）。
-- 本迁移**只建列与索引**：`revokeQrToken` 那条既有 UPDATE 一字不动（多维索引不参与撤销）。
--
-- ## 存量行**不回填**（与 V99 的 `processing_set_part_tokens.short_code` 同款）
-- `NULL` = 尚未分配 ⇒ 读面给 `null`（**不编造**）；补码路径 = 实例化 / 重新发码那条链
-- （`ProductionService.ensureShortCode`，`AND short_code IS NULL` 的条件更新 ⇒ 幂等、
-- **已有短码的行一字不动**）。RANDOM 短码不可枚举 ⇒ 也不该在迁移里批量生成（在 DB 里造码
-- 会绕开 `WorkerShortLinkService.allocateUnique` 的查重，等于第二份分配器）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS` ⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）
--
-- 下面每一条以 `-- -- ` 开头 = **真的 SQL**（顺序即安全顺序）：
-- 先摘索引（`DROP COLUMN` 会连带删索引，但显式写出来让回滚路径逐句可读），再删列。
-- ⚠️ **有损**（如实登记）：`short_code` 的取值回不来（随机、不可重算）⇒ 已经打印出去的纸
-- 在回滚后那一段路径失效（本单 B1 还没接线 `/o/` 的 302，实际影响面要等 B2 落地才成立）。
-- 要保留短码就不要回滚，改往前修。
--
-- -- DROP INDEX IF EXISTS uk_processing_orders_short_code;
-- -- ALTER TABLE processing_orders DROP COLUMN IF EXISTS short_code;

BEGIN;

-- ① 加工单级人可读短码（NULL = 尚未分配）
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS short_code CHAR(8);

COMMENT ON COLUMN processing_orders.short_code IS
    '加工单级人可读短码（V155，issue #6867）：8 位 Crockford Base32（0-9 + A-Z 去掉 I/L/O/U），随机、**跨租户全局唯一**。印刷品写 https://<稳定域名>/o/<短码>，服务端 302 换回 /w/?t=<qr_token>（同一张纸的两种表示）。NULL = 尚未分配（存量行；补码只补 NULL，已有值一字不动）。与 processing_orders.qr_token 的关系：短码 = 「哪一张纸」（不变），token = 「这张纸当前有效吗」（可撤销 ⇒ 置 NULL）';

-- ② 短码跨租户全局唯一（部分唯一索引，与 uk_processing_orders_qr_token 逐字同款）
--    跨租户是**必须**的：/o/{短码} 是公开入口（无 JWT ⇒ 无租户上下文），租户由短码本身解出。
--    谓词 deleted = 0 AND short_code IS NOT NULL ⇒ 软删行与未分配行都不占位（不阻塞后续分配）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_short_code
    ON processing_orders (short_code)
    WHERE deleted = 0 AND short_code IS NOT NULL;

-- ③ 终态对账：写错列名 / 漏建索引 / 谓词写漏必须**当场停**，
--    而不是留一个「看着在、其实没钉住」的迁移（本仓迁移写错了不会重跑 ⇒ 静态判据是唯一出口）
DO $$
DECLARE
    column_type TEXT;
    index_def TEXT;
BEGIN
    SELECT data_type INTO column_type
      FROM information_schema.columns
     WHERE table_name = 'processing_orders' AND column_name = 'short_code';
    IF column_type IS NULL THEN
        RAISE EXCEPTION 'V155 终态对账失败：processing_orders.short_code 列不存在 —— 回滚本迁移';
    END IF;

    SELECT indexdef INTO index_def FROM pg_indexes
     WHERE indexname = 'uk_processing_orders_short_code'
       AND tablename = 'processing_orders';
    IF index_def IS NULL THEN
        RAISE EXCEPTION 'V155 终态对账失败：uk_processing_orders_short_code 不存在 —— 回滚本迁移';
    END IF;
    IF index_def NOT LIKE '%UNIQUE%' THEN
        RAISE EXCEPTION 'V155 终态对账失败：uk_processing_orders_short_code 不是唯一索引（实际 = %）'
            ' —— 回滚本迁移', index_def;
    END IF;
    -- 谓词两条都要在：漏 deleted = 0 ⇒ 软删行占位；漏 short_code IS NOT NULL ⇒ 一堆 NULL 互相不冲突、
    -- 索引看着在但**对未分配行零约束力**（真库判据抓到过这一形态，见 InboundLabelMigrationTest 的同类注记）
    IF index_def NOT LIKE '%deleted = 0%' OR index_def NOT LIKE '%short_code IS NOT NULL%' THEN
        RAISE EXCEPTION 'V155 终态对账失败：部分唯一索引谓词不完整（实际 = %）—— 回滚本迁移', index_def;
    END IF;
END $$;

COMMIT;
