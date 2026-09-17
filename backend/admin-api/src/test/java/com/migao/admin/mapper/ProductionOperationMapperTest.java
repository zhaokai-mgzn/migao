package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionOperationMapper 契约测试（生产工序库，issue #3995，V49）
 * 验证：表映射 production_operations + 实体字段与迁移 V49 / docs/sql/schema.sql 收敛。
 */
@DisplayName("ProductionOperationMapper 表/字段契约（工序库）")
class ProductionOperationMapperTest {

    @Test
    @DisplayName("实体映射 production_operations 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOperation.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_operations");
    }

    @Test
    @DisplayName("实体字段与迁移 V49 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionOperation.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "name", "groupName", "position", "unit", "unitPrice",
                "isMustFinish", "isStartMarker", "sortOrder", "status", "deleted"
        );
        ProductionMigrationSql.assertTableColumns("production_operations",
                "id", "tenant_id", "name", "group_name", "position", "unit", "unit_price",
                "is_must_finish", "is_start_marker", "sort_order", "status",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionOperationMapper.class)).isTrue();
    }
}
