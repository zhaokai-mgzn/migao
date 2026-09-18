package com.migao.admin.mapper;

// case_ids: PG-023

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOptionFactor;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionOptionFactorMapper 契约测试（特殊选项 → 计件系数，issue #4230，V59）
 *
 * 验证：表映射 {@code production_option_factors} + 实体字段与迁移 V59 / {@code docs/sql/schema.sql}
 * 双源收敛。{@code factor} 是**直接乘进计件工资**的列（Σ 合格数 × 单价 × 系数）——
 * 字段名/精度漂移就是发错钱，故单独钉住。
 */
@DisplayName("ProductionOptionFactorMapper 表/字段契约（特殊选项 → 计件系数）")
class ProductionOptionFactorMapperTest {

    @Test
    @DisplayName("实体映射 production_option_factors 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOptionFactor.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_option_factors");
    }

    @Test
    @DisplayName("实体字段与迁移 V59 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionOptionFactor.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "optionName", "operationName", "factor", "source", "deleted");
        // factor 必须是 BigDecimal（精度 NUMERIC(6,2)）—— 用 double 会引入 0.005 级取整漂移
        assertThat(ProductionOptionFactor.class.getDeclaredFields())
                .filteredOn(f -> "factor".equals(f.getName()))
                .singleElement()
                .satisfies(f -> assertThat(f.getType()).isEqualTo(java.math.BigDecimal.class));
        ProductionMigrationSql.assertTableColumnsIn(
                ProductionOptionRoutingMapperTest.V59,
                "production_option_factors",
                "id", "tenant_id", "option_name", "operation_name", "factor", "source",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionOptionFactorMapper.class)).isTrue();
    }
}
