package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPosition;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionOperationPositionMapper 契约测试（issue #4423 P2 / #4432，V72）。
 *
 * 验证：表映射 `production_operation_positions` + 实体字段与 `docs/sql/schema.sql` 终态收敛。
 * 为什么必须有（门禁口径）：新增 Mapper 缺契约测试 ⇒ QA Growth Gate **阻塞合并**；
 * 且实体↔schema 漂移会让建库后相关接口 **500**（`test_schema_covers_entity_columns` 的互补项）。
 */
@DisplayName("ProductionOperationPositionMapper 表/字段契约（production_operation_positions）")
class ProductionOperationPositionMapperTest {

    @Test
    @DisplayName("实体映射 production_operation_positions 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOperationPosition.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_operation_positions");
    }

    @Test
    @DisplayName("实体字段与 schema.sql 终态列收敛")
    void entityFieldsMatchSchema() {
        List<String> fields = Arrays.stream(ProductionOperationPosition.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "logicalName", "position", "unitPrice", "applicable", "status", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(
                "backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql",
                "production_operation_positions",
                "id", "tenant_id", "logical_name", "position", "unit_price", "applicable", "status", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionOperationPositionMapper.class)).isTrue();
    }
}
