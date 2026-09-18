package com.migao.admin.mapper;

// case_ids: PG-031

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRoutingVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionRoutingVersionMapper 契约测试（工艺路线版本账，issue #4308，V60）
 *
 * <p>验证：表映射 {@code production_routing_versions} + 实体字段与迁移 V60 /
 * {@code docs/sql/schema.sql} **双源收敛**。</p>
 *
 * <p><b>为什么需要本文件</b>：路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**
 * （必完工序全绿）的唯一输入 —— 版本账的列一旦与实体漂移，{@code operations} 读到 null ⇒
 * 「这条路线昨天是什么样」答不出来（留痕形同虚设，且不会变红）。</p>
 */
@DisplayName("ProductionRoutingVersionMapper 表/字段契约（工艺路线版本账）")
class ProductionRoutingVersionMapperTest {

    @Test
    @DisplayName("实体映射 production_routing_versions 表")
    void entityMapsToTable() {
        TableName tableName = ProductionRoutingVersion.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_routing_versions");
    }

    @Test
    @DisplayName("实体字段与迁移 V60 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionRoutingVersion.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "routingId", "curtainType", "craft", "operations", "operationCount", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(ProductionRouteSignalMapperTest.V60,
                "production_routing_versions",
                "id", "tenant_id", "routing_id", "curtain_type", "craft", "operations",
                "operation_count", "created_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionRoutingVersionMapper.class)).isTrue();
    }
}
