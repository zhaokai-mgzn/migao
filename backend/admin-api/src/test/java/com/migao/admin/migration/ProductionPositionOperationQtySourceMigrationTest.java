package com.migao.admin.migration;

// case_ids: PG-022

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工序实例 {@code qty_source} 迁移契约（V57，issue #4208）
 *
 * 守三条会被下一位验收者重开的判据：
 *   ① 迁移走 {@code ADD COLUMN IF NOT EXISTS}（MigrationRunner 要求可重复执行），且列**可空**
 *      —— 存量行留 NULL 表示「本列引入之前的旧实例」，与 {@code fallback} 可区分（不回填、不猜）；
 *   ② bootstrap（{@code docs/sql/schema.sql}，CI/本地 docker 栈由 docker-entrypoint-initdb.d 执行、
 *      **不跑迁移链**）的终态里必须有同一列，否则新建库上该列不存在 → admin-api 查询 500
 *      （issue #3270 的实测根因形态）；
 *   ③ 三源收敛：迁移列 ↔ Java 实体字段 ↔ 落库语句（{@code ProductionService.instantiate} 必须真写它，
 *      否则「列存在但恒 NULL」= 兜底仍静默，本单要治的缺陷原样复发）。
 *
 * 红证（实现前）：V57 不存在 ⇒ ① 红；实体无 {@code qtySource} ⇒ ③ 红（编译失败）。
 */
@DisplayName("工序实例 qty_source 迁移契约（V57，issue #4208）")
class ProductionPositionOperationQtySourceMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V57__add_qty_source_to_position_operations.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";
    private static final String ENTITY =
            "backend/admin-api/src/main/java/com/migao/admin/entity/ProcessingPositionOperation.java";
    private static final String SERVICE =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java";
    private static final String TABLE = "processing_position_operations";

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录");
    }

    private static String read(String relative) throws Exception {
        return Files.readString(repoRoot().resolve(relative), StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("V57 用 ADD COLUMN IF NOT EXISTS 增列 qty_source，且列可空（存量行 NULL ≠ fallback）")
    void migrationAddsNullableColumnIdempotently() throws Exception {
        String sql = read(MIGRATION);

        assertThat(sql).contains("ALTER TABLE " + TABLE);
        assertThat(Pattern.compile("ADD\\s+COLUMN\\s+IF\\s+NOT\\s+EXISTS\\s+qty_source\\s+VARCHAR\\(32\\)",
                        Pattern.CASE_INSENSITIVE).matcher(sql).find())
                .as("必须 IF NOT EXISTS（可重复执行）+ VARCHAR(32)")
                .isTrue();
        assertThat(sql).as("存量行留 NULL 表示旧实例 ⇒ 不得 NOT NULL / 不得 DEFAULT 回填")
                .doesNotContain("qty_source VARCHAR(32) NOT NULL")
                .doesNotContain("qty_source VARCHAR(32) DEFAULT");
        assertThat(sql).as("列语义必须写在 SQL 注释里（DB 是权威但没人知道字段什么意思）")
                .contains("COMMENT ON COLUMN " + TABLE + ".qty_source")
                .contains("fallback");
    }

    @Test
    @DisplayName("bootstrap 终态：docs/sql/schema.sql 的 processing_position_operations 含 qty_source")
    void bootstrapSchemaCarriesTheColumn() throws Exception {
        String sql = read(SCHEMA);
        int at = sql.toLowerCase().indexOf("create table if not exists " + TABLE);
        assertThat(at).as("schema.sql 应有 %s 建表语句", TABLE).isGreaterThanOrEqualTo(0);
        String body = sql.substring(sql.indexOf('(', at), sql.indexOf("\n);", at));
        assertThat(Pattern.compile("(?m)^\\s*qty_source\\s+VARCHAR\\(32\\)").matcher(body).find())
                .as("新建库（bootstrap 路径不跑迁移链）必须有该列，否则查询 500（#3270 形态）")
                .isTrue();
    }

    @Test
    @DisplayName("三源收敛：实体字段 + 落库语句都真带 qty_source（列存在但恒 NULL = 兜底仍静默）")
    void entityAndInsertBothCarryQtySource() throws Exception {
        assertThat(read(ENTITY))
                .as("实体必须声明 qtySource（MyBatis-Plus 按字段名映射列名）")
                .contains("private String qtySource;");
        String service = read(SERVICE);
        assertThat(service).as("实例化落库必须真写该列").contains(".qtySource(spec.qtySource())");
        assertThat(service).as("请求体里的 qty_source 必须被解析（否则落库恒 NULL）")
                .contains("str(op.get(\"qty_source\"))");
        assertThat(service).as("幂等比较的字段集 = 落库字段集（新增列不进签名 ⇒ 配置漂移检测不到）")
                .contains("orDash(qtySource)");
    }
}
