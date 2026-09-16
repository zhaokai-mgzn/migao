package com.migao.admin.migration;

// case_ids: UI-040

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 发货人（order_logistics.shipper_name）迁移契约（issue #3768 判据 / #3818 收尾）
 *
 * 守的是一条**会被下一个验收者重开**的判据：存量已发货订单历史上从未采集发货人，
 * 所以 shipper_name 必须 **nullable** ——
 *   ① 加 NOT NULL 会让迁移在存量库上失败（或被迫回填假值）；
 *   ② 即便回填成功，纸面就会出现**伪造的经手人**，比留白更糟（发货单是纸质凭据）。
 *
 * 与 UI-040 的 data_check 同口径（#3818 裁定）：空值不靠 NOT NULL 兜底，而是
 * **纸面发货人栏显示「-」**（ShipmentDoc 侧由
 * frontend/admin-web/tests/unit/components/ShipmentDoc.test.tsx 守）。
 *
 * 写法沿用同目录 KnowledgeWikiMigrationTest：直接断言迁移 SQL 文本
 * （本仓库用自研 MigrationRunner，无 Flyway checksum 语义，只按文件名记录已执行）。
 */
@DisplayName("发货人迁移契约（V46 shipper_name 必须 nullable + schema.sql 同步）")
class OrderLogisticsShipperNameMigrationTest {

    private static final String MIGRATION_DIR =
            "backend/admin-api/src/main/resources/db/migration";
    private static final String V46 = MIGRATION_DIR + "/V46__add_order_logistics_shipper_name.sql";
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
    @DisplayName("V46 存在，且 shipper_name 加列语句不带 NOT NULL（存量 NULL 不得让迁移失败）")
    void v46_shipperNameColumnIsNullable() throws IOException {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        assertThat(Files.exists(root.resolve(V46))).as("应存在 V46 发货人迁移文件").isTrue();

        String sql = read(V46);
        int at = sql.indexOf("ADD COLUMN IF NOT EXISTS shipper_name");
        assertThat(at).as("V46 应含 shipper_name 加列语句").isGreaterThanOrEqualTo(0);

        // 只看这条语句本身（到分号为止），避免把文件里别的注释误判进来
        String stmt = sql.substring(at, sql.indexOf(';', at));
        assertThat(stmt).as("shipper_name 必须是 VARCHAR(64)").contains("VARCHAR(64)");
        assertThat(stmt)
                .as("存量已发货订单历史无发货人 ⇒ 必须 nullable，加 NOT NULL 会让迁移失败")
                .doesNotContain("NOT NULL");
    }

    @Test
    @DisplayName("docs/sql/schema.sql 同步：order_logistics.shipper_name 同样 nullable")
    void schemaSql_shipperNameIsNullable() throws IOException {
        String schema = read(SCHEMA_SQL);
        int at = schema.indexOf("shipper_name");
        assertThat(at).as("schema.sql 应含 order_logistics.shipper_name 列").isGreaterThanOrEqualTo(0);

        String line = schema.substring(at, schema.indexOf('\n', at));
        assertThat(line).as("shipper_name 必须是 VARCHAR(64)").contains("VARCHAR(64)");
        assertThat(line)
                .as("全量 schema 文档必须与迁移同口径：nullable")
                .doesNotContain("NOT NULL");
    }
}
