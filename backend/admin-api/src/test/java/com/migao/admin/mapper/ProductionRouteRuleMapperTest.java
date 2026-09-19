package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteRule;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionRouteRuleMapper 契约测试（issue #4423 P2 / #4432，V72）。
 *
 * 验证：表映射 `production_route_rules` + 实体字段与 `docs/sql/schema.sql` 终态收敛。
 * 为什么必须有（门禁口径）：新增 Mapper 缺契约测试 ⇒ QA Growth Gate **阻塞合并**；
 * 且实体↔schema 漂移会让建库后相关接口 **500**（`test_schema_covers_entity_columns` 的互补项）。
 */
@DisplayName("ProductionRouteRuleMapper 表/字段契约（production_route_rules）")
class ProductionRouteRuleMapperTest {

    @Test
    @DisplayName("实体映射 production_route_rules 表")
    void entityMapsToTable() {
        TableName tableName = ProductionRouteRule.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_route_rules");
    }

    @Test
    @DisplayName("实体字段与 schema.sql 终态列收敛")
    void entityFieldsMatchSchema() {
        List<String> fields = Arrays.stream(ProductionRouteRule.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "triggerKind", "triggerValue", "position", "action", "operation", "afterOperation", "priority", "status", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(
                "backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql",
                "production_route_rules",
                "id", "tenant_id", "trigger_kind", "trigger_value", "position", "action", "operation", "after_operation", "priority", "status", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("V72 的 factor 列（ALTER ADD COLUMN ⇒ 不在 CREATE TABLE 体，单独断言）")
    void factorColumnAddedByAlter() {
        // 计件系数档（`一分为二 ×1.7`）在 V72 里以 ALTER 形式补到规则表 ——
        // 实体字段断言已覆盖 `factor`；此处钉住「它确实被加进 schema 终态」，防两源漂移。
        String schema = ProductionMigrationSql.read("docs/sql/schema.sql");
        assertThat(schema).contains("ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS factor");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionRouteRuleMapper.class)).isTrue();
    }
}
