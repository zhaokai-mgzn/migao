package com.migao.admin.migration;

// case_ids: PG-018

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 生产报工迁移契约（V49，issue #3995，M4-G-2）
 *
 * 守三条会被下一位验收者重开的判据：
 *   ① 四张表 + 索引齐备（迁移与 docs/sql/schema.sql 双源同口径）；
 *   ② `processing_orders.qr_token` 走 ADD COLUMN IF NOT EXISTS（存量库必须可重复执行）
 *      + 部分唯一索引只约束 deleted=0（软删后 token 释放可复用）；
 *   ③ 报工三态语义写在 SQL 注释里（normal/rework/scrap、必完工序、二维码 token），
 *      防「DB 层是权威但没人知道字段什么意思」。
 *
 * 写法沿用同目录 OrderLogisticsShipperNameMigrationTest（直接断言迁移 SQL 文本）。
 */
@DisplayName("生产报工迁移契约（V49 四表 + qr_token + 中文语义注释）")
class ProductionReportingMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql";
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
    @DisplayName("V49 建四张表：工序库/工艺路线模板/工序实例/报工记录")
    void v49CreatesFourTables() throws Exception {
        String sql = read(MIGRATION).toLowerCase();
        assertThat(sql).contains("create table if not exists production_operations");
        assertThat(sql).contains("create table if not exists production_routings");
        assertThat(sql).contains("create table if not exists processing_position_operations");
        assertThat(sql).contains("create table if not exists production_work_logs");
        // 部分唯一索引：软删后可重建同名工序 / 同部位×工艺路线
        assertThat(sql).contains("uk_production_operations_tenant_name");
        assertThat(sql).contains("uk_production_routings_tenant_type_craft");
        assertThat(sql).contains("where deleted = 0");
    }

    @Test
    @DisplayName("qr_token 走 ADD COLUMN IF NOT EXISTS + 部分唯一索引（存量库可重复执行）")
    void qrTokenIsIdempotentAndPartialUnique() throws Exception {
        String sql = read(MIGRATION);
        int at = sql.indexOf("ADD COLUMN IF NOT EXISTS qr_token");
        assertThat(at).as("V49 应含 qr_token 加列语句").isGreaterThanOrEqualTo(0);
        String stmt = sql.substring(at, sql.indexOf(';', at));
        assertThat(stmt).as("qr_token 为 32 位 UUID 去横线，VARCHAR(64) 足够").contains("VARCHAR(64)");

        int idx = sql.indexOf("uk_processing_orders_qr_token");
        assertThat(idx).as("qr_token 需要唯一索引").isGreaterThanOrEqualTo(0);
        String indexStmt = sql.substring(idx, sql.indexOf(';', idx));
        assertThat(indexStmt).as("唯一性只约束未软删行（软删后 token 释放）")
                .contains("deleted = 0").contains("qr_token IS NOT NULL");
    }

    @Test
    @DisplayName("报工三态与必完工序语义写在 SQL 注释里（DB 层是权威）")
    void semanticsAreDocumented() throws Exception {
        String sql = read(MIGRATION);
        assertThat(sql).contains("normal 正常 / rework 返工 / scrap 报废");
        assertThat(sql).contains("必完工序");
        assertThat(sql).contains("扫码报工入口");
        // bootstrap 同步：schema.sql 也必须有这四张表 + qr_token 列（CI 起栈用的是它）
        String schema = read(SCHEMA);
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS production_operations");
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS production_routings");
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS processing_position_operations");
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS production_work_logs");
        assertThat(schema).contains("qr_token VARCHAR(64)");
    }
}
