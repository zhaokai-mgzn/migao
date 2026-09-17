package com.migao.admin.mapper;

// case_ids: PG-018

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 生产报工（V49，issue #3995）/ 库存台账（V53，issue #4055）SQL 契约测试支撑
 *
 * 把「Java 实体字段 ↔ 迁移列 ↔ bootstrap schema」三源收敛变成可执行断言：
 * 只写实体不写迁移、或迁移不同步 docs/sql/schema.sql 都会在此变红
 * （跨源漂移守卫 tests/unit_ci_workflows/test_schema_integrity.py 的用例级补充）。
 */
final class ProductionMigrationSql {

    static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql";
    static final String SCHEMA = "docs/sql/schema.sql";

    private ProductionMigrationSql() {
    }

    /** 仓库根（从测试工作目录逐级上溯） */
    static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录（backend/admin-api/... 不存在）");
    }

    static String read(String relative) {
        try {
            return Files.readString(repoRoot().resolve(relative), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /**
     * 断言 table 在「迁移 V49」与「docs/sql/schema.sql」两源里都存在，且 CREATE TABLE 体含全部列。
     * 列名按行首匹配（避免 `qty` 被 `done_qty` 这类子串误命中）。
     */
    static void assertTableColumns(String table, String... columns) {
        assertTableColumnsIn(MIGRATION, table, columns);
    }

    /**
     * 同上，但显式指定迁移文件（V53 库存台账等复用；避免为每个迁移复制一套读文件逻辑）。
     *
     * @param migration 仓库根相对的迁移路径
     */
    static void assertTableColumnsIn(String migration, String table, String... columns) {
        for (String source : new String[]{migration, SCHEMA}) {
            String body = createTableBody(read(source), table);
            assertThat(body).as("%s 缺少表 %s", source, table).isNotNull();
            for (String column : columns) {
                assertThat(Pattern.compile("(?m)^\\s*" + Pattern.quote(column) + "\\s+\\w").matcher(body).find())
                        .as("%s 的 %s 表缺少列 %s", source, table, column)
                        .isTrue();
            }
        }
    }

    /** 提取 `CREATE TABLE [IF NOT EXISTS] <table> ( ... );` 的表体；不存在返回 null。 */
    private static String createTableBody(String sql, String table) {
        String lower = sql.toLowerCase();
        int at = lower.indexOf("create table if not exists " + table.toLowerCase());
        if (at < 0) {
            at = lower.indexOf("create table " + table.toLowerCase());
        }
        if (at < 0) {
            return null;
        }
        int start = sql.indexOf('(', at);
        int end = sql.indexOf("\n);", start);
        return (start < 0 || end < 0) ? null : sql.substring(start, end);
    }
}
