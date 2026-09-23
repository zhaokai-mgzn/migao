-- 知识单元统一命名：知识词条 → 知识卡片（issue #3051 产品语言对齐，全链路改名）
-- 背景：knowledge_entries 由 V35 创建；本迁移仅重命名表与索引（V37 > V36，顺序执行）。
-- 兼容性：ALTER TABLE IF EXISTS / ALTER INDEX IF EXISTS 对「已应用 V35」与「全新库」均幂等。
ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards;
ALTER INDEX IF EXISTS idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant;
ALTER INDEX IF EXISTS idx_knowledge_entries_status RENAME TO idx_knowledge_cards_status;
ALTER INDEX IF EXISTS idx_knowledge_entries_category RENAME TO idx_knowledge_cards_category;
