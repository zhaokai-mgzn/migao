package com.migao.admin.migration;

// case_ids=[PR-036]

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Locale;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 入库单迁移契约（V111，issue #5034）。
 *
 * <p>写法沿用同目录 {@code OrderLogisticsShipperNameMigrationTest}：直接断言迁移 SQL 文本
 * （本仓库用自研 {@code MigrationRunner}，无 Flyway checksum 语义，只按文件名记录已执行）。
 * 而迁移一旦被**按文件名**跳过，写错的东西**永远不会再执行**、也永远不会变红
 * ⇒ 文本级判据是这里唯一能提前发现问题的位置。</p>
 *
 * <p>守三条判据：</p>
 * <ol>
 *   <li><b>幂等</b>：{@code MigrationRunner} 要求所有迁移可重复执行 —— 每个 DDL 必须带
 *       {@code IF NOT EXISTS} 或「不存在才 ADD」的守卫，且显式 {@code BEGIN/COMMIT}
 *       （{@code psql -f} 默认逐条 autocommit，不显式包事务会留下半完成态）。</li>
 *   <li><b>存量成本不得回填</b>：{@code avg_cost} / {@code cost_amount} 必须**保持 NULL**（未知）——
 *       存量库存的成本没有任何真值来源，编一个 0 会被读成「成本为零」的真数据。
 *       ⇒ 迁移里**不得**出现给这两列赋 0 的 UPDATE。</li>
 *   <li><b>{@code reason} 放行 inbound</b>：漏了它 ⇒ 入库落台账当场违反 CHECK 约束（23514），
 *       功能全断且只在真实过账时暴露。</li>
 * </ol>
 */
@DisplayName("入库单迁移契约（V111 幂等 + 存量成本留 NULL + reason 放行 inbound）")
class InboundOrderMigrationTest {

    private static final String MIGRATION_DIR =
            "backend/admin-api/src/main/resources/db/migration";
    private static final String V111 =
            MIGRATION_DIR + "/V111__create_inbound_orders_and_batches.sql";
    private static final String SCHEMA_SQL = "docs/sql/schema.sql";

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

    private static String read(String relative) throws IOException {
        Path root = findRepoRoot();
        if (root == null) {
            throw new IOException("找不到仓库根目录: " + relative);
        }
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("V111 存在，且显式 BEGIN/COMMIT 包事务（两条执行路径同语义）")
    void v111WrapsInExplicitTransaction() throws IOException {
        String sql = read(V111);
        assertThat(sql).contains("BEGIN;").contains("COMMIT;");
        assertThat(sql.indexOf("BEGIN;")).isLessThan(sql.indexOf("COMMIT;"));
    }

    @Test
    @DisplayName("V111 幂等：建表带 IF NOT EXISTS、加列带 IF NOT EXISTS、约束用 pg_constraint 判据守卫")
    void v111IsIdempotent() throws IOException {
        String sql = read(V111);
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS inbound_orders");
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS inbound_order_items");
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS stock_batches");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS avg_cost");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS cost_amount");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS latest_batch_no");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS unit_cost");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS avg_cost_before");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS avg_cost_after");
        // 权限种子幂等
        assertThat(sql).contains("ON CONFLICT (role_id, permission_id) DO NOTHING");
    }

    @Test
    @DisplayName("存量成本**不得**被回填：迁移里没有给 avg_cost / cost_amount 赋 0 的 UPDATE")
    void v111DoesNotBackfillZeroCost() throws IOException {
        String sql = read(V111).toLowerCase(Locale.ROOT);
        // 0 会被读成「成本为零」的真数据 ⇒ 只允许 NULL（未知）。
        // 逐条扫 UPDATE 语句：任何针对 product_skus 的 UPDATE 都不得把这两列写成 0。
        for (String stmt : sql.split(";")) {
            String s = stmt.strip();
            if (!s.startsWith("update")) {
                continue;
            }
            boolean touchesCost = s.contains("avg_cost") || s.contains("cost_amount");
            if (!touchesCost) {
                continue;
            }
            assertThat(s)
                    .as("V111 不得回填存量成本（0 是假真值；存量成本必须留 NULL）")
                    .doesNotContain("avg_cost = 0")
                    .doesNotContain("cost_amount = 0");
        }
    }

    @Test
    @DisplayName("reason 约束放行 inbound，且覆盖既有三类（不放行 ⇒ 入库落台账当场 23514）")
    void v111AllowsInboundReason() throws IOException {
        String sql = read(V111);
        assertThat(sql).contains("ck_stock_ledger_reason");
        assertThat(sql).contains("'order', 'aftersales', 'manual', 'inbound'");
        // 终态对账里也必须显式校验「放行了 inbound」（判据漂移的停止条件）
        assertThat(sql).contains("reason 约束未放行 inbound");
    }

    @Test
    @DisplayName("docs/sql/schema.sql（新建库路径）已同步 V111 终态：三张新表 + 成本列 + inbound 约束")
    void schemaSqlIsSyncedWithV111() throws IOException {
        String schema = read(SCHEMA_SQL);
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS inbound_orders");
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS inbound_order_items");
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS stock_batches");
        assertThat(schema).contains("avg_cost NUMERIC(12,4)");
        assertThat(schema).contains("cost_amount NUMERIC(16,4)");
        assertThat(schema).contains("latest_batch_no VARCHAR(32)");
        assertThat(schema).contains("avg_cost_before NUMERIC(12,4)");
        assertThat(schema).contains("avg_cost_after NUMERIC(12,4)");
        assertThat(schema).contains("CONSTRAINT ck_stock_ledger_reason CHECK (reason IN ('order', 'aftersales', 'manual', 'inbound'))");
        // 批次号租户内唯一（防重号的安全网）
        assertThat(schema).contains("uk_stock_batches_no");
        assertThat(schema).contains("uk_inbound_orders_no");
    }
}
