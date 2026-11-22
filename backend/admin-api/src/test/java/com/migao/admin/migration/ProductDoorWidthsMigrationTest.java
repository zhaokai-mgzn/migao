// case_ids: PR-017
package com.migao.admin.migration;

import com.baomidou.mybatisplus.annotation.TableField;
import com.migao.admin.entity.Product;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 门幅清单迁移契约（V214 / issue #9005）：<b>列 · 映射 · 回填 · 回滚</b>四件事同源。
 *
 * <h2>为什么需要这份静态判据（真库判据的补充，不是替代）</h2>
 * {@code ProductDoorWidthsRoundTripRealDbTest} 证的是「在 CI/本机的真 PG 上行为对」；
 * 本文件证的是「**脚本本身**具备四件在评审里必须能直接读到的事实」，而且它在
 * **没有 PG 的环境**里也跑（纯文本 + 反射）：
 * <ol>
 *   <li><b>幂等</b>：{@code ADD COLUMN IF NOT EXISTS} —— {@code MigrationRunner} 会在
 *       「schema.sql 已建出终态」的库上再跑一遍迁移链（bootstrap-first），
 *       裸 {@code ADD COLUMN} 会报 {@code column ... already exists} 让整份迁移回滚
 *       （issue #3615 的实证形态）；</li>
 *   <li><b>回填窄</b>：只填「空数组」行、从既有 {@code product_skus.door_width} 去重聚合
 *       —— 回填把存量改成可推导的真值，而不是编一个默认门幅；已有值一律不覆盖；</li>
 *   <li><b>回滚可执行</b>：脚本头部写明 {@code ALTER TABLE products DROP COLUMN IF EXISTS door_widths}
 *       （纯新增列、无外键/约束 ⇒ 回滚即回到 V213 终态）；</li>
 *   <li><b>终态同步 + 实体映射</b>：{@code db/init/schema.sql} 的 {@code products} 建表里有该列
 *       （否则 `test_migration_references_exist_in_schema` 与真库 bootstrap 两条路都会红），
 *       且 {@link Product} 上有同名列 + 与 {@code selling_methods}/{@code detail_images} 同款
 *       JSON typeHandler（否则「列有了、代码没映射」= 本 issue 的病灶原样复发）。</li>
 * </ol>
 *
 * <h2>红证</h2>
 * 改前：{@code V214__*door_widths*.sql} 不存在、{@code schema.sql} 无该列、{@link Product} 无该字段
 * ⇒ 三个判据各自红（判据 1/3/4）。映射被摘掉（删掉实体字段或 typeHandler）⇒ 判据 4 红。
 */
@DisplayName("门幅清单迁移契约（V214 / issue #9005）：列 · 映射 · 回填 · 回滚")
class ProductDoorWidthsMigrationTest {

    private static final String MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration";
    private static final String SCHEMA_SQL = "backend/admin-api/src/main/resources/db/init/schema.sql";

    // ══════════════════════════════════ 判据 1：脚本存在 + 幂等 + 回填窄 + 回滚可执行

    @Test
    @DisplayName("判据1：V214 存在，加列幂等（IF NOT EXISTS）+ JSONB 默认空数组 + 回滚语句在册")
    void v214AddsColumnIdempotently() throws IOException {
        String sql = read(v214Path());

        assertThat(sql)
                .as("加列必须 IF NOT EXISTS —— MigrationRunner 会在 schema.sql 终态库上重跑迁移链（issue #3615）")
                .contains("ADD COLUMN IF NOT EXISTS door_widths JSONB");
        assertThat(sql)
                .as("门幅清单与 selling_methods/detail_images 同风格：JSONB 数组默认空")
                .contains("DEFAULT '[]'::jsonb");
        assertThat(sql)
                .as("回滚方式必须在脚本头部可读（纯新增列 ⇒ DROP COLUMN；评审要能看到）")
                .contains("DROP COLUMN IF EXISTS door_widths");
        assertThat(sql)
                .as("列注释必须写清「与 SKU 派生口径的关系」，避免下一个人把它当权威")
                .contains("COMMENT ON COLUMN products.door_widths IS");
    }

    @Test
    @DisplayName("判据2：回填只覆盖空数组行、取自既有 SKU 去重集合（不编默认值、不覆盖已有声明）")
    void v214BackfillIsNarrow() throws IOException {
        String sql = read(v214Path());
        String executable = stripComments(sql);

        assertThat(executable)
                .as("回填的**真值来源**必须是既有 SKU 行（product_skus.door_width），不是常量")
                .contains("product_skus")
                .contains("door_width")
                .contains("DISTINCT");
        assertThat(executable)
                .as("只填空的行（存量清理），已有值不覆盖 —— 回填不许改写本次改动之后的真实声明")
                .contains("jsonb_array_length");
    }

    // ══════════════════════════════════ 判据 3：schema.sql 终态同步

    @Test
    @DisplayName("判据3：db/init/schema.sql 的 products 建表同步 door_widths（bootstrap 终态 = 迁移终态）")
    void schemaSqlHasDoorWidths() throws IOException {
        String schema = read(REPO.resolve(SCHEMA_SQL));
        int productsAt = schema.indexOf("CREATE TABLE products (");
        assertThat(productsAt).as("schema.sql 应有 products 建表语句").isGreaterThanOrEqualTo(0);
        int tableEnd = schema.indexOf(");", productsAt);
        String productsDdl = schema.substring(productsAt, tableEnd);

        assertThat(productsDdl)
                .as("products 建表必须含 door_widths（否则 bootstrap 出来的库没有该列，迁移又被 IF NOT EXISTS 跳过 ⇒ 静默缺列）")
                .contains("door_widths JSONB");
    }

    // ══════════════════════════════════ 判据 4：实体映射（列 ⇄ 字段 ⇄ JSON handler）

    @Test
    @DisplayName("判据4：Product 上有 doorWidths 字段，且 @TableField 走 JacksonTypeHandler（与 selling_methods 同款）")
    void entityMapsDoorWidthsWithJsonHandler() throws NoSuchFieldException {
        Field field = Product.class.getDeclaredField("doorWidths");
        TableField annotation = field.getAnnotation(TableField.class);

        assertThat(annotation)
                .as("@TableField 必须在场（需要 typeHandler；products 表开了 autoResultMap）")
                .isNotNull();
        assertThat(annotation.typeHandler().getName())
                .as("JSONB 列必须显式点名 JacksonTypeHandler —— Wrapper 的 .set(col,val) 拿不到字段 handler 时"
                        + "PG 会报 Can't infer the SQL type（issue #6961 真库实测）")
                .isEqualTo("com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler");
        assertThat(annotation.value().isEmpty() ? field.getName() : annotation.value())
                .as("列名映射：@TableField 未显式取名时按驼峰转下划线 = door_widths")
                .isEqualTo("doorWidths");
    }

    // ══════════════════════════════════ 装置

    private static final Path REPO = repoRoot();

    private static Path v214Path() throws IOException {
        List<Path> hits = new ArrayList<>();
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(REPO.resolve(MIGRATION_DIR),
                "V214__*door_width*.sql")) {
            for (Path path : stream) {
                hits.add(path);
            }
        }
        assertThat(hits)
                .as("应恰有 1 份 V214 门幅迁移（%s/V214__*door_width*.sql）；"
                        + "新增迁移后还要跑 python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger",
                        MIGRATION_DIR)
                .hasSize(1);
        return hits.get(0);
    }

    private static String stripComments(String sql) {
        StringBuilder out = new StringBuilder();
        for (String line : sql.split("\n")) {
            if (!line.trim().startsWith("--")) {
                out.append(line).append('\n');
            }
        }
        return out.toString();
    }

    private static String read(Path path) throws IOException {
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve(MIGRATION_DIR))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录（" + MIGRATION_DIR + " 不存在）");
    }
}
