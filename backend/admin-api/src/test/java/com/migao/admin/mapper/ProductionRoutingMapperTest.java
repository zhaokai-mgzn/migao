package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouting;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionRoutingMapper 契约测试（工艺路线模板，issue #3995，V49）
 * 验证：表映射 production_routings + 实体字段与迁移 V49 / docs/sql/schema.sql 收敛。
 */
@DisplayName("ProductionRoutingMapper 表/字段契约（工艺路线模板）")
class ProductionRoutingMapperTest {

    @Test
    @DisplayName("实体映射 production_routings 表")
    void entityMapsToTable() {
        TableName tableName = ProductionRouting.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_routings");
    }

    @Test
    @DisplayName("实体字段与迁移 V49 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionRouting.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "curtainType", "craft", "operations", "status", "deleted"
        );
        ProductionMigrationSql.assertTableColumns("production_routings",
                "id", "tenant_id", "curtain_type", "craft", "operations", "status",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionRoutingMapper.class)).isTrue();
    }
}
