package com.migao.admin.migration;

// case_ids: PG-018

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 报工计件快照迁移契约（V61，issue #4351，P0）
 *
 * <p>守三条会被下一位验收者重开的判据：
 * ① 两列真的落在 {@code production_work_logs} 上，且走 {@code ADD COLUMN IF NOT EXISTS}
 * （MigrationRunner 要求所有 SQL 可重复执行）；
 * ② **回填含软删实例** —— 存量报工里已经有指向软删实例的行（那正是本单要治的形态），
 * 过滤 {@code deleted = 0} 会把最需要救的那批历史报工留成 NULL ⇒ 钱照样消失；
 * ③ 三源同口径：迁移列 / {@code docs/sql/schema.sql} bootstrap 终态 / Java 实体字段
 * （schema 侧由 {@code TestSchemaCoversEntityColumns} 另行按实体守，本类只钉 SQL 文本）。</p>
 *
 * <p>写法沿用同目录 {@code ProductionReportingMigrationTest}（直接断言迁移 SQL 文本）。</p>
 */
@DisplayName("报工计件快照迁移契约（V61 unit_price/factor + 回填含软删 + 幂等）")
class ProductionWorkLogSnapshotMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V61__add_piecework_snapshot_to_work_logs.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve(MIGRATION).getParent())) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    private static String read(String relative) throws Exception {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        return Files.readString(root.resolve(relative), java.nio.charset.StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("V61 增两列且幂等（ADD COLUMN IF NOT EXISTS），存量行留 NULL 可区分")
    void v61AddsSnapshotColumnsIdempotently() throws Exception {
        String sql = read(MIGRATION);
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS unit_price NUMERIC(10,2)");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS factor NUMERIC(10,2)");
        assertThat(sql)
                .as("加列前必须点名目标表 —— 本列落在报工记录上，不是工序实例")
                .contains("ALTER TABLE production_work_logs");
        assertThat(sql)
                .as("NULL = 本列引入之前的存量行（聚合按实例回查兜底）—— 不回填成 0，0 会被读成「免费」")
                .doesNotContain("DEFAULT 0");
    }

    @Test
    @DisplayName("V61 回填存量报工：含软删实例（那正是本单要治的形态），只补 unit_price IS NULL 的行")
    void v61BackfillsLegacyRowsIncludingSoftDeletedInstances() throws Exception {
        String sql = read(MIGRATION);
        int at = sql.indexOf("UPDATE production_work_logs");
        assertThat(at).as("V61 应含存量回填语句").isGreaterThanOrEqualTo(0);
        String stmt = sql.substring(at, sql.indexOf(';', at));
        assertThat(stmt)
                .as("回填源 = 工序实例的生成时快照（V49 口径：改价不回溯既有实例）")
                .contains("processing_position_operations")
                .contains("o.unit_price");
        assertThat(stmt)
                .as("幂等：只补本列引入前的行，不覆盖已固化的快照")
                .contains("w.unit_price IS NULL");
        assertThat(stmt)
                .as("**不得**过滤 deleted —— 软删实例上的单价仍是「报工当时的价」，"
                        + "过滤掉会把最需要救的历史报工留成 NULL")
                .doesNotContain("deleted = 0");
        assertThat(stmt)
                .as("系数缺失按 1 处理（与聚合口径 op.getFactor() == null ? ONE 逐字一致）")
                .contains("COALESCE(o.factor, 1)");
    }

    @Test
    @DisplayName("bootstrap 同步：schema.sql 的 production_work_logs 含两列 + 语义注释（CI 起栈用的是它）")
    void bootstrapSchemaCarriesTheSnapshotColumns() throws Exception {
        String schema = read(SCHEMA);
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS production_work_logs");
        int at = schema.indexOf("CREATE TABLE IF NOT EXISTS production_work_logs");
        String table = schema.substring(at, schema.indexOf(");", at));
        assertThat(table).contains("unit_price NUMERIC(10,2)").contains("factor NUMERIC(10,2)");
        assertThat(schema)
                .as("两列的口径必须写进 DB 注释（防「DB 层是权威但没人知道字段什么意思」）")
                .contains("COMMENT ON COLUMN production_work_logs.unit_price")
                .contains("COMMENT ON COLUMN production_work_logs.factor");
    }
}
