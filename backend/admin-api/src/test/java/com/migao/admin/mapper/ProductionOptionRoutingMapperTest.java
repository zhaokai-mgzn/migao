package com.migao.admin.mapper;

// case_ids: PG-023

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOptionRouting;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionOptionRoutingMapper 契约测试（特殊选项 → 条件工序，issue #4230，V59）
 *
 * 验证：表映射 {@code production_option_routings} + 实体字段与迁移 V59 / {@code docs/sql/schema.sql}
 * **双源收敛**（只写实体不写迁移、或迁移不同步 bootstrap 都会在此变红）。
 *
 * <p>为什么需要本文件：这两张表是「设计过但从未接线」的另一半 —— 列名与实体字段一旦漂移，
 * 实例化时 {@code afterOperation} 读到的就是 null ⇒ 条件工序静默退化成「追加到末尾」，
 * 而界面上看不出任何异常（正是本单要治的静默形态）。</p>
 */
@DisplayName("ProductionOptionRoutingMapper 表/字段契约（特殊选项 → 条件工序）")
class ProductionOptionRoutingMapperTest {

    @Test
    @DisplayName("实体映射 production_option_routings 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOptionRouting.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_option_routings");
    }

    @Test
    @DisplayName("实体字段与迁移 V59 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionOptionRouting.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "optionName", "operationName", "afterOperation", "sortOrder", "status", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(
                ProductionOptionRoutingMapperTest.V59,
                "production_option_routings",
                "id", "tenant_id", "option_name", "operation_name", "after_operation",
                "sort_order", "status", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionOptionRoutingMapper.class)).isTrue();
    }

    /** V59 迁移路径（两张表同迁移；本常量与 Factor 侧共用同一份字面量以避免两处漂移）。 */
    static final String V59 =
            "backend/admin-api/src/main/resources/db/migration/V59__create_production_option_tables.sql";
}
