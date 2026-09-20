// case_ids: PG-020
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionInstanceRepricingLog;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 未定价实例补价动作账契约测试（V94，issue #4709 C）。
 *
 * <p>守三条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>三源收敛</b>：实体字段 ↔ V94 迁移 ↔ {@code docs/sql/schema.sql}
 *       （bootstrap 路径**不跑迁移链** ⇒ 只写迁移不写 schema.sql 会让全新库缺表 ⇒ 补价端点 500）；</li>
 *   <li><b>幂等</b>：{@code CREATE TABLE/INDEX IF NOT EXISTS}（bootstrap-first 会让迁移在建好终态的库上再跑一遍）；
 *       <b>且不回填任何存量行</b>（补价是**商家的动作**，迁移静默改价正是本 issue 要治的「无人知道」形态）；</li>
 *   <li><b>留痕可回滚可判</b>：外键挂到真实实例行（不会留下孤儿账）+ 索引按
 *       {@code (tenant_id, batch_id)}（按批回滚）+ {@code rolled_back_at IS NULL} 谓词（重复回滚幂等）。</li>
 * </ol>
 */
@DisplayName("未定价实例补价动作账/实体契约（V94，issue #4709 C）")
class ProductionInstanceRepricingLogMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V94__create_instance_repricing_logs.sql";

    @Test
    @DisplayName("实体映射 production_instance_repricing_logs 表")
    void entityMapsToTable() {
        TableName tableName = ProductionInstanceRepricingLog.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_instance_repricing_logs");
    }

    @Test
    @DisplayName("实体字段 ↔ V94 迁移 ↔ schema.sql 三源收敛（列名逐条一致）")
    void entityFieldsMatchMigrationAndSchema() {
        List<String> fields = Arrays.stream(ProductionInstanceRepricingLog.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("id", "tenantId", "batchId", "processingOrderId",
                "positionOperationId", "newUnitPrice", "createdAt", "rolledBackAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, "production_instance_repricing_logs",
                "id", "tenant_id", "batch_id", "processing_order_id", "position_operation_id",
                "new_unit_price", "created_at", "rolled_back_at", "deleted");
    }

    @Test
    @DisplayName("V94 幂等：建表/建索引 IF NOT EXISTS + **不回填任何存量行**（补价必须是商家的动作）")
    void migrationIsIdempotentAndDoesNotBackfill() {
        String sql = ProductionMigrationSql.read(MIGRATION);
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS production_instance_repricing_logs");
        assertThat(sql).contains("CREATE INDEX IF NOT EXISTS idx_instance_repricing_batch");
        assertThat(sql).contains("CREATE INDEX IF NOT EXISTS idx_instance_repricing_operation");
        // 迁移不得改任何存量数据（UPDATE/DELETE/INSERT 全禁）——「静默补价」正是本 issue 要治的形态
        assertThat(sql).doesNotContain("UPDATE processing_position_operations");
        assertThat(sql).doesNotContain("DELETE FROM");
        assertThat(sql).doesNotContain("INSERT INTO");
    }

    @Test
    @DisplayName("留痕可判：外键挂实例行/加工单 + 按批索引 + 只索引未软删行")
    void ledgerIsAuditable() {
        String sql = ProductionMigrationSql.read(MIGRATION);
        assertThat(sql).contains("REFERENCES processing_position_operations(id)");
        assertThat(sql).contains("REFERENCES processing_orders(id)");
        assertThat(sql).contains("(tenant_id, batch_id)");
        assertThat(sql).contains("WHERE deleted = 0");
    }

    @Test
    @DisplayName("回滚留痕谓词：`rolled_back_at IS NULL`（重复回滚幂等，不刷新时间戳）")
    void markRolledBackIsIdempotent() throws Exception {
        Method method = ProductionInstanceRepricingLogMapper.class.getMethod(
                "markRolledBack", String.class, Long.class, java.time.OffsetDateTime.class);
        String sql = String.join(" ", method.getAnnotation(Update.class).value());
        assertThat(sql).contains("SET rolled_back_at");
        assertThat(sql).contains("rolled_back_at IS NULL");
        assertThat(sql).contains("id = #{id}");
        assertThat(sql).contains("tenant_id = #{tenantId}");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionInstanceRepricingLogMapper.class)).isTrue();
    }
}
