package com.migao.admin.mapper;

// case_ids: PG-020

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 单价版本表契约测试（issue #4204，V55）
 *
 * 守三条会被下一位验收者重开的判据：
 *   ① 三源收敛：实体字段 ↔ V55 迁移 ↔ docs/sql/schema.sql（bootstrap 路径不跑迁移链，
 *      只写迁移不写 schema.sql ⇒ 全新库缺表 ⇒ PUT 端点 500）；
 *   ② 幂等：CREATE TABLE/INDEX IF NOT EXISTS + 回填按 NOT EXISTS 守卫
 *      （bootstrap-first 会让迁移在建好终态的库上再跑一遍）；
 *   ③ 「当前价 = 最新版本行」可判：索引按 (operation_id, created_at DESC) 且只索引未软删行。
 */
@DisplayName("单价版本表/实体契约（V55，issue #4204）")
class ProductionOperationPriceVersionMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V55__create_production_operation_price_versions.sql";

    @Test
    @DisplayName("实体映射 production_operation_price_versions 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOperationPriceVersion.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_operation_price_versions");
    }

    @Test
    @DisplayName("实体字段 ↔ V55 迁移 ↔ schema.sql 三源收敛（列名/列数逐条一致）")
    void entityFieldsMatchMigrationAndSchema() {
        List<String> fields = Arrays.stream(ProductionOperationPriceVersion.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "operationId", "unitPrice", "createdAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, "production_operation_price_versions",
                "id", "tenant_id", "operation_id", "unit_price", "created_at", "deleted");
    }

    @Test
    @DisplayName("V55 幂等：建表/建索引 IF NOT EXISTS + 回填 NOT EXISTS 守卫（bootstrap-first 可重复执行）")
    void migrationIsIdempotent() throws Exception {
        String sql = ProductionMigrationSql.read(MIGRATION);
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS production_operation_price_versions");
        assertThat(sql).contains("CREATE INDEX IF NOT EXISTS idx_op_price_versions_operation");
        // 回填初始版本：已有版本行的工序跳过（否则每次启动都追加一行重复版本）
        assertThat(sql).contains("NOT EXISTS");
        assertThat(sql).contains("ON CONFLICT (id) DO NOTHING");
        // 当前价 = 最新版本行：索引必须能按 operation_id 取最新（created_at DESC）+ 只算未软删
        assertThat(sql).contains("(operation_id, created_at DESC)");
        assertThat(sql).contains("WHERE deleted = 0");
        // 版本行必须挂在工序库行上（外键 = 不会留下指向不存在工序的孤儿版本）
        assertThat(sql).contains("REFERENCES production_operations(id)");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionOperationPriceVersionMapper.class)).isTrue();
    }
}
