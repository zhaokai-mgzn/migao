-- =====================================================================
-- V42: 知识表名收敛（bootstrap-first 库的幂等收口）
-- =====================================================================
-- 背景（issue #3270 实测）：`docs/sql/schema.sql` 提供的是迁移链的**终态**
-- （已含 `knowledge_cards`），而迁移链本身是「V35 建 knowledge_entries → V37 改名
-- 为 knowledge_cards」。于是 bootstrap-first 库（schema.sql 已建 knowledge_cards）
-- 再跑迁移链时：
--     V35 建出 knowledge_entries（与终态重名无关，正常）
--     V37 `ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards`
--         → 目标已存在 → 报错（MigrationRunner 现已改为**跳过并继续**，不再冻结整链）
-- 结果：终态正确，但库里多出一张孤儿表 `knowledge_entries`，且每次启动留一行
-- 无意义的 ERROR（长期掩盖真问题的正是这种噪音 —— V28 那类真失败曾因此无人发现）。
--
-- 本迁移做幂等收口（两个方向都覆盖）：
--   1) 只有 knowledge_entries、没有 knowledge_cards（V37 从未成功过的老库）→ 改名；
--   2) 两者都在（bootstrap-first + V35 已建的形态）→ 丢弃孤儿 knowledge_entries。
--
-- 幂等：全部 IF EXISTS / 条件判断，可重复执行。
-- =====================================================================

DO $$
DECLARE
    has_entries BOOLEAN;
    has_cards   BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = 'knowledge_entries'
    ) INTO has_entries;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = 'knowledge_cards'
    ) INTO has_cards;

    IF has_entries AND NOT has_cards THEN
        -- 老库：V37 未成功过 → 补上改名（含索引改名，与 V37 语义一致）
        ALTER TABLE knowledge_entries RENAME TO knowledge_cards;
        RAISE NOTICE 'V42: knowledge_entries → knowledge_cards（补 V37）';
    ELSIF has_entries AND has_cards THEN
        -- bootstrap-first：终态已存在，knowledge_entries 是 V35 留下的孤儿
        DROP TABLE knowledge_entries;
        RAISE NOTICE 'V42: 丢弃孤儿表 knowledge_entries（终态 knowledge_cards 已存在）';
    ELSE
        RAISE NOTICE 'V42: 无需处理（knowledge_entries 不存在）';
    END IF;
END $$;

-- 索引名收敛（与 V37 的三条改名为同一目标；IF EXISTS 保证幂等）
ALTER INDEX IF EXISTS idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant;
ALTER INDEX IF EXISTS idx_knowledge_entries_status RENAME TO idx_knowledge_cards_status;
ALTER INDEX IF EXISTS idx_knowledge_entries_category RENAME TO idx_knowledge_cards_category;

-- 终态索引兜底（无论走哪条分支都要有）
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_tenant ON knowledge_cards(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_status ON knowledge_cards(tenant_id, status);
