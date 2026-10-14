// case_ids: PG-018
package com.migao.admin.migration;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 加工单级短码的迁移契约（V155，issue #6867 / B1）。
 *
 * <p>写法沿用同目录 {@code InboundLabelMigrationTest}：直接断言迁移 SQL 文本 —— 本仓的
 * {@code MigrationRunner} 按**文件名**记台账（已应用的文件整份跳过）⇒ 迁移写错了
 * **永远不会再执行**、也永远不会变红，文本级判据是这里唯一能提前发现问题的位置。</p>
 *
 * <h3>四条判据（每条对着一个真实缺陷形态）</h3>
 * <ol>
 *   <li><b>幂等 + 显式事务</b>：{@code MigrationRunner} 要求所有迁移可重复执行；</li>
 *   <li><b>部分唯一索引齐备且谓词完整</b>：谓词漏 {@code deleted = 0} ⇒ 软删行占位；
 *       漏 {@code short_code IS NOT NULL} ⇒ 一堆 NULL 互不冲突，索引看着在但**对未分配行零约束力**；</li>
 *   <li><b>本迁移只建列与索引</b>：不得回填（在 DB 里批量造码 = 绕开 {@code allocateUnique} 的查重，
 *       等于第二份分配器）；不得碰 {@code qr_token} / {@code processing_set_part_tokens}（两个码空间）；</li>
 *   <li><b>终态同步</b>：{@code db/init/schema.sql} 必须体现同一终态（新建库不跑迁移链）。</li>
 * </ol>
 */
@DisplayName("加工单级短码迁移契约（V155，issue #6867）：加一列 + 跨租户部分唯一索引 + 终态同步")
class ProductionOrderShortCodeMigrationTest {

    private static final String V155 = "backend/admin-api/src/main/resources/db/migration/"
            + "V155__add_short_code_to_processing_orders.sql";
    private static final String SCHEMA_SQL = "backend/admin-api/src/main/resources/db/init/schema.sql";

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    private static String read(String relative) throws IOException {
        Path root = findRepoRoot();
        if (root == null) {
            throw new IOException("找不到仓库根目录: " + relative);
        }
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    /** 剥掉 SQL 的 `--` 行注释（判据只看语句；注释是解释，不是实现）。 */
    private static String stripSqlComments(String sql) {
        StringBuilder sb = new StringBuilder();
        for (String line : sql.split("\n", -1)) {
            int idx = line.indexOf("--");
            sb.append(idx >= 0 ? line.substring(0, idx) : line).append('\n');
        }
        return sb.toString();
    }

    @Test
    @DisplayName("V155 在活目录里，且显式 BEGIN/COMMIT 包事务（幂等 DDL，两步都 IF NOT EXISTS）")
    void v155WrapsInExplicitTransactionAndIsIdempotent() throws IOException {
        String sql = read(V155);
        assertThat(sql).contains("BEGIN;").contains("COMMIT;");
        assertThat(sql.indexOf("BEGIN;")).isLessThan(sql.indexOf("COMMIT;"));
        assertThat(sql).contains("ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS short_code CHAR(8)");
        assertThat(sql).contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_short_code");
        // 只加一列 + 一条索引：不得顺手改别的表 / 别的列（本包是「码本体」，读面与入口是 B2/B3 的活）
        String statements = stripSqlComments(sql);
        assertThat(statements).doesNotContain("CREATE TABLE");
        assertThat(statements).doesNotContain("DROP COLUMN");
        assertThat(statements).doesNotContain("ALTER TABLE processing_set_part_tokens");
        assertThat(statements).doesNotContain("UPDATE processing_orders");
    }

    @Test
    @DisplayName("🔴 部分唯一索引谓词完整：跨租户全局唯一，且 deleted = 0 + short_code IS NOT NULL 两条都在")
    void v155DeclaresThePartialUniqueIndexWithFullPredicate() throws IOException {
        String sql = read(V155);
        assertThat(sql).contains("ON processing_orders (short_code)");
        // 与 uk_processing_orders_qr_token 逐字同款（照抄既有形态，不另创）
        assertThat(sql).contains("WHERE deleted = 0 AND short_code IS NOT NULL;");
        // 索引列**只有** short_code：加 tenant_id 就变成租户内唯一 ⇒ 「跨租户全局唯一」这条契约当场失效
        assertThat(sql).doesNotContain("ON processing_orders (tenant_id, short_code)");
        // 终态对账：谓词两条都要被 DO 块点名校验（否则「看着在、其实没钉住」不会被发现）
        assertThat(sql).contains("DO $$").contains("RAISE EXCEPTION");
        assertThat(sql).contains("information_schema.columns");
        assertThat(sql).contains("pg_indexes");
    }

    @Test
    @DisplayName("🔴 回滚路径是**可执行 SQL**（不是散文）：先摘索引、再删列")
    void v155RollbackPathIsExecutableSql() throws IOException {
        String sql = read(V155);
        assertThat(sql).contains("-- -- DROP INDEX IF EXISTS uk_processing_orders_short_code;");
        assertThat(sql).contains("-- -- ALTER TABLE processing_orders DROP COLUMN IF EXISTS short_code;");
    }

    @Test
    @DisplayName("🔴 终态同步：建库脚本必须有同一列 + 同一条部分唯一索引（新库不跑迁移链）")
    void v155IsMirroredInTheBootstrapSchema() throws IOException {
        String schema = read(SCHEMA_SQL);
        assertThat(schema).contains("short_code CHAR(8),");
        assertThat(schema).contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_orders_short_code");
        assertThat(schema).contains("WHERE deleted = 0 AND short_code IS NOT NULL;");
        // 位置与存量库一致：short_code 紧随 qr_token（迁移链里是 ADD COLUMN 追加 ⇒ 列序一致）
        assertThat(schema.indexOf("qr_token VARCHAR(64),")).isLessThan(schema.indexOf("short_code CHAR(8),"));
    }
}
