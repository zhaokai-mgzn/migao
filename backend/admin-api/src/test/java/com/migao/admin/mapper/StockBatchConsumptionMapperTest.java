package com.migao.admin.mapper;

// case_ids: PR-056, PR-063

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockBatchConsumption;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 批次消耗台账的表/字段/SQL 契约（V116，issue #5145 阶段 1）。
 *
 * <p>三条会被下一个验收者重开的判据：</p>
 * <ol>
 *   <li><b>幂等闸唯一索引必须在</b>：漏了它「重复生成加工单不会二次扣减」这条判据
 *       只靠上游 {@code uk_processing_orders_active} 一条网，而本表的扣减行一旦重复，
 *       余量与分布会静默偏小；</li>
 *   <li><b>{@code reason} 约束必须同时放行扣减与回补</b>：漏了回补取值 ⇒ 作废回补当场
 *       23514 违反约束 ⇒「对称回补」整条判据不成立；</li>
 *   <li><b>{@code order_item_id} 宽度必须与 {@code order_items.id} 一致</b>：它是
 *       {@code ASSIGN_UUID} 主键（VARCHAR(36)），写成 BIGINT 会在真实库上插入失败
 *       （单测全绿、生产全挂的那一类）。</li>
 * </ol>
 */
@DisplayName("StockBatchConsumptionMapper 表/字段契约（批次消耗台账）")
class StockBatchConsumptionMapperTest {

    private static final String V116 =
            "backend/admin-api/src/main/resources/db/migration-archive/V116__create_stock_batch_consumptions.sql";
    private static final String V119 =
            "backend/admin-api/src/main/resources/db/migration-archive/V119__add_cutting_plan_meters_to_batch_consumptions.sql";
    private static final String SCHEMA = "backend/admin-api/src/main/resources/db/init/schema.sql";
    private static final Path MIGRATION_DIR =
            ProductionMigrationSql.repoRoot().resolve("backend/admin-api/src/main/resources/db/migration-archive");

    @Test
    @DisplayName("实体映射 stock_batch_consumptions 表")
    void entityMapsToTable() {
        TableName tableName = StockBatchConsumption.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("stock_batch_consumptions");
    }

    @Test
    @DisplayName("实体字段与 V116 列收敛（批次/余量前后值/delta/reason/三查询列/明细行 id）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(StockBatchConsumption.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "batchId", "batchNo", "productId", "skuId", "skuCode",
                "delta", "beforeQty", "afterQty", "reason", "processingOrderNo", "orderNo",
                "orderItemId", "operator", "note", "createdAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V116, "stock_batch_consumptions",
                "id", "tenant_id", "batch_id", "batch_no", "product_id", "sku_id", "sku_code",
                "delta", "before_qty", "after_qty", "reason", "processing_order_no", "order_no",
                "order_item_id", "operator", "note", "created_at", "deleted");
    }

    @Test
    @DisplayName("order_item_id 与 order_items.id 同宽（VARCHAR(36)）—— 写成 BIGINT 会在真库插入失败")
    void orderItemIdWidthMatchesOrderItems() {
        String sql = ProductionMigrationSql.read(V116);
        assertThat(sql).contains("order_item_id VARCHAR(36) NOT NULL");
        assertThat(sql).doesNotContain("order_item_id BIGINT");
    }

    @Test
    @DisplayName("幂等闸唯一索引必须在（漏了它 ⇒ 重复扣减不会被任何检查发现）")
    void idempotencyUniqueIndexExists() {
        String sql = ProductionMigrationSql.read(V116);
        assertThat(sql).contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_batch_consumption_line");
        assertThat(sql).contains(
                "ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason)");
    }

    @Test
    @DisplayName("三条查询索引必须在（按批次 / 加工单 / 订单都能查回来）")
    void lookupIndexesExist() {
        String sql = ProductionMigrationSql.read(V116);
        assertThat(sql).contains("idx_batch_consumptions_tenant_batch")
                .contains("idx_batch_consumptions_tenant_po")
                .contains("idx_batch_consumptions_tenant_order");
    }

    @Test
    @DisplayName("reason 约束同时放行扣减与回补（漏了回补 ⇒ 作废回补当场违反约束）")
    void reasonConstraintAllowsBothReasons() {
        String sql = ProductionMigrationSql.read(V116);
        assertThat(sql).contains("ck_batch_consumption_reason")
                .contains("'processing_order'")
                .contains("'processing_order_cancelled'");
        // 两个取值必须是**同一个** CHECK 的成员（分别出现在两句里也能过上面三条断言）
        assertThat(sql).matches("(?s).*CHECK \\(reason IN \\('processing_order', 'processing_order_cancelled'\\)\\).*");
    }

    @Test
    @DisplayName("V116 在且版本号集合无重复（迁移号撞车 = 有一条永远不会跑；**不**锁死「V116 是最高」）")
    void isUniqueHighestVersion() throws Exception {
        List<Integer> versions;
        try (Stream<Path> files = Files.list(MIGRATION_DIR)) {
            versions = files.map(p -> p.getFileName().toString())
                    .filter(n -> n.startsWith("V") && n.endsWith(".sql"))
                    .map(n -> n.substring(1, n.indexOf("__")))
                    .filter(v -> v.chars().allMatch(Character::isDigit))
                    .map(Integer::parseInt)
                    .sorted()
                    .toList();
        }
        assertThat(versions).contains(116);
        assertThat(versions.stream().filter(v -> v == 116).count()).isEqualTo(1);
        // ⚠️ 这里原写 `versions.get(size - 1) == 116`（「V116 是当前最大迁移号」）—— 那是本仓
        //    点名过的**自毁式真值主张**：下一个迁移一出现就必红，且报错文案指向错误行动
        //    （同族教训与改法见 tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py 与
        //    test_public_ops_v88_migration.py；issue #5148 新增 V117 时**实测踩中**）。
        //    判据本意（见方法名与 DisplayName）= 「**迁移号撞车 ⇒ 有一条永远不会跑**」⇒ 正确口径 =
        //    版本号在**本档及以后**无重复。为什么只查 `>= 116` 而不查全体：仓库存量里 V29 / V33
        //    各有两份（历史遗留，与本判据无关）⇒ 全量查重会对历史假红；而新增迁移只会出现在尾部。
        //    V116 自身的逐字节冻结另由 migration_fingerprints.json 的 sha256 账本守（此处不重复主张）。
        assertThat(versions.stream().filter(v -> v >= 116).toList()).doesNotHaveDuplicates();
    }

    @Test
    @DisplayName("V119：两个米数 + 当时均价三列在实体与迁移里都收敛（#5159 的「两个米数必须落库」）")
    void cuttingPlanMetersArePersisted() {
        List<String> fields = Arrays.stream(StockBatchConsumption.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("formulaMeters", "plannedMeters", "unitCost");
        // V119 是**加列**迁移（表在 V116 建）⇒ 判据看 ADD COLUMN 与 bootstrap 终态，不看 CREATE TABLE
        String sql = ProductionMigrationSql.read(V119);
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS formula_meters NUMERIC(12,1)")
                .contains("ADD COLUMN IF NOT EXISTS planned_meters NUMERIC(12,1)")
                .contains("ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,4)");
        // 两个米数**必填**（漏了它 ⇒ 「答不出省了多少」的账能静默落库）
        assertThat(sql).contains("ALTER COLUMN formula_meters SET NOT NULL")
                .contains("ALTER COLUMN planned_meters SET NOT NULL");
        // 历史行回填 = 改前口径（扣减行正、回补行负），且**不猜均价**
        assertThat(sql).contains("SET formula_meters = -delta").contains("planned_meters = -delta");
        assertThat(sql).doesNotContain("SET unit_cost");
    }

    @Test
    @DisplayName("V119：「只多不少」约束同时钉住 planned<=formula 与两列同号（漏后半句 ⇒ 符号打架的行能落库）")
    void planMetersInvariantIsEnforcedInSql() {
        String sql = ProductionMigrationSql.read(V119);
        assertThat(sql).contains("ck_batch_consumption_plan_meters")
                .contains("planned_meters <= formula_meters")
                .contains("formula_meters * planned_meters >= 0")
                .contains("ck_batch_consumption_unit_cost");
    }

    @Test
    @DisplayName("派生值不落库：saved_meters / saved_amount 由实体算（落库就是第三个会漂移的数）")
    void derivedSavingsAreNotPersisted() {
        List<String> fields = Arrays.stream(StockBatchConsumption.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).doesNotContain("savedMeters", "savedAmount");
        String sql = ProductionMigrationSql.read(V119);
        // ⚠️ 断言带 `ADD COLUMN` 前缀：迁移**注释**里会解释 saved_meters 这个派生口径（那是文档，不是落库）
        assertThat(sql).doesNotContain("ADD COLUMN IF NOT EXISTS saved_meters")
                .doesNotContain("ADD COLUMN IF NOT EXISTS saved_amount");
        // 派生口径可执行：formula 6 / planned 1.5 / 均价 12.5 ⇒ 省 4.5 米、56.25 元
        StockBatchConsumption row = StockBatchConsumption.builder()
                .formulaMeters(new BigDecimal("6")).plannedMeters(new BigDecimal("1.5"))
                .unitCost(new BigDecimal("12.5")).build();
        assertThat(row.getSavedMeters()).isEqualByComparingTo("4.5");
        assertThat(row.getSavedAmount()).isEqualByComparingTo("56.25");
        // 均价未知（历史行）⇒ 省钱数读不出（**不按 0 或现价折算**）
        assertThat(StockBatchConsumption.builder()
                .formulaMeters(new BigDecimal("6")).plannedMeters(new BigDecimal("6")).build()
                .getSavedAmount()).isNull();
    }

    @Test
    @DisplayName("bootstrap 终态同步：backend/admin-api/src/main/resources/db/init/schema.sql 也带三列与「只多不少」约束")
    void bootstrapSchemaMirrorsCuttingPlanMeters() {
        String schema = ProductionMigrationSql.read(SCHEMA);
        assertThat(schema).contains("formula_meters NUMERIC(12,1) NOT NULL")
                .contains("planned_meters NUMERIC(12,1) NOT NULL")
                .contains("unit_cost NUMERIC(12,4)")
                .contains("ck_batch_consumption_plan_meters");
    }

    @Test
    @DisplayName("V116 显式事务 + fail-closed 停止条件（psql -f 逐条 autocommit ⇒ 不写 BEGIN 会留半完成态）")
    void explicitTransactionAndFailClosed() {
        String sql = ProductionMigrationSql.read(V116);
        assertThat(sql).contains("BEGIN;").contains("COMMIT;");
        assertThat(sql).contains("information_schema.tables")
                .contains("RAISE EXCEPTION")
                .contains("ck_batch_consumption_reason")
                .contains("uk_batch_consumption_line");
    }

    @Test
    @DisplayName("bootstrap 终态同步：backend/admin-api/src/main/resources/db/init/schema.sql（新建库路径不跑迁移链）也建了该表")
    void bootstrapSchemaMirrorsTable() {
        String schema = ProductionMigrationSql.read(SCHEMA);
        assertThat(schema).contains("CREATE TABLE IF NOT EXISTS stock_batch_consumptions");
        assertThat(schema).contains("uk_batch_consumption_line");
    }

    @Test
    @DisplayName("id 为数据库自增；软删标 @TableLogic；Mapper 继承 BaseMapper")
    void idSoftDeleteAndBaseMapper() throws Exception {
        TableId tableId = StockBatchConsumption.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("AUTO");
        assertThat(StockBatchConsumption.class.getDeclaredField("deleted").getAnnotation(TableLogic.class))
                .as("deleted 必须标 @TableLogic").isNotNull();
        assertThat(BaseMapper.class.isAssignableFrom(StockBatchConsumptionMapper.class)).isTrue();
    }
}
