-- 知识单元统一命名：知识词条 → 知识卡片（issue #3051 产品语言对齐，全链路改名）
-- 背景：knowledge_entries 由 V35 创建；本迁移仅重命名表与索引（V37 > V36，顺序执行）。
-- 兼容性修正（issue #3615，真库实测）：`ALTER TABLE ... IF EXISTS` 只守卫**源表**，
-- 不守卫**目标表**。bootstrap-first 库（`docs/sql/schema.sql` 已直接建终态 `knowledge_cards`）上：
--     V35 因 `IF NOT EXISTS` 空过（knowledge_entries 不存在）
--     → `ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards` 报
--       「关系 "knowledge_cards" 已经存在」→ 本文件整条回滚且**不写入 schema_migrations**
--     → 每次重启重跑再报一次 → admin-api 日志永久留「schema 可能与代码不一致（2 条迁移失败）」
--       噪音，掩盖真失败（本类噪音正是 issue #3270 复盘点名的归因污染源）。
-- 故表改名补**双向守卫**（目标表已存在 → 无需改名），照 V42 的 `DO $$` 范式
-- （PG 不支持 `ALTER TABLE IF NOT EXISTS`；索引改名同理用 `DO $$`，见下）。
-- 语义不变：首次执行（只有源表的老库）仍是改名；仅影响「目标表已存在」的重复执行路径。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = current_schema() AND table_name = 'knowledge_entries')
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = current_schema() AND table_name = 'knowledge_cards') THEN
        ALTER TABLE knowledge_entries RENAME TO knowledge_cards;
    END IF;
END $$;

-- 索引改名同理：`ALTER INDEX IF EXISTS` 也只守卫**源索引**，不守卫**目标索引名**。
-- bootstrap-first 库上 schema.sql 已建三条终态索引（idx_knowledge_cards_*），
-- 而 V35 在 knowledge_entries 上建了三条同名旧索引 → 改名报
-- 「关系 "idx_knowledge_cards_tenant" 已经存在」（实测；修好表改名后暴露的下一个同源缺陷）。
-- 照上块同一范式补双向守卫：源存在且目标不存在 → 才改名（三对写开，与仓库既有风格一致）。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
               AND relname = 'idx_knowledge_entries_tenant')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
                       AND relname = 'idx_knowledge_cards_tenant') THEN
        ALTER INDEX idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
               AND relname = 'idx_knowledge_entries_status')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
                       AND relname = 'idx_knowledge_cards_status') THEN
        ALTER INDEX idx_knowledge_entries_status RENAME TO idx_knowledge_cards_status;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
               AND relname = 'idx_knowledge_entries_category')
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'i'
                       AND relname = 'idx_knowledge_cards_category') THEN
        ALTER INDEX idx_knowledge_entries_category RENAME TO idx_knowledge_cards_category;
    END IF;
END $$;
