-- 对齐 bootstrap 建库脚本与迁移链的最终状态（issue #3270）
--
-- ## 背景
-- `docs/sql/schema.sql` 是**全新库 bootstrap** 脚本（docker-compose 的
-- `docker-entrypoint-initdb.d/001_schema.sql` 与 CI 本地栈都用它），不是增量迁移源。
-- 存量库的表结构由 V1~V38 迁移链负责，二者应当收敛到**同一最终状态**。
--
-- issue #3270 实测发现 bootstrap 脚本无法执行（`psql -v ON_ERROR_STOP=1` exit 3）：
--   * `product_processing_items` 前向引用尚未创建的 `processing_items`
--   * `idx_knowledge_cards_*` 三个索引误写成 `ON knowledge_entries`
--   * `rag_chunks` / `knowledge_documents` / `knowledge_sync_history` 已由 V36 删除，
--     但脚本里仍残留其 `COMMENT` / RLS / `POLICY` 语句
-- → postgres 容器 `exited (3)` → 整个本地/CI docker 栈起不来
-- → C 端小布验收 workflow 自 2026-08-31 起 9/9 全 failure。
--
-- 这些缺陷**只存在于 bootstrap 脚本**：存量库经 V35（建 knowledge_entries）→
-- V36（删旧 RAG 表）→ V37（重命名为 knowledge_cards + 索引改名）已处于正确状态。
-- 故本迁移对存量库通常为 **no-op**，其价值是：
--   1. 声明并保证「迁移链产出」与「bootstrap 快照」收敛到同一状态（防再次漂移）；
--   2. 兜住 V35 索引可能缺失/命名异常的库（幂等补齐）。
--
-- ## 幂等性
-- 全部语句幂等（IF NOT EXISTS / IF EXISTS），符合 MigrationRunner 的
-- 「所有 SQL 文件必须幂等」约定；可在「bootstrap 库」与「存量库」上重复执行。

-- 1) 补齐 knowledge_cards 的三个检索索引（V35 建、V37 改名；此处兜底）
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_tenant ON knowledge_cards(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_status ON knowledge_cards(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_cards_category ON knowledge_cards(category);

-- 2) 清理已由 V36 删除的旧 RAG 知识库表可能残留的索引（幂等；通常为 no-op）
DROP INDEX IF EXISTS idx_rag_chunks_tenant;
DROP INDEX IF EXISTS idx_knowledge_sync_history_tenant;
