package com.migao.admin.migration;

// case_ids: API-013, API-014

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 知识卡片迁移契约测试（LLM WIKI 板块 P1，issue #3051）
 *
 * 防「文档-代码状态漂移」（self-consistency-checklist P0-3）：
 * 1. V35 迁移创建 knowledge_entries，V37 重命名为 knowledge_cards；V35 创建 knowledge_candidates 全字段；
 * 2. docs/sql/schema.sql（全量 schema 文档）必须同步包含两张新表；
 * 3. 迁移用 CREATE TABLE IF NOT EXISTS（MigrationRunner 幂等，失败不阻塞启动）。
 */
@DisplayName("知识卡片迁移契约（V35 + V37 + schema.sql 同步）")
class KnowledgeWikiMigrationTest {

    private static final String MIGRATION_DIR =
            "backend/admin-api/src/main/resources/db/migration";
    private static final String SCHEMA_SQL = "docs/sql/schema.sql";

    private static String read(String relative) throws IOException {
        // 从仓库根目录解析（mvn 在模块目录运行时向上回溯）
        Path root = findRepoRoot();
        if (root == null) {
            throw new IOException("找不到仓库根目录: " + relative);
        }
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve(MIGRATION_DIR))) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    @Test
    @DisplayName("V35 迁移存在且幂等建表 knowledge_entries/knowledge_candidates")
    void v35Migration_createsBothTables() throws IOException {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        Path dir = root.resolve(MIGRATION_DIR);

        Path v35 = null;
        try (var stream = Files.list(dir)) {
            for (Path p : stream.toList()) {
                String name = p.getFileName().toString();
                if (name.startsWith("V35__") && name.contains("knowledge")) {
                    v35 = p;
                }
            }
        }
        assertThat(v35).as("应存在 V35__*knowledge* 迁移文件").isNotNull();

        String sql = Files.readString(v35, StandardCharsets.UTF_8);
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS knowledge_entries");
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS knowledge_candidates");

        // 知识卡片表核心列（契约 API-013）
        for (String col : new String[]{
                "tenant_id BIGINT", "title VARCHAR(255)", "source_type VARCHAR(32)",
                "answer TEXT", "status VARCHAR(32)", "version INTEGER",
                "reviewed_by VARCHAR(64)", "reviewed_at TIMESTAMP"}) {
            assertThat(sql).as("knowledge_entries 应含列: %s", col).contains(col);
        }
        // 候选表核心列（契约 API-014）
        for (String col : new String[]{
                "suggested_title VARCHAR(255)", "suggested_answer TEXT",
                "confidence NUMERIC", "evidence TEXT"}) {
            assertThat(sql).as("knowledge_candidates 应含列: %s", col).contains(col);
        }
        // 租户索引（V35 建表时为 entries 命名，V37 重命名为 cards）
        assertThat(sql).contains("idx_knowledge_entries_tenant");
        assertThat(sql).contains("idx_knowledge_candidates_tenant");
    }

    @Test
    @DisplayName("V36 迁移完全移除旧 RAG 知识库三表（替代闭环，issue #3051）")
    void v36Migration_dropsRagTables() throws IOException {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        Path dir = root.resolve(MIGRATION_DIR);

        Path v36 = null;
        try (var stream = Files.list(dir)) {
            for (Path p : stream.toList()) {
                String name = p.getFileName().toString();
                if (name.startsWith("V36__") && name.contains("knowledge")) {
                    v36 = p;
                }
            }
        }
        assertThat(v36).as("应存在 V36__*knowledge* 迁移文件").isNotNull();

        String sql = Files.readString(v36, StandardCharsets.UTF_8);
        // 删除顺序：rag_chunks（FK 引用 knowledge_documents）→ knowledge_documents → sync_history
        assertThat(sql).contains("DROP TABLE IF EXISTS rag_chunks");
        assertThat(sql).contains("DROP TABLE IF EXISTS knowledge_documents");
        assertThat(sql).contains("DROP TABLE IF EXISTS knowledge_sync_history");
    }


    @Test
    @DisplayName("V37 迁移：knowledge_entries → knowledge_cards（产品语言统一为知识卡片，issue #3051）")
    void v37Migration_renamesEntriesToCards() throws IOException {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        Path dir = root.resolve(MIGRATION_DIR);

        Path v37 = null;
        try (var stream = Files.list(dir)) {
            for (Path p : stream.toList()) {
                String name = p.getFileName().toString();
                if (name.startsWith("V37__") && name.contains("card")) {
                    v37 = p;
                }
            }
        }
        assertThat(v37).as("应存在 V37__*card* 迁移文件").isNotNull();

        String sql = Files.readString(v37, StandardCharsets.UTF_8);
        assertThat(sql).contains("ALTER TABLE IF EXISTS knowledge_entries RENAME TO knowledge_cards");
        assertThat(sql).contains("idx_knowledge_entries_tenant RENAME TO idx_knowledge_cards_tenant");
    }

    @Test
    @DisplayName("docs/sql/schema.sql 全量 schema 同步包含两张新表")
    void schemaSql_inSyncWithMigration() throws IOException {
        String schema = read(SCHEMA_SQL);
        assertThat(schema).as("schema.sql 应包含 knowledge_cards 建表")
                .contains("CREATE TABLE IF NOT EXISTS knowledge_cards");
        assertThat(schema).as("schema.sql 应包含 knowledge_candidates 建表")
                .contains("CREATE TABLE IF NOT EXISTS knowledge_candidates");
        assertThat(schema).as("schema.sql 应包含卡片租户索引")
                .contains("idx_knowledge_cards_tenant");
        assertThat(schema).as("schema.sql 应包含候选租户索引")
                .contains("idx_knowledge_candidates_tenant");
    }
}
