-- 旧 RAG 知识库完全移除（issue #3051：LLM WIKI 完全替代，决策 D1 巩固）
-- 删除顺序：rag_chunks 外键引用 knowledge_documents → 先删 rag_chunks，再删 knowledge_documents；knowledge_sync_history 独立
-- 旧知识由 knowledge_entries（词条）+ knowledge_candidates（提炼候选）替代，见 V35。
DROP TABLE IF EXISTS rag_chunks;
DROP TABLE IF EXISTS knowledge_documents;
DROP TABLE IF EXISTS knowledge_sync_history;
