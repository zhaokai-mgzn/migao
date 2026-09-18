package com.migao.admin.mapper;

// case_ids: PG-030

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteSignal;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionRouteSignalMapper 契约测试（信号 → 路线键，issue #4308，V60）
 *
 * <p>验证：表映射 {@code production_route_signals} + 实体字段与迁移 V60 /
 * {@code docs/sql/schema.sql} **双源收敛**（只写实体不写迁移、或迁移不同步 bootstrap 都会在此变红）。</p>
 *
 * <p><b>为什么需要本文件</b>：这张表取代了迁移前的两个 Java 常量关键字表（{@code CURTAIN_TYPE_KEYWORDS}
 * / {@code CRAFT_KEYWORDS}）—— 列名与实体字段一旦漂移，派生时读到的就是 null ⇒ 路线键静默退化成
 * 默认 {@code 布帘×韩褶}（**正是本单要治的静默回落形态**，且这次连 incident 日志都不会有：
 * 表里明明有行、只是字段没映射上）。</p>
 */
@DisplayName("ProductionRouteSignalMapper 表/字段契约（信号 → 路线键）")
class ProductionRouteSignalMapperTest {

    /** V60 迁移路径（三张表/列同迁移；本常量与 Version 侧共用同一份字面量以避免两处漂移）。 */
    static final String V60 =
            "backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql";

    @Test
    @DisplayName("实体映射 production_route_signals 表")
    void entityMapsToTable() {
        TableName tableName = ProductionRouteSignal.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_route_signals");
    }

    @Test
    @DisplayName("实体字段与迁移 V60 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionRouteSignal.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "signal", "curtainType", "craft", "priority", "status", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V60, "production_route_signals",
                "id", "tenant_id", "signal", "curtain_type", "craft", "priority",
                "status", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionRouteSignalMapper.class)).isTrue();
    }
}
